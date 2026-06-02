# Software Requirements Specification (SRS)

## LogNest — Kubernetes Log Collection Helm Chart

| Field        | Value                                      |
|--------------|--------------------------------------------|
| **Title**    | LogNest Software Requirements Specification |
| **Version**  | 1.0.0                                      |
| **Date**     | 2025-01-20                                 |
| **Author**   | eliatiya                                   |
| **Repository** | https://github.com/eliatiya/LogNest      |
| **Status**   | Approved                                   |

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements for LogNest, a production-ready Kubernetes log collection, compression, and web dashboard Helm chart. It serves as the authoritative reference for development, testing, and validation activities.

### 1.2 Scope

LogNest provides automated, incremental log collection from all pods across all namespaces in a Kubernetes cluster. It packages collected logs into compressed archives, stores them on NFS-backed persistent storage, and exposes a web-based dashboard for log browsing, searching, downloading, and on-demand collection triggering.

The system is designed to operate in air-gapped environments without internet access at runtime, supports multi-node clusters via DaemonSet deployment mode, and preserves collected data across chart uninstall/reinstall cycles.

### 1.3 Intended Audience

- DevOps engineers deploying and operating Kubernetes clusters
- System administrators managing log retention and storage
- Developers troubleshooting application issues via log analysis
- QA engineers validating log collection behavior

### 1.4 Document Conventions

- Requirements are uniquely identified with the prefix **FR-** (functional) or **NFR-** (non-functional).
- Priority levels: **High** (must-have for v1.0), **Medium** (important), **Low** (nice-to-have).

---

## 2. Definitions and Acronyms

| Term / Acronym | Definition |
|----------------|------------|
| **Helm**       | Kubernetes package manager for deploying applications as charts |
| **RKE2**       | Rancher Kubernetes Engine 2 — a FIPS-compliant Kubernetes distribution |
| **NFS**        | Network File System — shared storage protocol used for persistent data |
| **PVC**        | Persistent Volume Claim — Kubernetes abstraction for requesting storage |
| **PV**         | Persistent Volume — a provisioned piece of storage in the cluster |
| **CronJob**    | Kubernetes resource that runs Jobs on a time-based schedule |
| **DaemonSet**  | Kubernetes resource that ensures a pod runs on every (or selected) node |
| **SQLite**     | Lightweight embedded relational database used for indexing |
| **WAL**        | Write-Ahead Logging — SQLite journal mode for concurrent access |
| **tar.gz**     | Gzip-compressed tar archive format |
| **Air-gap**    | Network-isolated environment with no external internet access |
| **Ingress**    | Kubernetes resource that manages external HTTP/HTTPS access to services |
| **RBAC**       | Role-Based Access Control — Kubernetes authorization mechanism |
| **kubelet**    | Node-level agent that manages pod lifecycle and container logs |
| **hostPath**   | Kubernetes volume type that mounts a directory from the host node |
| **Byte-offset** | File position tracking for incremental reads |
| **Clock skew** | Difference in system time between nodes in a distributed system |

---

## 3. Overall Description

### 3.1 Product Perspective

LogNest is a self-contained Helm chart that deploys into an existing Kubernetes cluster. It integrates with:
- The Kubernetes API for pod enumeration and log retrieval
- The node filesystem (`/var/log/pods`) for direct log access
- NFS storage for durable, shared data persistence
- The cluster's Ingress controller for external web UI access

It does not depend on external logging stacks (ELK, Loki, etc.) and operates independently.

### 3.2 Product Functions

1. **Automated log collection** — Scheduled collection of container logs from all pods across all namespaces using a two-phase approach (node-local filesystem + Kubernetes API fallback).
2. **Incremental collection** — Byte-offset tracking ensures only new log data is collected on each run, minimizing I/O and storage overhead.
3. **Log rotation handling** — Detection and proper handling of rotated logs (both gzip-compressed and plain-text rotated files).
4. **Compression & archiving** — Each collection run is packaged into a tar.gz archive for efficient long-term storage.
5. **Web-based dashboard** — A dark-themed responsive UI for browsing, viewing, searching, and downloading collected logs.
6. **On-demand collection** — Manual trigger of immediate log collection outside the CronJob schedule.
7. **Retention management** — Configurable time-based and capacity-based cleanup of old log data.
8. **Data persistence** — Log data survives chart uninstall/reinstall via NFS folder preservation.

### 3.3 User Characteristics

