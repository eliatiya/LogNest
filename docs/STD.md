# Software Test Description (STD)

## LogNest — Kubernetes Log Collection Helm Chart

| Field        | Value                                      |
|--------------|--------------------------------------------|
| **Title**    | LogNest Software Test Description           |
| **Version**  | 1.0.0                                      |
| **Date**     | 2025-01-20                                 |
| **Author**   | eliatiya                                   |
| **Repository** | https://github.com/eliatiya/LogNest      |
| **Status**   | Approved                                   |
| **Related**  | SRS v1.0.0                                 |

---

## 1. Introduction

### 1.1 Purpose

This document describes the test cases, procedures, and environment required to validate that LogNest meets the functional and non-functional requirements specified in the SRS. It covers installation, core functionality, web UI, data management, and lifecycle operations.

### 1.2 Scope

Testing covers the complete LogNest Helm chart including:
- Helm installation and resource creation
- Log collection (incremental, rotation, multi-node)
- Web UI endpoints and functionality
- Data persistence across uninstall/reinstall
- Retention and capacity management
- On-demand collection triggering

### 1.3 References

- LogNest SRS v1.0.0
- LogNest `tests/qa-test.sh` automated QA script
- Kubernetes documentation (CronJob, DaemonSet, PVC)

---

## 2. Test Environment

### 2.1 Infrastructure

| Component | Specification |
|-----------|---------------|
| **Kubernetes Distribution** | RKE2 v1.28+ |
| **Cluster Nodes** | 1–3 nodes (control-plane + workers) |
| **Node OS** | Ubuntu 22.04 LTS / RHEL 8+ |
| **Node Resources** | Minimum 4 CPU, 8 GB RAM per node |
| **NFS Server** | Dedicated NFS server with `/exports/lognest` exported |
| **NFS Storage** | Minimum 150 Gi available capacity |
| **StorageClass** | `nfs-storage` (nfs-subdir-external-provisioner) |
| **Ingress Controller** | nginx ingress controller |
| **Helm Version** | 3.12+ |
| **kubectl Version** | 1.28+ |

### 2.2 Software Dependencies

| Tool | Version | Purpose |
|------|---------|---------|
| `helm` | 3.12+ | Chart installation and management |
| `kubectl` | 1.28+ | Cluster interaction and Job creation |
| `curl` | 7.x+ | HTTP endpoint testing |
| `bash` | 5.x+ | QA test script execution |
| `grep` | 3.x+ | Log content verification |

### 2.3 Test Data

- A dedicated `qa-test` busybox pod generating numbered log lines (`QA_1`, `QA_2`, ...) at 1-second intervals
- Pre-existing cluster workloads generating container logs in multiple namespaces
- System namespace pods (kube-system, lognest) for multi-namespace verification

---

## 3. Test Approach

### 3.1 Automated Testing

The primary test execution uses `tests/qa-test.sh`, a comprehensive Bash script that:
1. Performs a clean Helm install
2. Validates all Kubernetes resources are created
3. Tests core collection functionality
4. Validates web UI endpoints via port-forward
5. Verifies incremental collection behavior
6. Tests on-demand triggering
7. Verifies data persistence across uninstall/reinstall
8. Reports results in a structured table

### 3.2 Manual Verification

Certain tests require manual validation:
- Visual UI inspection (layout, responsiveness, dark theme)
- Ingress access from outside the cluster
- Multi-node DaemonSet behavior
- Long-running retention policy execution

### 3.3 Test Execution Order

Tests are grouped into sequential phases:
1. **Phase 1** — Clean install and resource validation
2. **Phase 2** — Core functionality (pods, PVC, CronJobs, init job)
3. **Phase 3** — Web UI endpoint verification
4. **Phase 4** — Incremental collection validation
5. **Phase 5** — On-demand trigger
6. **Phase 6** — Download endpoints
7. **Phase 7** — State persistence and additional coverage
8. **Phase 8** — Uninstall and data preservation
9. **Phase 9** — Reinstall and data continuity

