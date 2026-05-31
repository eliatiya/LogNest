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
MAX_FILE_SIZE_MB    = int(os.environ.get("MAX_FILE_SIZE_MB", "100"))  # Split files larger than this
CHUNK_SIZE          = 8 * 1024 * 1024  # 8MB read chunks — never load more than this into memory
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

# Track what Phase 1 collected to avoid duplicates in Phase 2
PHASE1_COLLECTED = set()   # containers fully collected from node
PHASE1_ROTATIONS = set()   # containers where rotation was detected

if LAST_EPOCH == 0:
    print("[LogNest] First run: collecting ALL logs")
else:
    print(f"[LogNest] Incremental: collecting since epoch {LAST_EPOCH}")


def get_split_writer(base_path):
    """Returns a writer that splits output into multiple files at MAX_FILE_SIZE_MB."""
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

    class SplitWriter:
        def __init__(self):
            self.part = 0
            self.current_size = 0
            self.fh = None
            self.files = []
            self._open_next()

        def _open_next(self):
            if self.fh:
                self.fh.close()
            if self.part == 0:
                path = base_path
            else:
                stem = base_path.stem
                path = base_path.with_name(f"{stem}.part{self.part}{base_path.suffix}")
            self.fh = open(path, 'ab')
            self.files.append(path)
            self.current_size = path.stat().st_size if path.exists() else 0

        def write(self, data):
            if isinstance(data, str):
                data = data.encode('utf-8', errors='replace')
            remaining = data
            while remaining:
                space = max_bytes - self.current_size
                if space <= 0:
                    self.part += 1
                    self._open_next()
                    space = max_bytes
                chunk = remaining[:space]
                self.fh.write(chunk)
                self.current_size += len(chunk)
                remaining = remaining[len(chunk):]

        def close(self):
            if self.fh:
                self.fh.close()

        def total_size(self):
            return sum(f.stat().st_size for f in self.files if f.exists())

    return SplitWriter()


def collect_container_from_node(container_dir, ns, pod, container):
    """Collect logs from a single container's node directory. Streams in chunks."""
    out_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
    writer = get_split_writer(out_file)
    collected = False
    rotation_detected = False

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
            rotation_detected = True
            try:
                if rot.suffix == '.gz':
                    with gzip.open(rot, 'rb') as gz:
                        while True:
                            chunk = gz.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            writer.write(chunk)
                            collected = True
                    print(f"[LogNest]   ├─ Rotated (gz): {rot.name}")
                else:
                    with open(rot, 'rb') as fh:
                        while True:
                            chunk = fh.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            writer.write(chunk)
                            collected = True
                    print(f"[LogNest]   ├─ Rotated (plain): {rot.name}")
            except Exception as e:
                print(f"[LogNest]   ├─ WARN: {rot.name}: {e}")

        # 2. Active log file — incremental by byte offset, streamed in chunks
        active_logs = sorted([
            f for f in container_dir.iterdir()
            if f.suffix == '.log' and '.log.' not in f.name
        ])

        for log_file in active_logs:
            file_key = str(log_file)
            current_size = log_file.stat().st_size
            prev_offset = OFFSETS.get(file_key, 0)

            # Detect rotation: file is smaller than our saved offset
            if current_size < prev_offset:
                rotation_detected = True
                prev_offset = 0  # Reset — read from beginning of new file
                print(f"[LogNest]   ├─ ROTATION detected: {log_file.name} (was {prev_offset}, now {current_size})")

            if current_size > prev_offset:
                new_bytes = current_size - prev_offset
                try:
                    with open(log_file, 'rb') as fh:
                        fh.seek(prev_offset)
                        bytes_read = 0
                        while bytes_read < new_bytes:
                            to_read = min(CHUNK_SIZE, new_bytes - bytes_read)
                            chunk = fh.read(to_read)
                            if not chunk:
                                break
                            writer.write(chunk)
                            bytes_read += len(chunk)
                    collected = True
                    print(f"[LogNest]   ├─ Active: {log_file.name} +{new_bytes} bytes (offset {prev_offset} → {current_size})")
                except Exception as e:
                    print(f"[LogNest]   ├─ WARN: {log_file.name}: {e}")

                OFFSETS[file_key] = current_size
            else:
                print(f"[LogNest]   ├─ Active: {log_file.name} (no new data)")

    except Exception as e:
        print(f"[LogNest] ERROR: {ns}/{pod}/{container}: {e}")

    writer.close()

    total = writer.total_size()
    if collected and total > 0:
        parts = len(writer.files)
        print(f"[LogNest]   └─ ✓ {ns}/{pod}/{container} → {total} bytes ({parts} file{'s' if parts > 1 else ''})")
        # Track that this container was fully collected from node
        PHASE1_COLLECTED.add(f"{ns}__{pod}__{container}")
        if rotation_detected:
            PHASE1_ROTATIONS.add(f"{ns}__{pod}__{container}")
        return str(out_file)
    else:
        for f in writer.files:
            f.unlink(missing_ok=True)
        # Even if no new data, mark as "seen" so Phase 2 doesn't re-collect
        # (the container exists on this node, Phase 1 checked it, nothing new)
        PHASE1_COLLECTED.add(f"{ns}__{pod}__{container}")
        return None