| User Type | Description |
|-----------|-------------|
| Cluster Administrator | Deploys and configures LogNest via Helm values; manages storage and retention |
| DevOps Engineer | Uses the web UI to investigate incidents, download logs, and trigger on-demand collection |
| Developer | Browses logs filtered by namespace/pod to debug application issues |

### 3.4 Constraints

- Must run on Kubernetes 1.25+ with Helm 3.x
- Storage backend must be NFS with ReadWriteMany access mode
- Air-gap environments require pre-loaded container images in a private registry
- The collector requires ClusterRole permissions to list pods and read logs across all namespaces
- SQLite is used for indexing; not suitable for clusters producing > 100,000 log files per day

### 3.5 Assumptions and Dependencies

- An NFS server is provisioned and accessible from all cluster nodes
- The `nfs-subdir-external-provisioner` StorageClass is configured
- Kubernetes RBAC is enabled and allows ServiceAccount creation
- An Ingress controller (nginx) is deployed in the cluster
- Node clocks are synchronized within ±5 minutes (NTP recommended)
- Container runtime writes logs to `/var/log/pods` (standard kubelet behavior)

---

## 4. Functional Requirements

### 4.1 Log Collection

| ID | Requirement | Priority |
|----|-------------|----------|
| **FR-001** | The system SHALL collect container stdout/stderr logs from all pods in all namespaces within the cluster. | High |
| **FR-002** | The system SHALL perform incremental collection using byte-offset tracking, reading only new bytes appended since the previous collection run. | High |
| **FR-003** | The system SHALL handle log rotation by detecting both gzip-compressed (`.gz`) rotated files and plain-text rotated files (`0.log.YYYYMMDD-*`), reading their new content appropriately. | High |
| **FR-004** | The system SHALL run log collection on a configurable cron schedule, defaulting to every 4 hours (`0 */4 * * *`). | High |
| **FR-005** | The system SHALL compress each collection run into a tar.gz archive stored in a dedicated archive directory. | High |
| **FR-014** | The system SHALL support air-gap deployment by functioning without internet access at runtime, using pre-loaded images from a configurable private registry. | High |
| **FR-015** | The system SHALL support multi-node cluster deployment via DaemonSet mode, ensuring one collector pod runs per node. | Medium |
| **FR-019** | The system SHALL use a lock file mechanism to prevent concurrent collector instances from running simultaneously. | High |
| **FR-020** | The system SHALL apply a 5-minute clock skew tolerance (buffer) when determining which files have new data, to account for node clock drift. | Medium |

### 4.2 Web UI

| ID | Requirement | Priority |
|----|-------------|----------|
| **FR-006** | The system SHALL provide a web-based dashboard displaying collection statistics including total runs, file count, archive count, storage usage, and last run time. | High |
| **FR-007** | The system SHALL provide a log viewer with level-based filtering supporting error, warning, info, and debug severity levels. | High |
| **FR-008** | The system SHALL provide cross-run search functionality allowing users to search by pod name, namespace, and date range. | Medium |
| **FR-009** | The system SHALL support multi-file download as a ZIP archive, allowing users to select multiple files across runs and download them in a single archive. | Medium |
| **FR-010** | The system SHALL provide an on-demand collection trigger accessible from the web UI, creating a Kubernetes Job for immediate log collection. | High |
| **FR-016** | The system SHALL maintain a SQLite index database for instant UI queries, with graceful fallback to filesystem scanning when the index is unavailable. | Medium |
| **FR-017** | The system SHALL support multi-pod merged view, combining logs from multiple selected pods sorted by timestamp. | Low |
| **FR-018** | The system SHALL provide namespace filtering capabilities in all tabs (Dashboard, Files, Downloads, Search). | Medium |

### 4.3 Data Management

| ID | Requirement | Priority |
|----|-------------|----------|
| **FR-011** | The system SHALL enforce a configurable retention policy (default 1 month), gradually deleting runs older than the configured threshold. | High |
| **FR-012** | The system SHALL perform capacity-based cleanup when PVC disk usage exceeds a configurable threshold percentage (default 80%), deleting oldest runs until usage drops below the threshold. | High |
| **FR-013** | The system SHALL preserve all collected log data on the NFS folder across chart uninstall and reinstall operations, ensuring data persistence independent of Helm lifecycle. | High |

---

## 5. Non-Functional Requirements

### 5.1 Performance

