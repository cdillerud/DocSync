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

### Phase 5 — Per-Document Intelligence Engine
8 learning dimensions on every document.

### Phase 6 — Deep Learning Engine
5 advanced layers: Extraction Pattern Learning, Document Similarity, Confidence Self-Correction, Vendor Maturity Scoring, Predictive Readiness.

### Phase 7 — Advanced Intelligence Engine
7 engines: Line Item Intelligence, Document Flow Sequencing, Amount Pattern Learning, Correction Replay, Field Correlation Learning, Temporal Intelligence, Error Pattern Recognition.

### Phase 8 — Vendor Intelligence Integration
All deep learning data wired into Vendor Intelligence page.

### Phase 9 — Validation Gap Closers (7 active)
1. Confidence Miscalibration routing
2. PO Validation Enhancement (fuzzy + vendor patterns)
3. Customer Match Enhancement (historical suggestions)
4. Sales Order Match Enhancement (flow + fuzzy)
5. **Duplicate Intelligence** — Learns false-positive rates per vendor, auto-clears unreliable flags
6. **Amount Anomaly Detection** — Per-vendor z-score detection, high-severity forced to review
7. **Auto-Escalation Intelligence** — Pre-routes failing vendor+doc_type combos to review

### Phase 10 — Enhanced LLM Prompt Intelligence
Amount intelligence context + Field correlation predictions injected into AI extraction prompts.

### Phase 11 — Executive Monitoring Dashboard (Apr 4, 2026)
Clean `/monitor` page showing the 5 KPIs that matter:
1. AI Confidence Accuracy (95-100% band accuracy)
2. Vendor Maturity (Stable+Autonomous / total)
3. Auto-File Rate (% of docs processed without human touch)
4. Validation Gaps (open gaps by type)
5. Escalation Patterns (always-escalate combos)
Plus: Automation Health Score (weighted composite), contextual explanations for each metric.

## Key Routes
- `/` — Inbox
- `/monitor` — Executive Monitoring Dashboard
- `/sales-inventory` — Sales
- `/posting-intelligence` — Posting AI
- `/invoice-trace` — Trace
- `/ai-learning` — AI Learning Dashboard (detailed 20 dimensions)
- `/review-queue` — Review Queue
- `/config` — Settings

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
