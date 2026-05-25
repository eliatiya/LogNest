#!/usr/bin/env python3
"""
LogNest Collector — Parallel, incremental, with rotation support.
Reads from /var/log/pods (hostPath) and kubectl API.
Tracks byte offsets for incremental reads.
"""
import os, sys, json, gzip, time, tarfile, shutil, subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ──
LOGS_DIR       = Path(os.environ.get("LOGS_DIR", "/data/logs"))
ZIP_DIR        = Path(os.environ.get("ZIP_DIR", "/data/logs_zip"))
NODE_LOGS      = Path("/var/log/pods")
STATE_FILE     = Path("/data/.lognest_last_collect")
OFFSETS_FILE   = Path("/data/.lognest_offsets")
RETENTION_MONTHS    = int(os.environ.get("RETENTION_MONTHS", "1"))
CAPACITY_THRESHOLD  = int(os.environ.get("CAPACITY_THRESHOLD", "80"))
MAX_WORKERS         = int(os.environ.get("COLLECTOR_THREADS", "8"))
TIMESTAMP      = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
NOW_EPOCH      = int(time.time())

print(f"[LogNest] ============================================")
print(f"[LogNest] Starting collection at {TIMESTAMP}")
print(f"[LogNest] Node: {os.environ.get('NODE_NAME', 'unknown')}")
print(f"[LogNest] Threads: {MAX_WORKERS}")
print(f"[LogNest] ============================================")


# ── State management ──
def load_last_epoch():
    try:
        if STATE_FILE.exists():
            return int(STATE_FILE.read_text().strip())
    except Exception:
        pass
    return 0

def save_last_epoch():
    STATE_FILE.write_text(str(NOW_EPOCH))

def load_offsets():
    try:
        if OFFSETS_FILE.exists():
            return json.loads(OFFSETS_FILE.read_text())
    except Exception:
        pass
    return {}

def save_offsets(offsets):
    OFFSETS_FILE.write_text(json.dumps(offsets))


# ── Collection logic ──
LAST_EPOCH = load_last_epoch()
OFFSETS = load_offsets()
RUN_DIR = LOGS_DIR / TIMESTAMP
RUN_DIR.mkdir(parents=True, exist_ok=True)
ZIP_DIR.mkdir(parents=True, exist_ok=True)

if LAST_EPOCH == 0:
    print("[LogNest] First run: collecting ALL logs")
else:
    print(f"[LogNest] Incremental: collecting since epoch {LAST_EPOCH}")


def collect_container_from_node(container_dir, ns, pod, container):
    """Collect logs from a single container's node directory."""
    out_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
    collected = False

    try:
        # 1. Rotated files (both .gz and plain)
        rotated = sorted([
            f for f in container_dir.iterdir()
            if f.name.startswith("0.log.") or (f.suffix == '.gz' and '.log.' in f.name)
        ], key=lambda f: f.name)

        for rot in rotated:
            file_mtime = int(rot.stat().st_mtime)
            if file_mtime <= LAST_EPOCH:
                continue
            try:
                if rot.suffix == '.gz':
                    with gzip.open(rot, 'rt', errors='replace') as gz:
                        content = gz.read()
                    print(f"[LogNest]   ├─ Rotated (gz): {rot.name} ({len(content)} bytes)")
                else:
                    content = rot.read_text(errors='replace')
                    print(f"[LogNest]   ├─ Rotated (plain): {rot.name} ({len(content)} bytes)")
                if content:
                    with open(out_file, 'a') as f:
                        f.write(content)
                    collected = True
            except Exception as e:
                print(f"[LogNest]   ├─ WARN: {rot.name}: {e}")

        # 2. Active log file — incremental by byte offset
        active_logs = sorted([
            f for f in container_dir.iterdir()
            if f.suffix == '.log' and '.log.' not in f.name
        ])

        for log_file in active_logs:
            file_key = str(log_file)
            current_size = log_file.stat().st_size
            prev_offset = OFFSETS.get(file_key, 0)

            if current_size > prev_offset:
                new_bytes = current_size - prev_offset
                try:
                    with open(log_file, 'rb') as fh:
                        fh.seek(prev_offset)
                        new_data = fh.read()
                    if new_data:
                        with open(out_file, 'ab') as f:
                            f.write(new_data)
                        collected = True
                        print(f"[LogNest]   ├─ Active: {log_file.name} +{new_bytes} bytes (offset {prev_offset} → {current_size})")
                except Exception as e:
                    print(f"[LogNest]   ├─ WARN: {log_file.name}: {e}")

                OFFSETS[file_key] = current_size
            else:
                print(f"[LogNest]   ├─ Active: {log_file.name} (no new data, offset={prev_offset})")

    except Exception as e:
        print(f"[LogNest] ERROR: {ns}/{pod}/{container}: {e}")

    if collected and out_file.exists() and out_file.stat().st_size > 0:
        size = out_file.stat().st_size
        print(f"[LogNest]   └─ ✓ {ns}/{pod}/{container} → {size} bytes")
        return str(out_file)
    else:
        out_file.unlink(missing_ok=True)
        return None


