# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction made, every interaction makes the system smarter. Use ALL available data — every interaction, every calculation, every routing decision.

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB (gpi_document_hub)
- **Integrations**: OpenAI GPT-4o / Gemini (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)

## What's Implemented

### Core Features (Complete)
- Document ingestion pipeline (email, upload, SharePoint)
- AI extraction + deterministic classification pipeline
- Drop-Ship PO auto-creation in BC
- Intake Benchmark testing suite
- SharePoint file preview, Email polling, Event emission

### AP Auto-Post Pipeline (Complete)
- Strict binary 4-condition check (classified + extracted + vendor matched + PO matched)
- Wired into intake, reprocess, and mark-ready flows

### Phase 1: Bulk Knowledge Seeding (April 1, 2026 — COMPLETE)
| Metric | Before | After |
|--------|--------|-------|
| Vendor Aliases | 7 | 962 |
| Sender-Domain Mappings | 14 | 122 |
| Vendor Invoice Profiles | 3 | 603 |
- Knowledge Base admin page in Intelligence Hub

### Phase 2: Context-Rich LLM Calls (April 1, 2026 — COMPLETE)
- **Vendor Context Builder** (`vendor_context_builder.py`) — builds extraction + classification context from BC historical data
  - Extraction context: vendor profile + 3 real BC invoice examples + name variants (~885 chars for TUMALOC)
  - Classification context: BC entity type distribution + strong classification signals ("100% purchase invoices → likely AP_Invoice")
- **Classification pipeline enriched**: Now injects BC classification intelligence before LLM call (Step 3 added after feedback loop)
- **Extraction prompt enriched**: Now includes vendor profile, real invoice examples, PO patterns
- **Auto-Confirm on Success**: When a doc reaches ReadyForPost/Posted, records positive feedback in classification_corrections + reinforces vendor aliases
- **Feedback prompt builder fixed**: Uses classification_corrections (117 records) instead of empty classification_feedback, includes vendor profile intelligence + all 962 aliases

### Derived State Fix (April 1, 2026 — COMPLETE)
- Fixed ReadyForPost documents showing "Failed" badge
- Root cause: `auto_clear=True` shadowed `decision="ReadyForPost"` in event handler

## Key API Endpoints
- `GET /api/knowledge-seed/status` — Knowledge base health metrics
- `POST /api/knowledge-seed/run-all` — Run all seeders (idempotent)
- `GET /api/documents/{doc_id}` — Document detail with derived state
- `POST /api/documents/{doc_id}/reprocess` — Document reprocessing
- `POST /api/ap-review/documents/{doc_id}/mark-ready` — Triggers BC post

## Key Collections
- `bc_reference_cache`: 278,817 records
- `vendor_aliases`: 962 (name variant → BC vendor number)
- `vendor_invoice_profiles`: 603 (amount stats, PO patterns, frequency)
- `sender_vendor_map`: 122 (email domain → vendor)
- `classification_corrections`: 117+ (corrections + auto-confirms → few-shot examples)

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