---

## 4. Test Cases

### TC-001: Helm Install

| Field | Value |
|-------|-------|
| **ID** | TC-001 |
| **Name** | Clean Helm Installation |
| **Objective** | Verify LogNest installs successfully via Helm with default values |
| **Prerequisites** | Clean cluster with no previous LogNest installation; NFS server accessible |
| **Steps** | 1. Remove any existing LogNest release and namespace<br>2. Run `helm install lognest . --namespace lognest --create-namespace -f values.yaml`<br>3. Wait for deployment to stabilize (90 seconds) |
| **Expected Result** | Helm install returns exit code 0; release is listed in `helm list` |
| **Priority** | High |

---

### TC-002: UI Deployment Ready

| Field | Value |
|-------|-------|
| **ID** | TC-002 |
| **Name** | UI Deployment Running |
| **Objective** | Verify the web UI deployment has at least 1 ready replica |
| **Prerequisites** | TC-001 passed; pods have time to start |
| **Steps** | 1. Run `kubectl get deploy lognest-ui -n lognest`<br>2. Check `readyReplicas` field |
| **Expected Result** | `readyReplicas >= 1` |
| **Priority** | High |

---

### TC-003: PVC Bound

| Field | Value |
|-------|-------|
| **ID** | TC-003 |
| **Name** | Persistent Volume Claim Bound |
| **Objective** | Verify the PVC is bound to a PV backed by NFS |
| **Prerequisites** | TC-001 passed; NFS StorageClass configured |
| **Steps** | 1. Run `kubectl get pvc pvc-lognest -n lognest`<br>2. Check `.status.phase` |
| **Expected Result** | PVC phase is `Bound` |
| **Priority** | High |

---

### TC-004: CronJobs Created

| Field | Value |
|-------|-------|
| **ID** | TC-004 |
| **Name** | CronJob Resources Created |
| **Objective** | Verify at least one CronJob is created for scheduled collection |
| **Prerequisites** | TC-001 passed |
| **Steps** | 1. Run `kubectl get cronjobs -n lognest`<br>2. Count CronJob resources |
| **Expected Result** | At least 1 CronJob exists (up to 2 if `schedule2` is configured) |
| **Priority** | High |

---

### TC-005: Init Job Completed

| Field | Value |
|-------|-------|
| **ID** | TC-005 |
| **Name** | Initial Collection Job Completion |
| **Objective** | Verify the init-collect job runs and completes on first install |
| **Prerequisites** | TC-001 passed |
| **Steps** | 1. Wait for job `lognest-init-collect` to complete (up to 5 minutes)<br>2. Check `.status.succeeded` field |
| **Expected Result** | Job status shows `succeeded >= 1` |
| **Priority** | High |

---

### TC-006: Logs on NFS

| Field | Value |
|-------|-------|
| **ID** | TC-006 |
| **Name** | Log Files Written to NFS |
| **Objective** | Verify collected logs are stored on the NFS mount |
| **Prerequisites** | TC-005 passed; NFS path accessible |
| **Steps** | 1. Check directory `<nfsPath>/logs/`<br>2. List run subdirectories |
| **Expected Result** | At least 1 run directory exists with `.log` files |
| **Priority** | High |

---

### TC-007: Archives on NFS

| Field | Value |
|-------|-------|
| **ID** | TC-007 |
| **Name** | Tar.gz Archives Created |
| **Objective** | Verify that collection runs produce compressed archives |
| **Prerequisites** | TC-005 passed; NFS path accessible |
| **Steps** | 1. Check directory `<nfsPath>/logs_zip/`<br>2. List `.tar.gz` files |
| **Expected Result** | At least 1 `.tar.gz` archive file exists |
| **Priority** | High |

---

