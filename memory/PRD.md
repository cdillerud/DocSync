# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI + Recharts
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-16f — See previous sessions

### Phase 16g — PO Bypass + Vendor Bypass + Batch Alias (Apr 8, 2026)
- Direct vendor profile lookup for `po_expected` in readiness
- `PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass`
- `POST /api/aliases/vendors/batch-resolve`

### Phase 16h — Aggressive Auto-Processing Engine (Apr 8, 2026)
- Smart warning categorization: CRITICAL vs INFORMATIONAL
- Lowered confidence thresholds
- Expanded auto-post: removed AP-only restriction, cap 50, skip reason tracking
- Posting template trust: medium/high → auto-upgrade to ready_auto_draft
- Enhanced re-evaluation results display

### Phase 16i — Automation Rate Dashboard Widget (Apr 8, 2026)
- `GET /api/readiness/automation-rate?days=N` — rate %, trend, top manual vendors
- Circular SVG gauge + Recharts BarChart + Top Manual Vendors list
- Period selector (7d / 30d / 90d)

### Phase 16j — Missing Required Fields Fix: The 421 Unblock (Apr 8, 2026)

**Problem**: 421 documents BLOCKED with `missing_required_fields`. These included fully-resolved vendors like TUMALOC (2773 docs learned), CARGOMO, ROTONDO, GROUPWA. The check only looked at `extracted_fields` for vendor/invoice_number/amount — missing vendor_canonical, bc_vendor_number, normalized_fields, external_document_no.

**Root cause**: `required_fields_complete` in `compute_signals()` only checked `extracted_fields.vendor`, `extracted_fields.invoice_number`, and `extracted_fields.amount`. If AI extraction didn't populate those exact fields (even though vendor was matched via alias, BC lookup, or resolution), the doc was hard-blocked.

**Fix — 3 changes:**

1. **Broadened field lookup** in `compute_signals()`:
   - Vendor: checks `extracted_fields.vendor` + `vendor_canonical` + `bc_vendor_number` + `vendor_resolution.vendor_no` + `unified_vendor_match.bc_vendor_no`
   - Invoice number: checks `extracted_fields` + `normalized_fields` + `external_document_no`
   - Amount: checks `extracted_fields` + `normalized_fields` for all amount variants
   - Non-invoice doc types (BOL, shipping): only require vendor, not invoice#/amount

2. **Downgraded from BLOCKING to WARNING** when vendor IS resolved:
   - If vendor is resolved but other fields missing → `missing_required_fields` becomes a warning, doc goes to `ready_auto_draft` instead of `blocked`
   - If vendor is NOT resolved → stays as blocking (correct behavior)

3. **Broadened `check_ap_ready_to_post()`** in `ap_auto_post_service.py`:
   - `invoice_no` also checks `external_document_no`
   - `amount` also checks `nf.total_amount`, `ef.invoice_amount`
   - `vendor_raw` also checks `vendor_canonical`

**Expected production impact**: ~400+ documents should move from `blocked` → `ready_auto_draft` after deploy + re-evaluate. Review Queue should drop significantly.

**Files changed:**
- `/app/backend/services/document_readiness_service.py`
- `/app/backend/services/ap_auto_post_service.py`

## Pending Production Steps
1. Deploy: Save to Github → `git pull && docker compose up -d --build`
2. Re-evaluate: `POST /api/readiness/reevaluate-all`
3. Monitor: Automation Rate widget + Review Queue badge
4. NOFACH bypass: `PATCH /api/vendor-intelligence/profiles/NOFACH/bypass?enabled=true`
5. SC Warehouses alias: Need target vendor_no from user

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P2: Expand stable vendor criteria
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
