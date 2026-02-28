#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Property of solutions reseaux chromatel
"""
LED Ticker - Data Worker Processes
===================================
Worker processes that fetch external data in parallel.
"""

import time
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from multiprocessing import Queue

from utils import (
    is_us_market_open, safe_fetch_last_prev,
    fetch_weather_warning,
    update_worker_status, put_latest, now_local
)

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from nhlpy import NHLClient
    NHLPY_AVAILABLE = True
except ImportError:
    NHLPY_AVAILABLE = False
    NHLClient = None

# Globals set by ticker.py
TZINFO = None
STATUS_PATH = None
SCOREBOARD_PREGAME_WINDOW_MIN = 30
SCOREBOARD_POSTGAME_DELAY_MIN = 5


def set_globals(**kwargs):
    """Set global variables from ticker.py"""
    global TZINFO, STATUS_PATH, SCOREBOARD_PREGAME_WINDOW_MIN, SCOREBOARD_POSTGAME_DELAY_MIN
    TZINFO = kwargs.get('TZINFO')
    STATUS_PATH = kwargs.get('STATUS_PATH')
    SCOREBOARD_PREGAME_WINDOW_MIN = kwargs.get('SCOREBOARD_PREGAME_WINDOW_MIN', 30)
    SCOREBOARD_POSTGAME_DELAY_MIN = kwargs.get('SCOREBOARD_POSTGAME_DELAY_MIN', 5)


def market_worker(all_syms, refresh_sec, out_q: Queue, status_path=None, tzinfo=None):
    """Poll yfinance for all symbols and publish a compact cache snapshot."""
    # Property of solutions reseaux chromatel
    # Set globals for this worker process
    global STATUS_PATH, TZINFO
    STATUS_PATH = status_path
    TZINFO = tzinfo

    while True:
        fetch_start = time.time()
        snapshot = {"ts": time.time(), "data": {}, "market_state": "UNKNOWN", "ok_any": False}
        any_ok = False
        market_state = "UNKNOWN"
        error_msg = ""

        # Try to get market state from S&P 500 first
        try:
            sp_ticker = yf.Ticker("^GSPC")
            fi = getattr(sp_ticker, "fast_info", None)
            if fi:
                yf_state = fi.get("market_state", "UNKNOWN") or "UNKNOWN"
                market_state = yf_state.upper()
        except Exception as e:
            error_msg = f"S&P fetch failed: {str(e)[:50]}"

        # If yfinance doesn't give us a clear state, use time-based detection
        if market_state == "UNKNOWN" or not market_state:
            market_state = "REGULAR" if is_us_market_open() else "CLOSED"

        # Fetch data for all symbols
        symbols_failed = 0
        for sym in all_syms:
            try:
                last, prev = safe_fetch_last_prev(sym)
                pct = None
                if last is not None and prev not in (None, 0.0):
                    pct = ((last - prev) / prev) * 100.0
                    any_ok = True
                else:
                    symbols_failed += 1
                snapshot["data"][sym] = {"last": last, "prev": prev, "pct": pct, "ts": time.time()}
            except Exception:
                symbols_failed += 1
                snapshot["data"][sym] = {"last": None, "prev": None, "pct": None, "ts": time.time()}

        snapshot["market_state"] = market_state
        snapshot["ok_any"] = any_ok
        fetch_duration = time.time() - fetch_start

        # Determine overall status
        if symbols_failed == len(all_syms):
            status = "error"
            error_msg = "All symbols failed to fetch"
        elif symbols_failed > 0:
            status = "partial"
            error_msg = f"{symbols_failed}/{len(all_syms)} symbols failed"
        elif any_ok:
            status = "ok"
        else:
            status = "no_data"

        # Update status file
        if status_path:
            update_worker_status(status_path, "market", {
                "status": status,
                "market_state": market_state,
                "symbols_count": len(all_syms),
                "symbols_failed": symbols_failed,
                "fetch_duration_sec": round(fetch_duration, 2),
                "error_message": error_msg if error_msg else None,
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
            })

        try:
            put_latest(out_q, {"type": "market", "payload": snapshot})
        except Exception as e:
            print(f"[MARKET] Queue put failed: {e}", flush=True)

        time.sleep(max(5, refresh_sec))


