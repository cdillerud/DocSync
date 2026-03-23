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
- **server.py Extraction Pass 3**: Reduced from 7879 to 6874 lines
  - Email polling logic → `services/email_polling_service.py` (authoritative)
  - Classification pipeline → `services/classification_helpers.py` (authoritative)
  - Rewired 8 consumer modules to import from extracted services
- **Rep Assignment in SO Creation**: Wired salesperson code from BC customer record into SO creation flow
  - `_lookup_bc_customer` returns (customer_number, salesperson_code) tuple
  - `create_sales_order` includes `salesperson` field in BC API payload
  - Document record stores `assigned_salesperson_code` for audit trail
- **Salesperson Performance Dashboard**: New "Rep Performance" tab in Sales & Inventory Hub
  - 3 API endpoints: /overview, /trend, /detail/{code}
  - KPI cards, bar + line charts, ranked leaderboard, rep drill-down, unassigned docs alert
- **Auto-Post Readiness Improvements** (targeting 76.8% → higher):
  - Active vendor resolution: When vendor_canonical not found on hub_doc, runs lookup_vendor_alias (aliases, BC cache, fuzzy matching), direct alias lookup, and BC cache name match
  - Expanded PO number sources: ai_extraction, normalized_fields, bc_po_number, purchase_order_number, linked BC records
  - Added vendor_resolution_methods tracking in readiness response for observability

## Code Architecture
```
/app/backend/
├── server.py                              # Core orchestration (6874 lines)
├── main.py                                # App startup, router registration
├── deps.py                                # Shared config, DB connection
├── routers/
│   ├── salesperson_dashboard.py           # Rep performance metrics API
│   ├── bakeoff.py                         # Intake benchmark (updated: active vendor resolution)
│   ├── documents.py                       # Document CRUD + search
│   ├── email_polling.py                   # Email poll trigger
│   ├── mailbox_sources.py                 # Dynamic mailbox management
│   ├── settings.py                        # Email watcher config
│   ├── sharepoint.py                      # SharePoint operations
│   ├── workflows.py                       # Workflow management
│   └── reference_intelligence.py          # BC reference resolution
├── services/
│   ├── email_polling_service.py           # Extracted email polling (authoritative)
│   ├── classification_helpers.py          # Extracted classification (authoritative)
│   ├── auto_post_service.py               # AP auto-posting + SO creation (rep assignment)
│   ├── business_central_service.py        # BC API client (salesperson in SO)
│   ├── vendor_matching.py                 # Multi-source vendor resolution
│   ├── config_service.py                  # Token management
│   ├── bc_api_helpers.py                  # BC companies/sales orders
│   ├── document_handlers.py               # Document processing
│   └── derived_state_service.py           # UI state from events
/app/frontend/src/pages/
│   ├── SalespersonDashboardPage.js        # Rep performance dashboard
│   ├── SalesInventoryHubPage.js           # 3 tabs (Sales, Rep Performance, Inventory)
│   └── ...
```

## Known Limitations
- BC Sandbox and SharePoint Graph API calls fail in preview environment (DEMO_MODE=true)
- 19 pre-existing integration tests fail (env var mocking, low priority)
- 205 `no_bc_match` batch failures need investigation

## Backlog
- P2: Vendor Inventory Dashboard and Sales module
- P2: Product/BOM (Bill of Materials) module
- P2: Production-ready email service and Entra ID SSO
- P3: Continue server.py extraction (5 remaining `from server import` calls)
- P3: Investigate 205 `no_bc_match` batch failures
