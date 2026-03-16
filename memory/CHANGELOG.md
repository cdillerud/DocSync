# GPI Document Hub - Changelog

## [2026-03-16] SharePoint Folder Routing Feature

### Added
- **SharePoint Folder Routing Management Page** (`/sharepoint-routing`)
  - Folder tree visualization based on "Temp Folder Structure 9.15.25.docx"
  - Vendor-to-folder mapping CRUD (31 default mappings)
  - Processor assignment management (Andy, Ellie, Meg, Rhonda, Aaron)
  - Interactive test routing tool
  - Re-seed defaults functionality

- **Backend Router** (`/api/sharepoint-routing/*`)
  - Full CRUD for folder rules, vendor mappings, processor assignments
  - Document folder suggestion endpoint
  - Document folder assignment and move-to-SharePoint endpoints
  - Batch suggest and batch move operations
  - Auto-seeding of default configuration on first access

- **Folder Routing Service** (updated `folder_routing_service.py`)
  - Complete routing logic matching the accounting folder structure
  - Priority-based rules: Canpack override -> Credit Memos -> Tooling -> Freight -> S&H -> Standard
  - Vendor pattern matching for Ball, Canpack, Anchor, OI, freight carriers
  - International/domestic routing
  - Warehouse subfolder routing (Assembly, GT's, Ball Orders, UPS Orders, etc.)

- **AI Classification Enhancement**
  - Updated Gemini prompt with SharePoint routing context
  - Added extraction of routing fields: is_international, is_tooling, is_storage_handling, is_credit_memo, is_dunnage, freight_direction
  - Return_Request classification updated for credit memos

- **Document Pipeline Integration**
  - Auto-compute SharePoint folder suggestion after document classification
  - Store `sharepoint_folder_suggested` and `sharepoint_folder_reason` on hub_documents
  - Display folder suggestion in document detail page with breadcrumb path

- **Document Detail "Move to SharePoint" Button**
  - "Get Folder Suggestion" button when no folder suggestion exists
  - "Move to SharePoint" one-click button after folder is suggested
  - Shows folder path breadcrumbs, routing reason, and move timestamp
  - Both buttons integrated directly in the SharePoint card on document detail page

### Fixed
- **P0: Multi-Page PDF Misclassification** - Root cause: entire multi-page PDF was sent to Gemini, causing shipping content from later pages to overwhelm the classification. Fix: extract first page only using pypdf for classification of multi-page PDFs.
- **Regression: Purchase Invoice Line Items Missing in BC** - Root cause: `create_purchase_invoice_from_document` created the PI header but never called `add_purchase_invoice_lines` to add line items. Fix: added `add_purchase_invoice_lines` function to `gpi_integration_service.py` (mirrors `add_sales_order_lines` pattern) and integrated it into the PI creation flow. Lines are now extracted from `extracted_fields.line_items` and sent via `purchaseInvoices({id})/purchaseInvoiceLines` standard BC API. Frontend updated to show lines_added/lines_total/line_errors.

### Dependencies Added
- `pypdf` - For extracting first page of multi-page PDFs

### Test Results
- Backend: 20/20 tests passed (100%)
- Frontend: 12/12 UI tests passed (100%)
- Test report: `/app/test_reports/iteration_123.json`
