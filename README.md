# Chromatel Raspberry Pi LED Stock Ticker

I built this project because I wanted a stock ticker in my office and wasn’t about to drop $4k on a commercial one with a subscription fee. With the help of Copilot and Claude, this project was born. You may see sample holdings or tickers in the code — **none of it is financial advice**.

Also this project was proudly ⚜️ Fabriqué au Québec ⚜️by an it specialist/ham operator/musician 

⚠️ **Important:**  
There is **no authentication or security** in this project. The Web UI is wide open.  
Run this on an isolated VLAN or private network. Keep it simple, keep it safe.

---
<img width="869" height="619" alt="image" src="https://github.com/user-attachments/assets/5c304925-1794-4406-b069-59720d6b9077" />

## 🧰 Materials List

What I used to build the physical ticker:

- Raspberry Pi 4  
- Raspberry Pi 4 PoE HAT  
- Adafruit RGB HUB75 Matrix HAT  
- 64GB SD card (cheap is fine)
- **2× VEVOR programmable P10 RGB signs**  
  Full product name:  
  _“VEVOR Programmable LED Sign, P10 Full Color Flexible Digital Scrolling Panel, DIY Custom Text Pattern GIF Display Board, Bluetooth APP Control Message Shop Sign for Store Business Advertising, 40×8”_  
  I canibalized these for their frames, PSUs, and panels.
- 2020 aluminum connector/coupler (to join both signs into a single 192×16 panel)
- Alien tape (yes, it actually holds)

You can chain more panels if you want a full 360° wraparound room ticker… but that’s between you and your wall space.

---

# ChromaTicker — Project Summary

**ChromaTicker** is a multi‑process Python application for Raspberry Pi that drives a **192×16 HUB75 RGB LED matrix** (or HDMI-rendered pixel window). It displays:

- Real‑time stock market data  
- Live NHL/NFL sports scores  
- Environment Canada weather alerts  
- Time prerolls  
- Custom injected messages  

A built‑in Web UI handles all configuration and updates instantly with **hot‑reload**.

---

## ✨ Key Features

### 📈 Real‑Time Market Ticker
- Live updates via **yfinance**
- Shows symbol label, price, and color‑coded percent change
- Optional portfolio value mode (shares × price)
- Status dot shows:
  - Market open/closed
  - Pre‑market status
  - Data freshness
  - Whether your tracked team plays today

### 🏒 Live Sports Scoreboards
- Automatically activates full-height scoreboard when your team is playing
- Supports NHL + NFL
- Goal/touchdown flash animations + scrolling alerts
- Compact scoreboard mode that fits inside ticker rows

### 🌩 Weather Alerts (Environment Canada)
- Reads regional RSS alert feeds
- Displays full‑width scrolling warnings/advisories
- Severity‑colored messages (red/yellow)
- Sticky mode, repeat intervals, and testing options

### 🕒 Time Preroll Events
- Top‑of‑hour big clock display
- Market open/close announcements
- Customizable style, duration, color, and scroll speed

### 🚨 Override Modes
From the Web UI:
- **Clock Mode** (large centered clock)
- **Full Brightness**
- **Force Scoreboard**
- **Custom Message Display**
- **Maintenance Mode**

Overrides are the highest‑priority state.

---

## 🧩 Architecture Overview

```
ticker.py             Main loop + state machine
├── market_worker     Fetches financial data via yfinance
├── weather_worker    Fetches Environment Canada RSS alerts
└── scoreboard_worker Fetches NHL/NFL game data

rendering.py          Drawing, fonts, dimming, RGB matrix output
flask_ui.py           Web UI + REST API (port 5080)
config.json           Hot‑reload configuration
```

Each worker runs independently and communicates via multiprocessing queues.  
The renderer pushes frames to the LED panel at up to **60 FPS**.

---

## 🌐 Web Control Panel

**URL:** `http://<pi-ip>:5080`

Includes:
- Full configuration editor (`config.json`)
- Hot‑reload within ~1 second
- Quick actions (Clock 5m, Bright 30m, Clear Override, Force Scoreboard)
- Live preview (`/preview`, `/preview.png`)

---

## 🛠 Configuration System

Everything lives in `config.json`:

- Display mode + layout (dual-row, single-row, HDMI preview)
- Scroll speeds
- Market tickers + holdings
- Weather system settings
- Scoreboard league/team selection
- Dimming + night mode schedules
- Override parameters
- RGB matrix hardware configuration

Most settings apply instantly without restarting.

---

## 🚦 Display States

The ticker always runs in one of these prioritized states:

1. **Override (OV)**  
2. **Score Alert** (goal/touchdown banner)  
3. **Preroll (PR)**  
4. **Scoreboard (SB)**  
5. **Ticker (TK)**  

---

## 🔧 Testing & Debugging Tools

- Test scoreboard, weather alerts, score events, and messages  
- `/raw` JSON editor  
- Systemd logging (`journalctl`)  
- Debug overlay showing FPS, state, dim %, and layout  

---

## 📁 Project File Structure

```
led-ticker/
├── ticker.py              # Main loop + state machine
├── rendering.py           # Drawing, fonts, dimming, output
├── workers.py             # Market, weather, scoreboard fetchers
├── scoreboard_logos.py    # Auto-generated NHL/NFL logos
├── flask_ui.py            # Web UI + REST API
├── config.json            # System configuration (hot reload)
├── ticker_status.json     # Worker health/status
├── docs.html              # Documentation
├── requirements.txt
└── venv/                  # Python virtual environment
```

---

## 🚀 Summary

**ChromaTicker** is a customizable, always‑on information display for Raspberry Pi, featuring:

- Real-time market tracking  
- Live sports intelligence  
- Weather alerting  
- Automated dimming  
- Time-based prerolls  
- Instant configuration updates  
- Web-based control  
- Multi-process architecture  

Designed for reliability, responsiveness, and everyday use in an office, home lab, or ham shack.
