# GPI Document Hub - Product Requirements Document

## Overview
A **Document Intelligence Platform** that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central (BC). The hub orchestrates document ingestion from multiple sources, AI-powered classification, and BC record linking.

---

## Tech Stack
| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python) |
| Frontend | React + Tailwind CSS + Shadcn/UI |
| Database | MongoDB |
| AI | Gemini 2.5 Flash (via Emergent LLM Key) |
| Email | Microsoft Graph API |
| Storage | SharePoint Online |
| ERP | Dynamics 365 Business Central |

---

## Current Implementation Status

### Completed Features (All tested and verified)

#### Core Platform
- [x] FastAPI modular backend with MongoDB
- [x] React frontend with Shadcn/UI components
- [x] JWT authentication (mock for POC)
- [x] Document upload and storage
- [x] SharePoint integration
- [x] Email ingestion (Graph API)
- [x] AI Classification (Gemini)
- [x] Document Queue (unified)
- [x] Observability & Metrics

#### Workflow Engine
- [x] AP Invoice Workflow Engine
- [x] Multi-Document Type Workflows (10 doc types)
- [x] Square9 Workflow Alignment (retry counter, 17 stages)
- [x] AP Review Workspace (PDF preview, BC posting)

#### Intelligence Layer
- [x] Reference Intelligence v2 (fuzzy matching, OCR tolerance, contextual inference)
- [x] Vendor Intelligence Engine
- [x] Automation Rules Engine
- [x] Label Correction Feedback Loop
- [x] Layout Fingerprint Service
- [x] Vendor Extraction Profiles

#### Architecture
- [x] Backend Modular Router Structure (24+ routers in /routers/)
- [x] BC Environment Hardening (Production reads, Sandbox writes)
- [x] Document Processor Plugin Architecture (3 processors)
- [x] BC Reference Cache Layer (277K records)

#### Transaction Graph Layer (March 11, 2026)
- [x] `transaction_graph_nodes` and `transaction_graph_edges` collections
- [x] `TransactionGraphService` with probabilistic confidence-based edges
- [x] Auto-population from document processing pipeline (additive, non-blocking)
- [x] Graph-assisted resolver bonus integrated into reference_intelligence_service
- [x] Cross-document same-transaction inference via shared references
- [x] Graph API endpoints (stats, nodes, edges, connections, search, bulk-ingest)
- [x] Frontend TransactionGraphPanel on Document Detail page
- [x] Frontend TransactionGraphWidget on Dashboard
- [x] 30/30 automated tests passed

#### Processor Spec Workflow (March 11, 2026)
- [x] `processor_specs` collection with CRUD + generation
- [x] Three outputs: human-readable brief, JSON spec, Emergent-ready prompt
- [x] Spec lifecycle: draft -> ready -> approved -> implemented (or rejected)
- [x] Generate from candidate data
- [x] Full CRUD API + frontend dashboard
- [x] 30/30 automated tests passed

#### Transaction Search Page (March 11, 2026)
- [x] `/transaction-search` page — transaction-aware document retrieval
- [x] 4-tier search: exact -> normalized -> likely -> fuzzy with clear tier labels
- [x] Chain BFS traversal with configurable depth (1-5)
- [x] Provenance/confidence display for every edge
- [x] Node type, vendor, confidence filters
- [x] Connected documents with Open links
- [x] Cross-links from Document Detail graph panel and Dashboard widget
- [x] URL-based search with ?q= parameter
- [x] 26/26 automated tests passed

---

## Key API Endpoints

### Transaction Search (NEW)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/transaction-search?q=... | Main search (exact -> normalized -> likely -> fuzzy) |
| GET | /api/transaction-search/node/{node_id}/chain | Chain from a graph node |
| GET | /api/transaction-search/document/{doc_id}/chain | Chain from a document |

### Transaction Graph
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/graph/stats | Graph aggregate statistics |
| GET | /api/graph/nodes | List nodes with optional type filter |
| GET | /api/graph/edges | List edges with optional filter |
| GET | /api/graph/document/{doc_id}/connections | Document transaction context |
| GET | /api/graph/search?reference=VALUE | Search by reference |
| POST | /api/graph/bulk-ingest | Bulk ingest existing documents |

### Processor Specs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/processor-specs/list | List specs with filters |
| POST | /api/processor-specs/create | Create new spec |
| POST | /api/processor-specs/{id}/generate | Generate brief, JSON, prompt |
| POST | /api/processor-specs/generate-from-candidate | Generate from candidate |

---

## Remaining Tasks

### P1 - Upcoming
- [ ] Package & Publish BC (AL) Extension to Sandbox
- [ ] Add "Create BC Sales Order" Button to UI

### P2 - Future
- [ ] Outbound Document Delivery module
- [ ] Replace mock email service with real provider
- [ ] Multi-step approval routing
- [ ] Entra ID SSO integration
- [ ] Add more document processors

---

## File Structure (Key Files)
```
/app/backend/
├── routers/
│   ├── transaction_search.py       # Transaction search endpoints
│   ├── transaction_graph.py        # Graph CRUD endpoints
│   └── processor_specs.py          # Processor spec endpoints
├── services/
│   ├── transaction_graph_service.py # Graph logic
│   ├── processor_spec_service.py   # Spec generation
│   └── reference_intelligence_service.py # Resolver (with graph bonus)
/app/frontend/src/
├── pages/
│   ├── TransactionSearchPage.js    # Transaction search UI
│   └── ProcessorSpecsPage.js       # Spec dashboard
├── components/
│   └── TransactionGraph.js         # Graph panel + widget
```

---

*Last Updated: March 11, 2026*
