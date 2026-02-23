#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Property of solutions reseaux chromatel
"""
LED Ticker - Control Panel (with Live Preview)
==============================================
This Flask UI edits `config.json`, provides temporary overrides, and exposes
a Live Preview of the current display when the ticker is running.

Notes
-----
 - Preview works in both HDMI and RGBMATRIX modes by reading preview frames from /tmp/ticker_preview.png
 - Ticker saves preview snapshots every 10th frame (~3 FPS at 30 FPS render rate)
 - If Pillow (PIL) is not installed, the preview endpoint will explain how to
   install it in your venv: `pip install pillow`.

Environment (optional)
----------------------
TICKER_RESTART_CMD - Full shell command to restart the ticker (wins over systemd)
TICKER_SERVICE     - systemd service name (default: led-ticker.service)
TICKER_USE_SUDO    - "1" to use sudo for systemctl if not running as root (default 1)
FLASK_SECRET       - Secret key; set this in production
FLASK_PORT         - Listening port (default 5080)
"""
import os
import io
import json
import time
import tempfile
import html
import shutil
import subprocess
from threading import Lock
from flask import (
    Flask, request, redirect, url_for, render_template_string,
    jsonify, flash, Response, send_from_directory
)
# Optional Pillow for PNG encoding of SHM frames
try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    Image = None
    _PIL_OK = False

APP_TITLE = "LED Ticker - Control Panel"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("TICKER_CONFIG", os.path.join(BASE_DIR, "config.json"))

# Restart configuration (optional environment variables)
RESTART_CMD_ENV = os.environ.get("TICKER_RESTART_CMD", "").strip()
SYSTEMD_SERVICE = os.environ.get("TICKER_SERVICE", "led-ticker.service").strip()
USE_SUDO_DEFAULT = os.environ.get("TICKER_USE_SUDO", "1") == "1"

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")  # change in prod
_write_lock = Lock()

@app.after_request
def add_header(response):
    if 'Content-Type' in response.headers:
        if 'charset' not in response.headers['Content-Type']:
            if 'text/html' in response.headers['Content-Type']:
                response.headers['Content-Type'] = 'text/html; charset=utf-8'
            elif 'application/json' in response.headers['Content-Type']:
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

# ---------------------------- helpers ---------------------------------
def load_cfg():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def atomic_save_cfg(cfg: dict):
    """Atomic write of config.json with a lock."""
    with _write_lock:
        dname = os.path.dirname(CONFIG_PATH) or "."
        fd, tmp = tempfile.mkstemp(prefix=".cfg.", dir=dname)
        os.close(fd)
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

def _parse_lines_pairs(txt: str):
    """
    Parse textarea content formatted as pairs:
    SYMBOL on one line, LABEL on the next line, repeated.
    Returns [["SYM", "LABEL"], ...]
    """
    out = []
    lines = (txt or "").splitlines()
    i = 0
    while i < len(lines):
        sym = (lines[i] or "").strip()
        lab = (lines[i + 1] if i + 1 < len(lines) else "").strip()
        if sym and lab:
            out.append([sym, lab])
        i += 2
    return out

def _pairs_to_text(pairs):
    return "\n".join([f"{s[0]}\n{s[1]}" for s in (pairs or [])])

