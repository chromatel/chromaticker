# chromaticker
The Chromatel Raspberry Pi LED Stock Ticker.

I built this project becuase I thought it would be super cool to have a stock ticker in my office and I didn't want to pay $4k for something with a subsctiption, so with a little copilot and claude and we made this. You will probably see in the code my current some sample portfolio I made up please don't consider that financial advice. 

There is no security built in to this code and may introduce vulnerabilities. I would run this thing on a locked down vlan, the web ui has no authentication and I didn't want this thing to be to complex.

Materials List - 
Pi 4 
Pi 4 poe hat
Adafruit RBG Hub75 Hat
64gb cheapo sd card
2x These vevor premade signs. I canibalized them since they had the frame and the psu and the panels it was cleaner and easier to do that then buy panels. This is the exact item name VEVOR Programmable LED Sign, P10 Full Color Flexible Digital Scrolling Panel, DIY Custom Text Pattern GIF Display Board, Bluetooth APP Control Message Shop Sign for Store Business Advertising,40x8"
2x 2020 Aluminium coupler thing to join the two vevor signs to make it a 1x6 panel sign.  You could technically chain as many as you want and make like a 365 wrap around but I didn't have the space. 
Its stuck to the wall with a bunch of alien tape 


ChromaTicker — Project Summary
The LED Ticker is a multi‑process Python application designed for Raspberry Pi that drives a 192×16 HUB75 RGB LED matrix (or an HDMI-rendered pixel window). It displays real‑time market data, live sports scores, weather alerts, time prerolls, and custom messages, all managed through a sleek web-based control panel with hot‑reload configuration.

✨ Key Capabilities
Real‑Time Market Ticker

Fetches live data using yfinance.
Displays label, price, and percentage change (color‑coded).
Supports portfolio/holdings mode, showing real-time market value instead of price.
Status dot indicates market hours, data freshness, and team game days.

Live Sports Scoreboards

Auto-switching full-height scoreboard when your tracked team is playing.
Supports NHL and NFL via league APIs.
Goal/touchdown animations with scrolling alerts.
Compact scoreboard mode available inside ticker rows.

Environment Canada Weather Alerts

Polls RSS feeds and displays full-width scrolling warnings/advisories.
Color-coded severity levels.
Includes sticky mode, repeat intervals, and test tools.

Time Preroll Events

Every top of the hour (and market open/close), shows large centered time or announcement.
Configurable display style, duration, and scroll speed.

Override Modes
Used for special displays, all accessible from the Web UI:

Clock Mode (large time only)
Full Brightness
Forced Scoreboard
Custom Message Display
Maintenance Screen

Overrides take priority over all normal states.

🧩 Architecture Overview
The system is modular and process‑based:
ticker.py (Main Loop + State Machine)
├── market_worker → yfinance
├── weather_worker → Environment Canada RSS
└── scoreboard_worker → NHL/NFL APIs
rendering.py → all drawing & matrix output
flask_ui.py → config panel & REST API (port 5080)
config.json → full hot-reloadable config

Each worker runs independently and communicates through multiprocessing queues.
The main loop renders frames up to 60 FPS, composing pixel surfaces and pushing them to the LED matrix.

🌐 Web Control Panel
Accessible at:
http://<pi-ip>:5080

Features:

Complete configuration editing (writes to config.json).
Hot‑reload within ~1 second — no restarts required.
Quick actions (Clock 5m, Bright 30m, Clear Override, Scoreboard Mode).
Live preview window (/preview, /preview.png).


🛠 Configuration System
All settings live in config.json, covering:

Display mode & layout (dual-row ticker, single-row, HDMI preview)
Scroll speeds
Market tickers & holdings
Weather system
Scoreboard settings
Dimming schedules + Night Mode
Overrides
RGB matrix hardware options

Most changes apply instantly without restarting.

🚦 Display States
The ticker always operates in one of several prioritized runtime states:

OV – Manual override
Score Alert – Goal/touchdown banners
PR – Preroll events
SB – Live scoreboard
TK – Normal ticker mode


🔧 Testing & Debugging Tools

Built‑in test modes for weather, scoreboards, alerts, and messages.
/raw editor for direct JSON editing.
Systemd integration with journal logs.
Debug overlay for FPS, state, dimming, and layout info.


📁 Project File Structure
led-ticker/
├── ticker.py              # Main loop + state machine
├── rendering.py           # Drawing, fonts, dimming, output
├── workers.py             # Market, weather, scoreboard fetchers
├── scoreboard_logos.py    # Auto-generated NHL/NFL logos
├── flask_ui.py            # Web UI & REST API
├── config.json            # Full system configuration (hot reload)
├── ticker_status.json     # Worker health/status
├── docs.html              # Full built-in documentation
├── requirements.txt
└── venv/                  # Python virtual environment


🚀 Summary
The LED Ticker is a fully customizable micro‑information display system for Raspberry Pi, combining:

Real‑time financial data
Sports intelligence
Weather alerting
Time displays
Automated dimming
Hot‑reload configuration
Web-based management
Multi-process performance

It was built for reliability, fast feedback, and seamless daily use in an office, home lab, or operations center.