### TC-008: Dashboard Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-008 |
| **Name** | GET / Dashboard Page |
| **Objective** | Verify the dashboard page returns HTTP 200 |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. Port-forward to lognest-ui service<br>2. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/` |
| **Expected Result** | HTTP 200 |
| **Priority** | High |

---

### TC-009: Downloads Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-009 |
| **Name** | GET /downloads Page |
| **Objective** | Verify the downloads page returns HTTP 200 |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/downloads` |
| **Expected Result** | HTTP 200 |
| **Priority** | High |

---

### TC-010: Files Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-010 |
| **Name** | GET /files Page |
| **Objective** | Verify the files browser page returns HTTP 200 |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/files` |
| **Expected Result** | HTTP 200 |
| **Priority** | High |

---

### TC-011: On-Demand Page Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-011 |
| **Name** | GET /collect Page |
| **Objective** | Verify the on-demand collection page returns HTTP 200 |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/collect` |
| **Expected Result** | HTTP 200 |
| **Priority** | High |

---

### TC-012: API Stats Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-012 |
| **Name** | GET /api/stats Returns Valid JSON |
| **Objective** | Verify the stats API returns valid JSON with expected keys |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s http://localhost:18080/api/stats`<br>2. Verify response contains `"runs"` and `"storage"` keys |
| **Expected Result** | Valid JSON response with `runs` and `storage` fields |
| **Priority** | High |

---

### TC-013: Incremental Collection — Run 1

| Field | Value |
|-------|-------|
| **ID** | TC-013 |
| **Name** | Incremental Collection First Run |
| **Objective** | Verify collection captures initial log data from a test pod |
| **Prerequisites** | TC-005 passed; qa-test pod running for 60+ seconds |
| **Steps** | 1. Deploy a busybox pod emitting numbered lines<br>2. Wait 65 seconds<br>3. Trigger collection job from CronJob template<br>4. Count QA lines in output file |
| **Expected Result** | Run 1 captures approximately 60+ QA lines |
| **Priority** | High |

---

### TC-014: Incremental Collection — Run 2

| Field | Value |
|-------|-------|
| **ID** | TC-014 |
| **Name** | Incremental Collection Second Run |
| **Objective** | Verify second run only collects lines generated after first run (incremental behavior) |
| **Prerequisites** | TC-013 passed; 35-second gap between runs |
| **Steps** | 1. Wait 35 seconds after Run 1 completes<br>2. Trigger second collection job<br>3. Count QA lines in Run 2 output file<br>4. Compare Run 2 count vs Run 1 count |
| **Expected Result** | Run 2 has fewer lines than Run 1 (approximately 35 lines, within the inter-run window) |
| **Priority** | High |

---

### TC-015: On-Demand Trigger

| Field | Value |
|-------|-------|
| **ID** | TC-015 |
| **Name** | On-Demand Collection Trigger |
| **Objective** | Verify the UI can trigger immediate log collection via POST |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -X POST -d "note=QA" http://localhost:18080/collect/trigger`<br>2. Check response code (302 or 200)<br>3. Verify a Job with label `lognest/trigger=ondemand` was created |
| **Expected Result** | HTTP 302/200 response; at least 1 on-demand Job created |
| **Priority** | High |

---

### TC-016: Single File Download

