#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Property of solutions reseaux chromatel
"""
LED Ticker - Rendering & Display Functions
===========================================
All pygame rendering, fonts, colors, and display helpers.
Supports rpi-rgb-led-matrix for direct HUB75 driving.
"""
import pygame
import os
import time
from datetime import datetime, time as dtime
from multiprocessing import Queue
import queue as queue_std

# Import normalize_ws from utils (avoid duplication)
from utils import normalize_ws, now_local

# Globals - will be set by ticker.py via set_globals()
W = 192
H = 16
OUTPUT_MODE = "RGBMATRIX"  # "RGBMATRIX" or "HDMI"
ROW_H = 8
TOP_Y = 0
BOT_Y = 8
IS_SINGLE = False
IS_DUAL = True
LAYOUT = "dual"
MICROFONT_ENABLED = False

# RGB Matrix specific globals
RGB_MATRIX = None
RGB_CANVAS = None

BLACK = (0, 0, 0)
WHITE = (220, 220, 220)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
GREY = (140, 140, 140)

FONT_FAMILY_BASE = "DejaVu Sans Mono"
FONT_FAMILY_SCOREBOARD = "DejaVu Sans Mono"
FONT_FAMILY_DEBUG = "DejaVu Sans Mono"
PREROLL_FONT_FAMILY = "DejaVu Sans Mono"
MAINT_FONT_FAMILY = "DejaVu Sans Mono"
FONT_SIZE_ROW = 8
FONT_SIZE_SB = 7
FONT_SIZE_DEBUG = 6
PREROLL_FONT_PX = 16
MAINT_FONT_PX = 14
FONT_BOLD_BASE = False
FONT_BOLD_SB = True
FONT_BOLD_DEBUG = False
PREROLL_FONT_BOLD = True
MAINT_FONT_BOLD = True

# DIM variables
DIM_ENABLED = False
DIM_LEVEL = "off"
DIM_CUSTOM_PCT = 0
DIM_SCHEDULE_ENABLED = False
DIM1_START = ""
DIM1_END = ""
DIM1_PCT = 30
DIM2_START = ""
DIM2_END = ""
DIM2_PCT = 60
DIM3_START = ""
DIM3_END = ""
DIM3_PCT = 100
DIM_TEST_ENABLED = False
DIM_TEST_PCT = 100
NIGHT_MODE_ENABLED = False
NIGHT_MODE_START = "22:00"
NIGHT_MODE_END = "07:00"
NIGHT_MODE_DIM_PCT = 30
NIGHT_MODE_SPEED_PCT = 75

SCHEDULE_ENABLED = False
SCHEDULE_TEST_FORCE_OFF = False
SCHEDULE_OFF_START = "23:00"
SCHEDULE_OFF_END = "07:00"

FORCE_KMS = False
USE_SDL_SCALED = True
USE_BUSY_LOOP = False
TICKER_SCALE = 8
TZINFO = None

HOLDINGS = {}
HOLDINGS_ENABLED = False

# Preroll settings
PREROLL_COLOR = "yellow"

# Clock override settings
CLOCK_24H = True
CLOCK_SHOW_SECONDS = False
CLOCK_BLINK_COLON = True
CLOCK_COLOR = "yellow"
CLOCK_DATE_SHOW = False
CLOCK_DATE_FMT = "%a %b %d"
CLOCK_DATE_COLOR = "white"

# Font objects - will be set by ticker.py after pygame init
font_row = None
font_dbg = None
font_sb = None


def set_fonts(row_font, dbg_font, sb_font):
    """Set the font globals after pygame initialization or config reload."""
    global font_row, font_dbg, font_sb
    font_row = row_font
    font_dbg = dbg_font
    font_sb = sb_font


def set_globals(**kwargs):
    """Set globals from ticker.py"""
    g = globals()
    for key, value in kwargs.items():
        if key in g:
            g[key] = value
    # Initialize DIM_WINDOWS after globals are set
    if 'DIM1_START' in kwargs or 'DIM2_START' in kwargs or 'DIM3_START' in kwargs:
        _init_dim_windows()


def using_microfont() -> bool:
    """Use microfont when in dual layout and MICROFONT_ENABLED is true."""
    return (LAYOUT == "dual") and MICROFONT_ENABLED