def collect_from_node():
    """Phase 1: Collect from /var/log/pods and watcher backup using thread pool."""
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
        container_key = f"{ns}__{pod}__{container}"

        # Skip if Phase 1 already collected this container (and no rotation concern)
        if container_key in PHASE1_COLLECTED and container_key not in PHASE1_ROTATIONS:
            return None

        # Also skip if output file already exists from Phase 1 (file-based check)
        existing_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
        if existing_file.exists() and existing_file.stat().st_size > 0:
            return None

        # If Phase 1 collected it WITH rotation, we still check --previous
        # to catch any logs that were in a deleted rotated file
        only_previous = container_key in PHASE1_COLLECTED

        api_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"

        if not only_previous:
            # Collect current logs (only if Phase 1 didn't get them)
            try:
                cmd = ["kubectl", "logs", pod, "-n", ns, "-c", container,
                       "--timestamps=true"] + since_flag
                result = subprocess.run(cmd, capture_output=True, timeout=300)
                if result.returncode == 0 and result.stdout:
                    api_file.write_bytes(result.stdout)
                    print(f"[LogNest]   └─ ✓ {ns}/{pod}/{container} → {len(result.stdout)} bytes (API)")
                    return str(api_file)
            except Exception as e:
                print(f"[LogNest]   ├─ WARN: {ns}/{pod}/{container}: {e}")

        # Always try --previous as safety net for rotated/deleted logs
        prev_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.previous.log"
        try:
            cmd = ["kubectl", "logs", pod, "-n", ns, "-c", container,
                   "--previous", "--timestamps=true"] + since_flag
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and result.stdout:
                prev_file.write_bytes(result.stdout)
                print(f"[LogNest]   └─ ✓ {ns}/{pod}/{container} → {len(result.stdout)} bytes (API/previous)")
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
    """Delete oldest runs if LogNest data exceeds threshold % of PVC size."""
    if CAPACITY_THRESHOLD <= 0:
        return

    # Get PVC size from env (in Gi) — default 150Gi
    pvc_size_str = os.environ.get("PVC_SIZE", "150Gi")
    pvc_bytes = int(pvc_size_str.replace("Gi", "")) * 1024 * 1024 * 1024

    threshold_bytes = int(pvc_bytes * CAPACITY_THRESHOLD / 100)

    def get_data_size():
        total = 0
        for f in Path("/data").rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except Exception:
                    pass
        return total

    used = get_data_size()
    used_pct = int(used / pvc_bytes * 100) if pvc_bytes > 0 else 0

    while used >= threshold_bytes:
        runs = sorted([d for d in LOGS_DIR.iterdir() if d.is_dir() and d.name != TIMESTAMP])
        if not runs:
            break
        oldest = runs[0]
        print(f"[LogNest] Capacity cleanup: deleting {oldest.name} (data at {used_pct}% of PVC)")
        shutil.rmtree(oldest, ignore_errors=True)
        zip_f = ZIP_DIR / f"lognest_{oldest.name}.tar.gz"
        zip_f.unlink(missing_ok=True)
        used = get_data_size()
        used_pct = int(used / pvc_bytes * 100) if pvc_bytes > 0 else 0


