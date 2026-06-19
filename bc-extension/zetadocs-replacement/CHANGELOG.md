# Changelog

## 0.16.3.2

### Fixed
- Moved the Credit Memo permission set extension to object ID `70549`.
- Resolved compiler error `AL0264` caused by the Purchase Order permission set extension already using ID `70513`.

## 0.16.3.1

### Fixed
- Changed the Credit Memo permission set extension object ID from `70512` to `70513`.
- Resolved compiler error `AL0264` caused by the existing Blanket Sales Order permission set extension already using ID `70512`.

## 0.16.3.0

### Added
- Gamer-branded Posted Sales Credit Memo report and PDF layout.
- Preview and email actions on Posted Sales Credit Memo card and list.
- Credit Memo routing type with customer-specific rules and Customer primary-contact fallback.
- Credit memo delivery tracking, Delivery Log navigation, native sent-email history, draft reopening, and SharePoint archival.

### Changed
- Posted Sales Credit Memos use the existing GPI Invoice Batch Accounting sender scenario.
- Reopened drafts update the existing Delivery Log entry after send, re-save, or discard.

## 0.16.2.1

### Fixed
- Replaced internal Email Outbox field access with Microsoft-supported public APIs.

## 0.16.2.0

### Added
- Open Draft Email and Email Outbox actions on the GPI Document Delivery Log.

## 0.16.1.1

### Fixed
- Corrected Purchase Header sent-indicator persistence and reopen behavior.

## 0.16.1.0

### Added
- Synchronized PO Sent and Whse. Receiving Notice Sent after successful sends.

## 0.16.0.0

### Added
- Shared document policy for status, routing, ISR sender, and warehouse UOM conversion.

## Earlier versions

Added Gamer-owned sales and purchasing document email workflows, delivery logging, routing rules, native sent-email relationships, draft tracking, and SharePoint archival.
