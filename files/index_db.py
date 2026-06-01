"""
LogNest Index Database — SQLite-based log index for instant UI queries.

This module provides a lightweight SQLite database that indexes all collected
log runs, individual log files, and compressed archives. It is populated by
the collector (collect.py) after each run and queried by the UI (app.py) to
serve dashboard stats, run listings, and file searches without scanning the
filesystem.

Schema overview:
  - runs: One row per collection run (identified by timestamp name).
          Stores aggregate stats (file count, total bytes).
  - log_files: One row per collected log file within a run.
               Stores metadata (namespace, pod, container) and log-level
               counts (error, warn, info, debug) sampled from the first
               200 lines for quick severity overview.
  - archives: One row per tar.gz archive in the zip directory.
              Tracks filename and size for the UI's download page.

Performance notes:
  - WAL journal mode is used for concurrent read/write access (collector
    writes while UI reads).
  - PRAGMA synchronous=NORMAL trades a small durability risk for better
    write performance (acceptable since the data can be re-indexed).
  - Indexes on run_id, namespace, and run name enable fast lookups.

Database location: <LOGS_DIR>/.lognest_index.db (default: /data/logs/.lognest_index.db)
"""
import sqlite3, os
from pathlib import Path

# Database file lives alongside the log runs for easy backup/restore
DB_PATH = Path(os.environ.get("LOGS_DIR", "/data/logs")) / ".lognest_index.db"

def get_db():
    """Get a connection to the SQLite index database.

    Configures the connection with:
      - Row factory for dict-like access to query results.
      - WAL journal mode for concurrent readers + single writer.
      - NORMAL synchronous mode for better write throughput.

    Returns:
        sqlite3.Connection: A configured database connection.
                            Caller is responsible for closing it.
    """
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row  # Enables column-name access on rows
    db.execute("PRAGMA journal_mode=WAL")       # Write-Ahead Logging for concurrency
    db.execute("PRAGMA synchronous=NORMAL")     # Faster writes, acceptable durability
    return db

def init_db():
    """Create the database schema if tables don't already exist.

    This is idempotent — safe to call on every collector run. Uses
    CREATE TABLE IF NOT EXISTS so existing data is never lost.

    Tables created:
      - runs: Collection run metadata (name, timestamp, file_count, total_bytes).
      - log_files: Per-file metadata with foreign key to runs.
      - archives: Compressed archive metadata.

    Indexes created:
      - idx_files_run: Fast lookup of files by run_id (used when listing a run's files).
      - idx_files_ns: Fast lookup of files by namespace (used for namespace filtering).
      - idx_runs_name: Fast lookup of runs by name (used for run detail queries).
    """
    db = get_db()
    db.executescript("""
        -- Runs table: one row per collection run (identified by timestamp)
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,          -- Timestamp string (e.g., "2024-01-15_10-30-00")
            timestamp TEXT NOT NULL,            -- Same as name; kept for clarity
            file_count INTEGER DEFAULT 0,      -- Number of log files in this run
            total_bytes INTEGER DEFAULT 0,     -- Sum of all file sizes in this run
            created_at REAL NOT NULL           -- Unix timestamp when indexed
        );

        -- Log files table: one row per collected .log file
        CREATE TABLE IF NOT EXISTS log_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,           -- FK to runs.id
            filename TEXT NOT NULL,            -- e.g., "ns__pod__container__timestamp.log"
            namespace TEXT,                    -- Extracted from filename (part before first __)
            pod TEXT,                          -- Extracted from filename (second __ segment)
            container TEXT,                    -- Extracted from filename (third __ segment)
            size_bytes INTEGER DEFAULT 0,     -- File size on disk
            line_count INTEGER DEFAULT 0,     -- Total lines in the file
            error_count INTEGER DEFAULT 0,    -- Lines containing "error" (sampled)
            warn_count INTEGER DEFAULT 0,     -- Lines containing "warn" (sampled)
            info_count INTEGER DEFAULT 0,     -- Lines containing "info" (sampled)
            debug_count INTEGER DEFAULT 0,    -- Lines containing "debug" (sampled)
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );

        -- Archives table: one row per tar.gz file
        CREATE TABLE IF NOT EXISTS archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,     -- e.g., "lognest_2024-01-15_10-30-00.tar.gz"
            size_bytes INTEGER DEFAULT 0,     -- Archive file size
            created_at REAL NOT NULL          -- Unix timestamp when indexed
        );

        -- Indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_files_run ON log_files(run_id);   -- List files in a run
        CREATE INDEX IF NOT EXISTS idx_files_ns ON log_files(namespace); -- Filter by namespace
        CREATE INDEX IF NOT EXISTS idx_runs_name ON runs(name);          -- Lookup run by name
    """)
    db.close()

