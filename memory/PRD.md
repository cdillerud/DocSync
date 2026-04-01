# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn → Apply → Improve → Learn.** Every document processed, every correction, every interaction makes the system smarter.

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB (gpi_document_hub)
- **Integrations**: Gemini (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)

## What's Implemented

### Core Features (Complete)
- Document ingestion, AI extraction, classification, vendor matching, auto-post
- Intake Benchmark, SharePoint preview, Email polling, Event emission

### AP Auto-Post Pipeline (Complete)
- Strict binary 4-condition check, wired into all flows

### Knowledge Intelligence (Complete)
- Phase 1: 962 vendor aliases, 122 domain mappings, 603 vendor profiles from BC/Spiro
- Phase 2: Context-rich LLM calls with real BC invoice examples + vendor profiles
- Auto-confirm on success for positive reinforcement
- Auto-seed scheduler: startup + every 6h + post-BC-sync

### Intelligent Multi-Page Document Splitting (Complete)
- **Boundary detection service**: Page fingerprinting (vendor, invoice/PO/BOL numbers, letterhead)
- **Smart grouping**: Contiguous same-vendor same-invoice pages stay together
- **All doc types**: AP_Invoice, BOL, Unknown, PO, SO all splittable
- **Auto-split in intake pipeline**: Multi-page PDFs detected and split during ingestion
- **Split Preview UI**: Page thumbnail strip with boundary markers, group color coding, vendor hints, reference numbers, "Split into N docs" button
- API: GET `/{doc_id}/boundary-analysis`, POST `/{doc_id}/auto-split`
- Testing: 100% boundary detection, 100% frontend (iteration_163, 164)

### Derived State Fix (Complete)
- ReadyForPost documents show correct badges

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
