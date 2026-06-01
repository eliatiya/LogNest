#!/usr/bin/env python3
"""
LogNest Web UI — Production Ready
"""
import os, re, io, zipfile, html as _html, json as _json, time as _time
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, send_file, request, abort, jsonify, Response

app = Flask(__name__)

import logging
# Only log non-2xx responses
@app.after_request
def log_errors(response):
    if response.status_code >= 400:
        app.logger.warning(f"{request.method} {request.path} → {response.status_code}")
    return response

LOGS_DIR = Path(os.environ.get("LOGS_DIR", "/data/logs"))
ZIP_DIR  = Path(os.environ.get("ZIP_DIR",  "/data/logs_zip"))

# ------------------------------------------------------------------ helpers
_cache = {"runs": None, "runs_ts": 0, "zips": None, "zips_ts": 0}
CACHE_TTL = 60  # seconds

# Try to use SQLite index for instant queries
_use_index = False
try:
    import sys as _sys
    _sys.path.insert(0, "/scripts")
    from index_db import init_db, query_runs, query_run_count, query_files, query_stats, query_archives
    init_db()
    _use_index = True
except Exception:
    pass

def get_runs():
    if _use_index:
        try:
            rows = query_runs(limit=9999)
            return [r["name"] for r in rows]
        except Exception:
            pass
    # Fallback to NFS scan (cached)
    now = _time.time()
    if _cache["runs"] is not None and (now - _cache["runs_ts"]) < CACHE_TTL:
        return _cache["runs"]
    if not LOGS_DIR.exists():
        return []
    result = sorted([d.name for d in LOGS_DIR.iterdir() if d.is_dir()], reverse=True)
    _cache["runs"] = result
    _cache["runs_ts"] = now
    return result

def get_log_files(run=None):
    base = LOGS_DIR / run if run else LOGS_DIR
    if not base.exists():
        return []
    # Cache per-run file list for 60s
    cache_key = f"files_{run}"
    now = _time.time()
    if cache_key in _cache and (now - _cache.get(f"{cache_key}_ts", 0)) < CACHE_TTL:
        return _cache[cache_key]
    result = sorted(base.glob("*.log"), key=lambda p: p.name)
    _cache[cache_key] = result
    _cache[f"{cache_key}_ts"] = now
    return result

def get_zips():
    now = _time.time()
    if _cache["zips"] is not None and (now - _cache["zips_ts"]) < CACHE_TTL:
        return _cache["zips"]
    if not ZIP_DIR.exists():
        return []
    result = sorted(ZIP_DIR.glob("*.tar.gz"), key=lambda p: p.name, reverse=True)
    _cache["zips"] = result
    _cache["zips_ts"] = now
    return result

LEVEL_PATTERNS = {
    "error":   re.compile(r'\berror\b',      re.IGNORECASE),
    "warning": re.compile(r'\bwarn(ing)?\b', re.IGNORECASE),
    "debug":   re.compile(r'\bdebug\b',      re.IGNORECASE),
    "info":    re.compile(r'\binfo\b',       re.IGNORECASE),
}

def filter_lines(text, level):
    if not level or level == "all":
        return text
    pat = LEVEL_PATTERNS.get(level)
    if not pat:
        return text
    return "\n".join(line for line in text.splitlines() if pat.search(line))

def _human_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

# ------------------------------------------------------------------ stats
_stats_cache = {"data": None, "ts": 0}

def get_stats():
    now = _time.time()
    if _stats_cache["data"] and (now - _stats_cache["ts"]) < CACHE_TTL:
        return _stats_cache["data"]

    if _use_index:
        try:
            s = query_stats()
            result = {
                "runs": s["runs"],
                "files": s["files"],
                "zips": s["zips"],
                "storage": _human_size(s["storage_bytes"]),
                "last_run": s["last_run"],
            }
            _stats_cache["data"] = result
            _stats_cache["ts"] = now
            return result
        except Exception:
            pass

    # Fallback
    runs = get_runs()
    result = {
        "runs": len(runs),
        "files": 0,
        "zips": 0,
        "storage": "—",
        "last_run": runs[0] if runs else "Never",
    }
    _stats_cache["data"] = result
    _stats_cache["ts"] = now
    return result

# ------------------------------------------------------------------ HTML base
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LogNest{title_suffix}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234f8ef7' stroke-width='2'%3E%3Cpath d='M12 3C7 3 3 6 3 9c0 3 4 6 9 6s9-3 9-6c0-3-4-6-9-6z'/%3E%3Cpath d='M3 9v4c0 3 4 6 9 6s9-3 9-6V9'/%3E%3Cpath d='M3 13v4c0 3 4 6 9 6s9-3 9-6v-4'/%3E%3C/svg%3E"/>
<style>
:root{{
  --bg:        #0b0d14;
  --surface:   #13161f;
  --surface2:  #1a1e2b;
  --border:    #252836;
  --border2:   #2e3347;
  --accent:    #4f8ef7;
  --accent-h:  #3b7de8;
  --accent-dim:#1e3a6e;
  --text:      #d4d8e8;
  --text-dim:  #6b7280;
  --text-mute: #3d4255;
  --red:       #f87171;
  --red-bg:    #2d1515;
  --yellow:    #fbbf24;
  --yellow-bg: #2d2010;
  --green:     #34d399;
  --green-bg:  #0d2d20;
  --purple:    #a78bfa;
  --purple-bg: #1e1535;
  --radius:    6px;
  --radius-lg: 10px;
  --shadow:    0 4px 24px rgba(0,0,0,.4);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px;line-height:1.5}}

/* ── Animations ── */
@keyframes fadeInUp{{
  from{{opacity:0;transform:translateY(16px)}}
  to{{opacity:1;transform:translateY(0)}}
}}
@keyframes fadeIn{{
  from{{opacity:0}}
  to{{opacity:1}}
}}
@keyframes slideUp{{
  from{{transform:translateX(-50%) translateY(100px);opacity:0}}
  to{{transform:translateX(-50%) translateY(0);opacity:1}}
}}
@keyframes countUp{{
  from{{opacity:0;transform:translateY(8px)}}
  to{{opacity:1;transform:translateY(0)}}
}}
@keyframes shimmer{{
  0%{{background-position:-200% 0}}
  100%{{background-position:200% 0}}
}}
@keyframes toastIn{{
  from{{transform:translateY(80px) scale(.95);opacity:0}}
  to{{transform:translateY(0) scale(1);opacity:1}}
}}

