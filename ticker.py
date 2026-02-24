#!/home/fpp/led-ticker/venv/bin/python
# -*- coding: utf-8 -*- 
# Property of solutions reseaux chromatel
# =================================================================================================
# ================================== CONFIG (env defaults) ========================================
# =================================================================================================
import os, time, json, math
# Scroll position: round half toward -inf so the rendered pixel only ever moves left.
# round() uses banker's rounding which can snap 1px backward; floor() holds each pixel
# for a full pixel of travel making the stutter more visible. ceil(x-0.5) changes at
# the 0.5 mark (same cadence as round) but always rounds toward -inf — no backward blips.
_sp = lambda x: math.ceil(x - 0.5)
from datetime import datetime, date, time as dtime, timedelta, timezone
from multiprocessing import Process, Queue, set_start_method
from collections import deque
import queue as queue_std
import pygame
import signal
import sys

# Property of solutions reseaux chromatel
# Add pytz for proper market hours detection
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False
    print("[WARN] pytz not available - market hours detection will be limited", flush=True)

# --------------------------------------------------------------------------------
# OUTPUT / DRIVER BEHAVIOR
# --------------------------------------------------------------------------------

# Import worker modules
from utils import (
    is_us_market_open, get_market_event_announcement,
    now_local, set_globals as set_utils_globals
)
from workers import (
    market_worker, weather_worker, scoreboard_worker,
    set_globals as set_worker_globals
)
# Import rendering module
from rendering import (
    set_globals as set_rendering_globals, set_fonts,
    BLACK, WHITE, RED, GREEN, YELLOW, GREY,
    parse_color, fmt_price_compact, fmt_value_currency_compact,
    format_weather_alert_text, parse_hhmm,
    using_microfont,
    current_dim_scale, apply_night_mode_speed,
    init_pygame, write_surface_to_rgb_matrix, init_rgb_matrix,
    make_font, get_row_font, get_sb_font, get_dbg_font,
    get_preroll_big_font, get_maint_big_font,
    row_render_text, build_time_surface, build_announcement_surface,
    build_weather_alert_surface, build_message_surface, build_clock_surface,
    build_row_surfaces_from_cache, apply_dimming_inplace,
    render_fullheight_scoreboard, ScoreboardFlashState
)





# --------------------------------------------------------------------------------
# RGB MATRIX HARDWARE SETTINGS
# --------------------------------------------------------------------------------
RGB_BRIGHTNESS = max(0, min(100, int(os.environ.get("RGB_BRIGHTNESS", "100") or 100)))  # Brightness level 0-100
RGB_HARDWARE_MAPPING = (os.environ.get("RGB_HARDWARE_MAPPING", "adafruit-hat") or "adafruit-hat").strip()  # Hardware adapter type
RGB_GPIO_SLOWDOWN = max(0, min(4, int(os.environ.get("RGB_GPIO_SLOWDOWN", "4") or 4)))  # GPIO slowdown for stability (0-4)
RGB_PWM_BITS = max(1, min(11, int(os.environ.get("RGB_PWM_BITS", "11") or 11)))  # PWM bits for color depth (1-11)
RGB_PWM_LSB_NANOSECONDS = max(50, min(3000, int(os.environ.get("RGB_PWM_LSB_NANOSECONDS", "130") or 130)))  # PWM timing (50-3000)

# Advanced panel configuration
RGB_CHAIN_LENGTH = max(1, int(os.environ.get("RGB_CHAIN_LENGTH", "1") or 1))  # Number of panels chained horizontally
RGB_PARALLEL = max(1, int(os.environ.get("RGB_PARALLEL", "1") or 1))  # Number of parallel chains
RGB_SCAN_MODE = max(0, min(1, int(os.environ.get("RGB_SCAN_MODE", "0") or 0)))  # 0=progressive, 1=interlaced
RGB_ROW_ADDRESS_TYPE = max(0, min(4, int(os.environ.get("RGB_ROW_ADDRESS_TYPE", "0") or 0)))  # Row addressing: 0=direct, 1=AB, 2=direct-ABCDline, 3=ABC-shift, 4=ABC-ZigZag
RGB_MULTIPLEXING = max(0, min(18, int(os.environ.get("RGB_MULTIPLEXING", "0") or 0)))  # Multiplexing type for specific panels
RGB_LED_RGB_SEQUENCE = (os.environ.get("RGB_LED_RGB_SEQUENCE", "RGB") or "RGB").strip().upper()  # LED color order: RGB, RBG, GRB, GBR, BRG, BGR
RGB_PIXEL_MAPPER = (os.environ.get("RGB_PIXEL_MAPPER", "") or "").strip()  # Pixel mapper config (e.g. "Rotate:90" or "U-mapper")
RGB_PANEL_TYPE = (os.environ.get("RGB_PANEL_TYPE", "") or "").strip()  # Panel type hint (empty for default)

# --------------------------------------------------------------------------------
# CLOCK OVERRIDE (standalone big clock)
# --------------------------------------------------------------------------------
CLOCK_24H          = os.environ.get("CLOCK_24H", "1") == "1"      # True: 24-hour clock (HH:MM[/SS]). False: 12-hour (h:MM[/SS], no leading 0).
CLOCK_SHOW_SECONDS = os.environ.get("CLOCK_SHOW_SECONDS", "0") == "1"  # Append :SS (more updates/more CPU; off is cleaner for LED).
CLOCK_BLINK_COLON  = os.environ.get("CLOCK_BLINK_COLON", "1") == "1"   # Blink colon every second (replaced with space when off).
CLOCK_COLOR        = (os.environ.get("CLOCK_COLOR", "yellow") or "yellow")  # Time color.
CLOCK_DATE_SHOW    = os.environ.get("CLOCK_DATE_SHOW", "1") == "1"     # If true, render a date line under time (centered).
CLOCK_DATE_FMT     = (os.environ.get("CLOCK_DATE_FMT", "%a %b %d") or "%a %b %d")  # ex: "Sat Feb 08".
CLOCK_DATE_COLOR   = (os.environ.get("CLOCK_DATE_COLOR", "white") or "white")      # Date color.

# --------------------------------------------------------------------------------
# DIAGNOSTICS
# --------------------------------------------------------------------------------
DEMO_MODE    = os.environ.get("TICKER_DEMO", "0") == "1"   # Skip network calls; render canned market values for bench testing.
DEBUG_OVERLAY= os.environ.get("DEBUG_OVERLAY", "0") == "1" # Draw small technical info at the bottom line (FPS/state/dim/etc.).

# --------------------------------------------------------------------------------
# MODEL / CANVAS / LAYOUT
# --------------------------------------------------------------------------------
MODEL_NAME = os.environ.get("FPP_MODEL_NAME", "Matrix192x16")  # FPP model name; used for SHM filename and default WH resolver.
# DEPRECATED: SHM mode no longer supported - using RGB Matrix directly
W = int(os.environ.get("TICKER_W", "0") or 0)  # Override panel width; 0 = auto by MODEL_NAME.
H = int(os.environ.get("TICKER_H", "0") or 0)  # Override panel height; 0 = auto by MODEL_NAME.
LAYOUT = (os.environ.get("TICKER_LAYOUT", "") or "").lower()  # "single" or "dual"; empty="" = auto (H>=16 => dual else single).

# --------------------------------------------------------------------------------
# TIMEZONE
# --------------------------------------------------------------------------------
TICKER_TZ = (os.environ.get("TICKER_TZ", "America/Toronto") or "America/Toronto").strip()

# --------------------------------------------------------------------------------
# MAIN DISPLAY / FRAME RATE
# --------------------------------------------------------------------------------
try: FPS = max(1, int(os.environ.get("FPS", "60") or 60))
except: FPS = 60
try: PPS_TOP = float(os.environ.get("PPS_TOP", "40") or 40)
except: PPS_TOP = 40.0
try: PPS_BOT = float(os.environ.get("PPS_BOT", "40") or 40)
except: PPS_BOT = 40.0
try: PPS_SINGLE = float(os.environ.get("PPS_SINGLE", "40") or 40)
except: PPS_SINGLE = 40.0
try: REFRESH_SEC = max(10, int(os.environ.get("REFRESH_SEC", "120") or 120))
except: REFRESH_SEC = 120
try: FRESH_SEC = max(1, int(os.environ.get("FRESH_SEC", "180") or 180))
except: FRESH_SEC = 180

# --------------------------------------------------------------------------------
# TIME PREROLL
# --------------------------------------------------------------------------------
TIME_PREROLL_ENABLED = os.environ.get("TIME_PREROLL_ENABLED", "1") == "1"
try: TIME_PREROLL_SEC = max(0, int(os.environ.get("TIME_PREROLL_SEC", "15") or 15))
except: TIME_PREROLL_SEC = 15
PREROLL_STYLE = (os.environ.get("PREROLL_STYLE", "BIGTIME") or "BIGTIME").upper()  # "BIGTIME", "MARQUEE", "MARKET_ANNOUNCE", "NONE"
PREROLL_COLOR = (os.environ.get("PREROLL_COLOR", "yellow") or "yellow").lower()
try: PREROLL_PPS = float(os.environ.get("PREROLL_PPS", "40") or 40)
except: PREROLL_PPS = 40.0

# --------------------------------------------------------------------------------
# MAINTENANCE MODE
# --------------------------------------------------------------------------------
MAINTENANCE_MODE   = os.environ.get("MAINTENANCE_MODE", "0") == "1"
MAINTENANCE_TEXT   = (os.environ.get("MAINTENANCE_TEXT", "SYSTEM MAINTENANCE  EXPECTED BACK SOON") or "MAINTENANCE").strip()
MAINTENANCE_SCROLL = os.environ.get("MAINTENANCE_SCROLL", "1") == "1"
try: MAINTENANCE_PPS = float(os.environ.get("MAINTENANCE_PPS", "30") or 30)
except: MAINTENANCE_PPS = 30.0

# --------------------------------------------------------------------------------
# WEATHER WORKER
# --------------------------------------------------------------------------------
WEATHER_RSS_URL     = os.environ.get("WEATHER_RSS_URL", "https://weather.gc.ca/rss/warning/qc-147_e.xml")
WEATHER_REFRESH_SEC = int(os.environ.get("WEATHER_REFRESH_SEC", "300"))  # Poll RSS cadence (seconds).
WEATHER_ANNOUNCE_SEC= int(os.environ.get("WEATHER_ANNOUNCE_SEC", "12"))  # How long to show the banner (seconds).
try: WEATHER_TIMEOUT = float(os.environ.get("WEATHER_TIMEOUT", "5.0"))
except: WEATHER_TIMEOUT = 5.0
WEATHER_INCLUDE_WATCH = os.environ.get("WEATHER_INCLUDE_WATCH", "1") == "1"
WEATHER_FORCE_ACTIVE  = os.environ.get("WEATHER_FORCE_ACTIVE", "0") == "1"
WEATHER_FORCE_TEXT    = (os.environ.get("WEATHER_FORCE_TEXT", "") or "").strip()

# Test harness: if >0, after N seconds, inject a synthetic "active" weather message.
try: WEATHER_TEST_DELAY = int(os.environ.get("WEATHER_TEST_DELAY", "0") or 0)
except: WEATHER_TEST_DELAY = 0

# In-render repeat logic: how often to re-announce the weather banner if it is *still* logically active.
# NOTE: We still respect WEATHER_ANNOUNCE_SEC as a minimum spacing from the worker.
try: WEATHER_REPEAT_SEC = int(os.environ.get("WEATHER_REPEAT_SEC", "600") or 600)
except: WEATHER_REPEAT_SEC = 600
# Where to draw the banner when dual: "top" or "bottom"; single layout always uses the only row.
# WEATHER_ROW and WEATHER_COLOR are deprecated - weather alerts always render full-screen
# using WEATHER_WARNING_COLOR / WEATHER_ADVISORY_COLOR for severity-based colors.

# --------------------------------------------------------------------------------
# WEATHER ALERT DISPLAY BY SEVERITY
# --------------------------------------------------------------------------------
# WARNING (red): Full 16px height, red color, show every N scrolls
try: WEATHER_WARNING_EVERY_N_SCROLLS = int(os.environ.get("WEATHER_WARNING_EVERY_N_SCROLLS", "5") or 5)
except: WEATHER_WARNING_EVERY_N_SCROLLS = 5
WEATHER_WARNING_COLOR = (os.environ.get("WEATHER_WARNING_COLOR", "red") or "red").lower()

# ADVISORY/WATCH (yellow): Top line only, yellow color, show every N scrolls  
try: WEATHER_ADVISORY_EVERY_N_SCROLLS = int(os.environ.get("WEATHER_ADVISORY_EVERY_N_SCROLLS", "10") or 10)
except: WEATHER_ADVISORY_EVERY_N_SCROLLS = 10
WEATHER_ADVISORY_COLOR = (os.environ.get("WEATHER_ADVISORY_COLOR", "yellow") or "yellow").lower()