def collect_from_node():
    """Phase 1: Collect from /var/log/pods using thread pool."""
    if not NODE_LOGS.is_dir():
        print(f"[LogNest] WARN: {NODE_LOGS} not mounted — skipping")
        return 0

    tasks = []
    for ns_pod_dir in NODE_LOGS.iterdir():
        if not ns_pod_dir.is_dir():
            continue
        parts = ns_pod_dir.name.split("_")
        if len(parts) < 2:
            continue
        ns = parts[0]
        pod = parts[1]

        for container_dir in ns_pod_dir.iterdir():
            if not container_dir.is_dir():
                continue
            container = container_dir.name
            tasks.append((container_dir, ns, pod, container))

    print(f"[LogNest] Phase 1: {len(tasks)} containers to process ({MAX_WORKERS} threads)")
    collected = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(collect_container_from_node, *t): t
            for t in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                collected += 1

    print(f"[LogNest] Phase 1 done: {collected} files collected")
    return collected


def collect_from_api():
    """Phase 2: Collect via kubectl API for pods not covered by node logs."""
    print("[LogNest] Phase 2: kubectl API collection")
    collected = 0

    try:
        result = subprocess.run(
            ["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print("[LogNest] WARN: kubectl not available — skipping API phase")
            return 0
        namespaces = result.stdout.strip().split()
    except Exception as e:
        print(f"[LogNest] WARN: kubectl failed: {e}")
        return 0

    since_flag = []
    if LAST_EPOCH > 0:
        since_secs = NOW_EPOCH - LAST_EPOCH + 60
        since_flag = [f"--since={since_secs}s"]

    def collect_pod_api(ns, pod, container):
        # Skip if already collected from node
        node_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
        if node_file.exists() and node_file.stat().st_size > 0:
            return None

        api_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
        try:
            cmd = ["kubectl", "logs", pod, "-n", ns, "-c", container,
                   "--timestamps=true"] + since_flag
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and result.stdout:
                api_file.write_bytes(result.stdout)
                return str(api_file)
        except Exception:
            pass

        # Try --previous
        prev_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.previous.log"
        try:
            cmd = ["kubectl", "logs", pod, "-n", ns, "-c", container,
                   "--previous", "--timestamps=true"] + since_flag
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and result.stdout:
                prev_file.write_bytes(result.stdout)
                return str(prev_file)
        except Exception:
            pass

        return None

    api_tasks = []
    for ns in namespaces:
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", ns, "--no-headers",
                 "-o", "custom-columns=:metadata.name,:spec.containers[*].name"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                pod_name = parts[0]
                containers = parts[1].split(",")
                for c in containers:
                    api_tasks.append((ns, pod_name, c.strip()))
        except Exception:
            continue

    print(f"[LogNest] Phase 2: {len(api_tasks)} containers to check")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(collect_pod_api, *t): t
            for t in api_tasks
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                collected += 1

    print(f"[LogNest] Phase 2 done: {collected} files collected")
    return collected


def compress_run():
    """Compress the run directory into a tar.gz archive."""
    log_files = list(RUN_DIR.glob("*.log"))
    if not log_files:
        print("[LogNest] No files to compress — removing empty run dir")
        shutil.rmtree(RUN_DIR, ignore_errors=True)
        return

    zip_file = ZIP_DIR / f"lognest_{TIMESTAMP}.tar.gz"
    try:
        with tarfile.open(zip_file, "w:gz") as tar:
            tar.add(RUN_DIR, arcname=TIMESTAMP)
        print(f"[LogNest] Archive created: {zip_file}")
    except Exception as e:
        print(f"[LogNest] WARN: compression failed: {e}")


def cleanup_capacity():
    """Delete oldest runs if disk usage exceeds threshold."""
    if CAPACITY_THRESHOLD <= 0:
        return
    try:
        stat = os.statvfs("/data")
        used_pct = int((1 - stat.f_bavail / stat.f_blocks) * 100)
    except Exception:
        return

    while used_pct >= CAPACITY_THRESHOLD:
        runs = sorted([d for d in LOGS_DIR.iterdir() if d.is_dir() and d.name != TIMESTAMP])
        if not runs:
            break
        oldest = runs[0]
        print(f"[LogNest] Capacity cleanup: deleting {oldest.name} (disk at {used_pct}%)")
        shutil.rmtree(oldest, ignore_errors=True)
        zip_f = ZIP_DIR / f"lognest_{oldest.name}.tar.gz"
        zip_f.unlink(missing_ok=True)
        try:
            stat = os.statvfs("/data")
            used_pct = int((1 - stat.f_bavail / stat.f_blocks) * 100)
        except Exception:
            break


def cleanup_retention():
    """Delete runs older than RETENTION_MONTHS."""
    cutoff = NOW_EPOCH - (RETENTION_MONTHS * 30 * 86400)
    for d in LOGS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            mtime = int(d.stat().st_mtime)
            if mtime < cutoff:
                print(f"[LogNest] Retention: deleting {d.name}")
                shutil.rmtree(d, ignore_errors=True)
                (ZIP_DIR / f"lognest_{d.name}.tar.gz").unlink(missing_ok=True)
        except Exception:
            continue


# ── Main ──
if __name__ == "__main__":
    total = 0
    total += collect_from_node()
    total += collect_from_api()

    save_offsets(OFFSETS)
    save_last_epoch()

    compress_run()
    cleanup_capacity()
    cleanup_retention()

    try:
        stat = os.statvfs("/data")
        used_pct = int((1 - stat.f_bavail / stat.f_blocks) * 100)
    except Exception:
        used_pct = "?"

    print(f"[LogNest] ============================================")
    print(f"[LogNest] Done. Files: {total}, Disk: {used_pct}%")
    print(f"[LogNest] ============================================")
    sys.exit(0)
