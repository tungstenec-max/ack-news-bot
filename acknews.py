#!/usr/bin/env python3
import meshtastic
from meshtastic.serial_interface import SerialInterface
from pubsub import pub
import requests
import xml.etree.ElementTree as ET
import re
import time
import threading
import queue
from datetime import datetime
import configparser
import os

# ============================================================
# LOAD CONFIG
# ============================================================
config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(__file__), "config.ini")
config.read(config_path)

SERIAL_PORT     = config.get("meshtastic", "serial_port", fallback="/dev/ttyUSB0")
NEWS_API_KEY    = config.get("newsapi", "key", fallback="")
OLLAMA_MODEL    = config.get("bot", "ollama_model", fallback="llama3.2:3b")
OLLAMA_URL      = config.get("bot", "ollama_url", fallback="http://localhost:11434/api/generate")
NUM_STORIES     = config.getint("bot", "num_stories", fallback=3)
MESSAGE_DELAY   = config.getint("bot", "message_delay", fallback=2)
STORY_EXPIRE    = config.getint("bot", "story_expire", fallback=600)
RATE_LIMIT_MAX  = config.getint("bot", "rate_limit_max", fallback=5)
RATE_LIMIT_WIN  = config.getint("bot", "rate_limit_window", fallback=3600)
MAX_QUEUE_SIZE  = config.getint("bot", "max_queue_size", fallback=20)
THROTTLE_DELAY  = config.getint("bot", "throttle_delay", fallback=4)
CHANNEL_QUIET   = config.getint("bot", "channel_quiet_window", fallback=10)

# ============================================================
# RSS FEED MAP BY STATE
# ============================================================
NATIONAL_RSS = "https://feeds.npr.org/1002/rss.xml"

STATE_RSS = {
    "CO": [
        "https://kdvr.com/feed/",
        "https://www.denverpost.com/feed/",
        "https://www.9news.com/feeds/syndication/rss/news",
        "https://coloradoan.com/arcio/rss/",
    ],
    "CA": [
        "https://www.latimes.com/local/rss2.0.xml",
        "https://www.sfgate.com/bayarea/feed/Bay-Area-News-429.php",
    ],
    "TX": [
        "https://www.chron.com/news/houston-texas/rss/",
        "https://www.dallasnews.com/arc/outboundfeeds/rss/",
    ],
    "NY": [
        "https://www.nydailynews.com/arcio/rss/",
        "https://nypost.com/feed/",
    ],
    "FL": [
        "https://www.miamiherald.com/news/local/?outputType=atom",
        "https://www.tampabay.com/feed/",
    ],
    "WA": [
        "https://www.seattletimes.com/feed/",
    ],
    "OR": [
        "https://www.oregonlive.com/arc/outboundfeeds/rss/",
    ],
    "AZ": [
        "https://www.azcentral.com/arcio/rss/",
    ],
    "IL": [
        "https://chicago.suntimes.com/rss/index.xml",
    ],
    "GA": [
        "https://www.ajc.com/arcio/rss/",
    ],
}

DEFAULT_RSS = [
    "https://www.usatoday.com/rss/news/",
    "https://rss.cnn.com/rss/edition.rss",
]

# ============================================================
# STATE
# ============================================================
request_queue    = queue.Queue(maxsize=MAX_QUEUE_SIZE)
node_stories     = {}
node_rate        = {}
state_lock       = threading.Lock()
last_send_time   = 0
last_receive_time = 0
channel_lock     = threading.Lock()

# ============================================================
# RATE LIMITING
# ============================================================
def is_rate_limited(node_id):
    now = time.time()
    with state_lock:
        if node_id not in node_rate:
            node_rate[node_id] = []
        node_rate[node_id] = [t for t in node_rate[node_id] if now - t < RATE_LIMIT_WIN]
        if len(node_rate[node_id]) >= RATE_LIMIT_MAX:
            return True
        node_rate[node_id].append(now)
        return False

# ============================================================
# THROTTLED SEND
# ============================================================
def throttled_send(interface, msg, node_id, want_ack=False):
    global last_send_time, last_receive_time
    with channel_lock:
        # Wait if channel was recently active
        while True:
            now = time.time()
            time_since_send    = now - last_send_time
            time_since_receive = now - last_receive_time
            if time_since_send >= THROTTLE_DELAY and time_since_receive >= CHANNEL_QUIET:
                break
            wait = max(THROTTLE_DELAY - time_since_send, CHANNEL_QUIET - time_since_receive)
            print("  [throttle] channel busy, waiting " + str(round(wait, 1)) + "s...")
            time.sleep(min(wait, 1))

        try:
            interface.sendText(msg, destinationId=node_id, wantAck=want_ack)
            last_send_time = time.time()
            print("  -> " + msg)
        except Exception as e:
            print("  Error sending: " + str(e))

