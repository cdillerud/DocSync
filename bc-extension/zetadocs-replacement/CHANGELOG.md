# Changelog

All notable changes to **GPI Sales Document Email** are recorded here.

The project follows four-part Business Central app versioning:

`major.minor.feature.fix`

- **Major**: production-breaking redesign or replacement
- **Minor**: major workflow milestone
- **Feature**: grouped functional enhancement
- **Fix**: corrective build or compile-only revision

## Unreleased - Planned 0.16.0.0

### Rhonda review follow-up still awaiting clarification

- Make Pick Ticket UOM use the Item Card warehouse unit of measure.
- Make Warehouse Receiving Notice UOM use the Item Card warehouse unit of measure.
- Change sales-document customer recipient selection to the customer's primary contact.
- Update Purchase Order sent indicators only after the corresponding email is actually sent.
- Update Warehouse Receiving Notice sent indicator only after the email is actually sent.
- Require Released status before sending:
  - Sales Order Confirmation
  - Pick Ticket
  - Warehouse Purchase Order
  - Warehouse Receiving Notice
- Require Pending Prepayment status before sending a Prepayment Notice.
- Send Warehouse Purchase Orders from the ISR associated with the Purchase Header.
- Add an option to omit selected document lines from generated documents.

### Clarification required

- Exact field captions for the Purchase Order and Warehouse Receiving Notice sent indicators.
- Exact source field for the Purchase Header ISR.
- Exact Business Central field/value representing Pending Prepayment.
- Whether primary-contact routing applies only to customer-facing sales documents or literally every document type.
- Required behavior for omitting document lines.
- Exact Item Card field to use as the warehouse unit of measure.
- Whether previews remain available while documents are not in the required status.

### Already confirmed in the current build

- Pick Tickets resolve the primary recipient from the Location Card email.
- Warehouse Receiving Notices resolve the primary recipient from the Location Card email.
- The Warehouse Receiving Notice layout does not contain terms-and-conditions language.

## 0.15.1.1

### Fixed

- Committed pending Sales Order page writes before opening Gamer report previews.
- Prevented `Report.RunModal` from running inside a write transaction for:
  - Gamer Preview Order Confirmation
  - Gamer Preview Prepayment Notice
  - Gamer Preview Pick Ticket
- Applied the same transaction boundary before opening Sales Order email editors to avoid equivalent `Form.RunModal` errors.

## 0.15.1.0

### Added

- Added a **Gamer Documents** menu to the Customer Card.
- Added a **Gamer Documents** menu to the Sales Orders list page.
- Added customer-filtered Gamer Delivery Log and Routing Rules navigation from the Customer Card.
- Added Sales Order Confirmation, Prepayment Notice, and Pick Ticket preview and email actions to the Sales Orders list page.

### Changed

- Labeled Gamer-owned preview, email, delivery-log, routing-rule, and sent-history actions consistently on:
  - Sales Order
  - Sales Orders list
  - Blanket Sales Order
  - Purchase Order
  - Posted Sales Invoice queue
  - Posted Sales Invoices list
- Removed Shipping Agent from the Pick Ticket report and dataset.
- Removed Gamer terms-and-conditions language and URL from the Pick Ticket while retaining the FIFO warehouse instruction and company footer.

### Verified

- Warehouse Receiving Notices already contained no Gamer terms-and-conditions language, so no report change was required.

## 0.15.0.0

### Added

- Added setup guidance for Business Central native document attachment uploads and SharePoint external storage.
- Added **Configure Drag-and-Drop Storage** to GPI SharePoint Archive Setup.
- Documented the standard **Doc. Attachment List Factbox** workflow and external attachment storage scenario.

### Changed

- Manual document uploads use Business Central's native Document Attachment framework rather than a custom browser control.
- GPI-generated PDFs continue using the Zetadocs-compatible archive structure.

## 0.14.x

### Added

- SharePoint archival for successfully sent GPI-generated documents.
- Archive status, path, URL, attempts, and error details in the Delivery Log.
- GPI SharePoint Archive Setup.
- External File Account and File Scenario integration.
- Connection testing and pending archive processing.

### Changed

- Stored PDF content can be cleared only after SharePoint confirms successful file creation.

## 0.13.x

### Added

- Dedicated **GPI Invoice Batch** email scenario.
- Accounting invoice sender status on the posted invoice queue.
- Accounting sender configuration action.

### Fixed

- Corrected the Business Central page object reference from the caption **Email Scenario Assignment** to the object **Email Scenario Setup**.

## 0.12.x

### Added

- Warehouse Receiving Notice.
- Warehouse Receipt Date field on Purchase Orders.
- Consolidated Purchase Order document actions under **Gamer Documents**.
- Conditional Drop Ship, Warehouse PO, and Receiving Notice action availability by Location Code.

## 0.11.x

### Added

- Warehouse Purchase Order workflow for non-`00` locations.
- Vendor recipient resolution, routing rules, delivery logging, preview, and email history.

## 0.10.x

### Added

- Drop Ship Purchase Order workflow for Location Code `00`.
- Vendor recipient resolution, routing rules, delivery logging, preview, and email history.

## 0.9.x

### Added

- Blanket Sales Order report and email workflow.
- Delivery Log and routing-rule integration for blanket orders.

## 0.8.x and earlier

### Added

- Gamer-owned Sales Order Confirmation.
- Gamer-owned Prepayment Notice.
- Gamer-owned Pick Ticket.
- Gamer-owned Posted Sales Invoice.
- Posted Sales Invoice queue and batch processing.
- Document Delivery Log.
- Customer, vendor, location, and document-specific routing rules.
- Native Business Central sent-email relationships and history.
- Sent, draft, discarded, and failed delivery tracking.
