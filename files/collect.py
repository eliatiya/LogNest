#!/usr/bin/env python3
"""
LogNest Collector — Parallel, incremental log collector with rotation support.

This module is the core collection engine for LogNest. It runs as a Kubernetes
CronJob (or on-demand) on each node and performs two-phase log collection:

  Phase 1 (Node-local): Reads container logs directly from /var/log/pods
      (mounted as a hostPath volume). Uses byte-offset tracking to perform
      incremental reads — only new bytes since the last run are collected.
      Handles log rotation (both gzip-compressed and plain rotated files).

  Phase 2 (API fallback): Uses `kubectl logs` to collect logs from pods that
      were not covered by Phase 1 (e.g., pods on other nodes, or containers
      whose node-local logs were already cleaned up by kubelet).

Key design decisions:
  - Byte offsets are persisted in a JSON file so each run only reads NEW data.
  - Rotation detection: if a file shrinks below its saved offset, the file was
    rotated and we reset to read from the beginning.
  - Clock skew tolerance: a 5-minute buffer is subtracted from the last-run
    epoch to avoid missing logs when node clocks drift.
  - A lock file prevents concurrent collector runs (CronJob overlap or manual).
  - Large log files are split into parts at MAX_FILE_SIZE_MB boundaries.
  - All file I/O is streamed in 8 MB chunks to limit memory usage.

Output:
  - Raw logs are written to /data/logs/<timestamp>/<ns>__<pod>__<container>__<ts>.log
  - A tar.gz archive is created in /data/logs_zip/
  - The run is indexed in SQLite (via index_db.py) for instant UI queries.
"""
import os, sys, json, gzip, time, tarfile, shutil, subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ══════════════════════════════════════════════════════════════════════════════
# Configuration — all tuneable via environment variables
# ══════════════════════════════════════════════════════════════════════════════
LOGS_DIR       = Path(os.environ.get("LOGS_DIR", "/data/logs"))          # Where raw log runs are stored
ZIP_DIR        = Path(os.environ.get("ZIP_DIR", "/data/logs_zip"))       # Where tar.gz archives go
NODE_LOGS      = Path("/var/log/pods")                                   # Kubelet's pod log directory (hostPath mount)
STATE_FILE     = Path("/data/.lognest_last_collect")                     # Persists the epoch of the last successful run
OFFSETS_FILE   = Path("/data/.lognest_offsets")                          # JSON map: file path → last-read byte offset
RETENTION_MONTHS    = int(os.environ.get("RETENTION_MONTHS", "1"))       # How many months of runs to keep
CAPACITY_THRESHOLD  = int(os.environ.get("CAPACITY_THRESHOLD", "80"))   # Delete oldest runs when PVC usage exceeds this %
MAX_WORKERS         = int(os.environ.get("COLLECTOR_THREADS", "8"))      # Thread pool size for parallel collection
MAX_FILE_SIZE_MB    = int(os.environ.get("MAX_FILE_SIZE_MB", "100"))    # Split output files larger than this
CHUNK_SIZE          = 8 * 1024 * 1024  # 8 MB read chunks — caps memory usage per file read
TIMESTAMP      = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")            # Unique identifier for this collection run
NOW_EPOCH      = int(time.time())                                        # Current Unix epoch (used for age comparisons)

print(f"[LogNest] ============================================")
print(f"[LogNest] Starting collection at {TIMESTAMP}")
print(f"[LogNest] Node: {os.environ.get('NODE_NAME', 'unknown')}")
print(f"[LogNest] Threads: {MAX_WORKERS}")
print(f"[LogNest] ============================================")


# ══════════════════════════════════════════════════════════════════════════════
# State management — persist collection progress between runs
# ══════════════════════════════════════════════════════════════════════════════
def load_last_epoch():
    """Load the Unix epoch timestamp of the last successful collection run.

    Returns:
        int: The epoch seconds of the last run, or 0 if this is the first run
             or the state file is missing/corrupt.
    """
    try:
        if STATE_FILE.exists():
            return int(STATE_FILE.read_text().strip())
    except Exception:
        pass
    return 0

