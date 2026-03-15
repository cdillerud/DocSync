# GPI Document Hub - Architecture (Post-Remediation)

> Generated after the controlled technical-debt remediation pass of March 2026.

---

## 1. Authoritative Entrypoint

| File | Role |
|------|------|
| **`backend/main.py`** | **Single FastAPI app.** Creates the `app`, registers all routers, CORS, health check, and lifecycle hooks. This is what `uvicorn` serves. |
| `backend/server.py` | **Library.** Contains module-level DB connection, business-logic functions (upload, BC integration, email polling, etc.), the legacy `api_router`, and the `startup()` / `shutdown_db_client()` lifecycle functions that `main.py` calls. Does **not** create or serve a `FastAPI` instance. |
| `backend/server_new.py` | **Deleted.** Was an unused experimental entrypoint. |

### Startup flow

```
uvicorn main:app
  -> main.py creates FastAPI app
  -> main.py imports server (module-level code runs: DB connect, config load)
  -> main.py registers all routers
  -> main.py @on_event("startup") calls server.startup()
       -> creates indexes
       -> initializes services (event, cache, auto-resolve, vendor intel, etc.)
       -> starts background workers (email polling, alert eval, etc.)
```

---

## 2. Routing Convention

All API routers live under **`backend/routers/`** (single directory, single convention).

| Pattern | Example |
|---------|---------|
| Router file | `routers/auth.py`, `routers/ap_review.py`, `routers/spiro.py` |
| Router prefix | Each router sets its own prefix (e.g. `/auth`, `/ap-review`, `/spiro`) |
| App-level prefix | `main.py` adds `/api` when including: `app.include_router(router, prefix="/api")` |
| Effective URL | `/api/auth/login`, `/api/ap-review/vendors`, `/api/spiro/status` |

The legacy `api_router` from `server.py` (prefix `/api`) is still included for routes not yet extracted. The `backend/routes/` directory is **empty** (all modules migrated to `routers/`).

### Router inventory (37 modules)

```
routers/
  admin.py              alerts.py             aliases.py
  ap_review.py *        ap_validation.py      auth.py *
  auto_clear.py         automation_rules.py   bc_integration.py
  bc_sandbox.py         cache.py              dashboard.py
  document_intelligence.py  documents.py      email_polling.py
  events.py             file_import.py        freight_routing.py
  gpi_integration.py    inventory_items.py    inventory_ledger.py
  label_corrections.py  layout_fingerprints.py  mailbox_sources.py
  metrics.py            migration_routes.py   pilot.py
  reference_intelligence.py  sales_dashboard.py  settings.py
  sharepoint.py         spiro.py *            square9.py
  stable_vendor.py      vendor_extraction_profiles.py
  vendor_intelligence.py  vendors.py          workflows.py
```

`*` = migrated from `routes/` during this remediation pass.

---

## 3. Document Processing Pipeline

A canonical pipeline module at **`services/pipeline/document_pipeline.py`** defines the standard processing sequence for any ingested document.

### Stages

| # | Stage | Service | What it does |
|---|-------|---------|--------------|
| 1 | `classification` | `document_intelligence_service` | AI doc-type classification + field extraction |
| 2 | `entity_resolution` | `entity_resolution_service` | Match extracted names/IDs to DB entities (customers, vendors, POs) |
| 3 | `transaction_match` | `transaction_matching_service` | Link document to existing draft transactions |
| 4 | `bundle_detection` | `document_bundle_service` | Group related documents into packets |
| 5 | `lifecycle_check` | `document_lifecycle_service` | Validate document set completeness for an entity |
| 6 | `policy_decision` | `decision_policy_service` | Evaluate automation rules and decide action |
| 7 | `learning_capture` | `learning_loop_service` | Update aggregated automation metrics |

### API

```
POST /api/document-intelligence/pipeline/{doc_id}
     ?stop_after=entity_resolution        (optional: stop early)
     &skip_stages=bundle_detection        (optional: comma-separated)

GET  /api/document-intelligence/pipeline/stages
     -> { "stages": ["classification", ...] }
```

### Key design decisions

- **Wraps, does not rewrite.** Each stage delegates to an existing service function.
- **Non-fatal errors.** A stage failure is logged and recorded but does not abort the pipeline.
- **Structured output.** `PipelineResult` contains per-stage status, duration, and output keys.
- **Partial runs.** `stop_after` and `skip_stages` allow callers to run subsets.

---

## 4. Core Service Domains

| Domain | Key Services | DB Collections |
|--------|-------------|----------------|
| **Document Intelligence** | `document_intelligence_service`, `ai_classifier` | `document_intelligence` |
| **Entity Resolution** | `entity_resolution_service`, `unified_vendor_matcher` | `entity_resolutions`, `vendor_aliases`, `customer_aliases` |
| **Transaction Matching** | `transaction_matching_service` | `transaction_matches` |
| **Document Bundling** | `document_bundle_service` | `document_bundles` |
| **Lifecycle Validation** | `document_lifecycle_service` | `lifecycle_validations` |
| **Decision Policy** | `decision_policy_service` | `decision_policies`, `decision_results` |
| **Learning Loop** | `learning_loop_service` | `learning_events`, `extraction_hints`, `learning_metrics` |
| **Reference Intelligence** | `reference_intelligence_service`, `bc_reference_cache_service` | `matching_diagnostics`, `bc_reference_cache` |
| **Vendor Intelligence** | `vendor_intelligence_service`, `vendor_extraction_profile_service` | `vendor_intelligence_profiles`, `vendor_extraction_profiles` |
| **Inventory Ledger** | `inventory_ledger_service` | `inventory_movements`, `inv_item_settings` |
| **Business Central** | `business_central_service`, `bc_sandbox_service`, `bc_write_safety_guard` | (external API) |
| **Email Ingestion** | Graph API polling (in `server.py`) | `mail_intake_log`, `mail_poll_runs` |

---

## 5. Known Follow-Up Refactor Targets

| Target | Description | Priority |
|--------|-------------|----------|
| **`server.py` (~9400 lines)** | Still contains all legacy business-logic functions (upload, BC calls, email polling, etc.). Should be broken into focused service/utility modules over time. | P1 |
| **`routers/document_intelligence.py`** | Grew to ~660 lines. Could be split into sub-routers per pipeline stage. | P2 |
| **`routers/inventory_ledger.py`** | Large monolithic router. Candidate for splitting. | P2 |
| **`frontend/.../DocumentIntelligencePanel.js`** | Contains UI for all 6+ pipeline stages in one component. Should be broken into sub-components. | P2 |
| **Legacy `api_router` in `server.py`** | Routes still registered directly on `api_router` rather than in modular router files. Extract over time. | P1 |
| **`sales_module.py`** | Standalone module included as a router. Should be migrated into `routers/sales.py`. | P3 |

---

## 6. Compatibility Notes

- **`backend/routes/`** directory exists but is empty (contains only a deprecation notice in `__init__.py`). Safe to delete entirely when all downstream references are confirmed removed.
- **`server.py`** no longer creates a `FastAPI` instance or registers routers. It is purely a library imported by `main.py`.
- All API endpoint paths are unchanged. No frontend modifications were required.

---

*Last updated: March 15, 2026*