# Test harness: if >0, after WEATHER_TEST_DELAY seconds, force an artificial active alert
# that remains logically "active" for this many seconds (0 = one-shot).
try: WEATHER_TEST_STICKY_TOTAL = int(os.environ.get("WEATHER_TEST_STICKY_TOTAL", "60") or 60)
except: WEATHER_TEST_STICKY_TOTAL = 60

# --------------------------------------------------------------------------------
# SCOREBOARD - PREGAME & POSTGAME TIMING
# --------------------------------------------------------------------------------
SCOREBOARD_PREGAME_WINDOW_MIN = int(os.environ.get("SCOREBOARD_PREGAME_WINDOW_MIN", "30"))  # Show scoreboard N min before game starts
SCOREBOARD_POSTGAME_DELAY_MIN = int(os.environ.get("SCOREBOARD_POSTGAME_DELAY_MIN", "5"))   # Keep showing scoreboard N min after FINAL
SCOREBOARD_SHOW_COUNTDOWN = os.environ.get("SCOREBOARD_SHOW_COUNTDOWN", "1") == "1"          # Show "GAME STARTS IN Xm" for pregame

# --------------------------------------------------------------------------------
# MESSAGE INJECTOR
# --------------------------------------------------------------------------------
INJECT_MESSAGE     = (os.environ.get("TICKER_MESSAGE", "*** DEV MODE ***") or "").strip()  # Message to inject into scroll.
MESSAGE_EVERY      = max(0, int(os.environ.get("MESSAGE_EVERY_SCROLLS", "5") or 0))         # Inject every N full scrolls (0=disabled).
MESSAGE_ROW        = (os.environ.get("MESSAGE_ROW", "auto") or "auto").lower()              # "top", "bottom", "single", "both", or "auto".
MESSAGE_COLOR      = (os.environ.get("MESSAGE_COLOR", "magenta") or "yellow").lower()       # Named color for message text.
MESSAGE_TEST_FORCE = os.environ.get("MESSAGE_TEST_FORCE", "0") == "1"                       # If true, message appears on **every** scroll.

# --------------------------------------------------------------------------------
# NIGHT MODE  (time-based dimming + scroll speed reduction)
# --------------------------------------------------------------------------------
NIGHT_MODE_ENABLED = os.environ.get("NIGHT_MODE_ENABLED", "0") == "1"
NIGHT_MODE_START   = (os.environ.get("NIGHT_MODE_START", "22:00") or "22:00").strip()
NIGHT_MODE_END     = (os.environ.get("NIGHT_MODE_END", "07:00") or "07:00").strip()
try: NIGHT_MODE_DIM_PCT = int(os.environ.get("NIGHT_MODE_DIM_PCT", "30") or 30)
except: NIGHT_MODE_DIM_PCT = 30
try: NIGHT_MODE_SPEED_PCT = int(os.environ.get("NIGHT_MODE_SPEED_PCT", "50") or 50)
except: NIGHT_MODE_SPEED_PCT = 50
QUICK_DIM_PCT = 0  # Quick brightness override (1-100); 0 = disabled

# --------------------------------------------------------------------------------
# FONTS
# --------------------------------------------------------------------------------
FONT_FAMILY_BASE       = (os.environ.get("FONT_FAMILY_BASE", "DejaVuSansMono") or "DejaVuSansMono")
FONT_FAMILY_SCOREBOARD = (os.environ.get("FONT_FAMILY_SCOREBOARD", FONT_FAMILY_BASE) or FONT_FAMILY_BASE)
FONT_FAMILY_DEBUG      = (os.environ.get("FONT_FAMILY_DEBUG", FONT_FAMILY_BASE) or FONT_FAMILY_BASE)
PREROLL_FONT_FAMILY    = (os.environ.get("PREROLL_FONT_FAMILY", FONT_FAMILY_BASE) or FONT_FAMILY_BASE)
MAINT_FONT_FAMILY      = (os.environ.get("MAINT_FONT_FAMILY", FONT_FAMILY_BASE) or FONT_FAMILY_BASE)
FONT_SIZE_ROW   = (os.environ.get("FONT_SIZE_ROW", "auto") or "auto")
FONT_SIZE_SB    = (os.environ.get("FONT_SIZE_SB", "auto") or "auto")
FONT_SIZE_DEBUG = (os.environ.get("FONT_SIZE_DEBUG", "auto") or "auto")
try: PREROLL_FONT_PX = int(os.environ.get("PREROLL_FONT_PX", "0") or 0)
except: PREROLL_FONT_PX = 0
try: MAINT_FONT_PX = int(os.environ.get("MAINT_FONT_PX", "0") or 0)
except: MAINT_FONT_PX = 0
FONT_BOLD_BASE  = os.environ.get("FONT_BOLD_BASE", "1") == "1"
FONT_BOLD_SB    = os.environ.get("FONT_BOLD_SB", "1") == "1"
FONT_BOLD_DEBUG = os.environ.get("FONT_BOLD_DEBUG", "0") == "1"
PREROLL_FONT_BOLD= os.environ.get("PREROLL_FONT_BOLD", "1") == "1"
MAINT_FONT_BOLD = os.environ.get("MAINT_FONT_BOLD", "1") == "1"

# --------------------------------------------------------------------------------
# SCOREBOARD CORE
# --------------------------------------------------------------------------------
SCOREBOARD_ENABLED  = os.environ.get("SCOREBOARD_ENABLED", "1") == "1"
SCOREBOARD_LEAGUES  = [s.strip().upper() for s in (os.environ.get("SCOREBOARD_LEAGUES", "NHL,NFL") or "").split(",") if s.strip()]
SCOREBOARD_NHL_TEAMS= [s.strip().upper() for s in (os.environ.get("SCOREBOARD_NHL_TEAMS", "MTL") or "").split(",") if s.strip()]
SCOREBOARD_NFL_TEAMS= [s.strip().upper() for s in (os.environ.get("SCOREBOARD_NFL_TEAMS", "NE") or "").split(",") if s.strip()]
SCOREBOARD_POLL_WINDOW_MIN = int(os.environ.get("SCOREBOARD_POLL_WINDOW_MIN", "120") or 120)
SCOREBOARD_POLL_CADENCE    = int(os.environ.get("SCOREBOARD_POLL_CADENCE", "60") or 60)
SCOREBOARD_LIVE_REFRESH    = int(os.environ.get("SCOREBOARD_LIVE_REFRESH", "45") or 45)
SCOREBOARD_PRECEDENCE      = (os.environ.get("SCOREBOARD_PRECEDENCE", "normal") or "normal").lower()
SCOREBOARD_LAYOUT          = (os.environ.get("SCOREBOARD_LAYOUT", "auto") or "auto").lower()
SCOREBOARD_UPPERCASE       = os.environ.get("SCOREBOARD_UPPERCASE", "1") == "1"
SCOREBOARD_HOME_FIRST      = os.environ.get("SCOREBOARD_HOME_FIRST", "1") == "1"
SCOREBOARD_SHOW_CLOCK      = os.environ.get("SCOREBOARD_SHOW_CLOCK", "1") == "1"
SCOREBOARD_SHOW_SOG        = os.environ.get("SCOREBOARD_SHOW_SOG", "1") == "1"
SCOREBOARD_SHOW_POSSESSION = os.environ.get("SCOREBOARD_SHOW_POSSESSION", "1") == "1"
SCOREBOARD_INCLUDE_OTHERS  = os.environ.get("SCOREBOARD_INCLUDE_OTHERS", "0") == "1"
SCOREBOARD_ONLY_MY_TEAMS   = os.environ.get("SCOREBOARD_ONLY_MY_TEAMS", "1") == "1"
SCOREBOARD_MAX_GAMES       = max(1, int(os.environ.get("SCOREBOARD_MAX_GAMES", "2") or 2))
SCOREBOARD_SCROLL_ENABLED  = os.environ.get("SCOREBOARD_SCROLL_ENABLED", "0") == "1"
try: SCOREBOARD_STATIC_DWELL_SEC = int(os.environ.get("SCOREBOARD_STATIC_DWELL_SEC", "4") or 4)
except Exception: SCOREBOARD_STATIC_DWELL_SEC = 4
SCOREBOARD_STATIC_ALIGN = (os.environ.get("SCOREBOARD_STATIC_ALIGN", "left") or "left").lower()

# --------------------------------------------------------------------------------
# SCOREBOARD TEST HARNESS
# --------------------------------------------------------------------------------
SCOREBOARD_TEST         = os.environ.get("SCOREBOARD_TEST", "0") == "1"
SCOREBOARD_TEST_LEAGUE  = (os.environ.get("SCOREBOARD_TEST_LEAGUE", "NHL") or "NHL").upper()
SCOREBOARD_TEST_HOME    = (os.environ.get("SCOREBOARD_TEST_HOME", "MTL") or "").upper()
SCOREBOARD_TEST_AWAY    = (os.environ.get("SCOREBOARD_TEST_AWAY", "TOR") or "").upper()
SCOREBOARD_TEST_DURATION= int(os.environ.get("SCOREBOARD_TEST_DURATION", "0") or 0)

# --------------------------------------------------------------------------------
# OVERRIDES (temporary modes)
# --------------------------------------------------------------------------------
OVERRIDE_MODE = (os.environ.get("OVERRIDE_MODE", "OFF") or "OFF").upper()  # "OFF","BRIGHT","SCOREBOARD","MESSAGE","MAINT","CLOCK"
try: OVERRIDE_DURATION_MIN = int(os.environ.get("OVERRIDE_DURATION_MIN", "0") or 0)
except: OVERRIDE_DURATION_MIN = 0
OVERRIDE_MESSAGE_TEXT = (os.environ.get("OVERRIDE_MESSAGE_TEXT", "") or "").strip()

# --------------------------------------------------------------------------------
# SCORE ALERTS (flashing scroll)
# --------------------------------------------------------------------------------
SCORE_ALERTS_ENABLED      = os.environ.get("SCORE_ALERTS_ENABLED", "1") == "1"
SCORE_ALERTS_NHL          = os.environ.get("SCORE_ALERTS_NHL", "1") == "1"
SCORE_ALERTS_NFL          = os.environ.get("SCORE_ALERTS_NFL", "1") == "1"
SCORE_ALERTS_MY_TEAMS_ONLY= os.environ.get("SCORE_ALERTS_MY_TEAMS_ONLY", "1") == "1"
try: SCORE_ALERTS_CYCLES     = int(os.environ.get("SCORE_ALERTS_CYCLES", "2") or 2)
except: SCORE_ALERTS_CYCLES   = 2
try: SCORE_ALERTS_QUEUE_MAX  = int(os.environ.get("SCORE_ALERTS_QUEUE_MAX", "4") or 4)
except: SCORE_ALERTS_QUEUE_MAX= 4
try: SCORE_ALERTS_FLASH_MS   = int(os.environ.get("SCORE_ALERTS_FLASH_MS", "250") or 250)
except: SCORE_ALERTS_FLASH_MS = 250
SCORE_ALERTS_FLASH_COLORS = [c.strip().lower() for c in (os.environ.get("SCORE_ALERTS_FLASH_COLORS", "red,white,blue") or "red,white,blue").split(",") if c.strip()]
try: SCORE_ALERTS_NFL_TD_DELTA_MIN = int(os.environ.get("SCORE_ALERTS_NFL_TD_DELTA_MIN","6") or 6)
except: SCORE_ALERTS_NFL_TD_DELTA_MIN = 6
SCORE_ALERTS_TEST        = os.environ.get("SCORE_ALERTS_TEST", "0") == "1"
SCORE_ALERTS_TEST_LEAGUE = (os.environ.get("SCORE_ALERTS_TEST_LEAGUE","NHL") or "NHL").upper()
SCORE_ALERTS_TEST_TEAM   = (os.environ.get("SCORE_ALERTS_TEST_TEAM","MTL") or "MTL").upper()
try: SCORE_ALERTS_TEST_INTERVAL_SEC = int(os.environ.get("SCORE_ALERTS_TEST_INTERVAL_SEC","12") or 12)
except: SCORE_ALERTS_TEST_INTERVAL_SEC = 12

# --------------------------------------------------------------------------------
# MICROFONT
# --------------------------------------------------------------------------------
MICROFONT_ENABLED = os.environ.get("MICROFONT_ENABLED", "0") == "1"  # In dual layout, use a crisp 5x7 microfont for row text.

# =================================================================================================
# ============================== Ticker lists + holdings (defaults) ===============================
# =================================================================================================
# The default symbol sets (overridable in config.json as TICKERS_TOP/BOT).
TICKERS_TOP = [
    ("^IXIC", "NAS"),
    ("^GSPC", "S&P"),  # S&P 500
    ("^GSPTSE", "TSX"),
    ("CADUSD=X", "CAD/USD"),
    ("GC=F", "GOLD"),
]
TICKERS_BOT = [
    ("AAPL", ""),
    ("MSFT", ""),
    ("GOOGL", ""),
    ("AMZN", ""),
    ("NVDA", ""),
    ("TSLA", ""),
    ("META", ""),
    ("TSM", ""),
]
TICKERS_BOT2 = []  # Alternate bottom row (shown every other scroll); empty = no alternating
HOLDINGS_ENABLED = False
HOLDINGS = {}  # {"SYM": {"shares": float}, ...}

