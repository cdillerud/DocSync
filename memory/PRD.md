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
- Sales order processing, customer matching, rep assignment

### Phase 4 — Continuous Learning (Complete)
- Learning Dashboard UI, Review Queue, Feedback Loop
- Batch Re-evaluation Engine
- 4 Continuous Learning Engines (Draft Detection, Cross-Vendor Propagation, Auto-Promotion, Extraction Feedback)

### Phase 5 — Per-Document Intelligence Engine (Complete — Apr 4, 2026)
Every document makes the AI smarter via 6 learning dimensions:
1. Outcome Recording — Full lifecycle tracking
2. Real-Time Vendor Intelligence — Per-vendor accuracy, auto-validation rate
3. Confidence Calibration — AI confidence vs actual outcome by band
4. Positive Reinforcement — Successes reinforce patterns
5. Validation Gap Analysis — WHY high-confidence docs fail
6. Extraction Accuracy — Per-field, per-vendor accuracy tracking

Collections: document_outcomes, vendor_realtime_intelligence, confidence_calibration, validation_gap_log, field_accuracy_tracking

### Phase 6 — Deep Learning Engine (Complete — Apr 4, 2026)
5 advanced intelligence layers:
1. **Extraction Pattern Learning** — Per-vendor, per-field patterns. Remembers which fields appear for each vendor and injects hints into AI prompts.
2. **Document Similarity Engine** — Fingerprints every document. Matches unknown documents to mastered templates via weighted feature vectors.
3. **Confidence Self-Correction** — Periodically samples auto-filed docs and re-evaluates them. Detects decision drift where today's smarter system would decide differently.
4. **Vendor Maturity Scoring** — Multi-dimensional 0-100 score across 6 dimensions (volume, accuracy, consistency, recency, field_coverage, error_rate). Levels: novice → learning → developing → proficient → mastered.
5. **Predictive Readiness** — Before validation completes, predicts whether a document will need human review based on vendor history, AI confidence, field completeness, doc type patterns, and extraction pattern match.

Collections: extraction_patterns, document_fingerprints, self_correction_audits, vendor_maturity_scores, readiness_predictions

Endpoints:
- GET /api/posting-patterns/deep-learning/summary
- GET /api/posting-patterns/deep-learning/extraction-patterns/{vendor_no}
- GET /api/posting-patterns/deep-learning/extraction-hints/{vendor_no}
- POST /api/posting-patterns/deep-learning/find-similar/{doc_id}
- POST /api/posting-patterns/deep-learning/self-correction/run
- GET /api/posting-patterns/deep-learning/self-correction/history
- GET /api/posting-patterns/deep-learning/vendor-maturity/{vendor_no}
- POST /api/posting-patterns/deep-learning/vendor-maturity/compute-all
- POST /api/posting-patterns/deep-learning/predict-readiness/{doc_id}

Background Schedulers:
- Self-correction + vendor maturity: every 4 hours
- Predictive readiness: fires on every document ingestion

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
