# Changelog

## 0.19.3.0

### Added
- Added a warehouse-facing Transfer Pick List for the transfer-from location.
- Added a warehouse-facing Transfer Receipt Notification for the transfer-to location.
- Added email and preview actions to the Transfer Order page.
- Added Delivery Log, native sent-email history, and routing-rule actions to Transfer Orders.
- Added a dedicated Transfer Line visibility field with Both Transfer Documents, Pick List Only, Receipt Notification Only, and Do Not Print options.
- Added dedicated branded RDLC layouts for both Transfer documents without modifying any Phase 1 report layouts.
- Added current-user sender account selection, recipient de-duplication, draft handling, Delivery Log tracking, native email relations, and SharePoint archival through the existing framework.
- Connected Transfer Header Delivery Log entries to the Warehouse archive folder.

### Recipient policy
- Transfer Pick List defaults to the transfer-from Location Card email and supports location-specific or generic Transfer Pick List routing rules.
- Transfer Receipt Notification defaults to the transfer-to Location Card email and supports location-specific or generic Transfer Receipt Notification routing rules.
- No sales-team CC recipients are added automatically. CC recipients are entered by the sender in the Email Editor or supplied by routing rules.
- Routing rules can add or replace default recipients.

### Safeguards
- Sending requires the Transfer Order to be Released; preview remains available before release.
- Transfer-from and transfer-to locations must both be populated and must be different.
- Pick-list and receipt-notification line visibility are controlled independently.
- Transfer documents contain no pricing or cost information.

### Pending validation
- Compile against Business Central 28.1 symbols.
- Validate the Transfer Order and Transfer Order Subform page-extension targets.
- Validate Transfer Header status and standard field names against the downloaded symbols.
- Validate both new RDLC layouts and Warehouse-folder archival in Sandbox_5_5_2026.

## 0.19.2.0

### Added
- Added a vendor-facing Purchase Return Order for Purchase Return Orders.
- Added a warehouse-facing Purchase Return Pick Ticket for items being shipped back to the supplier.
- Added email and preview actions to the Purchase Return Order page.
- Added Delivery Log, native sent-email history, and routing-rule actions to Purchase Return Orders.
- Added Document Visibility to Purchase Return Order lines.
- Added dedicated branded RDLC layouts for both Purchase Return documents without modifying any Phase 1 report layouts.
- Added current-user sender account selection, recipient de-duplication, draft handling, Delivery Log tracking, native email relations, and SharePoint archival through the existing framework.

### Recipient policy
- Purchase Return Order defaults to the document contact, vendor primary contact, or Vendor Card email and CCs the OSR and ISR when those fields can be identified, excluding the sender.
- Purchase Return Pick Ticket defaults to the return Location Card email and uses location-specific routing rules. CC recipients are entered by the sender in the Email Editor.
- Routing rules can add or replace default recipients.

### Safeguards
- Sending requires the Purchase Return Order to be Released; preview remains available before release.
- Purchase Return Order validates that nonzero financial lines are not hidden from the vendor-facing document.
- Warehouse and vendor line visibility follow the existing Document Visibility policy.
- The vendor document does not display pricing and asks the supplier for any additional authorization or shipping instructions.

### Pending validation
- Compile against Business Central 28.1 symbols.
- Validate the Purchase Return Order and Purchase Return Order Subform page-extension targets.
- Validate both new RDLC layouts in Sandbox_5_5_2026.

## 0.19.1.0

### Added
- Added a customer-facing Sales Return Authorization for Sales Return Orders.
- Added a Sales Return Warehouse Notification for the return location.
- Added email and preview actions to the Sales Return Order page.
- Added Delivery Log, native sent-email history, and routing-rule actions to Sales Return Orders.
- Added Document Visibility to Sales Return Order lines.
- Added dedicated branded RDLC layouts for both Sales Return documents without modifying any Phase 1 report layouts.
- Added current-user sender account selection, recipient de-duplication, draft handling, Delivery Log tracking, native email relations, and SharePoint archival through the existing framework.