# ============================================================
# HELPERS
# ============================================================
def get_location(zip_code):
    try:
        r = requests.get("http://api.zippopotam.us/us/" + zip_code, timeout=10)
        if r.status_code == 200:
            d = r.json()
            city  = d["places"][0]["place name"]
            state = d["places"][0]["state abbreviation"]
            lat   = d["places"][0]["latitude"]
            lon   = d["places"][0]["longitude"]
            return city + ", " + state, state, lat, lon
    except:
        pass
    return None, None, None, None

def fetch_rss(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "ACKNewsBot/1.0"})
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            items = []
            for item in root.iter("item"):
                title = item.findtext("title") or ""
                desc  = item.findtext("description") or ""
                link  = item.findtext("link") or ""
                desc  = re.sub(r"<[^>]+>", "", desc).strip()
                if title:
                    items.append({"title": title.strip(), "description": desc[:200], "url": link.strip()})
            return items
    except:
        pass
    return []

def get_local_news(state):
    feeds = STATE_RSS.get(state, DEFAULT_RSS)
    articles = []
    for feed_url in feeds:
        items = fetch_rss(feed_url)
        articles.extend(items)
        if len(articles) >= 2:
            break
    return articles[:2]

def get_national_news():
    items = fetch_rss(NATIONAL_RSS)
    return items[:1]

def get_noaa_alerts(lat, lon):
    try:
        point_url = "https://api.weather.gov/points/" + lat + "," + lon
        r = requests.get(point_url, timeout=10, headers={"User-Agent": "ACKNewsBot/1.0"})
        if r.status_code != 200:
            return []
        county_url = r.json().get("properties", {}).get("county", "")
        if not county_url:
            return []
        zone = county_url.split("/")[-1]
        alert_url = "https://api.weather.gov/alerts/active?zone=" + zone
        a = requests.get(alert_url, timeout=10, headers={"User-Agent": "ACKNewsBot/1.0"})
        if a.status_code != 200:
            return []
        features = a.json().get("features", [])
        alerts = []
        for f in features[:3]:
            props    = f.get("properties", {})
            event    = props.get("event", "")
            headline = props.get("headline", "") or ""
            severity = props.get("severity", "")
            if event:
                alerts.append(severity + ": " + event + " - " + headline[:60])
        return alerts
    except:
        pass
    return []

def summarize(headline, description):
    prompt = "Summarize in ONE sentence under 100 chars. Be direct:\nHeadline: " + headline + "\nDetails: " + description + "\nSummary:"
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }, timeout=30)
        if r.status_code == 200:
            s = r.json().get("response", "").strip()
            s = s.replace('"', "").replace("\n", " ")
            return s[:100]
    except:
        pass
    return headline[:100]

# ============================================================
# PROCESSORS
# ============================================================
def process_news(interface, node_id, zip_code):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[" + ts + "] " + node_id + " -> news " + zip_code)

    # Instant ACK
    throttled_send(interface, "ACK News! Got your request for " + zip_code + ", working on it...", node_id)

    location, state, lat, lon = get_location(zip_code)
    if not location:
        throttled_send(interface, "Invalid zip code.", node_id)
        return

    local_articles    = get_local_news(state)
    national_articles = get_national_news()
    alerts            = get_noaa_alerts(lat, lon)
    all_articles      = local_articles + national_articles
    msgs              = ["ACK NEWS - " + location]
    stories           = []

    if not all_articles:
        msgs.append("No recent news found.")
    else:
        for i, a in enumerate(all_articles[:NUM_STORIES], 1):
            h    = re.sub(r"\s*-\s*\w+$", "", a.get("title", "")).strip()
            desc = a.get("description", "") or ""
            url  = a.get("url", "") or ""
            tag  = "[Local] " if i <= len(local_articles) else "[NPR] "
            summary = summarize(h, desc)
            msgs.append(str(i) + ". " + tag + summary)
            stories.append({"title": h, "description": desc, "url": url})

    if alerts:
        msgs.append("⚠️ " + str(len(alerts)) + " active NOAA alert(s) - reply 'alerts' for details")

    msgs.append("Reply 1-3 expand | 'alerts' 4 NOAA | exp 10min")

    with state_lock:
        node_stories[node_id] = {
            "time":    time.time(),
            "stories": stories,
            "alerts":  alerts
        }

    for msg in msgs:
        throttled_send(interface, msg, node_id, want_ack=True)

