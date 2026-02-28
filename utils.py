#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Property of solutions reseaux chromatel
"""
LED Ticker - Shared Utilities
==============================
Shared functions used by both the main ticker and workers.
Includes: market hours detection, data fetching, config helpers, etc.
"""

import os
import time
import json
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, time as dtime

# Timezone support
try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

# yfinance for market data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

# Global timezone (set by set_globals)
TZINFO = None

def set_globals(**kwargs):
    """Set globals from main ticker."""
    global TZINFO
    if 'TZINFO' in kwargs:
        TZINFO = kwargs['TZINFO']

def now_local():
    """Get current time in local timezone."""
    return datetime.now(TZINFO) if TZINFO else datetime.now().astimezone()

# =================================================================================================
# ===================================== STATUS FILE HELPERS =======================================
# =================================================================================================

def update_worker_status(status_path: str, worker_name: str, status: dict):
    """Update worker status in ticker_status.json."""
    try:
        # Load existing status
        status_data = {}
        if os.path.exists(status_path):
            try:
                with open(status_path, "r", encoding="utf-8") as f:
                    status_data = json.load(f) or {}
            except Exception:
                pass
        
        # Update worker status
        if "workers" not in status_data:
            status_data["workers"] = {}
        status_data["workers"][worker_name] = {
            **status,
            "timestamp": time.time()
        }
        
        # Write atomically
        with open(status_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
        os.replace(status_path + ".tmp", status_path)
    except Exception:
        # Don't crash on status write failures
        pass

# =================================================================================================
# ===================================== MARKET HELPERS ============================================
# =================================================================================================

def is_us_market_open() -> bool:
    """
    Determine if US stock market is open (Mon-Fri, 9:30 AM - 4:00 PM ET).
    Returns True if market should be open, False otherwise.
    """
    if not PYTZ_AVAILABLE:
        # Fallback: basic time-based check without timezone (less accurate)
        now = datetime.now()
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        hour = now.hour
        # Rough guess assuming system is in ET or close
        is_weekday = weekday < 5  # Mon-Fri
        is_business_hours = (9 <= hour < 16)
        return is_weekday and is_business_hours
    
    try:
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        weekday = now_et.weekday()  # 0=Monday, 6=Sunday
        
        # Check if it's a weekday (Monday-Friday)
        if weekday >= 5:  # Saturday or Sunday
            return False
        
        # Check if within market hours (9:30 AM - 4:00 PM ET)
        hour = now_et.hour
        minute = now_et.minute
        
        # Market opens at 9:30 AM
        if hour < 9 or (hour == 9 and minute < 30):
            return False
        
        # Market closes at 4:00 PM (16:00)
        if hour >= 16:
            return False
        
        return True
    except Exception:
        # Fallback to simple check
        now = datetime.now()
        weekday = now.weekday()
        hour = now.hour
        is_weekday = weekday < 5
        is_business_hours = (9 <= hour < 16)
        return is_weekday and is_business_hours

def get_market_event_announcement() -> tuple:
    """
    Check if we should show a market open/close announcement.
    Returns (should_show, message, color) tuple.
    Property of solutions reseaux chromatel
    """
    if not PYTZ_AVAILABLE:
        return (False, "", "green")
    
    try:
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        weekday = now_et.weekday()  # 0=Monday, 6=Sunday
        
        # Only on weekdays
        if weekday >= 5:
            return (False, "", "green")
        
        hour = now_et.hour
        minute = now_et.minute
        
        # Market open: 9:30 AM (show for 3 minutes: 9:30:00-9:32:59)
        if hour == 9 and 30 <= minute < 33:
            return (True, "*** MARKET OPEN ***", "green")
        
        # Market close: 4:00 PM / 16:00 (show for 3 minutes: 16:00:00-16:02:59)
        if hour == 16 and minute < 3:
            return (True, "*** MARKET CLOSED ***", "red")
        
        return (False, "", "green")
    except Exception:
        return (False, "", "green")

def safe_fetch_last_prev(sym):
    """Best-effort get last/previous close and compute pct change via yfinance."""
    if not YFINANCE_AVAILABLE:
        return None, None
    
    try:
        t = yf.Ticker(sym); last = prev = None
        fi = getattr(t, "fast_info", None)
        if fi:
            last = fi.get("last_price", None)
            prev = fi.get("previous_close", None)
        if last is None or prev is None:
            hist = t.history(period="5d", interval="1d", auto_adjust=False, prepost=False)
            if not hist.empty:
                last = float(hist["Close"].iloc[-1]); prev = float(hist["Close"].iloc[-2]) if len(hist)>1 else last
        if last is None or prev is None or float(prev)==0.0: return None, None
        return float(last), float(prev)
    except Exception:
        return None, None

# =================================================================================================
# ===================================== WEATHER HELPERS ===========================================
# =================================================================================================

def normalize_ws(s: str) -> str:
    """Normalize whitespace in string."""
    return " ".join((s or "").split())

def ascii_fold(s: str) -> str:
    """Strip diacritics so accented chars render cleanly on LED (e.g. é→e, È→E, ñ→n)."""
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")

def fetch_weather_warning(rss_url: str, timeout: float = 5.0, include_watch: bool = True):
    """Parse Environment Canada RSS/Atom for Watch/Warning. Returns (active, message, severity)."""
    try:
        with urllib.request.urlopen(rss_url, timeout=timeout) as resp:
            xmlb = resp.read()
    except Exception:
        return False, "", ""
    try: 
        root = ET.fromstring(xmlb)
    except Exception: 
        return False, "", ""
    
    # Try Atom format first (Environment Canada current format)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('.//atom:entry', ns)
    
    if entries:
        for entry in entries:
            title_elem = entry.find('atom:title', ns)
            title = ascii_fold((title_elem.text or "").strip() if title_elem is not None else "")
            t = title.lower()
            
            # Skip "no watches or warnings" messages
            if "no watch" in t or "no warning" in t or "no advisory" in t or "no statement" in t:
                continue

            # Skip ENDED alerts
            if "ended" in t:
                continue

            # Determine severity based on color prefix
            severity = ""
            if "red warning" in t or "red advisory" in t:
                severity = "warning"  # RED = highest severity
            elif "orange warning" in t or "orange advisory" in t:
                severity = "warning"  # ORANGE = high severity (also treat as warning)
            elif "yellow warning" in t or "yellow advisory" in t:
                severity = "advisory"  # YELLOW = medium severity
            elif "warning" in t:
                # Generic warning without color prefix - treat as high severity
                severity = "warning"
            elif "advisory" in t:
                # Generic advisory without color prefix
                severity = "advisory"
            elif "watch" in t:
                severity = "watch"
            elif "statement" in t:
                # Special Weather Statement — own severity level, controlled by include_watch
                severity = "statement"

            # Only return if we have a valid severity
            if severity == "warning":
                msg = title if len(title) <= 80 else title[:80].rstrip() + "..."
                return True, msg, "warning"
            elif severity in ["advisory", "watch", "statement"] and include_watch:
                msg = title if len(title) <= 80 else title[:80].rstrip() + "..."
                return True, msg, severity

    # Fallback: RSS format
    channel = root.find("./channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = ascii_fold(normalize_ws(item.findtext("title") or ""))
            t = title.lower()

            # Skip "no watches or warnings" messages
            if "no watch" in t or "no warning" in t or "no advisory" in t or "no statement" in t:
                continue

            # Skip ENDED alerts
            if "ended" in t:
                continue

            # Determine severity based on color prefix
            severity = ""
            if "red warning" in t or "red advisory" in t:
                severity = "warning"  # RED = highest severity
            elif "orange warning" in t or "orange advisory" in t:
                severity = "warning"  # ORANGE = high severity
            elif "yellow warning" in t or "yellow advisory" in t:
                severity = "advisory"  # YELLOW = medium severity
            elif "warning" in t:
                # Generic warning without color prefix
                severity = "warning"
            elif "advisory" in t:
                # Generic advisory without color prefix
                severity = "advisory"
            elif "watch" in t:
                severity = "watch"
            elif "statement" in t:
                # Special Weather Statement — own severity level, controlled by include_watch
                severity = "statement"

            # Only return if we have a valid severity
            if severity == "warning":
                msg = title if len(title) <= 80 else title[:80].rstrip() + "..."
                return True, msg, "warning"
            elif severity in ["advisory", "watch", "statement"] and include_watch:
                msg = title if len(title) <= 80 else title[:80].rstrip() + "..."
                return True, msg, severity
    
    return False, "", ""

# =================================================================================================
# ===================================== QUEUE HELPERS =============================================
# =================================================================================================

def put_latest(q, payload: dict):
    """Drop stale payloads and push the newest one to the queue."""
    import queue as queue_std
    try:
        while True: q.get_nowait()
    except queue_std.Empty:
        pass
    try:
        q.put_nowait(payload)
    except queue_std.Full:
        # Queue still full after drain (race condition) - drop oldest and retry
        try:
            q.get_nowait()
        except queue_std.Empty:
            pass
        try:
            q.put_nowait(payload)
        except queue_std.Full:
            pass  # Give up silently rather than crash
