# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## What's Been Implemented

### Phase 1-3 — Core Platform
- Document Ingestion & Classification (multi-source, AI pipeline, feedback loop)
- AP Module (PI auto-drafting, posting patterns, Review Queue)
- Sales Module (sales orders, customer matching, rep assignment)

### Phase 4 — Continuous Learning
- Learning Dashboard, Review Queue, Feedback Loop
- Batch Re-evaluation Engine
- 4 Continuous Learning Engines (Draft Detection, Cross-Vendor Propagation, Auto-Promotion, Extraction Feedback)

### Phase 5 — Per-Document Intelligence Engine (Apr 4, 2026)
6 learning dimensions fired on EVERY document: Outcome Recording, Vendor Intelligence, Confidence Calibration, Positive Reinforcement, Validation Gap Analysis, Extraction Accuracy.

### Phase 6 — Deep Learning Engine (Apr 4, 2026)
5 advanced layers: Extraction Pattern Learning, Document Similarity Engine, Confidence Self-Correction, Vendor Maturity Scoring, Predictive Readiness.

### Phase 7 — Advanced Intelligence Engine (Apr 4, 2026)
7 engines that learn EVERYTHING from every document:

1. **Line Item Intelligence** — Memorizes line patterns per vendor (descriptions, GL accounts, amounts). Auto-suggests GL mappings for future invoices.
2. **Document Flow Sequencing** — Tracks document arrival order per vendor (BOL → PO → Invoice). Predicts what doc type arrives next.
3. **Amount Pattern Learning** — Learns typical amount ranges per vendor. Detects anomalous amounts using z-score (>2σ flagged). TUMALOC: $295-$1,825, ANCH: ~$9,500.
4. **Correction Replay Engine** — When a human corrects a field, replays that correction across ALL similar vendor documents still in the pipeline.
5. **Field Correlation Learning** — Discovers field→field prediction rules. E.g., `po_prefix=613` → Sales_Order (100% confidence, 7 samples).
6. **Temporal Intelligence** — Learns day-of-week and hour-of-day patterns. Predicts tomorrow's inbox volume. Shows peak/quiet days.
7. **Error Pattern Recognition** — Categorizes failures (scan_quality, empty_document, api_failure, missing_data, format_error, layout_change). Learns from every error.

Collections: line_item_intelligence, document_flow_sequences, amount_patterns, correction_replays, field_correlations, temporal_intelligence, error_patterns

Endpoints:
- GET /api/posting-patterns/advanced-learning/summary
- GET /api/posting-patterns/advanced-learning/line-items/{vendor_no}
- GET /api/posting-patterns/advanced-learning/predict-next/{vendor_no}
- GET /api/posting-patterns/advanced-learning/amount-check/{vendor_no}?amount=X
- GET /api/posting-patterns/advanced-learning/correction-replays
- GET /api/posting-patterns/advanced-learning/volume-prediction
- POST /api/posting-patterns/advanced-learning/backfill

## Total Learning Dimensions: 18
Across 3 learning layers (Phase 5 + 6 + 7), every document now trains the AI across 18 distinct intelligence dimensions.

## Background Schedulers
- BC Sync: periodic
- Continuous Learning Engines: every 2h
- Self-Correction + Vendor Maturity: every 4h
- Predictive Readiness: fires on every document ingestion
- All 7 advanced engines: fire on every document event

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
