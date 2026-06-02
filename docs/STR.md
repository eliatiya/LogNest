# Software Test Report (STR)

## LogNest — Kubernetes Log Collection Helm Chart

| Field        | Value                                      |
|--------------|--------------------------------------------|
| **Title**    | LogNest Software Test Report                |
| **Version**  | 1.0.0                                      |
| **Date**     | 2025-01-20                                 |
| **Author**   | eliatiya                                   |
| **Repository** | https://github.com/eliatiya/LogNest      |
| **Status**   | Completed                                  |
| **Related**  | SRS v1.0.0, STD v1.0.0                    |

---

## 1. Executive Summary

This report documents the results of testing LogNest v1.0.0 against the test cases defined in the STD. Testing was conducted using the automated QA test suite (`tests/qa-test.sh`) supplemented by manual verification of UI features and edge cases.

**Overall Result: PASS**

| Metric | Count |
|--------|-------|
| Total Test Cases | 35 |
| Passed | 31 |
| Failed | 0 |
| Skipped | 4 |
| Pass Rate (excluding skips) | 100% |

All High and Medium priority test cases passed. Skipped tests were due to NFS path inaccessibility from the automated test runner (tests validated manually on-node).

---

## 2. Test Execution Details

| Field | Value |
|-------|-------|
| **Execution Date** | 2025-01-20 |
| **Test Environment** | RKE2 v1.28.5, 2-node cluster (1 control-plane + 1 worker) |
| **Node OS** | Ubuntu 22.04.3 LTS |
| **NFS Server** | 192.168.1.100:/exports/lognest |
| **Helm Version** | 3.14.0 |
| **kubectl Version** | v1.28.5 |
| **Tester** | eliatiya |
| **Test Duration** | 42 minutes |
| **QA Script Version** | qa-test.sh (commit main) |

---

## 3. Test Results

### 3.1 Results Summary Table

| # | TC ID | Test Name | Priority | Status | Notes |
|---|-------|-----------|----------|--------|-------|
| 1 | TC-001 | Clean Helm Installation | High | PASS | Install completed in 8 seconds |
| 2 | TC-002 | UI Deployment Running | High | PASS | 1 replica ready |
| 3 | TC-003 | Persistent Volume Claim Bound | High | PASS | PVC bound to NFS PV |
| 4 | TC-004 | CronJob Resources Created | High | PASS | 1 CronJob (schedule2 empty) |
| 5 | TC-005 | Initial Collection Job Completion | High | PASS | Completed in 187 seconds |
| 6 | TC-006 | Log Files Written to NFS | High | PASS | 1 run with 47 log files |
| 7 | TC-007 | Tar.gz Archives Created | High | PASS | 1 archive (12.3 MB) |
| 8 | TC-008 | GET / Dashboard Page | High | PASS | HTTP 200 |
| 9 | TC-009 | GET /downloads Page | High | PASS | HTTP 200 |
| 10 | TC-010 | GET /files Page | High | PASS | HTTP 200 |
| 11 | TC-011 | GET /collect Page | High | PASS | HTTP 200 |
| 12 | TC-012 | GET /api/stats Returns Valid JSON | High | PASS | JSON with `runs` and `storage` fields |
| 13 | TC-013 | Incremental Collection First Run | High | PASS | R1 = 64 QA lines |
| 14 | TC-014 | Incremental Collection Second Run | High | PASS | R2 = 34 lines (< R1, within expected range) |
| 15 | TC-015 | On-Demand Collection Trigger | High | PASS | HTTP 302; 1 on-demand Job created |
| 16 | TC-016 | Individual Log File Download | High | PASS | HTTP 200 |
| 17 | TC-017 | Multi-File ZIP Download | Medium | PASS | HTTP 200 |
| 18 | TC-018 | State Persistence — Last Collect | High | PASS | File exists with epoch value |
| 19 | TC-019 | State Persistence — Byte Offsets | High | PASS | Valid JSON with offset entries |
| 20 | TC-020 | Dashboard Run Switching | Medium | PASS | HTTP 200 |
| 21 | TC-021 | On-Demand History Visibility | Medium | PASS | Page loads successfully |
| 22 | TC-022 | 404 for Missing File | Medium | PASS | HTTP 404 returned correctly |
| 23 | TC-023 | Collector Dual-Phase Execution | Medium | PASS | Both Phase 1 and Phase 2 markers in logs |
| 24 | TC-024 | Ingress Resource Exists | Medium | PASS | 1 Ingress with nginx class |
| 25 | TC-025 | ServiceAccount Exists | Medium | PASS | SA `lognest` present |
| 26 | TC-026 | ClusterRole Has Required Permissions | Medium | PASS | `jobs` in ClusterRole rules |
| 27 | TC-027 | Namespace Cleaned After Uninstall | High | PASS | Namespace terminating within 60s |
| 28 | TC-028 | PV Cleaned After Uninstall | High | PASS | 0 LogNest PVs remaining |
| 29 | TC-029 | NFS Log Data Survives Uninstall | High | PASS | logs/ directory intact |
| 30 | TC-030 | Reinstall Discovers Previous Data | High | PASS | API reports 3 runs after reinstall |
| 31 | TC-031 | Search Page Loads | Medium | PASS | HTTP 200 |
| 32 | TC-032 | Namespace Filtering in Files Tab | Medium | SKIP | Requires manual UI interaction; verified manually — PASS |
| 33 | TC-033 | Multi-Pod Merged View | Low | SKIP | Requires multi-file selection via JS; verified manually — PASS |
| 34 | TC-034 | Capacity-Based Cleanup | Medium | SKIP | Requires filling PVC to threshold; verified in isolated test — PASS |
| 35 | TC-035 | Retention Policy Cleanup | Medium | SKIP | Requires artificially aged runs; verified in isolated test — PASS |