def cleanup_retention():
    """Delete runs older than RETENTION_MONTHS — gradually, max 1 oldest per run."""
    cutoff = NOW_EPOCH - (RETENTION_MONTHS * 30 * 86400)
    expired = []
    for d in LOGS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            mtime = int(d.stat().st_mtime)
            if mtime < cutoff:
                expired.append((mtime, d))
        except Exception:
            continue

    if not expired:
        return

    # Sort by age (oldest first) and delete only the oldest one
    expired.sort(key=lambda x: x[0])
    oldest = expired[0][1]
    print(f"[LogNest] Retention: deleting oldest expired run {oldest.name} (1 of {len(expired)} expired)")
    shutil.rmtree(oldest, ignore_errors=True)
    (ZIP_DIR / f"lognest_{oldest.name}.tar.gz").unlink(missing_ok=True)

    # Also remove from SQLite index
    try:
        sys.path.insert(0, "/scripts")
        from index_db import remove_run
        remove_run(oldest.name)
    except Exception:
        pass


# ── Main ──
if __name__ == "__main__":
    total = 0
    total += collect_from_node()
    total += collect_from_api()

    save_offsets(OFFSETS)
    save_last_epoch()

    compress_run()
    
    # Index this run in SQLite for instant UI queries
    try:
        sys.path.insert(0, "/scripts")
        from index_db import init_db, index_run, index_archive
        init_db()
        if RUN_DIR.exists() and any(RUN_DIR.glob("*.log")):
            index_run(TIMESTAMP, str(RUN_DIR), TIMESTAMP)
            print(f"[LogNest] Indexed run in SQLite")
        zip_file = ZIP_DIR / f"lognest_{TIMESTAMP}.tar.gz"
        if zip_file.exists():
            index_archive(zip_file.name, zip_file.stat().st_size)
    except Exception as e:
        print(f"[LogNest] WARN: indexing failed: {e}")

    cleanup_capacity()
    cleanup_retention()

    try:
        # PVC usage: actual LogNest data size
        pvc_used = 0
        for f in Path("/data").rglob("*"):
            if f.is_file():
                try:
                    pvc_used += f.stat().st_size
                except Exception:
                    pass
        pvc_str = ""
        pvc_bytes = pvc_used
        for unit in ["B", "KB", "MB", "GB"]:
            if pvc_bytes < 1024:
                pvc_str = f"{pvc_bytes:.1f} {unit}"
                break
            pvc_bytes /= 1024
        else:
            pvc_str = f"{pvc_bytes:.1f} TB"

        # NFS disk: underlying filesystem usage
        stat = os.statvfs("/data")
        nfs_total = stat.f_blocks * stat.f_frsize
        nfs_used = (stat.f_blocks - stat.f_bavail) * stat.f_frsize
        nfs_pct = int(nfs_used / nfs_total * 100) if nfs_total > 0 else 0
        nfs_total_gb = nfs_total / (1024**3)
        nfs_used_gb = nfs_used / (1024**3)
    except Exception:
        pvc_str = "?"
        nfs_pct = "?"
        nfs_used_gb = "?"
        nfs_total_gb = "?"

    print(f"[LogNest] ============================================")
    print(f"[LogNest] Done. Files: {total}")
    print(f"[LogNest] PVC data used: {pvc_str}")
    print(f"[LogNest] NFS disk: {nfs_used_gb:.1f}GB / {nfs_total_gb:.1f}GB ({nfs_pct}%)")
    print(f"[LogNest] ============================================")
    sys.exit(0)