# ------------------------------ MICROFONT (5x7) ---------------------------------------------------
_MICRO_GLYPHS = {
    # digits / letters / punctuation for a 5x7 pixel grid
    '0': ["01110","10001","10011","10101","11001","10001","01110"],
    '1': ["00100","01100","00100","00100","00100","00100","01110"],
    '2': ["01110","10001","00001","00010","00100","01000","11111"],
    '3': ["11110","00001","00001","01110","00001","00001","11110"],
    '4': ["00010","00110","01010","10010","11111","00010","00010"],
    '5': ["11111","10000","11110","00001","00001","10001","01110"],
    '6': ["00110","01000","10000","11110","10001","10001","01110"],
    '7': ["11111","00001","00010","00100","01000","01000","01000"],
    '8': ["01110","10001","10001","01110","10001","10001","01110"],
    '9': ["01110","10001","10001","01111","00001","00010","01100"],
    'A': ["00100","01010","10001","11111","10001","10001","10001"],
    'B': ["11110","10001","10001","11110","10001","10001","11110"],
    'C': ["01110","10001","10000","10000","10000","10001","01110"],
    'D': ["11100","10010","10001","10001","10001","10010","11100"],
    'E': ["11111","10000","10000","11110","10000","10000","11111"],
    'F': ["11111","10000","10000","11110","10000","10000","10000"],
    'G': ["01110","10001","10000","10111","10001","10001","01110"],
    'H': ["10001","10001","10001","11111","10001","10001","10001"],
    'I': ["01110","00100","00100","00100","00100","00100","01110"],
    'J': ["00001","00001","00001","00001","10001","10001","01110"],
    'K': ["10001","10010","10100","11000","10100","10010","10001"],
    'L': ["10000","10000","10000","10000","10000","10000","11111"],
    'M': ["10001","11011","10101","10101","10001","10001","10001"],
    'N': ["10001","11001","10101","10011","10001","10001","10001"],
    'O': ["01110","10001","10001","10001","10001","10001","01110"],
    'P': ["11110","10001","10001","11110","10000","10000","10000"],
    'Q': ["01110","10001","10001","10001","10101","10010","01101"],
    'R': ["11110","10001","10001","11110","10100","10010","10001"],
    'S': ["01111","10000","10000","01110","00001","00001","11110"],
    'T': ["11111","00100","00100","00100","00100","00100","00100"],
    'U': ["10001","10001","10001","10001","10001","10001","01110"],
    'V': ["10001","10001","10001","10001","01010","01010","00100"],
    'W': ["10001","10001","10001","10101","10101","11011","10001"],
    'X': ["10001","01010","00100","00100","00100","01010","10001"],
    'Y': ["10001","01010","00100","00100","00100","00100","00100"],
    'Z': ["11111","00001","00010","00100","01000","10000","11111"],
    ' ': ["00000","00000","00000","00000","00000","00000","00000"],
    ':': ["00000","00100","00100","00000","00100","00100","00000"],
    '.': ["00000","00000","00000","00000","00000","00110","00110"],
    ',': ["00000","00000","00000","00000","00000","00110","00010"],
    '-': ["00000","00000","00000","11111","00000","00000","00000"],
    '+': ["00000","00100","00100","11111","00100","00100","00000"],
    '/': ["00001","00010","00100","01000","10000","00000","00000"],
    '%': ["11001","11010","00100","01000","00100","01011","10011"],
    '$': ["00100","01111","10100","01110","00101","11110","00100"],
    '&': ["01000","10100","10100","01000","10101","10010","01101"],
    '(': ["00010","00100","01000","01000","01000","00100","00010"],
    ')': ["01000","00100","00010","00010","00010","00100","01000"],
    '>': ["00000","10000","01000","00100","01000","10000","00000"],
    '<': ["00000","00001","00010","00100","00010","00001","00000"],
    '=': ["00000","00000","11111","00000","11111","00000","00000"],
    "'": ["00100","00100","00000","00000","00000","00000","00000"],
    '*': ["00100","10101","01110","11111","01110","10101","00100"],
    '^': ["00100","01010","10001","00000","00000","00000","00000"],
    'v': ["00000","00000","00000","10001","01010","01010","00100"],
}


