# GPI Document Hub — Product Requirements Document

## Original Problem Statement
Build a document intelligence platform (GPI Hub) to automate document-to-ERP completions, decouple legacy systems, and improve automated multi-source PO extraction. Key capabilities:
- "Intake Benchmark" workspace to compare GPI Hub extraction vs Square 9 side-by-side
- AI classification engine with true Feedback Loop
- Automated processing pipelines for Sales Orders (Drop-Ship vs Warehouse) and Freight G/L routing
- Decommission Square9 data paths
- PDF splitting and page deletion matching Square9 parity

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React on port 3000
- **Database**: MongoDB
- **Integrations**: OpenAI GPT-4o / Gemini 3 Pro (Emergent LLM Key), Dynamics 365 BC, MS Graph (Email/SharePoint)
- **Key Pattern**: Derived state via workflow events — UI updates based on event timeline

## What's Implemented

### Core Features (Complete)
- Document ingestion pipeline (email, upload, SharePoint)
- Multi-field text search with MongoDB $text index
- AI extraction + deterministic classification pipeline
- Drop-Ship PO auto-creation in BC
- Intake Benchmark testing suite with auto-post readiness scoring
- SharePoint file preview with fallback logic
- Email polling (AP, Sales, dynamic UI-configured mailboxes)
- Event emission with direct DB fallback (hardened)
- Warehouse workflow with shipping doc auto-close

### Session Work (March 23, 2026)
- **server.py Extraction Pass 3**: Reduced from 7879 → 6874 lines
  - Email polling logic → `services/email_polling_service.py` (authoritative)
  - Classification pipeline → `services/classification_helpers.py` (authoritative)
  - Rewired: bc_draft_service, bc_link_service, document_orchestration_service, document_handlers, routers/settings, routers/email_polling, routers/mailbox_sources, routers/sharepoint → now import from extracted services
- **Rep Assignment in SO Creation**: Wired salesperson code from BC customer record into Sales Order creation flow
  - `_lookup_bc_customer` returns (customer_number, salesperson_code) tuple
  - `attempt_auto_create_sales_order` passes salesperson to order_data
  - `create_sales_order` includes `salesperson` field in BC API payload
  - Document record stores `assigned_salesperson_code` for audit trail

## Code Architecture
```
/app/backend/
├── server.py                              # Core orchestration (6874 lines, down from 7879)
├── main.py                                # App startup, router registration
├── deps.py                                # Shared config, DB connection
├── routers/
│   ├── documents.py                       # Document CRUD + search
│   ├── bakeoff.py                         # Intake benchmark scoring
│   ├── email_polling.py                   # Email poll trigger endpoint
│   ├── mailbox_sources.py                 # Dynamic mailbox management
│   ├── settings.py                        # Email watcher config
│   ├── sharepoint.py                      # SharePoint operations
│   ├── workflows.py                       # Workflow management
│   └── reference_intelligence.py          # BC reference resolution
├── services/
│   ├── email_polling_service.py           # [NEW] Extracted email polling (authoritative)
│   ├── classification_helpers.py          # [NEW] Extracted classification (authoritative)
│   ├── auto_post_service.py               # AP auto-posting + SO auto-creation (updated: rep assignment)
│   ├── business_central_service.py        # BC API client (updated: salesperson in SO payload)
│   ├── bc_reference_cache_service.py      # BC entity cache with salesperson data
│   ├── config_service.py                  # Token management (Graph, BC, Email)
│   ├── bc_api_helpers.py                  # BC companies/sales orders
│   ├── document_handlers.py               # Document processing (updated: direct service imports)
│   ├── classification_pipeline.py         # 5-stage AI classification
│   ├── sharepoint_service.py              # SharePoint operations
│   └── derived_state_service.py           # UI state from events
```

## Remaining server.py Import Dependencies
These lazy imports remain in server.py (lower priority extraction targets):
- `routers/documents.py` → `classify_document` (reclassification)
- `routers/reference_intelligence.py` → `batch_auto_resolve`
- `routers/workflows.py` → `link_document`
- `services/document_handlers.py` → `_update_vendor_profile_incremental`, `_update_standard_workflow_status`, `compute_ap_normalized_fields`

## Known Limitations
- BC Sandbox and SharePoint Graph API calls fail in preview environment (DEMO_MODE=true handles gracefully)
- 19 pre-existing integration tests fail due to missing env var mocking (low priority)
- 205 `no_bc_match` batch failures need investigation

## Backlog
- P1: ~~Wire rep assignment into SO creation flow~~ (DONE)
- P2: Vendor Inventory Dashboard and Sales module
- P2: Product/BOM (Bill of Materials) module
- P2: Production-ready email service and Entra ID SSO
- P3: Continue server.py extraction (vendor profile, workflow status, intake pipeline)
