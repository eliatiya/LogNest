# LogNest — Third-Party License & Dependency Report

**Project:** LogNest  
**Version:** 1.0.0  
**Date:** June 2026  
**Prepared for:** Internal Company Release  

---

## 1. Executive Summary

LogNest uses only **permissive open-source licenses** (MIT, BSD, Apache 2.0, PSF, Public Domain). There are **no copyleft restrictions** (no GPL, no AGPL). The software is fully cleared for:

- Internal company deployment
- Production use
- Air-gap / classified environments
- Modification without obligation to share changes
- Commercial distribution (if needed)

---

## 2. Container Images

| Image | Version | License | Source |
|-------|---------|---------|--------|
| alpine/k8s | 1.30.2 | Apache 2.0 | https://hub.docker.com/r/alpine/k8s |
| python | 3.11-slim | PSF License | https://hub.docker.com/_/python |

---

## 3. Python Packages (UI Image)

| Package | Version | License | PyPI Link |
|---------|---------|---------|-----------|
| Flask | 3.0.3 | BSD-3-Clause | https://pypi.org/project/Flask/ |
| Gunicorn | 22.0.0 | MIT | https://pypi.org/project/gunicorn/ |
| kubernetes | 29.0.0 | Apache 2.0 | https://pypi.org/project/kubernetes/ |

---

## 4. Python Standard Library Modules

These are built into Python and require no separate license:

| Module | Used In | Purpose |
|--------|---------|---------|
| os, sys, json | All files | System operations, JSON parsing |
| gzip | collect.py | Decompress rotated .gz log files |
| time, datetime | collect.py, app.py | Timestamps, scheduling |
| tarfile | collect.py | Create .tar.gz archives |
| shutil | collect.py | Directory operations |
| subprocess | collect.py | Execute kubectl commands |
| sqlite3 | index_db.py | SQLite database (Public Domain) |
| pathlib | All files | File path operations |
| concurrent.futures | collect.py | Thread pool for parallel collection |
| io, zipfile | app.py | In-memory zip creation for downloads |
| re, html | app.py | Regex filtering, HTML escaping |

---

## 5. Infrastructure Components

| Component | License | Role in LogNest |
|-----------|---------|-----------------|
| Helm 3 | Apache 2.0 | Chart packaging and deployment |
| kubectl | Apache 2.0 | API-based log collection (Phase 2) |
| Kubernetes API | Apache 2.0 | Pod/log access, job creation |
| NFS Subdir External Provisioner | Apache 2.0 | Dynamic PVC provisioning |
| NGINX Ingress Controller | Apache 2.0 | External access to UI |

---

## 6. License Summary

| License | Components | Key Terms |
|---------|-----------|-----------|
| **MIT** | Gunicorn, LogNest itself | No restrictions. Keep copyright notice. |
| **BSD-3-Clause** | Flask | Keep copyright notice. Don't use author name for endorsement. |
| **Apache 2.0** | Kubernetes, kubectl, Helm, NFS provisioner, kubernetes-python | Keep notice. State changes if modified. Patent grant included. |
| **PSF License** | Python runtime | Keep copyright notice. |
| **Public Domain** | SQLite | No restrictions whatsoever. |

---

## 7. Compliance Requirements

To comply with all licenses, you must:

1. **Keep copyright notices** in the Docker image layers (already included automatically)
2. **Include a NOTICE file** if distributing Apache 2.0 components externally (not required for internal use)
3. **No other obligations** — no source code disclosure, no copyleft, no patent concerns

---

## 8. Risk Assessment

| Risk | Level | Notes |
|------|-------|-------|
| License conflict | **NONE** | All licenses are mutually compatible |
| Copyleft obligation | **NONE** | No GPL/AGPL/LGPL components |
| Patent risk | **LOW** | Apache 2.0 includes explicit patent grant |
| Export control | **NONE** | No cryptographic components (TLS handled by ingress, not LogNest) |
| Data privacy | **LOW** | LogNest stores container stdout/stderr only. No PII processing. |

---

## 9. Approval

| | |
|---|---|
| **Approved for internal release:** | ☐ Yes / ☐ No |
| **Reviewer:** | _________________ |
| **Date:** | _________________ |
| **Notes:** | |

---

*This report was generated for LogNest v1.0.0. Review should be repeated if dependencies are updated.*