def _glyph_surface_5x7(text: str, color=(255,255,0), row_h=8, spacing=1) -> pygame.Surface:
    """Render a microfont string into a pygame Surface."""
    text = text or ""
    char_w, char_h = 5, 7
    n = len(text)
    if n <= 0:
        surf = pygame.Surface((1, row_h), pygame.SRCALPHA); surf.fill((0,0,0,0)); return surf
    width = n * char_w + (n - 1) * spacing
    surf = pygame.Surface((max(1,width), row_h), pygame.SRCALPHA)
    surf.fill((0,0,0,0))
    yoff = max(0, (row_h - char_h) // 2)
    x = 0
    for ch in text:
        pat = _MICRO_GLYPHS.get(ch.upper() if 'A' <= ch <= 'Z' else ch, ["11111","00001","00010","00100","01000","00000","00100"])
        for ry, row in enumerate(pat):
            for rx, bit in enumerate(row):
                if bit == '1': surf.set_at((x+rx, yoff+ry), color)
        x += char_w + spacing
    return surf


def _micro_sanitize(text: str) -> str:
    """Convert Unicode arrows/dashes to available microfont glyphs."""
    if not text: return ""
    return (text.replace("\u2013", "-")   # en-dash
            .replace("\u2014", "-")       # em-dash
            .replace("\u2192", ">")       # right arrow →
            .replace("\u2190", "<")       # left arrow ←
            .replace("\u2026", "...")      # ellipsis …
            )

# ===== SCOREBOARD LOGOS IMPORT =====
try:
    from scoreboard_logos import render_logo_to_surface, get_nfl_logo_code
    LOGOS_AVAILABLE = True
    print("[START] Scoreboard logos loaded successfully", flush=True)
except ImportError:
    LOGOS_AVAILABLE = False
    def render_logo_to_surface(code, w, h):
        import pygame
        s = pygame.Surface((w,h))
        s.fill((0,0,0))
        return s
    def get_nfl_logo_code(code):
        return code
    print("[WARN] scoreboard_logos.py not found - logos disabled", flush=True)
# ===== END SCOREBOARD LOGOS IMPORT =====

# ------------------------------ utils & formatters ------------------------------------------------
def parse_color(name: str):
    palette = {
        "white":(220,220,220), "yellow":(255,255,0), "red":(255,0,0), "green":(0,255,0),
        "cyan":(100,180,255), "blue":(80,160,255), "magenta":(255,80,180), "orange":(255,165,0),
        "grey":(140,140,140), "gray":(140,140,140), "black":(0,0,0)
    }
    return palette.get((name or "").lower().strip(), palette["yellow"])



def format_weather_alert_text(title: str, severity: str) -> str:
    """Return the exact weather alert text from RSS feed."""
    if not title:
        return "WEATHER ALERT"
    return title


def fmt_price_compact(v: float) -> str:
    try: x=float(v)
    except Exception: return "--"
    if x >= 1_000_000: return f"{x/1_000_000:.1f}M"
    if x >= 1_000: return f"{x/1_000:.1f}k"
    return f"{x:.1f}"


def fmt_value_currency_compact(amount: float) -> str:
    if amount is None: return "$--"
    try: x=float(amount)
    except Exception: return "$--"
    if x >= 1_000_000: return f"${x/1_000_000:.1f}M"
    if x >= 1_000: return f"${x/1_000:.1f}k"
    return f"${x:.0f}"


def parse_hhmm(s: str):
    try: hh, mm = s.strip().split(":"); return max(0, min(23, int(hh))), max(0, min(59, int(mm)))
    except Exception: return 0, 0


def time_in_range(now_t: dtime, start_t: dtime, end_t: dtime) -> bool:
    return (start_t <= end_t and start_t <= now_t < end_t) or (start_t > end_t and (now_t >= start_t or now_t < end_t))


def is_off_window_local(now_dt: datetime) -> bool:
    if SCHEDULE_TEST_FORCE_OFF: return True
    if not SCHEDULE_ENABLED: return False
    sh, sm = parse_hhmm(SCHEDULE_OFF_START); eh, em = parse_hhmm(SCHEDULE_OFF_END)
    return time_in_range(now_dt.time(), dtime(sh, sm), dtime(eh, em))


def compute_baseline_dim_scale()->float:
    if not DIM_ENABLED: return 1.0
    if DIM_CUSTOM_PCT > 0: return max(0.01, min(1.0, DIM_CUSTOM_PCT/100.0))
    return {"low":0.30, "medium":0.60, "off":1.0}.get(DIM_LEVEL, 1.0)

DIM_WINDOWS=[]

def _init_dim_windows():
    global DIM_WINDOWS
    DIM_WINDOWS=[]
    for start_var, end_var, pct_var in [("DIM1_START","DIM1_END","DIM1_PCT"),("DIM2_START","DIM2_END","DIM2_PCT"),("DIM3_START","DIM3_END","DIM3_PCT")]:
        sv = globals().get(start_var, ""); ev = globals().get(end_var, ""); pv = globals().get(pct_var, 100)
        if not sv or not ev: continue
        sh, sm = parse_hhmm(sv); eh, em = parse_hhmm(ev)
        DIM_WINDOWS.append((dtime(sh,sm), dtime(eh,em), max(0.01, min(1.0, float(pv)/100.0))))

def apply_night_mode_speed(pps: float, now_dt: datetime)->float:
    if not NIGHT_MODE_ENABLED: return pps
    sh, sm = parse_hhmm(NIGHT_MODE_START); eh, em = parse_hhmm(NIGHT_MODE_END)
    if time_in_range(now_dt.time(), dtime(sh,sm), dtime(eh,em)):
        scale = max(0.01, min(1.0, NIGHT_MODE_SPEED_PCT/100.0)); return pps*scale
    return pps

def current_dim_scale(now_dt: datetime)->float:
    base = compute_baseline_dim_scale()
    if DIM_SCHEDULE_ENABLED:
        for st, et, scale_val in DIM_WINDOWS:
            if time_in_range(now_dt.time(), st, et): return scale_val
    if NIGHT_MODE_ENABLED:
        sh, sm = parse_hhmm(NIGHT_MODE_START); eh, em = parse_hhmm(NIGHT_MODE_END)
        if time_in_range(now_dt.time(), dtime(sh,sm), dtime(eh,em)):
            scale = max(0.01, min(1.0, NIGHT_MODE_DIM_PCT/100.0)); return scale
    if DIM_TEST_ENABLED: return max(0.01, min(1.0, DIM_TEST_PCT/100.0))
    return base

# -------------------- RGB MATRIX FUNCTIONS --------------------

def init_rgb_matrix(width=192, height=16, brightness=100, hardware_mapping='adafruit-hat', 
                     gpio_slowdown=4, pwm_bits=11, pwm_lsb_nanoseconds=130,
                     chain_length=1, parallel=1, scan_mode=0, row_address_type=0,
                     multiplexing=0, led_rgb_sequence='RGB', pixel_mapper='', panel_type=''):
    """
    Initialize the RGB Matrix using rpi-rgb-led-matrix library.
    
    Args:
        width: Panel width (default 192)
        height: Panel height (default 16)
        brightness: Brightness level 0-100 (default 100)
        hardware_mapping: Hardware adapter type (default 'adafruit-hat')
        gpio_slowdown: GPIO slowdown for stability (default 4)
        pwm_bits: PWM bits for color depth (default 11)
        pwm_lsb_nanoseconds: PWM timing (default 130)
        chain_length: Number of panels chained horizontally (default 1)
        parallel: Number of parallel chains (default 1)
        scan_mode: 0=progressive, 1=interlaced (default 0)
        row_address_type: Row addressing method 0-4 (default 0)
        multiplexing: Multiplexing type 0-18 (default 0)
        led_rgb_sequence: LED color order RGB/RBG/GRB/etc (default 'RGB')
        pixel_mapper: Pixel mapper config like 'Rotate:90' (default '')
        panel_type: Panel type hint (default '')
    """
    global RGB_MATRIX, RGB_CANVAS
    
    print(f"[RGB Matrix] Initializing {width}x{height}, brightness={brightness}, hw={hardware_mapping}", flush=True)

    try:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions

        options = RGBMatrixOptions()
        options.rows = height
        options.cols = width
        options.brightness = brightness
        options.hardware_mapping = hardware_mapping
        options.gpio_slowdown = gpio_slowdown
        options.pwm_bits = pwm_bits
        options.pwm_lsb_nanoseconds = pwm_lsb_nanoseconds
        options.disable_hardware_pulsing = False
        options.show_refresh_rate = False
        options.drop_privileges = False

        # Advanced panel configuration
        options.chain_length = chain_length
        options.parallel = parallel
        options.scan_mode = scan_mode
        options.row_address_type = row_address_type
        options.multiplexing = multiplexing
        if led_rgb_sequence:
            options.led_rgb_sequence = led_rgb_sequence
        if pixel_mapper:
            options.pixel_mapper_config = pixel_mapper
        if panel_type:
            options.panel_type = panel_type

        RGB_MATRIX = RGBMatrix(options=options)
        RGB_CANVAS = RGB_MATRIX.CreateFrameCanvas()

        chain_info = f", chain={chain_length}x{parallel}" if (chain_length > 1 or parallel > 1) else ""
        print(f"[RGB Matrix] Ready: {width}x{height} brightness={brightness}% hw={hardware_mapping}{chain_info}", flush=True)
        return True
        
    except ImportError as e:
        print(f"[RGB Matrix] ERROR: rpi-rgb-led-matrix library not found: {e}", flush=True)
        print("[RGB Matrix] Install with: sudo pip3 install rpi-rgb-led-matrix", flush=True)
        return False
    except Exception as e:
        print(f"[RGB Matrix] ERROR initializing matrix: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False


_rgb_dim_warn_ts = 0.0
_rgb_err_ts = 0.0
_rgb_init_warn_ts = 0.0

def write_surface_to_rgb_matrix(surf):
    """
    Write pygame surface to RGB Matrix.
    Returns True on success, False on failure.
    """
    global RGB_CANVAS, RGB_MATRIX, _rgb_dim_warn_ts, _rgb_err_ts, _rgb_init_warn_ts

    if RGB_MATRIX is None or RGB_CANVAS is None:
        now = time.time()
        if now - _rgb_init_warn_ts >= 10.0:
            print("[RGB Matrix] ERROR: Matrix not initialized", flush=True)
            _rgb_init_warn_ts = now
        return False

    try:
        w, h = surf.get_width(), surf.get_height()
        if (w, h) != (W, H):
            now = time.time()
            if now - _rgb_dim_warn_ts >= 10.0:
                print(f"[RGB Matrix] Dimension mismatch: expected {W}x{H}, got {w}x{h}", flush=True)
                _rgb_dim_warn_ts = now
            return False

        # Convert pygame surface to RGB pixel array
        pixels = pygame.surfarray.array3d(surf)

        # Write pixels to RGB Matrix canvas
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                RGB_CANVAS.SetPixel(x, y, int(r), int(g), int(b))

        # Swap the canvas to display
        RGB_CANVAS = RGB_MATRIX.SwapOnVSync(RGB_CANVAS)

        return True

    except Exception as e:
        now = time.time()
        if now - _rgb_err_ts >= 10.0:
            print(f"[RGB Matrix] ERROR writing to matrix: {e}", flush=True)
            _rgb_err_ts = now
        return False


def _resolve_px_auto_row():
    # Match font size to row height for clean rendering
    # In dual mode (ROW_H=8), use 8px font to fill the row perfectly
    if IS_DUAL:
        return max(6, ROW_H) # Use full row height (8px for 16px display)
    return 11 if ROW_H >= 16 else 10 # Single mode uses larger font


def _resolve_px_auto_sb():
    # Fit scoreboard text into compact rows
    if IS_DUAL: return max(6, ROW_H) # Use full row height (8px for dual mode)
    return max(11, ROW_H - (1 if ROW_H <= 16 else 0))


# ------------------------------ PYGAME / FONTS ----------------------------------------------------
def init_pygame():
    """Initialize pygame and create the output surface/window."""
    os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp")
    if OUTPUT_MODE == "RGBMATRIX":
        # RGB Matrix mode - absolute minimal pygame init
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        
        # Minimal init for RGBMATRIX mode - just fonts and surfaces
        try:
            pygame.display.init()
            pygame.font.init()
            clock = pygame.time.Clock()
            screen = pygame.Surface((W, H))
            print(f"[PYGAME] Initialized for RGBMATRIX mode ({W}x{H})", flush=True)
            return screen, clock, False
        except Exception as e:
            print(f"[PYGAME] Init error: {e}", flush=True)
            raise
    else:
        # HDMI mode - create display window
        if FORCE_KMS:
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "0")
        os.environ.setdefault("SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", "1")
        os.environ.setdefault("SDL_RENDER_VSYNC", "1")
        pygame.init()
        pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN])
        clock = pygame.time.Clock()
        
        flags = pygame.FULLSCREEN | pygame.DOUBLEBUF
        scaled_flag = pygame.SCALED if (USE_SDL_SCALED and hasattr(pygame, "SCALED")) else 0
        if scaled_flag:
            flags |= scaled_flag
        try:
            if scaled_flag:
                screen = pygame.display.set_mode((W, H), flags, vsync=1)
                use_hw_scale = True
            else:
                win_size = (W * TICKER_SCALE, H * TICKER_SCALE)
                try:
                    screen = pygame.display.set_mode(win_size, flags, vsync=1)
                except TypeError:
                    screen = pygame.display.set_mode(win_size, flags)
                use_hw_scale = False
        except TypeError:
            if scaled_flag:
                screen = pygame.display.set_mode((W, H), flags)
                use_hw_scale = True
            else:
                screen = pygame.display.set_mode((W * TICKER_SCALE, H * TICKER_SCALE), flags)
                use_hw_scale = False
        pygame.mouse.set_visible(False)
        return screen, clock, use_hw_scale


