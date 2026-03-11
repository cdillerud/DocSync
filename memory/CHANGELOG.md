# CHANGELOG - GPI Document Hub

## 2026-03-11: Backend Refactor (server.py Monolith → Modular Architecture) ✅

### What Changed
- Created `/app/backend/main.py` as the new application entry point
- Supervisor config updated: `main:app` instead of `server:app`
- `server.py` is now imported as a library module (not served directly)
- All 22+ modular routers in `/app/backend/routers/` are included via `main.py`
- Legacy routes still in `server.py` are included via `api_router`

### Files Created/Modified
- **NEW**: `/app/backend/main.py` — Clean FastAPI entry point
- **FIXED**: `/app/backend/routers/sharepoint.py` — Completed truncated function
- **FIXED**: `/app/backend/routers/vendors.py` — Completed truncated function
- **FIXED**: `/app/backend/routers/migration_routes.py` — Completed truncated functions
- **FIXED**: `/app/backend/routers/square9.py` — Added missing imports
- **FIXED**: `/app/backend/routers/dashboard.py` — Added `db = get_db()` calls, lazy imports
- **FIXED**: `/app/backend/routers/settings.py` — Added missing imports (by testing agent)
- **FIXED**: `/app/backend/routers/pilot.py` — Added `PILOT_SUMMARY_CRON_HOUR_UTC` import

### Test Results
- Backend: 22/22 endpoints pass (100%)
- Frontend: Login, Dashboard, Document Queue, all pages verified (100%)
- Test report: `/app/test_reports/iteration_37.json`

---

## 2026-03-10: Document Layout Fingerprinting ✅

### What Was Built
- Complete "Document Layout Fingerprinting" system for structural document analysis
- Backend: `layout_fingerprint_service.py`, resolver integration, auto-resolution integration
- Database: `document_layout_fingerprints`, `layout_families` collections
- API: `/api/layout-fingerprints/*` endpoints
- Frontend: Admin page at `/layout-fingerprints`, MatchingDebugPanel integration
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
