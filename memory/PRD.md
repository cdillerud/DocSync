# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction made, every interaction makes the system smarter. Use ALL available data — every interaction, every calculation, every routing decision. The system must continuously self-improve through feedback loops at every layer.

## Original Problem Statement
Build a document intelligence platform (GPI Hub) to automate document-to-ERP completions, decouple legacy systems, and improve automated multi-source PO extraction. Key capabilities:
- "Intake Benchmark" workspace to compare GPI Hub extraction vs Square 9 side-by-side
- AI classification engine with true Feedback Loop
- Automated processing pipelines for Sales Orders (Drop-Ship vs Warehouse) and Freight G/L routing
- Decommission Square9 data paths
- PDF splitting and page deletion matching Square9 parity

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB (gpi_document_hub)
- **Integrations**: OpenAI GPT-4o / Gemini (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)
- **Key Pattern**: Event-driven derived state — UI badges computed from workflow_events timeline

## What's Implemented

### Core Features (Complete)
- Document ingestion pipeline (email, upload, SharePoint)
- Multi-field text search with MongoDB $text index
- AI extraction + deterministic classification pipeline
- Drop-Ship PO auto-creation in BC
- Intake Benchmark testing suite
- SharePoint file preview with fallback logic
- Email polling (AP, Sales, dynamic UI-configured mailboxes)
- Event emission with direct DB fallback (hardened)
- Warehouse workflow with shipping doc auto-close

### Strict Binary AP Auto-Post Pipeline (Complete)
- `ap_auto_post_service.py`: 4-condition check (classified + fields extracted + vendor matched + PO matched)
- Wired into intake (`server.py`), reprocess (`document_handlers.py`), mark-ready (`ap_review.py`)
- AP invoices bypass old auto_clear entirely
- Vendor profile learning from BC cache
- Vendor alias auto-learning from successful BC validation

### Derived State / Status Badge Fix (April 1, 2026 - COMPLETE)
- **Root cause**: `auto_clear=True` shadowed `decision="ReadyForPost"` in event handler
- **Fix**: Restructured to check `decision` FIRST, then fallback to `auto_clear/auto_post`
- ReadyForPost → validation_state=pass, workflow_state=ready, clears blocking_issues/needs_review
- Testing: 100% (iteration_160)

### Phase 1: Bulk Knowledge Seeding (April 1, 2026 - COMPLETE)
- **Problem**: System had 278K BC records, 11K Spiro companies, 117 corrections but was barely using them. LLM flying blind.
- **Solution**: Built `knowledge_seed_service.py` + API endpoints + admin UI

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Vendor Aliases | 7 | 961 | 137x |
| Sender-Domain Mappings | 14 | 122 | 9x |
| Vendor Invoice Profiles | 3 | 603 | 201x |
| Feedback to LLM | ~0 context | Rich profiles + 117 corrections + aliases | ∞ |

- **Vendor Profiles** include: amount stats (mean/median/min/max), PO expected flag, PO format patterns, posting frequency
- **Feedback Prompt Builder** fixed to use `classification_corrections` (117 records) instead of empty `classification_feedback` (2 records), now injects vendor profile intelligence
- **Extraction Prompt** enriched with vendor context from profiles
- **Entity Resolution** alias limit increased 500→2000
- **Knowledge Base admin page** added to Intelligence Hub with health monitoring + Run Full Seed button
- Testing: 100% (17/17 backend, full frontend — iteration_161)

## Key API Endpoints
- `GET /api/documents/search` — Multi-field text search
- `GET /api/documents/{doc_id}` — Document detail with derived state
- `POST /api/documents/{doc_id}/reprocess` — Document reprocessing
- `POST /api/ap-review/documents/{doc_id}/mark-ready` — Triggers direct BC post
- `GET /api/dashboard/inbox-stats` — Inbox metrics
- `GET /api/knowledge-seed/status` — Knowledge base health metrics
- `POST /api/knowledge-seed/run-all` — Run all 3 seeders (idempotent)

## Key Collections
- `bc_reference_cache`: 278,817 records (posted invoices, shipments, POs)
- `vendor_aliases`: 961 (name variant → BC vendor number)
- `vendor_invoice_profiles`: 603 (amount stats, PO patterns, frequency)
- `sender_vendor_map`: 122 (email domain → vendor)
- `classification_corrections`: 117 (human corrections → few-shot examples)
- `spiro_companies`: 11,700 (CRM data)

## Backlog

### Phase 2: Context-Rich LLM Calls (Next Priority)
- P0: Enrich extraction prompt with BC historical examples (few-shot with REAL invoice data)
- P0: Enrich classification with folder path → doc type patterns from 21K folder_classifications
- P1: Auto-confirm on success — when a doc auto-posts, record as positive reinforcement

### Existing Backlog
- P1: Rep Overrides management UI (Admin screen to map customers to reps)
- P1: Teams Adaptive Card integration (webhook for Approve → BC SO)
- P2: Vendor Inventory Dashboard
- P2: Product/BOM (Bill of Materials) module
- P2: Production-ready email service and Entra ID SSO
- P3: Continue server.py extraction
- P3: Clean up dead code in auto_clear_service.py
