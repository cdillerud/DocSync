# GPI Document Hub — Product Requirements

## Core Philosophy
**Learn -> Apply -> Improve -> Learn.** Every document processed, every correction, every interaction makes the system smarter.

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
- Boundary detection service with page fingerprinting
- Smart grouping, auto-split in intake pipeline
- Split Preview UI with page thumbnails and boundary markers

### Derived State Fix (Complete)
- ReadyForPost documents show correct badges

### Bulk Reprocess & Comparison (Complete - Feb 2026)
- **Compare (Preview)**: Re-runs LLM classification on all docs, shows before/after without touching production
- **Apply Improvements**: Commits only improved results back to production
- **Full Pipeline Reprocess**: Re-runs entire pipeline on non-terminal docs
- **File Recovery**: Recovers files from MongoDB file_content_b64 or SharePoint when not on disk
- **Smart Delta Scoring (Feb 2026)**:
  - BC-match fields (vendor_no, vendor_canonical, vendor_match_method) excluded from improved/regressed scoring — shown dimmed with asterisk
  - Vendor name comparison is case-insensitive
  - Amount comparison normalizes $, commas, currency codes
  - Confidence micro-jitter (<=0.02) is ignored
  - PO/invoice/amount changes only scored when one side is empty (found vs lost)
- **Frontend**: Settings > Before/After tab with progress, summary cards, field change breakdown, document-level results

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
- P3: Investigate 205 no_bc_match batch failures