def weather_worker(rss_url, include_watch, refresh_sec, timeout_s, force_active, force_text, out_q: Queue, status_path=None, tzinfo=None):
    """Check RSS for watch/warning and publish an 'active' flag + message."""
    # Set globals for this worker process
    global STATUS_PATH, TZINFO
    STATUS_PATH = status_path
    TZINFO = tzinfo

    while True:
        fetch_start = time.time()
        error_msg = None
        try:
            if force_active:
                active = True
                msg = force_text or "TEST WEATHER WARNING"
                severity = "warning"
                status = "active"
            else:
                active, msg, severity = fetch_weather_warning(rss_url, timeout=timeout_s, include_watch=include_watch)
                status = "active" if active else "ok"
        except Exception as e:
            active = False
            msg = ""
            severity = "none"
            status = "error"
            error_msg = f"Connection failed: {str(e)[:50]}"

        fetch_duration = time.time() - fetch_start

        # Update status file
        if status_path:
            update_worker_status(status_path, "weather", {
                "status": status,
                "severity": severity if active else "none",
                "fetch_duration_sec": round(fetch_duration, 2),
                "error_message": error_msg,
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
            })

        try:
            put_latest(out_q, {"type": "weather", "payload": {"ts": time.time(), "active": bool(active), "message": msg, "severity": severity}})
        except Exception as e:
            print(f"[WEATHER] Queue put failed: {e}", flush=True)

        time.sleep(max(10, refresh_sec))




