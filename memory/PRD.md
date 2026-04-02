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
- Vendor Name Normalization (alias→canonical via alias table)
- Doc Type Refinement (vendor profile-based correction)
- PO Number Validation (noise stripping, false positive detection)
- Confidence Calibration (signal-based adjustments)
- Feedback Loop Amplification (vendor-specific + recency-weighted few-shot)
- Pipeline Integration at Stage 3c (between extraction and validation)

### Feedback Loop Fix (Complete - Feb 2026)
- **Fixed**: All event handlers now mark events as `applied=True` (was broken — only vendor corrections were being marked)
- **Added handlers**: `po_correction`, `amount_correction`, `field_edit` (were recorded but never consumed)
- **Approval reinforcement**: Approvals now create positive classification confirmations and reinforce vendor alias mappings
- **Replay endpoint**: `POST /api/feedback-loop/replay` retroactively applies all unapplied events
- **Result**: Application rate went from 0% to 100% (51/51 applied)
- **UI**: "Replay N Unapplied" button on Feedback Loop Health page

### LLM Learning Pipeline Gap Fixes (Complete - Apr 2026)
- Classification corrections now feed into unified feedback loop (documents.py + ap_review.py)
- Sender domain seed queries both `sender` and `sender_email` fields
- VEP profiles seeded from BC cache — 13 → 469 profiles covering all vendors with BC history
- Few-shot builder no longer requires text_snippet — uses filename+vendor context
- Same-type correction noise filtered from prompts and backfilled data
- Unlearnable feedback events force-marked to prevent infinite replay loops
- New `/api/knowledge-seed/close-all-gaps` endpoint runs all gap closers at once
- Knowledge status endpoint expanded with VEP, feedback rate, correction enrichment metrics

### Comparison Delta Scoring (Complete - Feb 2026)
- BC-match fields excluded from improved/regressed scoring
- Normalization (case, amounts, confidence micro-jitter)

### Intelligent Multi-Page Document Splitting (Complete)
- Boundary detection, smart grouping, auto-split, Split Preview UI

### Bulk Reprocess & Comparison (Complete)
- Compare (Preview), Apply Improvements, Full Pipeline Reprocess
- File recovery from MongoDB b64 or SharePoint

### Manual PO Override (Complete - Feb 2026)
- `POST /api/ap-review/documents/{doc_id}/override-po` — sets `manual_po_override=True` and re-runs auto-post
- `mark-ready` endpoint also sets override flag
- `check_ap_ready_to_post()` skips PO check when override is set or source is mark_ready/manual_override
- UI: "Override PO Check" button in Document Detail derived state card

### Derived State Vendor/PO Fix (Complete - Apr 2026)
- **Root cause**: `vendor.match.failed` event added "Vendor not matched" to blocking_issues, but when `bc.validation.failed` fired (PO-only failure), the stale vendor block was never cleared — even when the vendor_match check PASSED
- **Fix 1**: `bc.validation.failed` handler now checks if vendor is NOT in failed_checks → clears stale vendor blocks
- **Fix 2**: `automation.decision.completed` NeedsReview now REPLACES blocking_issues with actual auto-post failures
- **Fix 3**: `validation.completed` warning handler clears vendor blocks when `vendor_resolved=True`
- **Fix 4**: Post-processing checks individual BC validation checks (not just overall status) to clear vendor blocks
- **Fix 5**: Post-processing checks `manual_po_override` flag and clears PO blocking issues + updates state_reason
- **Result**: Documents no longer show contradictory "Vendor not matched" blocking issues when vendor IS matched at 100%

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
