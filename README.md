# 🪺 LogNest

> **Production-ready Kubernetes log collection, compression, and web dashboard — RKE2-ready, air-gap compatible.**

[![Helm](https://img.shields.io/badge/Helm-v3-blue?logo=helm)](https://helm.sh)
[![RKE2](https://img.shields.io/badge/RKE2-ready-green)](https://docs.rke2.io)
[![Air-Gap](https://img.shields.io/badge/Air--Gap-supported-orange)](./images.txt)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Overview

LogNest is a Helm chart that deploys a complete log management solution on Kubernetes:

| Feature | Details |
|---|---|
| **Log Collection** | CronJob runs twice daily (configurable), collects logs from every container in every pod across all namespaces |
| **Log Naming** | Files named `<namespace>__<pod>__<container>__<timestamp>.log` |
| **Compression** | After each collection run, a `.tar.gz` archive is created automatically |
| **Storage** | Single NFS-backed PVC with two subdirectories: `logs/` and `logs_zip/` |
| **Retention** | Configurable month-based retention with automatic cleanup |
| **Web Dashboard** | 3-tab UI: live log viewer, archive downloads, individual file downloads |
| **Air-Gap** | All images configurable via private registry; helper script included |
| **RKE2** | Uses `nginx` IngressClass (default in RKE2); no cloud-specific dependencies |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                   │
│                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐  │
│  │  CronJob ×2  │───▶│  NFS PVC (100Gi)             │  │
│  │  (collector) │    │  ├── logs/                   │  │
│  └──────────────┘    │  │   └── <timestamp>/        │  │
│                      │  │       └── ns__pod__c.log  │  │
│  ┌──────────────┐    │  └── logs_zip/               │  │
│  │  Deployment  │───▶│      └── lognest_<ts>.tar.gz │  │
│  │  (Flask UI)  │    └──────────────────────────────┘  │
│  └──────┬───────┘                                       │
│         │                                               │
│  ┌──────▼───────┐    ┌──────────────┐                  │
│  │   Service    │───▶│   Ingress    │◀── Browser        │
│  │  (ClusterIP) │    │  (nginx)     │                   │
│  └──────────────┘    └──────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

---

## 📦 Prerequisites

| Requirement | Notes |
|---|---|
| Kubernetes 1.24+ | Tested on RKE2 |
| Helm 3.x | `helm version` |
| NFS server | Accessible from all cluster nodes |
| `nfs-client` StorageClass | Already present in Rancher/RKE2 clusters |
| `nginx` IngressClass | Default in RKE2 |

### Install NFS Subdir External Provisioner (if not present)

> RKE2 clusters managed by Rancher already have the `nfs-client` StorageClass available. No additional provisioner installation is needed.

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/eliatiya/LogNest.git
cd LogNest
```

### 2. Configure `values.yaml`

At minimum, set your NFS server details and ingress hostname:

```yaml
storage:
  nfsServer: "192.168.1.100"       # ← your NFS server IP
  nfsPath: "/exports/lognest"      # ← your NFS export path

ingress:
  host: "lognest.company.internal" # ← your desired hostname
```

### 3. Install

```bash
helm install lognest . \
  --namespace lognest \
  --create-namespace \
  -f values.yaml
```

### 4. Access the dashboard

Add the hostname to your DNS or `/etc/hosts`, then open:

```
http://lognest.company.internal
```

---

## ✈️ Air-Gap Installation

### Step 1 — On an internet-connected machine

```bash
# Make the script executable
chmod +x scripts/pull-push-images.sh

# Pull all required images and push to your private registry
./scripts/pull-push-images.sh registry.internal:5000
```

### Step 2 — Update `values.yaml`

```yaml
global:
  imageRegistry: "registry.internal:5000"

  # If your registry requires authentication:
  imagePullSecrets:
    - name: regcred
```

> Create the pull secret if needed:
> ```bash
> kubectl create secret docker-registry regcred \
>   --docker-server=registry.internal:5000 \
>   --docker-username=<user> \
>   --docker-password=<password> \
>   -n lognest
> ```

### Step 3 — Install (air-gap)

```bash
helm install lognest . \
  --namespace lognest \
  --create-namespace \
  -f values.yaml
```

---

## ⚙️ Configuration Reference

### Core Settings

| Parameter | Default | Description |
|---|---|---|
| `global.imageRegistry` | `""` | Private registry prefix for all images |
| `global.imagePullSecrets` | `[]` | Image pull secrets |
| `namespace.name` | `lognest` | Namespace to deploy into |

### Log Collector

| Parameter | Default | Description |
|---|---|---|
| `collector.schedule1` | `"0 2 * * *"` | First daily collection (cron format, UTC) |
| `collector.schedule2` | `"0 14 * * *"` | Second daily collection (cron format, UTC) |
| `collector.allNamespaces` | `true` | Collect from all namespaces |
| `collector.namespaces` | `[]` | Specific namespaces (when `allNamespaces: false`) |
| `collector.retentionMonths` | `1` | Months of logs/zips to retain |
| `collector.image.repository` | `bitnami/kubectl` | Collector image |
| `collector.image.tag` | `1.29.3` | Collector image tag |

### Storage

| Parameter | Default | Description |
|---|---|---|
| `storage.nfsServer` | `192.168.1.100` | NFS server address |
| `storage.nfsPath` | `/exports/lognest` | NFS export path |
| `storage.storageClassName` | `nfs-client` | StorageClass name (Rancher/RKE2 built-in) |
| `storage.pvc.size` | `100Gi` | PVC size |
| `storage.logsDir` | `logs` | Subdirectory for raw logs |
| `storage.logsZipDir` | `logs_zip` | Subdirectory for compressed archives |

### Web UI

| Parameter | Default | Description |
|---|---|---|
| `ui.replicaCount` | `1` | Number of UI replicas |
| `ui.image.repository` | `python` | UI image |
| `ui.image.tag` | `3.11-slim` | UI image tag |
| `ui.service.port` | `8080` | Service port |

### Ingress

| Parameter | Default | Description |
|---|---|---|
| `ingress.enabled` | `true` | Enable ingress |
| `ingress.className` | `nginx` | IngressClass (RKE2 default) |
| `ingress.host` | `lognest.example.com` | Hostname |
| `ingress.tlsSecret` | `""` | TLS secret name (leave empty for HTTP) |

---

## 🖥️ Dashboard Tabs

### Tab 1 — 📊 Dashboard
- Select a collection run by date/time
- Select a specific pod/container
- Filter log lines by level: **All / Error / Warning / Info / Debug**
- Color-coded log output (errors in red, warnings in yellow, etc.)

### Tab 2 — 📦 Downloads
- Lists all compressed `.tar.gz` archives by date
- One-click download of any archive

### Tab 3 — 📄 Files
- Browse individual log files within a specific run
- Download any single log file directly

---

## 📁 Log File Naming Convention

```
<namespace>__<pod-name>__<container-name>__<YYYY-MM-DD_HH-MM-SS>.log
```

Example:
```
production__api-deployment-7d9f8b-xk2p9__api__2026-04-19_02-00-01.log
```

---

## 🔄 Retention Policy

Logs and zip archives older than `collector.retentionMonths` months are automatically deleted after each collection run. Default is **1 month**.

To change retention to 3 months:
```yaml
collector:
  retentionMonths: 3
```

---

## 🛠️ Useful Commands

```bash
# Check collector CronJob status
kubectl get cronjobs -n lognest

# View last collection job logs
kubectl logs -n lognest -l lognest/component=collector --tail=50

# Check UI pod status
kubectl get pods -n lognest -l lognest/component=ui

# Manually trigger a collection run
kubectl create job --from=cronjob/lognest-collector-1 manual-run -n lognest

# Uninstall
helm uninstall lognest -n lognest
```

---

## 📂 Repository Structure

```
LogNest/
├── Chart.yaml                        # Chart metadata
├── values.yaml                       # All configurable values
├── images.txt                        # Air-gap image list
├── README.md                         # This file
├── scripts/
│   └── pull-push-images.sh           # Air-gap image helper
└── templates/
    ├── _helpers.tpl                  # Template helpers
    ├── namespace.yaml
    ├── serviceaccount.yaml
    ├── clusterrole.yaml
    ├── clusterrolebinding.yaml
    ├── storageclass.yaml
    ├── pvc.yaml
    ├── configmap-collector.yaml      # Log collection shell script
    ├── configmap-ui.yaml             # Flask web app
    ├── cronjob.yaml                  # Two scheduled collectors
    ├── deployment-ui.yaml            # Web dashboard deployment
    ├── service-ui.yaml
    └── ingress.yaml
```

---

## 🔐 Security Notes

- The collector uses a dedicated `ServiceAccount` with a `ClusterRole` scoped to **read-only** access on `pods`, `pods/log`, and `namespaces`.
- No secrets are stored in the chart — credentials (registry, NFS) are provided via values.
- The UI is read-only — it only serves files from the NFS mount.

---

## 📄 License

MIT © [eliatiya](https://github.com/eliatiya)