# Default weathers have a sticky time in seconds (show for X seconds after active).
try: WEATHER_STICKY_SEC = int(os.environ.get("WEATHER_STICKY_SEC", "12") or 12)
except: WEATHER_STICKY_SEC = 12

# =================================================================================================
# ===================================== PANEL/LAYOUT SETUP ========================================
# =================================================================================================
def _resolve_tz():
    """Return a pytz timezone for TICKER_TZ if available, else None."""
    if not PYTZ_AVAILABLE:
        return None
    try:
        return pytz.timezone(TICKER_TZ)
    except Exception:
        print(f"[WARN] Timezone '{TICKER_TZ}' invalid; using local system time.", flush=True)
        return None

def _resolve_panel_size():
    """
    Auto-detect or override WxH. If both W and H are specified in env/config, use them.
    Otherwise infer from MODEL_NAME. If both are 0, default to 96x16 for safety.
    """
    global W, H
    if W > 0 and H > 0:
        return
    mn = (MODEL_NAME or "").lower()
    if "96x32" in mn:
        W, H = 96, 32
    elif "192x16" in mn:
        W, H = 192, 16
    elif "96x16" in mn:
        W, H = 96, 16
    else:
        W, H = max(1, W), max(1, H)  # keep env overrides if user-provided
        if W <= 0 or H <= 0:
            W, H = 96, 16

_resolve_panel_size()
IS_SINGLE = False
IS_DUAL   = False
ROW_H, TOP_Y, BOT_Y = H, 0, 0  # Will be recomputed in _recompute_layout_globals

TZINFO = _resolve_tz()

# --- Top-of-hour helper: compute the next local hour boundary (aligned to wall clock) ---
def _compute_next_hour_ts(now_dt=None):
    # Return a unix timestamp for the next top-of-hour in local tz.
    if now_dt is None:
        now_dt = now_local()
    hour_start = now_dt.replace(minute=0, second=0, microsecond=0)
    next_hour = hour_start + timedelta(hours=1)
    return next_hour.timestamp()


# Score Alerts - colors via parse_color
_SCORE_FLASH_COLORS = [parse_color(c) for c in (SCORE_ALERTS_FLASH_COLORS or ['red','white','blue'])]

class ScoreAlert:
    """Flashing static banner for GOAL/TOUCHDOWN events."""
    def __init__(self, league: str, team: str, score: int, cycles: int):
        self.league = league
        self.team = team
        self.score = score
        n = max(1, len(_SCORE_FLASH_COLORS))
        self.flashes_left = max(1, cycles) * n
        self.flash_idx = 0
        self.flash_next_ts = time.time() + (SCORE_ALERTS_FLASH_MS / 1000.0)

    def current_color(self):
        now = time.time()
        if now >= self.flash_next_ts:
            self.flash_idx = (self.flash_idx + 1) % max(1, len(_SCORE_FLASH_COLORS))
            self.flash_next_ts = now + (SCORE_ALERTS_FLASH_MS / 1000.0)
            self.flashes_left -= 1
        return _SCORE_FLASH_COLORS[self.flash_idx]

    @property
    def done(self):
        return self.flashes_left <= 0

# =================================================================================================
# ============================ config loader + hot reload (config.json) ============================
# =================================================================================================
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticker_status.json")
_cfg_mtime = 0.0