| Field | Value |
|-------|-------|
| **ID** | TC-016 |
| **Name** | Individual Log File Download |
| **Objective** | Verify a specific log file can be downloaded via the API |
| **Prerequisites** | TC-006 passed; port-forward active; at least one log file exists |
| **Steps** | 1. Identify a log file from the latest run<br>2. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/download/log/<run>/<file>` |
| **Expected Result** | HTTP 200 with file content |
| **Priority** | High |

---

### TC-017: Multi-File Download

| Field | Value |
|-------|-------|
| **ID** | TC-017 |
| **Name** | Multi-File ZIP Download |
| **Objective** | Verify multiple files can be downloaded as a ZIP archive |
| **Prerequisites** | TC-006 passed; port-forward active |
| **Steps** | 1. POST to `/download/multi` with multiple run/file pairs<br>2. Check response code |
| **Expected Result** | HTTP 200 with ZIP content |
| **Priority** | Medium |

---

### TC-018: State File — Last Collect

| Field | Value |
|-------|-------|
| **ID** | TC-018 |
| **Name** | State Persistence — Last Collect Timestamp |
| **Objective** | Verify the `.lognest_last_collect` state file is created after collection |
| **Prerequisites** | TC-005 passed; NFS path accessible |
| **Steps** | 1. Check for file `<nfsPath>/.lognest_last_collect`<br>2. Verify it contains a Unix epoch timestamp |
| **Expected Result** | File exists with valid numeric content |
| **Priority** | High |

---

### TC-019: State File — Offsets

| Field | Value |
|-------|-------|
| **ID** | TC-019 |
| **Name** | State Persistence — Byte Offsets |
| **Objective** | Verify the `.lognest_offsets` file is created with byte-offset data |
| **Prerequisites** | TC-005 passed; NFS path accessible |
| **Steps** | 1. Check for file `<nfsPath>/.lognest_offsets`<br>2. Verify it contains valid JSON |
| **Expected Result** | File exists with JSON dictionary mapping file paths to byte offsets |
| **Priority** | High |

---

### TC-020: Dashboard Run Switching

| Field | Value |
|-------|-------|
| **ID** | TC-020 |
| **Name** | Dashboard Run Selection |
| **Objective** | Verify switching between collection runs in the dashboard works |
| **Prerequisites** | TC-006 passed; port-forward active; at least one run exists |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" "http://localhost:18080/?run=<run_name>"` |
| **Expected Result** | HTTP 200 |
| **Priority** | Medium |

---

### TC-021: On-Demand History Visibility

| Field | Value |
|-------|-------|
| **ID** | TC-021 |
| **Name** | On-Demand Collection History in UI |
| **Objective** | Verify triggered on-demand jobs appear in the collection page |
| **Prerequisites** | TC-015 passed; port-forward active |
| **Steps** | 1. GET `/collect` page<br>2. Check for presence of on-demand job references |
| **Expected Result** | Page loads successfully (on-demand history visible or empty state shown) |
| **Priority** | Medium |

---

### TC-022: 404 for Missing File

