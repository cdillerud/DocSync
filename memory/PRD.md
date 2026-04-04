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
6 learning dimensions on every document: Outcome Recording, Vendor Intelligence, Confidence Calibration, Positive Reinforcement, Validation Gap Analysis, Extraction Accuracy.

### Phase 6 — Deep Learning Engine (Apr 4, 2026)
5 advanced layers: Extraction Pattern Learning, Document Similarity, Confidence Self-Correction, Vendor Maturity Scoring, Predictive Readiness.

### Phase 7 — Advanced Intelligence Engine (Apr 4, 2026)
7 engines: Line Item Intelligence, Document Flow Sequencing, Amount Pattern Learning, Correction Replay, Field Correlation Learning, Temporal Intelligence, Error Pattern Recognition.

### Phase 8 — Vendor Intelligence Integration (Apr 4, 2026)
All deep learning data wired into the existing Vendor Intelligence page: Maturity column in table, VendorDeepLearningSection in detail panel (maturity score, extraction patterns, line items, amount intelligence, flow prediction, real-time learning).

### Phase 9 — Validation Gap Closers (Apr 4, 2026)
4 active gap closers using learned intelligence:

1. **Confidence Miscalibration** — Routes documents in unreliable confidence bands (<65% historical accuracy) to human review. In production: 85-95% band has 50% accuracy → automatically routed to review.
2. **PO Validation Enhancement** — Fuzzy PO matching (strip prefixes, add variants, numeric extraction) + vendor-specific PO patterns from extraction_patterns + document flow cross-reference.
3. **Customer Match Enhancement** — Historical customer suggestions from vendor document history + validation history + document flow sales orders.
4. **Sales Order Match Enhancement** — Cross-references document flow history + fuzzy order number matching (strip zeros, add SO/S- prefixes) to find matches that exact lookup misses.

Endpoint: GET /api/posting-patterns/gap-closer/status

## Total Learning Dimensions: 18 (across Phases 5-7)
## Active Gap Closers: 4 (Phase 9)
## Background Schedulers: 6+ (BC Sync, Continuous Learning, Self-Correction, Maturity, Predictive Readiness, etc.)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module, Email service, Entra ID SSO
- P3: server.py refactor, no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
