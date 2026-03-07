# ACK News Bot 📡

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support%20This%20Project-yellow)](https://buymeacoffee.com/acknewsbot)

A free, locally-hosted AI news service for Meshtastic mesh networks. Users send a simple command from any node in range of the bot on the mesh and receive AI-summarized local and national news headlines, NOAA weather alerts, and full story details — all privately delivered with no internet-connected apps required just the bot online and connected to the mesh.

---

## Features

- 📰 **Local + National News** — 2 local stories and 1 NPR national story per request
- 🤖 **AI Summaries** — Local Ollama AI summarizes headlines to mesh-friendly length
- ⚠️ **NOAA Alerts** — Live weather and emergency alerts by zip code
- 📖 **Story Expansion** — Reply 1, 2, or 3 to get the full story and source link
- 🔒 **Private Replies** — Responses go only to the requesting node, not the public channel
- 🚦 **Channel Throttling** — Bot waits for channel quiet before sending, respects other users
- ⏱️ **Rate Limiting** — Max 5 requests per node per hour to prevent abuse
- 💰 **Zero Monthly Cost** — All free APIs, local AI, no subscriptions

---

## Hardware Requirements

| Component | Recommended | Minimum |
|-----------|-------------|---------|
| Single Board Computer | Raspberry Pi 5 8GB | Raspberry Pi 4 4GB |
| Storage | 32GB microSD | 16GB microSD |
| Meshtastic Node | Any USB-C node | Any WiFi/TCP node |
| Connection | USB serial (recommended) | WiFi/TCP |

> ⚠️ The Raspberry Pi Zero 2W is **not supported** — it has insufficient RAM (512MB) to run Ollama.

---

## How It Works

```
User sends:  news 80537
Bot replies: ACK News! Got your request for 80537, working on it...
Bot replies: ACK NEWS - Loveland, CO
             1. [Local] Story one summary
             2. [Local] Story two summary
             3. [NPR] National story summary
             ⚠️ 2 active NOAA alert(s) - reply 'alerts' for details
             Reply 1-3 expand | 'alerts' 4 NOAA | exp 10min

User sends:  1
Bot replies: Story 1: Full headline here
             Full description of the story...
             Source: https://example.com/story

User sends:  alerts
Bot replies: ⚠️ NOAA ALERTS:
             Moderate: Winter Storm Warning - Heavy snow expected...
```

---

## Commands

| Command | Description |
|---------|-------------|
| `news 12345` | Get local + national news for zip code |
| `news12345` | Same as above (space optional) |
| `1` `2` `3` | Expand a story from your last news request |
| `alerts` | Get full NOAA alert details from your last request |
| `news help` | Show available commands |

---

## Installation

### Step 1 — Prepare Raspberry Pi

1. Download and install [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS 64-bit** to your microSD card
3. In Imager settings, configure your WiFi credentials and enable SSH
4. Boot your Pi and SSH in (default hostname: `raspberrypi.local`)

### Step 2 — Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### Step 3 — Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv -y
```

### Step 4 — Set Up the Bot

```bash
mkdir ~/acknews && cd ~/acknews
python3 -m venv venv
source venv/bin/activate
pip install meshtastic requests
```

### Step 5 — Deploy Files

Copy `acknews.py` and `config.ini` to `~/acknews/` using WinSCP or SCP.

### Step 6 — Configure

Edit `config.ini` with your settings:

```ini
[meshtastic]
serial_port = /dev/ttyUSB0        # USB connection (recommended)
# serial_port = 192.168.0.215     # WiFi/TCP alternative

[newsapi]
key = your_newsapi_key_here       # Optional, not required for RSS mode

[bot]
ollama_model = llama3.2:3b
num_stories = 3
message_delay = 2
story_expire = 600
rate_limit_max = 5
rate_limit_window = 3600
max_queue_size = 20
throttle_delay = 3
channel_quiet_window = 10
```

### Step 7 — Connect Meshtastic Node

**Recommended: USB Serial**
1. Plug USB-C cable from Meshtastic node into Pi's USB-A port
2. Verify connection: `ls /dev/ttyUSB*` — should show `/dev/ttyUSB0`

**Alternative: WiFi/TCP**
1. Set a static IP for your node in your router's DHCP settings
2. Update `config.ini` with the node's IP address

### Step 8 — Install as System Service

```bash
sudo nano /etc/systemd/system/acknews.service
```

Paste this content:

```ini
[Unit]
Description=ACK News Bot
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/acknews
ExecStart=/home/pi/acknews/venv/bin/python3 /home/pi/acknews/acknews.py
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable acknews
sudo systemctl start acknews
sudo systemctl status acknews
```

---

## Adding Local News Sources

The bot uses RSS feeds mapped by US state. To add or change feeds for your area, edit the `STATE_RSS` dictionary in `acknews.py`:

```python
STATE_RSS = {
    "CO": [
        "https://kdvr.com/feed/",
        "https://www.denverpost.com/feed/",
        "https://www.9news.com/feeds/syndication/rss/news",
        "https://coloradoan.com/arcio/rss/",
    ],
    # Add your state here
    "XX": [
        "https://your-local-news-site.com/feed/",
    ],
}
```

Most local TV stations and newspapers publish free RSS feeds. Search for `[station name] RSS feed` to find them.

---

## ARES/RACES Integration Guide

ACK News Bot is designed to work alongside amateur radio emergency communication groups. Here is how to integrate it with your local ARES/RACES organization.

### What ARES/RACES Operators Can Do

- Use the bot as a **public information resource** during activations
- Direct affected community members to use `news ZIPCODE` for local updates
- Use `alerts ZIPCODE` for real-time NOAA emergency alert status
- Supplement traditional HF/VHF nets with mesh-based information delivery

### Contacting Your Local ARES/RACES Group

1. Find your local ARRL section at **arrl.org/sections**
2. Contact your **Section Emergency Coordinator (SEC)** or **Emergency Coordinator (EC)**
3. Introduce the mesh network and ACK News Bot capabilities
4. Propose adding the bot node to your local EmComm plan

### Suggested Pitch to ARES/RACES

*"We have a Meshtastic mesh network covering [X] nodes in [your area]. ACK News Bot provides on-demand local news and NOAA emergency alerts to any node on the mesh — no internet, no cell service required once the Pi has its data. During an activation this gives served agencies and community members a self-service information resource that doesn't tie up voice nets."*

### Admin Broadcast Command (Coming Soon)

A future update will allow trusted ARES/RACES operators to push urgent announcements to the entire mesh channel. Trusted operator node IDs will be stored in `config.ini`. This will enable:

- Net control stations to push activation notices
- Emergency managers to broadcast evacuation or shelter information
- Public information officers to distribute official updates

### Contacting Local Emergency Management

For Larimer County / Loveland CO area:
- **Larimer County Emergency Management** — larimerco.org/emergency-management
- **Loveland Fire Rescue Authority** — cityofloveland.org/lfra
- **City of Loveland Emergency Management** — cityofloveland.org

For other areas search: `[your county] emergency management office`

---

## Cost Analysis

| Item | Cost |
|------|------|
| Raspberry Pi 5 8GB | ~$80 |
| microSD card 32GB | ~$10 |
| Power supply | ~$12 |
| USB-C cable | ~$0 (you have one) |
| **Total hardware** | **~$102** |
| Monthly operating cost | **$0.00** |
| Electricity (Pi 5 idle) | ~$2-4/year |

---

## Troubleshooting

**Bot not connecting to node:**
```bash
ls /dev/ttyUSB*        # Check USB device is visible
ping 192.168.0.x       # Check WiFi/TCP node is reachable
```

**No news results:**
- Check your RSS feeds are still valid
- Some feeds change URLs over time — search for updated feed URLs

**Slow responses:**
- Normal on first request after idle (Ollama loads model into memory)
- Adjust `throttle_delay` in `config.ini` if needed
- Consider upgrading to Pi 5 if using Pi 4

**Service not starting:**
```bash
sudo journalctl -u acknews -n 20 --no-pager
```

---

## Roadmap

- [ ] Admin broadcast command for ARES/RACES and emergency management
- [ ] Web dashboard for monitoring requests and bot health
- [ ] Support for additional Meshtastic channels
- [ ] Configurable RSS feeds via config.ini (no code editing required)
- [ ] Multi-language support

---

## Support This Project

If ACK News Bot is useful to your mesh community, consider buying us a coffee! ☕

👉 **[buymeacoffee.com/acknewsbot](https://buymeacoffee.com/acknewsbot)**

Every coffee helps keep the project going and supports new features!

---

## License

MIT License — free to use, modify, and share.

---

## Credits

Built with:
- [Meshtastic](https://meshtastic.org) — mesh networking platform
- [Ollama](https://ollama.com) — local AI inference
- [api.weather.gov](https://api.weather.gov) — free NOAA weather alerts
- [NPR News RSS](https://npr.org) — national news feed
- Local RSS feeds from regional news outlets

---

*Built for the Meshtastic community. Stay connected when it counts.* 📡
