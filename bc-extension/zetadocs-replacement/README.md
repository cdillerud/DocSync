# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, batch delivery, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, Customer Statement, Customer Open Order Status, Sales Return Authorization, and Sales Return Warehouse Notification.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, Posted Purchase Credit Memo, Purchase Return Order, and Purchase Return Pick Ticket.

Warehouse transfers: Transfer Pick List and Transfer Receipt Notification.

## Phase 2 infrastructure

The shared Phase 2 email service resolves the initiating user's email address, requires a matching Business Central Email Account, removes duplicate recipients, and excludes the sender from default To, CC, and BCC recipients. A dedicated Warehouse archive folder setting is available for transfer and warehouse-owned documents.

## Customer Open Order Status

Customer Cards include actions to preview and email one current Open Order Status report. Customer List includes a batch action for selected or filtered customers.

The report combines live warehouse and drop-ship Sales Order item lines with Outstanding Quantity greater than zero. It includes Sales Order number, customer PO, order date, item, description, outstanding quantity, unit of measure, supply type, linked Purchase Order number, expected date, and customer-facing status.

The report does not expose vendor identity, vendor contacts, vendor cost, margin, internal purchasing notes, or escalation notes. Expected dates are identified as estimates that may change.

Recipient priority is customer-specific routing, primary contact, Customer Card E-Mail, and generic routing. OSR and ISR are added to CC when available, excluding the sender and existing To recipients.

Individual delivery uses the initiating user's matching Business Central Email Account and supports the native Email Editor, Send, Save As Draft, Discard, draft reopening, Delivery Log tracking, native sent-email history, and Sales-folder archival.

Batch delivery performs a preflight, sends directly from the initiating user's matching Email Account, skips customers with no outstanding item lines or no resolved recipient, allows repeat sends, and reports sent, failed, missing-recipient, and no-open-line totals.

Delivery Log entries record the report as-of date, included order count, included line count, and Sales Order numbers.

## Return documents

Sales Return Orders include a customer-facing Sales Return Authorization and a warehouse-facing Sales Return Warehouse Notification. Purchase Return Orders include a vendor-facing Purchase Return Order and a warehouse-facing Purchase Return Pick Ticket.

External return documents use customer or vendor routing and contact fallback, add OSR and ISR to CC when available, exclude the sender, display no pricing, and require Released status for sending. Warehouse return documents use location routing, manual CC, warehouse quantity display, and warehouse-only line visibility.

All return workflows support preview, Send, Save As Draft, Discard, draft reopening, native sent-email history, Delivery Log tracking, and SharePoint archival under Sales or Purchase.

## Transfer documents

Transfer Orders include a Transfer Pick List for the transfer-from location and a Transfer Receipt Notification for the transfer-to location.

Each document defaults to the applicable Location Card E-Mail and supports location-specific or generic routing rules. No sales-team recipients are added automatically.

Transfer lines use Both Transfer Documents, Pick List Only, Receipt Notification Only, and Do Not Print. Sent transfer PDFs archive under Warehouse using the applicable location as the archive party.

## Document line visibility

Sales Order, Blanket Sales Order, Sales Return Order, Purchase Order, and Purchase Return Order lines use All Documents, Customer/Vendor Documents Only, Warehouse Documents Only, and Do Not Print.

Transfer Lines use a separate visibility field because outbound and inbound transfer documents need independent control.

Customer/vendor-facing reports stop with a clear error when a nonzero financial line is hidden from the external document. Existing lines default to the option that prints on both applicable documents.

## Customer Statements

Customer Card actions create an individual statement for a selected date range. Customer List includes batch statement delivery. Statements use the dedicated GPI Customer Statement email scenario and archive under Sales.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## SharePoint archival

Sent Sales documents archive under Sales, purchasing documents archive under Purchase, and Transfer Header documents archive under Warehouse through a scheduled background task after the email transaction commits.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.20.0.0
- Object ranges: 70510..70549 and 70550..70649
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

Use `PHASE2-SANDBOX-TESTS.md` for the complete infrastructure, return, transfer, Customer Open Order, routing, draft, visibility, archive, regression, and production-gate checklist.

## Remaining work

- Compile and validate version 0.20.0.0 in Sandbox_5_5_2026.
- Correct any Business Central 28.1 symbol-specific compiler issues.
- Complete the production-readiness review and sandbox regression checklist before any Production publication.