| ID | Requirement |
|----|-------------|
| **NFR-001** | Log collection SHALL complete within 10 minutes for clusters with up to 500 pods. |
| **NFR-002** | The web UI SHALL respond to dashboard page loads within 2 seconds under normal conditions. |
| **NFR-003** | The collector SHALL process containers in parallel using a configurable thread pool (default 8 threads). |
| **NFR-004** | File I/O SHALL be streamed in 8 MB chunks to limit memory usage per file read. |
| **NFR-005** | The SQLite index SHALL provide sub-100ms query response for stats, run listings, and file searches. |
| **NFR-006** | Large log files SHALL be split into parts at configurable size boundaries (default 100 MB) to maintain manageability. |

### 5.2 Security

| ID | Requirement |
|----|-------------|
| **NFR-007** | The system SHALL use a dedicated ServiceAccount with least-privilege RBAC (ClusterRole for pod listing and log reading only). |
| **NFR-008** | The system SHALL support TLS termination via Ingress when a TLS secret is configured. |
| **NFR-009** | The system SHALL not expose sensitive information (tokens, secrets) in collected logs or UI output. |
| **NFR-010** | The web UI SHALL return HTTP 404 for requests to non-existent files without revealing filesystem paths. |

### 5.3 Reliability

| ID | Requirement |
|----|-------------|
| **NFR-011** | The system SHALL gracefully handle NFS unavailability by failing the current collection run without corrupting previously collected data. |
| **NFR-012** | The system SHALL handle stale lock files (older than 3 hours) by removing them and proceeding with collection. |
| **NFR-013** | The system SHALL tolerate individual container collection failures without aborting the entire run. |
| **NFR-014** | The SQLite database SHALL use WAL journal mode for safe concurrent read/write access. |
| **NFR-015** | The web UI SHALL use an in-memory TTL-based cache (60 seconds) to reduce NFS directory scan frequency. |

### 5.4 Portability

| ID | Requirement |
|----|-------------|
| **NFR-016** | The system SHALL deploy on any Kubernetes 1.25+ cluster using standard Helm 3 commands. |
| **NFR-017** | The system SHALL support configurable image registry prefixes for air-gap environments with private registries. |
| **NFR-018** | The system SHALL support both single-node (CronJob mode) and multi-node (DaemonSet mode) deployments without code changes. |
| **NFR-019** | The system SHALL be compatible with RKE2, standard kubeadm, and managed Kubernetes distributions. |

---

## 6. Interface Requirements

### 6.1 Web UI Interface

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard with stats cards and log viewer |
| `/downloads` | GET | Browse and download tar.gz archives |
| `/files` | GET | Browse individual log files per run |
| `/search` | GET | Cross-run search with filters |
| `/collect` | GET | On-demand collection page with history |
| `/collect/trigger` | POST | Trigger immediate collection Job |
| `/download/log/<run>/<file>` | GET | Download a specific log file |
| `/download/zip/<file>` | GET | Download a specific archive |
| `/download/multi` | POST | Download multiple files as ZIP |
| `/api/stats` | GET | JSON API returning dashboard statistics |
| `/healthz` | GET | Health check endpoint |

### 6.2 Ingress Interface

- Ingress class: `nginx` (configurable)
- Host-based routing via configurable hostname (default: `lognest.example.com`)
- Optional TLS termination via Secret reference
- Proxy body size limit: 500 MB (for large downloads)
- Proxy read timeout: 300 seconds

### 6.3 NFS Storage Interface

| Path | Purpose |
|------|---------|
| `<nfsPath>/logs/` | Raw log files organized by run timestamp subdirectories |
| `<nfsPath>/logs_zip/` | Compressed tar.gz archives |
| `<nfsPath>/.lognest_last_collect` | State file: epoch of last successful collection |
| `<nfsPath>/.lognest_offsets` | State file: JSON map of byte offsets per log file |
| `<nfsPath>/.lognest_collecting` | Lock file: prevents concurrent collection |
| `<nfsPath>/logs/.lognest_index.db` | SQLite index database |

### 6.4 Kubernetes API Interface

The collector interacts with the Kubernetes API for:
- Listing all namespaces (`kubectl get namespaces`)
- Listing pods and containers in each namespace (`kubectl get pods`)
- Retrieving container logs (`kubectl logs`) with `--timestamps`, `--since`, and `--previous` flags
- Creating Jobs for on-demand collection trigger (via in-cluster API)

---

## 7. Revision History

| Version | Date       | Author   | Description         |
|---------|------------|----------|---------------------|
| 1.0.0   | 2025-01-20 | eliatiya | Initial release     |
