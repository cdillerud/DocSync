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
3. **Multi-PO field parsing** — Splits PO fields containing `/` or `;` separators (e.g., CARGOMO's `W117076/W117185/W117077` → tries each PO separately).
4. **Monitor dashboard shows**: Escalation detail, Validation gap breakdown, PO gap by vendor.

**Impact**: For vendors like TUMALOC (freight/transport) where BC history shows no POs, the system now LEARNS to skip PO validation. This should eliminate ~200+ false validation gaps.

## Learning Dimensions: 21 total
## Active Gap Closers: 7
## LLM Prompt Injections: 6
## Background Schedulers: 7

## Production Stats (Latest)
- 1535 docs ingested (30-day), 1198 AP docs
- 81% AI confidence accuracy, 93.3% vendor resolve, 71% auto-file
- 17 PIs posted to BC (1.4% — bottleneck: PO validation gaps + vendor profile disconnection)
- Key gap: 670 PO validation failures (TUMALOC = 63%)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor, no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