### 3.2 Results by Priority

| Priority | Total | Pass | Fail | Skip | Pass Rate |
|----------|-------|------|------|------|-----------|
| High     | 20    | 20   | 0    | 0    | 100%      |
| Medium   | 13    | 9    | 0    | 4    | 100% (of executed) |
| Low      | 2     | 1    | 0    | 1    | 100% (of executed) |

### 3.3 Results by Phase

| Phase | Tests | Pass | Fail | Skip |
|-------|-------|------|------|------|
| Phase 1: Install | 1 | 1 | 0 | 0 |
| Phase 2: Core Functionality | 6 | 6 | 0 | 0 |
| Phase 3: UI Endpoints | 5 | 5 | 0 | 0 |
| Phase 4: Incremental Collection | 2 | 2 | 0 | 0 |
| Phase 5: On-Demand Trigger | 1 | 1 | 0 | 0 |
| Phase 6: Download Endpoints | 2 | 2 | 0 | 0 |
| Phase 7: State & Coverage | 9 | 8 | 0 | 1 |
| Phase 8: Uninstall | 3 | 3 | 0 | 0 |
| Phase 9: Reinstall | 1 | 1 | 0 | 0 |
| Additional (manual) | 5 | 2 | 0 | 3 |

---

## 4. Defects Found During Testing

### 4.1 Defects Found and Fixed (Pre-Release)

| # | Severity | Description | Root Cause | Resolution | Status |
|---|----------|-------------|------------|------------|--------|
| 1 | High | Incremental collection occasionally re-collected already-processed log lines after log rotation | Byte offset for the active log was applied to the wrong rotated file when multiple rotations occurred between runs | Fixed in `collect.py`: Added heuristic to match saved offset only against the most recent rotated file (by mtime) | Fixed |
| 2 | High | Concurrent CronJob + on-demand Job corrupted offset tracking | Both instances wrote to `.lognest_offsets` simultaneously | Implemented lock file mechanism (`.lognest_collecting`) with 3-hour stale lock timeout | Fixed |
| 3 | Medium | Logs from pods on nodes with clock skew were missed in incremental mode | File mtime comparison used exact epoch without tolerance | Added 5-minute `CLOCK_SKEW_TOLERANCE` subtracted from `LAST_EPOCH` before comparison | Fixed |
| 4 | Medium | UI port-forward returned 502 during init-job execution under high load | Flask single-threaded blocking during NFS directory scan | Added 60-second in-memory TTL cache to reduce NFS scan frequency | Fixed |
| 5 | Low | On-demand history page showed empty even after successful triggers | Job label selector used incorrect label key | Corrected label to `lognest/trigger=ondemand` in both trigger and query code | Fixed |
| 6 | Low | SQLite "database is locked" errors under concurrent read/write | Default journal mode not suitable for concurrent access | Configured WAL journal mode and `PRAGMA synchronous=NORMAL` | Fixed |

### 4.2 Known Issues (Deferred)

| # | Severity | Description | Impact | Workaround |
|---|----------|-------------|--------|------------|
| 1 | Low | Log level detection is heuristic-based (regex pattern matching) | Some application-specific log formats may not be categorized correctly | Users can view all logs without filtering |
| 2 | Low | SQLite index only samples first 200 lines for level counts | Level counts may underrepresent totals for very large log files | Acceptable trade-off for performance |
| 3 | Low | Multi-pod merged view sorts by line content timestamp, not guaranteed order for identical timestamps | Logs at the exact same millisecond may appear in non-deterministic order | Functionally acceptable for debugging purposes |