def make_font(family: str, px: int, bold: bool):
    """Create a pygame font."""
    try:
        f = pygame.font.SysFont(family, px, bold=bold)
        return f
    except Exception:
        return pygame.font.Font(None, px)


def get_holdings_shares(sym: str)->float:
    return float(HOLDINGS.get(sym, {}).get("shares", 0.0))


def get_row_font():
    if font_row: return font_row
    px = FONT_SIZE_ROW if isinstance(FONT_SIZE_ROW, int) else _resolve_px_auto_row()
    return make_font(FONT_FAMILY_BASE, px, FONT_BOLD_BASE)


def get_sb_font():
    if font_sb: return font_sb
    px = FONT_SIZE_SB if isinstance(FONT_SIZE_SB, int) else _resolve_px_auto_sb()
    return make_font(FONT_FAMILY_SCOREBOARD, px, FONT_BOLD_SB)


def get_dbg_font():
    if font_dbg: return font_dbg
    px = FONT_SIZE_DEBUG if isinstance(FONT_SIZE_DEBUG, int) else 6
    return make_font(FONT_FAMILY_DEBUG, px, FONT_BOLD_DEBUG)


def get_preroll_big_font():
    px = PREROLL_FONT_PX if PREROLL_FONT_PX > 0 else max(12, H - 2)
    return make_font(PREROLL_FONT_FAMILY, px, PREROLL_FONT_BOLD)


