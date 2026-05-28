"""
LogNest Index Database — SQLite-based log index for instant UI queries.
Built during collection, queried by the UI.
"""
import sqlite3, os
from pathlib import Path

DB_PATH = Path(os.environ.get("LOGS_DIR", "/data/logs")) / ".lognest_index.db"

def get_db():
    """Get a connection to the index database."""
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    return db

def init_db():
    """Create tables if they don't exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            file_count INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS log_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            namespace TEXT,
            pod TEXT,
            container TEXT,
            size_bytes INTEGER DEFAULT 0,
            line_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            warn_count INTEGER DEFAULT 0,
            info_count INTEGER DEFAULT 0,
            debug_count INTEGER DEFAULT 0,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        CREATE TABLE IF NOT EXISTS archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_run ON log_files(run_id);
        CREATE INDEX IF NOT EXISTS idx_files_ns ON log_files(namespace);
        CREATE INDEX IF NOT EXISTS idx_runs_name ON runs(name);
    """)
    db.close()

def index_run(run_name, run_dir, timestamp):
    """Index a completed collection run."""
    import time
    db = get_db()
    
    # Insert or update run
    db.execute(
        "INSERT OR REPLACE INTO runs (name, timestamp, created_at) VALUES (?, ?, ?)",
        (run_name, timestamp, time.time())
    )
    run_id = db.execute("SELECT id FROM runs WHERE name=?", (run_name,)).fetchone()[0]
    
    # Delete old file entries for this run (in case of re-index)
    db.execute("DELETE FROM log_files WHERE run_id=?", (run_id,))
    
    total_bytes = 0
    file_count = 0
    
    for f in Path(run_dir).glob("*.log"):
        parts = f.stem.split("__")
        ns = parts[0] if len(parts) > 0 else ""
        pod = parts[1] if len(parts) > 1 else ""
        container = parts[2] if len(parts) > 2 else ""
        
        size = f.stat().st_size
        total_bytes += size
        file_count += 1
        
        # Count levels (sample first 200 lines for speed)
        error_c = warn_c = info_c = debug_c = 0
        line_count = 0
        try:
            with open(f, 'r', errors='replace') as fh:
                for i, line in enumerate(fh):
                    line_count += 1
                    if i < 200:
                        ll = line.lower()
                        if 'error' in ll: error_c += 1
                        elif 'warn' in ll: warn_c += 1
                        elif 'info' in ll: info_c += 1
                        elif 'debug' in ll: debug_c += 1
        except Exception:
            pass
        
        db.execute("""
            INSERT INTO log_files 
            (run_id, filename, namespace, pod, container, size_bytes, line_count,
             error_count, warn_count, info_count, debug_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, f.name, ns, pod, container, size, line_count,
              error_c, warn_c, info_c, debug_c))
    
    # Update run totals
    db.execute(
        "UPDATE runs SET file_count=?, total_bytes=? WHERE id=?",
        (file_count, total_bytes, run_id)
    )
    db.commit()
    db.close()

def index_archive(filename, size_bytes):
    """Index a zip archive."""
    import time
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO archives (filename, size_bytes, created_at) VALUES (?, ?, ?)",
        (filename, size_bytes, time.time())
    )
    db.commit()
    db.close()

def remove_run(run_name):
    """Remove a run from the index."""
    db = get_db()
    run = db.execute("SELECT id FROM runs WHERE name=?", (run_name,)).fetchone()
    if run:
        db.execute("DELETE FROM log_files WHERE run_id=?", (run[0],))
        db.execute("DELETE FROM runs WHERE id=?", (run[0],))
    db.execute("DELETE FROM archives WHERE filename LIKE ?", (f"%{run_name}%",))
    db.commit()
    db.close()

# ── Query functions for the UI ──

def query_runs(limit=30, offset=0):
    """Get runs list — instant from SQLite."""
    db = get_db()
    rows = db.execute(
        "SELECT name, timestamp, file_count, total_bytes FROM runs ORDER BY name DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]

def query_run_count():
    """Get total number of runs."""
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    db.close()
    return count

def query_files(run_name, search=""):
    """Get files for a run — instant from SQLite."""
    db = get_db()
    run = db.execute("SELECT id FROM runs WHERE name=?", (run_name,)).fetchone()
    if not run:
        db.close()
        return []
    query = "SELECT * FROM log_files WHERE run_id=?"
    params = [run[0]]
    if search:
        query += " AND filename LIKE ?"
        params.append(f"%{search}%")
    query += " ORDER BY filename"
    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]

def query_stats():
    """Get dashboard stats — instant from SQLite."""
    db = get_db()
    run_count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    file_count = db.execute("SELECT COALESCE(SUM(file_count), 0) FROM runs").fetchone()[0]
    total_bytes = db.execute("SELECT COALESCE(SUM(total_bytes), 0) FROM runs").fetchone()[0]
    archive_count = db.execute("SELECT COUNT(*) FROM archives").fetchone()[0]
    archive_bytes = db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM archives").fetchone()[0]
    last_run = db.execute("SELECT name FROM runs ORDER BY name DESC LIMIT 1").fetchone()
    db.close()
    return {
        "runs": run_count,
        "files": file_count,
        "zips": archive_count,
        "storage_bytes": total_bytes + archive_bytes,
        "last_run": last_run[0] if last_run else "Never",
    }

def query_archives():
    """Get archives list — instant from SQLite."""
    db = get_db()
    rows = db.execute(
        "SELECT filename, size_bytes, created_at FROM archives ORDER BY filename DESC"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