/* ── Scrollbar ── */
::-webkit-scrollbar{{width:6px;height:6px}}
::-webkit-scrollbar-track{{background:var(--bg)}}
::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:3px}}
::-webkit-scrollbar-thumb:hover{{background:#3d4255}}

/* ── Header ── */
.header{{
  background:var(--surface);
  border-bottom:1px solid var(--border);
  padding:0 32px;
  display:flex;align-items:center;gap:0;
  height:56px;position:sticky;top:0;z-index:100;
  backdrop-filter:blur(12px);
  box-shadow:0 1px 0 var(--border),0 4px 20px rgba(0,0,0,.3);
}}
.header::after{{
  content:'';position:absolute;bottom:-1px;left:0;right:0;height:3px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
  opacity:.3;pointer-events:none;
}}
.logo{{
  display:flex;align-items:center;gap:10px;
  font-size:1.1rem;font-weight:700;color:var(--accent);
  letter-spacing:.5px;margin-right:32px;white-space:nowrap;
  text-decoration:none;
}}
.logo svg{{flex-shrink:0}}
.nav{{display:flex;height:100%;gap:0}}
.nav a{{
  display:flex;align-items:center;gap:7px;
  padding:0 20px;color:var(--text-dim);text-decoration:none;
  border-bottom:2px solid transparent;font-size:.88rem;font-weight:500;
  transition:color .2s,border-color .2s,background .2s;white-space:nowrap;
}}
.nav a:hover{{color:var(--text);background:rgba(255,255,255,.02)}}
.nav a.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.nav a svg{{opacity:.7}}
.nav a.active svg{{opacity:1}}
.header-right{{margin-left:auto;display:flex;align-items:center;gap:12px}}
.header-badge{{
  font-size:.72rem;background:var(--accent-dim);color:var(--accent);
  padding:3px 10px;border-radius:20px;font-weight:600;letter-spacing:.3px;
}}

/* ── Layout ── */
.page{{max-width:1280px;margin:0 auto;padding:28px 32px}}

/* ── Stats bar ── */
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.stat-card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:16px 20px;
  position:relative;overflow:hidden;
  transition:transform .2s ease,box-shadow .2s ease,border-color .3s ease;
  animation:fadeInUp .5s ease both;
}}
.stat-card:nth-child(1){{animation-delay:.05s}}
.stat-card:nth-child(2){{animation-delay:.1s}}
.stat-card:nth-child(3){{animation-delay:.15s}}
.stat-card:nth-child(4){{animation-delay:.2s}}
.stat-card:nth-child(5){{animation-delay:.25s}}
.stat-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),var(--purple),var(--accent));
  background-size:200% 100%;
  animation:shimmer 3s linear infinite;
  opacity:.7;
}}
.stat-card::after{{
  content:'';position:absolute;inset:0;border-radius:var(--radius-lg);
  background:radial-gradient(ellipse at top,rgba(79,142,247,.04),transparent 70%);
  pointer-events:none;
}}
.stat-card:hover{{
  transform:translateY(-2px);
  box-shadow:0 8px 24px rgba(79,142,247,.1),0 0 0 1px rgba(79,142,247,.15);
  border-color:rgba(79,142,247,.3);
}}
.stat-card .val{{
  font-size:1.6rem;font-weight:700;color:var(--accent);line-height:1;
  animation:countUp .6s ease both;
  animation-delay:.3s;
}}
.stat-card .lbl{{font-size:.72rem;color:var(--text-dim);margin-top:5px;text-transform:uppercase;letter-spacing:.5px}}
.stat-card .sub{{font-size:.75rem;color:var(--text-mute);margin-top:3px}}

/* ── Card ── */
.card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);margin-bottom:20px;overflow:hidden;
  transition:border-color .2s ease,box-shadow .2s ease;
  animation:fadeInUp .5s ease both;
  animation-delay:.1s;
}}
.card:hover{{
  border-color:var(--border2);
  box-shadow:0 4px 16px rgba(0,0,0,.2);
}}
.card-header{{
  padding:16px 20px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;gap:12px;
}}
.card-title{{font-size:.88rem;font-weight:600;color:var(--text);display:flex;align-items:center;gap:8px}}
.card-title svg{{color:var(--accent)}}
.card-body{{padding:20px}}

/* ── Form controls ── */
.controls{{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}}
.field{{display:flex;flex-direction:column;gap:5px;min-width:200px}}
.field label{{font-size:.75rem;font-weight:500;color:var(--text-dim);text-transform:uppercase;letter-spacing:.4px}}
select,.input{{
  background:var(--bg);color:var(--text);
  border:1px solid var(--border2);border-radius:var(--radius);
  padding:8px 12px;font-size:.88rem;font-family:inherit;
  transition:border-color .15s,box-shadow .15s,background .15s;cursor:pointer;
}}
select:focus,.input:focus{{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,142,247,.12)}}
.input{{cursor:text}}
.input::placeholder{{color:var(--text-mute)}}