def get_maint_big_font():
    px = MAINT_FONT_PX if MAINT_FONT_PX > 0 else max(12, H - 2)
    return make_font(MAINT_FONT_FAMILY, px, MAINT_FONT_BOLD)


def row_render_text(txt: str, color, row_h=None, custom_font=None) -> pygame.Surface:
    """Render text using either microfont (if enabled) or normal pygame font."""
    rh = row_h if row_h is not None else ROW_H
    if using_microfont():
        return _glyph_surface_5x7(_micro_sanitize(txt), color, rh, spacing=1)
    else:
        f = custom_font if custom_font else get_row_font()
        return f.render(txt, True, color)


def build_time_surface(dot_color=None, row_font=None):
    """Render time + dot indicator with trailing space, clipped to ROW_H."""
    # Always use row font for ticker display (not the big preroll font)
    font = row_font if row_font else get_row_font()
    
    now_dt = now_local()
    if CLOCK_24H:
        time_str = now_dt.strftime("%H:%M")
    else:
        time_str = now_dt.strftime("%-I:%M")  # 12-hour, no leading zero
    if CLOCK_BLINK_COLON and (now_dt.second % 2 == 0):
        time_str = time_str.replace(":", " ")
    
    # Render time with trailing spaces for separation
    time_str_with_space = time_str + "  "  # Add 2 spaces after time
    time_srf = font.render(time_str_with_space, True, parse_color(CLOCK_COLOR))
    
    # Add status dot BEFORE the time
    time_w = time_srf.get_width()
    time_h = time_srf.get_height()
    dot_w = 2
    spacing = 3
    combined_w = dot_w + spacing + time_w
    
    # CRITICAL: Clip height to exactly ROW_H (8px) to prevent bottom row overlap
    final_h = min(time_h, ROW_H)
    combined = pygame.Surface((combined_w, final_h), pygame.SRCALPHA)
    combined.fill((0,0,0,0))
    
    # Draw dot with provided color or default to GREEN
    # Position dot vertically centered in the clipped height
    dot_col = dot_color if dot_color else GREEN
    dot_x = 0
    dot_y = final_h // 2  # Center the dot vertically in clipped area
    pygame.draw.circle(combined, dot_col, (dot_x + 1, dot_y), 1)
    
    # Blit time AFTER the dot - use subsurface if time is taller than ROW_H
    if time_h > ROW_H:
        # Crop from BOTTOM to keep baseline aligned (remove descenders, not ascenders)
        y_offset = time_h - ROW_H
        time_cropped = time_srf.subsurface((0, y_offset, time_w, ROW_H))
        combined.blit(time_cropped, (dot_w + spacing, 0))
    else:
        # Vertically center the time if it's shorter than ROW_H
        time_y = (final_h - time_h) // 2
        combined.blit(time_srf, (dot_w + spacing, time_y))
    
    return combined


