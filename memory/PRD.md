# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phase 1 — Document Ingestion & Classification
- Multi-source ingestion (SharePoint, upload, email)
- AI classification pipeline with feedback loop
- Vendor matching and PO validation

### Phase 2 — AP Module
- Purchase Invoice auto-drafting to BC sandbox
- Posting pattern analysis and templates
- Review Queue for auto-drafted PIs

### Phase 3 — Sales Module
- Sales order processing
- Customer matching
- Rep assignment logic

### Phase 4 — Continuous Learning (Complete)
- Learning Dashboard UI with proof of AI learning
- Review Queue UI for draft PIs
- Feedback Loop: BC edits sync back into AI templates
- Readiness Signal Contradiction fixes with self-learning
- Batch Re-evaluation Engine
- 4 Continuous Learning Engines (Draft Detection, Cross-Vendor Propagation, Confidence Auto-Promotion, Extraction Feedback Loop)

### Phase 5 — Per-Document Intelligence Engine (Complete — Apr 4, 2026)
**Every document now makes the AI smarter.** 6 learning dimensions:
1. **Outcome Recording** — Full lifecycle tracking per document
2. **Real-Time Vendor Intelligence** — Per-vendor accuracy, auto-validation rate, correction rate, confidence gap
3. **Confidence Calibration** — AI confidence vs actual outcome by band (0-50%, 50-70%, 70-85%, 85-95%, 95-100%)
4. **Positive Reinforcement** — Successes reinforce classification, vendor aliases, extraction patterns, posting templates
5. **Validation Gap Analysis** — WHY high-confidence docs fail (per vendor, per check)
6. **Extraction Accuracy Tracking** — Per-field, per-vendor accuracy

**Wired into every document path:**
- Ingestion, Classification, Auto-file, File & Clear, Bulk File
- Approval, Rejection, BC Posting, Field Edits, Manual Linking, Pipeline

**New Collections:** document_outcomes, vendor_realtime_intelligence, confidence_calibration, validation_gap_log, field_accuracy_tracking

**New Endpoints:**
- GET /api/posting-patterns/learning-pulse
- GET /api/posting-patterns/learning-pulse/vendor/{vendor_no}
- GET /api/posting-patterns/learning-pulse/confidence-calibration
- POST /api/posting-patterns/learning-pulse/backfill

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future / Backlog
- P2: Auto-delete on max retries
- P2: Expand stable vendor criteria (90% vs 100%)
- P2: Vendor Inventory Dashboard
- P2: Product/BOM module
- P2: Production-ready email service & Entra ID SSO
- P3: server.py routing extraction/refactor
- P3: Investigate 205 no_bc_match batch failures

## Deployment
Docker Compose on Azure VM. Use "Save to Github" → `git pull && docker compose up -d --build`.