def save_last_epoch():
    """Persist the current epoch as the 'last successful run' marker.

    Called at the end of a successful collection so the next run knows
    which files have already been processed (by mtime comparison).
    """
    STATE_FILE.write_text(str(NOW_EPOCH))

def load_offsets():
    """Load the byte-offset map from disk.

    The offsets file is a JSON dictionary mapping absolute file paths to the
    number of bytes already read from that file. This enables incremental
    collection — on the next run we seek to the saved offset and only read
    new bytes appended since then.

    Returns:
        dict: Mapping of file path (str) → byte offset (int).
              Empty dict if file is missing or corrupt.
    """
    try:
        if OFFSETS_FILE.exists():
            return json.loads(OFFSETS_FILE.read_text())
    except Exception:
        pass
    return {}

def save_offsets(offsets):
    """Persist the byte-offset map to disk.

    Args:
        offsets (dict): Mapping of file path (str) → byte offset (int).
    """
    OFFSETS_FILE.write_text(json.dumps(offsets))


# ══════════════════════════════════════════════════════════════════════════════
# Collection setup — initialize directories, load state, configure tolerances
# ══════════════════════════════════════════════════════════════════════════════
LAST_EPOCH = load_last_epoch()
OFFSETS = load_offsets()
RUN_DIR = LOGS_DIR / TIMESTAMP       # Each run gets its own timestamped subdirectory
RUN_DIR.mkdir(parents=True, exist_ok=True)
ZIP_DIR.mkdir(parents=True, exist_ok=True)

# Fix #6: Add 5-minute tolerance to LAST_EPOCH to handle clock skew.
# In Kubernetes, node clocks can drift slightly. If the node clock jumped
# backward between runs, files modified during the gap would appear older
# than LAST_EPOCH and be skipped. Subtracting a tolerance window ensures
# we re-check files whose mtime falls within that window.
CLOCK_SKEW_TOLERANCE = 300  # 5 minutes in seconds
LAST_EPOCH_WITH_TOLERANCE = max(0, LAST_EPOCH - CLOCK_SKEW_TOLERANCE)

# Fix #40: Lock file to prevent concurrent collector runs.
# The collector can be triggered by both a CronJob schedule and an on-demand
# Job. Without a lock, two instances could write to the same run directory
# and corrupt offset tracking.
LOCK_FILE = Path("/data/.lognest_collecting")

def acquire_lock():
    """Try to acquire the collection lock file.

    The lock prevents two collector instances from running simultaneously
    (e.g., CronJob overlap or manual trigger during scheduled run).

    A lock is considered stale if it's older than 3 hours (10800 seconds),
    which handles cases where a previous collector crashed without releasing.

    Returns:
        bool: True if the lock was acquired (safe to proceed),
              False if another collector is actively running.
    """
    try:
        if LOCK_FILE.exists():
            # Check if lock is stale (older than 3 hours)
            lock_age = NOW_EPOCH - int(LOCK_FILE.stat().st_mtime)
            if lock_age < 10800:  # 3 hours
                print(f"[LogNest] WARN: Another collector is running (lock age: {lock_age}s). Exiting.")
                return False
            else:
                print(f"[LogNest] Removing stale lock (age: {lock_age}s)")
        LOCK_FILE.write_text(str(NOW_EPOCH))
        return True
    except Exception as e:
        print(f"[LogNest] WARN: Could not acquire lock: {e}")
        return True  # Proceed anyway if lock file can't be created (e.g., read-only FS)

def release_lock():
    """Release the collection lock file.

    Called in a finally block to ensure the lock is always released,
    even if the collector encounters an unhandled exception.
    """
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

