# 🪺 LogNest

[![Helm](https://img.shields.io/badge/Helm-v3-blue?logo=helm)](https://helm.sh)
[![RKE2](https://img.shields.io/badge/RKE2-Ready-green?logo=kubernetes)](https://docs.rke2.io)
[![Air-Gap](https://img.shields.io/badge/Air--Gap-Compatible-orange)](https://github.com/eliatiya/LogNest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Production-ready Kubernetes log collection, compression, and web dashboard — deployed as a single Helm chart.**

---

## Overview

LogNest is a Helm chart that deploys an automated log collection pipeline for Kubernetes clusters. It collects container logs incrementally from node filesystems and the kubectl API, compresses them into archives, and serves them through a modern web dashboard with search, filtering, and download capabilities.

Designed for RKE2 clusters in air-gapped environments, LogNest requires no external dependencies beyond NFS storage. It handles log rotation, tracks byte offsets for incremental collection, and provides capacity-based cleanup to prevent storage exhaustion.

| Feature | Description |
|---------|-------------|
| **Incremental Collection** | Byte-offset tracking — only new log data is collected each cycle |
| **Dual-Phase Collection** | Phase 1: node filesystem (`/var/log/pods`), Phase 2: kubectl API |
| **Log Rotation Handling** | Detects rotated files (`.gz` + plain), avoids duplicates |
| **Compression** | Each run is archived as `.tar.gz` for long-term storage |
| **Web Dashboard** | Real-time stats, log viewer with level filtering, multi-file download |
| **SQLite Index** | Instant UI queries without scanning NFS on every request |
| **Air-Gap Ready** | No internet required at runtime; all images pre-bundled |
| **Capacity Cleanup** | Auto-deletes oldest runs when PVC usage exceeds threshold |
| **Gradual Retention** | Removes 1 oldest expired run per cycle (no sudden data loss) |
| **Multi-Node Support** | DaemonSet mode for clusters with multiple worker nodes |
| **On-Demand Collection** | Trigger immediate collection from the UI |
| **RBAC Minimal** | Read-only access to pods/logs, no secrets in chart |

---

## Architecture

```
                    Every 4 hours (CronJob) or always (DaemonSet)
                                    |
                                    v
    +-------------------------------------------------------+
    |              COLLECTOR (Python, 8 threads)            |
    |                                                       |
    |  Phase 1: Read /var/log/pods (node disk, fast)        |
    |  Phase 2: kubectl logs API (multi-node safety net)    |
    |                                                       |
    |  Features:                                            |
    |  - Byte-offset incremental (only new data)            |
    |  - Rotation detection (.gz + plain)                   |
    |  - 8MB chunked streaming (constant memory)            |
    |  - File splitting at 100MB                            |
    +-------------------------------------------------------+
                                    |
                                    v
    +-------------------------------------------------------+
    |              NFS PVC (150Gi, ReadWriteMany)           |
    |                                                       |
    |  /logs/          raw .log files per run               |
    |  /logs_zip/      compressed .tar.gz archives          |
    |  /.lognest_*     state (offsets, epoch, SQLite)       |
    +-------------------------------------------------------+
                                    ^
                                    |
    +-------------------------------------------------------+
    |              WEB UI (Flask + Gunicorn)                |
    |                                                       |
    |  - Dashboard with stats + log viewer                  |
    |  - Search across all runs (SQLite index)              |
    |  - Multi-pod merged view (sorted by timestamp)        |
    |  - Download: single / multi-select / zip              |
    |  - On-demand collection trigger                       |
    |  - Namespace filtering                                |
    +-------------------------------------------------------+
                                    |
                                    v
    +-------------------------------------------------------+
    |  Service:8080 --> Ingress (nginx)                     |
    |                   lognest.example.com                 |
    +-------------------------------------------------------+
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/eliatiya/LogNest.git
cd LogNest
```

### 2. Configure values.yaml

Edit `values.yaml` to match your environment:

```yaml
storage:
  nfsServer: "10.0.0.50"          # Your NFS server IP
  nfsPath: "/exports/lognest"     # NFS export path

ingress:
  host: "lognest.mycompany.com"   # Your ingress hostname
```

### 3. Build the UI image (if not using Docker Hub)

```bash
./docker/build.sh registry.internal:5000
```

### 4. Install the chart

```bash
helm install lognest . \
  --namespace lognest \
  --create-namespace \
  -f values.yaml
```

### 5. Access the dashboard

```bash
# Via ingress
open https://lognest.mycompany.com

# Or via port-forward
kubectl port-forward svc/lognest-ui 8080:8080 -n lognest
open http://localhost:8080
```

---

## Air-Gap Installation

Complete guide for deploying LogNest in environments without internet access.

### Step 1: Pull all images (internet-connected machine)

```bash
docker pull alpine/k8s:1.30.2
docker pull eliezer1234/lognest-ui:1.0.0
```

### Step 2: Save images to tar

```bash
docker save -o lognest-images.tar alpine/k8s:1.30.2 eliezer1234/lognest-ui:1.0.0
```

### Step 3: Package the Helm chart

```bash
helm package .
# Creates: lognest-1.0.0.tgz
```

### Step 4: Transfer to air-gap machine

Copy both files to the air-gapped environment:
- `lognest-images.tar` (container images)
- `lognest-1.0.0.tgz` (Helm chart)

### Step 5: Load images

```bash
docker load -i lognest-images.tar
```

### Step 6: Push to private registry

**Option A: Private registry (recommended)**

```bash
# Tag for your registry
docker tag alpine/k8s:1.30.2 registry.internal:5000/alpine/k8s:1.30.2
docker tag eliezer1234/lognest-ui:1.0.0 registry.internal:5000/eliezer1234/lognest-ui:1.0.0

# Push
docker push registry.internal:5000/alpine/k8s:1.30.2
docker push registry.internal:5000/eliezer1234/lognest-ui:1.0.0
```

Then set in `values.yaml`:

```yaml
global:
  imageRegistry: "registry.internal:5000"
```

**Option B: Local images (single-node / dev)**

If images are loaded directly on the node, set `imagePullPolicy: Never`:

```yaml
collector:
  image:
    pullPolicy: Never
ui:
  image:
    pullPolicy: Never
```

### Step 7: Install from packaged chart

```bash
helm install lognest lognest-1.0.0.tgz \
  -f values.yaml \
  --namespace lognest \
  --create-namespace
```

> **Helper script:** You can also use `./scripts/pull-push-images.sh registry.internal:5000` to automate pulling, tagging, and pushing all images listed in `images.txt`.

---

## Configuration Reference

### Global

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.imageRegistry` | Private registry prefix for all images | `""` |
| `global.imagePullSecrets` | Array of image pull secret names | `[]` |
| `namespace.name` | Namespace to deploy into | `lognest` |

### Collector

| Parameter | Description | Default |
|-----------|-------------|---------|
| `collector.mode` | Deployment mode: `cronjob` or `daemonset` | `cronjob` |
| `collector.enableApiPhase` | Enable Phase 2 kubectl API collection | `false` |
| `collector.schedule1` | Primary cron schedule | `"0 */4 * * *"` |
| `collector.schedule2` | Secondary cron schedule (empty to disable) | `""` |
| `collector.allNamespaces` | Collect from all namespaces | `true` |
| `collector.namespaces` | Specific namespaces (when `allNamespaces: false`) | `[]` |
| `collector.retentionMonths` | Months to retain logs before deletion | `1` |
| `collector.capacityThresholdPercent` | Delete oldest runs when PVC usage exceeds this % | `80` |
| `collector.image.repository` | Collector image repository | `alpine/k8s` |
| `collector.image.tag` | Collector image tag | `"1.30.2"` |
| `collector.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `collector.resources.requests.cpu` | CPU request | `"100m"` |
| `collector.resources.requests.memory` | Memory request | `"256Mi"` |
| `collector.resources.limits.cpu` | CPU limit | `"1000m"` |
| `collector.resources.limits.memory` | Memory limit | `"1Gi"` |
| `collector.nodeSelector` | Node selector for collector pods | `{}` |
| `collector.tolerations` | Tolerations (includes control-plane by default) | See values.yaml |
| `collector.affinity` | Affinity rules | `{}` |

### Storage

| Parameter | Description | Default |
|-----------|-------------|---------|
| `storage.nfsServer` | NFS server address | `"127.0.0.1"` |
| `storage.nfsPath` | NFS exported path | `"/exports/lognest"` |
| `storage.storageClassName` | StorageClass name (NFS provisioner) | `nfs-storage` |
| `storage.pvc.name` | PVC name | `pvc-lognest` |
| `storage.pvc.size` | PVC size | `150Gi` |
| `storage.pvc.accessMode` | PVC access mode | `ReadWriteMany` |
| `storage.pvc.nfsSubPath` | NFS subdirectory name | `"lognest-data-pvc"` |
| `storage.logsDir` | Subdirectory for raw logs inside PVC | `"logs"` |
| `storage.logsZipDir` | Subdirectory for archives inside PVC | `"logs_zip"` |

### UI

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ui.replicaCount` | Number of UI replicas | `1` |
| `ui.image.repository` | UI image repository | `eliezer1234/lognest-ui` |
| `ui.image.tag` | UI image tag | `"1.0.0"` |
| `ui.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `ui.service.type` | Service type | `ClusterIP` |
| `ui.service.port` | Service port | `8080` |
| `ui.resources.requests.cpu` | CPU request | `"100m"` |
| `ui.resources.requests.memory` | Memory request | `"128Mi"` |
| `ui.resources.limits.cpu` | CPU limit | `"500m"` |
| `ui.resources.limits.memory` | Memory limit | `"512Mi"` |
| `ui.nodeSelector` | Node selector | `{}` |
| `ui.tolerations` | Tolerations (includes control-plane by default) | See values.yaml |
| `ui.affinity` | Affinity rules | `{}` |

### Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress resource | `true` |
| `ingress.className` | Ingress class name | `"nginx"` |
| `ingress.host` | Ingress hostname | `"lognest.example.com"` |
| `ingress.tlsSecret` | TLS secret name (empty to disable TLS) | `""` |
| `ingress.annotations` | Ingress annotations | See values.yaml |

### ServiceAccount

| Parameter | Description | Default |
|-----------|-------------|---------|
| `serviceAccount.create` | Create a ServiceAccount | `true` |
| `serviceAccount.name` | ServiceAccount name | `lognest` |

### Images (Air-Gap Overrides)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `images.collector.repository` | Collector image override | `alpine/k8s` |
| `images.collector.tag` | Collector tag override | `"1.30.2"` |
| `images.ui.repository` | UI image override | `eliezer1234/lognest-ui` |
| `images.ui.tag` | UI tag override | `"1.0.0"` |

---

## How It Works

### Incremental Collection (Byte Offsets)

LogNest tracks the byte offset of each active log file (`0.log`) between collection runs. On the next run, it seeks to the saved offset and reads only new data. This avoids re-collecting gigabytes of already-processed logs.

State is persisted in `/data/.lognest_offsets` (JSON map of file path → byte position).

### Log Rotation Handling

Kubernetes rotates container logs (e.g., `0.log` → `0.log.20240101-120000.gz`). LogNest:
1. Detects rotated files (both `.gz` compressed and plain text)
2. Applies the saved offset to the most recently rotated file (since it was the active file before rotation)
3. Reads the new active `0.log` from the beginning
4. Detects size-based rotation (file smaller than saved offset) and resets

### Phase 1 (Node Filesystem) vs Phase 2 (kubectl API)

- **Phase 1** reads directly from `/var/log/pods` via hostPath mount. This is fast, supports incremental offsets, and works for all containers on the local node.
- **Phase 2** uses `kubectl logs` API to collect from pods on other nodes (multi-node clusters). It skips containers already collected in Phase 1 to avoid duplicates. Also fetches `--previous` logs for rotated containers.

Set `collector.enableApiPhase: true` for multi-node clusters.

### SQLite Index

After each collection run, the collector indexes metadata (filenames, sizes, line counts, error/warn/info/debug counts) into a SQLite database on the PVC. The UI queries this index for instant dashboard stats and file listings instead of scanning NFS on every request.

### Gradual Retention

When runs expire (older than `retentionMonths`), LogNest deletes only the **1 oldest** expired run per collection cycle. This prevents sudden bulk deletion and spreads I/O over time.

### Capacity-Based Cleanup

If total data on the PVC exceeds `capacityThresholdPercent` of the PVC size, the collector deletes the oldest runs (both raw logs and archives) until usage drops below the threshold.

---

## UI Tabs

| Tab | Description |
|-----|-------------|
| **Dashboard** | Overview stats (total runs, files, archives, storage used, last run time). Log viewer with level-based highlighting and filtering (error/warn/info/debug). Run selector to browse historical collections. |
| **Downloads** | Browse and download compressed `.tar.gz` archives of past collection runs. |
| **Files** | Browse raw `.log` files per run. View file sizes, select multiple files for bulk download as ZIP. |
| **Search** | Full-text search across all collected log files. Filter by namespace, pod, or container. |
| **On-Demand** | Trigger an immediate collection run from the UI without waiting for the cron schedule. View history of on-demand runs. |

---

## Collector Modes

| Mode | Value | Best For | How It Works |
|------|-------|----------|--------------|
| **CronJob** | `collector.mode: cronjob` | Single-node clusters, RKE2 single-server | A single pod runs on the configured schedule. Mounts `/var/log/pods` from the node. |
| **DaemonSet** | `collector.mode: daemonset` | Multi-node clusters | One collector pod per node. Each pod collects from its own node's `/var/log/pods`. Eliminates the need for Phase 2 API calls. |

**When to use CronJob:**
- Single-node or small clusters
- You want minimal resource usage (pod only exists during collection)
- Combined with `enableApiPhase: true` for multi-node coverage via API

**When to use DaemonSet:**
- Multi-node clusters (3+ nodes)
- You want direct filesystem access on every node (faster, no API overhead)
- Large clusters where kubectl API collection would be slow

---

## Troubleshooting

### Pod can't schedule

**Symptom:** Collector or UI pod stuck in `Pending`.

**Fix:** The chart includes tolerations for control-plane nodes by default. If your nodes have additional taints, add them:

```yaml
collector:
  tolerations:
    - key: "your-custom-taint"
      operator: "Exists"
      effect: "NoSchedule"
```

### PVC not binding

**Symptom:** PVC stays in `Pending` state.

**Fix:**
1. Verify the NFS server is reachable: `showmount -e <nfs-server-ip>`
2. Verify the StorageClass exists: `kubectl get sc nfs-storage`
3. Verify the NFS path exists and has correct permissions (at least `755`)
4. Check the NFS provisioner logs: `kubectl logs -l app=nfs-subdir-external-provisioner`

### UI slow to load

**Symptom:** Dashboard takes several seconds to render.

**Fix:** The SQLite index may be missing or corrupted. Trigger a new collection run (On-Demand tab) to rebuild the index. Alternatively, delete `.lognest_index.db` from the PVC and restart the UI pod.

### Logs missing

**Symptom:** Expected container logs not appearing in collection runs.

**Fix:**
1. Check Phase 1 output: `kubectl logs -l job-name=<job> -n lognest | grep "Phase 1"`
2. Verify `/var/log/pods` is mounted (hostPath in the pod spec)
3. For multi-node clusters, ensure `enableApiPhase: true` or use DaemonSet mode
4. Check if the container's namespace is included (if `allNamespaces: false`)

### Job failed

**Symptom:** CronJob or init job shows `BackoffLimitExceeded`.

**Fix:**
1. Check job logs: `kubectl logs -l job-name=<job-name> -n lognest`
2. Increase resources if OOMKilled:
   ```yaml
   collector:
     resources:
       limits:
         memory: "2Gi"
   ```
3. Check NFS connectivity (most common cause of job failures)
4. Verify ServiceAccount and ClusterRole exist: `kubectl get sa,clusterrole -l app.kubernetes.io/name=lognest`

---

## Development

### Build the UI image

```bash
# Build locally
./docker/build.sh

# Build and push to a registry
./docker/build.sh registry.internal:5000
```

The Dockerfile uses `python:3.11-slim` with Flask 3.0.3 and Gunicorn 22.0.0. The app source (`files/app.py`) is mounted via ConfigMap at runtime, but a default copy is baked into the image.

### Run QA tests

```bash
chmod +x tests/qa-test.sh
./tests/qa-test.sh
```

The QA suite performs a full lifecycle test:
1. Clean install
2. Verify UI, PVC, CronJobs, init job
3. Test all UI endpoints
4. Validate incremental collection (Run2 < Run1)
5. On-demand trigger
6. Download endpoints
7. State persistence
8. Uninstall & data preservation
9. Reinstall reads existing data

Requires: `kubectl`, `helm`, cluster access, and NFS path accessible from the test machine.

### Modify the collector

The collector script is at `files/collect.py` and is mounted into pods via ConfigMap. After editing:

1. Update the ConfigMap: `helm upgrade lognest . -n lognest -f values.yaml`
2. Trigger a test run: use the On-Demand tab or create a job manually:
   ```bash
   kubectl create job --from=cronjob/lognest-collector-1 test-run -n lognest
   ```
3. Check logs: `kubectl logs -l job-name=test-run -n lognest`

---

## Repository Structure

```
LogNest/
├── Chart.yaml                      # Helm chart metadata (v1.0.0)
├── values.yaml                     # All configurable parameters
├── README.md                       # This file
├── images.txt                      # Air-gap image list
├── push.ps1                        # Windows push helper
├── docker/
│   ├── Dockerfile.ui               # UI image (python:3.11-slim + Flask + Gunicorn)
│   └── build.sh                    # Build & push script
├── files/
│   ├── app.py                      # Web UI application (Flask)
│   ├── collect.py                  # Log collector (incremental, parallel)
│   └── index_db.py                 # SQLite index for fast UI queries
├── scripts/
│   └── pull-push-images.sh         # Air-gap image pull/tag/push helper
├── templates/
│   ├── _helpers.tpl                # Helm template helpers
│   ├── clusterrole.yaml            # RBAC: read pods/logs, create jobs
│   ├── clusterrolebinding.yaml     # Bind ClusterRole to ServiceAccount
│   ├── configmap-collector.yaml    # Mounts collect.py + index_db.py
│   ├── configmap-ui.yaml           # Mounts app.py + index_db.py
│   ├── cronjob.yaml                # Collector CronJob (mode=cronjob)
│   ├── daemonset-collector.yaml    # Collector DaemonSet (mode=daemonset)
│   ├── deployment-ui.yaml          # Web UI Deployment
│   ├── ingress.yaml                # Ingress resource
│   ├── job-cleanup-pv.yaml         # Pre-delete hook: cleanup PV
│   ├── job-init-collect.yaml       # Post-install hook: initial collection
│   ├── pvc.yaml                    # PersistentVolumeClaim (NFS)
│   ├── service-ui.yaml             # ClusterIP Service for UI
│   └── serviceaccount.yaml         # ServiceAccount
├── tests/
│   └── qa-test.sh                  # Full lifecycle QA test suite
└── preview/
    └── index.html                  # Static preview of UI design
```

---

## Security

### RBAC

LogNest follows the principle of least privilege:

- **Pods/Logs** — `get`, `list` only (read-only access to pod metadata and logs)
- **Namespaces** — `get`, `list` (to enumerate namespaces for collection)
- **PersistentVolumeClaims** — `get`, `list` (wait-for-PVC init container)
- **Jobs** — `get`, `list`, `create`, `delete` (on-demand trigger from UI)
- **CronJobs** — `get`, `list` (UI displays schedule info)

No `write`, `patch`, or `update` access to pods, deployments, or secrets.

### No Secrets in Chart

The chart does not create or manage any Secret resources. If your private registry requires authentication, create the pull secret separately and reference it via `global.imagePullSecrets`.

### NFS Permissions

- The PVC directory should be owned by the container runtime user (typically UID 0 or 1000)
- Recommended permissions: `755` for directories, `644` for files
- The collector writes state files (`.lognest_offsets`, `.lognest_last_collect`, `.lognest_index.db`) to the PVC root

### Network

- The UI listens only on port 8080 within the cluster (ClusterIP service)
- External access is controlled via Ingress — configure TLS via `ingress.tlsSecret`
- No outbound network calls are made by any component

---

## License

[MIT](https://opensource.org/licenses/MIT) © [eliatiya](https://github.com/eliatiya)
