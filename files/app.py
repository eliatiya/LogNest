#!/usr/bin/env python3
"""
LogNest Web UI
Tabs:
  1. Dashboard  - browse pods, filter by level (error/warn/debug/info)
  2. Downloads  - download compressed zip archives by date
  3. File Pick  - download individual log files
"""
import os, re
from pathlib import Path
from flask import Flask, render_template_string, send_file, request, abort

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

# ------------------------------------------------------------------ HTML
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}
header{background:#1a1d27;padding:16px 32px;display:flex;align-items:center;gap:16px;border-bottom:1px solid #2a2d3a}
header h1{font-size:1.4rem;color:#7eb8f7;letter-spacing:1px}
nav{display:flex;gap:0}
nav a{padding:10px 28px;text-decoration:none;color:#aaa;border-bottom:3px solid transparent;transition:.2s}
nav a.active,nav a:hover{color:#7eb8f7;border-bottom-color:#7eb8f7}
.container{max-width:1200px;margin:32px auto;padding:0 24px}
.card{background:#1a1d27;border-radius:8px;padding:24px;margin-bottom:24px;border:1px solid #2a2d3a}
select{background:#0f1117;color:#e0e0e0;border:1px solid #3a3d4a;border-radius:4px;padding:8px 12px;font-size:.95rem}
select:focus{outline:none;border-color:#7eb8f7}
.btn{background:#2563eb;color:#fff;border:none;border-radius:4px;padding:8px 20px;cursor:pointer;font-size:.9rem;text-decoration:none;display:inline-block}
.btn:hover{background:#1d4ed8}
.btn-sm{padding:4px 12px;font-size:.82rem}
pre{background:#0a0c12;border-radius:6px;padding:16px;overflow:auto;max-height:600px;font-size:.82rem;line-height:1.5;white-space:pre-wrap;word-break:break-all}
.log-error{color:#f87171}
.log-warn{color:#fbbf24}
.log-debug{color:#a78bfa}
.log-info{color:#34d399}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid #2a2d3a;font-size:.9rem}
th{color:#7eb8f7;font-weight:600}
tr:hover td{background:#1f2235}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end}
label{font-size:.85rem;color:#aaa;display:block;margin-bottom:4px}
.empty{color:#555;font-style:italic;padding:16px 0}
"""

def base_html(tab, content):
    active = lambda t: "active" if tab == t else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>LogNest</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <h1>&#x1FAB9; LogNest</h1>
  <nav>
    <a href="/" class="{active('dashboard')}">&#x1F4CA; Dashboard</a>
    <a href="/downloads" class="{active('downloads')}">&#x1F4E6; Downloads</a>
    <a href="/files" class="{active('files')}">&#x1F4C4; Files</a>
  </nav>
</header>
<div class="container">{content}</div>
</body></html>"""

# ------------------------------------------------------------------ routes
@app.route("/")
def dashboard():
    runs        = get_runs()
    sel_run     = request.args.get("run", "")
    sel_pod     = request.args.get("pod", "")
    level       = request.args.get("level", "all")
    log_files   = []
    log_content = None

    if sel_run:
        log_files = get_log_files(sel_run)
        if sel_pod:
            target = LOGS_DIR / sel_run / sel_pod
            if target.exists():
                raw = target.read_text(errors="replace")
                log_content = filter_lines(raw, level)
            else:
                abort(404)

    # Build filter controls
    run_opts = "".join(
        f'<option value="{r}" {"selected" if r == sel_run else ""}>{r}</option>'
        for r in runs
    )
    pod_opts = "".join(
        f'<option value="{f.name}" {"selected" if f.name == sel_pod else ""}>'
        f'{f.name.replace(".log","")}</option>'
        for f in log_files
    ) if sel_run else ""

    level_opts = "".join(
        f'<option value="{v}" {"selected" if v == level else ""}>{l}</option>'
        for v, l in [("all","All"),("error","Error"),("warning","Warning"),
                     ("info","Info"),("debug","Debug")]
    )

    pod_select = f"""
      <div>
        <label>Pod / Container</label>
        <select name="pod" onchange="this.form.submit()">
          <option value="">-- All pods --</option>{pod_opts}
        </select>
      </div>
      <div>
        <label>Level filter</label>
        <select name="level" onchange="this.form.submit()">
          {level_opts}
        </select>
      </div>""" if sel_run else ""

    log_block = ""
    if log_content is not None:
        log_block = f"""
        <div class="card">
          <pre id="logview">{log_content}</pre>
        </div>
        <script>
          (function(){{
            var pre = document.getElementById('logview');
            var html = pre.innerHTML;
            html = html.replace(/^(.*\\berror\\b.*)$/gim, '<span class="log-error">$1</span>');
            html = html.replace(/^(.*\\bwarn(ing)?\\b.*)$/gim, '<span class="log-warn">$1</span>');
            html = html.replace(/^(.*\\bdebug\\b.*)$/gim, '<span class="log-debug">$1</span>');
            html = html.replace(/^(.*\\binfo\\b.*)$/gim, '<span class="log-info">$1</span>');
            pre.innerHTML = html;
          }})();
        </script>"""
    elif sel_run:
        log_block = '<p class="empty">Select a pod to view its logs.</p>'
    else:
        log_block = '<p class="empty">Select a run to get started.</p>'

    content = f"""
    <div class="card">
      <form method="get" action="/">
        <div class="row">
          <div>
            <label>Run (date/time)</label>
            <select name="run" onchange="this.form.submit()">
              <option value="">-- Select run --</option>{run_opts}
            </select>
          </div>
          {pod_select}
        </div>
      </form>
    </div>
    {log_block}"""

    return base_html("dashboard", content)


@app.route("/downloads")
def downloads():
    class ZipInfo:
        def __init__(self, path):
            self.name = path.name
            self.size = _human_size(path.stat().st_size)

    zips = [ZipInfo(z) for z in get_zips()]
    if zips:
        rows = "".join(
            f"<tr><td>{z.name}</td><td>{z.size}</td>"
            f'<td><a class="btn btn-sm" href="/download/zip/{z.name}">&#x2B07; Download</a></td></tr>'
            for z in zips
        )
        table = f"""<table>
          <thead><tr><th>Archive</th><th>Size</th><th>Action</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""
    else:
        table = '<p class="empty">No archives yet. Archives are created after each log collection run.</p>'

    content = f"""
    <div class="card">
      <h2 style="margin-bottom:16px;color:#7eb8f7">Compressed Archives</h2>
      {table}
    </div>"""
    return base_html("downloads", content)


@app.route("/files")
def files():
    runs    = get_runs()
    sel_run = request.args.get("run", "")

    run_opts = "".join(
        f'<option value="{r}" {"selected" if r == sel_run else ""}>{r}</option>'
        for r in runs
    )

    table_block = ""
    if sel_run:
        class FileInfo:
            def __init__(self, path):
                self.name = path.name
                self.size = _human_size(path.stat().st_size)

        log_files = [FileInfo(f) for f in get_log_files(sel_run)]
        if log_files:
            rows = "".join(
                f"<tr><td>{f.name}</td><td>{f.size}</td>"
                f'<td><a class="btn btn-sm" href="/download/log/{sel_run}/{f.name}">&#x2B07; Download</a></td></tr>'
                for f in log_files
            )
            table_block = f"""
            <div class="card">
              <h2 style="margin-bottom:16px;color:#7eb8f7">Log Files — run: {sel_run}</h2>
              <table>
                <thead><tr><th>File</th><th>Size</th><th>Action</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </div>"""
        else:
            table_block = '<p class="empty">No log files found in this run.</p>'
    else:
        table_block = '<p class="empty">Select a run to browse individual log files.</p>'

    content = f"""
    <div class="card">
      <form method="get" action="/files">
        <div class="row">
          <div>
            <label>Run (date/time)</label>
            <select name="run" onchange="this.form.submit()">
              <option value="">-- Select run --</option>{run_opts}
            </select>
          </div>
        </div>
      </form>
    </div>
    {table_block}"""
    return base_html("files", content)


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
