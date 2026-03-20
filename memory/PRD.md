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

## PO Resolution System (Hardened v2 — Mar 20 2026)

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

Non-PO patterns (rejected):
- SI- prefixes (shipping invoice refs)
- SSH- prefixes (shipping refs)
- Container numbers (MSKU, TCNU, YMJA)
- Date-based refs, BOL refs, INV refs

### BC Link Result (Standardized)
```json
{
  "status": "linked" | "linked_local" | "failed",
  "bc_record_type": "purchaseOrder" | "local_draft" | null,
  "bc_record_id": "...",
  "link_method": "bc_po_verified:bc_cache_exact" | "local_staging_match" | null,
  "error_code": "bc_auth_error" | "bc_record_not_found" | "network_error" | ...,
  "error_message": "..."
}
```

### Lookup Trace (Audit Trail)
Every PO resolution stores a complete lookup_trace array showing:
- Each candidate tried
- Each lookup source queried (bc_cache, bc_api, local_staging)
- Hit count and result per source
- Errors encountered

### Metrics API
GET /api/po-resolution/metrics returns:
- po_resolution: attempted, resolved, ambiguous, not_found, skipped, rate
- bc_link: attempted, succeeded_real, succeeded_local, failed, rate_real, rate_total
- unresolved_by_miss_reason: {miss_reason: count}
- bc_link_failures_by_reason: {error_code: count}
- lookup_sources: {bc_cache, bc_api, local_staging}
- match_methods distribution
- multi_po_count
- by_doc_type breakdown

### Batch Resolve API
POST /api/po-resolution/batch-resolve?force=true&limit=N returns:
- processed, resolved, ambiguous, not_found counts
- po_resolution_rate, bc_link_success_rate
- miss_reasons breakdown
- bc_link_failures breakdown
- per-document details (doc_id, file_name, status, miss_reason, po_number, bc_link_status)

### Results (Preview, 10 shipping docs, v2 hardened)
| Metric | v1 | v2 | v2.1 (BOL+filename) | Why |
|--------|----|----|---------------------|-----|
| Resolved | 7 (70%) | 4 (40%) | 4 (40%) preview | v2.1 adds BOL/filename candidates; preview blocked by BC auth |
| Not Found | 3 | 6 | 6 (5 bc_lookup_error + 1 invalid) | bc_lookup_error would resolve on prod with live BC |
| BC Cache matches | 4 | 4 | 4 | Same real BC matches in preview |
| False positives | 3 | 0 | 0 | Non-PO refs still correctly rejected |

### v2.1 PO Candidate Sources (Mar 20 2026)
1. `extracted_field:po_number` (0.90 confidence)
2. `extracted_field:purchase_order_number` (0.90)
3. `extracted_field:customer_po` (0.90)
4. `extracted_field:order_number` (0.80)
5. **NEW** `extracted_field:bol_number` (0.75) — BOL often contains the real PO
6. **NEW** `filename:PO_prefix` (0.65) — Explicit PO label in filename
7. **NEW** `filename:alpha_prefix` (0.65) — Alpha-prefix POs (W, WA, WR, PR) in filename
8. **NEW** `filename:digits` (0.65) — Standalone 5-7 digit numbers in filename
9. **NEW** `filename:token_split` (0.60) — Delimiter-split tokens validated as PO format
10. `regex:text_patterns` (0.70) — Regex matches in raw text

## Key Files
- `backend/services/po_resolution_service.py` - PO resolution v2 (hardened)
- `backend/routers/po_resolution.py` - Metrics + batch-resolve endpoints
- `backend/services/pipeline/document_pipeline.py` - Pipeline with po_resolution stage
- `backend/services/transaction_matching_service.py` - TX matching using PO resolution
- `backend/services/document_readiness_service.py` - Readiness with BC PO signal
- `backend/services/auto_clear_service.py` - Auto-clear PO gate
- `backend/services/classification_pipeline.py` - 5-stage processing pipeline
- `backend/services/bc_validation_service.py` - BC validation + 3-state status
- `backend/tests/test_po_resolution.py` - 34 unit tests

## Mocked Services
- Microsoft Graph API (email ingestion - partial)
- JWT Authentication (Entra ID)
- BC API (preview can't authenticate; production uses real BC)

## P1/P2 Backlog
### P1
- Run PO resolution on production data (batch-resolve endpoint ready)
- Azure OpenAI integration alongside Gemini for classification

### P2
- Vendor Inventory Dashboard & Sales module
- Product/BOM module
- Refactor monolithic files
- Production email service & Entra ID SSO
- Decommission legacy Zetadocs

## Credentials
- Web UI: admin / admin