def _atomic_load_json(path: str) -> dict:
    """Load JSON safely ({} on error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _recompute_layout_globals():
    """Recompute layout flags and row geometry after W/H/LAYOUT changes."""
    global W, H, LAYOUT, IS_SINGLE, IS_DUAL, ROW_H, TOP_Y, BOT_Y
    _resolve_panel_size()
    if not LAYOUT:
        LAYOUT = "dual" if H >= 16 else "single"
    IS_SINGLE = (LAYOUT == "single")
    IS_DUAL   = (LAYOUT == "dual")
    if IS_DUAL:
        ROW_H = H // 2; TOP_Y = 0; BOT_Y = ROW_H
    else:
        ROW_H = H; TOP_Y = 0; BOT_Y = 0

def _apply_config(cfg: dict) -> dict:
    """Apply config.json into globals and set 'changed' flags per category."""
    g = globals()
    changed = {"any": False, "layout": False, "dim": False, "markets": False, "scoreboard": False, "override": False, "weather": False, "message": False}
    def set_if(key):
        if key not in cfg: return
        old = g.get(key, None); new = cfg[key]
        # Apply transformations for specific keys
        if key == "PREROLL_STYLE" and isinstance(new, str):
            new = new.upper()
        if key in ("OVERRIDE_MODE",) and isinstance(new, str):
            new = new.upper()
        if old != new:
            g[key] = new; changed["any"]=True
            # Treat clock tunables as "override" changes so they apply immediately
            if key.startswith("CLOCK_"): changed["override"] = True
            if key in ("MODEL_NAME","W","H","LAYOUT"): changed["layout"]=True
            if key.startswith("NIGHT_MODE") or key == "QUICK_DIM_PCT": changed["dim"]=True
            if key in ("TICKERS_TOP","TICKERS_BOT","TICKERS_BOT2","HOLDINGS","HOLDINGS_ENABLED"): changed["markets"]=True
            if key.startswith("SCOREBOARD_"): changed["scoreboard"]=True
            if key.startswith("OVERRIDE_"):   changed["override"]=True
            if key.startswith("WEATHER_"):    changed["weather"]=True
            if key in ("INJECT_MESSAGE","MESSAGE_EVERY","MESSAGE_ROW","MESSAGE_COLOR","MESSAGE_TEST_FORCE"): changed["message"]=True

    for k in [
        "RGB_BRIGHTNESS","RGB_HARDWARE_MAPPING","RGB_GPIO_SLOWDOWN","RGB_PWM_BITS","RGB_PWM_LSB_NANOSECONDS",
        "RGB_CHAIN_LENGTH","RGB_PARALLEL","RGB_SCAN_MODE","RGB_ROW_ADDRESS_TYPE","RGB_MULTIPLEXING",
        "RGB_LED_RGB_SEQUENCE","RGB_PIXEL_MAPPER","RGB_PANEL_TYPE",
        "MODEL_NAME","W","H","LAYOUT","TICKER_TZ",
        "FPS","PPS_TOP","PPS_BOT","PPS_SINGLE","REFRESH_SEC","FRESH_SEC",
        "TIME_PREROLL_ENABLED","TIME_PREROLL_SEC","PREROLL_STYLE","PREROLL_COLOR","PREROLL_PPS",
        "MAINTENANCE_MODE","MAINTENANCE_TEXT","MAINTENANCE_SCROLL","MAINTENANCE_PPS",
        "WEATHER_RSS_URL","WEATHER_REFRESH_SEC","WEATHER_ANNOUNCE_SEC","WEATHER_TIMEOUT",
        "WEATHER_INCLUDE_WATCH","WEATHER_FORCE_ACTIVE","WEATHER_FORCE_TEXT","WEATHER_TEST_DELAY","WEATHER_WARNING_EVERY_N_SCROLLS","WEATHER_WARNING_COLOR","WEATHER_ADVISORY_EVERY_N_SCROLLS","WEATHER_ADVISORY_COLOR","WEATHER_STICKY_SEC","WEATHER_TEST_STICKY_TOTAL","WEATHER_REPEAT_SEC",
        "INJECT_MESSAGE","MESSAGE_EVERY","MESSAGE_ROW","MESSAGE_COLOR","MESSAGE_TEST_FORCE",
        "NIGHT_MODE_ENABLED","NIGHT_MODE_START","NIGHT_MODE_END","NIGHT_MODE_DIM_PCT","NIGHT_MODE_SPEED_PCT","QUICK_DIM_PCT",
        "FONT_FAMILY_BASE","FONT_FAMILY_SCOREBOARD","FONT_FAMILY_DEBUG","PREROLL_FONT_FAMILY","MAINT_FONT_FAMILY",
        "FONT_SIZE_ROW","FONT_SIZE_SB","FONT_SIZE_DEBUG","PREROLL_FONT_PX","MAINT_FONT_PX",
        "FONT_BOLD_BASE","FONT_BOLD_SB","FONT_BOLD_DEBUG","PREROLL_FONT_BOLD","MAINT_FONT_BOLD",
        "SCOREBOARD_ENABLED","SCOREBOARD_LEAGUES","SCOREBOARD_NHL_TEAMS","SCOREBOARD_NFL_TEAMS",
        "SCOREBOARD_POLL_WINDOW_MIN","SCOREBOARD_POLL_CADENCE","SCOREBOARD_LIVE_REFRESH",
        "SCOREBOARD_PREGAME_WINDOW_MIN","SCOREBOARD_POSTGAME_DELAY_MIN","SCOREBOARD_SHOW_COUNTDOWN",
        "SCOREBOARD_PRECEDENCE","SCOREBOARD_LAYOUT","SCOREBOARD_UPPERCASE","SCOREBOARD_HOME_FIRST",
        "SCOREBOARD_SHOW_CLOCK","SCOREBOARD_SHOW_SOG","SCOREBOARD_SHOW_POSSESSION",
        "SCOREBOARD_INCLUDE_OTHERS","SCOREBOARD_ONLY_MY_TEAMS","SCOREBOARD_MAX_GAMES",
        "SCOREBOARD_SCROLL_ENABLED","SCOREBOARD_STATIC_DWELL_SEC","SCOREBOARD_STATIC_ALIGN",
        "OVERRIDE_MODE","OVERRIDE_DURATION_MIN","OVERRIDE_MESSAGE_TEXT",
        "SCORE_ALERTS_ENABLED","SCORE_ALERTS_NHL","SCORE_ALERTS_NFL","SCORE_ALERTS_MY_TEAMS_ONLY",
        "SCORE_ALERTS_CYCLES","SCORE_ALERTS_QUEUE_MAX","SCORE_ALERTS_FLASH_MS","SCORE_ALERTS_FLASH_COLORS",
        "SCORE_ALERTS_NFL_TD_DELTA_MIN","SCORE_ALERTS_TEST","SCORE_ALERTS_TEST_LEAGUE","SCORE_ALERTS_TEST_TEAM","SCORE_ALERTS_TEST_INTERVAL_SEC",
        "TICKERS_TOP","TICKERS_BOT","TICKERS_BOT2","HOLDINGS_ENABLED","HOLDINGS",
        "MICROFONT_ENABLED",
        "SCOREBOARD_TEST","SCOREBOARD_TEST_LEAGUE","SCOREBOARD_TEST_HOME","SCOREBOARD_TEST_AWAY","SCOREBOARD_TEST_DURATION",
        # CLOCK override tunables
        "CLOCK_24H","CLOCK_SHOW_SECONDS","CLOCK_BLINK_COLON","CLOCK_COLOR","CLOCK_DATE_SHOW","CLOCK_DATE_FMT","CLOCK_DATE_COLOR",
        # Diagnostics and test flags
        "DEBUG_OVERLAY","DEMO_MODE",
    ]:
        set_if(k)

    if changed["layout"]: _recompute_layout_globals()
    return changed

def _initial_config_load():
    """Load config.json once at startup (BEFORE printing the banner)."""
    global _cfg_mtime, TZINFO
    try:
        cfg = _atomic_load_json(CONFIG_PATH)
        if cfg:
            changes = _apply_config(cfg)
            try: _cfg_mtime = os.path.getmtime(CONFIG_PATH)
            except Exception: _cfg_mtime = 0.0
            TZINFO = _resolve_tz()
            print(f"[START] Loaded config.json from {CONFIG_PATH} (changes: {changes})", flush=True)
        else:
            print(f"[START] No config.json overrides found at {CONFIG_PATH}", flush=True)
    except Exception as e:
        print(f"[START] config.json load error: {e}", flush=True)

def _maybe_reload_config() -> dict:
    """Hot-reload config.json when mtime changes; return change flags."""
    global _cfg_mtime, TZINFO
    try:
        m = os.path.getmtime(CONFIG_PATH)
    except Exception:
        return {"reloaded": False}
    if m <= _cfg_mtime:
        return {"reloaded": False}
    cfg = _atomic_load_json(CONFIG_PATH)
    changes = _apply_config(cfg)
    _cfg_mtime = m
    TZINFO = _resolve_tz()
    print(f"[CFG] Reloaded config.json (flags: {changes})", flush=True)
    return {"reloaded": True, **changes}

# =================================================================================================
# =========================================== MAIN ================================================
# =================================================================================================
def run_maintenance_loop(screen, clock, maint_font):
    """
    Minimal maintenance mode loop: just scroll MAINTENANCE_TEXT indefinitely.
    Press Ctrl+C or send SIGTERM to exit.
    """
    import pygame
    x = float(W)
    txt = (MAINTENANCE_TEXT or "MAINTENANCE").upper()
    srf = maint_font.render(txt, True, WHITE)
    pps = max(1.0, float(MAINTENANCE_PPS))
    while True:
        dt = clock.tick(FPS)/1000.0
        frame = pygame.Surface((W, H)); frame.fill(BLACK)
        if MAINTENANCE_SCROLL:
            w = srf.get_width()
            y = max(0, (H - srf.get_height())//2)
            if -w < x < W: frame.blit(srf, (_sp(x), y))
            x -= pps*dt
            if x < -w: x = float(W)
        else:
            wt = srf.get_width()
            xt = max(0, (W - wt)//2)
            y = max(0, (H - srf.get_height())//2)
            frame.blit(srf, (xt, y))
        write_surface_to_rgb_matrix(frame)
        try:
            pygame.image.save(frame, "/tmp/ticker_preview.png")
        except Exception:
            pass

# Global shutdown flag
_shutdown_requested = False

def _signal_handler(signum, frame):
    """Handle SIGTERM and SIGINT gracefully."""
    global _shutdown_requested
    sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n[SIGNAL] Received {sig_name}, initiating clean shutdown...", flush=True)
    _shutdown_requested = True


def _terminate_worker(proc):
    """Terminate a worker process gracefully, falling back to kill."""
    if proc and proc.is_alive():
        proc.terminate()
        proc.join(timeout=1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=0.5)


def _push_alert(alert_queue, entry):
    """Push an alert entry onto the alert_queue, evicting oldest if full."""
    if len(alert_queue) >= alert_queue.maxlen:
        try:
            alert_queue.popleft()
        except Exception:
            pass
    alert_queue.append(entry)


def _extract_live_game_data(scoreboard_latest):
    """Find the first live game in scoreboard_latest and return a game_data dict, or None."""
    for league_key in ("NHL", "NFL"):
        payload = scoreboard_latest.get(league_key)
        if payload and payload.get("games"):
            for g in payload["games"]:
                if g.get("state") == "LIVE":
                    home_code = g.get("home", {}).get("code", "???")
                    away_code = g.get("away", {}).get("code", "???")
                    home_score = g.get("home", {}).get("score", 0)
                    away_score = g.get("away", {}).get("score", 0)
                    game_clock = g.get("clock", "")
                    period = g.get("period_label", "")
                    if not period:
                        period_num = g.get("period", 0)
                        if league_key == "NHL":
                            period = "OT" if period_num > 3 else f"P{period_num}"
                        elif league_key == "NFL":
                            period = f"Q{period_num}"
                    return {
                        "home_code": home_code,
                        "away_code": away_code,
                        "home_score": home_score,
                        "away_score": away_score,
                        "clock": game_clock,
                        "period": period,
                        "league": league_key
                    }
    return None

def run():
    global _shutdown_requested
    
    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    
    # 1) Load config first
    _initial_config_load()
    
    # No longer need SHM_PATH with RGB Matrix mode
    
    # 2) Initialize rendering module globals
    set_rendering_globals(
        W=W, H=H, LAYOUT=LAYOUT, ROW_H=ROW_H, TOP_Y=TOP_Y, BOT_Y=BOT_Y,
        IS_SINGLE=IS_SINGLE, IS_DUAL=IS_DUAL,
        MICROFONT_ENABLED=MICROFONT_ENABLED,
        TZINFO=TZINFO,
        NIGHT_MODE_ENABLED=NIGHT_MODE_ENABLED,
        NIGHT_MODE_START=NIGHT_MODE_START,
        NIGHT_MODE_END=NIGHT_MODE_END,
        NIGHT_MODE_DIM_PCT=NIGHT_MODE_DIM_PCT,
        NIGHT_MODE_SPEED_PCT=NIGHT_MODE_SPEED_PCT,
        QUICK_DIM_PCT=QUICK_DIM_PCT,
        HOLDINGS=HOLDINGS,
        HOLDINGS_ENABLED=HOLDINGS_ENABLED,
        FONT_FAMILY_BASE=FONT_FAMILY_BASE,
        FONT_SIZE_ROW=FONT_SIZE_ROW,
        FONT_BOLD_BASE=FONT_BOLD_BASE,
        FONT_FAMILY_SCOREBOARD=FONT_FAMILY_SCOREBOARD,
        FONT_SIZE_SB=FONT_SIZE_SB,
        FONT_BOLD_SB=FONT_BOLD_SB,
        FONT_FAMILY_DEBUG=FONT_FAMILY_DEBUG,
        FONT_SIZE_DEBUG=FONT_SIZE_DEBUG,
        FONT_BOLD_DEBUG=FONT_BOLD_DEBUG,
        PREROLL_FONT_FAMILY=PREROLL_FONT_FAMILY,
        PREROLL_FONT_PX=PREROLL_FONT_PX,
        PREROLL_FONT_BOLD=PREROLL_FONT_BOLD,
        PREROLL_COLOR=PREROLL_COLOR,
        MAINT_FONT_FAMILY=MAINT_FONT_FAMILY,
        MAINT_FONT_PX=MAINT_FONT_PX,
        MAINT_FONT_BOLD=MAINT_FONT_BOLD,
        CLOCK_24H=CLOCK_24H,
        CLOCK_SHOW_SECONDS=CLOCK_SHOW_SECONDS,
        CLOCK_BLINK_COLON=CLOCK_BLINK_COLON,
        CLOCK_COLOR=CLOCK_COLOR,
        CLOCK_DATE_SHOW=CLOCK_DATE_SHOW,
        CLOCK_DATE_FMT=CLOCK_DATE_FMT,
        CLOCK_DATE_COLOR=CLOCK_DATE_COLOR
    )
    # 3) Show banner
    start_ts = time.time()

    print("="*80, flush=True)
    print(f"[START] LED Ticker {W}x{H} (layout={LAYOUT}, fps={FPS})", flush=True)
    print(f"[START] Timezone: {TICKER_TZ} (TZINFO={TZINFO})", flush=True)
    print(f"[START] Config file: {CONFIG_PATH}", flush=True)
    if DEMO_MODE: print("[START] DEMO MODE: no network calls", flush=True)
    if DEBUG_OVERLAY: print("[START] DEBUG overlay ON (bottom line)", flush=True)
    if MICROFONT_ENABLED and IS_DUAL: print("[START] Microfont enabled for dual layout row text", flush=True)
    if TIME_PREROLL_ENABLED:
        print(f"[START] Time preroll: ENABLED {TIME_PREROLL_SEC}s style={PREROLL_STYLE} color={PREROLL_COLOR} pps={PREROLL_PPS}", flush=True)
    else:
        print(f"[START] Time preroll: DISABLED", flush=True)
    print(f"[START] Weather worker: RSS={bool(WEATHER_RSS_URL)} force_active={int(WEATHER_FORCE_ACTIVE)} test_delay={WEATHER_TEST_DELAY} announce={WEATHER_ANNOUNCE_SEC}s repeat={WEATHER_REPEAT_SEC}s", flush=True)
    if NIGHT_MODE_ENABLED:
        print(f"[START] Night Mode: {NIGHT_MODE_START}-{NIGHT_MODE_END} dim={NIGHT_MODE_DIM_PCT}% speed={NIGHT_MODE_SPEED_PCT}%", flush=True)
    if INJECT_MESSAGE and MESSAGE_EVERY>0: print(f"[START] Message injector: every {MESSAGE_EVERY} scrolls row={MESSAGE_ROW} color={MESSAGE_COLOR}", flush=True)
    if MESSAGE_TEST_FORCE: print("[START] Message TEST: force every scroll", flush=True)
    if MAINTENANCE_MODE: print(f"[START] Maintenance: scroll={int(MAINTENANCE_SCROLL)} pps={MAINTENANCE_PPS}", flush=True)
    if SCOREBOARD_ENABLED:
        print(f"[START] Scoreboard: leagues={SCOREBOARD_LEAGUES} NHL={SCOREBOARD_NHL_TEAMS} NFL={SCOREBOARD_NFL_TEAMS} test={int(SCOREBOARD_TEST)} precedence={SCOREBOARD_PRECEDENCE} my_only={int(SCOREBOARD_ONLY_MY_TEAMS)}", flush=True)
        print(f"[START] Scoreboard scroll={'ON' if SCOREBOARD_SCROLL_ENABLED else 'OFF'} align={SCOREBOARD_STATIC_ALIGN} dwell={SCOREBOARD_STATIC_DWELL_SEC}s", flush=True)
    if SCORE_ALERTS_ENABLED:
        print(f"[START] Score Alerts: NHL={int(SCORE_ALERTS_NHL)} NFL={int(SCORE_ALERTS_NFL)} my_only={int(SCORE_ALERTS_MY_TEAMS_ONLY)} cycles={SCORE_ALERTS_CYCLES} queue={SCORE_ALERTS_QUEUE_MAX} flash_ms={SCORE_ALERTS_FLASH_MS} test={int(SCORE_ALERTS_TEST)}", flush=True)

    # Compute override AFTER config load (and keep variables mutable for reload)
    override_mode = OVERRIDE_MODE if OVERRIDE_MODE in ("BRIGHT","SCOREBOARD","MESSAGE","MAINT","CLOCK") else "OFF"
    override_active = (override_mode != "OFF")
    override_end_ts = (time.time() + OVERRIDE_DURATION_MIN*60) if (override_active and OVERRIDE_DURATION_MIN>0) else None
    if override_active:
        dur_str = f"{OVERRIDE_DURATION_MIN} min" if OVERRIDE_DURATION_MIN>0 else "until cleared"
        print(f"[START] OVERRIDE: {override_mode} for {dur_str}", flush=True)

    ALL_TICKERS = sorted({s for s,_ in (TICKERS_TOP+TICKERS_BOT+(TICKERS_BOT2 or []))})
    # Queues with maxsize to prevent unbounded memory growth
    mq=Queue(maxsize=10); wq=Queue(maxsize=5); sbq=Queue(maxsize=20)
    
    # Start workers with current config - we'll track them for restart
    workers = {"market": None, "weather": None, "scoreboard": None}
    
    if not DEMO_MODE:
        workers["market"] = Process(target=market_worker,  args=(ALL_TICKERS, REFRESH_SEC, mq, STATUS_PATH, TZINFO), daemon=True)
        workers["weather"] = Process(target=weather_worker, args=(WEATHER_RSS_URL, WEATHER_INCLUDE_WATCH, WEATHER_REFRESH_SEC, WEATHER_TIMEOUT, WEATHER_FORCE_ACTIVE, WEATHER_FORCE_TEXT, wq, STATUS_PATH, TZINFO), daemon=True)
        workers["market"].start(); workers["weather"].start()
        print("[WORKERS] Market and Weather workers started", flush=True)
        if SCOREBOARD_ENABLED:
            test_cfg = {
                "enabled":SCOREBOARD_TEST, "league":SCOREBOARD_TEST_LEAGUE,
                "home":SCOREBOARD_TEST_HOME, "away":SCOREBOARD_TEST_AWAY,
                "duration":SCOREBOARD_TEST_DURATION
            }
            workers["scoreboard"] = Process(target=scoreboard_worker,
                       args=(SCOREBOARD_LEAGUES, SCOREBOARD_NHL_TEAMS, SCOREBOARD_NFL_TEAMS,
                             SCOREBOARD_POLL_WINDOW_MIN, SCOREBOARD_POLL_CADENCE, SCOREBOARD_LIVE_REFRESH,
                             SCOREBOARD_INCLUDE_OTHERS, SCOREBOARD_ONLY_MY_TEAMS, SCOREBOARD_MAX_GAMES,
                             test_cfg, sbq, STATUS_PATH, TZINFO, SCOREBOARD_PREGAME_WINDOW_MIN, SCOREBOARD_POSTGAME_DELAY_MIN),
                       daemon=True)
            workers["scoreboard"].start()
            print("[SB] worker spawned", flush=True)

    screen, clock = init_pygame()

    print("[RGB Matrix] Initializing RGB Matrix...", flush=True)
    rgb_init_success = init_rgb_matrix(
        width=W,
        height=H,
        brightness=RGB_BRIGHTNESS,
        hardware_mapping=RGB_HARDWARE_MAPPING,
        gpio_slowdown=RGB_GPIO_SLOWDOWN,
        pwm_bits=RGB_PWM_BITS,
        pwm_lsb_nanoseconds=RGB_PWM_LSB_NANOSECONDS,
        chain_length=RGB_CHAIN_LENGTH,
        parallel=RGB_PARALLEL,
        scan_mode=RGB_SCAN_MODE,
        row_address_type=RGB_ROW_ADDRESS_TYPE,
        multiplexing=RGB_MULTIPLEXING,
        led_rgb_sequence=RGB_LED_RGB_SEQUENCE,
        pixel_mapper=RGB_PIXEL_MAPPER,
        panel_type=RGB_PANEL_TYPE
    )
    if not rgb_init_success:
        print("[RGB Matrix] FATAL: Failed to initialize RGB Matrix", flush=True)
        print("[RGB Matrix] Check that you're running as root and rpi-rgb-led-matrix is installed", flush=True)
        sys.exit(1)
    
    global font_row, font_dbg, font_sb
    font_row = get_row_font()
    font_dbg = get_dbg_font()
    font_sb  = get_sb_font()
    set_fonts(font_row, font_dbg, font_sb)  # Set fonts in rendering module
    maint_big_font  = get_maint_big_font()
    preroll_big_font= get_preroll_big_font()

    if MAINTENANCE_MODE and not override_active:
        print("[MAINT] Maintenance active; entering maintenance loop.", flush=True)
        return run_maintenance_loop(screen, clock, font_row)

    # Create message surface after fonts are initialized
    injector_active = bool(INJECT_MESSAGE and MESSAGE_EVERY>0)
    msg_surface = None
    if injector_active:
        col = parse_color(MESSAGE_COLOR)
        msg_surface = build_message_surface(INJECT_MESSAGE, col, font_row)

    market_cache={}; market_state="UNKNOWN"; last_success_ts=0.0; last_result_ok=False
    weather_active=False; weather_message=""
    scoreboard_latest = {}  # league -> payload
    # Full-height scoreboard state
    scoreboard_flash = ScoreboardFlashState()
    last_scores_fullheight = {}
    last_scores = {}
    alert_queue = deque(maxlen=max(1, SCORE_ALERTS_QUEUE_MAX))
    alert_obj = None
    alert_test_last_ts = 0.0
    
    # Initialize ticker parts NOW (after market_cache exists but with empty cache)
    # This prevents black screen on startup
    single_parts, top_parts, bot_parts = [], [], []
    try:
        single_parts,_ = build_row_surfaces_from_cache(TICKERS_TOP+TICKERS_BOT, market_cache, font_row, HOLDINGS_ENABLED)
        top_parts,_    = build_row_surfaces_from_cache(TICKERS_TOP, market_cache, font_row, HOLDINGS_ENABLED)
        bot_parts,_    = build_row_surfaces_from_cache(TICKERS_BOT, market_cache, font_row, HOLDINGS_ENABLED)
        bot_parts2,_   = build_row_surfaces_from_cache(TICKERS_BOT2, market_cache, font_row, HOLDINGS_ENABLED) if TICKERS_BOT2 else ([], False)
        print(f"[INIT] Built initial ticker parts: {len(single_parts)} single, {len(top_parts)} top, {len(bot_parts)} bot, {len(bot_parts2)} bot2", flush=True)
    except Exception as e:
        print(f"[INIT] Failed to build initial ticker parts: {e}", flush=True)
    
    # RGB Matrix error tracking (suppress repeated errors)
    shm_last_error = None
    shm_error_count = 0
    shm_last_error_print = 0.0
    shm_write_success = False  # Track first successful write

    # --- Weather banner state machine (sticky / re-announce) ---
    weather_banner = {
        "active": False,          # last-known active flag from worker or test
        "message": "",            # last headline
        "severity": "",           # severity level (warning, advisory, watch)
        "show_until": 0.0,        # wallclock ts until which the banner must remain pinned
        "next_repeat_at": 0.0,    # earliest time allowed to re-pin while still active
        "test_forced_until": 0.0  # when in test harness, how long we pretend it's still active
    }

    def poll_queues_nonblock():
        """Non-blocking drain of worker queues into local caches."""
        nonlocal market_cache, market_state, last_success_ts, last_result_ok
        nonlocal weather_active, weather_message
        nonlocal scoreboard_latest, weather_banner
        if not DEMO_MODE:
            try:
                while True:
                    msg = mq.get_nowait()
                    if msg.get("type")=="market":
                        payload = msg["payload"]
                        market_cache = payload.get("data",{}) or {}
                        market_state = (payload.get("market_state") or "UNKNOWN").upper()
                        if payload.get("ok_any", False):
                            last_success_ts = payload.get("ts", time.time()); last_result_ok=True
                        else:
                            last_result_ok=False
            except queue_std.Empty: pass
            try:
                while True:
                    msg = wq.get_nowait()
                    if msg.get("type")=="weather":
                        payload = msg["payload"]
                        weather_active = bool(payload.get("active",False))
                        weather_message = payload.get("message","") or ""
                        weather_severity = payload.get("severity","") or ""
                        # Sticky pin logic driven by worker cadence
                        now = time.time()
                        new_msg = (weather_message or "").strip()
                        if weather_active:
                            if (not weather_banner["active"]) or (new_msg and new_msg != weather_banner["message"]):
                                weather_banner["active"] = True
                                weather_banner["message"] = new_msg or "Weather alert"
                                weather_banner["severity"] = weather_severity
                                # Don't use show_until - using scroll-count display instead
                        else:
                            weather_banner["active"] = False
            except queue_std.Empty: pass
            if SCOREBOARD_ENABLED:
                try:
                    while True:
                        msg = sbq.get_nowait()
                        if msg.get("type")=="scoreboard":
                            payload = msg["payload"]; league=(payload.get("league") or "").upper()
                            if league:
                                scoreboard_latest[league]=payload
                except queue_std.Empty: pass

    def detect_score_bursts():
        """Look for score deltas and enqueue GOAL/TOUCHDOWN alerts."""
        if not SCORE_ALERTS_ENABLED: return
        for league_key in ("NHL","NFL"):
            p = scoreboard_latest.get(league_key)
            if not p: continue
            for g in (p.get("games") or []):
                gid = str(g.get("id") or f"{g['home']['code']}-{g['away']['code']}")
                k = f"{league_key}:{gid}"
                hs = int(g["home"].get("score", 0) or 0)
                as_ = int(g["away"].get("score", 0) or 0)
                prev = last_scores.get(k)
                if prev is None:
                    last_scores[k]=(hs,as_,True); continue
                ph, pa, _ = prev
                last_scores[k]=(hs,as_,True)
                if (g.get("state") or "") != "LIVE":
                    continue
                dh = hs - ph; da = as_ - pa
                scored = None
                if league_key=="NHL" and SCORE_ALERTS_NHL:
                    if dh>0: scored="home"
                    elif da>0: scored="away"
                elif league_key=="NFL" and SCORE_ALERTS_NFL:
                    if dh>=SCORE_ALERTS_NFL_TD_DELTA_MIN: scored="home"
                    elif da>=SCORE_ALERTS_NFL_TD_DELTA_MIN: scored="away"
                if not scored: continue
                team = g[scored]["code"].upper()
                if SCORE_ALERTS_MY_TEAMS_ONLY:
                    if league_key=="NHL" and team not in set(SCOREBOARD_NHL_TEAMS): continue
                    if league_key=="NFL" and team not in set(SCOREBOARD_NFL_TEAMS): continue
                score = hs if scored == "home" else as_
                _push_alert(alert_queue, {"league": league_key, "team": team, "score": score})

    def generate_test_alert():
        """Generate periodic test alerts when SCORE_ALERTS_TEST is enabled."""
        nonlocal alert_test_last_ts
        if not SCORE_ALERTS_TEST: return
        if not SCORE_ALERTS_ENABLED: return
        now = time.time()
        if now - alert_test_last_ts < SCORE_ALERTS_TEST_INTERVAL_SEC:
            return
        alert_test_last_ts = now
        test_count = int(now / SCORE_ALERTS_TEST_INTERVAL_SEC) % 10
        score = 2 + test_count
        _push_alert(alert_queue, {"league": SCORE_ALERTS_TEST_LEAGUE, "team": SCORE_ALERTS_TEST_TEAM, "score": score})

    _goal_logged = {}  # track which game_id goals we already logged

    def detect_goals():
        """Detect score changes and trigger flash animation."""
        nonlocal last_scores_fullheight
        if not scoreboard_latest:
            return

        for league, payload in scoreboard_latest.items():
            for game in (payload.get("games") or []):
                game_id = game.get("id", "")
                if not game_id or game.get("state") != "LIVE":
                    continue

                home_score = game.get("home", {}).get("score", 0)
                away_score = game.get("away", {}).get("score", 0)

                prev = last_scores_fullheight.get(game_id, {})
                prev_home = prev.get("home", home_score)
                prev_away = prev.get("away", away_score)

                if home_score > prev_home:
                    scoreboard_flash.start_flash("home", cycles=4)
                    log_key = f"{game_id}_home_{home_score}"
                    if log_key not in _goal_logged:
                        _goal_logged[log_key] = True
                        print(f"[GOAL FLASH] Home scored! {game['home']['code']} ({home_score})", flush=True)
                elif away_score > prev_away:
                    scoreboard_flash.start_flash("away", cycles=4)
                    log_key = f"{game_id}_away_{away_score}"
                    if log_key not in _goal_logged:
                        _goal_logged[log_key] = True
                        print(f"[GOAL FLASH] Away scored! {game['away']['code']} ({away_score})", flush=True)

                last_scores_fullheight[game_id] = {"home": home_score, "away": away_score}

    # State machine
    STATE_TICKER, STATE_PREROLL, STATE_SCOREBOARD = "TK", "PR", "SB"
    state = STATE_TICKER; state_enter_ts = time.time()
    preroll_reason = "hour"  # "hour", "market_open", or "market_close"
    next_top_ts = _compute_next_hour_ts()  # Compute actual next top of hour
    prefetch_done_for_this_hour = False
    weather_test_injected = False

    # Scrolling state
    x_single, x_top, x_bot = float(W), float(W), float(W)
    x_maint = float(W)  # Scrolling position for maintenance mode
    completed_single, completed_top, completed_bot = 0, 0, 0
    show_msg_single = show_msg_top = show_msg_bot = False
    weather_scroll_shown = False  # Track if currently showing weather
    
    # Property of solutions reseaux chromatel
    # Track market event announcement timing
    market_announcement_last_shown = 0.0
    market_announcement_interval = 300  # Show every 5 minutes
    
    # Track last market event (for preroll triggering)
    last_market_event = None  # Will be "open" or "close"
    market_event_shown_today = set()  # Track which events we've already shown today

    # MARKET OPEN persistent scroll injection (5 scrolls, once per day)
    market_open_srf = None          # Rendered surface for *** MARKET OPEN ***
    market_open_scrolls_left = 0    # Decremented on each top/single scroll completion
    market_open_scroll_date = None  # Date object when armed (prevents re-arming same day)

    def check_market_event_preroll():
        """Check if we should trigger preroll for market open/close."""
        if not TIME_PREROLL_ENABLED:
            return False, None
        
        should_show, message, color = get_market_event_announcement()
        if not should_show:
            return False, None
        
        # Determine event type from message
        event_type = None
        if "OPEN" in message.upper():
            event_type = "open"
        elif "CLOSE" in message.upper():
            event_type = "close"
        
        if not event_type:
            return False, None
        
        # Check if we've already shown this event today
        today_key = f"{datetime.now().date()}_{event_type}"
        if today_key in market_event_shown_today:
            return False, None
        
        # Mark as shown and return trigger
        market_event_shown_today.add(today_key)
        return True, event_type

    def should_show_weather_alert(scroll_count):
        """Determine if weather alert should be shown on this scroll based on severity."""
        if not weather_banner.get("active"):
            return False
        sev = weather_banner.get("severity", "")
        if sev == "warning":
            # Show warning every N scrolls
            return (scroll_count % max(1, WEATHER_WARNING_EVERY_N_SCROLLS)) == 0
        elif sev in ["advisory", "watch"]:
            # Show advisory/watch less frequently
            return (scroll_count % max(1, WEATHER_ADVISORY_EVERY_N_SCROLLS)) == 0
        return False

    def build_scoreboard_compact_parts():
        """
        Build single or dual-line scoreboard text that fits in the normal ticker row(s).
        Returns (lines_top, lines_bot): each is a list of Surfaces.
        lines_top always present; lines_bot may be empty for single layout.
        """
        font_sb_ = get_sb_font()
        lines_top = []
        lines_bot = []
        if not SCOREBOARD_ENABLED or not scoreboard_latest:
            return [font_sb_.render("Scoreboard (no data) ", True, WHITE)], []
        ordered = []
        for key in ["NHL","NFL"]:
            p = scoreboard_latest.get(key)
            if not p: continue
            games = p.get("games") or []
            live=[g for g in games if g.get("state")=="LIVE"]
            fut =[g for g in games if g.get("state")=="PREGAME"]
            for g in (live + fut)[:SCOREBOARD_MAX_GAMES]:
                ordered.append((key,g))
        if not ordered:
            return [font_sb_.render("Scoreboard (no data) ", True, WHITE)], []

        def mk_compact(key,g):
            hc, ac = g["home"]["code"], g["away"]["code"]
            hs, as_ = g["home"].get("score",0), g["away"].get("score",0)
            state=g.get("state",""); pd=g.get("period",0); ck=g.get("clock","")
            period_label = g.get("period_label", f"P{pd}")
            
            # PREGAME with countdown
            if state == "PREGAME" and SCOREBOARD_SHOW_COUNTDOWN:
                mins_until = g.get("minutes_until_start")
                if mins_until is not None and mins_until >= 0:
                    order = f"{hc} VS {ac}" if SCOREBOARD_HOME_FIRST else f"{ac} VS {hc}"
                    return f"PREGAME {order} - GAME STARTS IN {mins_until}m"
                else:
                    order = f"{hc} VS {ac}" if SCOREBOARD_HOME_FIRST else f"{ac} VS {hc}"
                    return f"PREGAME {order}"
            
            # LIVE or FINAL
            if key=="NHL" and state=="LIVE" and SCOREBOARD_SHOW_CLOCK:
                tail = f"({period_label} {ck})" if ck else f"({period_label})"
            elif key=="NFL" and state=="LIVE" and SCOREBOARD_SHOW_CLOCK:
                tail = f"(Q{pd} {ck})"
            else:
                tail = f"({state})"
            order = (f"{hc} {hs} - {ac} {as_}") if SCOREBOARD_HOME_FIRST else (f"{ac} {as_} - {hc} {hs}")
            return f"{order} {tail}"

        for key,g in ordered[:SCOREBOARD_MAX_GAMES]:
            lines_top.append(font_sb_.render(mk_compact(key,g) + " ", True, WHITE))
        # second-row detail (only first game)
        key,g = ordered[0]
        if key=="NHL" and SCOREBOARD_SHOW_SOG:
            sog=f"SOG H:{g['home'].get('sog',0)} A:{g['away'].get('sog',0)} "
            lines_bot=[font_sb_.render(sog, True, WHITE)]
        elif key=="NFL" and SCOREBOARD_SHOW_POSSESSION:
            pos=(g.get("possession") or "").upper()
            if pos in ("HOME","AWAY"):
                who = g["home"]["code"] if pos=="HOME" else g["away"]["code"]
                lines_bot=[font_sb_.render(f"Possession: {who} ", True, WHITE)]
        return lines_top, lines_bot

    # ---- main loop ----
    print("[MAIN] Entering main rendering loop...", flush=True)
    loop_count = 0
    try:
        while not _shutdown_requested:
            # Apply time-limited override expiry
            if override_active and override_end_ts is not None and time.time() >= override_end_ts:
                print("[OVERRIDE] elapsed; reverting.", flush=True)
                override_active=False; override_mode="OFF"; override_end_ts=None

            now_ticks = pygame.time.get_ticks()
            dt = (now_ticks - getattr(run, "_prev_ticks", now_ticks))/1000.0
            run._prev_ticks = now_ticks
            
            loop_count += 1
            poll_queues_nonblock()
            detect_goals()  # Check for score changes
            detect_score_bursts()
            generate_test_alert()  # Generate test alerts if enabled

            cfg_info = _maybe_reload_config()
            if cfg_info.get("reloaded"):
                # Keep next_top_ts aligned in case TZ/clock changed
                try:
                    next_top_ts = _compute_next_hour_ts() if time.time() > next_top_ts + 3600 else next_top_ts
                except Exception:
                    pass
                # Update rendering globals when night mode config changes
                if cfg_info.get("dim"):
                    set_rendering_globals(
                        NIGHT_MODE_ENABLED=NIGHT_MODE_ENABLED,
                        NIGHT_MODE_START=NIGHT_MODE_START,
                        NIGHT_MODE_END=NIGHT_MODE_END,
                        NIGHT_MODE_DIM_PCT=NIGHT_MODE_DIM_PCT,
                        NIGHT_MODE_SPEED_PCT=NIGHT_MODE_SPEED_PCT,
                        QUICK_DIM_PCT=QUICK_DIM_PCT,
                    )
                    print("[CFG] Updated rendering globals for night mode changes", flush=True)
                
                # Rebuild fonts (layout/size may have changed)
                # Clear cached fonts first so getters create fresh ones
                set_fonts(None, None, None)
                font_row = get_row_font(); font_dbg = get_dbg_font(); font_sb = get_sb_font()
                set_fonts(font_row, font_dbg, font_sb)  # Update fonts in rendering module
                maint_big_font = get_maint_big_font(); preroll_big_font = get_preroll_big_font()
                if cfg_info.get("layout"):
                    x_single = x_top = x_bot = float(W)
                
                # HOT RELOAD FIX: Restart workers when their config changes
                if cfg_info.get("markets") and not DEMO_MODE:
                    try:
                        ALL_TICKERS = sorted({s for s,_ in (TICKERS_TOP+TICKERS_BOT+(TICKERS_BOT2 or []))})
                        _terminate_worker(workers["market"])
                        workers["market"] = Process(target=market_worker, args=(ALL_TICKERS, REFRESH_SEC, mq, STATUS_PATH, TZINFO), daemon=True)
                        workers["market"].start(); print("[CFG] market worker restarted", flush=True)
                    except Exception as e:
                        print("[CFG] market restart failed:", e, flush=True)
                    x_single = x_top = x_bot = float(W)

                # HOT RELOAD FIX: Restart weather worker when weather config changes
                if cfg_info.get("weather") and not DEMO_MODE:
                    try:
                        _terminate_worker(workers["weather"])
                        workers["weather"] = Process(target=weather_worker, args=(WEATHER_RSS_URL, WEATHER_INCLUDE_WATCH, WEATHER_REFRESH_SEC, WEATHER_TIMEOUT, WEATHER_FORCE_ACTIVE, WEATHER_FORCE_TEXT, wq, STATUS_PATH, TZINFO), daemon=True)
                        workers["weather"].start()
                        # Reset weather test state when restarting weather worker
                        weather_test_injected = False
                        weather_banner = {
                            "active": False,
                            "message": "",
                            "severity": "",
                            "show_until": 0.0,
                            "next_repeat_at": 0.0,
                            "test_forced_until": 0.0
                        }
                        print("[CFG] weather worker restarted", flush=True)
                    except Exception as e:
                        print("[CFG] weather restart failed:", e, flush=True)
                
                # HOT RELOAD FIX: Rebuild message surface when message config changes
                if cfg_info.get("message"):
                    try:
                        injector_active = bool(INJECT_MESSAGE and MESSAGE_EVERY>0)
                        if injector_active:
                            col = parse_color(MESSAGE_COLOR)
                            msg_surface = build_message_surface(INJECT_MESSAGE, col, font_row)
                            print(f"[CFG] Message surface rebuilt: '{INJECT_MESSAGE}' every {MESSAGE_EVERY} scrolls row={MESSAGE_ROW} color={MESSAGE_COLOR}", flush=True)
                        else:
                            msg_surface = None
                            print("[CFG] Message injector disabled", flush=True)
                    except Exception as e:
                        print("[CFG] message rebuild failed:", e, flush=True)
                
                if cfg_info.get("scoreboard") and not DEMO_MODE:
                    try:
                        # Stop existing scoreboard worker if running
                        _terminate_worker(workers["scoreboard"])
                        workers["scoreboard"] = None

                        if SCOREBOARD_ENABLED:
                            scoreboard_latest.clear()
                            test_cfg = {
                                "enabled":SCOREBOARD_TEST, "league":SCOREBOARD_TEST_LEAGUE,
                                "home":SCOREBOARD_TEST_HOME, "away":SCOREBOARD_TEST_AWAY,
                                "duration":SCOREBOARD_TEST_DURATION
                            }
                            workers["scoreboard"] = Process(target=scoreboard_worker,
                                args=(SCOREBOARD_LEAGUES, SCOREBOARD_NHL_TEAMS, SCOREBOARD_NFL_TEAMS,
                                      SCOREBOARD_POLL_WINDOW_MIN, SCOREBOARD_POLL_CADENCE, SCOREBOARD_LIVE_REFRESH,
                                      SCOREBOARD_INCLUDE_OTHERS, SCOREBOARD_ONLY_MY_TEAMS, SCOREBOARD_MAX_GAMES,
                                      test_cfg, sbq, STATUS_PATH, TZINFO, SCOREBOARD_PREGAME_WINDOW_MIN, SCOREBOARD_POSTGAME_DELAY_MIN),
                                daemon=True)
                            workers["scoreboard"].start(); print("[CFG] scoreboard worker restarted", flush=True)
                        else:
                            scoreboard_latest.clear()
                            print("[CFG] scoreboard disabled; worker stopped", flush=True)
                    except Exception as e:
                        print("[CFG] scoreboard restart failed:", e, flush=True)
                
                if cfg_info.get("override"):
                    override_mode = OVERRIDE_MODE if OVERRIDE_MODE in ("BRIGHT","SCOREBOARD","MESSAGE","MAINT","CLOCK") else "OFF"
                    override_active = (override_mode != "OFF")
                    override_end_ts = (time.time() + OVERRIDE_DURATION_MIN*60) if (override_active and OVERRIDE_DURATION_MIN>0) else None
                    print(f"[CFG] Override now: {override_mode} ({'dur '+str(OVERRIDE_DURATION_MIN)+'m' if OVERRIDE_DURATION_MIN>0 else 'until cleared'})", flush=True)

            # Weather TEST harness: force logical active window after delay
            if WEATHER_TEST_DELAY > 0 and not weather_test_injected and (time.time() - start_ts) >= WEATHER_TEST_DELAY:
                weather_test_injected = True
                weather_banner["test_forced_until"] = time.time() + max(WEATHER_TEST_STICKY_TOTAL, WEATHER_STICKY_SEC)
                test_msg = WEATHER_FORCE_TEXT or "TEST WEATHER WARNING"
                weather_message = test_msg
                weather_banner["active"] = True
                weather_banner["message"] = test_msg
                weather_banner["severity"] = "warning"  # Set severity for test
                weather_banner["show_until"] = time.time() + max(5, WEATHER_STICKY_SEC)
                weather_banner["next_repeat_at"] = time.time() + max(WEATHER_REPEAT_SEC, WEATHER_ANNOUNCE_SEC)
                print(f"[WEATHER-TEST] Activated test weather alert: {test_msg}", flush=True)

            if weather_banner["test_forced_until"] > 0:
                if time.time() <= weather_banner["test_forced_until"]:
                    if time.time() >= weather_banner["next_repeat_at"]:
                        weather_banner["show_until"] = time.time() + max(5, WEATHER_STICKY_SEC)
                        weather_banner["next_repeat_at"] = time.time() + max(WEATHER_REPEAT_SEC, WEATHER_ANNOUNCE_SEC)
                    weather_banner["active"] = True
                else:
                    weather_banner["test_forced_until"] = 0.0
                    weather_banner["active"] = False
                    print("[WEATHER-TEST] Test weather alert expired", flush=True)

            now_dt = now_local()

            # Apply night mode speed reduction
            pps_top_current = apply_night_mode_speed(PPS_TOP, now_dt)
            pps_bot_current = apply_night_mode_speed(PPS_BOT, now_dt)
            pps_single_current = apply_night_mode_speed(PPS_SINGLE, now_dt)

            # Rebuild scrolling parts periodically from latest market cache (lightweight)
            if int(time.time() * 2) % 4 == 0:  # ~every 0.5s
                single_parts,_ = build_row_surfaces_from_cache(TICKERS_TOP+TICKERS_BOT, market_cache, font_row, HOLDINGS_ENABLED)
                top_parts,_    = build_row_surfaces_from_cache(TICKERS_TOP, market_cache, font_row, HOLDINGS_ENABLED)
                bot_parts,_    = build_row_surfaces_from_cache(TICKERS_BOT, market_cache, font_row, HOLDINGS_ENABLED)
                if TICKERS_BOT2: bot_parts2,_ = build_row_surfaces_from_cache(TICKERS_BOT2, market_cache, font_row, HOLDINGS_ENABLED)

            secs_to_top = next_top_ts - time.time()
            if 0 < secs_to_top <= 20 and not prefetch_done_for_this_hour:
                prefetch_done_for_this_hour=True

            any_live = any(any(g.get("state")=="LIVE" for g in (p.get("games") or [])) for p in scoreboard_latest.values())

            # Normal state transitions
            # Priority order from STATE_TICKER:
            #   1. Top-of-hour preroll (always fires unless override/alert active)
            #   2. Market open/close preroll (fires in its 3-min window)
            #   3. Scoreboard (only if no preroll pending)
            # This ensures a live game cannot suppress the top-of-hour clock or market open scroller.
            # SCOREBOARD_PRECEDENCE="force" can still eject an *already-running* preroll.
            if not override_active and not (SCORE_ALERTS_ENABLED and alert_obj):
                if state==STATE_TICKER:
                    if TIME_PREROLL_ENABLED and time.time() >= next_top_ts:
                        state=STATE_PREROLL; state_enter_ts=time.time(); preroll_reason="hour"; print(f'[PREROLL] Fired at top of hour for {TIME_PREROLL_SEC}s (style={PREROLL_STYLE}, color={PREROLL_COLOR}, pps={PREROLL_PPS})', flush=True); next_top_ts = _compute_next_hour_ts(); prefetch_done_for_this_hour=False
                    else:
                        # Check for market event (open/close) preroll before scoreboard
                        market_event_trigger, event_type = check_market_event_preroll()
                        if market_event_trigger:
                            state=STATE_PREROLL; state_enter_ts=time.time(); preroll_reason=f"market_{event_type}"
                            print(f'[PREROLL] Fired for MARKET {event_type.upper()} for {TIME_PREROLL_SEC}s (style={PREROLL_STYLE}, color={PREROLL_COLOR})', flush=True)
                        elif SCOREBOARD_ENABLED and any_live:
                            state=STATE_SCOREBOARD; state_enter_ts=time.time()
                elif state==STATE_PREROLL:
                    if SCOREBOARD_PRECEDENCE=="force" and SCOREBOARD_ENABLED and any_live:
                        state=STATE_SCOREBOARD; state_enter_ts=time.time()
                    elif time.time() - state_enter_ts >= TIME_PREROLL_SEC:
                        state = STATE_TICKER
                        state_enter_ts=time.time()
                elif state==STATE_SCOREBOARD:
                    if not (SCOREBOARD_ENABLED and any_live):
                        state=STATE_TICKER; state_enter_ts=time.time()

            # Compose frame
            frame = pygame.Surface((W, H), pygame.SRCALPHA); frame.fill(BLACK)
            # Property of solutions reseaux chromatel
            def market_dot_color():
                """
                Determine status dot color:
                - RED: No data OR data is stale (>FRESH_SEC old)
                - BLUE: My team (NHL/NFL) has a game scheduled today
                - YELLOW: Pre-market hours (before 9:30 AM on weekdays)
                - GREEN: Market is open (REGULAR state) and data is fresh
                - GREY: Market is closed and data is fresh
                """
                # Check if we have fresh data
                if (not last_result_ok) or (time.time() - (last_success_ts or 0)) > FRESH_SEC:
                    return RED
                
                # Check if my teams have a game today (highest priority)
                my_teams_playing_today = False
                try:
                    if scoreboard_latest:
                        for league_key in ["NHL", "NFL"]:
                            payload = scoreboard_latest.get(league_key)
                            if payload and payload.get("games"):
                                for g in payload["games"]:
                                    # Any state counts - PREGAME, LIVE, FINAL
                                    if g.get("state") in ["PREGAME", "LIVE", "FINAL"]:
                                        my_teams_playing_today = True
                                        break
                            if my_teams_playing_today:
                                break
                except Exception:
                    pass
                
                if my_teams_playing_today:
                    return (0, 150, 255)  # Blue for game day
                
                # Check if pre-market (before 9:30 AM ET on weekdays)
                try:
                    if PYTZ_AVAILABLE:
                        et_tz = pytz.timezone('America/New_York')
                        now_et = datetime.now(et_tz)
                        if now_et.weekday() < 5:  # Monday-Friday
                            if now_et.time() < dtime(9, 30):
                                return YELLOW
                except Exception:
                    pass
                
                # Check market state
                if market_state == "REGULAR":
                    return GREEN
                else:
                    return GREY
            
            # Property of solutions reseaux chromatel - market event announcements
            # --- MARKET OPEN: arm once per trading day; persist for 5 scroll completions ---
            _today = datetime.now().date()
            if market_open_scrolls_left == 0 and _today != market_open_scroll_date:
                _should_open, _open_msg, _open_color = get_market_event_announcement()
                if _should_open and "OPEN" in _open_msg and market_state == "REGULAR":
                    market_open_srf = build_message_surface(_open_msg, parse_color(_open_color), font_row)
                    market_open_scrolls_left = 5
                    market_open_scroll_date = _today
                    print("[MARKET] MARKET OPEN injection armed for 5 scrolls", flush=True)
            if market_open_scrolls_left == 0:
                market_open_srf = None  # Clear once exhausted
            # --- MARKET CLOSE / other events: timed one-shot announcement ---
            market_announcement_srf = None
            now = time.time()
            if now - market_announcement_last_shown >= market_announcement_interval:
                _should_ann, _ann_msg, _ann_color = get_market_event_announcement()
                if _should_ann and "OPEN" not in _ann_msg:
                    market_announcement_srf = build_announcement_surface(_ann_msg, parse_color(_ann_color), font_row)
                    market_announcement_last_shown = now

            time_dot_color = market_dot_color()
            time_srf = build_time_surface(time_dot_color, font_row)

            # OVERRIDE MODES
            if override_active and override_mode!="BRIGHT":
                # BRIGHT mode falls through to normal ticker rendering
                if override_mode=="SCOREBOARD":
                    # Force scoreboard view
                    if SCOREBOARD_ENABLED:
                        # First try to get real game data from scoreboard_latest
                        game_data = _extract_live_game_data(scoreboard_latest) if scoreboard_latest else None
                            
                        # If we have game data, render the scoreboard
                        if game_data:
                            score_font = pygame.font.SysFont("monospace", 14, bold=True)
                            flash_color = scoreboard_flash.get_flash_color() or (255,255,255)
                            flash_home = scoreboard_flash.is_flashing("home")
                            flash_away = scoreboard_flash.is_flashing("away")

                            render_fullheight_scoreboard(
                                frame, game_data, score_font,
                                flash_home=flash_home,
                                flash_away=flash_away,
                                flash_color=flash_color
                            )
                        else:
                            # No live games - show appropriate message
                            try:
                                if SCOREBOARD_TEST:
                                    msg = row_render_text("SCOREBOARD TEST MODE - LOADING...", (255, 255, 0))
                                else:
                                    msg = row_render_text("NO LIVE GAMES", (255, 255, 255))
                                msg_x = (W - msg.get_width()) // 2
                                msg_y = (H - msg.get_height()) // 2
                                frame.blit(msg, (msg_x, msg_y))
                            except Exception as e:
                                print(f"[SCOREBOARD OVERRIDE] Error rendering message: {e}", flush=True)
                    else:
                        # Scoreboard is disabled
                        try:
                            msg = row_render_text("SCOREBOARD DISABLED", (255, 255, 255))
                            msg_x = (W - msg.get_width()) // 2
                            msg_y = (H - msg.get_height()) // 2
                            frame.blit(msg, (msg_x, msg_y))
                        except Exception:
                            pass
                elif override_mode=="MESSAGE":
                    # Show override message
                    txt = (OVERRIDE_MESSAGE_TEXT or "MESSAGE").strip()
                    msg_srf = build_message_surface(txt, parse_color("yellow"), font_row)
                    parts = [time_srf, msg_srf]
                    if IS_SINGLE:
                        curr_x = x_single; total_w = 0
                        for s in parts:
                            w = s.get_width()
                            if -w < curr_x < W: frame.blit(s, (_sp(curr_x), 1))
                            curr_x += w; total_w += w
                        total_w = max(1, total_w); x_single -= pps_single_current * dt
                        if x_single < -total_w: x_single = float(W)
                    else:
                        curr_x = x_top; total_w = 0
                        for s in parts:
                            w = s.get_width()
                            if -w < curr_x < W: frame.blit(s, (_sp(curr_x), TOP_Y))
                            curr_x += w; total_w += w
                        total_w = max(1, total_w); x_top -= pps_top_current * dt
                        if x_top < -total_w: x_top = float(W)
                elif override_mode=="MAINT":
                    # Maintenance screen
                    txt = (MAINTENANCE_TEXT or "MAINTENANCE").strip()
                    if MAINTENANCE_SCROLL:
                        # Scrolling maintenance message in RED
                        srf = maint_big_font.render(txt, True, RED)
                        w = srf.get_width()
                        y = max(0, (H - srf.get_height()) // 2)
                        if -w < x_maint < W:
                            frame.blit(srf, (_sp(x_maint), y))
                        x_maint -= MAINTENANCE_PPS * dt
                        if x_maint < -w:
                            x_maint = float(W)
                    else:
                        # Centered maintenance message in RED
                        srf = maint_big_font.render(txt, True, RED)
                        wt = srf.get_width()
                        xt = max(0, (W - wt) // 2)
                        y = max(0, (H - srf.get_height()) // 2)
                        frame.blit(srf, (xt, y))
                elif override_mode=="CLOCK":
                    # Big centered clock - FIX: Ensure fonts are available
                    try:
                        # Re-fetch font to ensure it exists
                        clock_font = get_preroll_big_font()
                        clock_srf = build_clock_surface(W, H)
                        xt = max(0, (W - clock_srf.get_width()) // 2)
                        yt = max(0, (H - clock_srf.get_height()) // 2)
                        frame.blit(clock_srf, (xt, yt))
                    except Exception as e:
                        print(f"[CLOCK] render error: {e}", flush=True)
                        # Fallback: show time surface
                        frame.blit(time_srf, (2, 1 if IS_SINGLE else TOP_Y))

            # SCORE ALERTS (top priority if active)
            elif SCORE_ALERTS_ENABLED and (alert_obj or alert_queue):
                if not alert_obj and alert_queue:
                    try:
                        nxt = alert_queue.popleft()
                        alert_obj = ScoreAlert(nxt["league"], nxt["team"], nxt["score"], SCORE_ALERTS_CYCLES)
                        print(f"[ALERT] {nxt['team']} {nxt['score']}", flush=True)
                    except Exception: pass
                if alert_obj:
                    col = alert_obj.current_color()
                    al_srf = font_sb.render(f"{alert_obj.team}  {alert_obj.score}", True, col)
                    x_al = max(0, (W - al_srf.get_width()) // 2)
                    y_al = max(0, (H - al_srf.get_height()) // 2)
                    frame.blit(al_srf, (x_al, y_al))
                    if alert_obj.done:
                        alert_obj = None
                        print("[ALERT] Finished", flush=True)

            # PREROLL
            elif state==STATE_PREROLL:
                # For market events, always show the announcement regardless of style
                if preroll_reason in ("market_open", "market_close"):
                    # Market event preroll - show announcement if still in window
                    should_announce, announcement, announce_color = get_market_event_announcement()
                    if should_announce and announcement:
                        ann_srf = build_announcement_surface(announcement, parse_color(announce_color), font_row)
                        parts = [time_srf, ann_srf]
                        if IS_SINGLE:
                            curr_x = x_single; total_w = 0
                            for s in parts:
                                w = s.get_width()
                                if -w < curr_x < W: frame.blit(s, (_sp(curr_x), 1))
                                curr_x += w; total_w += w
                            total_w = max(1, total_w); x_single -= PREROLL_PPS * dt
                            if x_single < -total_w: x_single = float(W)
                        else:
                            curr_x = x_top; total_w = 0
                            for s in parts:
                                w = s.get_width()
                                if -w < curr_x < W: frame.blit(s, (_sp(curr_x), TOP_Y))
                                curr_x += w; total_w += w
                            total_w = max(1, total_w); x_top -= PREROLL_PPS * dt
                            if x_top < -total_w: x_top = float(W)
                    else:
                        # Announcement window expired mid-preroll; end preroll early
                        state = STATE_TICKER; state_enter_ts = time.time()
                elif PREROLL_STYLE=="MARQUEE":
                    # Scrolling time display (marquee style)
                    if IS_SINGLE:
                        curr_x = x_single; total_w = time_srf.get_width()
                        if -total_w < curr_x < W: frame.blit(time_srf, (_sp(curr_x), 1))
                        x_single -= PREROLL_PPS * dt
                        if x_single < -total_w: x_single = float(W)
                    else:
                        curr_x = x_top; total_w = time_srf.get_width()
                        if -total_w < curr_x < W: frame.blit(time_srf, (_sp(curr_x), TOP_Y))
                        x_top -= PREROLL_PPS * dt
                        if x_top < -total_w: x_top = float(W)
                elif PREROLL_STYLE=="BIGTIME":
                    try:
                        pr_srf = build_preroll_bigtime_surface(now_local(), preroll_big_font)
                        xt = max(0, (W - pr_srf.get_width()) // 2)
                        yt = max(0, (H - pr_srf.get_height()) // 2)
                        frame.blit(pr_srf, (xt, yt))
                    except Exception as e:
                        print(f"[PREROLL] bigtime error: {e}", flush=True)
                        # Fallback: static time on top row (never scroll in BIGTIME mode)
                        frame.blit(time_srf, (2, TOP_Y))
                elif PREROLL_STYLE=="MARKET_ANNOUNCE":
                    # Show market announcement
                    should_announce, announcement, announce_color = get_market_event_announcement()
                    if should_announce and announcement:
                        ann_srf = build_announcement_surface(announcement, parse_color(announce_color), font_row)
                        parts = [time_srf, ann_srf]
                        if IS_SINGLE:
                            curr_x = x_single; total_w = 0
                            for s in parts:
                                w = s.get_width()
                                if -w < curr_x < W: frame.blit(s, (_sp(curr_x), 1))
                                curr_x += w; total_w += w
                            total_w = max(1, total_w); x_single -= PREROLL_PPS * dt
                            if x_single < -total_w: x_single = float(W)
                        else:
                            curr_x = x_top; total_w = 0
                            for s in parts:
                                w = s.get_width()
                                if -w < curr_x < W: frame.blit(s, (_sp(curr_x), TOP_Y))
                                curr_x += w; total_w += w
                            total_w = max(1, total_w); x_top -= PREROLL_PPS * dt
                            if x_top < -total_w: x_top = float(W)
                    else:
                        # No announcement available; fall back to BIGTIME
                        try:
                            pr_srf = build_preroll_bigtime_surface(now_local(), preroll_big_font)
                            xt = max(0, (W - pr_srf.get_width()) // 2)
                            yt = max(0, (H - pr_srf.get_height()) // 2)
                            frame.blit(pr_srf, (xt, yt))
                        except Exception:
                            frame.blit(time_srf, (2, TOP_Y))
                else:
                    # Fallback: Unknown PREROLL_STYLE, default to BIGTIME
                    try:
                        pr_srf = build_preroll_bigtime_surface(now_local(), preroll_big_font)
                        xt = max(0, (W - pr_srf.get_width()) // 2)
                        yt = max(0, (H - pr_srf.get_height()) // 2)
                        frame.blit(pr_srf, (xt, yt))
                    except Exception as e:
                        print(f"[PREROLL] fallback error: {e}", flush=True)
                        # Last resort: static time on top row
                        frame.blit(time_srf, (2, TOP_Y))

            elif state==STATE_SCOREBOARD and SCOREBOARD_ENABLED:
                # STATE_SCOREBOARD - Full-height scoreboard with logos
                game_data = _extract_live_game_data(scoreboard_latest) if scoreboard_latest else None
                if game_data:
                    score_font = pygame.font.SysFont("monospace", 14, bold=True)
                    flash_color = scoreboard_flash.get_flash_color()
                    flash_home = scoreboard_flash.is_flashing("home")
                    flash_away = scoreboard_flash.is_flashing("away")
                    render_fullheight_scoreboard(
                        frame, game_data, score_font,
                        flash_home=flash_home,
                        flash_away=flash_away,
                        flash_color=flash_color
                    )
                else:
                    # No live games
                    try:
                        msg = row_render_text("NO LIVE GAMES", (255, 255, 255))
                        msg_x = (W - msg.get_width()) // 2
                        msg_y = (H - msg.get_height()) // 2
                        frame.blit(msg, (msg_x, msg_y))
                    except Exception:
                        pass


            else:
                # TICKER
                if IS_SINGLE:
                    # Single row layout
                    # Check if we should show weather alert on THIS scroll cycle
                    weather_msg = weather_banner.get("message", "")
                    weather_sev = weather_banner.get("severity", "")

                    # Determine if it's time to show weather
                    should_show = should_show_weather_alert(completed_single) and weather_msg

                    # Start showing weather on the right scroll count
                    if should_show and not weather_scroll_shown:
                        weather_scroll_shown = True
                        x_single = float(W)  # Reset scroll to start fresh
                    # Stop showing weather after scroll completes
                    elif not should_show and weather_scroll_shown:
                        weather_scroll_shown = False

                    show_weather_now = weather_scroll_shown

                    if show_weather_now and weather_sev in ["warning", "advisory", "watch"]:
                        # Full screen weather alert - scrolls across full height
                        weather_color = parse_color(WEATHER_WARNING_COLOR if weather_sev == "warning" else WEATHER_ADVISORY_COLOR)
                        formatted_msg = format_weather_alert_text(weather_msg, weather_sev)
                        weather_srf = build_weather_alert_surface(formatted_msg, weather_color)

                        # Center the weather message vertically
                        weather_y = max(0, (H - weather_srf.get_height()) // 2)

                        # Render scrolling weather alert
                        parts_weather = [time_srf, weather_srf]
                        curr_x = x_single
                        total_w = 0

                        for s in parts_weather:
                            w = s.get_width()
                            if -w < curr_x < W:
                                if s == weather_srf:
                                    frame.blit(s, (_sp(curr_x), weather_y))
                                else:
                                    frame.blit(s, (_sp(curr_x), 1))
                            curr_x += w
                            total_w += w

                        total_w = max(1, total_w)
                        x_single -= pps_single_current * dt

                        if x_single < -total_w:
                            completed_single += 1
                            x_single = float(W)
                            weather_scroll_shown = False  # Done scrolling, return to normal
                            if not MESSAGE_TEST_FORCE:
                                show_msg_single = injector_active and (MESSAGE_ROW in ("single","auto")) and (((completed_single+1)%max(1,MESSAGE_EVERY))==0)
                    else:
                        # Normal single row ticker
                        parts=[time_srf]
                        if market_open_srf:
                            parts.append(market_open_srf)
                        elif market_announcement_srf:
                            parts.append(market_announcement_srf)
                        if injector_active and (MESSAGE_TEST_FORCE or show_msg_single) and msg_surface and (MESSAGE_ROW in ("single","auto")):
                            parts.append(msg_surface)
                        parts += single_parts
                        curr_x=x_single; total_w=0
                        for s in parts:
                            w=s.get_width()
                            if -w<curr_x<W: frame.blit(s,(_sp(curr_x),1))
                            curr_x+=w; total_w+=w
                        total_w=max(1,total_w); x_single -= pps_single_current * dt
                        if x_single < -total_w:
                            completed_single+=1; x_single=float(W)
                            if market_open_scrolls_left > 0:
                                market_open_scrolls_left -= 1
                            if not MESSAGE_TEST_FORCE:
                                show_msg_single = injector_active and (MESSAGE_ROW in ("single","auto")) and (((completed_single+1)%max(1,MESSAGE_EVERY))==0)
                else:
                    # dual layout
                    # Check if we should show weather alert on THIS scroll cycle
                    weather_msg = weather_banner.get("message", "")
                    weather_sev = weather_banner.get("severity", "")
                        
                    # Determine if it's time to show weather
                    should_show = should_show_weather_alert(completed_top) and weather_msg
                        
                    # Start showing weather on the right scroll count
                    if should_show and not weather_scroll_shown:
                        weather_scroll_shown = True
                        x_top = float(W)  # Reset scroll to start fresh
                    # Stop showing weather after scroll completes
                    elif not should_show and weather_scroll_shown:
                        weather_scroll_shown = False
                        
                    show_weather_now = weather_scroll_shown
                        
                    if show_weather_now and weather_sev in ["warning", "advisory", "watch"]:
                        # Full screen weather alert - scrolls across full 16px height
                        weather_color = parse_color(WEATHER_WARNING_COLOR if weather_sev == "warning" else WEATHER_ADVISORY_COLOR)
                        # Format weather message with city and type
                        formatted_msg = format_weather_alert_text(weather_msg, weather_sev)
                        weather_srf = build_weather_alert_surface(formatted_msg, weather_color)
                            
                        # Center the weather message vertically in the full 16px
                        weather_y = max(0, (H - weather_srf.get_height()) // 2)
                            
                        # Render scrolling weather alert
                        parts_weather = [time_srf, weather_srf]
                        curr_x = x_top
                        total_w = 0
                            
                        for s in parts_weather:
                            w = s.get_width()
                            if -w < curr_x < W:
                                # Draw weather message centered vertically
                                if s == weather_srf:
                                    frame.blit(s, (_sp(curr_x), weather_y))
                                else:
                                    # Draw time at normal top position
                                    frame.blit(s, (_sp(curr_x), TOP_Y))
                            curr_x += w
                            total_w += w
                            
                        total_w = max(1, total_w)
                        x_top -= pps_top_current * dt
                            
                        if x_top < -total_w:
                            completed_top += 1
                            x_top = float(W)
                            weather_scroll_shown = False  # Done scrolling, return to normal
                            if not MESSAGE_TEST_FORCE:
                                show_msg_top = injector_active and (MESSAGE_ROW in ("top","both","auto")) and (((completed_top+1)%max(1,MESSAGE_EVERY))==0)
                            
                        # Don't render bottom row separately during weather alert
                    else:
                        # Normal top row ticker
                        parts_top=[time_srf]
                        # Property of solutions reseaux chromatel - inject market announcement
                        if market_open_srf:
                            parts_top.append(market_open_srf)
                        elif market_announcement_srf:
                            parts_top.append(market_announcement_srf)
                        if injector_active and (MESSAGE_TEST_FORCE or show_msg_top) and msg_surface and (MESSAGE_ROW in ("top","both","auto")):
                            parts_top.append(msg_surface)

                        parts_top += top_parts

                        curr_x=x_top; total_w_top=0
                        for s in parts_top:
                            w=s.get_width()
                            if -w<curr_x<W: frame.blit(s,(_sp(curr_x),TOP_Y))
                            curr_x+=w; total_w_top+=w
                        total_w_top=max(1,total_w_top); x_top -= pps_top_current * dt
                        if x_top < -total_w_top:
                            completed_top+=1; x_top=float(W)
                            if market_open_scrolls_left > 0:
                                market_open_scrolls_left -= 1
                            if not MESSAGE_TEST_FORCE:
                                show_msg_top = injector_active and (MESSAGE_ROW in ("top","both","auto")) and (((completed_top+1)%max(1,MESSAGE_EVERY))==0)

                        # bottom row - alternate between TICKERS_BOT and TICKERS_BOT2 every other roll
                        _active_bot = bot_parts2 if (TICKERS_BOT2 and completed_bot % 2 == 1) else bot_parts
                        parts_bot=[]
                        if injector_active and (MESSAGE_TEST_FORCE or show_msg_bot) and msg_surface and (MESSAGE_ROW in ("bottom","both")):
                            parts_bot.append(msg_surface)
                        parts_bot += _active_bot
                        curr_xb=x_bot; total_w_bot=0
                        for s in parts_bot:
                            w=s.get_width()
                            if -w<curr_xb<W: frame.blit(s,(_sp(curr_xb),BOT_Y))
                            curr_xb+=w; total_w_bot+=w
                        total_w_bot=max(1,total_w_bot); x_bot -= pps_bot_current * dt
                        if x_bot < -total_w_bot:
                            completed_bot+=1; x_bot=float(W)
                            if not MESSAGE_TEST_FORCE:
                                show_msg_bot = injector_active and (MESSAGE_ROW in ("bottom","both")) and (((completed_bot+1)%max(1,MESSAGE_EVERY))==0)

            if override_mode != "BRIGHT":
                apply_dimming_inplace(frame, current_dim_scale(now_dt))
            if DEBUG_OVERLAY:
                try:
                    info_str = f"FPS:{int(clock.get_fps())} st={state} dim={int(current_dim_scale(now_dt)*100)}% {LAYOUT}"
                    dbg_srf = font_dbg.render(info_str, True, (128, 128, 128))
                    frame.blit(dbg_srf, (0, H - dbg_srf.get_height()))
                except Exception: pass

            # Output — write directly to LED matrix
            ok = write_surface_to_rgb_matrix(frame)
            if ok:
                if not shm_write_success:
                    shm_write_success = True
                    print(f"[RGB Matrix] First successful frame written", flush=True)
                if loop_count % 10 == 0:
                    try:
                        pygame.image.save(frame, "/tmp/ticker_preview.png")
                    except Exception:
                        pass
            else:
                now = time.time()
                if now - shm_last_error_print >= 10.0:
                    print(f"[RGB Matrix] write failed (suppressing repeats)", flush=True)
                    shm_last_error_print = now

            clock.tick(FPS)

    except KeyboardInterrupt:
        print("\n[MAIN] Keyboard interrupt; exiting.", flush=True)
    finally:
        print("[SHUTDOWN] Cleaning up workers...", flush=True)
        # Clean shutdown: terminate all workers quickly
        start_cleanup = time.time()
        
        # First, try terminate (sends SIGTERM to worker processes)
        for worker_name, worker in workers.items():
            if worker and worker.is_alive():
                try:
                    worker.terminate()
                except Exception as e:
                    print(f"[SHUTDOWN] {worker_name} terminate error: {e}", flush=True)
        
        # Give them a brief moment to terminate gracefully
        time.sleep(0.1)
        
        # Then join with short timeout, kill if still alive
        for worker_name, worker in workers.items():
            if worker and worker.is_alive():
                try:
                    worker.join(timeout=0.5)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(timeout=0.3)
                        print(f"[SHUTDOWN] {worker_name} killed", flush=True)
                    else:
                        print(f"[SHUTDOWN] {worker_name} terminated", flush=True)
                except Exception as e:
                    print(f"[SHUTDOWN] {worker_name} join error: {e}", flush=True)
        
        cleanup_duration = time.time() - start_cleanup
        print(f"[SHUTDOWN] Cleanup completed in {cleanup_duration:.2f}s", flush=True)
        
        # Quit pygame
        try:
            pygame.quit()
        except:
            pass

if __name__ == "__main__":
    if os.environ.get("XDG_RUNTIME_DIR", "").strip() == "":
        os.environ["XDG_RUNTIME_DIR"] = "/tmp"
    try:
        set_start_method("spawn")
    except RuntimeError:
        pass
    
    set_utils_globals(TZINFO=TZINFO)
    set_worker_globals(TZINFO=TZINFO)
    run()

