# Changelog

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
