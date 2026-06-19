# Changelog

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
- Customer List batch delivery with customer filters and a selectable statement date range.
- Customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, and generic statement routing fallback.
- Dedicated GPI Customer Statement email scenario for the Accounting mailbox.
- Native draft, discard, direct batch send, Delivery Log tracking, customer tracking, and automatic SharePoint archival under the Sales folder.

## 0.16.4.3

### Fixed
- Moved automatic SharePoint archival to a scheduled background task after the email transaction commits.

## Earlier versions

Added Gamer-owned sales and purchasing document email workflows, delivery logging, routing rules, native sent-email relationships, draft tracking, posted sales and purchase credit memos, and SharePoint archival.