def _es_nhl_has_game_today(teams: set) -> bool:
    """Check ESPN NHL scoreboard for any game involving the given teams today."""
    url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
    try:
        with urllib.request.urlopen(url, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return False
    for ev in (data or {}).get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        comp_status = comp.get("status") or {}
        status_type = comp_status.get("type") or {}
        if (status_type.get("state") or "").lower() == "post":
            continue  # Game already finished — don't count it for the blue dot
        for c in (comp.get("competitors") or []):
            abbrev = ((c.get("team") or {}).get("abbreviation") or "").upper()
            if abbrev in teams:
                return True
    return False


def _es_nhl_fetch_now():
    """Fetch ESPN NHL scoreboard and normalize to the same game dict format as _nhl_fetch_now_via_apiweb."""
    url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
    try:
        with urllib.request.urlopen(url, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    out = []
    for ev in (data or {}).get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        comp_status = comp.get("status") or {}
        status = comp_status.get("type") or {}      # state/period live in status.type
        state = (status.get("state") or "").lower()
        mapped = {"pre": "PREGAME", "in": "LIVE", "post": "FINAL"}.get(state, state.upper() or "FUT")
        period = int(status.get("period") or comp_status.get("period") or 0)
        clock = comp_status.get("displayClock") or status.get("displayClock") or ""  # displayClock is at status level, not status.type
        if period > 3:
            period_label = "OT"
        elif period > 0:
            period_label = f"P{period}"
        else:
            period_label = ""
        compet = comp.get("competitors") or []
        home = next((c for c in compet if c.get("homeAway") == "home"), None)
        away = next((c for c in compet if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hteam = home.get("team") or {}
        ateam = away.get("team") or {}
        out.append({
            "league": "NHL", "state": mapped, "period": period, "clock": clock,
            "period_label": period_label,
            "home": {"code": (hteam.get("abbreviation") or "").upper(), "score": int(home.get("score") or 0), "sog": 0},
            "away": {"code": (ateam.get("abbreviation") or "").upper(), "score": int(away.get("score") or 0), "sog": 0},
            "possession": None,
            "id": str(ev.get("id") or comp.get("id") or ""),
            "start_ts": ev.get("date") or None
        })
    return out


def _es_nfl_fetch_now():
    """Fetch ESPN NFL scoreboard (public JSON) and normalize."""
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    try:
        with urllib.request.urlopen(url, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []
    out = []
    for ev in (data or {}).get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type", {})
        state = (status.get("state") or "").lower()
        mapped = {"pre": "PREGAME", "in": "LIVE", "post": "FINAL"}.get(state, state.upper() or "UNKNOWN")
        period = status.get("period") or 0
        clock = status.get("displayClock") or ""
        compet = comp.get("competitors") or []
        home = next((c for c in compet if c.get("homeAway") == "home"), None)
        away = next((c for c in compet if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hteam = (home.get("team") or {})
        ateam = (away.get("team") or {})
        out.append({
            "league": "NFL", "state": mapped, "period": int(period), "clock": clock,
            "home": {"code": (hteam.get("abbreviation") or "").upper(), "score": int(home.get("score") or 0)},
            "away": {"code": (ateam.get("abbreviation") or "").upper(), "score": int(away.get("score") or 0)},
            "possession": (comp.get("situation") or {}).get("possession", "").upper() if comp.get("situation") else None,
            "id": ev.get("id") or comp.get("id") or "",
            "start_ts": ev.get("date") or None
        })
    return out


def _nhl_fetch_now_via_apiweb():
    """Fetch NHL 'score/now' JSON and normalize."""
    url = "https://api-web.nhle.com/v1/score/now"
    try:
        with urllib.request.urlopen(url, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []

    out = []
    for g in (data or {}).get("games", []):
        st = (g.get("gameState") or "").upper()
        pd = (g.get("periodDescriptor") or {})
        period = int(pd.get("number") or 0)
        period_type = (pd.get("periodType") or "").upper()
        clock = g.get("clock", "") or ""

        # Format period label: OT for overtime, SO for shootout
        if period_type == "SO":
            period_label = "SO"
        elif period_type == "OT" or period > 3:
            period_label = "OT"
        else:
            period_label = f"P{period}"

        home = g.get("homeTeam") or {}
        away = g.get("awayTeam") or {}
        out.append({
            "league": "NHL",
            "state": {"CRIT": "LIVE"}.get(st, st),
            "period": period, "clock": clock,
            "period_label": period_label,
            "home": {"code": (home.get("abbrev") or "").upper(), "score": int(home.get("score") or 0), "sog": int(home.get("sog") or 0)},
            "away": {"code": (away.get("abbrev") or "").upper(), "score": int(away.get("score") or 0), "sog": int(away.get("sog") or 0)},
            "possession": None,
            "id": str(g.get("id") or ""),
            "start_ts": g.get("startTimeUTC") or None
        })
    return out


def _nhl_schedule_today_via_wrapper(client: "NHLClient"):
    """Use nhlpy wrapper (if available) to supplement pregame windows."""
    try:
        sched = client.schedule.daily_schedule()
        games = []
        for g in (sched or []):
            home = ((g.get("homeTeam") or g.get("home") or {}).get("abbrev")
                    or (g.get("homeTeam") or g.get("home") or {}).get("triCode") or "").upper()
            away = ((g.get("awayTeam") or g.get("away") or {}).get("abbrev")
                    or (g.get("awayTeam") or g.get("away") or {}).get("triCode") or "").upper()
            start_ts = g.get("startTimeUTC") or g.get("gameDate") or None
            games.append({"home": home, "away": away, "start_ts": start_ts})
        return games
    except Exception:
        return []


def _team_in_list(game, wanted: set):
    """True if either team is one of the 'wanted' codes."""
    return (game["home"]["code"] in wanted) or (game["away"]["code"] in wanted)


def _within_window(start_ts_iso: str, minutes_before: int):
    """Check if we're within N minutes before scheduled start. Returns (is_within, minutes_until)."""
    if not start_ts_iso:
        return False, None
    try:
        dt_utc = datetime.fromisoformat(start_ts_iso.replace("Z", "+00:00"))
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        game_local = dt_utc.astimezone(TZINFO) if TZINFO else dt_utc.astimezone()
        now = now_local()
        delta = game_local - now
        minutes_until = int(delta.total_seconds() / 60)
        is_within = now >= (game_local - timedelta(minutes=minutes_before))
        return is_within, minutes_until
    except Exception:
        return False, None


def _filter_postgame_games(games, final_states, game_hours, postgame_delay_min):
    """Return games excluding FINAL/OFF games that are past the postgame window."""
    result = []
    for g in games:
        state = g.get("state", "").upper()
        if state in final_states:
            start_ts = g.get("start_ts") or ""
            if start_ts:
                try:
                    dt_utc = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                    if dt_utc.tzinfo is None:
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                    game_local = dt_utc.astimezone(TZINFO) if TZINFO else dt_utc.astimezone()
                    approx_end = game_local + timedelta(hours=game_hours)
                    mins_since_end = (now_local() - approx_end).total_seconds() / 60
                    if mins_since_end <= postgame_delay_min:
                        result.append(g)
                except Exception:
                    pass
        else:
            result.append(g)
    return result


def _apply_pregame_window(games_raw, window_min):
    """Filter pregame games to those within window, annotating with minutes_until_start."""
    result = []
    for g in games_raw:
        is_within, mins_until = _within_window(g.get("start_ts") or "", window_min)
        if is_within:
            g["minutes_until_start"] = mins_until
            result.append(g)
    return result


def _order_and_trim_games(live_mine, live_others, pre_mine, pre_others, include_others, only_mine, max_games):
    """Order games by priority: live my teams, live others, pregame my teams, pregame others."""
    ordered = list(live_mine)
    if include_others and not only_mine:
        ordered += live_others
    ordered += pre_mine
    if include_others and not only_mine:
        ordered += pre_others
    return ordered[:max_games]


def scoreboard_worker(leagues, nhl_teams, nfl_teams, window_min, pre_cadence, live_cadence,
                      include_others, only_mine, max_games, test_cfg, out_q: Queue, status_path=None, tzinfo=None,
                      pregame_window_min=30, postgame_delay_min=5):
    """Continuously fetch NHL/NFL data (or emit test payloads) and publish."""
    # Set globals for this worker process
    global STATUS_PATH, TZINFO, SCOREBOARD_PREGAME_WINDOW_MIN, SCOREBOARD_POSTGAME_DELAY_MIN
    STATUS_PATH = status_path
    TZINFO = tzinfo
    SCOREBOARD_PREGAME_WINDOW_MIN = pregame_window_min
    SCOREBOARD_POSTGAME_DELAY_MIN = postgame_delay_min

    print("[SB] worker starting; test=", int(test_cfg.get("enabled", False)), flush=True)

    test_mode = test_cfg.get("enabled", False)
    test_until = time.time() + test_cfg.get("duration", 0) if (test_mode and test_cfg.get("duration", 0) > 0) else None
    test_league = (test_cfg.get("league") or "NHL").upper()
    auto_home = (test_cfg.get("home") or "").upper()
    if not auto_home:
        if test_league == "NHL" and nhl_teams:
            auto_home = nhl_teams[0]
        elif test_league == "NFL" and nfl_teams:
            auto_home = nfl_teams[0]
        else:
            auto_home = "MTL" if test_league == "NHL" else "NE"
    auto_away = (test_cfg.get("away") or "").upper() or "OPP"

    nhl_client = None
    if NHLPY_AVAILABLE and ("NHL" in leagues) and (not test_mode):
        try:
            nhl_client = NHLClient()
        except Exception:
            nhl_client = None

    cadence = pre_cadence

    while True:
        error_msg = None
        fetch_status = "ok"
        try:
            now = time.time()
            payloads = []
            game_today = False  # True if any watched team has a game today

            if test_mode and (test_until is None or now <= test_until):
                elapsed = int(now % 600)
                home_score = elapsed // 120
                away_score = (elapsed // 180)
                minute = (elapsed // 2) % 20
                second = (elapsed * 3) % 60
                clock = f"{20 - minute:02d}:{59 - second:02d}"
                period = 3 if elapsed > 360 else 2 if elapsed > 180 else 1
                payloads.append({
                    "league": test_league,
                    "games": [{
                        "league": test_league, "state": "LIVE", "period": period, "clock": clock,
                        "home": {"code": auto_home, "score": home_score, "sog": 20 + home_score},
                        "away": {"code": auto_away, "score": away_score, "sog": 19 + away_score},
                        "possession": "HOME" if ((elapsed // 10) % 2) == 0 else "AWAY",
                        "id":"TEST-1","start_ts":None
                    }],
                    "ts": now
                })
                cadence = 3
            else:
                # NFL
                if "NFL" in leagues:
                    try:
                        nfl_all = _es_nfl_fetch_now()
                    except Exception as e:
                        nfl_all = []
                        error_msg = f"NFL fetch failed: {str(e)[:50]}"
                        fetch_status = "error"

                    nfl_all = _filter_postgame_games(nfl_all, {"FINAL"}, 3, SCOREBOARD_POSTGAME_DELAY_MIN)

                    wanted = set([t for t in nfl_teams if t])
                    if any(_team_in_list(g, wanted) for g in nfl_all):
                        game_today = True
                    live_mine = [g for g in nfl_all if g["state"] == "LIVE" and _team_in_list(g, wanted)]
                    live_others = [g for g in nfl_all if g["state"] == "LIVE" and not _team_in_list(g, wanted)]
                    pre_mine = _apply_pregame_window(
                        [g for g in nfl_all if g["state"] == "PREGAME" and _team_in_list(g, wanted)],
                        SCOREBOARD_PREGAME_WINDOW_MIN)
                    pre_others = _apply_pregame_window(
                        [g for g in nfl_all if g["state"] == "PREGAME" and not _team_in_list(g, wanted)],
                        SCOREBOARD_PREGAME_WINDOW_MIN)

                    trimmed = _order_and_trim_games(live_mine, live_others, pre_mine, pre_others, include_others, only_mine, max_games)
                    if trimmed:
                        payloads.append({"league":"NFL","games":trimmed,"ts":now})

                # NHL
                if "NHL" in leagues:
                    try:
                        nhl_now = _nhl_fetch_now_via_apiweb()
                    except Exception as e:
                        nhl_now = []
                        if not error_msg:
                            error_msg = f"NHL fetch failed: {str(e)[:50]}"
                        else:
                            error_msg += f" & NHL failed: {str(e)[:30]}"
                        fetch_status = "error"

                    # If NHL API returned nothing, fall back to ESPN NHL scoreboard for all game data
                    if not nhl_now:
                        nhl_now = _es_nhl_fetch_now()

                    nhl_now = _filter_postgame_games(nhl_now, {"FINAL", "OFF"}, 2.5, SCOREBOARD_POSTGAME_DELAY_MIN)

                    wanted = set([t for t in nhl_teams if t])
                    if any(_team_in_list(g, wanted) for g in nhl_now):
                        game_today = True
                    elif not game_today:
                        # Both APIs empty — last resort check via ESPN
                        game_today = _es_nhl_has_game_today(wanted)
                    live_mine = [g for g in nhl_now if g["state"] == "LIVE" and _team_in_list(g, wanted)]
                    live_others = [g for g in nhl_now if g["state"] == "LIVE" and not _team_in_list(g, wanted)]

                    pre_all = []
                    if nhl_client:
                        try:
                            sched = _nhl_schedule_today_via_wrapper(nhl_client)
                            for s in sched:
                                is_within, _mins = _within_window(s.get("start_ts") or "", window_min)
                                if not is_within:
                                    continue
                                pre_all.append({
                                    "league":"NHL","state":"PREGAME","period":0,"clock":"",
                                    "home":{"code":s["home"],"score":0,"sog":0},
                                    "away":{"code":s["away"],"score":0,"sog":0},
                                    "possession":None,"id":"", "start_ts": s["start_ts"]
                                })
                        except Exception:
                            pass

                    for g in nhl_now:
                        if g["state"] in ("FUT", "PREGAME"):
                            is_within, _mins = _within_window(g.get("start_ts") or "", window_min)
                            if is_within:
                                pre_all.append({**g, "state":"PREGAME"})

                    pre_mine = _apply_pregame_window(
                        [g for g in pre_all if _team_in_list(g, wanted)],
                        SCOREBOARD_PREGAME_WINDOW_MIN)
                    pre_others = _apply_pregame_window(
                        [g for g in pre_all if not _team_in_list(g, wanted)],
                        SCOREBOARD_PREGAME_WINDOW_MIN)

                    trimmed = _order_and_trim_games(live_mine, live_others, pre_mine, pre_others, include_others, only_mine, max_games)
                    if trimmed:
                        payloads.append({"league":"NHL","games":trimmed,"ts":now})

            any_live = any(any(g["state"] == "LIVE" for g in p.get("games", [])) for p in payloads)
            cadence = live_cadence if any_live else pre_cadence

            for p in payloads:
                try:
                    put_latest(out_q, {"type":"scoreboard","payload":p})
                except Exception as e:
                    print(f"[SB] Queue put failed: {e}", flush=True)

            # Always broadcast game-today flag for dot color (independent of pregame window)
            try:
                put_latest(out_q, {"type":"scoreboard_status","payload":{"game_today":game_today,"ts":now}})
            except Exception as e:
                print(f"[SB] Status put failed: {e}", flush=True)

            # Update status file
            total_games = sum(len(p.get("games", [])) for p in payloads)
            live_games = sum(sum(1 for g in p.get("games", []) if g.get("state") == "LIVE") for p in payloads)
            pregame_games = sum(sum(1 for g in p.get("games", []) if g.get("state") == "PREGAME") for p in payloads)

            leagues_with_games = []
            for p in payloads:
                league = p.get("league", "").upper()
                games_count = len(p.get("games", []))
                if league and games_count > 0:
                    leagues_with_games.append(f"{league}:{games_count}")

            if status_path:
                update_worker_status(status_path, "scoreboard", {
                    "status": "error" if fetch_status == "error" else ("live" if live_games > 0 else "ok" if total_games > 0 else "idle"),
                    "total_games": total_games,
                    "live_games": live_games,
                    "pregame_games": pregame_games,
                    "leagues_with_games": leagues_with_games,
                    "game_today": game_today,
                    "test_mode": test_mode,
                    "error_message": error_msg,
                    "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                })

            time.sleep(max(3, cadence))

        except Exception as e:
            print(f"[SB] Worker cycle error: {e}", flush=True)
            time.sleep(pre_cadence)
