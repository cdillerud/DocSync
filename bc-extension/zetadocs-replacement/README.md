# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, batch delivery, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, Customer Statement, Sales Return Authorization, and Sales Return Warehouse Notification.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, Posted Purchase Credit Memo, Purchase Return Order, and Purchase Return Pick Ticket.

Warehouse transfers: Transfer Pick List and Transfer Receipt Notification.

## Phase 2 infrastructure

The shared Phase 2 email service resolves the initiating user's email address, requires a matching Business Central Email Account, removes duplicate recipients, and excludes the sender from default To, CC, and BCC recipients. A dedicated Warehouse archive folder setting is available for transfer and warehouse-owned documents.

The remaining planned Phase 2 document is Customer Open Order Status.

## Sales Return documents

Sales Return Orders include Gamer actions to email and preview two dedicated branded documents:

- Sales Return Authorization, sent to the customer to authorize the physical return
- Sales Return Warehouse Notification, sent to the return location to prepare for receipt and inspection

Sales Return Authorization recipient priority is customer-specific routing, Sales Return Order contact, customer primary contact, and Customer Card E-Mail. The OSR and ISR are added to CC when available unless already the sender or a To recipient. A routing rule using Replace can intentionally replace the defaults.

Sales Return Warehouse Notification defaults to the Location Card E-Mail value. Location-specific and generic warehouse routing rules may add or replace recipients. No sales-team CC recipients are added automatically; the sender may add CC recipients in the native Email Editor.

Both workflows use the initiating user's matching Business Central Email Account, support Send, Save As Draft, Discard, draft reopening, native sent-email history, Delivery Log tracking, and SharePoint archival under Sales. Sending requires a Released Sales Return Order, while preview remains available before release.

The customer authorization does not display pricing or promise a final credit value. It states that final credit is subject to receipt and inspection.

## Purchase Return documents

Purchase Return Orders include Gamer actions to email and preview two dedicated branded documents:

- Purchase Return Order, sent to the supplier with the return items and return reasons
- Purchase Return Pick Ticket, sent to the return location to pick and prepare the items for shipment back to the supplier

Purchase Return Order recipient priority is vendor-specific routing, Purchase Return Order contact, vendor primary contact, and Vendor Card E-Mail. The OSR and ISR are added to CC when those fields can be identified, unless already the sender or a To recipient. A routing rule using Replace can intentionally replace the defaults.

Purchase Return Pick Ticket defaults to the Location Card E-Mail value. Location-specific and generic routing rules may add or replace recipients. No sales-team CC recipients are added automatically; the sender may add CC recipients in the native Email Editor.

Both workflows use the initiating user's matching Business Central Email Account, support Send, Save As Draft, Discard, draft reopening, native sent-email history, Delivery Log tracking, and SharePoint archival under Purchase. Sending requires a Released Purchase Return Order, while preview remains available before release.

The vendor Purchase Return Order does not display pricing. It asks the supplier to provide any additional return authorization, labeling, or shipping instructions.

## Transfer documents

Transfer Orders include Gamer actions to email and preview two dedicated branded warehouse documents:

- Transfer Pick List, sent to the transfer-from location
- Transfer Receipt Notification, sent to the transfer-to location

The Transfer Pick List defaults to the transfer-from Location Card E-Mail. The Transfer Receipt Notification defaults to the transfer-to Location Card E-Mail. Each document supports location-specific and generic routing rules that can add or replace recipients.

No sales-team recipients are added automatically. The sender may add CC recipients in the native Email Editor or configure them through routing rules.

Transfer lines use a dedicated Document Visibility field with four values: Both Transfer Documents, Pick List Only, Receipt Notification Only, and Do Not Print.

Both workflows use the initiating user's matching Business Central Email Account, support Send, Save As Draft, Discard, draft reopening, native sent-email history, and Delivery Log tracking. Sending requires a Released Transfer Order, while preview remains available before release.

Sent transfer PDFs archive under the SharePoint Warehouse folder. Pick Lists use the transfer-from location as the archive party; Receipt Notifications use the transfer-to location.

## Document line visibility

Sales Order, Blanket Sales Order, Sales Return Order, Purchase Order, and Purchase Return Order lines include Document Visibility with four options: All Documents, Customer/Vendor Documents Only, Warehouse Documents Only, and Do Not Print.

Transfer Lines use a separate visibility field because outbound and inbound transfer documents need independent control.

Customer/vendor-facing reports stop with a clear error when a nonzero financial line is configured as Warehouse Documents Only or Do Not Print. Posted invoices and posted credit memos continue to show all posted lines. The visibility value is retained on posted lines for traceability.

Existing lines default to the option that prints on both applicable documents, so the feature does not require data migration.

## Customer Statements

Customer Card actions create an individual statement for a selected date range, preview the branded PDF, open the native Business Central email editor, show Delivery Log history, show native sent-email history, and configure routing and sender setup.

The Customer List includes a batch statement action with customer filters and a selectable date range. The batch skips customers with no activity or balance, customers missing a recipient, and customers already sent for the exact period. It reports sent, failed, missing-recipient, no-activity, and already-sent totals.

Statements use the dedicated GPI Customer Statement email scenario, which should be assigned to the Accounting mailbox. Successfully sent statement PDFs automatically archive under the SharePoint Sales folder structure.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## SharePoint archival

When a Delivery Log entry is completed with email status Sent, the extension queues a one-time scheduled task. The task starts in a separate background session after the email transaction commits and performs the SharePoint upload.

Sales documents archive under Sales, purchasing documents archive under Purchase, and Transfer Header documents archive under Warehouse.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.19.3.0
- Object ranges: 70510..70549 and 70550..70649
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

Use `PHASE2-SANDBOX-TESTS.md` for the complete infrastructure, return-document, transfer-document, routing, draft, visibility, and archive validation checklist.

## Remaining work

- Compile and validate version 0.19.3.0 in Sandbox_5_5_2026.
- Implement Customer Open Order Status in version 0.20.0.0.
- Complete the production-readiness review and sandbox regression checklist before any Production publication.
