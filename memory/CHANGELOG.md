# CHANGELOG - GPI Document Hub

## 2026-03-11: Stable Vendor Auto-Ready Rules (New Feature)

### What Was Built
Complete implementation of a rule-driven mechanism that evaluates vendor stability and automatically routes documents to `auto_ready`, `low_priority_review`, or `manual_review` based on vendor intelligence and document quality signals.

**Backend:**
- **Service**: `/app/backend/services/stable_vendor_service.py` — Core decision engine
  - Vendor stability evaluation (5 checks: volume, automation rate, resolution rate, correction rate, validation pass rate)
  - Document auto-ready eligibility (10 safety checks: vendor stability, validation, duplicates, vendor match, resolver confidence, freight GL, blocking issues, layout families, alerts, amount anomaly)
  - Configurable thresholds stored in MongoDB (`stable_vendor_config` collection)
  - Drift detection and vendor demotion
  - Dashboard KPI metrics
- **Router**: `/app/backend/routers/stable_vendor.py` — 6 API endpoints
- **Pipeline Integration**: Wired into `auto_resolution_service.py` (runs after automation rules)
- **Events**: Emits `stable_vendor.auto_ready`, `.low_priority_review`, `.promoted`, `.demoted`

**Frontend:**
- Dashboard: Stable Vendor Auto-Ready KPI widget (5 headline metrics)
- Document Queue: Routing column with Auto/Low/Manual badges
- Document Detail: Auto-Ready Routing card with vendor stability, score, and decision reasoning

**Safety:** NEVER bypasses validation failures, duplicate detection, or unresolved freight classification

### Test Results
- Backend: 11/11 tests passed (100%)
- Frontend: Dashboard, Queue, Document Detail all verified (100%)
- Test report: `/app/test_reports/iteration_38.json`
- Test file: `/app/backend/tests/test_stable_vendor.py`

---

## 2026-03-11: Backend Refactor (server.py Monolith -> Modular Architecture)

### What Changed
- Created `/app/backend/main.py` as the new application entry point
- Supervisor config updated: `main:app` instead of `server:app`
- `server.py` is now imported as a library module (not served directly)
- Fixed 7 broken router files from the incomplete prior extraction
- Fixed Re-process button 500 error (missing EMERGENT_LLM_KEY)

### Test Results
- Backend: 22/22 endpoints pass (100%)
- Frontend: All verified (100%)
- Test report: `/app/test_reports/iteration_37.json`

---

## 2026-03-10: Document Layout Fingerprinting

### What Was Built
- Complete structural document fingerprinting system
- Backend service, resolver integration, auto-resolution integration
- Database collections, API endpoints, frontend admin page
- Test report: `/app/test_reports/iteration_3.json`

---

## Earlier Work (Pre-March 2026)
- Core platform: Document ingestion, classification, BC linking
- Vendor Intelligence, Automation Rules, Freight GL Routing
- AP Validation, Label Corrections, Alert Patterns
- Email polling, SharePoint migration, Spiro CRM integration
- Sales module, File import, Square9 workflow alignment
- BC Reference Cache, Auto-Resolution Service
- Vendor Extraction Profiles (adaptive interpretation)
