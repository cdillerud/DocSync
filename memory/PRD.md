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

### Post-LLM Refinement Pipeline (Complete - Feb 2026)
- **Vendor Name Normalization**: Maps LLM vendor_raw to canonical BC vendor name via alias table (exact match, prefix match, profile match)
- **Doc Type Refinement**: Uses vendor profiles to correct common confusion (Unknown→AP_Invoice when vendor has AP history; Shipping vs Warehouse based on vendor type keywords)
- **PO Number Validation**: Strips noise prefixes (PO#, PU, P.O.), detects false positives (phone numbers, dates), truncates multi-PO concatenations
- **Confidence Calibration**: Boosts when multiple strong signals align (vendor resolved + key fields extracted); reduces when signals weak
- **Feedback Loop Amplification**: Vendor-specific corrections prioritized in few-shot prompt; frequent correction types get more examples (up to 12)
- **Pipeline Integration**: Runs as Stage 3c between extraction and validation

### Comparison Delta Scoring (Complete - Feb 2026)
- BC-match fields (vendor_no, vendor_canonical, vendor_match_method) excluded from improved/regressed scoring
- Case-insensitive vendor name comparison
- Amount normalization ($, commas, currency codes stripped)
- Confidence micro-jitter (<=0.02) filtered as noise
- PO/invoice/amount only scored when one side empty (found vs lost)
- Frontend: BC-match fields shown dimmed with asterisk + explanatory note

### Intelligent Multi-Page Document Splitting (Complete)
- Boundary detection, smart grouping, auto-split in intake
- Split Preview UI with page thumbnails and boundary markers

### Bulk Reprocess & Comparison (Complete)
- Compare (Preview), Apply Improvements, Full Pipeline Reprocess
- File recovery from MongoDB b64 or SharePoint download

### Derived State Fix (Complete)
- ReadyForPost documents show correct badges

## Backlog
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email / Entra ID SSO
- P3: server.py extraction, auto_clear_service cleanup
- P3: Investigate 205 no_bc_match batch failures