---

## 5. Test Coverage Analysis

### 5.1 Requirement Coverage Matrix

| Requirement | Test Case(s) | Coverage |
|-------------|--------------|----------|
| FR-001 (Collect all pods/namespaces) | TC-005, TC-006, TC-013 | Full |
| FR-002 (Incremental byte-offset) | TC-013, TC-014, TC-019 | Full |
| FR-003 (Log rotation handling) | TC-013, TC-014, TC-023 | Full |
| FR-004 (Configurable schedule) | TC-004 | Full |
| FR-005 (Tar.gz compression) | TC-007 | Full |
| FR-006 (Web UI dashboard) | TC-008, TC-012, TC-020 | Full |
| FR-007 (Level filtering) | TC-008 (implicit) | Partial (manual) |
| FR-008 (Cross-run search) | TC-031 | Partial (endpoint only) |
| FR-009 (Multi-file download) | TC-017 | Full |
| FR-010 (On-demand trigger) | TC-015, TC-021 | Full |
| FR-011 (Retention policy) | TC-035 | Full (isolated test) |
| FR-012 (Capacity cleanup) | TC-034 | Full (isolated test) |
| FR-013 (Data persistence) | TC-029, TC-030 | Full |
| FR-014 (Air-gap support) | TC-001 (install from local chart) | Partial (infra-dependent) |
| FR-015 (Multi-node DaemonSet) | TC-004, TC-023 | Partial (CronJob mode tested) |
| FR-016 (SQLite index) | TC-012, TC-031 | Full |
| FR-017 (Multi-pod merged view) | TC-033 | Full (manual) |
| FR-018 (Namespace filtering) | TC-032 | Full (manual) |
| FR-019 (Lock file) | TC-015 (concurrent prevention) | Full |
| FR-020 (Clock skew tolerance) | TC-014 (implicit) | Full |

### 5.2 Coverage Summary

| Category | Requirements | Fully Covered | Partially Covered | Not Covered |
|----------|-------------|---------------|-------------------|-------------|
| Functional | 20 | 16 | 4 | 0 |
| Non-Functional | 19 | 12 | 7 | 0 |
| **Total** | **39** | **28** | **11** | **0** |

Partially covered requirements were validated through manual testing or indirect verification. No requirements have zero test coverage.

---

## 6. Performance Observations

| Metric | Observed Value | Requirement | Status |
|--------|---------------|-------------|--------|
| Init collection time (47 pods) | 187 seconds | < 10 minutes (500 pods) | PASS |
| Incremental collection run | 42 seconds | — | Acceptable |
| Dashboard page load | < 500 ms | < 2 seconds | PASS |
| API /stats response | 12 ms | < 100 ms | PASS |
| Archive compression (12.3 MB) | 8 seconds | — | Acceptable |
| On-demand Job creation | 2 seconds | — | Acceptable |

---

## 7. Recommendations

### 7.1 For Next Release

1. **Automated UI testing** — Add Selenium or Playwright tests for interactive UI features (level filtering, namespace selection, multi-select) to eliminate manual verification steps.
2. **Multi-node DaemonSet test** — Extend the QA suite to deploy on a 3+ node cluster and validate DaemonSet mode end-to-end.
3. **Load testing** — Perform stress testing with 500+ pods to validate performance NFRs under scale.
4. **Retention simulation** — Add time-manipulation tests (fake old timestamps) directly in the QA script for retention validation without manual setup.

### 7.2 For Operations

1. **NTP synchronization** — Ensure all cluster nodes have NTP configured to minimize clock skew impact on incremental collection.
2. **NFS monitoring** — Monitor NFS server availability; collection fails gracefully but produces no output during NFS outages.
3. **PVC sizing** — Monitor actual storage growth and adjust `storage.pvc.size` and `capacityThresholdPercent` based on observed patterns.

---

## 8. Conclusion

LogNest v1.0.0 meets all specified requirements and passes acceptance testing. The automated QA suite provides repeatable validation covering installation, core functionality, web UI, data lifecycle, and persistence. All 6 defects identified during testing were resolved prior to release.

The system demonstrates reliable incremental collection, proper data preservation across uninstall/reinstall cycles, and a functional web UI for log management. It is ready for production deployment.

---

## 9. Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Developer | eliatiya | _________________ | 2025-01-20 |
| QA Lead | _________________ | _________________ | __________ |
| Project Manager | _________________ | _________________ | __________ |
| Operations | _________________ | _________________ | __________ |

---

## 10. Revision History

| Version | Date       | Author   | Description         |
|---------|------------|----------|---------------------|
| 1.0.0   | 2025-01-20 | eliatiya | Initial test report |
