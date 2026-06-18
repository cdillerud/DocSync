# Changelog

All notable changes to **GPI Sales Document Email** are recorded here.

The project follows four-part Business Central app versioning:

`major.minor.feature.fix`

- **Major**: production-breaking redesign or replacement
- **Minor**: major workflow milestone
- **Feature**: grouped functional enhancement
- **Fix**: corrective build or compile-only revision

## 0.16.0.0

### Added

- Added a **Gamer Documents > Gamer Document Routing Rules** action to the Vendor Card, filtered to the current vendor.
- Added shared document-policy management for send-status validation, recipient resolution, ISR sender-account resolution, and warehouse UOM conversion.
- Added execute permissions for the supported sales, purchasing, warehouse, and shared-policy objects to the `GPI DOC EMAIL` permission set.

### Changed

- Customer Card **Gamer Documents** now contains only **Gamer Document Routing Rules**, filtered to the current customer.
- Removed Customer Card Delivery Log and Sent Email History actions. Documents are not sent from Customer or Vendor Cards.
- Customer-specific routing rules are evaluated before standard recipients for:
  - Sales Order Confirmation
  - Blanket Sales Order
  - Prepayment Notice
  - Pick Ticket
  - Posted Sales Invoice
- When no customer-specific rule supplies a recipient:
  - Sales Order Confirmation uses the contact selected on the Sales Order.
  - Blanket Sales Order uses the contact selected on the Blanket Sales Order.
  - Prepayment Notice uses the contact selected on the Sales Order.
  - Pick Ticket uses the Location Card email.
  - Posted Sales Invoice uses the Customer Card primary contact email.
- Sending is blocked unless the source document is **Released** for:
  - Sales Order Confirmation
  - Pick Ticket
  - Warehouse Purchase Order
  - Warehouse Receiving Notice
- Preview remains available while those documents are Open.
- Prepayment Notice sending is blocked unless the installed prepayment-status field resolves to **Pending Prepayment**. Preview remains available in other statuses.
- Pick Ticket and Warehouse Receiving Notice now display the Item Card **Whse Unit of Measure Code** and calculate quantity from base quantity divided by the matching Item Unit of Measure **Qty. per Unit of Measure**.
- Warehouse Purchase Order sender selection now resolves the ISR on the Purchase Header, reads the ISR email from Salespeople/Purchasers, and requires a registered Business Central Email Account with the same address.
- Warehouse Purchase Order delivery logs now record sender policy **Purchase Header ISR** and the selected ISR Email Account.

### Not implemented in this version

- Existing Purchase Order and Warehouse Receiving Notice sent-indicator updates are intentionally unchanged. Their exact field IDs and captions are not present in this repository or its source symbols. The fields must be identified from the Gamer sandbox metadata before implementing send-only toggles and reopen reset behavior.
- Warehouse Receiving Notice sender remains unchanged because the sender rule is still TBD.
- Line-exclusion behavior remains unimplemented pending business clarification.
- Posted Sales Credit Memo email workflow is not currently present in this extension; this version changes primary-contact routing for the existing Posted Sales Invoice workflow only.

## 0.15.1.2

### Fixed

- Restored equal heights for the two Pick Ticket detail boxes after removing Shipping Agent.
- Corrected the uneven red-border alignment above the line table.

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