def index_run(run_name, run_dir, timestamp):
    """Index a completed collection run by scanning its log files.

    Inserts (or replaces) the run record and scans each .log file to extract:
      - Namespace, pod, and container from the filename convention:
        <namespace>__<pod>__<container>__<timestamp>.log
      - File size and total line count.
      - Log-level counts (error/warn/info/debug) sampled from the first
        200 lines for performance (avoids reading multi-GB files fully).

    Args:
        run_name (str): The run's unique name (typically a timestamp string).
        run_dir (str): Absolute path to the run's directory containing .log files.
        timestamp (str): The timestamp string for this run.
    """
    import time
    db = get_db()
    
    # Insert or update run record (REPLACE handles re-indexing the same run)
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
        # Parse the filename to extract Kubernetes metadata.
        # Filename format: <namespace>__<pod>__<container>__<timestamp>.log
        parts = f.stem.split("__")
        ns = parts[0] if len(parts) > 0 else ""
        pod = parts[1] if len(parts) > 1 else ""
        container = parts[2] if len(parts) > 2 else ""
        
        size = f.stat().st_size
        total_bytes += size
        file_count += 1
        
        # Count log levels by sampling the first 200 lines.
        # This gives a quick severity overview without reading entire files
        # (which could be hundreds of MB for busy containers).
        error_c = warn_c = info_c = debug_c = 0
        line_count = 0
        try:
            with open(f, 'r', errors='replace') as fh:
                for i, line in enumerate(fh):
                    line_count += 1
                    if i < 200:  # Only sample first 200 lines for level counts
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
    
    # Update run totals (aggregated from individual files)
    db.execute(
        "UPDATE runs SET file_count=?, total_bytes=? WHERE id=?",
        (file_count, total_bytes, run_id)
    )
    db.commit()
    db.close()

def index_archive(filename, size_bytes):
    """Index a compressed tar.gz archive file.

    Called after compress_run() creates a new archive. Uses INSERT OR REPLACE
    so re-indexing the same archive (e.g., after a re-run) is safe.

    Args:
        filename (str): The archive filename (e.g., "lognest_2024-01-15_10-30-00.tar.gz").
        size_bytes (int): The archive file size in bytes.
    """
    import time
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO archives (filename, size_bytes, created_at) VALUES (?, ?, ?)",
        (filename, size_bytes, time.time())
    )
    db.commit()
    db.close()

def remove_run(run_name):
    """Remove a run and all its associated data from the index.

    Deletes the run record, all its log_files entries (cascade-like),
    and any archive whose filename contains the run name.

    Called during retention cleanup to keep the index in sync with
    the filesystem after old runs are deleted.

    Args:
        run_name (str): The run's unique name (timestamp string).
    """
    db = get_db()
    run = db.execute("SELECT id FROM runs WHERE name=?", (run_name,)).fetchone()
    if run:
        # Delete child records first (log_files), then the parent (runs)
        db.execute("DELETE FROM log_files WHERE run_id=?", (run[0],))
        db.execute("DELETE FROM runs WHERE id=?", (run[0],))
    # Also remove matching archive entry (LIKE match handles the filename pattern)
    db.execute("DELETE FROM archives WHERE filename LIKE ?", (f"%{run_name}%",))
    db.commit()
    db.close()

# ══════════════════════════════════════════════════════════════════════════════
# Query functions for the UI — all return plain dicts for JSON serialization
# ══════════════════════════════════════════════════════════════════════════════

def query_runs(limit=30, offset=0):
    """Get a paginated list of collection runs, newest first.

    Used by the UI's main runs page. Returns lightweight metadata
    (no file details) for fast rendering.

    Args:
        limit (int): Maximum number of runs to return (default 30).
        offset (int): Number of runs to skip for pagination (default 0).

    Returns:
        list[dict]: Each dict has keys: name, timestamp, file_count, total_bytes.
    """
    db = get_db()
    # ORDER BY name DESC works because names are timestamps (lexicographic = chronological)
    rows = db.execute(
        "SELECT name, timestamp, file_count, total_bytes FROM runs ORDER BY name DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]

def query_run_count():
    """Get the total number of indexed runs.

    Used for pagination controls in the UI (total pages calculation).

    Returns:
        int: Total number of runs in the database.
    """
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    db.close()
    return count

def query_files(run_name, search=""):
    """Get all log files for a specific run, with optional filename search.

    Used by the UI's run detail page. Returns full file metadata including
    log-level counts for severity indicators.

    Args:
        run_name (str): The run's unique name to look up.
        search (str): Optional substring filter on filename (case-sensitive LIKE).

    Returns:
        list[dict]: Each dict has all log_files columns. Empty list if run not found.
    """
    db = get_db()
    run = db.execute("SELECT id FROM runs WHERE name=?", (run_name,)).fetchone()
    if not run:
        db.close()
        return []
    # Build query with optional search filter
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
    """Get aggregate dashboard statistics across all runs.

    Used by the UI's main dashboard to show a quick overview of the
    entire LogNest data store. All queries hit indexed columns for
    sub-millisecond response times.

    Returns:
        dict: Keys: runs (int), files (int), zips (int),
              storage_bytes (int), last_run (str or "Never").
    """
    db = get_db()
    run_count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    file_count = db.execute("SELECT COALESCE(SUM(file_count), 0) FROM runs").fetchone()[0]
    total_bytes = db.execute("SELECT COALESCE(SUM(total_bytes), 0) FROM runs").fetchone()[0]
    archive_count = db.execute("SELECT COUNT(*) FROM archives").fetchone()[0]
    archive_bytes = db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM archives").fetchone()[0]
    # Get the most recent run name (newest timestamp = last alphabetically)
    last_run = db.execute("SELECT name FROM runs ORDER BY name DESC LIMIT 1").fetchone()
    db.close()
    return {
        "runs": run_count,
        "files": file_count,
        "zips": archive_count,
        "storage_bytes": total_bytes + archive_bytes,  # Combined raw + archive storage
        "last_run": last_run[0] if last_run else "Never",
    }

def query_archives():
    """Get all indexed archives, newest first.

    Used by the UI's archives/download page to list available tar.gz
    files with their sizes.

    Returns:
        list[dict]: Each dict has keys: filename, size_bytes, created_at.
    """
    db = get_db()
    rows = db.execute(
        "SELECT filename, size_bytes, created_at FROM archives ORDER BY filename DESC"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
