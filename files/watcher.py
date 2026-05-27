#!/usr/bin/env python3
"""
LogNest Rotation Watcher — DaemonSet
Watches /var/log/pods for new rotated log files and immediately
copies them to NFS before containerd can delete them.
This prevents log loss when maxFiles is reached between collection runs.
"""
import os, sys, time, shutil, gzip
from pathlib import Path
from datetime import datetime

WATCH_DIR   = Path("/var/log/pods")
BACKUP_DIR  = Path(os.environ.get("BACKUP_DIR", "/data/rotated"))
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "30"))  # seconds
SEEN_FILE   = Path("/data/.lognest_watcher_seen")

def load_seen():
    try:
        if SEEN_FILE.exists():
            return set(SEEN_FILE.read_text().strip().splitlines())
    except Exception:
        pass
    return set()

def save_seen(seen):
    try:
        SEEN_FILE.write_text("\n".join(sorted(seen)))
    except Exception:
        pass

def get_rotated_files():
    """Find all rotated log files on the node."""
    rotated = []
    if not WATCH_DIR.exists():
        return rotated
    for pod_dir in WATCH_DIR.iterdir():
        if not pod_dir.is_dir():
            continue
        for container_dir in pod_dir.iterdir():
            if not container_dir.is_dir():
                continue
            for f in container_dir.iterdir():
                # Rotated files: 0.log.20260524-093000 or 0.log.20260524-093000.gz
                if '.log.' in f.name and f.name != '0.log':
                    rotated.append(f)
    return rotated

def backup_file(src, pod_dir_name, container_name):
    """Copy a rotated file to NFS backup directory."""
    parts = pod_dir_name.split("_")
    ns = parts[0] if len(parts) > 0 else "unknown"
    pod = parts[1] if len(parts) > 1 else "unknown"

    dest_dir = BACKUP_DIR / ns / pod / container_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / src.name

    if dest_file.exists():
        return False  # already backed up

    try:
        shutil.copy2(src, dest_file)
        return True
    except Exception as e:
        print(f"[Watcher] ERROR copying {src}: {e}", flush=True)
        return False

def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    print(f"[Watcher] Started — monitoring {WATCH_DIR}", flush=True)
    print(f"[Watcher] Backup dir: {BACKUP_DIR}", flush=True)
    print(f"[Watcher] Scan interval: {SCAN_INTERVAL}s", flush=True)
    print(f"[Watcher] Previously seen: {len(seen)} files", flush=True)

    while True:
        try:
            rotated = get_rotated_files()
            new_count = 0

            for f in rotated:
                file_key = str(f)
                if file_key in seen:
                    continue

                # New rotated file found — back it up immediately
                pod_dir_name = f.parent.parent.name
                container_name = f.parent.name

                if backup_file(f, pod_dir_name, container_name):
                    new_count += 1
                    print(f"[Watcher] Backed up: {pod_dir_name}/{container_name}/{f.name}", flush=True)

                seen.add(file_key)

            if new_count > 0:
                save_seen(seen)
                print(f"[Watcher] {new_count} new rotated file(s) backed up", flush=True)

        except Exception as e:
            print(f"[Watcher] ERROR in scan loop: {e}", flush=True)

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