| Field | Value |
|-------|-------|
| **ID** | TC-022 |
| **Name** | 404 Response for Non-Existent File |
| **Objective** | Verify the system returns 404 for download requests of non-existent files |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/download/log/fake-run/fake-file.log` |
| **Expected Result** | HTTP 404 |
| **Priority** | Medium |

---

### TC-023: Collector Dual-Phase Execution

| Field | Value |
|-------|-------|
| **ID** | TC-023 |
| **Name** | Collector Runs Both Phases |
| **Objective** | Verify the collector executes Phase 1 (node-local) and Phase 2 (API) |
| **Prerequisites** | At least one collection job has run |
| **Steps** | 1. Retrieve logs from a completed collector Job pod<br>2. Search for "Phase 1" and "Phase 2" markers |
| **Expected Result** | Both phase markers appear in collector logs |
| **Priority** | Medium |

---

### TC-024: Ingress Resource Created

| Field | Value |
|-------|-------|
| **ID** | TC-024 |
| **Name** | Ingress Resource Exists |
| **Objective** | Verify an Ingress resource is created for external access |
| **Prerequisites** | TC-001 passed |
| **Steps** | 1. `kubectl get ingress -n lognest`<br>2. Verify at least 1 Ingress exists |
| **Expected Result** | Ingress resource exists with configured host |
| **Priority** | Medium |

---

### TC-025: ServiceAccount Created

| Field | Value |
|-------|-------|
| **ID** | TC-025 |
| **Name** | ServiceAccount Exists |
| **Objective** | Verify the lognest ServiceAccount is created |
| **Prerequisites** | TC-001 passed |
| **Steps** | 1. `kubectl get sa lognest -n lognest` |
| **Expected Result** | ServiceAccount `lognest` exists |
| **Priority** | Medium |

---

### TC-026: RBAC Permissions

| Field | Value |
|-------|-------|
| **ID** | TC-026 |
| **Name** | ClusterRole Has Required Permissions |
| **Objective** | Verify the ClusterRole includes batch/jobs permission for on-demand triggering |
| **Prerequisites** | TC-001 passed |
| **Steps** | 1. `kubectl get clusterrole lognest-collector -o jsonpath='{.rules}'`<br>2. Check for `jobs` in the rules |
| **Expected Result** | ClusterRole rules include `jobs` resource |
| **Priority** | Medium |

---

### TC-027: Namespace Cleanup on Uninstall

| Field | Value |
|-------|-------|
| **ID** | TC-027 |
| **Name** | Namespace Cleaned After Uninstall |
| **Objective** | Verify namespace is deleted or terminating after Helm uninstall |
| **Prerequisites** | Completed all functional tests |
| **Steps** | 1. Run `helm uninstall lognest -n lognest`<br>2. Wait 60 seconds<br>3. Check namespace status |
| **Expected Result** | Namespace is `NotFound` or `Terminating` |
| **Priority** | High |

---

### TC-028: PV Cleanup on Uninstall

| Field | Value |
|-------|-------|
| **ID** | TC-028 |
| **Name** | Persistent Volume Cleaned After Uninstall |
| **Objective** | Verify PVs associated with LogNest are removed |
| **Prerequisites** | TC-027 started |
| **Steps** | 1. `kubectl get pv --no-headers | grep lognest`<br>2. Count remaining PVs |
| **Expected Result** | No PVs with "lognest" remain |
| **Priority** | High |

---

### TC-029: NFS Data Preserved After Uninstall

| Field | Value |
|-------|-------|
| **ID** | TC-029 |
| **Name** | NFS Log Data Survives Uninstall |
| **Objective** | Verify log data on NFS is NOT deleted when the chart is uninstalled |
| **Prerequisites** | TC-027 completed; NFS path accessible |
| **Steps** | 1. Check `<nfsPath>/logs/` directory still exists<br>2. Verify log files from previous runs are intact |
| **Expected Result** | NFS data directory and log files still present |
| **Priority** | High |

---

### TC-030: Reinstall Reads Existing Data

| Field | Value |
|-------|-------|
| **ID** | TC-030 |
| **Name** | Reinstall Discovers Previous Log Data |
| **Objective** | Verify a fresh install picks up existing log data from NFS |
| **Prerequisites** | TC-029 passed |
| **Steps** | 1. Reinstall LogNest with same values<br>2. Wait for UI pod to be ready<br>3. Query `/api/stats`<br>4. Check `runs` count |
| **Expected Result** | API reports runs > 0 (previous data visible) |
| **Priority** | High |

---

### TC-031: Search Endpoint

| Field | Value |
|-------|-------|
| **ID** | TC-031 |
| **Name** | Search Page Loads |
| **Objective** | Verify the cross-run search page is accessible |
| **Prerequisites** | TC-002 passed; port-forward active |
| **Steps** | 1. `curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/search` |
| **Expected Result** | HTTP 200 |
| **Priority** | Medium |

---

### TC-032: Namespace Filtering

| Field | Value |
|-------|-------|
| **ID** | TC-032 |
| **Name** | Namespace Filtering in Files Tab |
| **Objective** | Verify the files tab can filter logs by namespace |
| **Prerequisites** | TC-006 passed; multiple namespaces have logs collected |
| **Steps** | 1. Access `/files` page with namespace filter parameter<br>2. Verify returned files belong only to the specified namespace |
| **Expected Result** | Only files matching the filtered namespace are displayed |
| **Priority** | Medium |

---

### TC-033: Multi-Pod Merged View

| Field | Value |
|-------|-------|
| **ID** | TC-033 |
| **Name** | Multi-Pod Log Merge View |
| **Objective** | Verify selecting multiple pods shows merged logs sorted by timestamp |
| **Prerequisites** | TC-006 passed; multiple pod logs available |
| **Steps** | 1. Select multiple files in the UI<br>2. POST to `/view-multi` with selected files<br>3. Verify merged output is sorted chronologically |
| **Expected Result** | Merged view displays logs from all selected pods ordered by timestamp |
| **Priority** | Low |

---

### TC-034: Capacity-Based Cleanup

| Field | Value |
|-------|-------|
| **ID** | TC-034 |
| **Name** | Capacity Threshold Cleanup |
| **Objective** | Verify the system deletes oldest runs when disk usage exceeds the configured threshold |
| **Prerequisites** | PVC nearing capacity threshold; multiple runs exist |
| **Steps** | 1. Simulate high disk usage (fill PVC near threshold)<br>2. Trigger a collection run<br>3. Verify oldest runs are deleted until usage drops below threshold |
| **Expected Result** | Oldest runs removed; disk usage drops below configured threshold percentage |
| **Priority** | Medium |

---

### TC-035: Retention Policy Cleanup

| Field | Value |
|-------|-------|
| **ID** | TC-035 |
| **Name** | Time-Based Retention Cleanup |
| **Objective** | Verify runs older than the configured retention period are deleted |
| **Prerequisites** | Runs older than `retentionMonths` exist on NFS |
| **Steps** | 1. Create or simulate runs with timestamps older than retention period<br>2. Trigger a collection run<br>3. Verify old runs are deleted |
| **Expected Result** | Runs older than configured retention months are removed from both NFS and SQLite index |
| **Priority** | Medium |

---

## 5. Test Data Requirements

| Data Item | Description | Source |
|-----------|-------------|--------|
| Test pod | Busybox pod emitting numbered lines at 1/sec | Created during test execution |
| Cluster workloads | Existing pods generating varied log levels | Pre-existing in test cluster |
| NFS mount | Accessible from test runner machine | Infrastructure prerequisite |
| Stale data | Artificially aged run directories | Created for TC-035 |
| High-usage PVC | PVC filled to near threshold | Simulated for TC-034 |

---

## 6. Pass/Fail Criteria

### 6.1 Overall Pass Criteria

- **All High priority tests** must PASS (0 failures allowed)
- **90% of Medium priority tests** must PASS
- **Low priority tests** are informational and do not block release

### 6.2 Individual Test Criteria

| Status | Definition |
|--------|------------|
| **PASS** | Test executed successfully and expected result matched |
| **FAIL** | Test executed but expected result did not match |
| **SKIP** | Test could not be executed due to environment constraints (e.g., NFS not accessible from test runner) |

### 6.3 Blocking Conditions

Testing is blocked and cannot proceed if:
- Helm install fails (TC-001)
- Kubernetes cluster is unreachable
- NFS server is down or inaccessible
- Required tools (`kubectl`, `helm`, `curl`) are unavailable

---

## 7. Test Schedule

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Environment setup | 15 min | Infrastructure ready |
| Phase 1: Install | 2 min | Clean cluster |
| Phase 2: Core (wait) | 5 min | Pods starting |
| Phase 3: UI | 2 min | Pods ready |
| Phase 4: Incremental | 8 min | Test pod running |
| Phase 5: On-demand | 2 min | UI accessible |
| Phase 6: Downloads | 2 min | Log files exist |
| Phase 7: State/Coverage | 3 min | Collection complete |
| Phase 8: Uninstall | 2 min | All tests done |
| Phase 9: Reinstall | 3 min | Uninstall complete |
| **Total** | **~45 min** | — |

---

## 8. Revision History

| Version | Date       | Author   | Description         |
|---------|------------|----------|---------------------|
| 1.0.0   | 2025-01-20 | eliatiya | Initial release     |
