# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning. Goal: maximize AI autonomy via continuous learning and aggressive validation gap closure.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-16f — See previous sessions

### Phase 16g — Robust PO Bypass + Vendor Processing Bypass + Batch Alias Resolution (Apr 8, 2026)

- Enhanced `evaluate_and_persist()` with direct vendor profile lookup for `po_expected` and `auto_process_bypass`
- New `PATCH /api/vendor-intelligence/profiles/{vendor_no}/bypass` for NOFACH-style vendors
- New `POST /api/aliases/vendors/batch-resolve` for SC Warehouses-style batch alias creation

### Phase 16h — Aggressive Auto-Processing: Inbox Reduction Engine (Apr 8, 2026)

**Problem**: Review Queue had 339 items and growing. Re-evaluation of 1733 docs found 151 corrections but posted **0** to BC. The system was learning but not acting. 177/218 vendors stuck at LOW confidence. The readiness engine was too conservative.

**Root causes identified:**
1. Confidence threshold of 0.80 too high for auto-draft with warnings
2. ALL warnings treated equally — minor ones (no_line_items, po_missing) blocked auto-processing same as critical ones (vendor_needs_review)
3. 3+ warnings of ANY type forced "ambiguous" status = mandatory human review
4. Auto-post in batch re-evaluation only triggered for AP/invoice doc types
5. Auto-post cap too low (25), no visibility into WHY docs weren't posting
6. Vendors with proven posting templates (medium/high confidence) not trusted enough

**5 Fixes Applied:**

**Fix 1: Smart Warning Categorization**
- Split warnings into CRITICAL and INFORMATIONAL categories:
  - CRITICAL: `policy_hold`, `customer_unresolved`, `vendor_needs_review`, `amount_anomaly`, `auto_escalation`
  - INFORMATIONAL: `po_missing`, `no_line_items`, `low_line_item_confidence`
- Only CRITICAL warnings count toward the "ambiguous" threshold (3+)
- Informational warnings alone NEVER block auto-draft when vendor is resolved + fields complete

**Fix 2: Lowered Confidence Thresholds**
- Docs with only informational warnings + core signals green: auto-draft regardless of confidence score
- Docs with critical warnings: threshold lowered from 0.80 to 0.75
- Core readiness = vendor_resolved AND required_fields_complete

**Fix 3: Expanded Auto-Post in Batch Re-evaluation**
- Removed doc_type restriction (was AP/invoice only, now all non-sales types)
- Increased cap from 25 to 50 auto-posts per batch
- Added skip reason tracking (`auto_act_skipped`, `auto_act_skip_reasons`)
- Added `document_type` to projection for better type detection

**Fix 4: Posting Template Trust**
- In `evaluate_and_persist`, looks up vendor's posting pattern analysis
- If template confidence is medium+ AND invoices_analyzed >= 5 AND vendor resolved + fields complete AND no blockers → automatically upgrades `needs_review` to `ready_auto_draft`
- Logged as "TEMPLATE TRUST" in explanations

**Fix 5: Frontend: Re-evaluation Results Enhanced**
- Added "Auto-Posted to BC" counter in results grid
- Added "Auto-Post Skip Reasons" badge display
- Toast message now shows skip count

**Expected production impact:**
- Documents from vendors with resolved vendor + complete fields that were stuck due to po_missing/no_line_items → AUTO-RELEASED
- Documents from 38 medium-confidence + 3 high-confidence vendor templates → AUTO-DRAFTED more aggressively
- Re-evaluation should now actually POST ready documents, with visibility into why others are skipped
- Review Queue 339 should decrease significantly after deploy + re-evaluate

**Files changed:**
- `/app/backend/services/document_readiness_service.py` — All 5 backend fixes
- `/app/frontend/src/pages/LearningDashboard.js` — Enhanced re-evaluation results display

## Active Gap Closers: 10
## Backfill Steps: 15
## Learning Dimensions: 21

## Pending Production Steps
1. Deploy: Save to Github → `git pull && docker compose up -d --build` on Azure VM
2. For NOFACH: `PATCH /api/vendor-intelligence/profiles/NOFACH/bypass?enabled=true&reason=100%25+extraction+failure`
3. For SC Warehouses: `POST /api/aliases/vendors/batch-resolve` with correct vendor_no mapping
4. Re-evaluate: `POST /api/readiness/reevaluate-all`
5. Monitor Review Queue count — should decrease

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration
- P1: PO pending auto-retry queue

## Future / Backlog
- P2: Low-volume vendor review routing
- P2: Correction replay engine activation
- P2: Email sender → vendor mapping
- P2: Expand stable vendor criteria for Auto-Ready
- P3: server.py refactor (7,500+ lines)

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