# Track what Phase 1 collected to avoid duplicates in Phase 2.
# Phase 2 (API) should not re-collect containers that Phase 1 already handled
# from the node filesystem, unless rotation was detected (in which case
# --previous logs from the API might contain data not on disk).
PHASE1_COLLECTED = set()   # containers fully collected from node
PHASE1_ROTATIONS = set()   # containers where rotation was detected

if LAST_EPOCH == 0:
    print("[LogNest] First run: collecting ALL logs")
else:
    print(f"[LogNest] Incremental: collecting since epoch {LAST_EPOCH} (tolerance: -{CLOCK_SKEW_TOLERANCE}s)")


# ══════════════════════════════════════════════════════════════════════════════
# Split writer — handles output file splitting at size boundaries
# ══════════════════════════════════════════════════════════════════════════════

def get_split_writer(base_path):
    """Create a writer that transparently splits output across multiple files.

    When a single container produces logs larger than MAX_FILE_SIZE_MB, the
    writer automatically rolls over to a new part file (e.g., file.part1.log,
    file.part2.log). This prevents individual log files from becoming too
    large for the UI to handle or for tar.gz compression to be effective.

    Args:
        base_path (Path): The primary output file path. Additional parts will
                          be named with .partN suffix inserted before the extension.

    Returns:
        SplitWriter: An object with write(data), close(), total_size(), and files attributes.
    """
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

    class SplitWriter:
        """Internal writer that manages multiple part files."""

        def __init__(self):
            self.part = 0
            self.current_size = 0
            self.fh = None
            self.files = []
            self._open_next()

        def _open_next(self):
            """Close current file handle and open the next part file."""
            if self.fh:
                self.fh.close()
            # First part uses the base filename; subsequent parts get .partN suffix
            if self.part == 0:
                path = base_path
            else:
                stem = base_path.stem
                path = base_path.with_name(f"{stem}.part{self.part}{base_path.suffix}")
            self.fh = open(path, 'ab')
            self.files.append(path)
            self.current_size = path.stat().st_size if path.exists() else 0

        def write(self, data):
            """Write data, splitting to a new file if max size is exceeded.

            Args:
                data (str or bytes): Content to write. Strings are encoded as UTF-8.
            """
            if isinstance(data, str):
                data = data.encode('utf-8', errors='replace')
            remaining = data
            while remaining:
                space = max_bytes - self.current_size
                if space <= 0:
                    # Current file is full — roll over to next part
                    self.part += 1
                    self._open_next()
                    space = max_bytes
                chunk = remaining[:space]
                self.fh.write(chunk)
                self.current_size += len(chunk)
                remaining = remaining[len(chunk):]

        def close(self):
            """Flush and close the current file handle."""
            if self.fh:
                self.fh.close()

        def total_size(self):
            """Return the combined size of all part files in bytes."""
            return sum(f.stat().st_size for f in self.files if f.exists())

    return SplitWriter()


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Node-local collection (direct filesystem reads)
# ══════════════════════════════════════════════════════════════════════════════