/* ── Buttons ── */
.btn{{
  display:inline-flex;align-items:center;gap:6px;
  background:var(--accent);color:#fff;border:none;
  border-radius:var(--radius);padding:8px 16px;
  font-size:.83rem;font-weight:600;cursor:pointer;
  text-decoration:none;transition:background .15s,transform .1s,box-shadow .2s;
  white-space:nowrap;font-family:inherit;
}}
.btn:hover{{background:var(--accent-h);transform:translateY(-1px);box-shadow:0 4px 12px rgba(79,142,247,.25)}}
.btn:active{{transform:translateY(0);box-shadow:none}}
.btn-sm{{padding:5px 12px;font-size:.78rem}}
.btn-ghost{{background:transparent;color:var(--text-dim);border:1px solid var(--border2)}}
.btn-ghost:hover{{background:var(--surface2);color:var(--text);border-color:var(--border2);box-shadow:none}}
.btn-danger{{background:#7f1d1d;color:var(--red)}}
.btn-danger:hover{{background:#991b1b;box-shadow:0 4px 12px rgba(248,113,113,.15)}}

/* ── Log viewer ── */
.log-toolbar{{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:12px 16px;background:var(--bg);border-bottom:1px solid var(--border);
}}
.log-filename{{font-size:.78rem;color:var(--text-dim);font-family:monospace;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.log-counts{{display:flex;gap:6px;flex-shrink:0}}
.lc{{font-size:.72rem;padding:2px 8px;border-radius:4px;font-weight:600;cursor:pointer;border:1px solid transparent;transition:transform .15s,box-shadow .15s,background .15s}}
.lc-e{{background:var(--red-bg);color:var(--red);border-color:#7f1d1d}}
.lc-w{{background:var(--yellow-bg);color:var(--yellow);border-color:#78350f}}
.lc-i{{background:var(--green-bg);color:var(--green);border-color:#065f46}}
.lc-d{{background:var(--purple-bg);color:var(--purple);border-color:#4c1d95}}
.log-search-wrap{{display:flex;align-items:center;gap:6px}}
.log-search{{width:200px;padding:5px 10px;font-size:.8rem}}
pre#logview{{
  background:var(--bg);padding:16px;overflow:auto;
  max-height:560px;font-size:.78rem;line-height:1.8;
  white-space:pre-wrap;word-break:break-all;
  font-family:'JetBrains Mono','Fira Code','Cascadia Code',monospace;
  margin:0;border-radius:0;
}}
.log-line{{display:block;padding:0 4px;border-radius:3px;transition:background .1s}}
.log-line:hover{{background:var(--surface2)}}
.log-line.hl-search{{background:#2d2a00;outline:1px solid #fbbf2440}}
.log-error{{color:var(--red)}}
.log-warn {{color:var(--yellow)}}
.log-debug{{color:var(--purple)}}
.log-info {{color:var(--green)}}
.log-ts   {{color:var(--text-mute)}}
.log-hidden{{display:none}}

/* ── Table ── */
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:var(--bg)}}
th{{
  text-align:left;padding:10px 16px;
  font-size:.72rem;font-weight:600;color:var(--text-dim);
  text-transform:uppercase;letter-spacing:.5px;
  border-bottom:1px solid var(--border);white-space:nowrap;
}}
td{{
  padding:11px 16px;border-bottom:1px solid var(--border);
  font-size:.85rem;vertical-align:middle;transition:background .15s;
}}
tbody tr:hover td{{background:var(--surface2)}}
tbody tr:last-child td{{border-bottom:none}}
td.mono{{font-family:monospace;font-size:.8rem;color:#a0aec0}}

/* ── Badges ── */
.badge{{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:600;letter-spacing:.2px}}
.badge-ns{{background:var(--accent-dim);color:var(--accent)}}
.badge-error{{background:var(--red-bg);color:var(--red)}}
.badge-warn {{background:var(--yellow-bg);color:var(--yellow)}}
.badge-info {{background:var(--green-bg);color:var(--green)}}
.badge-debug{{background:var(--purple-bg);color:var(--purple)}}

/* ── Empty state ── */
.empty-state{{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:60px 20px;gap:12px;color:var(--text-mute);
  background:
    radial-gradient(ellipse at center,rgba(79,142,247,.03) 0%,transparent 70%),
    repeating-linear-gradient(0deg,transparent,transparent 40px,rgba(79,142,247,.015) 40px,rgba(79,142,247,.015) 41px),
    repeating-linear-gradient(90deg,transparent,transparent 40px,rgba(79,142,247,.015) 40px,rgba(79,142,247,.015) 41px);
  border-radius:var(--radius-lg);
  animation:fadeIn .6s ease both;
}}
.empty-state svg{{opacity:.3;transition:opacity .3s}}
.empty-state:hover svg{{opacity:.5}}
.empty-state p{{font-size:.88rem}}

/* ── Size pill ── */
.size{{font-size:.75rem;color:var(--text-dim);font-family:monospace;background:var(--surface2);padding:2px 7px;border-radius:4px}}

/* ── Checkbox ── */
.cb-wrap{{display:flex;align-items:center;justify-content:center}}
input[type=checkbox]{{
  width:16px;height:16px;cursor:pointer;accent-color:var(--accent);
  border-radius:3px;flex-shrink:0;
}}
tr.selected td{{background:rgba(79,142,247,.07)!important}}
tr.selected td:first-child{{border-left:2px solid var(--accent)}}

/* ── Selection bar ── */
#sel-bar{{
  position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(100px);
  background:var(--surface2);border:1px solid var(--accent);
  border-radius:40px;padding:10px 20px;
  display:flex;align-items:center;gap:16px;
  box-shadow:0 8px 32px rgba(0,0,0,.5),0 0 0 1px rgba(79,142,247,.2);
  transition:transform .3s cubic-bezier(.34,1.56,.64,1),opacity .25s;
  opacity:0;z-index:200;white-space:nowrap;
  backdrop-filter:blur(8px);
}}
#sel-bar.visible{{transform:translateX(-50%) translateY(0);opacity:1}}
#sel-bar .sel-count{{
  font-size:.85rem;font-weight:600;color:var(--accent);
  background:var(--accent-dim);padding:3px 10px;border-radius:20px;
}}
#sel-bar .sel-label{{font-size:.85rem;color:var(--text-dim)}}
#sel-bar .sep{{width:1px;height:20px;background:var(--border2)}}

/* ── Toast ── */
#toast{{
  position:fixed;bottom:24px;right:24px;
  background:var(--surface2);border:1px solid var(--border2);
  color:var(--text);padding:12px 20px 12px 16px;border-radius:var(--radius-lg);
  font-size:.85rem;box-shadow:0 8px 32px rgba(0,0,0,.4),0 0 0 1px rgba(255,255,255,.03);
  transform:translateY(80px) scale(.95);opacity:0;transition:.3s cubic-bezier(.34,1.56,.64,1);z-index:999;
  display:flex;align-items:center;gap:10px;
  backdrop-filter:blur(8px);
  max-width:360px;
}}
#toast.show{{transform:translateY(0) scale(1);opacity:1}}
#toast.success{{border-left:3px solid var(--green)}}
#toast.success::before{{content:'✓';font-weight:700;color:var(--green);font-size:1rem}}
#toast.error{{border-left:3px solid var(--red)}}
#toast.error::before{{content:'✕';font-weight:700;color:var(--red);font-size:1rem}}

/* ── Responsive ── */
@media(max-width:1024px){{
  .page{{max-width:100%;padding:24px}}
  .stats-grid{{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}}
}}
@media(max-width:768px){{
  .header{{padding:0 16px;height:50px}}
  .page{{padding:16px 12px}}
  .nav a span{{display:none}}
  .nav a{{padding:0 12px}}
  .stats-grid{{grid-template-columns:repeat(2,1fr);gap:8px}}
  .stat-card{{padding:12px 14px}}
  .stat-card .val{{font-size:1.3rem}}
  .controls{{flex-direction:column}}
  .field{{min-width:100%}}
  .card-header{{padding:12px 16px;flex-wrap:wrap}}
  .card-body{{padding:14px}}
  .log-toolbar{{flex-direction:column;align-items:stretch;gap:8px}}
  .log-search{{width:100%}}
  #sel-bar{{
    left:12px;right:12px;transform:translateX(0) translateY(100px);
    border-radius:16px;padding:10px 14px;gap:10px;
  }}
  #sel-bar.visible{{transform:translateX(0) translateY(0)}}
  #toast{{left:12px;right:12px;bottom:12px;max-width:none}}
  .header-badge{{display:none}}
}}
@media(max-width:480px){{
  .stats-grid{{grid-template-columns:1fr}}
  .nav a{{padding:0 8px}}
  .logo{{font-size:.95rem;margin-right:16px}}
  .logo svg{{width:18px;height:18px}}
}}

/* ── Search hint ── */
.search-wrap{{position:relative;display:inline-flex;align-items:center}}
.search-wrap .kbd-hint{{
  position:absolute;right:8px;top:50%;transform:translateY(-50%);
  font-size:.65rem;color:var(--text-mute);background:var(--surface2);
  padding:2px 6px;border-radius:3px;border:1px solid var(--border);
  pointer-events:none;font-family:monospace;opacity:.7;
  transition:opacity .2s;
}}
.search-wrap input:focus ~ .kbd-hint{{opacity:0}}

/* ── Page load animation ── */
.page{{animation:fadeIn .4s ease both}}
</style>
</head>
<body>

<header class="header">
  <a class="logo" href="/">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
      <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    LogNest
  </a>
  <nav class="nav">
    <a href="/" class="{a_dash}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
      <span>Dashboard</span>
    </a>
    <a href="/downloads" class="{a_dl}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      <span>Downloads</span>
    </a>
    <a href="/files" class="{a_files}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      <span>Files</span>
    </a>
    <a href="/collect" class="{a_collect}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      <span>On-Demand</span>
    </a>
    <a href="/search" class="{a_search}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <span>Search</span>
    </a>
  </nav>
  <div class="header-right">
    <span class="header-badge">RKE2</span>
  </div>
</header>

<div class="page">
{body}
</div>

<!-- ── Multi-select floating bar ── -->
<div id="sel-bar">
  <div style="display:flex;align-items:center;gap:8px">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
    <span class="sel-count" id="sel-count">0</span>
    <span class="sel-label" id="sel-label">items selected</span>
  </div>
  <span class="sep"></span>
  <button class="btn btn-sm" id="view-multi-btn" onclick="viewSelected()" style="display:none">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
    View Together
  </button>
  <button class="btn btn-ghost btn-sm" onclick="downloadSelected()">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    Download
  </button>
  <button class="btn btn-ghost btn-sm" onclick="clearAll()">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="6" x2="6" y2="18"/>
      <line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
    Clear
  </button>
</div>

<script>
var selectedItems = {{}};

function toast(msg, type) {{
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + (type || '');
  setTimeout(function() {{ t.className = ''; }}, 3000);
}}

/* ── Persist selection across page reloads via sessionStorage ── */
var STORE_KEY = 'lognest_sel';

function loadSelection() {{
  try {{
    var raw = sessionStorage.getItem(STORE_KEY);
    selectedItems = raw ? JSON.parse(raw) : {{}};
  }} catch(e) {{ selectedItems = {{}}; }}
}}

function saveSelection() {{
  try {{ sessionStorage.setItem(STORE_KEY, JSON.stringify(selectedItems)); }}
  catch(e) {{}}
}}

function restoreCheckboxes() {{
  document.querySelectorAll('.row-cb').forEach(function(cb) {{
    var key = cb.dataset.run + '|' + cb.dataset.file;
    if (selectedItems[key]) {{
      cb.checked = true;
      cb.closest('tr').classList.add('selected');
    }}
  }});
  syncHeaderCb();
  updateBar();
}}

function toggleRow(cb) {{
  var row = cb.closest('tr');
  var key = cb.dataset.run + '|' + cb.dataset.file;
  if (cb.checked) {{
    selectedItems[key] = {{ run: cb.dataset.run, file: cb.dataset.file, type: cb.dataset.type || 'log' }};
    row.classList.add('selected');
  }} else {{
    delete selectedItems[key];
    row.classList.remove('selected');
  }}
  saveSelection();
  syncHeaderCb();
  updateBar();
}}

function syncHeaderCb() {{
  var all = document.querySelectorAll('.row-cb');
  var hcb = document.getElementById('cb-all');
  if (!hcb || !all.length) return;
  var n = Array.from(all).filter(function(c) {{ return c.checked; }}).length;
  hcb.checked       = n === all.length;
  hcb.indeterminate = n > 0 && n < all.length;
}}

function toggleAll(masterCb) {{
  document.querySelectorAll('.row-cb').forEach(function(cb) {{
    cb.checked = masterCb.checked;
    var row = cb.closest('tr');
    var key = cb.dataset.run + '|' + cb.dataset.file;
    if (masterCb.checked) {{
      selectedItems[key] = {{ run: cb.dataset.run, file: cb.dataset.file, type: cb.dataset.type || 'log' }};
      row.classList.add('selected');
    }} else {{
      delete selectedItems[key];
      row.classList.remove('selected');
    }}
  }});
  saveSelection();
  updateBar();
}}

function selectAllVisible() {{
  var hcb = document.getElementById('cb-all');
  if (hcb) {{ hcb.checked = true; hcb.indeterminate = false; }}
  toggleAll({{ checked: true }});
}}

function deselectAll() {{
  selectedItems = {{}};
  saveSelection();
  document.querySelectorAll('.row-cb').forEach(function(cb) {{
    cb.checked = false;
    cb.closest('tr').classList.remove('selected');
  }});
  var hcb = document.getElementById('cb-all');
  if (hcb) {{ hcb.checked = false; hcb.indeterminate = false; }}
  updateBar();
}}

function clearAll() {{ deselectAll(); }}

function updateBar() {{
  var keys  = Object.keys(selectedItems);
  var count = keys.length;
  var bar   = document.getElementById('sel-bar');
  var cnt   = document.getElementById('sel-count');
  var lbl   = document.getElementById('sel-label');
  var viewBtn = document.getElementById('view-multi-btn');
  cnt.textContent = count;
  lbl.textContent = count === 1 ? 'item selected' : 'items selected';
  bar.classList.toggle('visible', count > 0);
  // Show "View Together" only when multiple log files are selected (not zips)
  var logCount = Object.keys(selectedItems).filter(function(k){{return selectedItems[k].type !== 'zip';}}).length;
  if (viewBtn) viewBtn.style.display = logCount >= 2 ? 'inline-flex' : 'none';
}}

function viewSelected() {{
  var keys = Object.keys(selectedItems).filter(function(k){{return selectedItems[k].type !== 'zip';}});
  if (keys.length < 2) return;
  var form = document.createElement('form');
  form.method = 'POST';
  form.action = '/view-multi';
  form.target = '_blank';
  keys.forEach(function(k) {{
    var item = selectedItems[k];
    var i1 = document.createElement('input');
    i1.type='hidden'; i1.name='run[]'; i1.value=item.run;
    var i2 = document.createElement('input');
    i2.type='hidden'; i2.name='file[]'; i2.value=item.file;
    form.appendChild(i1); form.appendChild(i2);
  }});
  document.body.appendChild(form);
  form.submit();
  document.body.removeChild(form);
}}

function downloadSelected() {{
  var keys = Object.keys(selectedItems);
  if (!keys.length) return;

  var logs = keys.filter(function(k) {{ return selectedItems[k].type !== 'zip'; }});
  var zips = keys.filter(function(k) {{ return selectedItems[k].type === 'zip'; }});

  zips.forEach(function(k) {{
    var a = document.createElement('a');
    a.href = '/download/zip/' + encodeURIComponent(selectedItems[k].file);
    a.download = selectedItems[k].file;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }});

  if (logs.length === 1) {{
    var item = selectedItems[logs[0]];
    var a = document.createElement('a');
    a.href = '/download/log/' + encodeURIComponent(item.run) + '/' + encodeURIComponent(item.file);
    a.download = item.file;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }} else if (logs.length > 1) {{
    var form = document.createElement('form');
    form.method = 'POST'; form.action = '/download/multi';
    logs.forEach(function(k) {{
      var item = selectedItems[k];
      var i1 = document.createElement('input');
      i1.type='hidden'; i1.name='run[]'; i1.value=item.run;
      var i2 = document.createElement('input');
      i2.type='hidden'; i2.name='file[]'; i2.value=item.file;
      form.appendChild(i1); form.appendChild(i2);
    }});
    document.body.appendChild(form); form.submit(); document.body.removeChild(form);
  }}

  toast('Downloading ' + keys.length + ' item' + (keys.length > 1 ? 's' : '') + '...', 'success');
}}

/* ── Init on page load ── */
document.addEventListener('DOMContentLoaded', function() {{
  loadSelection();
  restoreCheckboxes();

  /* Ctrl+K keyboard shortcut to focus search */
  document.addEventListener('keydown', function(e) {{
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {{
      e.preventDefault();
      var s = document.getElementById('log-search-input');
      if (s) {{ s.focus(); s.select(); }}
    }}
  }});
}});
</script>
<div id="toast"></div>
</body></html>"""

# ------------------------------------------------------------------ page renderer
def render_page(tab, body, title_suffix=""):
    a = lambda t: "active" if tab == t else ""
    return PAGE.format(
        title_suffix=f" — {title_suffix}" if title_suffix else "",
        a_dash=a("dashboard"), a_dl=a("downloads"),
        a_files=a("files"), a_collect=a("collect"),
        a_search=a("search"),
        body=body
    )

# ------------------------------------------------------------------ routes
@app.route("/")
def dashboard():
    runs      = get_runs()
    sel_run   = request.args.get("run", "")
    sel_pod   = request.args.get("pod", "")
    level     = request.args.get("level", "all")
    search    = request.args.get("q", "")
    stats     = get_stats()
    log_files = []
    log_content = None
    error_count = warn_count = info_count = debug_count = 0

    if sel_run:
        log_files = get_log_files(sel_run)
        if sel_pod:
            target = LOGS_DIR / sel_run / sel_pod
            if target.exists():
                # Always read the full file
                raw = target.read_text(errors='replace')
                lines = raw.splitlines()

                # Quick level counts
                for line in lines[:5000]:
                    ll = line.lower()
                    if 'error' in ll: error_count += 1
                    elif 'warn' in ll: warn_count += 1
                    elif 'info' in ll: info_count += 1
                    elif 'debug' in ll: debug_count += 1

                # Apply filters
                if level and level != "all":
                    pat = LEVEL_PATTERNS.get(level)
                    if pat:
                        lines = [l for l in lines if pat.search(l)]
                if search:
                    sl = search.lower()
                    lines = [l for l in lines if sl in l.lower()]

                log_content = "\n".join(lines)
            else:
                abort(404)

    # stats bar
    stats_html = f"""
    <div class="stats-grid">
      <div class="stat-card"><div class="val">{stats['runs']}</div><div class="lbl">Collection Runs</div></div>
      <div class="stat-card"><div class="val">{stats['files']}</div><div class="lbl">Log Files</div></div>
      <div class="stat-card"><div class="val">{stats['zips']}</div><div class="lbl">Archives</div></div>
      <div class="stat-card"><div class="val">{stats['storage']}</div><div class="lbl">Storage Used</div></div>
      <div class="stat-card"><div class="val" style="font-size:1rem">{stats['last_run']}</div><div class="lbl">Last Run</div></div>
    </div>"""

    # run selector — always show all runs (SQLite makes this instant)
    run_opts = "".join(
        f'<option value="{r}" {"selected" if r==sel_run else ""}>{r}</option>'
        for r in runs
    )

    # pod selector — filter by namespace if selected
    sel_ns = request.args.get("ns", "")
    
    # Get unique namespaces from this run's files
    ns_in_run = sorted(set(
        f.name.split("__")[0] for f in log_files if "__" in f.name
    )) if log_files else []
    
    # Filter pods by namespace
    filtered_log_files = log_files
    if sel_ns and log_files:
        filtered_log_files = [f for f in log_files if f.name.startswith(sel_ns + "__")]
    
    pod_opts = "".join(
        f'<option value="{f.name}" {"selected" if f.name==sel_pod else ""}>'
        f'{f.name.replace(".log","")}</option>'
        for f in filtered_log_files
    ) if sel_run else ""

    ns_opts_dash = "".join(
        f'<option value="{_html.escape(n)}" {"selected" if n==sel_ns else ""}>{_html.escape(n)}</option>'
        for n in ns_in_run
    )

    level_opts = "".join(
        f'<option value="{v}" {"selected" if v==level else ""}>{l}</option>'
        for v, l in [("all","All Levels"),("error","Errors"),
                     ("warning","Warnings"),("info","Info"),("debug","Debug")]
    )

    ns_field = f"""
      <div class="field" style="min-width:150px">
        <label>Namespace</label>
        <select name="ns" onchange="this.form.submit()">
          <option value="">All</option>{ns_opts_dash}
        </select>
      </div>""" if sel_run and ns_in_run else ""

    pod_field = f"""
      {ns_field}
      <div class="field" style="flex:1;min-width:250px">
        <label>Pod / Container</label>
        <select name="pod" id="pod-sel" onchange="this.form.submit()">
          <option value="">— Select pod —</option>{pod_opts}
        </select>
      </div>
      <div class="field" style="min-width:120px">
        <label>Level</label>
        <select name="level" onchange="this.form.submit()">{level_opts}</select>
      </div>""" if sel_run else ""

    controls = f"""
    <div class="card">
      <div class="card-body">
        <form method="get" action="/" id="filter-form">
          <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end">
            <div class="field" style="min-width:200px">
              <label>Collection Run</label>
              <select name="run" id="run-sel"
                onchange="
                  var podSel=document.getElementById('pod-sel');
                  if(podSel){{podSel.value='';}}
                  this.form.submit();
                ">
                <option value="">— Select run —</option>{run_opts}
              </select>
            </div>
            {pod_field}
            {"<input type='hidden' name='q' value='" + _html.escape(search) + "'/>" if search else ""}
          </div>
        </form>
      </div>
    </div>"""

    # log viewer
    if log_content is not None:
        lines = log_content.splitlines()
        line_count = len(lines)
        # Send raw escaped text — coloring done client-side for speed
        log_html = _html.escape(log_content)

        viewer = f"""
        <div class="card">
          <div class="log-toolbar">
            <span class="log-filename">{_html.escape(sel_pod.replace('.log',''))}</span>
            <div class="log-counts">
              <span class="lc lc-e" title="Errors">{error_count} ERR</span>
              <span class="lc lc-w" title="Warnings">{warn_count} WARN</span>
              <span class="lc lc-i" title="Info">{info_count} INFO</span>
              <span class="lc lc-d" title="Debug">{debug_count} DBG</span>
            </div>
            <div class="log-search-wrap">
              <form method="get" action="/" style="display:flex;gap:6px">
                <input type="hidden" name="run" value="{_html.escape(sel_run)}"/>
                <input type="hidden" name="pod" value="{_html.escape(sel_pod)}"/>
                <input type="hidden" name="level" value="{_html.escape(level)}"/>
                <span class="search-wrap"><input class="input log-search" name="q" placeholder="Search logs..." value="{_html.escape(search)}" type="text" id="log-search-input"/><span class="kbd-hint">Ctrl+K</span></span>
                <button class="btn btn-sm" type="submit">Search</button>
                {"<a class='btn btn-ghost btn-sm' href='/?run=" + _html.escape(sel_run) + "&pod=" + _html.escape(sel_pod) + "&level=" + level + "'>Clear</a>" if search else ""}
              </form>
            </div>
            <a class="btn btn-ghost btn-sm" href="/download/log/{_html.escape(sel_run)}/{_html.escape(sel_pod)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download
            </a>
          </div>
          <pre id="logview">{log_html}</pre>
          <script>
          (function(){{
            var pre=document.getElementById('logview');
            var lines=pre.innerHTML.split('\\n');
            var out=[];
            for(var i=0;i<lines.length;i++){{
              var l=lines[i],cls='log-ts',lo=l.toLowerCase();
              if(/\\berror\\b/.test(lo))cls='log-error';
              else if(/\\bwarn/.test(lo))cls='log-warn';
              else if(/\\bdebug\\b/.test(lo))cls='log-debug';
              else if(/\\binfo\\b/.test(lo))cls='log-info';
              out.push('<span class="log-line '+cls+'">'+l+'</span>');
            }}
            pre.innerHTML=out.join('\\n');
          }})();
          </script>
          <div style="padding:8px 16px;background:var(--bg);border-top:1px solid var(--border);font-size:.72rem;color:var(--text-mute);display:flex;justify-content:space-between">
            <span>{line_count:,} lines shown</span>
            <span>{"Filtered by: " + level if level != "all" else "All levels"}{" · Search: " + _html.escape(search) if search else ""}</span>
          </div>
        </div>"""
    elif sel_run and sel_pod:
        viewer = '<div class="empty-state"><p>No log content found.</p></div>'
    elif sel_run:
        viewer = '<div class="empty-state"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><p>Select a pod to view its logs</p></div>'
    else:
        viewer = '<div class="empty-state"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg><p>Select a collection run to get started</p></div>'

    body = stats_html + controls + viewer
    return render_page("dashboard", body, "Dashboard")


@app.route("/downloads")
def downloads():
    zips = list(get_zips())

    if zips:
        rows = ""
        for z in zips:
            sz   = _human_size(z.stat().st_size)
            name = z.name
            fn   = _html.escape(name)
            try:
                ts   = name.replace("lognest_","").replace(".tar.gz","")
                dt   = datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S")
                date = dt.strftime("%b %d, %Y  %H:%M")
            except Exception:
                date = "—"
            rows += f"""<tr>
              <td class="cb-wrap">
                <input type="checkbox" class="row-cb"
                       data-run="" data-file="{fn}" data-type="zip"
                       onchange="toggleRow(this)"/>
              </td>
              <td class="mono">{fn}</td>
              <td>{date}</td>
              <td><span class="size">{sz}</span></td>
              <td>
                <a class="btn btn-sm" href="/download/zip/{fn}">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                  Download
                </a>
              </td>
            </tr>"""
        table = f"""
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th style="width:40px">
                  <input type="checkbox" id="cb-all" onchange="toggleAll(this)" title="Select all"/>
                </th>
                <th>Archive</th><th>Date</th><th>Size</th><th>Action</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""
    else:
        table = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          <p>No archives yet — they are created after each collection run</p>
        </div>"""

    select_all_btn = '<button class="btn btn-ghost btn-sm" onclick="selectAllVisible()">Select All</button><button class="btn btn-ghost btn-sm" onclick="deselectAll()" style="margin-left:6px">Deselect All</button>' if zips else ""
    body = f"""
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Compressed Archives
        </span>
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-size:.75rem;color:var(--text-dim)">{len(zips)} archive{"s" if len(zips)!=1 else ""}</span>
          {select_all_btn}
        </div>
      </div>
      {table}
    </div>"""
    return render_page("downloads", body, "Downloads")


@app.route("/files")
def files():
    runs    = get_runs()
    sel_run = request.args.get("run", "")
    search  = request.args.get("q", "")
    sel_ns  = request.args.get("ns", "")

    run_opts = "".join(
        f'<option value="{r}" {"selected" if r==sel_run else ""}>{r}</option>'
        for r in runs
    )

    # Get namespaces for this run
    ns_in_run = []
    if sel_run:
        raw_files = get_log_files(sel_run)
        ns_in_run = sorted(set(
            f.name.split("__")[0] for f in raw_files if "__" in f.name
        ))

    ns_opts_files = "".join(
        f'<option value="{_html.escape(n)}" {"selected" if n==sel_ns else ""}>{_html.escape(n)}</option>'
        for n in ns_in_run
    )

    ns_field = f"""
            <div class="field" style="min-width:150px">
              <label>Namespace</label>
              <select name="ns" onchange="this.form.submit()">
                <option value="">All</option>{ns_opts_files}
              </select>
            </div>""" if ns_in_run else ""

    controls = f"""
    <div class="card">
      <div class="card-body">
        <form method="get" action="/files">
          <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end">
            <div class="field" style="min-width:200px">
              <label>Collection Run</label>
              <select name="run" onchange="this.form.submit()">
                <option value="">— Select run —</option>{run_opts}
              </select>
            </div>
            {ns_field}
            <div class="field" style="flex:1;min-width:150px">
              <label>Search filename</label>
              <input class="input" name="q" placeholder="e.g. coredns, worker..."
                     value="{_html.escape(search)}" type="text"/>
            </div>
            <div class="field" style="min-width:auto">
              <label>&nbsp;</label>
              <button class="btn" type="submit">Filter</button>
            </div>
          </div>
        </form>
      </div>
    </div>"""

    table_block = ""
    if sel_run:
        class FileInfo:
            def __init__(self, path):
                self.name = path.name
                self.size = _human_size(path.stat().st_size)
                parts = path.stem.split("__")
                self.ns        = parts[0] if len(parts) > 0 else "—"
                self.pod       = parts[1] if len(parts) > 1 else "—"
                self.container = parts[2] if len(parts) > 2 else "—"

        all_files = [FileInfo(f) for f in get_log_files(sel_run)]
        if sel_ns:
            all_files = [f for f in all_files if f.ns == sel_ns]
        if search:
            all_files = [f for f in all_files if search.lower() in f.name.lower()]

        if all_files:
            rows = ""
            for f in all_files:
                r = _html.escape(sel_run)
                fn = _html.escape(f.name)
                rows += f"""<tr>
                  <td class="cb-wrap">
                    <input type="checkbox" class="row-cb"
                           data-run="{r}" data-file="{fn}" data-type="log"
                           onchange="toggleRow(this)"/>
                  </td>
                  <td><span class="badge badge-ns">{_html.escape(f.ns)}</span></td>
                  <td class="mono">{_html.escape(f.pod)}</td>
                  <td class="mono">{_html.escape(f.container)}</td>
                  <td><span class="size">{f.size}</span></td>
                  <td>
                    <div style="display:flex;gap:6px">
                      <a class="btn btn-sm"
                         href="/download/log/{r}/{fn}">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2.5">
                          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                          <polyline points="7 10 12 15 17 10"/>
                          <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                        Download
                      </a>
                      <a class="btn btn-ghost btn-sm"
                         href="/?run={r}&pod={fn}">View</a>
                    </div>
                  </td>
                </tr>"""

            table_block = f"""
            <div class="card">
              <div class="card-header">
                <span class="card-title">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                  </svg>
                  {_html.escape(sel_run)}
                </span>
                <div style="display:flex;align-items:center;gap:12px">
                  <span style="font-size:.75rem;color:var(--text-dim)">
                    {len(all_files)} file{"s" if len(all_files)!=1 else ""}
                  </span>
                  <button class="btn btn-ghost btn-sm" type="button"
                          onclick="var cb=document.getElementById('cb-all');cb.checked=true;toggleAll(cb);">Select All</button>
                  <button class="btn btn-ghost btn-sm" type="button"
                          onclick="deselectAll()">Deselect All</button>
                </div>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style="width:40px">
                        <input type="checkbox" id="cb-all"
                               onchange="toggleAll(this)"
                               title="Select all"/>
                      </th>
                      <th>Namespace</th>
                      <th>Pod</th>
                      <th>Container</th>
                      <th>Size</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </div>"""
        else:
            table_block = '<div class="empty-state"><p>No files match your search.</p></div>'
    else:
        table_block = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <p>Select a run to browse individual log files</p>
        </div>"""

    return render_page("files", controls + table_block, "Files")


# ------------------------------------------------------------------ multi-download
@app.route("/download/multi", methods=["POST"])
def download_multi():
    runs  = request.form.getlist("run[]")
    files = request.form.getlist("file[]")

    if not runs or not files or len(runs) != len(files):
        abort(400)

    # Build zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for run, filename in zip(runs, files):
            # Sanitize — no path traversal
            run      = Path(run).name
            filename = Path(filename).name
            path     = LOGS_DIR / run / filename
            if path.exists() and path.is_file():
                # Store as run/filename inside the zip
                zf.write(path, arcname=f"{run}/{filename}")

    buf.seek(0)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="lognest-selection-{ts}.zip"',
            "Content-Length": str(buf.getbuffer().nbytes),
        }
    )


# ------------------------------------------------------------------ API
@app.route("/healthz")
def healthz():
    return "ok"

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


# ------------------------------------------------------------------ downloads
@app.route("/download/zip/<filename>")
def download_zip(filename):
    path = ZIP_DIR / filename
    if not path.exists() or not path.is_file():
        abort(404)
    return send_file(str(path), as_attachment=True, download_name=filename)


@app.route("/download/log/<run>/<filename>")
def download_log(run, filename):
    path = LOGS_DIR / run / filename
    if not path.exists() or not path.is_file():
        abort(404)
    return send_file(str(path), as_attachment=True, download_name=filename)


# ------------------------------------------------------------------ search across runs
@app.route("/search")
def search_page():
    pod_query = request.args.get("pod", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to", "").strip()

    # Get unique namespaces for dropdown
    ns_list = []
    if _use_index:
        try:
            from index_db import get_db
            db = get_db()
            ns_rows = db.execute("SELECT DISTINCT namespace FROM log_files WHERE namespace != '' ORDER BY namespace").fetchall()
            ns_list = [r[0] for r in ns_rows]
            db.close()
        except Exception:
            pass

    sel_ns = request.args.get("ns", "").strip()

    results = []
    if pod_query or sel_ns:
        # Query SQLite for matching files across all runs
        if _use_index:
            try:
                from index_db import get_db
                db = get_db()
                query = """
                    SELECT r.name as run_name, f.filename, f.namespace, f.pod, 
                           f.container, f.size_bytes, f.line_count,
                           f.error_count, f.warn_count, f.info_count, f.debug_count
                    FROM log_files f
                    JOIN runs r ON f.run_id = r.id
                    WHERE 1=1
                """
                params = []

                if pod_query:
                    query += " AND (f.pod LIKE ? OR f.namespace LIKE ? OR f.filename LIKE ?)"
                    params.extend([f"%{pod_query}%", f"%{pod_query}%", f"%{pod_query}%"])

                if sel_ns:
                    query += " AND f.namespace = ?"
                    params.append(sel_ns)

                if date_from:
                    query += " AND r.name >= ?"
                    params.append(date_from)
                if date_to:
                    query += " AND r.name <= ?"
                    params.append(date_to + "_99-99-99")

                query += " ORDER BY r.name DESC, f.filename LIMIT 500"
                rows = db.execute(query, params).fetchall()
                results = [dict(r) for r in rows]
                db.close()
            except Exception as e:
                results = []
        else:
            # Fallback: scan NFS (slow)
            runs = get_runs()
            if date_from:
                runs = [r for r in runs if r >= date_from]
            if date_to:
                runs = [r for r in runs if r <= date_to + "_99-99-99"]
            for run in runs[:30]:
                run_dir = LOGS_DIR / run
                if run_dir.is_dir():
                    for f in run_dir.glob("*.log"):
                        if (not pod_query or pod_query.lower() in f.name.lower()) and \
                           (not sel_ns or f.stem.split("__")[0] == sel_ns):
                            results.append({
                                "run_name": run,
                                "filename": f.name,
                                "namespace": f.stem.split("__")[0] if "__" in f.stem else "",
                                "pod": f.stem.split("__")[1] if len(f.stem.split("__")) > 1 else "",
                                "container": f.stem.split("__")[2] if len(f.stem.split("__")) > 2 else "",
                                "size_bytes": f.stat().st_size,
                                "line_count": 0,
                                "error_count": 0, "warn_count": 0,
                                "info_count": 0, "debug_count": 0,
                            })

    # Build namespace options
    ns_opts = "".join(
        f'<option value="{_html.escape(n)}" {"selected" if n==sel_ns else ""}>{_html.escape(n)}</option>'
        for n in ns_list
    )

    controls = f"""
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          Search Across All Runs
        </span>
      </div>
      <div class="card-body">
        <form method="get" action="/search">
          <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end">
            <div class="field" style="flex:1;min-width:180px">
              <label>Pod / Container</label>
              <input class="input" name="pod" placeholder="e.g. api, nginx, worker..."
                     value="{_html.escape(pod_query)}" type="text"/>
            </div>
            <div class="field" style="min-width:160px">
              <label>Namespace</label>
              <select name="ns">
                <option value="">All namespaces</option>
                {ns_opts}
              </select>
            </div>
            <div class="field" style="min-width:140px">
              <label>From date</label>
              <input class="input" name="from" placeholder="2026-05-01"
                     value="{_html.escape(date_from)}" type="text"/>
            </div>
            <div class="field" style="min-width:140px">
              <label>To date</label>
              <input class="input" name="to" placeholder="2026-05-31"
                     value="{_html.escape(date_to)}" type="text"/>
            </div>
            <div class="field" style="min-width:auto">
              <label>&nbsp;</label>
              <button class="btn" type="submit">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                Search
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>"""

    if (pod_query or sel_ns) and results:
        rows_html = ""
        for r in results:
            sz = _human_size(r["size_bytes"])
            run = _html.escape(r["run_name"])
            fn  = _html.escape(r["filename"])
            ns  = _html.escape(r.get("namespace", ""))
            pod = _html.escape(r.get("pod", ""))
            ctr = _html.escape(r.get("container", ""))
            err = r.get("error_count", 0)
            wrn = r.get("warn_count", 0)

            level_badges = ""
            if err > 0:
                level_badges += f'<span class="badge badge-error">{err} err</span> '
            if wrn > 0:
                level_badges += f'<span class="badge badge-warn">{wrn} warn</span>'

            rows_html += f"""<tr>
              <td class="cb-wrap">
                <input type="checkbox" class="row-cb"
                       data-run="{run}" data-file="{fn}" data-type="log"
                       onchange="toggleRow(this)"/>
              </td>
              <td style="font-size:.78rem;color:var(--text-dim);font-family:monospace">{run}</td>
              <td><span class="badge badge-ns">{ns}</span></td>
              <td class="mono">{pod}</td>
              <td class="mono">{ctr}</td>
              <td><span class="size">{sz}</span></td>
              <td>{level_badges}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <a class="btn btn-sm" href="/?run={run}&pod={fn}">View</a>
                  <a class="btn btn-ghost btn-sm" href="/download/log/{run}/{fn}">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                  </a>
                </div>
              </td>
            </tr>"""

        table = f"""
        <div class="card">
          <div class="card-header">
            <span class="card-title">Results</span>
            <div style="display:flex;align-items:center;gap:12px">
              <span style="font-size:.75rem;color:var(--text-dim)">{len(results)} file{"s" if len(results)!=1 else ""} found</span>
              <button class="btn btn-ghost btn-sm" type="button"
                onclick="var cb=document.getElementById('cb-all');cb.checked=true;toggleAll(cb);">Select All</button>
              <button class="btn btn-ghost btn-sm" type="button"
                onclick="deselectAll()">Deselect All</button>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style="width:40px"><input type="checkbox" id="cb-all" onchange="toggleAll(this)"/></th>
                  <th onclick="sortTable(1)" style="cursor:pointer">Run ⇅</th>
                  <th onclick="sortTable(2)" style="cursor:pointer">Namespace ⇅</th>
                  <th onclick="sortTable(3)" style="cursor:pointer">Pod ⇅</th>
                  <th onclick="sortTable(4)" style="cursor:pointer">Container ⇅</th>
                  <th onclick="sortTable(5)" style="cursor:pointer">Size ⇅</th>
                  <th onclick="sortTable(6)" style="cursor:pointer">Levels ⇅</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
          </div>
        </div>
        <script>
        var sortDir={{}};
        function sortTable(col){{
          var table=document.querySelector('.table-wrap table');
          var tbody=table.querySelector('tbody');
          var rows=Array.from(tbody.querySelectorAll('tr'));
          sortDir[col]=!sortDir[col];
          rows.sort(function(a,b){{
            var aVal=a.cells[col]?a.cells[col].textContent.trim():'';
            var bVal=b.cells[col]?b.cells[col].textContent.trim():'';
            // Try numeric sort for size/levels columns
            var aNum=parseFloat(aVal.replace(/[^0-9.]/g,''));
            var bNum=parseFloat(bVal.replace(/[^0-9.]/g,''));
            if(!isNaN(aNum)&&!isNaN(bNum)){{
              return sortDir[col]?aNum-bNum:bNum-aNum;
            }}
            return sortDir[col]?aVal.localeCompare(bVal):bVal.localeCompare(aVal);
          }});
          rows.forEach(function(r){{tbody.appendChild(r);}});
        }}
        </script>"""
    elif pod_query or sel_ns:
        table = '<div class="empty-state"><p>No files match your search.</p></div>'
    else:
        table = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <p>Search for a pod, namespace, or container name across all collection runs</p>
        </div>"""

    return render_page("search", controls + table, "Search")


# ------------------------------------------------------------------ view-multi
@app.route("/view-multi", methods=["POST"])
def view_multi():
    runs  = request.form.getlist("run[]")
    files = request.form.getlist("file[]")

    if not runs or len(runs) != len(files):
        abort(400)

    # Color palette for different pods
    POD_COLORS = [
        "#4f8ef7", "#34d399", "#fbbf24", "#f87171",
        "#a78bfa", "#fb923c", "#38bdf8", "#f472b6",
        "#86efac", "#fde68a",
    ]

    # Read and tag each line with its source
    all_lines = []
    sources = []
    for i, (run, filename) in enumerate(zip(runs, files)):
        run      = Path(run).name
        filename = Path(filename).name
        path     = LOGS_DIR / run / filename
        if not path.exists():
            continue
        color = POD_COLORS[i % len(POD_COLORS)]
        label = filename.replace(".log", "").split("__")
        short = f"{label[1]}/{label[2]}" if len(label) >= 3 else filename
        sources.append({"label": short, "color": color, "file": filename, "run": run})

        try:
            content = path.read_text(errors="replace")
            lines = content.splitlines()
            # Limit to last 1000 lines per file for speed
            if len(lines) > 1000:
                lines = lines[-1000:]
            for line in lines:
                all_lines.append((line, i, short, color))
        except Exception:
            continue

    # Sort by timestamp prefix (ISO format at start of line)
    def extract_ts(line_tuple):
        line = line_tuple[0]
        # Try to extract timestamp from start of line
        parts = line.split(" ", 1)
        if parts and len(parts[0]) >= 10:
            return parts[0]
        return ""

    all_lines.sort(key=extract_ts)

    # Build legend
    legend_html = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;font-size:.78rem">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{s["color"]};flex-shrink:0"></span>'
        f'{_html.escape(s["label"])}</span>'
        for s in sources
    )

    # Build merged log HTML
    log_lines_html = ""
    for line, src_idx, label, color in all_lines:
        esc = _html.escape(line)
        ll = line.lower()
        if 'error' in ll:   level_cls = "log-error"
        elif 'warn' in ll:  level_cls = "log-warn"
        elif 'debug' in ll: level_cls = "log-debug"
        elif 'info' in ll:  level_cls = "log-info"
        else:               level_cls = "log-ts"

        log_lines_html += (
            f'<span class="log-line {level_cls}" style="border-left:2px solid {color};padding-left:6px">'
            f'<span style="color:{color};font-size:.7rem;margin-right:6px;opacity:.8">[{_html.escape(label)}]</span>'
            f'{esc}</span>\n'
        )

    body = f"""
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          Multi-Pod View — {len(all_lines):,} lines from {len(sources)} sources
        </span>
        <div style="display:flex;gap:8px;align-items:center">
          <span style="font-size:.75rem;color:var(--text-dim)">sorted by timestamp</span>
        </div>
      </div>
      <div style="padding:12px 16px;background:var(--bg);border-bottom:1px solid var(--border);display:flex;flex-wrap:wrap;gap:4px">
        {legend_html}
      </div>
      <div style="padding:8px 16px;background:var(--bg);border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center">
        <input class="input" id="mp-search" placeholder="Search across all pods..." type="text"
               style="flex:1;max-width:400px;padding:5px 10px;font-size:.8rem"
               oninput="filterMulti(this.value)"/>
        <span id="mp-count" style="font-size:.75rem;color:var(--text-dim)">{len(all_lines):,} lines</span>
      </div>
      <pre id="mp-log" style="background:var(--bg);padding:16px;overflow:auto;max-height:75vh;
           font-size:.78rem;line-height:1.8;white-space:pre-wrap;word-break:break-all;
           font-family:'JetBrains Mono','Fira Code',monospace;margin:0">{log_lines_html}</pre>
    </div>
    <script>
    function filterMulti(q) {{
      var lines = document.querySelectorAll('#mp-log .log-line');
      var count = 0;
      var ql = q.toLowerCase();
      lines.forEach(function(l) {{
        var show = !ql || l.textContent.toLowerCase().includes(ql);
        l.style.display = show ? 'block' : 'none';
        if (show) count++;
      }});
      document.getElementById('mp-count').textContent = count.toLocaleString() + ' lines';
    }}
    </script>"""

    return render_page("search", body, "Multi-Pod View")


# ------------------------------------------------------------------ on-demand collect
K8S_NAMESPACE   = os.environ.get("POD_NAMESPACE", "lognest")
ONDEMAND_LOG    = Path(os.environ.get("LOGS_DIR", "/data/logs")) / ".ondemand_runs.json"
COLLECTOR_IMAGE = os.environ.get("COLLECTOR_IMAGE", "alpine/k8s:1.30.2")
COLLECTOR_SA    = os.environ.get("COLLECTOR_SA", "lognest")
COLLECTOR_CM    = os.environ.get("COLLECTOR_CM", "lognest-collector-script")
PVC_NAME        = os.environ.get("PVC_NAME", "pvc-lognest")

def load_ondemand_runs():
    try:
        if ONDEMAND_LOG.exists():
            return _json.loads(ONDEMAND_LOG.read_text())
    except Exception:
        pass
    return []

def save_ondemand_run(entry):
    runs = load_ondemand_runs()
    runs.insert(0, entry)
    runs = runs[:50]  # keep last 50
    try:
        ONDEMAND_LOG.write_text(_json.dumps(runs))
    except Exception:
        pass

@app.route("/collect")
def collect_page():
    runs = load_ondemand_runs()

    if runs:
        rows = ""
        for r in runs:
            status     = r.get("status", "unknown")
            triggered  = r.get("triggered", "—")
            job_name   = r.get("job", "—")
            note       = r.get("note", "")
            status_cls = {"running": "badge-info", "completed": "badge-info",
                          "failed": "badge-error", "triggered": "badge-warn"}.get(status, "badge-debug")
            rows += f"""<tr>
              <td class="mono">{_html.escape(triggered)}</td>
              <td><span class="badge {status_cls}">{_html.escape(status)}</span></td>
              <td class="mono">{_html.escape(job_name)}</td>
              <td style="color:var(--text-dim);font-size:.8rem">{_html.escape(note)}</td>
            </tr>"""
        table = f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>Triggered At</th><th>Status</th><th>Job Name</th><th>Note</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""
    else:
        table = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          <p>No on-demand runs yet — trigger one below</p>
        </div>"""

    body = f"""
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          On-Demand Log Collection
        </span>
      </div>
      <div class="card-body">
        <p style="color:var(--text-dim);font-size:.88rem;margin-bottom:20px;line-height:1.7">
          Trigger an immediate log collection run outside the regular schedule.<br>
          This creates a Kubernetes Job that collects logs from all pods across all namespaces,
          including <strong style="color:var(--text)">previous container logs</strong> to capture
          rotated log files that <code style="background:var(--surface2);padding:1px 5px;border-radius:3px">kubectl logs</code> would otherwise miss.
        </p>
        <form method="post" action="/collect/trigger" id="trigger-form">
          <div class="controls" style="align-items:center">
            <div class="field" style="min-width:300px">
              <label>Note (optional)</label>
              <input class="input" name="note" placeholder="e.g. pre-upgrade snapshot, incident investigation..." type="text"/>
            </div>
            <div class="field" style="min-width:auto;justify-content:flex-end">
              <label>&nbsp;</label>
              <button class="btn" type="submit" id="trigger-btn">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                Trigger Collection Now
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          Recent On-Demand Runs
        </span>
        <button class="btn btn-ghost btn-sm" onclick="location.reload()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
          </svg>
          Refresh
        </button>
      </div>
      {table}
    </div>

    <script>
    document.getElementById('trigger-form').addEventListener('submit', function() {{
      var btn = document.getElementById('trigger-btn');
      btn.disabled = true;
      btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg> Triggering...';
    }});
    </script>
    <style>
    @keyframes spin {{ from{{transform:rotate(0deg)}} to{{transform:rotate(360deg)}} }}
    </style>"""

    return render_page("collect", body, "On-Demand")


@app.route("/collect/trigger", methods=["POST"])
def collect_trigger():
    note     = request.form.get("note", "").strip()[:200]
    ts       = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    job_name = f"lognest-ondemand-{ts}"

    try:
        from kubernetes import client as k8s_client, config as k8s_config

        k8s_config.load_incluster_config()
        batch_v1 = k8s_client.BatchV1Api()

        # Get the source CronJob to copy its pod template
        cron = batch_v1.read_namespaced_cron_job(
            name="lognest-collector-1",
            namespace=K8S_NAMESPACE
        )
        pod_template = cron.spec.job_template.spec.template

        # Build a clean Job — only set what's needed
        job = k8s_client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(
                name=job_name,
                namespace=K8S_NAMESPACE,
                labels={"lognest/trigger": "ondemand", "lognest/component": "collector"}
            ),
            spec=k8s_client.V1JobSpec(
                backoff_limit=0,
                active_deadline_seconds=7200,
                template=pod_template
            )
        )

        batch_v1.create_namespaced_job(namespace=K8S_NAMESPACE, body=job)
        status   = "triggered"
        note_out = note or "Manual trigger from UI"

    except Exception as e:
        status   = "failed"
        note_out = str(e)[:400]

    save_ondemand_run({
        "triggered": ts,
        "status":    status,
        "job":       job_name,
        "note":      note_out
    })

    from flask import redirect
    return redirect("/collect")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