def _parse_holdings(txt: str):
    """
    Parse "SYMBOL=SHARES" per-line to {"SYM":{"shares":float}}
    """
    out = {}
    for line in (txt or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        sym, sh = line.split("=", 1)
        sym = sym.strip()
        try:
            shares = float(sh.strip())
            if shares >= 0:
                out[sym] = {"shares": shares}
        except Exception:
            pass
    return out

def _holdings_to_text(hold):
    lines = []
    for k, v in (hold or {}).items():
        try:
            lines.append(f"{k}={v.get('shares',0)}")
        except Exception:
            pass
    return "\n".join(lines)

def _parse_dim_windows(txt):
    """
    Parse lines: HH:MM,HH:MM,PCT -> [{"start":"..","end":"..","pct":int},...]
    """
    wins = []
    for line in (txt or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        st, en, pct_s = parts
        try:
            pct = int(pct_s)
            if 1 <= pct <= 100 and st and en:
                wins.append({"start": st, "end": en, "pct": pct})
        except Exception:
            continue
    return wins

def _dim_windows_to_text(wins):
    lines = []
    for w in (wins or []):
        st = (w.get("start") or "").strip()
        en = (w.get("end") or "").strip()
        pc = int(w.get("pct") or 0)
        if st and en and pc > 0:
            lines.append(f"{st},{en},{pc}")
    return "\n".join(lines)

def _get_bool(form, name, default=False):
    v = form.get(name, None)
    if v in ("1", "true", "on", "True", "YES", "yes", "y"):
        return True
    if v in ("0", "false", "off", "False", "", None, "no", "NO", "n"):
        return False
    return bool(default)

def _get_num(form, name, default=0, cast=float):
    try:
        raw = form.get(name, None)
        if raw is None or raw == "":
            return default
        return cast(raw)
    except Exception:
        return default

def _get_csv_upper(form, name, default_list=None):
    raw = (form.get(name, "") or "").strip()
    if not raw and default_list is not None:
        return default_list
    return [s.strip().upper() for s in raw.split(",") if s.strip()]

# ---------------------------- restart helper ---------------------------
def _run_restart_command():
    """
    Try to restart the ticker:
    1) Use TICKER_RESTART_CMD if provided
    2) Else try systemctl restart <SERVICE> (optionally with sudo)
    Returns (ok, message)
    """
    if RESTART_CMD_ENV:
        try:
            proc = subprocess.run(
                RESTART_CMD_ENV,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return True, "Restarted via custom command."
            return False, f"Custom restart failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        except Exception as e:
            return False, f"Custom restart error: {e}"

    if not shutil.which("systemctl"):
        return False, "systemctl not found and no TICKER_RESTART_CMD provided."

    use_sudo = USE_SUDO_DEFAULT and (os.geteuid() != 0)
    cmd = ["systemctl", "restart", SYSTEMD_SERVICE]
    if use_sudo:
        if not shutil.which("sudo"):
            return False, "sudo not found; set TICKER_RESTART_CMD or run UI as root."
        cmd = ["sudo"] + cmd
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return True, f"systemd restart ok: {SYSTEMD_SERVICE}"
        err = proc.stderr.strip() or proc.stdout.strip()
        return False, f"systemd restart failed (rc={proc.returncode}): {err}"
    except Exception as e:
        return False, f"systemd restart error: {e}"

# ---------------------------- preview helpers --------------------------
def _resolve_panel_size_from_model(model_name: str):
    mn = (model_name or "").lower()
    if "96x32" in mn:
        return 96, 32
    if "192x16" in mn:
        return 192, 16
    if "96x16" in mn:
        return 96, 16
    return 96, 16

def _derive_panel_WH(cfg: dict):
    try:
        w = int(cfg.get("W", 0) or 0)
        h = int(cfg.get("H", 0) or 0)
    except Exception:
        w = h = 0
    if w > 0 and h > 0:
        return w, h
    m = cfg.get("MODEL_NAME", "Matrix96x16")
    return _resolve_panel_size_from_model(m)

def _read_preview_png_bytes(cfg: dict, scale: int = 6) -> tuple:
    """
    Return (ok, bytes_or_message, mime):
    - On success: (True, PNG_bytes, 'image/png')
    - On error:   (False, error_message, 'text/plain')
    
    Reads from /tmp/ticker_preview.png (written by ticker in RGBMATRIX mode).
    """
    if not _PIL_OK:
        return False, (
            "Pillow (PIL) is not installed. Install it in your venv to enable preview:\n"
            " pip install pillow\n"
        ), "text/plain"
    
    mode = (cfg.get("OUTPUT_MODE") or "HDMI").upper()
    
    # Both HDMI and RGBMATRIX modes now save preview files
    preview_path = "/tmp/ticker_preview.png"
    if not os.path.exists(preview_path):
        return False, f"Preview file not found: {preview_path}\nEnsure the ticker is running.", "text/plain"
    
    try:
        img = Image.open(preview_path)
        if scale > 1:
            new_size = (img.width * scale, img.height * scale)
            img = img.resize(new_size, Image.NEAREST)
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return True, buf.getvalue(), "image/png"
    except Exception as e:
        return False, f"Error reading preview: {e}", "text/plain"


# ---------------------------- templates --------------------------------
BASE_CSS = """
<style>
 :root{
  --bg:#0b0f16; --panel:#0f1724; --line:#1c2434; --text:#e6e6e6; --muted:#a7b1c2;
  --blue:#2563eb; --btn:#2563eb; --btn2:#334155; --link:#93c5fd; --ok:#16a34a; --bad:#dc2626;
 }
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}
 header{padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center}
 h1{font-size:18px;margin:0}
 main{padding:16px;max-width:1200px;margin:0 auto}
 section{margin:18px 0;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
 label{display:block;margin:8px 0 4px;color:var(--muted)}
 input,select,textarea{width:100%;padding:8px;background:var(--bg);border:1px solid #273046;color:var(--text);border-radius:6px}
 .row{display:flex;gap:12px;flex-wrap:wrap}
 .col{flex:1;min-width:260px}
 .grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
 .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
 .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
 button{background:var(--btn);color:white;border:none;padding:8px 12px;border-radius:6px;cursor:pointer}
 button.secondary{background:var(--btn2)}
 .btn{display:inline-block;background:var(--btn);color:white;padding:8px 12px;border-radius:6px;text-decoration:none}
 .btn.secondary{background:var(--btn2)}
 .pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#1e293b;border:1px solid #334155;font-size:12px}
 .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}
 a{color:var(--link);text-decoration:none}
 .toolbar{display:flex;gap:8px;align-items:center;margin-left:auto}
 .muted{color:var(--muted)}
 details{border:1px dashed var(--line);padding:8px;border-radius:8px}
 summary{cursor:pointer;color:#cbd5e1}
 .ok{color:var(--ok)} .bad{color:var(--bad)}
 .preview-wrap{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
 .preview-card{background:#0b1322;border:1px solid #233047;border-radius:10px;padding:8px}
 .preview-meta{font-size:12px;color:#9fb0c7;margin-top:6px}
 .hint{font-size:13px;color:#9fb0c7}
</style>
"""

HOME_HTML = """
<!doctype html>
<html lang="en"><head>
 <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <title>{{title}}</title>
""" + BASE_CSS + """
</head><body>
<header>
 <h1>{{title}}</h1>
 <span class="pill mono">config.json</span>
 <span class="pill mono">hot-reload</span>
 <div class="toolbar">
   <a class="btn" href="{{ url_for('preview_page') }}">Live Preview</a>
   <a class="btn secondary" href="{{ url_for('documentation') }}">Documentation</a>
   <a class="btn secondary" href="{{ url_for('raw_editor') }}">Raw JSON Editor</a>
   <button class="secondary" type="button" onclick="fetch('/restart',{method:'POST'}).then(()=>location.reload())" title="Restart the ticker process/service">Restart Ticker</button>
 </div>
</header>
<main>
{% with msgs = get_flashed_messages() %}
 {% if msgs %}
 <section>
 {% for m in msgs %}
 <div>{{m}}</div>
 {% endfor %}
 </section>
 {% endif %}
{% endwith %}
<section>
 <h2>Quick Preview</h2>
 <div class="preview-wrap">
   <div class="preview-card">
     <img id="qprev" src="{{ url_for('preview_png') }}?scale={{scale}}&t={{nowts}}" alt="preview" style="image-rendering:pixelated;max-width:100%;height:auto">
     <div class="preview-meta mono">{{wh}} {{mode}} scale={{scale}} {{preview_status}}</div>
   </div>
   <div class="hint">If the image doesn't move: ensure the ticker is running, OUTPUT_MODE is <b>RGBMATRIX</b>, and Pillow is installed in the UI's venv.<br>
   For a larger view and controls, open <a href="{{ url_for('preview_page') }}">Live Preview</a>.</div>
 </div>
</section>
<form method="post" action="{{ url_for('save') }}">
<!-- Status & Quick Actions -->
<div style="background:#1a1f2e;padding:16px;margin-bottom:20px;border-radius:8px;border:1px solid #2c3650;">
 <div style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;">
  <div>
   <div style="font-size:11px;color:#7d8ba8;margin-bottom:4px;">SERVICE STATUS</div>
   <div id="service-status" style="font-weight:600;"><span style="color:#888;">Checking...</span></div>
  </div>
  <div style="flex:1;">
   <div style="font-size:11px;color:#7d8ba8;margin-bottom:4px;">QUICK ACTIONS</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
    <button type="submit" class="btn" style="padding:6px 12px;font-size:13px;">Save Config</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/restart',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),2000);})"> Restart</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/stop-service',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Stop</button>
   </div>
   <div style="font-size:11px;color:#7d8ba8;margin-bottom:4px;margin-top:12px;">OVERRIDES</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/show-clock',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Clock 5m</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/bright-mode',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Full Bright 30m</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/scoreboard-mode',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Force Scoreboard</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/maint-mode',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Maintenance</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/clear-override',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Clear Override</button>
   </div>
   <div style="margin-top:8px;display:flex;gap:8px;align-items:center;">
    <input type="text" id="msg-input" placeholder="Custom message..." style="flex:1;padding:6px 10px;font-size:13px;max-width:300px;">
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="var msg=document.getElementById('msg-input').value.trim();if(msg){var fd=new FormData();fd.append('message',msg);fetch('/action/show-message',{method:'POST',body:fd}).then(()=>{document.getElementById('msg-input').value='';setTimeout(()=>location.reload(),1000);});}else{alert('Enter a message first');}"> Show Message 5m</button>
   </div>
   <div style="font-size:11px;color:#7d8ba8;margin-bottom:4px;margin-top:12px;">DIMMING</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/dim-low',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Dim 30%</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/dim-medium',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Dim 60%</button>
    <button type="button" class="btn secondary" style="padding:6px 12px;font-size:13px;" onclick="fetch('/action/dim-high',{method:'POST'}).then(()=>{setTimeout(()=>location.reload(),1000);})"> Dim Off</button>
   </div>
  </div>
 </div>
</div>
<!-- Worker Status Monitoring -->
<div style="background:#1a1f2e;padding:16px;margin-bottom:20px;border-radius:8px;border:1px solid #2c3650;">
 <div style="font-size:11px;color:#7d8ba8;margin-bottom:8px;">WORKER STATUS</div>
 <div id="worker-status" style="font-size:13px;">
  <span style="color:#888;">Loading...</span>
 </div>
</div>
<script>
function updateStatus(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    document.getElementById('service-status').innerHTML = d.service_running ?
      '<span style="color:#16a34a;">OK Running</span>' : '<span style="color:#dc2626;">WARN  Stopped</span>';
  }).catch(()=>{});
}
function updateWorkers(){
  fetch('/api/workers').then(r=>r.json()).then(d=>{
    const workers = d.workers || {};
    if (!d.file_exists) {
      document.getElementById('worker-status').innerHTML = `
      <div style="background:#0f1419;padding:16px;border-radius:6px;border:1px solid #fbbf24;">
        <div style="color:#fbbf24;font-weight:600;margin-bottom:8px;">WARN  Worker Status Not Available</div>
        <div style="font-size:13px;color:#9ca3af;line-height:1.6;">
          <p style="margin:0 0 8px 0;">The worker status file <code style="color:#e5e7eb;background:#1a1f2e;padding:2px 6px;border-radius:3px;">ticker_status.json</code> doesn't exist yet.</p>
          <p style="margin:0;"><strong style="color:#e5e7eb;">To enable monitoring:</strong></p>
          <ol style="margin:8px 0 0 20px;padding:0;">
            <li>Deploy the updated <code style="color:#e5e7eb;background:#1a1f2e;padding:2px 6px;border-radius:3px;">ticker.py</code> file</li>
            <li>Restart the LED ticker service</li>
            <li>Wait 30-60 seconds for workers to run</li>
            <li>This page will auto-refresh and show live data</li>
          </ol>
        </div>
      </div>`;
      return;
    }
    if (Object.keys(workers).length === 0) {
      document.getElementById('worker-status').innerHTML = '<span style="color:#888;">No worker data available</span>';
      return;
    }
    let html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;">';
    // Market Worker
    if (workers.market) {
      const m = workers.market;
      const isStale = (m.seconds_ago||0) > 600;
      const hasError = (m.status === 'error' || m.status === 'partial');
      const statusColor = hasError ? '#dc2626' : (m.status === 'ok' ? (isStale ? '#fbbf24' : '#16a34a') : '#fbbf24');
      let statusText = (m.status ? m.status.toUpperCase() : 'UNKNOWN');
      if (m.symbols_failed && m.symbols_failed > 0) { statusText += ` (${m.symbols_failed} failed)`; }
      let errorHtml = '';
      if (m.error_message) { errorHtml = `<div style="color:#dc2626;margin-top:4px;">WARN  ${m.error_message}</div>`; }
      html += `<div style="background:#0f1419;padding:12px;border-radius:6px;border:1px solid #2c3650;">
        <div style="font-weight:600;margin-bottom:6px;color:${statusColor};">Market Worker</div>
        <div style="font-size:12px;color:#9ca3af;">
          <div>Status: <span style="color:${statusColor};">${statusText}</span></div>
          <div>Market State: <span style="color:#e5e7eb;">${m.market_state||'UNKNOWN'}</span></div>
          <div>Symbols: <span style="color:#e5e7eb;">${m.symbols_count||0}</span></div>
          <div>Last Update: <span style="color:#e5e7eb;">${m.last_update||'Never'}</span></div>
          <div>Fetch Time: <span style="color:#e5e7eb;">${m.fetch_duration_sec||0}s</span></div>
          <div style="color:${isStale ? '#fbbf24' : '#9ca3af'};">Updated ${m.seconds_ago||0}s ago</div>
          ${errorHtml}
        </div>
      </div>`;
    }
    // Scoreboard Worker
    if (workers.scoreboard) {
      const s = workers.scoreboard;
      const isStale = (s.seconds_ago||0) > 600;
      const hasError = (s.status === 'error');
      const statusColor = hasError ? '#dc2626' : (s.status === 'live' ? '#16a34a' : (s.status === 'ok' ? '#3b82f6' : '#9ca3af'));
      let leagueInfo = '';
      if (s.leagues_with_games && s.leagues_with_games.length > 0) {
        const leagues = s.leagues_with_games.map(l => {
          const parts = String(l).split(':');
          return `${parts[0]} (${parts[1]||0})`;
        }).join(', ');
        leagueInfo = `<div>Today: <span style="color:#e5e7eb;">${leagues}</span></div>`;
      } else {
        leagueInfo = `<div>Today: <span style=\"color:#e5e7eb;\">No games</span></div>`;
      }
      let errorHtml = '';
      if (s.error_message) { errorHtml = `<div style="color:#dc2626;margin-top:4px;">WARN  ${s.error_message}</div>`; }
      html += `<div style="background:#0f1419;padding:12px;border-radius:6px;border:1px solid #2c3650;">
        <div style="font-weight:600;margin-bottom:6px;color:${statusColor};">Scoreboard Worker</div>
        <div style="font-size:12px;color:#9ca3af;">
          <div>Status: <span style="color:${statusColor};">${(s.status||'UNKNOWN').toUpperCase()}</span></div>
          ${leagueInfo}
          <div>Total Games: <span style="color:#e5e7eb;">${s.total_games||0}</span></div>
          <div>Live: <span style=\"color:#16a34a;\">${s.live_games||0}</span>  Scheduled: <span style=\"color:#3b82f6;\">${s.pregame_games||0}</span></div>
          <div>Test Mode: <span style="color:#e5e7eb;">${s.test_mode ? 'Yes' : 'No'}</span></div>
          <div>Last Update: <span style="color:#e5e7eb;">${s.last_update||'Never'}</span></div>
          <div style="color:${isStale ? '#fbbf24' : '#9ca3af'};">Updated ${s.seconds_ago||0}s ago</div>
          ${errorHtml}
        </div>
      </div>`;
    }
    // Weather Worker
    if (workers.weather) {
      const w = workers.weather;
      const isStale = (w.seconds_ago||0) > 600;
      const hasError = (w.status === 'error');
      const statusColor = hasError ? '#dc2626' : (w.status === 'active' ? '#dc2626' : '#16a34a');
      let errorHtml = '';
      if (w.error_message) { errorHtml = `<div style="color:#dc2626;margin-top:4px;">WARN  ${w.error_message}</div>`; }
      html += `<div style="background:#0f1419;padding:12px;border-radius:6px;border:1px solid #2c3650;">
        <div style="font-weight:600;margin-bottom:6px;color:${statusColor};">Weather Worker</div>
        <div style="font-size:12px;color:#9ca3af;">
          <div>Status: <span style="color:${statusColor};">${(w.status||'UNKNOWN').toUpperCase()}</span></div>
          <div>Severity: <span style="color:#e5e7eb;">${w.severity||'none'}</span></div>
          <div>Last Update: <span style="color:#e5e7eb;">${w.last_update||'Never'}</span></div>
          <div>Fetch Time: <span style="color:#e5e7eb;">${w.fetch_duration_sec||0}s</span></div>
          <div style="color:${isStale ? '#fbbf24' : '#9ca3af'};">Updated ${w.seconds_ago||0}s ago</div>
          ${errorHtml}
        </div>
      </div>`;
    }
    html += '</div>';
    document.getElementById('worker-status').innerHTML = html;
  }).catch(()=>{
    document.getElementById('worker-status').innerHTML = '<span style="color:#dc2626;">Error loading worker status</span>';
  });
}
updateStatus();
updateWorkers();
setInterval(updateStatus,5000);
setInterval(updateWorkers,3000);
</script>

<section>
 <h2>Display & Layout</h2>
 <div class="grid4">
  <div>
   <label>Output Mode</label>
   <select name="OUTPUT_MODE">
    {% for opt in ["RGBMATRIX","HDMI"] %}
    <option value="{{opt}}" {% if cfg.OUTPUT_MODE==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
  <div><label>Layout</label>
   <select name="LAYOUT">
    {% for opt in ["","single","dual"] %}
    <option value="{{opt}}" {% if cfg.LAYOUT==opt %}selected{% endif %}>{{opt if opt else "auto"}}</option>
    {% endfor %}
   </select>
  </div>
  <div><label>Timezone (IANA)</label><input name="TICKER_TZ" value="{{cfg.TICKER_TZ or ''}}"></div>
  <div><label>Microfont (dual-row only)</label>
   <select name="MICROFONT_ENABLED">
    <option value="1" {% if cfg.MICROFONT_ENABLED %}selected{% endif %}>on</option>
    <option value="0" {% if not cfg.MICROFONT_ENABLED %}selected{% endif %}>off</option>
   </select>
  </div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>FPS</label><input name="FPS" type="number" min="1" max="120" value="{{cfg.FPS or 30}}"></div>
  <div><label>Top PPS</label><input name="PPS_TOP" type="number" step="0.5" value="{{cfg.PPS_TOP or 16.0}}"></div>
  <div><label>Bottom PPS</label><input name="PPS_BOT" type="number" step="0.5" value="{{cfg.PPS_BOT or 20.0}}"></div>
  <div><label>Single PPS</label><input name="PPS_SINGLE" type="number" step="0.5" value="{{cfg.PPS_SINGLE or 20.0}}"></div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>Model Name</label><input name="MODEL_NAME" value="{{cfg.MODEL_NAME or 'Matrix96x16'}}"></div>
  <div><label>Width (W)</label><input name="W" type="number" value="{{cfg.W or 0}}"></div>
  <div><label>Height (H)</label><input name="H" type="number" value="{{cfg.H or 0}}"></div>
  <div><label>Scale (HDMI)</label><input name="TICKER_SCALE" type="number" value="{{cfg.TICKER_SCALE or 8}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <label><input type="checkbox" name="FORCE_KMS" value="1" {% if cfg.FORCE_KMS %}checked{% endif %}> Force KMS/DRM</label>
  <label><input type="checkbox" name="USE_SDL_SCALED" value="1" {% if cfg.USE_SDL_SCALED %}checked{% endif %}> Use SDL Scaled</label>
  <label><input type="checkbox" name="USE_BUSY_LOOP" value="1" {% if cfg.USE_BUSY_LOOP %}checked{% endif %}> Busy Loop Timing</label>
 </div>
 <h3 style="margin-top:16px;font-size:15px;color:#94a3b8;">RGB Matrix Hardware (RGBMATRIX mode only)</h3>
 <p class="muted">These settings configure the rpi-rgb-led-matrix library for direct HUB75 LED panel control.</p>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label>Hardware Mapping</label>
   <select name="RGB_HARDWARE_MAPPING" title="GPIO pin layout for your HAT/adapter">
    <option value="adafruit-hat" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'adafruit-hat' %}selected{% endif %}>adafruit-hat</option>
    <option value="adafruit-hat-pwm" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'adafruit-hat-pwm' %}selected{% endif %}>adafruit-hat-pwm</option>
    <option value="regular" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'regular' %}selected{% endif %}>regular</option>
    <option value="regular-pi1" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'regular-pi1' %}selected{% endif %}>regular-pi1</option>
    <option value="classic" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'classic' %}selected{% endif %}>classic</option>
    <option value="classic-pi1" {% if (cfg.RGB_HARDWARE_MAPPING or 'adafruit-hat') == 'classic-pi1' %}selected{% endif %}>classic-pi1</option>
   </select>
  </div>
  <div>
   <label>Brightness (0-100)</label>
   <input name="RGB_BRIGHTNESS" type="number" min="0" max="100" value="{{cfg.RGB_BRIGHTNESS or 100}}" title="LED brightness percentage">
  </div>
  <div>
   <label>GPIO Slowdown (0-4)</label>
   <input name="RGB_GPIO_SLOWDOWN" type="number" min="0" max="4" value="{{cfg.RGB_GPIO_SLOWDOWN or 4}}" title="Stability setting, higher for faster Pi models">
  </div>
  <div>
   <label>PWM Bits (1-11)</label>
   <input name="RGB_PWM_BITS" type="number" min="1" max="11" value="{{cfg.RGB_PWM_BITS or 11}}" title="Color depth, higher = more colors but slower refresh">
  </div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label>PWM LSB Nanoseconds (50-3000)</label>
   <input name="RGB_PWM_LSB_NANOSECONDS" type="number" min="50" max="3000" step="10" value="{{cfg.RGB_PWM_LSB_NANOSECONDS or 130}}" title="PWM timing, affects brightness/flicker tradeoff">
  </div>
 </div>
 <h3 style="margin-top:16px;font-size:15px;color:#94a3b8;">Advanced Panel Configuration</h3>
 <p class="muted">For chained panels, special panel types, and advanced configurations. Leave at defaults for single standard panels.</p>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label>Chain Length</label>
   <input name="RGB_CHAIN_LENGTH" type="number" min="1" max="32" value="{{cfg.RGB_CHAIN_LENGTH or 1}}" title="Number of panels chained horizontally">
  </div>
  <div>
   <label>Parallel Chains</label>
   <input name="RGB_PARALLEL" type="number" min="1" max="8" value="{{cfg.RGB_PARALLEL or 1}}" title="Number of parallel chains (increases height)">
  </div>
  <div>
   <label>Scan Mode</label>
   <select name="RGB_SCAN_MODE" title="Scan pattern for the panel">
    <option value="0" {% if (cfg.RGB_SCAN_MODE or 0) == 0 %}selected{% endif %}>0 - Progressive</option>
    <option value="1" {% if (cfg.RGB_SCAN_MODE or 0) == 1 %}selected{% endif %}>1 - Interlaced</option>
   </select>
  </div>
  <div>
   <label>Row Address Type (0-4)</label>
   <input name="RGB_ROW_ADDRESS_TYPE" type="number" min="0" max="4" value="{{cfg.RGB_ROW_ADDRESS_TYPE or 0}}" title="0=direct, 1=AB, 2=direct-ABCDline, 3=ABC-shift, 4=ABC-ZigZag">
  </div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label>Multiplexing (0-18)</label>
   <input name="RGB_MULTIPLEXING" type="number" min="0" max="18" value="{{cfg.RGB_MULTIPLEXING or 0}}" title="Panel-specific multiplexing type, usually 0">
  </div>
  <div>
   <label>LED RGB Sequence</label>
   <select name="RGB_LED_RGB_SEQUENCE" title="Physical LED color order">
    {% for seq in ['RGB','RBG','GRB','GBR','BRG','BGR'] %}
    <option value="{{seq}}" {% if (cfg.RGB_LED_RGB_SEQUENCE or 'RGB') == seq %}selected{% endif %}>{{seq}}</option>
    {% endfor %}
   </select>
  </div>
  <div>
   <label>Pixel Mapper</label>
   <input name="RGB_PIXEL_MAPPER" value="{{cfg.RGB_PIXEL_MAPPER or ''}}" placeholder="e.g. Rotate:90" title="Optional: Rotate:90, U-mapper, etc.">
  </div>
  <div>
   <label>Panel Type</label>
   <input name="RGB_PANEL_TYPE" value="{{cfg.RGB_PANEL_TYPE or ''}}" placeholder="Usually empty" title="Panel type hint for special panels">
  </div>
 </div>
</section>

<section>
 <h2>Time Preroll (Top of Hour)</h2>
 <p class="muted">Show a time display at the top of each hour for a configurable duration.</p>
 <div class="grid4" style="margin-top:8px">
  <label style="grid-column: span 4;"><input type="checkbox" name="TIME_PREROLL_ENABLED" value="1" {% if cfg.TIME_PREROLL_ENABLED %}checked{% endif %}> Enable Time Preroll</label>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label>Duration (seconds)</label>
   <input name="TIME_PREROLL_SEC" type="number" min="1" max="120" value="{{cfg.TIME_PREROLL_SEC or 15}}" title="How long to show the preroll (1-120 seconds)">
  </div>
  <div>
   <label>Style</label>
   <select name="PREROLL_STYLE" title="Display style for preroll">
    <option value="bigtime" {% if (cfg.PREROLL_STYLE or 'bigtime').lower() == 'bigtime' %}selected{% endif %}>Big Time (Static)</option>
    <option value="marquee" {% if (cfg.PREROLL_STYLE or 'bigtime').lower() == 'marquee' %}selected{% endif %}>Marquee (Scrolling)</option>
    <option value="market_announce" {% if (cfg.PREROLL_STYLE or 'bigtime').lower() == 'market_announce' %}selected{% endif %}>Market Announcement</option>
   </select>
  </div>
  <div>
   <label>Color</label>
   <select name="PREROLL_COLOR" title="Color for time display">
    <option value="white" {% if (cfg.PREROLL_COLOR or 'yellow') == 'white' %}selected{% endif %}>White</option>
    <option value="yellow" {% if (cfg.PREROLL_COLOR or 'yellow') == 'yellow' %}selected{% endif %}>Yellow</option>
    <option value="green" {% if (cfg.PREROLL_COLOR or 'yellow') == 'green' %}selected{% endif %}>Green</option>
    <option value="red" {% if (cfg.PREROLL_COLOR or 'yellow') == 'red' %}selected{% endif %}>Red</option>
    <option value="blue" {% if (cfg.PREROLL_COLOR or 'yellow') == 'blue' %}selected{% endif %}>Blue</option>
    <option value="magenta" {% if (cfg.PREROLL_COLOR or 'yellow') == 'magenta' %}selected{% endif %}>Magenta</option>
    <option value="cyan" {% if (cfg.PREROLL_COLOR or 'yellow') == 'cyan' %}selected{% endif %}>Cyan</option>
   </select>
  </div>
  <div>
   <label>Scroll Speed (PPS)</label>
   <input name="PREROLL_PPS" type="number" step="0.5" min="10" max="100" value="{{cfg.PREROLL_PPS or 40.0}}" title="Pixels per second for marquee style">
  </div>
 </div>
</section>

<section>
 <h2>Tickers (Top / Bottom)</h2>
 <p class="muted">Format: <span class="mono">SYMBOL\nLABEL</span> one per line.</p>
 <div class="row">
  <div class="col">
   <label>Top Row</label>
   <textarea name="TICKERS_TOP" rows="7">{{top_pairs}}</textarea>
  </div>
  <div class="col">
   <label>Bottom Row</label>
   <textarea name="TICKERS_BOT" rows="7">{{bot_pairs}}</textarea>
  </div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Market Refresh (sec)</label><input name="REFRESH_SEC" type="number" value="{{cfg.REFRESH_SEC or 240}}"></div>
  <div><label>Freshness Threshold (sec)</label><input name="FRESH_SEC" type="number" value="{{cfg.FRESH_SEC or 300}}"></div>
 </div>
</section>

<section>
 <h2>Holdings</h2>
 <p class="muted">Format: <span class="mono">SYMBOL=SHARES</span> one per line (fractions OK).</p>
 <label><input type="checkbox" name="HOLDINGS_ENABLED" value="1" {% if cfg.HOLDINGS_ENABLED %}checked{% endif %}> Enable holdings view</label>
 <textarea name="HOLDINGS" rows="8">{{holdings_text}}</textarea>
</section>

<section>
 <h2>Message & Weather</h2>
 <div class="grid3">
  <div><label>Inject Message</label><input name="INJECT_MESSAGE" value="{{cfg.INJECT_MESSAGE or ''}}"></div>
  <div><label>Message Every N Scrolls (0=off)</label><input name="MESSAGE_EVERY" type="number" min="0" value="{{cfg.MESSAGE_EVERY or 0}}"></div>
  <div><label>Message Row</label>
   <select name="MESSAGE_ROW">
    {% for opt in ["auto","single","top","bottom","both","off"] %}
    <option value="{{opt}}" {% if cfg.MESSAGE_ROW==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Message Color</label>
   <select name="MESSAGE_COLOR">
    {% for opt in ["yellow","white","red","green","cyan","blue","magenta","orange","grey","black"] %}
    <option value="{{opt}}" {% if cfg.MESSAGE_COLOR==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
  <label><input type="checkbox" name="MESSAGE_TEST_FORCE" value="1" {% if cfg.MESSAGE_TEST_FORCE %}checked{% endif %}> Force message every scroll (test)</label>
 </div>
 <hr style="border:none;border-top:1px solid #1c2434;margin:14px 0">
 <div class="grid3" style="margin-top:8px">
  <div><label>Weather RSS URL</label><input name="WEATHER_RSS_URL" value="{{cfg.WEATHER_RSS_URL or ''}}"></div>
  <div><label>Weather Announce Every (sec)</label><input name="WEATHER_ANNOUNCE_SEC" type="number" value="{{cfg.WEATHER_ANNOUNCE_SEC or 600}}"></div>
  <div><label>Weather Refresh (sec)</label><input name="WEATHER_REFRESH_SEC" type="number" value="{{cfg.WEATHER_REFRESH_SEC or 300}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <label><input type="checkbox" name="WEATHER_INCLUDE_WATCH" value="1" {% if cfg.WEATHER_INCLUDE_WATCH %}checked{% endif %}> Include "Watch"</label>
  <label><input type="checkbox" name="WEATHER_FORCE_ACTIVE" value="1" {% if cfg.WEATHER_FORCE_ACTIVE %}checked{% endif %}> Force Active</label>
  <div><label>Force Text</label><input name="WEATHER_FORCE_TEXT" value="{{cfg.WEATHER_FORCE_TEXT or ''}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Weather Timeout (s)</label><input name="WEATHER_TIMEOUT" type="number" step="0.5" value="{{cfg.WEATHER_TIMEOUT or 5.0}}"></div>
  <div><label>Weather Test Delay (s) (0=off)</label><input name="WEATHER_TEST_DELAY" type="number" value="{{cfg.WEATHER_TEST_DELAY or 0}}"></div>
  <div><label>Weather Sticky Duration (s)</label><input name="WEATHER_STICKY_SEC" type="number" value="{{cfg.WEATHER_STICKY_SEC or 20}}" title="How long banner stays visible"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Weather Test Sticky Total (s)</label><input name="WEATHER_TEST_STICKY_TOTAL" type="number" value="{{cfg.WEATHER_TEST_STICKY_TOTAL or 60}}" title="Test mode banner duration"></div>
  <div><label>Weather Repeat Every (s)</label><input name="WEATHER_REPEAT_SEC" type="number" value="{{cfg.WEATHER_REPEAT_SEC or 600}}" title="Re-announce interval for active alerts"></div>
 </div>
 <hr style="border:none;border-top:1px solid #1c2434;margin:14px 0">
 <h3 style="margin-top:16px;font-size:15px;color:#94a3b8;"> Weather Alert Display by Severity</h3>
 <p class="muted">Control how weather alerts appear based on severity level.</p>
 <div class="grid4" style="margin-top:8px">
  <div>
   <label> Warnings - Every N Scrolls</label>
   <input name="WEATHER_WARNING_EVERY_N_SCROLLS" type="number" min="1" value="{{cfg.WEATHER_WARNING_EVERY_N_SCROLLS or 5}}" title="Show red warnings every N scrolls">
  </div>
  <div>
   <label> Warning Color</label>
   <select name="WEATHER_WARNING_COLOR">
    {% for color in ["red","white","yellow","cyan","magenta","orange"] %}
    <option value="{{color}}" {% if cfg.WEATHER_WARNING_COLOR==color %}selected{% endif %}>{{color}}</option>
    {% endfor %}
   </select>
  </div>
  <div>
   <label> Advisories - Every N Scrolls</label>
   <input name="WEATHER_ADVISORY_EVERY_N_SCROLLS" type="number" min="1" value="{{cfg.WEATHER_ADVISORY_EVERY_N_SCROLLS or 10}}" title="Show yellow advisories every N scrolls">
  </div>
  <div>
   <label> Advisory Color</label>
   <select name="WEATHER_ADVISORY_COLOR">
    {% for color in ["yellow","cyan","white","magenta","orange"] %}
    <option value="{{color}}" {% if cfg.WEATHER_ADVISORY_COLOR==color %}selected{% endif %}>{{color}}</option>
    {% endfor %}
   </select>
  </div>
 </div>
 <p class="muted" style="margin-top:8px;">
  <strong>Warnings</strong> (red): Full 16px display, more frequent<br>
  <strong>Advisories/Watches</strong> (yellow): Top line only, less frequent
 </p>
</section>

<section>
 <h2>Scheduler & Dimming</h2>
 <div class="grid4">
  <label><input type="checkbox" name="SCHEDULE_ENABLED" value="1" {% if cfg.SCHEDULE_ENABLED %}checked{% endif %}> Enable Off Window</label>
  <div><label>Off Start (HH:MM)</label><input name="SCHEDULE_OFF_START" value="{{cfg.SCHEDULE_OFF_START or '23:00'}}"></div>
  <div><label>Off End (HH:MM)</label><input name="SCHEDULE_OFF_END" value="{{cfg.SCHEDULE_OFF_END or '07:00'}}"></div>
  <div><label>Blank FPS when Off</label><input name="SCHEDULE_BLANK_FPS" type="number" min="1" max="60" value="{{cfg.SCHEDULE_BLANK_FPS or 5}}"></div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <label><input type="checkbox" name="SCHEDULE_TEST_FORCE_OFF" value="1" {% if cfg.SCHEDULE_TEST_FORCE_OFF %}checked{% endif %}> Force Off (test)</label>
 </div>
 <hr style="border:none;border-top:1px solid #1c2434;margin:14px 0">
 <div style="margin-top:8px">
  <label>Dim Schedule Windows</label>
  <p class="muted">One per line: <span class="mono">HH:MM,HH:MM,PCT</span> &mdash; brightness % during that time window. Active when populated.</p>
  <textarea name="DIM_WINDOWS" rows="4" class="mono">{{dim_windows_text}}</textarea>
 </div>
 <div class="grid3" style="margin-top:8px">
  <label><input type="checkbox" name="DIM_TEST_ENABLED" value="1" {% if cfg.DIM_TEST_ENABLED %}checked{% endif %}> Test: force brightness</label>
  <div><label>Dim Test %</label><input name="DIM_TEST_PCT" type="number" min="1" max="100" value="{{cfg.DIM_TEST_PCT or 0}}"></div>
 </div>
</section>

<section>
 <h2>Night Mode (Auto-Dim + Slow Scroll)</h2>
 <p class="muted">Automatically dim display and slow scroll speed during night hours. Overrides other dimming settings when active.</p>
 <div class="grid4">
  <label><input type="checkbox" name="NIGHT_MODE_ENABLED" value="1" {% if cfg.NIGHT_MODE_ENABLED %}checked{% endif %}> Enable Night Mode</label>
  <div><label>Night Start (HH:MM)</label><input name="NIGHT_MODE_START" value="{{cfg.NIGHT_MODE_START or '22:00'}}" placeholder="22:00"></div>
  <div><label>Night End (HH:MM)</label><input name="NIGHT_MODE_END" value="{{cfg.NIGHT_MODE_END or '07:00'}}" placeholder="07:00"></div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>Night Brightness %</label><input name="NIGHT_MODE_DIM_PCT" type="number" min="1" max="100" value="{{cfg.NIGHT_MODE_DIM_PCT or 30}}"></div>
  <div><label>Night Scroll Speed %</label><input name="NIGHT_MODE_SPEED_PCT" type="number" min="1" max="100" value="{{cfg.NIGHT_MODE_SPEED_PCT or 50}}"></div>
 </div>
 <p class="muted" style="margin-top:8px;">
  Example: 22:00-07:00 at 30% brightness and 50% scroll speed (half speed = slower, easier to read)
 </p>
</section>

<section>
 <h2>Fonts</h2>
 <div class="grid3">
  <div><label>Base Font Family</label><input name="FONT_FAMILY_BASE" value="{{cfg.FONT_FAMILY_BASE or 'DejaVuSansMono'}}"></div>
  <div><label>Scoreboard Font Family</label><input name="FONT_FAMILY_SCOREBOARD" value="{{cfg.FONT_FAMILY_SCOREBOARD or cfg.FONT_FAMILY_BASE or 'DejaVuSansMono'}}"></div>
  <div><label>Debug Font Family</label><input name="FONT_FAMILY_DEBUG" value="{{cfg.FONT_FAMILY_DEBUG or cfg.FONT_FAMILY_BASE or 'DejaVuSansMono'}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Row Font Size (px or "auto")</label><input name="FONT_SIZE_ROW" value="{{cfg.FONT_SIZE_ROW or 'auto'}}"></div>
  <div><label>Scoreboard Font Size (px or "auto")</label><input name="FONT_SIZE_SB" value="{{cfg.FONT_SIZE_SB or 'auto'}}"></div>
  <div><label>Debug Font Size (px or "auto")</label><input name="FONT_SIZE_DEBUG" value="{{cfg.FONT_SIZE_DEBUG or 'auto'}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <label><input type="checkbox" name="FONT_BOLD_BASE" value="1" {% if cfg.FONT_BOLD_BASE %}checked{% endif %}> Base Bold</label>
  <label><input type="checkbox" name="FONT_BOLD_SB" value="1" {% if cfg.FONT_BOLD_SB %}checked{% endif %}> Scoreboard Bold</label>
  <label><input type="checkbox" name="FONT_BOLD_DEBUG" value="1" {% if cfg.FONT_BOLD_DEBUG %}checked{% endif %}> Debug Bold</label>
 </div>
 <hr style="border:none;border-top:1px solid #1c2434;margin:14px 0">
 <div class="grid3">
  <div><label>Preroll Font Family</label><input name="PREROLL_FONT_FAMILY" value="{{cfg.PREROLL_FONT_FAMILY or cfg.FONT_FAMILY_BASE or 'DejaVuSansMono'}}"></div>
  <div><label>Preroll Font px (0=auto)</label><input name="PREROLL_FONT_PX" type="number" min="0" value="{{cfg.PREROLL_FONT_PX or 0}}"></div>
  <label><input type="checkbox" name="PREROLL_FONT_BOLD" value="1" {% if cfg.PREROLL_FONT_BOLD %}checked{% endif %}> Preroll Bold</label>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Maintenance Font Family</label><input name="MAINT_FONT_FAMILY" value="{{cfg.MAINT_FONT_FAMILY or cfg.FONT_FAMILY_BASE or 'DejaVuSansMono'}}"></div>
  <div><label>Maintenance Font px (0=auto)</label><input name="MAINT_FONT_PX" type="number" min="0" value="{{cfg.MAINT_FONT_PX or 0}}"></div>
  <label><input type="checkbox" name="MAINT_FONT_BOLD" value="1" {% if cfg.MAINT_FONT_BOLD %}checked{% endif %}> Maintenance Bold</label>
 </div>
</section>

<section>
 <h2>Scoreboard</h2>
 <div class="grid4">
  <label><input type="checkbox" name="SCOREBOARD_ENABLED" value="1" {% if cfg.SCOREBOARD_ENABLED %}checked{% endif %}> Enable</label>
  <div><label>Leagues (comma)</label><input name="SCOREBOARD_LEAGUES" value="{{ (cfg.SCOREBOARD_LEAGUES or [])|join(',') }}"></div>
  <div><label>NHL Teams (comma)</label><input name="SCOREBOARD_NHL_TEAMS" value="{{ (cfg.SCOREBOARD_NHL_TEAMS or [])|join(',') }}"></div>
  <div><label>NFL Teams (comma)</label><input name="SCOREBOARD_NFL_TEAMS" value="{{ (cfg.SCOREBOARD_NFL_TEAMS or [])|join(',') }}"></div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>Poll window min before game</label><input name="SCOREBOARD_POLL_WINDOW_MIN" type="number" value="{{cfg.SCOREBOARD_POLL_WINDOW_MIN or 120}}"></div>
  <div><label>Poll cadence (sec)</label><input name="SCOREBOARD_POLL_CADENCE" type="number" value="{{cfg.SCOREBOARD_POLL_CADENCE or 60}}"></div>
  <div><label>Live refresh (sec)</label><input name="SCOREBOARD_LIVE_REFRESH" type="number" value="{{cfg.SCOREBOARD_LIVE_REFRESH or 45}}"></div>
  <div><label>Max games</label><input name="SCOREBOARD_MAX_GAMES" type="number" min="1" value="{{cfg.SCOREBOARD_MAX_GAMES or 2}}"></div>
 </div>
 <div class="grid3" style="margin-top:8px">
  <div><label>Pregame Window (min)</label><input name="SCOREBOARD_PREGAME_WINDOW_MIN" type="number" value="{{cfg.SCOREBOARD_PREGAME_WINDOW_MIN or 30}}" title="Show scoreboard N minutes before game starts"></div>
  <div><label>Postgame Delay (min)</label><input name="SCOREBOARD_POSTGAME_DELAY_MIN" type="number" value="{{cfg.SCOREBOARD_POSTGAME_DELAY_MIN or 5}}" title="Keep showing scoreboard N minutes after FINAL"></div>
  <label><input type="checkbox" name="SCOREBOARD_SHOW_COUNTDOWN" value="1" {% if cfg.SCOREBOARD_SHOW_COUNTDOWN %}checked{% endif %} title="Show 'GAME STARTS IN Xm' for pregame"> Show Countdown</label>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>Precedence</label>
   <select name="SCOREBOARD_PRECEDENCE">
    {% for opt in ["normal","force"] %}
    <option value="{{opt}}" {% if cfg.SCOREBOARD_PRECEDENCE==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
  <div><label>Layout</label>
   <select name="SCOREBOARD_LAYOUT">
    {% for opt in ["auto","left","center"] %}
    <option value="{{opt}}" {% if cfg.SCOREBOARD_LAYOUT==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
  <label><input type="checkbox" name="SCOREBOARD_UPPERCASE" value="1" {% if cfg.SCOREBOARD_UPPERCASE %}checked{% endif %}> Uppercase</label>
  <label><input type="checkbox" name="SCOREBOARD_HOME_FIRST" value="1" {% if cfg.SCOREBOARD_HOME_FIRST %}checked{% endif %}> Home first</label>
 </div>
 <div class="grid4" style="margin-top:8px">
  <label><input type="checkbox" name="SCOREBOARD_SHOW_CLOCK" value="1" {% if cfg.SCOREBOARD_SHOW_CLOCK %}checked{% endif %}> Show clock</label>
  <label><input type="checkbox" name="SCOREBOARD_SHOW_SOG" value="1" {% if cfg.SCOREBOARD_SHOW_SOG %}checked{% endif %}> Show SOG (NHL)</label>
  <label><input type="checkbox" name="SCOREBOARD_SHOW_POSSESSION" value="1" {% if cfg.SCOREBOARD_SHOW_POSSESSION %}checked{% endif %}> Show possession (NFL)</label>
  <label><input type="checkbox" name="SCOREBOARD_INCLUDE_OTHERS" value="1" {% if cfg.SCOREBOARD_INCLUDE_OTHERS %}checked{% endif %}> Include others</label>
 </div>
 <div class="grid3" style="margin-top:8px">
  <label><input type="checkbox" name="SCOREBOARD_ONLY_MY_TEAMS" value="1" {% if cfg.SCOREBOARD_ONLY_MY_TEAMS %}checked{% endif %}> Only my teams</label>
  <div>
   <label>Scroll vs Static</label>
   <select name="SCOREBOARD_SCROLL_ENABLED">
    <option value="1" {% if cfg.SCOREBOARD_SCROLL_ENABLED %}selected{% endif %}>scroll</option>
    <option value="0" {% if not cfg.SCOREBOARD_SCROLL_ENABLED %}selected{% endif %}>static</option>
   </select>
  </div>
  <div><label>Static dwell (sec)</label><input name="SCOREBOARD_STATIC_DWELL_SEC" type="number" min="2" value="{{cfg.SCOREBOARD_STATIC_DWELL_SEC or 4}}"></div>
 </div>
 <div style="margin-top:8px">
  <label>Static align</label>
  <select name="SCOREBOARD_STATIC_ALIGN">
   {% for opt in ["left","center"] %}
   <option value="{{opt}}" {% if cfg.SCOREBOARD_STATIC_ALIGN==opt %}selected{% endif %}>{{opt}}</option>
   {% endfor %}
  </select>
 </div>
 <details style="margin-top:12px">
  <summary>Scoreboard Test Harness</summary>
  <div class="grid4" style="margin-top:8px">
   <label><input type="checkbox" name="SCOREBOARD_TEST" value="1" {% if cfg.SCOREBOARD_TEST %}checked{% endif %}> Enable</label>
   <div>
    <label>League</label>
    <select name="SCOREBOARD_TEST_LEAGUE">
     {% for opt in ["NHL","NFL"] %}
     <option value="{{opt}}" {% if (cfg.SCOREBOARD_TEST_LEAGUE or 'NHL')==opt %}selected{% endif %}>{{opt}}</option>
     {% endfor %}
    </select>
   </div>
   <div><label>Home Team (abbrev)</label><input name="SCOREBOARD_TEST_HOME" value="{{cfg.SCOREBOARD_TEST_HOME or ''}}"></div>
   <div><label>Away Team (abbrev)</label><input name="SCOREBOARD_TEST_AWAY" value="{{cfg.SCOREBOARD_TEST_AWAY or ''}}"></div>
  </div>
  <div style="margin-top:8px">
   <label>Test Duration (sec, 0=infinite)</label>
   <input name="SCOREBOARD_TEST_DURATION" type="number" min="0" value="{{cfg.SCOREBOARD_TEST_DURATION or 0}}">
  </div>
 </details>
</section>

<section>
 <h2>Score Alerts</h2>
 <div class="grid4">
  <label><input type="checkbox" name="SCORE_ALERTS_ENABLED" value="1" {% if cfg.SCORE_ALERTS_ENABLED %}checked{% endif %}> Enable</label>
  <label><input type="checkbox" name="SCORE_ALERTS_NHL" value="1" {% if cfg.SCORE_ALERTS_NHL %}checked{% endif %}> NHL alerts</label>
  <label><input type="checkbox" name="SCORE_ALERTS_NFL" value="1" {% if cfg.SCORE_ALERTS_NFL %}checked{% endif %}> NFL alerts</label>
  <label><input type="checkbox" name="SCORE_ALERTS_MY_TEAMS_ONLY" value="1" {% if cfg.SCORE_ALERTS_MY_TEAMS_ONLY %}checked{% endif %}> My teams only</label>
 </div>
 <div class="grid4" style="margin-top:8px">
  <div><label>Cycles per alert</label><input name="SCORE_ALERTS_CYCLES" type="number" min="1" value="{{cfg.SCORE_ALERTS_CYCLES or 2}}"></div>
  <div><label>Queue max</label><input name="SCORE_ALERTS_QUEUE_MAX" type="number" min="1" value="{{cfg.SCORE_ALERTS_QUEUE_MAX or 4}}"></div>
  <div><label>Flash ms</label><input name="SCORE_ALERTS_FLASH_MS" type="number" min="50" value="{{cfg.SCORE_ALERTS_FLASH_MS or 250}}"></div>
  <div><label>NFL TD delta (min points)</label><input name="SCORE_ALERTS_NFL_TD_DELTA_MIN" type="number" min="1" value="{{cfg.SCORE_ALERTS_NFL_TD_DELTA_MIN or 6}}"></div>
 </div>
 <div style="margin-top:8px">
  <label>Flash colors (comma, names)</label>
  <input name="SCORE_ALERTS_FLASH_COLORS" value="{{ (cfg.SCORE_ALERTS_FLASH_COLORS or ['red','white','blue'])|join(',') }}">
 </div>
 <details style="margin-top:8px">
  <summary>Test generator</summary>
  <div class="grid4" style="margin-top:8px">
   <label><input type="checkbox" name="SCORE_ALERTS_TEST" value="1" {% if cfg.SCORE_ALERTS_TEST %}checked{% endif %}> Enable test</label>
   <div><label>League</label>
    <select name="SCORE_ALERTS_TEST_LEAGUE">
     {% for opt in ["NHL","NFL"] %}
     <option value="{{opt}}" {% if (cfg.SCORE_ALERTS_TEST_LEAGUE or 'NHL')==opt %}selected{% endif %}>{{opt}}</option>
     {% endfor %}
    </select>
   </div>
   <div><label>Team</label><input name="SCORE_ALERTS_TEST_TEAM" value="{{cfg.SCORE_ALERTS_TEST_TEAM or 'MTL'}}"></div>
   <div><label>Interval (sec)</label><input name="SCORE_ALERTS_TEST_INTERVAL_SEC" type="number" min="1" value="{{cfg.SCORE_ALERTS_TEST_INTERVAL_SEC or 12}}"></div>
  </div>
 </details>
</section>

<section>
 <h2>Clock (Standalone Override)</h2>
 <p class="muted">These apply when <span class="mono">OVERRIDE_MODE=CLOCK</span> is active.</p>
 <div class="grid4">
  <label><input type="checkbox" name="CLOCK_24H" value="1" {% if cfg.CLOCK_24H %}checked{% endif %}> 24-hour clock</label>
  <label><input type="checkbox" name="CLOCK_SHOW_SECONDS" value="1" {% if cfg.CLOCK_SHOW_SECONDS %}checked{% endif %}> Show seconds</label>
  <label><input type="checkbox" name="CLOCK_BLINK_COLON" value="1" {% if cfg.CLOCK_BLINK_COLON %}checked{% endif %}> Blink colon</label>
  <div><label>Time color</label>
   <select name="CLOCK_COLOR">
    {% for opt in ["yellow","white","red","green","cyan","blue","magenta","orange","grey","black"] %}
    <option value="{{opt}}" {% if cfg.CLOCK_COLOR==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
 </div>
 <div class="grid4" style="margin-top:8px">
  <label><input type="checkbox" name="CLOCK_DATE_SHOW" value="1" {% if cfg.CLOCK_DATE_SHOW %}checked{% endif %}> Show date</label>
  <div><label>Date format (strftime)</label><input name="CLOCK_DATE_FMT" value="{{cfg.CLOCK_DATE_FMT or '%a %b %d'}}"></div>
  <div><label>Date color</label>
   <select name="CLOCK_DATE_COLOR">
    {% for opt in ["white","yellow","red","green","cyan","blue","magenta","orange","grey","black"] %}
    <option value="{{opt}}" {% if cfg.CLOCK_DATE_COLOR==opt %}selected{% endif %}>{{opt}}</option>
    {% endfor %}
   </select>
  </div>
 </div>
</section>

<section>
 <h2>Maintenance Banner</h2>
 <div class="grid3">
  <label><input type="checkbox" name="MAINTENANCE_MODE" value="1" {% if cfg.MAINTENANCE_MODE %}checked{% endif %}> Enable Maintenance Mode</label>
  <label><input type="checkbox" name="MAINTENANCE_SCROLL" value="1" {% if cfg.MAINTENANCE_SCROLL %}checked{% endif %}> Scroll banner</label>
  <div><label>Scroll PPS</label><input name="MAINTENANCE_PPS" type="number" step="0.5" value="{{cfg.MAINTENANCE_PPS or 24.0}}"></div>
 </div>
 <div style="margin-top:8px"><label>Text</label><input name="MAINTENANCE_TEXT" value="{{cfg.MAINTENANCE_TEXT or ''}}"></div>
</section>

<section>
 <h2>Diagnostics / Test Flags</h2>
 <div class="grid4">
  <label><input type="checkbox" name="DEMO_MODE" value="1" {% if cfg.DEMO_MODE %}checked{% endif %}> Demo Mode (no workers)</label>
  <label><input type="checkbox" name="DEBUG_OVERLAY" value="1" {% if cfg.DEBUG_OVERLAY %}checked{% endif %}> Debug Overlay</label>
 </div>
</section>

<div class="row">
 <div class="col"><button type="submit">Save</button></div>
</div>
</form>
</main></body></html>
"""

RAW_HTML = """
<!doctype html>
<html lang="en"><head>
 <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <title>Raw JSON Editor</title>
""" + BASE_CSS + """
</head><body>
<header>
 <h1>Raw JSON Editor</h1>
 <div class="toolbar"><a class="btn secondary" href="{{ url_for('home') }}">Back</a></div>
</header>
<main>
 <section>
  <form method="post" action="{{ url_for('raw_editor_post') }}">
   <label>config.json</label>
   <textarea name="json" rows="28" class="mono">{{ raw }}</textarea>
   <div style="margin-top:8px"><button type="submit">Save JSON</button></div>
  </form>
 </section>
</main></body></html>
"""

OVERRIDE_HTML = """
<!doctype html>
<html lang="en"><head>
 <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <title>Overrides</title>
""" + BASE_CSS + """
</head><body>
<header>
 <h1>Temporary Overrides</h1>
 <div class="toolbar"><a class="btn secondary" href="{{ url_for('home') }}">Back</a></div>
</header>
<main>
<section>
 <form method="post" action="{{ url_for('apply_override') }}">
  <div class="grid3">
   <div><label>Mode</label>
    <select name="OVERRIDE_MODE">
     {% for m in ["OFF","BRIGHT","SCOREBOARD","MESSAGE","MAINT","CLOCK"] %}
     <option value="{{m}}" {% if cfg.OVERRIDE_MODE==m %}selected{% endif %}>{{m}}</option>
     {% endfor %}
    </select>
   </div>
   <div><label>Duration (minutes, 0 = until cleared)</label>
    <input type="number" name="OVERRIDE_DURATION_MIN" min="0" value="{{cfg.OVERRIDE_DURATION_MIN or 0}}">
   </div>
   <div><label>Message text (for MESSAGE override)</label>
    <input name="OVERRIDE_MESSAGE_TEXT" value="{{cfg.OVERRIDE_MESSAGE_TEXT or ''}}">
   </div>
  </div>
  <p class="muted">For <span class="mono">CLOCK</span>, adjust settings in the "Clock (Standalone Override)" section on the main page.</p>
  <div style="margin-top:12px"><button type="submit">Apply</button></div>
 </form>
</section>
</main></body></html>
"""

PREVIEW_HTML = """
<!doctype html>
<html lang="en"><head>
 <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <title>Live Preview</title>
""" + BASE_CSS + """
</head><body>
<header>
 <h1>Live Preview</h1>
 <div class="toolbar"><a class="btn secondary" href="{{ url_for('home') }}">Back</a></div>
</header>
<main>
 <section>
  <div class="row">
   <div class="col" style="max-width:720px">
    <div class="preview-card">
     <img id="pimg" src="{{ url_for('preview_png') }}?scale={{scale}}&t={{nowts}}" alt="preview" style="image-rendering:pixelated;max-width:100%;height:auto">
     <div class="preview-meta mono">{{wh}} | {{mode}} | scale=<span id="scval">{{scale}}</span> | {{preview_status}}</div>
    </div>
   </div>
   <div class="col">
    <div class="preview-card">
     <label>Refresh (ms)</label>
     <input id="irefresh" type="number" min="250" step="50" value="750">
     <label style="margin-top:8px">Scale (1-12)</label>
     <input id="iscale" type="number" min="1" max="12" step="1" value="{{scale}}">
     <div style="margin-top:8px;display:flex;gap:8px">
      <button id="btnStart" type="button">Start</button>
      <button id="btnStop" class="secondary" type="button">Stop</button>
      <a class="btn secondary" target="_blank" href="{{ url_for('preview_png') }}?scale={{scale}}">Open PNG</a>
     </div>
     <p class="hint" style="margin-top:10px">Preview works in RGBMATRIX mode (reads /tmp/ticker_preview.png). Requires Pillow.</p>
    </div>
   </div>
  </div>
 </section>
</main>
<script>
(function(){
  const img = document.getElementById('pimg');
  const scv = document.getElementById('scval');
  const iref = document.getElementById('irefresh');
  const iscale = document.getElementById('iscale');
  let timer = null;
  function tick(){
    const scale = Math.max(1, Math.min(12, parseInt(iscale.value || {{scale}})));
    scv.textContent = scale;
    const t = Date.now();
    img.src = '{{ url_for('preview_png') }}?scale=' + scale + '&t=' + t;
  }
  function start(){
    stop();
    const ms = Math.max(250, parseInt(iref.value || 750));
    tick();
    timer = setInterval(tick, ms);
  }
  function stop(){ if(timer){ clearInterval(timer); timer=null; } }
  document.getElementById('btnStart').addEventListener('click', start);
  document.getElementById('btnStop').addEventListener('click', stop);
  start();
})();
</script>
</body></html>
"""

# Documentation is served from docs.html in the project directory

# ---------------------------- routes -----------------------------------
@app.route("/")
def home():
    cfg = load_cfg()
    cfg.setdefault("TICKERS_TOP", [])
    cfg.setdefault("TICKERS_BOT", [])
    cfg.setdefault("HOLDINGS", {})
    cfg.setdefault("MICROFONT_ENABLED", False)

    w, h = _derive_panel_WH(cfg)
    mode = (cfg.get("OUTPUT_MODE") or "HDMI").upper()
    preview_path = "/tmp/ticker_preview.png"
    preview_ok = os.path.exists(preview_path) and mode == "RGBMATRIX"
    preview_status = "ready" if preview_ok else ("Preview unavailable" if not preview_ok else "HDMI mode")

    dim_windows_text = _dim_windows_to_text(cfg.get("DIM_WINDOWS"))
    top_pairs = _pairs_to_text(cfg.get("TICKERS_TOP"))
    bot_pairs = _pairs_to_text(cfg.get("TICKERS_BOT"))
    holdings_text = _holdings_to_text(cfg.get("HOLDINGS"))

    return render_template_string(
        HOME_HTML,
        title=APP_TITLE,
        cfg=cfg,
        top_pairs=top_pairs,
        bot_pairs=bot_pairs,
        holdings_text=holdings_text,
        dim_windows_text=dim_windows_text,
        wh=f"{w}x{h}",
        mode=f"mode={mode}",
        scale=int(cfg.get("TICKER_SCALE", 6) or 6),
        preview_status=preview_status,
        nowts=int(time.time()),
    )

@app.post("/save")
def save():
    cfg = load_cfg()
    # --- Display & Layout ---
    cfg["OUTPUT_MODE"] = request.form.get("OUTPUT_MODE", cfg.get("OUTPUT_MODE", "HDMI"))
    cfg["LAYOUT"] = request.form.get("LAYOUT", cfg.get("LAYOUT", ""))
    cfg["TICKER_TZ"] = request.form.get("TICKER_TZ", cfg.get("TICKER_TZ", ""))
    cfg["MICROFONT_ENABLED"] = _get_bool(request.form, "MICROFONT_ENABLED", cfg.get("MICROFONT_ENABLED", False))
    cfg["MODEL_NAME"] = request.form.get("MODEL_NAME", cfg.get("MODEL_NAME", "Matrix96x16"))
    cfg["W"] = _get_num(request.form, "W", cfg.get("W", 0), int)
    cfg["H"] = _get_num(request.form, "H", cfg.get("H", 0), int)
    cfg["FPS"] = _get_num(request.form, "FPS", cfg.get("FPS", 30), int)
    cfg["PPS_TOP"] = _get_num(request.form, "PPS_TOP", cfg.get("PPS_TOP", 16.0), float)
    cfg["PPS_BOT"] = _get_num(request.form, "PPS_BOT", cfg.get("PPS_BOT", 20.0), float)
    cfg["PPS_SINGLE"] = _get_num(request.form, "PPS_SINGLE", cfg.get("PPS_SINGLE", 20.0), float)
    cfg["TICKER_SCALE"] = _get_num(request.form, "TICKER_SCALE", cfg.get("TICKER_SCALE", 8), int)
    cfg["FORCE_KMS"] = _get_bool(request.form, "FORCE_KMS", cfg.get("FORCE_KMS", False))
    cfg["USE_SDL_SCALED"] = _get_bool(request.form, "USE_SDL_SCALED", cfg.get("USE_SDL_SCALED", True))
    cfg["USE_BUSY_LOOP"] = _get_bool(request.form, "USE_BUSY_LOOP", cfg.get("USE_BUSY_LOOP", False))
    
    # --- RGB Matrix Hardware ---
    cfg["RGB_BRIGHTNESS"] = _get_num(request.form, "RGB_BRIGHTNESS", cfg.get("RGB_BRIGHTNESS", 100), int)
    cfg["RGB_HARDWARE_MAPPING"] = request.form.get("RGB_HARDWARE_MAPPING", cfg.get("RGB_HARDWARE_MAPPING", "adafruit-hat"))
    cfg["RGB_GPIO_SLOWDOWN"] = _get_num(request.form, "RGB_GPIO_SLOWDOWN", cfg.get("RGB_GPIO_SLOWDOWN", 4), int)
    cfg["RGB_PWM_BITS"] = _get_num(request.form, "RGB_PWM_BITS", cfg.get("RGB_PWM_BITS", 11), int)
    cfg["RGB_PWM_LSB_NANOSECONDS"] = _get_num(request.form, "RGB_PWM_LSB_NANOSECONDS", cfg.get("RGB_PWM_LSB_NANOSECONDS", 130), int)
    cfg["RGB_CHAIN_LENGTH"] = _get_num(request.form, "RGB_CHAIN_LENGTH", cfg.get("RGB_CHAIN_LENGTH", 1), int)
    cfg["RGB_PARALLEL"] = _get_num(request.form, "RGB_PARALLEL", cfg.get("RGB_PARALLEL", 1), int)
    cfg["RGB_SCAN_MODE"] = _get_num(request.form, "RGB_SCAN_MODE", cfg.get("RGB_SCAN_MODE", 0), int)
    cfg["RGB_ROW_ADDRESS_TYPE"] = _get_num(request.form, "RGB_ROW_ADDRESS_TYPE", cfg.get("RGB_ROW_ADDRESS_TYPE", 0), int)
    cfg["RGB_MULTIPLEXING"] = _get_num(request.form, "RGB_MULTIPLEXING", cfg.get("RGB_MULTIPLEXING", 0), int)
    cfg["RGB_LED_RGB_SEQUENCE"] = request.form.get("RGB_LED_RGB_SEQUENCE", cfg.get("RGB_LED_RGB_SEQUENCE", "RGB"))
    cfg["RGB_PIXEL_MAPPER"] = request.form.get("RGB_PIXEL_MAPPER", cfg.get("RGB_PIXEL_MAPPER", ""))
    cfg["RGB_PANEL_TYPE"] = request.form.get("RGB_PANEL_TYPE", cfg.get("RGB_PANEL_TYPE", ""))

    # --- Tickers ---
    cfg["TICKERS_TOP"] = _parse_lines_pairs(request.form.get("TICKERS_TOP", ""))
    cfg["TICKERS_BOT"] = _parse_lines_pairs(request.form.get("TICKERS_BOT", ""))
    cfg["REFRESH_SEC"] = _get_num(request.form, "REFRESH_SEC", cfg.get("REFRESH_SEC", 240), int)
    cfg["FRESH_SEC"] = _get_num(request.form, "FRESH_SEC", cfg.get("FRESH_SEC", 300), int)

    # --- Holdings ---
    cfg["HOLDINGS_ENABLED"] = _get_bool(
        request.form, "HOLDINGS_ENABLED", cfg.get("HOLDINGS_ENABLED", True)
    )
    cfg["HOLDINGS"] = _parse_holdings(request.form.get("HOLDINGS", ""))

    # --- Preroll ---
    cfg["TIME_PREROLL_ENABLED"] = _get_bool(request.form, "TIME_PREROLL_ENABLED", cfg.get("TIME_PREROLL_ENABLED", True))
    cfg["TIME_PREROLL_SEC"] = _get_num(request.form, "TIME_PREROLL_SEC", cfg.get("TIME_PREROLL_SEC", 15), int)
    cfg["PREROLL_STYLE"] = request.form.get("PREROLL_STYLE", cfg.get("PREROLL_STYLE", "bigtime"))
    cfg["PREROLL_COLOR"] = request.form.get("PREROLL_COLOR", cfg.get("PREROLL_COLOR", "yellow"))
    cfg["PREROLL_PPS"] = _get_num(request.form, "PREROLL_PPS", cfg.get("PREROLL_PPS", 40.0), float)

    # --- Message & Weather ---
    cfg["INJECT_MESSAGE"] = request.form.get("INJECT_MESSAGE", cfg.get("INJECT_MESSAGE", ""))
    cfg["MESSAGE_EVERY"] = _get_num(request.form, "MESSAGE_EVERY", cfg.get("MESSAGE_EVERY", 0), int)
    cfg["MESSAGE_ROW"] = request.form.get("MESSAGE_ROW", cfg.get("MESSAGE_ROW", "auto"))
    cfg["MESSAGE_COLOR"] = request.form.get("MESSAGE_COLOR", cfg.get("MESSAGE_COLOR", "yellow"))
    cfg["MESSAGE_TEST_FORCE"] = _get_bool(request.form, "MESSAGE_TEST_FORCE", cfg.get("MESSAGE_TEST_FORCE", False))
    cfg["WEATHER_RSS_URL"] = request.form.get("WEATHER_RSS_URL", cfg.get("WEATHER_RSS_URL", ""))
    cfg["WEATHER_ANNOUNCE_SEC"] = _get_num(request.form, "WEATHER_ANNOUNCE_SEC", cfg.get("WEATHER_ANNOUNCE_SEC", 600), int)
    cfg["WEATHER_REFRESH_SEC"] = _get_num(request.form, "WEATHER_REFRESH_SEC", cfg.get("WEATHER_REFRESH_SEC", 300), int)
    cfg["WEATHER_INCLUDE_WATCH"] = _get_bool(request.form, "WEATHER_INCLUDE_WATCH", cfg.get("WEATHER_INCLUDE_WATCH", True))
    cfg["WEATHER_FORCE_ACTIVE"] = _get_bool(request.form, "WEATHER_FORCE_ACTIVE", cfg.get("WEATHER_FORCE_ACTIVE", False))
    cfg["WEATHER_FORCE_TEXT"] = request.form.get("WEATHER_FORCE_TEXT", cfg.get("WEATHER_FORCE_TEXT", ""))
    # Extended Weather
    cfg["WEATHER_REPEAT_SEC"] = _get_num(request.form, "WEATHER_REPEAT_SEC", cfg.get("WEATHER_REPEAT_SEC", 600), int)
    cfg["WEATHER_STICKY_SEC"] = _get_num(request.form, "WEATHER_STICKY_SEC", cfg.get("WEATHER_STICKY_SEC", 20), int)
    cfg["WEATHER_TEST_STICKY_TOTAL"] = _get_num(request.form, "WEATHER_TEST_STICKY_TOTAL", cfg.get("WEATHER_TEST_STICKY_TOTAL", 60), int)
    cfg["WEATHER_TIMEOUT"] = _get_num(request.form, "WEATHER_TIMEOUT", cfg.get("WEATHER_TIMEOUT", 5.0), float)
    cfg["WEATHER_TEST_DELAY"] = _get_num(request.form, "WEATHER_TEST_DELAY", cfg.get("WEATHER_TEST_DELAY", 0), int)

    # --- Weather Severity Display ---
    cfg["WEATHER_WARNING_EVERY_N_SCROLLS"] = _get_num(request.form, "WEATHER_WARNING_EVERY_N_SCROLLS", cfg.get("WEATHER_WARNING_EVERY_N_SCROLLS", 5), int)
    cfg["WEATHER_WARNING_COLOR"] = request.form.get("WEATHER_WARNING_COLOR", cfg.get("WEATHER_WARNING_COLOR", "red"))
    cfg["WEATHER_ADVISORY_EVERY_N_SCROLLS"] = _get_num(request.form, "WEATHER_ADVISORY_EVERY_N_SCROLLS", cfg.get("WEATHER_ADVISORY_EVERY_N_SCROLLS", 10), int)
    cfg["WEATHER_ADVISORY_COLOR"] = request.form.get("WEATHER_ADVISORY_COLOR", cfg.get("WEATHER_ADVISORY_COLOR", "yellow"))

    # --- Scheduler ---
    cfg["SCHEDULE_ENABLED"] = _get_bool(request.form, "SCHEDULE_ENABLED", cfg.get("SCHEDULE_ENABLED", True))
    cfg["SCHEDULE_OFF_START"] = request.form.get("SCHEDULE_OFF_START", cfg.get("SCHEDULE_OFF_START", "23:00"))
    cfg["SCHEDULE_OFF_END"] = request.form.get("SCHEDULE_OFF_END", cfg.get("SCHEDULE_OFF_END", "07:00"))
    cfg["SCHEDULE_BLANK_FPS"] = _get_num(request.form, "SCHEDULE_BLANK_FPS", cfg.get("SCHEDULE_BLANK_FPS", 5), int)
    cfg["SCHEDULE_TEST_FORCE_OFF"] = _get_bool(request.form, "SCHEDULE_TEST_FORCE_OFF", cfg.get("SCHEDULE_TEST_FORCE_OFF", False))

    # --- Dimming (DIM_WINDOWS schedule + test) ---
    # Remove legacy dim keys if present
    for old_key in ("DIM_ENABLED", "DIM_LEVEL", "DIM_CUSTOM_PCT", "DIM_SCHEDULE_ENABLED",
                     "DIM1_START", "DIM1_END", "DIM1_PCT", "DIM2_START", "DIM2_END", "DIM2_PCT",
                     "DIM3_START", "DIM3_END", "DIM3_PCT"):
        cfg.pop(old_key, None)
    dim_wins_txt = request.form.get("DIM_WINDOWS", "")
    dim_wins = _parse_dim_windows(dim_wins_txt)
    if dim_wins:
        cfg["DIM_WINDOWS"] = dim_wins
    else:
        cfg.pop("DIM_WINDOWS", None)
    cfg["DIM_TEST_ENABLED"] = _get_bool(request.form, "DIM_TEST_ENABLED", cfg.get("DIM_TEST_ENABLED", False))
    cfg["DIM_TEST_PCT"] = _get_num(request.form, "DIM_TEST_PCT", cfg.get("DIM_TEST_PCT", 0), int)

    # --- Night Mode ---
    cfg["NIGHT_MODE_ENABLED"] = _get_bool(request.form, "NIGHT_MODE_ENABLED", cfg.get("NIGHT_MODE_ENABLED", False))
    cfg["NIGHT_MODE_START"] = request.form.get("NIGHT_MODE_START", cfg.get("NIGHT_MODE_START", "22:00"))
    cfg["NIGHT_MODE_END"] = request.form.get("NIGHT_MODE_END", cfg.get("NIGHT_MODE_END", "07:00"))
    cfg["NIGHT_MODE_DIM_PCT"] = _get_num(request.form, "NIGHT_MODE_DIM_PCT", cfg.get("NIGHT_MODE_DIM_PCT", 30), int)
    cfg["NIGHT_MODE_SPEED_PCT"] = _get_num(request.form, "NIGHT_MODE_SPEED_PCT", cfg.get("NIGHT_MODE_SPEED_PCT", 50), int)

    # --- Fonts ---
    cfg["FONT_FAMILY_BASE"] = request.form.get("FONT_FAMILY_BASE", cfg.get("FONT_FAMILY_BASE", "DejaVuSansMono"))
    cfg["FONT_FAMILY_SCOREBOARD"] = request.form.get("FONT_FAMILY_SCOREBOARD", cfg.get("FONT_FAMILY_SCOREBOARD", cfg.get("FONT_FAMILY_BASE", "DejaVuSansMono")))
    cfg["FONT_FAMILY_DEBUG"] = request.form.get("FONT_FAMILY_DEBUG", cfg.get("FONT_FAMILY_DEBUG", cfg.get("FONT_FAMILY_BASE", "DejaVuSansMono")))
    cfg["FONT_SIZE_ROW"] = request.form.get("FONT_SIZE_ROW", cfg.get("FONT_SIZE_ROW", "auto"))
    cfg["FONT_SIZE_SB"] = request.form.get("FONT_SIZE_SB", cfg.get("FONT_SIZE_SB", "auto"))
    cfg["FONT_SIZE_DEBUG"] = request.form.get("FONT_SIZE_DEBUG", cfg.get("FONT_SIZE_DEBUG", "auto"))
    cfg["FONT_BOLD_BASE"] = _get_bool(request.form, "FONT_BOLD_BASE", cfg.get("FONT_BOLD_BASE", True))
    cfg["FONT_BOLD_SB"] = _get_bool(request.form, "FONT_BOLD_SB", cfg.get("FONT_BOLD_SB", True))
    cfg["FONT_BOLD_DEBUG"] = _get_bool(request.form, "FONT_BOLD_DEBUG", cfg.get("FONT_BOLD_DEBUG", False))
    cfg["PREROLL_FONT_FAMILY"] = request.form.get("PREROLL_FONT_FAMILY", cfg.get("PREROLL_FONT_FAMILY", cfg.get("FONT_FAMILY_BASE", "DejaVuSansMono")))
    cfg["PREROLL_FONT_PX"] = _get_num(request.form, "PREROLL_FONT_PX", cfg.get("PREROLL_FONT_PX", 0), int)
    cfg["PREROLL_FONT_BOLD"] = _get_bool(request.form, "PREROLL_FONT_BOLD", cfg.get("PREROLL_FONT_BOLD", True))
    cfg["MAINT_FONT_FAMILY"] = request.form.get("MAINT_FONT_FAMILY", cfg.get("MAINT_FONT_FAMILY", cfg.get("FONT_FAMILY_BASE", "DejaVuSansMono")))
    cfg["MAINT_FONT_PX"] = _get_num(request.form, "MAINT_FONT_PX", cfg.get("MAINT_FONT_PX", 0), int)
    cfg["MAINT_FONT_BOLD"] = _get_bool(request.form, "MAINT_FONT_BOLD", cfg.get("MAINT_FONT_BOLD", True))

    # --- Scoreboard ---
    cfg["SCOREBOARD_ENABLED"] = _get_bool(request.form, "SCOREBOARD_ENABLED", cfg.get("SCOREBOARD_ENABLED", True))
    cfg["SCOREBOARD_LEAGUES"] = _get_csv_upper(request.form, "SCOREBOARD_LEAGUES", cfg.get("SCOREBOARD_LEAGUES", ["NHL", "NFL"]))
    cfg["SCOREBOARD_NHL_TEAMS"] = _get_csv_upper(request.form, "SCOREBOARD_NHL_TEAMS", cfg.get("SCOREBOARD_NHL_TEAMS", ["MTL"]))
    cfg["SCOREBOARD_NFL_TEAMS"] = _get_csv_upper(request.form, "SCOREBOARD_NFL_TEAMS", cfg.get("SCOREBOARD_NFL_TEAMS", ["NE"]))
    cfg["SCOREBOARD_POLL_WINDOW_MIN"] = _get_num(request.form, "SCOREBOARD_POLL_WINDOW_MIN", cfg.get("SCOREBOARD_POLL_WINDOW_MIN", 120), int)
    cfg["SCOREBOARD_POLL_CADENCE"] = _get_num(request.form, "SCOREBOARD_POLL_CADENCE", cfg.get("SCOREBOARD_POLL_CADENCE", 60), int)
    cfg["SCOREBOARD_LIVE_REFRESH"] = _get_num(request.form, "SCOREBOARD_LIVE_REFRESH", cfg.get("SCOREBOARD_LIVE_REFRESH", 45), int)
    cfg["SCOREBOARD_PREGAME_WINDOW_MIN"] = _get_num(request.form, "SCOREBOARD_PREGAME_WINDOW_MIN", cfg.get("SCOREBOARD_PREGAME_WINDOW_MIN", 30), int)
    cfg["SCOREBOARD_POSTGAME_DELAY_MIN"] = _get_num(request.form, "SCOREBOARD_POSTGAME_DELAY_MIN", cfg.get("SCOREBOARD_POSTGAME_DELAY_MIN", 5), int)
    cfg["SCOREBOARD_SHOW_COUNTDOWN"] = _get_bool(request.form, "SCOREBOARD_SHOW_COUNTDOWN", cfg.get("SCOREBOARD_SHOW_COUNTDOWN", True))
    cfg["SCOREBOARD_PRECEDENCE"] = request.form.get("SCOREBOARD_PRECEDENCE", cfg.get("SCOREBOARD_PRECEDENCE", "normal"))
    cfg["SCOREBOARD_LAYOUT"] = request.form.get("SCOREBOARD_LAYOUT", cfg.get("SCOREBOARD_LAYOUT", "auto"))
    cfg["SCOREBOARD_UPPERCASE"] = _get_bool(request.form, "SCOREBOARD_UPPERCASE", cfg.get("SCOREBOARD_UPPERCASE", True))
    cfg["SCOREBOARD_HOME_FIRST"] = _get_bool(request.form, "SCOREBOARD_HOME_FIRST", cfg.get("SCOREBOARD_HOME_FIRST", True))
    cfg["SCOREBOARD_SHOW_CLOCK"] = _get_bool(request.form, "SCOREBOARD_SHOW_CLOCK", cfg.get("SCOREBOARD_SHOW_CLOCK", True))
    cfg["SCOREBOARD_SHOW_SOG"] = _get_bool(request.form, "SCOREBOARD_SHOW_SOG", cfg.get("SCOREBOARD_SHOW_SOG", True))
    cfg["SCOREBOARD_SHOW_POSSESSION"] = _get_bool(request.form, "SCOREBOARD_SHOW_POSSESSION", cfg.get("SCOREBOARD_SHOW_POSSESSION", True))
    cfg["SCOREBOARD_INCLUDE_OTHERS"] = _get_bool(request.form, "SCOREBOARD_INCLUDE_OTHERS", cfg.get("SCOREBOARD_INCLUDE_OTHERS", False))
    cfg["SCOREBOARD_ONLY_MY_TEAMS"] = _get_bool(request.form, "SCOREBOARD_ONLY_MY_TEAMS", cfg.get("SCOREBOARD_ONLY_MY_TEAMS", True))
    cfg["SCOREBOARD_MAX_GAMES"] = _get_num(request.form, "SCOREBOARD_MAX_GAMES", cfg.get("SCOREBOARD_MAX_GAMES", 2), int)
    cfg["SCOREBOARD_SCROLL_ENABLED"] = True if request.form.get("SCOREBOARD_SCROLL_ENABLED", "1") == "1" else False
    cfg["SCOREBOARD_STATIC_DWELL_SEC"] = _get_num(request.form, "SCOREBOARD_STATIC_DWELL_SEC", cfg.get("SCOREBOARD_STATIC_DWELL_SEC", 4), int)
    cfg["SCOREBOARD_STATIC_ALIGN"] = request.form.get("SCOREBOARD_STATIC_ALIGN", cfg.get("SCOREBOARD_STATIC_ALIGN", "left"))
    # Test harness
    cfg["SCOREBOARD_TEST"] = _get_bool(request.form, "SCOREBOARD_TEST", cfg.get("SCOREBOARD_TEST", False))
    cfg["SCOREBOARD_TEST_LEAGUE"] = request.form.get("SCOREBOARD_TEST_LEAGUE", cfg.get("SCOREBOARD_TEST_LEAGUE", "NHL"))
    cfg["SCOREBOARD_TEST_HOME"] = request.form.get("SCOREBOARD_TEST_HOME", cfg.get("SCOREBOARD_TEST_HOME", ""))
    cfg["SCOREBOARD_TEST_AWAY"] = request.form.get("SCOREBOARD_TEST_AWAY", cfg.get("SCOREBOARD_TEST_AWAY", ""))
    cfg["SCOREBOARD_TEST_DURATION"] = _get_num(request.form, "SCOREBOARD_TEST_DURATION", cfg.get("SCOREBOARD_TEST_DURATION", 0), int)

    # --- Score Alerts ---
    cfg["SCORE_ALERTS_ENABLED"] = _get_bool(request.form, "SCORE_ALERTS_ENABLED", cfg.get("SCORE_ALERTS_ENABLED", True))
    cfg["SCORE_ALERTS_NHL"] = _get_bool(request.form, "SCORE_ALERTS_NHL", cfg.get("SCORE_ALERTS_NHL", True))
    cfg["SCORE_ALERTS_NFL"] = _get_bool(request.form, "SCORE_ALERTS_NFL", cfg.get("SCORE_ALERTS_NFL", True))
    cfg["SCORE_ALERTS_MY_TEAMS_ONLY"] = _get_bool(request.form, "SCORE_ALERTS_MY_TEAMS_ONLY", cfg.get("SCORE_ALERTS_MY_TEAMS_ONLY", True))
    cfg["SCORE_ALERTS_CYCLES"] = _get_num(request.form, "SCORE_ALERTS_CYCLES", cfg.get("SCORE_ALERTS_CYCLES", 2), int)
    cfg["SCORE_ALERTS_QUEUE_MAX"] = _get_num(request.form, "SCORE_ALERTS_QUEUE_MAX", cfg.get("SCORE_ALERTS_QUEUE_MAX", 4), int)
    cfg["SCORE_ALERTS_FLASH_MS"] = _get_num(request.form, "SCORE_ALERTS_FLASH_MS", cfg.get("SCORE_ALERTS_FLASH_MS", 250), int)
    cfg["SCORE_ALERTS_NFL_TD_DELTA_MIN"] = _get_num(request.form, "SCORE_ALERTS_NFL_TD_DELTA_MIN", cfg.get("SCORE_ALERTS_NFL_TD_DELTA_MIN", 6), int)
    colors = (request.form.get("SCORE_ALERTS_FLASH_COLORS", "") or "").strip()
    if colors:
        cfg["SCORE_ALERTS_FLASH_COLORS"] = [c.strip().lower() for c in colors.split(",") if c.strip()]
    cfg["SCORE_ALERTS_TEST"] = _get_bool(request.form, "SCORE_ALERTS_TEST", cfg.get("SCORE_ALERTS_TEST", False))
    cfg["SCORE_ALERTS_TEST_LEAGUE"] = request.form.get("SCORE_ALERTS_TEST_LEAGUE", cfg.get("SCORE_ALERTS_TEST_LEAGUE", "NHL"))
    cfg["SCORE_ALERTS_TEST_TEAM"] = request.form.get("SCORE_ALERTS_TEST_TEAM", cfg.get("SCORE_ALERTS_TEST_TEAM", "MTL"))
    cfg["SCORE_ALERTS_TEST_INTERVAL_SEC"] = _get_num(request.form, "SCORE_ALERTS_TEST_INTERVAL_SEC", cfg.get("SCORE_ALERTS_TEST_INTERVAL_SEC", 12), int)

    # --- Clock (Standalone Override) ---
    cfg["CLOCK_24H"] = _get_bool(request.form, "CLOCK_24H", cfg.get("CLOCK_24H", True))
    cfg["CLOCK_SHOW_SECONDS"] = _get_bool(request.form, "CLOCK_SHOW_SECONDS", cfg.get("CLOCK_SHOW_SECONDS", False))
    cfg["CLOCK_BLINK_COLON"] = _get_bool(request.form, "CLOCK_BLINK_COLON", cfg.get("CLOCK_BLINK_COLON", True))
    cfg["CLOCK_COLOR"] = request.form.get("CLOCK_COLOR", cfg.get("CLOCK_COLOR", "yellow"))
    cfg["CLOCK_DATE_SHOW"] = _get_bool(request.form, "CLOCK_DATE_SHOW", cfg.get("CLOCK_DATE_SHOW", True))
    cfg["CLOCK_DATE_FMT"] = request.form.get("CLOCK_DATE_FMT", cfg.get("CLOCK_DATE_FMT", "%a %b %d"))
    cfg["CLOCK_DATE_COLOR"] = request.form.get("CLOCK_DATE_COLOR", cfg.get("CLOCK_DATE_COLOR", "white"))

    # --- Maintenance ---
    cfg["MAINTENANCE_MODE"] = _get_bool(request.form, "MAINTENANCE_MODE", cfg.get("MAINTENANCE_MODE", False))
    cfg["MAINTENANCE_SCROLL"] = _get_bool(request.form, "MAINTENANCE_SCROLL", cfg.get("MAINTENANCE_SCROLL", False))
    cfg["MAINTENANCE_PPS"] = _get_num(request.form, "MAINTENANCE_PPS", cfg.get("MAINTENANCE_PPS", 24.0), float)
    cfg["MAINTENANCE_TEXT"] = request.form.get("MAINTENANCE_TEXT", cfg.get("MAINTENANCE_TEXT", ""))

    # --- Diagnostics / Tests ---
    cfg["DEMO_MODE"] = _get_bool(request.form, "DEMO_MODE", cfg.get("DEMO_MODE", False))
    cfg["DEBUG_OVERLAY"] = _get_bool(request.form, "DEBUG_OVERLAY", cfg.get("DEBUG_OVERLAY", False))

    atomic_save_cfg(cfg)
    flash("OK Saved. Ticker will pick this up within ~1s.")
    return redirect(url_for("home"))

@app.get("/raw")
def raw_editor():
    cfg = load_cfg()
    raw = json.dumps(cfg, indent=2, ensure_ascii=False)
    return render_template_string(RAW_HTML, raw=raw)

@app.post("/raw")
def raw_editor_post():
    txt = request.form.get("json", "")
    try:
        data = json.loads(txt)
        if not isinstance(data, dict):
            raise ValueError("JSON must be an object at top level")
        atomic_save_cfg(data)
        flash("OK Saved JSON.")
        return redirect(url_for("raw_editor"))
    except Exception as e:
        flash(f" JSON error: {html.escape(str(e))}")
        return redirect(url_for("raw_editor"))

@app.get("/overrides")
def override_page():
    cfg = load_cfg()
    return render_template_string(OVERRIDE_HTML, cfg=cfg)

@app.post("/overrides")
def apply_override():
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = (request.form.get("OVERRIDE_MODE", "OFF") or "OFF").upper()
    try:
        cfg["OVERRIDE_DURATION_MIN"] = int(request.form.get("OVERRIDE_DURATION_MIN", "0") or 0)
    except Exception:
        cfg["OVERRIDE_DURATION_MIN"] = 0
    cfg["OVERRIDE_MESSAGE_TEXT"] = request.form.get("OVERRIDE_MESSAGE_TEXT", "")
    atomic_save_cfg(cfg)
    flash(f"Override applied: {cfg['OVERRIDE_MODE']}")
    return redirect(url_for("override_page"))

@app.post("/restart")
def restart_ticker():
    ok, msg = _run_restart_command()
    flash(("OK " if ok else " ") + msg)
    return redirect(url_for("home"))

# --------- Live Preview routes ---------
@app.get("/preview")
def preview_page():
    cfg = load_cfg()
    w, h = _derive_panel_WH(cfg)
    mode = (cfg.get("OUTPUT_MODE") or "HDMI").upper()
    preview_path = "/tmp/ticker_preview.png"
    status = "ready" if os.path.exists(preview_path) else "waiting for ticker"
    return render_template_string(
        PREVIEW_HTML,
        scale=int(cfg.get("TICKER_SCALE", 6) or 6),
        wh=f"{w}x{h}",
        mode=f"mode={mode}",
        preview_status=status,
        nowts=int(time.time()),
    )

@app.get("/docs")
@app.get("/documentation")
def documentation():
    """Serve docs.html from the project directory."""
    import datetime
    docs_path = os.path.join(BASE_DIR, "docs.html")
    if not os.path.exists(docs_path):
        return Response("Documentation file (docs.html) not found in project directory.", status=404, mimetype="text/plain")
    version = datetime.datetime.now().strftime("%Y.%m.%d")
    with open(docs_path, "r", encoding="utf-8") as f:
        raw = f.read()
    raw = raw.replace("v{{ version }}", f"v{version}")
    return Response(raw, mimetype="text/html; charset=utf-8")

@app.get("/preview.png")
def preview_png():
    cfg = load_cfg()
    try:
        scale = int(request.args.get("scale", cfg.get("TICKER_SCALE", 6) or 6))
    except Exception:
        scale = 6
    ok, payload, mime = _read_preview_png_bytes(cfg, scale=scale)
    if not ok:
        if mime == "text/plain":
            return Response(payload, status=503, mimetype=mime)
        return Response("preview unavailable", status=503)
    return Response(payload, mimetype=mime, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })

# JSON helpers (optional)
@app.get("/api/config")
def api_get_config():
    return jsonify(load_cfg())

@app.post("/api/config")
def api_set_config():
    cfg = request.get_json(force=True, silent=True) or {}
    if not isinstance(cfg, dict):
        return jsonify({"ok": False, "error": "expected JSON object"}), 400
    atomic_save_cfg(cfg)
    return jsonify({"ok": True})

@app.get("/api/status")
def api_status():
    """Get current system status."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SYSTEMD_SERVICE],
            capture_output=True, text=True, timeout=2
        )
        service_running = result.stdout.strip() == "active"
    except Exception:
        service_running = False
    return jsonify({
        "service_running": service_running,
        "service_name": SYSTEMD_SERVICE,
        "timestamp": int(time.time())
    })

@app.get("/api/workers")
def api_workers():
    """Get worker status from ticker_status.json."""
    status_file = os.path.join(BASE_DIR, "ticker_status.json")
    try:
        if os.path.exists(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            workers = data.get("workers", {})
            # Calculate time since last update for each worker
            now = time.time()
            for worker_name, worker_data in workers.items():
                ts = worker_data.get("timestamp", 0)
                worker_data["seconds_ago"] = int(now - ts) if ts > 0 else None
            return jsonify({
                "workers": workers,
                "file_exists": True,
                "timestamp": int(now)
            })
        else:
            return jsonify({
                "workers": {},
                "file_exists": False,
                "error": "Status file not found - workers haven't started yet or ticker.py needs to be updated",
                "timestamp": int(time.time())
            })
    except Exception as e:
        return jsonify({
            "workers": {},
            "file_exists": False,
            "error": str(e),
            "timestamp": int(time.time())
        })

@app.post("/action/show-clock")
def action_show_clock():
    """Show clock for 5 minutes."""
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "CLOCK"
    cfg["OVERRIDE_DURATION_MIN"] = 5
    atomic_save_cfg(cfg)
    flash(" Clock mode for 5 min")
    return redirect(url_for("home"))

@app.post("/action/bright-mode")
def action_bright_mode():
    """Activate bright mode for 30 minutes."""
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "BRIGHT"
    cfg["OVERRIDE_DURATION_MIN"] = 30
    atomic_save_cfg(cfg)
    flash("OK Bright mode for 30 min")
    return redirect(url_for("home"))

@app.post("/action/clear-override")
def action_clear_override():
    """Clear any active override."""
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "OFF"
    cfg["OVERRIDE_DURATION_MIN"] = 0
    cfg["OVERRIDE_MESSAGE_TEXT"] = ""
    atomic_save_cfg(cfg)
    flash("OK Override cleared")
    return redirect(url_for("home"))

@app.post("/action/stop-service")
def action_stop_service():
    """Stop the LED ticker service."""
    try:
        if RESTART_CMD_ENV:
            # Can't stop with custom command
            flash(" Cannot stop - using custom restart command")
            return redirect(url_for("home"))
        cmd_parts = []
        if USE_SUDO_DEFAULT:
            cmd_parts.append("sudo")
        cmd_parts.extend(["systemctl", "stop", SYSTEMD_SERVICE])
        subprocess.run(cmd_parts, check=True, timeout=10)
        flash(f"OK Service {SYSTEMD_SERVICE} stopped")
    except Exception as e:
        flash(f" Stop failed: {e}")
    return redirect(url_for("home"))

@app.post("/action/dim-low")
def action_dim_low():
    """Set dimming to 30% (all-day window)."""
    cfg = load_cfg()
    cfg["DIM_WINDOWS"] = [{"start": "00:00", "end": "23:59", "pct": 30}]
    atomic_save_cfg(cfg)
    flash("OK Dimming set to 30%")
    return redirect(url_for("home"))

@app.post("/action/dim-medium")
def action_dim_medium():
    """Set dimming to 60% (all-day window)."""
    cfg = load_cfg()
    cfg["DIM_WINDOWS"] = [{"start": "00:00", "end": "23:59", "pct": 60}]
    atomic_save_cfg(cfg)
    flash("OK Dimming set to 60%")
    return redirect(url_for("home"))

@app.post("/action/dim-high")
def action_dim_high():
    """Clear dim schedule (100% brightness)."""
    cfg = load_cfg()
    cfg.pop("DIM_WINDOWS", None)
    atomic_save_cfg(cfg)
    flash("OK Dimming cleared (100% brightness)")
    return redirect(url_for("home"))

@app.post("/action/show-message")
def action_show_message():
    """Show a message immediately using override mode."""
    msg = request.form.get('message', '').strip()
    if not msg:
        flash(" No message provided")
        return redirect(url_for("home"))
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "MESSAGE"
    cfg["OVERRIDE_MESSAGE_TEXT"] = msg
    cfg["OVERRIDE_DURATION_MIN"] = 5
    atomic_save_cfg(cfg)
    flash(f"OK Message showing for 5 minutes")
    return redirect(url_for("home"))

@app.post("/action/scoreboard-mode")
def action_scoreboard_mode():
    """Force scoreboard view."""
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "SCOREBOARD"
    cfg["OVERRIDE_DURATION_MIN"] = 0  # Until cleared
    atomic_save_cfg(cfg)
    flash(" Scoreboard override active")
    return redirect(url_for("home"))

@app.post("/action/maint-mode")
def action_maint_mode():
    """Activate maintenance mode."""
    cfg = load_cfg()
    cfg["OVERRIDE_MODE"] = "MAINT"
    cfg["OVERRIDE_DURATION_MIN"] = 0  # Until cleared
    atomic_save_cfg(cfg)
    flash(" Maintenance mode active")
    return redirect(url_for("home"))

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", "5080"))
    app.run(host="0.0.0.0", port=port, debug=False)
