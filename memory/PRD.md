# GPI Document Hub - Product Requirements Document

## Original Problem Statement
Enterprise document intelligence platform for Gamer Packaging, Inc. (GPI) that automates document classification, routing, approval workflows, and integration with Business Central and SharePoint.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn/UI components
- **AI**: Gemini via Emergent LLM Key
- **External APIs**: Microsoft Graph, Business Central (read+write), SharePoint

## Document Pipeline (11-stage)
```
classification -> extraction -> layout -> entity_resolution -> po_resolution
-> transaction_match -> bundle_detection -> lifecycle_check
-> policy_decision -> document_routing -> learning_capture
```

## PO Resolution System (Hardened v2.3 — Mar 21 2026)

### Multi-Source PO Candidate Extraction
The system extracts PO candidates from ALL available sources:
1. `extracted_field:po_number` (0.90 confidence) — AI-extracted PO fields
2. `extracted_field:purchase_order_number` (0.90)
3. `extracted_field:customer_po` (0.90)
4. `extracted_field:order_number` (0.80)
5. `extracted_field:bol_number` (0.75) — BOL often contains the real PO
6. **NEW v2.3** `extracted_field:subject` (0.72) — Email subject scanned for PO patterns
7. **NEW v2.3** `extracted_field:description` (0.72) — Description/email body scanned
8. **NEW v2.3** `extracted_field:notes` (0.72) — Notes field scanned
9. `filename:PO_prefix` (0.65) — Explicit PO label in filename
10. `filename:alpha_prefix` (0.65) — Alpha-prefix POs (W, WA, WR, PR) in filename
11. `filename:digits` (0.65) — Standalone 5-7 digit numbers in filename
12. `filename:token_split` (0.60) — Delimiter-split tokens validated as PO format
13. `regex:text_patterns` (0.70) — Regex matches in raw text

### v2.3 resolve_po_from_document Wrapper (Mar 21 2026)
Unified document-level resolver that:
- Merges `email_subject` → `subject` in extraction fields
- Merges `email_body` → `description` in extraction fields
- Merges top-level `notes` → `notes` in extraction fields
- Handles existing `po_candidates` deduplication
- Used consistently by: server.py (intake + reprocess), auto_resolution_service.py, po_resolution router batch

### Miss Taxonomy
Every unresolved PO stores an explicit miss_reason:
- `no_po_extracted` — no PO candidates found in document
- `normalized_po_empty` — PO normalized to empty string
- `invalid_po_format` — candidate doesn't match known BC PO patterns
- `cache_no_match` — not found in BC reference cache
- `live_bc_no_match` — not found via live BC API
- `multiple_bc_matches` — multiple distinct POs found
- `vendor_conflict` — ambiguous POs from different vendors
- `bc_lookup_error` — BC API call failed
- `no_bc_match` — exhausted all lookup paths

### PO Format Validation (from real BC cache analysis of 1616 POs)
Valid BC PO patterns:
- Pure numeric 4-7 digits: 100092, 109023
- W-prefix: W102008, W117397
- WA-prefix: WA1848
- WR-prefix: WR106124
- PR-prefix: PR10088
- T-prefix: T1126
- Suffix variants: 104718B, 111597_1

### v2.2 Shipment Resolution
When no purchase_order match is found, the system falls back to matching against
`posted_sales_shipment` records (127K+ in BC cache). Results include:
- `status: "resolved_shipment"` (distinct from `"resolved"` for PO matches)
- `bc_link_status: "linked_shipment"`
- `bc_entity_type: "posted_sales_shipment"`
- `bc_customer_name`, `bc_order_number` for full context

### Production Results
| Metric | v2.2 Prod (500 docs) |
|--------|---------------------|
| Resolved | 64% |
| BC Linked | ~40% |
| Not Found | ~36% |

## Dependency Injection Fix (Mar 21 2026)
- `routers/ap_review.py`: Replaced global `db`/`bc_service` injection with `deps.get_db()` and `get_bc_service()`
- `routers/spiro.py`: Replaced global `db` injection with `deps.get_db()`
- `routers/email_polling.py`: Fixed missing imports from `deps`

## Key Files
- `backend/services/po_resolution_service.py` - PO resolution v2.3 (hardened + subject/description/notes)
- `backend/routers/po_resolution.py` - Metrics + batch-resolve endpoints
- `backend/services/pipeline/document_pipeline.py` - Pipeline with po_resolution stage
- `backend/services/auto_resolution_service.py` - Auto-resolve with PO resolution
- `backend/services/document_handlers.py` - Extracted document handlers
- `backend/services/workflow_handlers.py` - Extracted workflow handlers
- `backend/routers/ap_review.py` - AP Review (refactored deps)
- `backend/routers/spiro.py` - Spiro integration (refactored deps)
- `backend/routers/email_polling.py` - Email polling (fixed imports)
- `backend/tests/test_po_resolution.py` - 42 unit tests
- `backend/tests/test_po_resolution_workflow_fix.py` - 23 integration tests
- `frontend/src/components/BCResolutionWidget.js` - Dashboard widget

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (preview can't authenticate; production uses real BC)

## Completed Work
- ✅ PO extraction from bol_number and file_name (v2.1)
- ✅ Sales Shipment fallback (v2.2, prod 6% → 64%)
- ✅ BC Resolution Dashboard Widget
- ✅ Auto-resolve PO step on intake
- ✅ Inspection_Form document type
- ✅ BC Validation checks ALL PO candidates
- ✅ Square9 import bug fix
- ✅ PO extraction from subject/description/notes (v2.3, Mar 21 2026)
- ✅ resolve_po signature unification (Mar 21 2026)
- ✅ FastAPI dependency injection fix for ap_review.py and spiro.py (Mar 21 2026)
- ✅ email_polling.py missing imports fix (Mar 21 2026)

## P0/P1/P2 Backlog

### P0
- ~~PO extraction from subject/description/notes~~ DONE
- ~~resolve_po signature unification~~ DONE
- server.py monolith refactor (IN PROGRESS — wrappers and duplicate code remain)

### P1
- ~~FastAPI dependency anti-patterns in ap_review.py, spiro.py~~ DONE
- Azure OpenAI integration alongside Gemini for classification
- Investigate remaining `no_bc_match` failures from 500-doc batch

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Branch Constraint
Only use branch: `conflict_150326_1947`

## Credentials
- Web UI: admin / admin