def collect_container_from_node(container_dir, ns, pod, container):
    """Collect logs from a single container's node-local log directory.

    Reads both rotated log files (0.log.YYYYMMDD-*, *.gz) and the active
    log file (0.log) using byte-offset tracking for incremental reads.

    The kubelet writes container stdout/stderr to:
        /var/log/pods/<ns>_<pod>_<uid>/<container>/0.log

    When the log is rotated, kubelet renames 0.log → 0.log.<timestamp> (or
    compresses it to 0.log.<timestamp>.gz) and creates a fresh 0.log.

    Strategy:
      1. Process rotated files first (they contain older data).
         - Skip bytes we already read before rotation (using saved offset).
      2. Process the active 0.log file incrementally (seek to saved offset).
      3. Detect rotation mid-run: if file size < saved offset, the file was
         rotated and we reset to read from byte 0.

    Args:
        container_dir (Path): Path to the container's log directory
                              (e.g., /var/log/pods/ns_pod_uid/container/).
        ns (str): Kubernetes namespace.
        pod (str): Pod name.
        container (str): Container name.

    Returns:
        str or None: Path to the output log file if data was collected,
                     None if no new data was found.
    """
    out_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
    writer = get_split_writer(out_file)
    collected = False
    rotation_detected = False

    try:
        # ── Step 1: Process rotated log files ──
        # Rotated files are old versions of 0.log that kubelet renamed.
        # They may be gzip-compressed (.gz) or plain text (.log.YYYYMMDD-*).
        rotated = sorted([
            f for f in container_dir.iterdir()
            if f.name.startswith("0.log.") or (f.suffix == '.gz' and '.log.' in f.name)
        ], key=lambda f: f.name)

        # The saved offset for the active log tells us how much of the file
        # we already read BEFORE it was rotated. The most recent rotated file
        # IS the old 0.log, so we can skip that many bytes from it.
        active_log_path = container_dir / "0.log"
        active_key = str(active_log_path)
        prev_active_offset = OFFSETS.get(active_key, 0)

        for rot in rotated:
            file_mtime = int(rot.stat().st_mtime)
            # Skip rotated files older than our last run (already collected)
            if file_mtime <= LAST_EPOCH_WITH_TOLERANCE:
                continue
            rotation_detected = True

            # ── Skip logic for rotated files ──
            # Determine how many bytes to skip (already collected before rotation).
            # Only apply the saved offset to the MOST RECENT rotated file because
            # that's the one that was 0.log during our last run. Older rotated
            # files should be read in full (they were rotated before our last run
            # and we never tracked offsets for them).
            rot_size = rot.stat().st_size
            skip_bytes = 0

            # Heuristic: if the rotated file's size >= our saved offset AND it's
            # the most recent rotated file (last in sorted list with mtime > LAST_EPOCH),
            # then it's likely the file we were tracking as 0.log.
            if prev_active_offset > 0 and rot_size >= prev_active_offset:
                # Check if this is the most recent rotated file (closest to last run)
                # by checking if it's the last in the sorted list with mtime > LAST_EPOCH
                recent_rotated = [r for r in rotated if int(r.stat().st_mtime) > LAST_EPOCH]
                if recent_rotated and rot == recent_rotated[-1]:
                    skip_bytes = prev_active_offset
                    # Clear the offset so we don't apply it again to another file
                    prev_active_offset = 0

            try:
                if rot.suffix == '.gz':
                    # Gzip files must be decompressed sequentially — can't seek directly.
                    # We read and discard `skip_bytes` worth of decompressed data first.
                    with gzip.open(rot, 'rb') as gz:
                        # Skip already-collected bytes (read and discard)
                        skipped = 0
                        while skipped < skip_bytes:
                            to_skip = min(CHUNK_SIZE, skip_bytes - skipped)
                            data = gz.read(to_skip)
                            if not data:
                                break
                            skipped += len(data)
                        # Read the rest (new data only) in chunks
                        while True:
                            chunk = gz.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            writer.write(chunk)
                            collected = True
                    if skip_bytes > 0:
                        print(f"[LogNest]   ├─ Rotated (gz): {rot.name} (skipped {skip_bytes} already-collected bytes)")
                    else:
                        print(f"[LogNest]   ├─ Rotated (gz): {rot.name}")
                else:
                    # Plain text rotated file — can seek directly to skip offset
                    with open(rot, 'rb') as fh:
                        if skip_bytes > 0:
                            fh.seek(skip_bytes)  # Jump past already-collected bytes
                        while True:
                            chunk = fh.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            writer.write(chunk)
                            collected = True
                    if skip_bytes > 0:
                        print(f"[LogNest]   ├─ Rotated (plain): {rot.name} (skipped {skip_bytes} already-collected bytes)")
                    else:
                        print(f"[LogNest]   ├─ Rotated (plain): {rot.name}")
            except Exception as e:
                print(f"[LogNest]   ├─ WARN: {rot.name}: {e}")

        # ── Step 2: Process the active log file (0.log) ──
        # The active file is what kubelet is currently writing to.
        # We use byte-offset tracking: seek to where we left off last time
        # and read only the newly appended bytes.
        active_logs = sorted([
            f for f in container_dir.iterdir()
            if f.suffix == '.log' and '.log.' not in f.name
        ])

        for log_file in active_logs:
            file_key = str(log_file)
            current_size = log_file.stat().st_size
            prev_offset = OFFSETS.get(file_key, 0)

            # ── Rotation detection ──
            # If the file is now SMALLER than our saved offset, it means kubelet
            # rotated the old file away and created a fresh 0.log. Reset offset
            # to 0 so we read the entire new file from the beginning.
            if current_size < prev_offset:
                rotation_detected = True
                prev_offset = 0  # Reset — read from beginning of new file
                print(f"[LogNest]   ├─ ROTATION detected: {log_file.name} (was {prev_offset}, now {current_size})")

            # Only read if there are new bytes beyond our saved offset
            if current_size > prev_offset:
                new_bytes = current_size - prev_offset
                try:
                    with open(log_file, 'rb') as fh:
                        fh.seek(prev_offset)  # Jump to where we left off
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

                # Update the offset to the current file size for next run
                OFFSETS[file_key] = current_size
            else:
                print(f"[LogNest]   ├─ Active: {log_file.name} (no new data)")

    except Exception as e:
        print(f"[LogNest] ERROR: {ns}/{pod}/{container}: {e}")

    writer.close()

    # ── Post-processing: keep or discard the output file ──
    total = writer.total_size()
    if collected and total > 0:
        parts = len(writer.files)
        print(f"[LogNest]   └─ ✓ {ns}/{pod}/{container} → {total} bytes ({parts} file{'s' if parts > 1 else ''})")
        # Mark container as collected so Phase 2 doesn't duplicate the work
        PHASE1_COLLECTED.add(f"{ns}__{pod}__{container}")
        if rotation_detected:
            PHASE1_ROTATIONS.add(f"{ns}__{pod}__{container}")
        return str(out_file)
    else:
        # No new data — remove the empty output file(s)
        for f in writer.files:
            f.unlink(missing_ok=True)
        # Still mark as "seen" so Phase 2 doesn't re-collect this container.
        # The container exists on this node; Phase 1 checked it; nothing new.
        PHASE1_COLLECTED.add(f"{ns}__{pod}__{container}")
        return None


