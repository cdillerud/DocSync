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
- [x] AP Invoice Workflow Engine (state machines, queues, mutations)
- [x] Multi-Document Type Workflows (10 doc types)
- [x] Square9 Workflow Alignment (retry counter, 17 stages)
- [x] AP Review Workspace (PDF preview, BC posting)

#### Intelligence Layer
- [x] Reference Intelligence v2 (fuzzy matching, OCR tolerance, contextual inference)
- [x] Vendor Intelligence Engine (behavioral profiles, stable vendor detection)
- [x] Automation Rules Engine (configurable routing)
- [x] Label Correction Feedback Loop
- [x] Layout Fingerprint Service
- [x] Vendor Extraction Profiles

#### Architecture
- [x] Backend Modular Router Structure (24+ routers in /routers/)
- [x] BC Environment Hardening (Production reads, Sandbox writes)
- [x] Document Processor Plugin Architecture (3 processors)
- [x] BC Reference Cache Layer (277K records)

#### Transaction Graph Layer (NEW - March 11, 2026)
- [x] `transaction_graph_nodes` collection with dedup by (node_type, reference_value)
- [x] `transaction_graph_edges` collection with probabilistic confidence and provenance
- [x] `TransactionGraphService` in `/app/backend/services/transaction_graph_service.py`
- [x] Auto-population from document processing/resolution pipeline (additive, non-blocking)
- [x] Graph-assisted resolver bonus integrated into reference_intelligence_service.py
- [x] Cross-document same-transaction inference via shared references
- [x] API endpoints: stats, nodes, edges, document connections, search, bulk-ingest, linkage-bonus
- [x] Frontend: TransactionGraphPanel on Document Detail page
- [x] Frontend: TransactionGraphWidget on Dashboard
- [x] Node types: document, purchase_order, sales_order, invoice, bill_of_lading, shipment, customs_entry, bc_record
- [x] Edge provenance: linked_by_extraction, linked_by_resolver, linked_by_processor, linked_by_shared_reference, linked_by_bc_linkage, manual
- [x] 30/30 automated tests passed

#### Processor Spec Workflow (NEW - March 11, 2026)
- [x] `processor_specs` collection with CRUD + generation
- [x] `ProcessorSpecService` in `/app/backend/services/processor_spec_service.py`
- [x] Three outputs: human-readable brief, JSON spec, Emergent-ready implementation prompt
- [x] Spec statuses: draft → ready → approved → implemented (or rejected)
- [x] Generate from candidate data (processor discovery)
- [x] API endpoints: CRUD, generate, set-status, generate-from-candidate, stats
- [x] Frontend: `/processor-specs` page with table, filters, search, create/edit/delete
- [x] Frontend: Detail panel with Brief/JSON/Prompt tabs and copy-to-clipboard
- [x] 30/30 automated tests passed

---

## Key API Endpoints

### Transaction Graph (NEW)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/graph/stats | Graph aggregate statistics |
| GET | /api/graph/nodes | List nodes with optional type filter |
| GET | /api/graph/edges | List edges with optional type/provenance filter |
| GET | /api/graph/document/{doc_id}/connections | Full transaction context for a document |
| GET | /api/graph/search?reference=VALUE | Search graph by reference value |
| GET | /api/graph/node/{node_id} | Get single node |
| GET | /api/graph/node/{node_id}/edges | Get edges for a node |
| POST | /api/graph/document/{doc_id}/ingest | Manual graph ingestion |
| POST | /api/graph/bulk-ingest | Bulk ingest existing documents |
| GET | /api/graph/document/{doc_id}/linkage-bonus | Debug graph scoring bonus |

### Processor Specs (NEW)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/processor-specs/stats | Spec statistics |
| GET | /api/processor-specs/list | List specs with optional status filter |
| POST | /api/processor-specs/create | Create new spec |
| GET | /api/processor-specs/{spec_id} | Get single spec |
| PUT | /api/processor-specs/{spec_id} | Update spec |
| DELETE | /api/processor-specs/{spec_id} | Delete spec |
| POST | /api/processor-specs/{spec_id}/generate | Generate brief, JSON, prompt |
| POST | /api/processor-specs/{spec_id}/set-status | Change spec status |
| POST | /api/processor-specs/generate-from-candidate | Generate from candidate |

---

## Database Collections

### Transaction Graph (NEW)
| Collection | Description |
|------------|-------------|
| transaction_graph_nodes | Graph nodes (documents, references, BC records) |
| transaction_graph_edges | Probabilistic edges with confidence and provenance |

### Processor Specs (NEW)
| Collection | Description |
|------------|-------------|
| processor_specs | Processor implementation specifications |

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
- [ ] Add more document processors (carrier confirmation, packing slip, vendor-specific)

---

## File Structure (Key New Files)
```
/app/backend/
├── services/
│   ├── transaction_graph_service.py    # NEW: Transaction graph logic
│   └── processor_spec_service.py       # NEW: Spec generation logic
├── routers/
│   ├── transaction_graph.py            # NEW: Graph API endpoints
│   └── processor_specs.py              # NEW: Spec API endpoints
/app/frontend/src/
├── pages/
│   └── ProcessorSpecsPage.js           # NEW: Spec dashboard
├── components/
│   └── TransactionGraph.js             # NEW: Graph panel + widget
```

---

*Last Updated: March 11, 2026*
