# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phases 1-3 — Core Platform
- Document Ingestion & Classification, AP Module, Sales Module

### Phase 4 — Continuous Learning
- Learning Dashboard, Review Queue, Feedback Loop, Batch Re-evaluation, 4 Continuous Learning Engines

### Phase 5 — Per-Document Intelligence Engine (Apr 4, 2026)
8 learning dimensions on every document: Outcome Recording, Vendor Intelligence, Confidence Calibration, Positive Reinforcement, Validation Gap Analysis, Extraction Accuracy, Duplicate Intelligence, Escalation Intelligence.

### Phase 6 — Deep Learning Engine (Apr 4, 2026)
5 advanced layers: Extraction Pattern Learning, Document Similarity, Confidence Self-Correction, Vendor Maturity Scoring, Predictive Readiness.

### Phase 7 — Advanced Intelligence Engine (Apr 4, 2026)
7 engines: Line Item Intelligence, Document Flow Sequencing, Amount Pattern Learning, Correction Replay, Field Correlation Learning, Temporal Intelligence, Error Pattern Recognition.

### Phase 8 — Vendor Intelligence Integration (Apr 4, 2026)
All deep learning data wired into the existing Vendor Intelligence page: Maturity column in table, VendorDeepLearningSection in detail panel (maturity score, extraction patterns, line items, amount intelligence, flow prediction, real-time learning).

### Phase 9 — Validation Gap Closers (Apr 4, 2026)
7 active gap closers using learned intelligence:

1. **Confidence Miscalibration** — Routes documents in unreliable confidence bands (<65% historical accuracy) to human review.
2. **PO Validation Enhancement** — Fuzzy PO matching + vendor-specific patterns + document flow cross-reference.
3. **Customer Match Enhancement** — Historical customer suggestions from vendor document history.
4. **Sales Order Match Enhancement** — Cross-references document flow history + fuzzy order number matching.
5. **Duplicate Intelligence** — Learns from false-positive duplicate flags per vendor. Auto-clears duplicate flags when vendor's detection is proven unreliable (80%+ false-positive rate). Tracks trust levels: reliable → moderate → low_confidence → unreliable.
6. **Amount Anomaly Detection** — Uses learned per-vendor amount patterns (mean, std dev, z-score) to detect unusual amounts. High-severity anomalies (z>3) forced to review. Warns on medium anomalies.
7. **Auto-Escalation Intelligence** — Tracks automation success rate per vendor + doc_type combination. Pre-routes consistently failing combos (<30% success over 5+ attempts) to manual review, saving wasted automation cycles.

### Phase 10 — Enhanced LLM Prompt Intelligence (Apr 4, 2026)
3 new intelligence injections into the AI extraction/classification prompt:
1. **Amount Intelligence Context** — Tells the LLM typical invoice amounts for the vendor so it can validate extracted amounts.
2. **Field Correlation Predictions** — Injects learned field→doc_type rules (e.g., "PO prefix 'GPI' → 70% likely AP_Invoice").
3. **Existing injections** — VEP hints, few-shot examples, feedback context, BC classification intelligence, deep learning extraction hints.

Endpoints:
- GET /api/posting-patterns/gap-closer/status (all 7 gaps)
- GET /api/posting-patterns/duplicate-intelligence
- POST /api/posting-patterns/duplicate-intelligence/batch-clear
- GET /api/posting-patterns/escalation-intelligence

## Total Learning Dimensions: 20 (6 core + 5 deep + 7 advanced + 2 intelligence layers)
## Active Gap Closers: 7 (Phase 9)
## LLM Prompt Injections: 6 (Phase 10)
## Background Schedulers: 6+ (BC Sync, Continuous Learning, Self-Correction, Maturity, Predictive Readiness, etc.)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Expand stable vendor criteria (90% auto rate)
- P2: Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7500+ lines), no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
