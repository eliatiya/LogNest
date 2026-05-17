#!/usr/bin/env python3
"""
LogNest Web UI — Production Ready
"""
import os, re, html as _html
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, send_file, request, abort, jsonify

app = Flask(__name__)

LOGS_DIR = Path(os.environ.get("LOGS_DIR", "/data/logs"))
ZIP_DIR  = Path(os.environ.get("ZIP_DIR",  "/data/logs_zip"))

# ------------------------------------------------------------------ helpers
def get_runs():
    if not LOGS_DIR.exists():
        return []
    return sorted([d.name for d in LOGS_DIR.iterdir() if d.is_dir()], reverse=True)

def get_log_files(run=None):
    base = LOGS_DIR / run if run else LOGS_DIR
    if not base.exists():
        return []
    return sorted(base.rglob("*.log"), key=lambda p: p.name)

def get_zips():
    if not ZIP_DIR.exists():
        return []
    return sorted(ZIP_DIR.glob("*.tar.gz"), key=lambda p: p.name, reverse=True)

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
def get_stats():
    runs = get_runs()
    total_files = sum(
        len(list((LOGS_DIR / r).glob("*.log")))
        for r in runs if (LOGS_DIR / r).is_dir()
    )
    zips = list(get_zips())
    storage = sum(z.stat().st_size for z in zips) if zips else 0
    last_run = runs[0] if runs else "Never"
    return {
        "runs": len(runs),
        "files": total_files,
        "zips": len(zips),
        "storage": _human_size(storage),
        "last_run": last_run,
    }

# ------------------------------------------------------------------ HTML base
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LogNest{title_suffix}</title>
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
  backdrop-filter:blur(8px);
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
  transition:color .15s,border-color .15s;white-space:nowrap;
}}
.nav a:hover{{color:var(--text)}}
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
}}
.stat-card .val{{font-size:1.6rem;font-weight:700;color:var(--accent);line-height:1}}
.stat-card .lbl{{font-size:.72rem;color:var(--text-dim);margin-top:5px;text-transform:uppercase;letter-spacing:.5px}}
.stat-card .sub{{font-size:.75rem;color:var(--text-mute);margin-top:3px}}

