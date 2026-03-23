# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint. The system should serve as a continuous feedback loop where every interaction makes the AI smarter.

## Core Principle
**Every interaction is training data. Every correction makes the system smarter.**

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini 3 Pro via Emergent LLM Key + Azure OpenAI fallback
- **External APIs**: Microsoft Graph, Business Central, SharePoint
- **Feedback Loop**: Unified feedback capture → learning signals → AI prompt enrichment

## Credentials
- Web UI: admin / admin

## Completed Work

### Core Platform
- PO Candidate Extraction, Square9 stage-counts fix, FastAPI dependency injection fix
- Auto-post AP invoices for stable vendors (with stable vendor confidence boost)
- Azure OpenAI fallback classifier (confidence < 0.70 triggers fallback)
- Freight GL routing extensions, Square9 decommission endpoints
- BC catalog sync, Drop-Ship vs Warehouse SO routing
- Warehouse SO Booked Notifications, BC Shipment Sync
- BC Customer + Salesperson Cache Sync & Rep Assignment (Step 1)
- BC Factbox Document Links (Zetadocs Replacement) + AL Extension
- Frontend Consolidation (38 → 8 pages), App Versioning (v1.6.0)

### Intake Benchmark (Mar 2026)
- Full benchmark workspace: run setup, scoring, auto-population, results, Excel export
- SharePoint folder scan (scan S9 output folders via Graph API)
- Folder Alignment Report (S9 vs GPI Hub folder comparison)
- Auto-Post Readiness Panel (criteria pass rates, blocker analysis)
- Truth auto-seeding from GPI extraction
- Hierarchical folder comparison (subfolder = bonus, not error)

### Vendor Intelligence (Mar 2026)
- Vendor Inference Service — 6 strategies
- "No Vendor Expected" classification (Letters of Auth, W9 forms, etc.)
- Noise file detection (PNGs, QR codes)
- Vendor name casing normalization

### Feedback Loop Architecture (Mar 22, 2026)
- Unified Feedback Loop Service (`feedback_loop_service.py`)
- Every user action captured: vendor corrections, reclassifications, amount/PO edits, approvals, folder moves
- Immediate learning signal application
- AI prompt enrichment via `build_feedback_context_for_prompt()`
- Wired into documents.py update flow and ap_review.py save flow

### LLM Optimization (Mar 22, 2026 — Session 2)
**Critical bugs fixed:**
1. Feedback context was never injected (vendor_id not passed) — FIXED
2. Vendor hints used filename instead of vendor name — FIXED
3. Secondary LLM path had no feedback injection — FIXED
4. Model upgraded: gemini-3-flash-preview → gemini-3-pro-preview
5. Chain-of-thought prompting: IDENTIFY → CLASSIFY → EXTRACT → ROUTE
6. General recent corrections always included in every LLM call

### Feedback Loop Health Dashboard (Mar 22, 2026 — Session 2)
- Settings > Feedback Loop tab (view-only)
- Backend: `GET /api/feedback-loop/health`
- Metrics: total events, applied rate, aliases, classification examples, routing corrections
- Daily activity chart, events by type, most corrected vendors, recent events

### Before/After Reprocess Comparison (Mar 22, 2026 — Session 2)
- Settings > Before/After tab
- Backend: `POST /api/reprocess-comparison/run`, `GET /api/reprocess-comparison/status`, `GET /api/reprocess-comparison/results/{run_id}`, `GET /api/reprocess-comparison/runs`
- Snapshots current classification results, re-runs LLM pipeline, compares field-by-field
- Does NOT overwrite production data — safe to run anytime
- Shows: summary cards, fields that changed, per-document before/after with verdict badges
- Background processing with live progress polling
- "Changes Only" filter for focused review

### Auto-Post Confidence (Mar 22, 2026)
- Stable vendor score wired into auto-post eligibility
- Confidence formula: stable_flag + score >= 0.85 → max(raw, stable_score)