def process_expand(interface, node_id, story_num):
    with state_lock:
        entry = node_stories.get(node_id)

    if not entry:
        throttled_send(interface, "No recent stories. Send 'news 12345' first.", node_id)
        return
    if time.time() - entry["time"] > STORY_EXPIRE:
        throttled_send(interface, "Stories expired. Send 'news 12345' for fresh news.", node_id)
        return

    stories = entry["stories"]
    idx = story_num - 1
    if idx < 0 or idx >= len(stories):
        throttled_send(interface, "Invalid number. Reply 1-" + str(len(stories)) + ".", node_id)
        return

    story = stories[idx]
    desc  = story["description"][:150] if story["description"] else "No details available."
    url   = story["url"][:100] if story["url"] else "No link available."

    throttled_send(interface, "Story " + str(story_num) + ": " + story["title"][:100], node_id, want_ack=True)
    throttled_send(interface, desc, node_id, want_ack=True)
    throttled_send(interface, "Source: " + url, node_id, want_ack=True)

def process_alerts(interface, node_id):
    with state_lock:
        entry = node_stories.get(node_id)

    if not entry:
        throttled_send(interface, "No recent data. Send 'news 12345' first.", node_id)
        return
    if time.time() - entry["time"] > STORY_EXPIRE:
        throttled_send(interface, "Data expired. Send 'news 12345' for fresh data.", node_id)
        return

    alerts = entry.get("alerts", [])
    if not alerts:
        throttled_send(interface, "No active NOAA alerts for your area.", node_id)
        return

    throttled_send(interface, "⚠️ NOAA ALERTS:", node_id, want_ack=True)
    for alert in alerts:
        throttled_send(interface, alert[:220], node_id, want_ack=True)

# ============================================================
# WORKER
# ============================================================
def worker(interface):
    while True:
        try:
            item = request_queue.get(timeout=1)
            if item[0] == "news":
                process_news(interface, item[1], item[2])
            elif item[0] == "expand":
                process_expand(interface, item[1], item[2])
            elif item[0] == "alerts":
                process_alerts(interface, item[1])
            request_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print("Worker error: " + str(e))

# ============================================================
# MESSAGE HANDLER
# ============================================================
def on_receive(packet, interface):
    global last_receive_time
    try:
        decoded = packet.get("decoded", {})
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return

        # Track channel activity
        last_receive_time = time.time()

        text    = decoded.get("text", "").strip().lower()
        node_id = packet.get("fromId", "")

        m = re.match(r"^news\s*(\d{5})$", text)
        if m:
            if is_rate_limited(node_id):
                try:
                    interface.sendText("ACK News: Too many requests. Try again later.", destinationId=node_id)
                except:
                    pass
                print("Rate limited: " + node_id)
                return
            print("Request from " + node_id + ": news " + m.group(1))
            # Notify user if queue is getting busy
            try:
                if request_queue.qsize() > 3:
                    interface.sendText("ACK News! Got your request, channel is busy - your news is queued, standby...", destinationId=node_id)
                request_queue.put_nowait(("news", node_id, m.group(1)))
            except queue.Full:
                interface.sendText("ACK News: Bot is busy, please try again in a moment.", destinationId=node_id)
            return

        m = re.match(r"^([123])$", text)
        if m:
            try:
                request_queue.put_nowait(("expand", node_id, int(m.group(1))))
            except queue.Full:
                interface.sendText("ACK News: Bot is busy, please try again.", destinationId=node_id)
            return

        if text == "alerts":
            try:
                request_queue.put_nowait(("alerts", node_id, None))
            except queue.Full:
                interface.sendText("ACK News: Bot is busy, please try again.", destinationId=node_id)
            return

        if text == "news help":
            interface.sendText("ACK News: 'news 12345' for headlines | Reply 1-3 expand | 'alerts' for NOAA", destinationId=node_id)

    except Exception as e:
        print("Error: " + str(e))

# ============================================================
# MAIN
# ============================================================
def main():
    print("ACK News Bot starting on " + SERIAL_PORT + "...")
    print("Rate limit: " + str(RATE_LIMIT_MAX) + " requests per " + str(RATE_LIMIT_WIN) + "s per node")
    print("Max queue: " + str(MAX_QUEUE_SIZE))
    print("Throttle delay: " + str(THROTTLE_DELAY) + "s | Channel quiet window: " + str(CHANNEL_QUIET) + "s")
    try:
        interface = SerialInterface(SERIAL_PORT)
        print("Connected!")
    except Exception as e:
        print("Failed: " + str(e))
        return
    pub.subscribe(on_receive, "meshtastic.receive")
    threading.Thread(target=worker, args=(interface,), daemon=True).start()
    print("Listening! Send 'news 12345' on your mesh to test.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        interface.close()

if __name__ == "__main__":
    main()