def collect_from_node():
    """Phase 1: Collect logs directly from the node filesystem using a thread pool.

    Iterates over /var/log/pods/<ns>_<pod>_<uid>/<container>/ directories and
    dispatches each container to a worker thread for parallel collection.

    The directory structure under /var/log/pods is:
        <namespace>_<pod-name>_<pod-uid>/
            <container-name>/
                0.log           (active log file)
                0.log.20240101  (rotated, plain text)
                0.log.20240101.gz (rotated, compressed)

    Returns:
        int: Number of containers that had new log data collected.
    """
    if not NODE_LOGS.is_dir():
        print(f"[LogNest] WARN: {NODE_LOGS} not mounted — skipping")
        return 0

    tasks = []
    for ns_pod_dir in NODE_LOGS.iterdir():
        if not ns_pod_dir.is_dir():
            continue
        # Directory name format: <namespace>_<pod-name>_<pod-uid>
        parts = ns_pod_dir.name.split("_")
        if len(parts) < 2:
            continue
        ns = parts[0]
        pod = parts[1]

        # Each subdirectory is a container name
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
    """Phase 2: Collect logs via the Kubernetes API for pods not covered by Phase 1.

    This phase acts as a fallback/complement to node-local collection:
      - Collects logs from pods on OTHER nodes (not mounted locally).
      - Retrieves --previous logs for containers where rotation was detected
        in Phase 1 (the rotated file may have been deleted from disk before
        Phase 1 could read it, but the API still has it).
      - Skips containers already fully collected by Phase 1 (no rotation).

    Uses `kubectl logs` with --since flag for incremental collection and
    --timestamps=true for consistent timestamp formatting.

    Returns:
        int: Number of containers that had new log data collected via API.
    """
    print("[LogNest] Phase 2: kubectl API collection")
    collected = 0

    try:
        # Get all namespaces in the cluster
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

    # Build --since flag for incremental API collection.
    # Add 60 seconds of overlap to avoid missing logs at the boundary.
    since_flag = []
    if LAST_EPOCH > 0:
        since_secs = NOW_EPOCH - LAST_EPOCH + 60  # +60s overlap for safety
        since_flag = [f"--since={since_secs}s"]

    def collect_pod_api(ns, pod, container):
        """Collect logs for a single container via kubectl API.

        Args:
            ns (str): Namespace.
            pod (str): Pod name.
            container (str): Container name.

        Returns:
            str or None: Path to output file if data was collected, None otherwise.
        """
        container_key = f"{ns}__{pod}__{container}"

        # Skip if Phase 1 already collected this container (and no rotation concern).
        # No point calling the API for something we already have from disk.
        if container_key in PHASE1_COLLECTED and container_key not in PHASE1_ROTATIONS:
            return None

        # Also skip if output file already exists from Phase 1 (file-based check)
        existing_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"
        if existing_file.exists() and existing_file.stat().st_size > 0:
            return None

        # If Phase 1 collected it WITH rotation, we only fetch --previous logs
        # to catch data that was in a deleted rotated file (not on disk anymore)
        only_previous = container_key in PHASE1_COLLECTED

        api_file = RUN_DIR / f"{ns}__{pod}__{container}__{TIMESTAMP}.log"

        if not only_previous:
            # Collect current logs (only if Phase 1 didn't get them from disk)
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

        # Always try --previous as safety net for rotated/deleted logs.
        # The API retains the previous container's logs even after rotation,
        # which may not be available on the node filesystem anymore.
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

    # Enumerate all pods and their containers across all namespaces
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
    """Compress the current run directory into a tar.gz archive.

    Creates a gzip-compressed tar archive of all .log files in the run
    directory. The archive is stored in ZIP_DIR for long-term storage
    and efficient transfer.

    If no log files were collected (empty run), the run directory is
    removed entirely to avoid cluttering the filesystem.
    """
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
    """Delete oldest runs if total data usage exceeds the PVC capacity threshold.

    Compares the total size of all files under /data against a percentage
    threshold of the PVC's total capacity (from PVC_SIZE env var). If usage
    exceeds the threshold, the oldest run directories are deleted one at a
    time until usage drops below the threshold.

    This prevents the PVC from filling up completely, which would cause
    kubelet to evict the pod.
    """
    if CAPACITY_THRESHOLD <= 0:
        return

    # Get PVC size from env (in Gi) — default 150Gi. Convert to bytes.
    pvc_size_str = os.environ.get("PVC_SIZE", "150Gi")
    pvc_bytes = int(pvc_size_str.replace("Gi", "")) * 1024 * 1024 * 1024

    # Calculate the byte threshold at which we start deleting
    threshold_bytes = int(pvc_bytes * CAPACITY_THRESHOLD / 100)

    def get_data_size():
        """Calculate total bytes used by all files under /data."""
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

    # Delete oldest runs one at a time until we're below threshold
    while used >= threshold_bytes:
        # Sort run directories by name (which is a timestamp) — oldest first
        runs = sorted([d for d in LOGS_DIR.iterdir() if d.is_dir() and d.name != TIMESTAMP])
        if not runs:
            break
        oldest = runs[0]
        print(f"[LogNest] Capacity cleanup: deleting {oldest.name} (data at {used_pct}% of PVC)")
        shutil.rmtree(oldest, ignore_errors=True)
        # Also remove the corresponding archive
        zip_f = ZIP_DIR / f"lognest_{oldest.name}.tar.gz"
        zip_f.unlink(missing_ok=True)
        used = get_data_size()
        used_pct = int(used / pvc_bytes * 100) if pvc_bytes > 0 else 0