/* ── Card ── */
.card{{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);margin-bottom:20px;overflow:hidden;
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
  transition:border-color .15s;cursor:pointer;
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
  text-decoration:none;transition:background .15s,transform .1s;
  white-space:nowrap;font-family:inherit;
}}
.btn:hover{{background:var(--accent-h);transform:translateY(-1px)}}
.btn:active{{transform:translateY(0)}}
.btn-sm{{padding:5px 12px;font-size:.78rem}}
.btn-ghost{{background:transparent;color:var(--text-dim);border:1px solid var(--border2)}}
.btn-ghost:hover{{background:var(--surface2);color:var(--text);border-color:var(--border2)}}
.btn-danger{{background:#7f1d1d;color:var(--red)}}
.btn-danger:hover{{background:#991b1b}}

/* ── Log viewer ── */
.log-toolbar{{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:12px 16px;background:var(--bg);border-bottom:1px solid var(--border);
}}
.log-filename{{font-size:.78rem;color:var(--text-dim);font-family:monospace;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.log-counts{{display:flex;gap:6px;flex-shrink:0}}
.lc{{font-size:.72rem;padding:2px 8px;border-radius:4px;font-weight:600;cursor:pointer;border:1px solid transparent;transition:.15s}}
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
  font-size:.85rem;vertical-align:middle;
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
}}
.empty-state svg{{opacity:.3}}
.empty-state p{{font-size:.88rem}}

/* ── Size pill ── */
.size{{font-size:.75rem;color:var(--text-dim);font-family:monospace;background:var(--surface2);padding:2px 7px;border-radius:4px}}

/* ── Toast ── */
#toast{{
  position:fixed;bottom:24px;right:24px;
  background:var(--surface2);border:1px solid var(--border2);
  color:var(--text);padding:12px 20px;border-radius:var(--radius);
  font-size:.85rem;box-shadow:var(--shadow);
  transform:translateY(80px);opacity:0;transition:.3s;z-index:999;
  display:flex;align-items:center;gap:8px;
}}
#toast.show{{transform:translateY(0);opacity:1}}
#toast.success{{border-left:3px solid var(--green)}}
#toast.error{{border-left:3px solid var(--red)}}

/* ── Responsive ── */
@media(max-width:768px){{
  .header{{padding:0 16px}}
  .page{{padding:16px}}
  .nav a span{{display:none}}
  .stats-grid{{grid-template-columns:repeat(2,1fr)}}
  .controls{{flex-direction:column}}
  .field{{min-width:100%}}
}}
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
  </nav>
  <div class="header-right">
    <span class="header-badge">RKE2</span>
  </div>
</header>

<div class="page">
{body}
</div>

<div id="toast"></div>
<script>
function toast(msg, type){{
  var t=document.getElementById('toast');
  t.textContent=msg; t.className='show '+(type||'');
  setTimeout(function(){{t.className='';}},3000);
}}
function copyText(txt){{
  navigator.clipboard.writeText(txt).then(function(){{toast('Copied to clipboard','success');}});
}}
</script>
</body></html>"""

# ------------------------------------------------------------------ page renderer
def render_page(tab, body, title_suffix=""):
    a = lambda t: "active" if tab == t else ""
    return PAGE.format(
        title_suffix=f" — {title_suffix}" if title_suffix else "",
        a_dash=a("dashboard"), a_dl=a("downloads"), a_files=a("files"),
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
                raw = target.read_text(errors="replace")
                filtered = filter_lines(raw, level)
                if search:
                    filtered = "\n".join(
                        l for l in filtered.splitlines()
                        if search.lower() in l.lower()
                    )
                log_content = filtered
                # count levels in raw
                for line in raw.splitlines():
                    ll = line.lower()
                    if re.search(r'\berror\b', ll): error_count += 1
                    elif re.search(r'\bwarn', ll):  warn_count  += 1
                    elif re.search(r'\binfo\b', ll): info_count += 1
                    elif re.search(r'\bdebug\b', ll): debug_count += 1
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

    # run selector
    run_opts = "".join(
        f'<option value="{r}" {"selected" if r==sel_run else ""}>{r}</option>'
        for r in runs
    )

    # pod selector
    pod_opts = "".join(
        f'<option value="{f.name}" {"selected" if f.name==sel_pod else ""}>'
        f'{f.name.replace(".log","")}</option>'
        for f in log_files
    ) if sel_run else ""

    level_opts = "".join(
        f'<option value="{v}" {"selected" if v==level else ""}>{l}</option>'
        for v, l in [("all","All Levels"),("error","Errors"),
                     ("warning","Warnings"),("info","Info"),("debug","Debug")]
    )

    pod_field = f"""
      <div class="field">
        <label>Pod / Container</label>
        <select name="pod" onchange="this.form.submit()">
          <option value="">— Select pod —</option>{pod_opts}
        </select>
      </div>
      <div class="field" style="min-width:140px">
        <label>Level</label>
        <select name="level" onchange="this.form.submit()">{level_opts}</select>
      </div>""" if sel_run else ""

    controls = f"""
    <div class="card">
      <div class="card-body">
        <form method="get" action="/" id="filter-form">
          <div class="controls">
            <div class="field">
              <label>Collection Run</label>
              <select name="run" onchange="this.form.submit()">
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
        # build colored lines
        colored = []
        for line in lines:
            esc = _html.escape(line)
            ll = line.lower()
            if re.search(r'\berror\b', ll):   cls = "log-error"
            elif re.search(r'\bwarn', ll):    cls = "log-warn"
            elif re.search(r'\bdebug\b', ll): cls = "log-debug"
            elif re.search(r'\binfo\b', ll):  cls = "log-info"
            else:                             cls = "log-ts"
            colored.append(f'<span class="log-line {cls}">{esc}</span>')
        log_html = "\n".join(colored)

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
                <input class="input log-search" name="q" placeholder="Search logs..." value="{_html.escape(search)}" type="text"/>
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
            # parse date from filename lognest_YYYY-MM-DD_HH-MM-SS.tar.gz
            try:
                ts   = name.replace("lognest_","").replace(".tar.gz","")
                dt   = datetime.strptime(ts, "%Y-%m-%d_%H-%M-%S")
                date = dt.strftime("%b %d, %Y  %H:%M")
            except Exception:
                date = "—"
            rows += f"""<tr>
              <td class="mono">{_html.escape(name)}</td>
              <td>{date}</td>
              <td><span class="size">{sz}</span></td>
              <td>
                <a class="btn btn-sm" href="/download/zip/{_html.escape(name)}">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  Download
                </a>
              </td>
            </tr>"""
        table = f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>Archive</th><th>Date</th><th>Size</th><th>Action</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""
    else:
        table = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <p>No archives yet — they are created after each collection run</p>
        </div>"""

    body = f"""
    <div class="card">
      <div class="card-header">
        <span class="card-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Compressed Archives
        </span>
        <span style="font-size:.75rem;color:var(--text-dim)">{len(zips)} archive{"s" if len(zips)!=1 else ""}</span>
      </div>
      {table}
    </div>"""
    return render_page("downloads", body, "Downloads")


@app.route("/files")
def files():
    runs    = get_runs()
    sel_run = request.args.get("run", "")
    search  = request.args.get("q", "")

    run_opts = "".join(
        f'<option value="{r}" {"selected" if r==sel_run else ""}>{r}</option>'
        for r in runs
    )

    controls = f"""
    <div class="card">
      <div class="card-body">
        <form method="get" action="/files">
          <div class="controls">
            <div class="field">
              <label>Collection Run</label>
              <select name="run" onchange="this.form.submit()">
                <option value="">— Select run —</option>{run_opts}
              </select>
            </div>
            <div class="field">
              <label>Search filename</label>
              <input class="input" name="q" placeholder="e.g. production, coredns..." value="{_html.escape(search)}" type="text"/>
            </div>
            <div class="field" style="justify-content:flex-end;min-width:auto">
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
                self.path = path
                self.name = path.name
                self.size = _human_size(path.stat().st_size)
                parts = path.stem.split("__")
                self.ns        = parts[0] if len(parts) > 0 else "—"
                self.pod       = parts[1] if len(parts) > 1 else "—"
                self.container = parts[2] if len(parts) > 2 else "—"

        all_files = [FileInfo(f) for f in get_log_files(sel_run)]
        if search:
            all_files = [f for f in all_files if search.lower() in f.name.lower()]

        if all_files:
            rows = ""
            for f in all_files:
                rows += f"""<tr>
                  <td><span class="badge badge-ns">{_html.escape(f.ns)}</span></td>
                  <td class="mono">{_html.escape(f.pod)}</td>
                  <td class="mono">{_html.escape(f.container)}</td>
                  <td><span class="size">{f.size}</span></td>
                  <td style="display:flex;gap:6px">
                    <a class="btn btn-sm" href="/download/log/{_html.escape(sel_run)}/{_html.escape(f.name)}">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      Download
                    </a>
                    <a class="btn btn-ghost btn-sm" href="/?run={_html.escape(sel_run)}&pod={_html.escape(f.name)}">View</a>
                  </td>
                </tr>"""
            table_block = f"""
            <div class="card">
              <div class="card-header">
                <span class="card-title">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  {_html.escape(sel_run)}
                </span>
                <span style="font-size:.75rem;color:var(--text-dim)">{len(all_files)} file{"s" if len(all_files)!=1 else ""}</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Namespace</th><th>Pod</th><th>Container</th><th>Size</th><th>Actions</th></tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </div>"""
        else:
            table_block = '<div class="empty-state"><p>No files match your search.</p></div>'
    else:
        table_block = """<div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <p>Select a run to browse individual log files</p>
        </div>"""

    return render_page("files", controls + table_block, "Files")


# ------------------------------------------------------------------ API
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