### Recipient policy
- Sales Return Authorization defaults to the customer contact or Customer Card email and CCs the OSR and ISR when available, excluding the sender.
- Sales Return Warehouse Notification defaults to the return Location Card email and uses location-specific routing rules. CC recipients are entered by the sender in the Email Editor.
- Routing rules can add or replace default recipients.

### Safeguards
- Sending requires the Sales Return Order to be Released; preview remains available before release.
- Sales Return Authorization validates that nonzero financial lines are not hidden from the customer-facing document.
- Warehouse and customer line visibility follow the existing Document Visibility policy.
- The authorization states that final credit remains subject to receipt and inspection.

### Pending validation
- Compile against Business Central 28.1 symbols.
- Validate the Sales Return Order and Sales Return Order Subform page-extension targets.
- Validate both new RDLC layouts in Sandbox_5_5_2026.

## 0.19.0.0

### Added
- Started Phase 2 shared infrastructure on branch `feature/phase-2-documents`.
- Expanded the extension object range with 70550..70649.
- Added delivery document types for Sales Return Authorization, Sales Return Warehouse Notification, Purchase Return Order, Purchase Return Pick Ticket, Transfer Pick List, Transfer Receipt Notification, and Customer Open Order Status.
- Added a shared Phase 2 email management codeunit for current-user sender account resolution, recipient parsing, recipient de-duplication, sender exclusion, and recipient logging.
- Added Warehouse Folder to SharePoint Archive Setup for transfer and other warehouse-owned documents.
- Added a permission-set extension for the Phase 2 email management service.

### Pending validation
- Compile against Business Central 28.1 symbols.
- Confirm current-user email resolution against User Setup and configured Business Central Email Accounts.
- Connect Transfer Header archive entries to the Warehouse folder after compile validation.

## 0.18.0.1

### Fixed
- Moved GPI Line Visibility Mgt. from codeunit 70521 to 70549 to resolve compiler error AL0264.
- Updated the extension package version after the object-ID correction.

## 0.18.0.0

### Added
- Added Document Visibility to Sales Lines and Purchase Lines with options for All Documents, Customer/Vendor Documents Only, Warehouse Documents Only, and Do Not Print.
- Added Document Visibility fields to Sales Order, Blanket Sales Order, and Purchase Order lines.
- Added centralized line-visibility policy and report extensions for Sales Order Confirmations, Prepayment Notices, Pick Tickets, Blanket Sales Orders, Drop Ship Purchase Orders, Warehouse Purchase Orders, and Warehouse Receiving Notices.
- Preserved Document Visibility on posted sales invoice, posted sales credit memo, and posted purchase credit memo lines for traceability.

### Safeguards
- Customer/vendor-facing reports block generation when a nonzero financial line is configured to be hidden from the external document.
- Posted invoice and credit memo reports continue to show all posted financial lines in this release.

## 0.17.1.0

### Changed
- Finalized the Warehouse Receiving Notice sender policy to use the ISR identified on the Purchase Header.
- The workflow now requires a matching Business Central Email Account for the ISR and opens the native email editor with that account explicitly selected.
- The ISR sender is excluded from default CC recipients, and the Delivery Log records the actual sender account with policy `Purchase Header ISR`.

## 0.17.0.1

### Fixed
- Moved the Customer Statement table extension from object ID 70515 to 70517.
- Resolved compiler error AL0264 caused by the existing Purchase Header table extension already using ID 70515.

## 0.17.0.0

### Added
- Gamer-branded Customer Statement PDF generation with statement-period, opening-balance, transaction, ending-balance, and outstanding-balance detail.
- Customer Card actions for preview, email, delivery history, native sent-email history, routing rules, and sender setup.
- Customer List batch delivery with customer filters and a selectable date range.
- Customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, and generic statement routing fallback.
- Dedicated GPI Customer Statement email scenario for the Accounting mailbox.
- Native draft, discard, direct batch send, Delivery Log tracking, customer tracking, and automatic SharePoint archival under the Sales folder.

## 0.16.4.3

### Fixed
- Moved automatic SharePoint archival to a scheduled background task after the email transaction commits.

## Earlier versions

Added Gamer-owned sales and purchasing document email workflows, delivery logging, routing rules, native sent-email relationships, draft tracking, posted sales and purchase credit memos, and SharePoint archival.