def build_clock_surface(w_full: int, h_full: int):
    """Full-height centered clock."""
    font = get_preroll_big_font()
    now_dt = now_local()
    # Format time
    if CLOCK_24H:
        time_str = now_dt.strftime("%H:%M:%S") if CLOCK_SHOW_SECONDS else now_dt.strftime("%H:%M")
    else:
        time_str = now_dt.strftime("%-I:%M:%S") if CLOCK_SHOW_SECONDS else now_dt.strftime("%-I:%M")
    # Render time
    time_srf = font.render(time_str, True, parse_color(CLOCK_COLOR))
    # Optionally add date below
    if CLOCK_DATE_SHOW:
        date_str = now_dt.strftime(CLOCK_DATE_FMT)
        date_font = make_font(FONT_FAMILY_BASE, max(8, H // 3), FONT_BOLD_BASE)
        date_srf = date_font.render(date_str, True, parse_color(CLOCK_DATE_COLOR))
        # Combine time and date
        total_w = max(time_srf.get_width(), date_srf.get_width())
        total_h = time_srf.get_height() + 2 + date_srf.get_height()
        combined = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
        combined.fill((0, 0, 0, 0))
        # Center time on top
        time_x = (total_w - time_srf.get_width()) // 2
        combined.blit(time_srf, (time_x, 0))
        # Center date below
        date_x = (total_w - date_srf.get_width()) // 2
        combined.blit(date_srf, (date_x, time_srf.get_height() + 2))
        return combined
    else:
        return time_srf


def build_preroll_bigtime_surface(now_dt, font):
    """
    Big centered time display for preroll (static, not scrolling).
    Uses PREROLL_COLOR for the time display.
    """
    if CLOCK_24H:
        time_str = now_dt.strftime("%H:%M:%S") if CLOCK_SHOW_SECONDS else now_dt.strftime("%H:%M")
    else:
        time_str = now_dt.strftime("%-I:%M:%S") if CLOCK_SHOW_SECONDS else now_dt.strftime("%-I:%M")
    if CLOCK_BLINK_COLON and (now_dt.second % 2 == 0):
        time_str = time_str.replace(":", " ")
    
    time_srf = font.render(time_str, True, parse_color(PREROLL_COLOR))
    return time_srf


def build_announcement_surface(text, color, row_font):
    """*** TEXT *** banner surface."""
    return row_render_text(f"*** {text} *** ", color)


def build_weather_alert_surface(text, color):
    """Full-height weather alert surface (uses bigger font for 16px displays)."""
    if IS_DUAL and H >= 16:
        # Use a larger font for full 16px height
        big_font = get_preroll_big_font()
        return big_font.render(f"*** {text} *** ", True, color)
    else:
        # Fall back to normal announcement surface for single row
        return row_render_text(f"*** {text} *** ", color)


def build_message_surface(text, color, row_font):
    """Message surface with trailing space (for smooth scroll concatenation)."""
    return row_render_text(f"{text} ", color)


def build_row_surfaces_from_cache(tickers, market_cache, row_font, holdings_enabled):
    """Return ([surfaces...], any_data_ok)."""
    parts=[]; any_ok=False
    for sym, name in tickers:
        label = row_render_text(f"{name}:", WHITE)
        entry = (market_cache or {}).get(sym) or {}
        pct = entry.get("pct", None); last = entry.get("last", None)
        if pct is None or last is None:
            parts.extend([label, row_render_text("-- ", GREY)])
            continue
        col = GREEN if pct >= 0 else RED
        shares = get_holdings_shares(sym) if holdings_enabled else 0.0
        if shares and shares > 0.0:
            mkt_value = shares * float(last)
            value_txt = f"{fmt_value_currency_compact(mkt_value)} {pct:+.2f}% "
        else:
            value_txt = f"{fmt_price_compact(last)} {pct:+.2f}% "
        parts.extend([label, row_render_text(value_txt, col)]); any_ok=True
    if not parts: parts=[row_render_text("Waiting... ", WHITE)]
    return parts, any_ok

# Dimming - direct pixel manipulation

def apply_dimming_inplace(frame_surf: pygame.Surface, scale: float):
    """Apply dimming by directly scaling pixel values."""
    s = max(0.01, min(1.0, float(scale)))
    if s >= 0.999: return
    try:
        pixels = pygame.surfarray.pixels3d(frame_surf)
        pixels[:] = (pixels * s).astype(pixels.dtype)
    except Exception:
        pass

# ===== FULL-HEIGHT SCOREBOARD RENDERER =====

def render_fullheight_scoreboard(frame, game_data, font_big, flash_home=False, flash_away=False, flash_color=(255,255,255)):
    """
    Render full-height 192x16 scoreboard with team logos and big scores.
    """
    W_local = frame.get_width()
    H_local = frame.get_height()
    frame.fill((0, 0, 0))

    home_code = game_data.get("home_code", "???")
    away_code = game_data.get("away_code", "???")
    home_score = game_data.get("home_score", 0)
    away_score = game_data.get("away_score", 0)
    clock = game_data.get("clock", "")
    period = game_data.get("period", "")
    league = game_data.get("league", "NHL")

    # For 192x16 displays (full layout)
    if W_local >= 192:
        # Render team logos
        if LOGOS_AVAILABLE:
            try:
                if league == "NFL":
                    home_logo_code = get_nfl_logo_code(home_code)
                    away_logo_code = get_nfl_logo_code(away_code)
                else:
                    home_logo_code = home_code
                    away_logo_code = away_code
                home_logo = render_logo_to_surface(home_logo_code, 32, 16)
                away_logo = render_logo_to_surface(away_logo_code, 32, 16)
                frame.blit(home_logo, (0, 0))
                frame.blit(away_logo, (160, 0))
            except Exception:
                pass  # Logo rendering is best-effort
        # Logos not available - team codes will show via score text
        # Render scores
        score_color_home = flash_color if flash_home else (255, 255, 255)
        score_color_away = flash_color if flash_away else (255, 255, 255)
        home_score_text = font_big.render(str(home_score), True, score_color_home)
        away_score_text = font_big.render(str(away_score), True, score_color_away)
        home_score_x = 34
        home_score_y = (H_local - home_score_text.get_height()) // 2
        away_score_x = 158 - away_score_text.get_width()
        away_score_y = (H_local - away_score_text.get_height()) // 2
        frame.blit(home_score_text, (home_score_x, home_score_y))
        frame.blit(away_score_text, (away_score_x, away_score_y))
        # Center area for clock/period
        if clock:
            clock_text = font_big.render(clock, True, (255, 255, 0))
            clock_x = 48 + (96 - clock_text.get_width()) // 2
            clock_y = 0
            frame.blit(clock_text, (clock_x, clock_y))
        if period:
            try:
                period_font = pygame.font.SysFont("monospace", 8, bold=True)
                period_text = period_font.render(str(period), True, (180, 180, 180))
                period_x = 48 + (96 - period_text.get_width()) // 2
                period_y = H_local - period_text.get_height()
                frame.blit(period_text, (period_x, period_y))
            except Exception:
                pass
    else:
        score_color_home = flash_color if flash_home else (255, 255, 255)
        score_color_away = flash_color if flash_away else (255, 255, 255)
        home_text = f"{home_code} {home_score}"
        away_text = f"{away_score} {away_code}"
        home_surf = font_big.render(home_text, True, score_color_home)
        away_surf = font_big.render(away_text, True, score_color_away)
        frame.blit(home_surf, (2, (H_local - home_surf.get_height()) // 2))
        away_x = W_local - away_surf.get_width() - 2
        frame.blit(away_surf, (away_x, (H_local - away_surf.get_height()) // 2))
        if clock and period:
            center_text = f"{clock} {period}"
            center_surf = font_big.render(center_text, True, (255, 255, 0))
            center_x = (W_local - center_surf.get_width()) // 2
            frame.blit(center_surf, (center_x, (H_local - center_surf.get_height()) // 2))

class ScoreboardFlashState:
    """Track which team's score is currently flashing after a goal."""
    def __init__(self):
        self.flashing = False
        self.team = None # "home" or "away"
        self.cycles_left = 0
        self.flash_idx = 0
        self.flash_colors = [(255,0,0), (255,255,255), (0,0,255)] # red, white, blue
        self.flash_ms = 250
        self.flash_next_ts = 0.0
    def start_flash(self, team: str, cycles: int = 4):
        """Start flashing for the specified team."""
        import time
        self.flashing = True
        self.team = team
        self.cycles_left = cycles
        self.flash_idx = 0
        self.flash_next_ts = time.time() + (self.flash_ms / 1000.0)
    def get_flash_color(self):
        """Get current flash color, advancing if needed."""
        import time
        if not self.flashing:
            return None
        now = time.time()
        if now >= self.flash_next_ts:
            self.flash_idx = (self.flash_idx + 1) % len(self.flash_colors)
            self.flash_next_ts = now + (self.flash_ms / 1000.0)
            # Check if we've completed a cycle
            if self.flash_idx == 0:
                self.cycles_left -= 1
                if self.cycles_left <= 0:
                    self.flashing = False
                    self.team = None
                    return None
        return self.flash_colors[self.flash_idx]
    def is_flashing(self, team: str) -> bool:
        """Check if the specified team is currently flashing."""
        return self.flashing and self.team == team