### DS PO Auto-Creation (Mar 22, 2026 — Session 3)
- `POST /api/gpi-integration/ds-purchase-orders/auto-create/{doc_id}` — Creates a Drop-Ship Purchase Order in BC when a DS_Sales_Order is approved/released
- Preconditions: doc_type=DS_Sales_Order, ds_po_pending=True, BC SO status=Released
- Idempotent: returns existing PO info if ds_po_created=True
- DEMO_MODE bypass for preview env (simulates PO creation)
- **Auto-resolution trigger**: `auto_resolution_service.py` checks DS PO eligibility during background processing and fires auto-create when conditions met
- **Router trigger**: `create_sales_order_from_document` spawns background task for DS PO auto-creation immediately after DS SO auto-approval
- Tests: 9 pytest cases covering happy path, idempotency, rejection, vendor validation, BC SO linkage

### SH_Invoice Document Type (Mar 22, 2026 — Session 3)
- **New document type**: `SH_Invoice` (Storage & Handling Invoice) for warehouse cost-only charges
- **Workflow**: received → classified → pending_approval → approved → exported (never auto-post)
- **Cost-only SO endpoint**: `POST /api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}` creates BC Sales Orders with GL Account type lines (not Item type)
- GL account resolution: Freight GL service → hub_config `sh_default_gl_account` fallback
- Processor assignment determines SharePoint subfolder routing (Andy vs Ellie)
- **Admin endpoints**: `POST /api/admin/sh-invoice/{doc_id}/assign-processor`, `GET /api/admin/sh-invoice/queue`
- **Workflow engine**: Added `SH_INVOICE` DocType, `PENDING_APPROVAL` status, `SH_APPROVED`/`SH_REJECTED` events
- Tests: 20 pytest cases covering doc type, workflow, cost-only SO, processor assignment, queue

### BC Factbox UI (Mar 22, 2026 — Session 3)
- Self-contained HTML page at `GET /api/gpi-integration/factbox-ui/{bc_entity}/{bc_document_no}`
- Embeddable in BC control add-in iframe (cross-origin: `X-Frame-Options: ALLOWALL`, `frame-ancestors *`)
- Shows linked documents list (file name link, date, source badge, delete button)
- Drag-and-drop + click-to-browse upload zone (25MB limit, FormData POST, auto-refresh)
- Source badges: GPI Hub (blue), BC Drop (green), Legacy (gray)
- All CSS/JS inline — zero external dependencies

### SharePoint File Preview Fallback (Mar 22, 2026 — Session 4)
- `GET /api/documents/{doc_id}/file` now falls back to SharePoint when local file is missing
- Fallback chain: local disk → MS Graph API → sharepoint_share_link_url redirect (307)
- Gracefully handles invalid Graph credentials (logs error, redirects to share link)
- `GET /api/documents/{doc_id}/preview-url` returns best available preview method
- Priority: local > sharepoint (proxy) > share_link > web_url > none
- Verified: All 4 scenarios tested and passing

### Multi-Field Document Search (Mar 22, 2026 — Session 4)
- MongoDB `$text` index on hub_documents with weighted fields (invoice/PO: 10, vendor: 8, filename: 6, raw_text: 1)
- `GET /api/documents` search param now searches: file_name, vendor_canonical, vendor_raw, invoice_number_clean, po_number_clean, extracted_fields.*, bc_document_no, amount_float
- Three-tier search: $text index (fast, ranked) → multi-field $regex fallback → amount_float exact match
- Backward compatible: same URL, same response shape, just better results
- New `GET /api/documents/search?q=...&limit=20` endpoint with match_fields highlights
- Verified: vendor, PO, invoice, filename, and amount searches all working