def cleanup_retention():
    """Delete runs older than RETENTION_MONTHS — one at a time per collector run.

    Uses a gradual deletion strategy: only the single oldest expired run is
    removed per collector invocation. This spreads I/O load across multiple
    runs rather than doing a bulk delete that could spike disk latency.

    Also removes the corresponding entry from the SQLite index so the UI
    doesn't show stale data.
    """
    # Calculate the cutoff epoch: anything older than this is expired
    cutoff = NOW_EPOCH - (RETENTION_MONTHS * 30 * 86400)  # Approximate months as 30 days
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


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point — orchestrates the full collection pipeline
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Fix #40: Acquire lock to prevent concurrent collector runs
    if not acquire_lock():
        sys.exit(0)

    try:
        total = 0
        # Phase 1: Node-local filesystem collection (fast, incremental)
        total += collect_from_node()
        # Phase 2: API-based collection (fallback for pods not on this node)
        if os.environ.get("ENABLE_API_PHASE", "true").lower() in ("true", "1", "yes"):
            total += collect_from_api()
        else:
            print("[LogNest] Phase 2: SKIPPED (enableApiPhase=false)")

        # Persist state for next run
        save_offsets(OFFSETS)
        save_last_epoch()

        # Compress collected logs into a tar.gz archive
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

        # Housekeeping: enforce capacity and retention limits
        cleanup_capacity()
        cleanup_retention()

        # Fix #5: Clean dead entries from offsets file.
        # Over time, containers get deleted and their log paths disappear.
        # Stale offset entries waste memory and could cause confusion if
        # a new container reuses the same path.
        dead_keys = [k for k in OFFSETS if not Path(k).exists()]
        if dead_keys:
            for k in dead_keys:
                del OFFSETS[k]
            save_offsets(OFFSETS)
            print(f"[LogNest] Cleaned {len(dead_keys)} dead offset entries")

        # ── Summary: calculate and display PVC usage stats ──
        try:
            pvc_used = 0
            for f in Path("/data").rglob("*"):
                if f.is_file():
                    try:
                        pvc_used += f.stat().st_size
                    except Exception:
                        pass
            pvc_str = ""
            pvc_bytes = pvc_used
            # Convert bytes to human-readable format (B → KB → MB → GB → TB)
            for unit in ["B", "KB", "MB", "GB"]:
                if pvc_bytes < 1024:
                    pvc_str = f"{pvc_bytes:.1f} {unit}"
                    break
                pvc_bytes /= 1024
            else:
                pvc_str = f"{pvc_bytes:.1f} TB"

            # PVC capacity from env var
            pvc_cap_str = os.environ.get("PVC_SIZE", "150Gi")
            pvc_cap_gb = int(pvc_cap_str.replace("Gi", "")) if "Gi" in pvc_cap_str else 150
            pvc_used_gb = pvc_used / (1024**3)
            pvc_pct = int(pvc_used_gb / pvc_cap_gb * 100) if pvc_cap_gb > 0 else 0
        except Exception:
            pvc_str = "?"; pvc_pct = "?"; pvc_cap_gb = "?"

        print(f"[LogNest] ============================================")
        print(f"[LogNest] Done. Files: {total}")
        print(f"[LogNest] PVC usage: {pvc_str} / {pvc_cap_gb}Gi ({pvc_pct}%)")
        print(f"[LogNest] ============================================")

    finally:
        release_lock()  # Fix #40: Always release lock, even on error

    sys.exit(0)
