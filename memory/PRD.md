# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Microsoft Graph, Business Central (read+write), SharePoint

## Classification Pipeline (5-stage + PO resolution)
```
PARSE    -> Extract text (pypdf), resolve file
CLASSIFY -> Heuristic-first (6 patterns), then LLM
EXTRACT  -> Merge LLM+existing fields. Gate: >=1 meaningful field
VALIDATE -> BC validation + extraction_quality_gate
ROUTE    -> Auto-clear / review / block with readiness score
```

## Document Pipeline (11-stage)
```
classification -> extraction -> layout -> entity_resolution -> po_resolution
-> transaction_match -> bundle_detection -> lifecycle_check
-> policy_decision -> document_routing -> learning_capture
```

## PO Resolution Pipeline (New - Mar 18 2026)

### Problem
- Shipping docs = largest volume (~1000+)
- BC Link Rate was ~0.5%
- PO resolution signal = 0%
- Most NeedsReview = shipping docs with missing PO

### Solution
1. **PO Extraction Hardening** (`document_intel_helpers.py`)
   - Regex patterns: PO, P.O., Purchase Order, Order No, 5-7 digit numbers
   - Comma-separated PO splitting (e.g., PO.107459,107460 → two candidates)
   - Normalization: strip label noise, uppercase, preserve alphanumeric + hyphens
   - BC PO format: pure numeric (e.g., 109023, 107346)

2. **PO Resolution Service** (NEW: `services/po_resolution_service.py`)
   - Lookup order: BC reference cache → live BC API → local staging fallback
   - BC cache: exact match on normalized_document_no → confidence 0.95
   - BC cache suffix: last 5 digits → confidence 0.65
   - BC API: exact search → confidence 0.90
   - Local staging: po_drafts/so_drafts → confidence 0.60/0.55
   - Multi-PO same vendor: resolves to first PO (not ambiguous)
   - Result statuses: resolved, ambiguous, not_found, skipped
   - Vendor boost: +0.05 confidence for vendor match

3. **Pipeline Integration** (`pipeline/document_pipeline.py`)
   - Added `po_resolution` stage after entity_resolution, before transaction_match
   - Persists po_resolution and po_candidates on document
   - Uses vendor info from entity_resolution for scoring

4. **Transaction Matching** (`transaction_matching_service.py`)
   - Shipping docs: use PO resolution as primary match source
   - Resolved → high-confidence BC PO candidate
   - Ambiguous → multiple candidates for review
   - Not found → legacy fallback search

5. **Auto-Clear Gate** (`auto_clear_service.py`)
   - CHECK 5a: Shipping docs cannot auto-clear without resolved PO
   - Blocks with reason: po_ambiguous or po_not_found

6. **Readiness Engine** (`document_readiness_service.py`)
   - Shipping docs: po_resolved requires actual BC resolution (not just field presence)
   - Non-shipping docs: po_resolved = field presence (backward compatible)

7. **Metrics Endpoint** (NEW: `routers/po_resolution.py`)
   - GET /api/po-resolution/metrics
   - po_resolution: attempted, resolved, ambiguous, not_found, skipped, rate
   - bc_link: attempted, succeeded, rate
   - match_methods distribution
   - by_doc_type breakdown

### Results (Preview environment, 10 shipping docs)
- PO Resolution Rate: 70% (7/10) — up from 0%
- BC Link Rate: 40% (4/10) — up from ~0.5%
- Ambiguous: 0
- Not Found: 3 (docs with no PO or non-BC references)
- Match methods: bc_cache_exact (4), local_po_draft (3)

### Logging
Every document logs:
- [PO_RESOLUTION] extracted candidates
- [PO_RESOLUTION] normalized PO
- [PO_RESOLUTION] BC cache lookup result
- [PO_RESOLUTION] live BC fallback result  
- [PO_RESOLUTION] final resolution status
- [TX_MATCH] shipping doc match via PO resolution

## Key Files
- `backend/services/po_resolution_service.py` - Core PO resolution (NEW)
- `backend/routers/po_resolution.py` - Metrics endpoint (NEW)
- `backend/services/pipeline/document_pipeline.py` - Pipeline with po_resolution stage
- `backend/services/transaction_matching_service.py` - TX matching using PO resolution
- `backend/services/document_readiness_service.py` - Readiness with BC PO signal
- `backend/services/auto_clear_service.py` - Auto-clear PO gate
- `backend/services/classification_pipeline.py` - 5-stage processing pipeline
- `backend/services/bc_validation_service.py` - BC validation + 3-state status
- `backend/services/bc_reference_cache_service.py` - BC cache with 1616 POs
- `backend/services/business_central_service.py` - Live BC API
- `backend/tests/test_po_resolution.py` - 16 unit tests
- `backend/tests/test_po_resolution_api.py` - 22 API tests

## Completed Work (This Session)
- P1: Pipeline Visualization component
- P1: Item Mapping Admin UI  
- P1: BC Validation 3-state status (PASSED/WARNINGS/FAILED)
- P1: Recompute Derived States tool
- P0: PO Resolution Service (extraction, resolution, pipeline, metrics)

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (demo/sandbox mode in preview — production uses real BC)

## P1/P2 Backlog
### P1
- Azure OpenAI integration alongside Gemini for classification
- Run PO resolution on production data (backfill)

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files (server.py, inventory_ledger.py, InventoryLedgerPage.js)
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