### Shipping Document Auto-Close Fix (Mar 23, 2026 — Session 4)
- **Critical bug**: `DocType.SHIPMENT` and `DocType.RECEIPT` don't exist in the enum → `AttributeError` crashed the warehouse workflow on every shipping document, leaving them stuck in "processing/manual" with only the initial "Document Received" event
- **Secondary bug**: `compute_ap_normalized_fields()` only extracts AP fields (vendor, invoice#, amount) — shipping fields like `bol_number`, `ship_date`, `pro_number` were never passed to the warehouse workflow validator
- **Fix**: Removed invalid enum references, added `extracted_fields` fallback for shipping-specific fields in `_update_standard_workflow_status()`
- **Also fixed**: `DocType.SALES_ORDER` (also missing from enum) in the sales workflow path
- **Also fixed**: `reprocess_document` in `services/document_handlers.py` now calls `_update_standard_workflow_status` and `evaluate_auto_clear` for non-AP docs, enabling shipping docs to auto-close on reprocess
- Verified: test shipping doc now correctly transitions to `exported`/`Completed`/`archived=True` both on initial intake and on reprocess

## P0/P1/P2 Backlog

### P0
- Run Before/After comparison on production data to validate LLM improvements

### P1
- Wire rep assignment into SO creation flow (Step 2)
- Investigate remaining `no_bc_match` failures from batch run
- Continue server.py extraction pass 3 (classification, email polling)

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Production email service & Entra ID SSO

## Key API Endpoints
- `POST /api/gpi-integration/ds-purchase-orders/auto-create/{doc_id}`
- `POST /api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}`
- `POST /api/admin/sh-invoice/{doc_id}/assign-processor`
- `GET /api/admin/sh-invoice/queue`
- `GET /api/gpi-integration/factbox-ui/{bc_entity}/{bc_document_no}` (self-contained HTML for BC iframe)
- `GET /api/documents/{doc_id}/pages` (page count + text previews)
- `POST /api/documents/{doc_id}/split` (split PDF at page boundaries)
- `POST /api/documents/{doc_id}/delete-pages` (remove pages in place)
- `GET /api/documents/search?q=...&limit=20` (multi-field search with match highlights)
- `GET /api/feedback-loop/health`
- `POST /api/reprocess-comparison/run`
- `GET /api/reprocess-comparison/status`
- `GET /api/reprocess-comparison/results/{run_id}`
- `GET /api/reprocess-comparison/runs`
- `GET /api/intake-benchmark/runs`
- `POST /api/intake-benchmark/runs/{id}/auto-populate`
- `POST /api/intake-benchmark/runs/{id}/scan-sharepoint`
- `GET /api/intake-benchmark/runs/{id}/folder-alignment`
- `GET /api/intake-benchmark/runs/{id}/auto-post-readiness`

## Key Collections
- `feedback_events` — every user interaction
- `vendor_aliases` — learned vendor name mappings
- `classification_feedback` — few-shot examples from corrections
- `routing_feedback` — folder routing corrections
- `vendor_intelligence_profiles` — stable vendor scores and flags
- `reprocess_comparison_runs` / `reprocess_comparison_results` — before/after comparison data
- `bakeoff_runs` / `bakeoff_documents` — benchmark data

## Known Issues
- Preview env: Graph API token fails (expected — use DEMO_MODE fallback)
- 19 pre-existing integration tests fail due to missing BASE_URL env var
- Before/After comparison on preview test docs shows "regression" because test files are plain text stubs with heuristic-assigned 1.0 confidence — real PDFs will show true improvement
- **FIXED (Session 4)**: Auto-clear doc_type case mismatch — DB stores `AP_INVOICE` but config used `AP_Invoice`, causing all AP invoices to fall through to DEFAULT (threshold 0.0, no vendor check). Now uses case-insensitive config key lookup.

### Bulk File Button (Mar 22, 2026 — Session 2)
- "File" button added to Documents Queue, right next to "Show auto-cleared"
- Select multiple documents via checkboxes → click "File (N)" → routes all selected to their destination SharePoint folders and marks as completed
- Uses existing `POST /api/documents/bulk-file-and-clear` endpoint

### Run Ref Intel Button + Startup Requeue (Mar 22, 2026 — Session 2)
- "Run Ref Intel" button added next to File button on Documents Queue
- When docs selected: triggers ref intel per-doc for selected items
- When no docs selected: batch-triggers ALL "Not Run" docs (up to 500)
- **Startup requeue**: Server now auto-scans for "not_run" ref intel docs on startup and re-enqueues them
- Root cause of "Not Run" docs: in-memory asyncio.Queue lost on server restart — startup requeue prevents this permanently
