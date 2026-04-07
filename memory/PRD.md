# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phases 1-12 — See previous PRD versions for full history

### Phase 13 — PO Format Learning Engine (Apr 4, 2026)
15+ PO transformations, records outcomes, applies learned vendor-specific transformations.

### Phase 14 — Vendor Profile PO Learning Integration (Apr 6, 2026)
**Root cause found**: `bc_validation_service.py` always ran PO validation regardless of what the vendor profile had learned. The vendor profile service (`po_expected=False`) was disconnected from the actual validation pipeline.

**Fixes**:
1. **Vendor profile PO learning wired into validation** — Before PO validation, checks vendor profile. If `po_expected=False` (learned from BC history: <5% of vendor's posted PIs have POs), switches to `PO_SKIP` mode.
2. **PO format learning fallback** — If vendor has 10+ PO attempts with <10% match rate, downgrades PO validation from "required" to "if_present".
3. **Multi-PO field parsing** — Splits PO fields containing `/` or `;` separators (e.g., CARGOMO's `W117076/W117185/W117077` -> tries each PO separately).
4. **Monitor dashboard shows**: Escalation detail, Validation gap breakdown, PO gap by vendor.

### Phase 15 — PO Gap Two-Pass Resolution Fix (Apr 7, 2026)
**Root cause found**: `_batch_revalidate_po_gaps()` only tried to find matching PO numbers in BC's `purchaseOrders` endpoint. It NEVER checked the vendor profile's `po_expected` flag. So even when cache synced and vendor profiles learned `po_expected=False`, existing PO gap documents weren't resolved.

**Fixes**:
1. **Two-pass PO revalidation** — Pass 1: checks vendor profile `po_expected` flag + PO format learning match rate. If vendor doesn't need POs, auto-resolves the gap. Pass 2: for remaining docs, tries BC PO matching with intelligence.
2. **Vendor profile force-refresh before PO revalidation** — `run_intelligence_backfill()` now force-rebuilds vendor profiles from the latest BC cache BEFORE running PO revalidation. This ensures profiles reflect newly synced cache data.
3. **Frontend updated** — Backfill results now show `skipped_by_profile` vs `bc_matched` breakdown, and profile refresh count.
4. **Dead code cleanup** — Removed unreachable duplicate return block in `_batch_revalidate_po_gaps`.

**Impact**: When the user triggers the BC cache sync, then runs "Run Intelligence Backfill" on the Monitor dashboard, vendors like TUMALOC (where BC shows no POs) will have their PO gaps auto-resolved in bulk via the vendor profile learning pass.

## Learning Dimensions: 21 total
## Active Gap Closers: 7
## LLM Prompt Injections: 6
## Background Schedulers: 7

## Production Stats (Latest)
- 1535 docs ingested (30-day), 1198 AP docs
- 81% AI confidence accuracy, 93.3% vendor resolve, 71% auto-file
- 17 PIs posted to BC (1.4% — bottleneck: PO validation gaps + vendor profile disconnection)
- Key gap: 670 PO validation failures (TUMALOC = 63%) — NOW FIXABLE via Phase 15

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor, no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" -> `git pull && docker compose up -d --build`.
