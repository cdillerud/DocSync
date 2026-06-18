# Changelog

All notable changes to **GPI Sales Document Email** are recorded here.

The project follows four-part Business Central app versioning:

`major.minor.feature.fix`

- **Major**: production-breaking redesign or replacement
- **Minor**: major workflow milestone
- **Feature**: grouped functional enhancement
- **Fix**: corrective build or compile-only revision

## Unreleased - Planned 0.16.0.0

### Rhonda review follow-up

- Add a **Gamer Documents** menu to the Customer Card.
- Add a **Gamer Documents** menu to the Sales Orders list page.
- Make Pick Ticket UOM use the Item Card warehouse unit of measure.
- Make Warehouse Receiving Notice UOM use the Item Card warehouse unit of measure.
- Change sales-document customer recipient selection to the customer's primary contact.
- Remove Shipping Agent from the Pick Ticket.
- Clearly label Gamer-owned report actions.
- Update Purchase Order sent indicators only after the corresponding email is actually sent.
- Update Warehouse Receiving Notice sent indicator only after the email is actually sent.
- Require Released status before sending:
  - Sales Order Confirmation
  - Pick Ticket
  - Warehouse Purchase Order
  - Warehouse Receiving Notice
- Require Pending Prepayment status before sending a Prepayment Notice.
- Send Warehouse Purchase Orders from the ISR associated with the Purchase Header.
- Send Warehouse Receiving Notices to the Location Card email.
- Send Pick Tickets to the Location Card email.
- Add an option to omit selected document lines from generated documents.
- Remove terms-and-conditions language from the Pick Ticket.
- Remove terms-and-conditions language from the Warehouse Receiving Notice.

### Clarification required

- Exact field captions for the Purchase Order and Warehouse Receiving Notice sent indicators.
- Exact source field for the Purchase Header ISR.
- Exact Business Central field/value representing Pending Prepayment.
- Whether primary-contact routing applies only to customer-facing sales documents or literally every document type.
- Required behavior for omitting document lines.
- Desired wording for Gamer-owned action labels.

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
