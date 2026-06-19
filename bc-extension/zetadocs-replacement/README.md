# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, and Blanket Sales Order.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing: Drop Ship Purchase Order, Warehouse Purchase Order, and Warehouse Receiving Notice.

## Posted Sales Credit Memos

Posted Sales Credit Memo card and list pages include Gamer actions to preview, email, open delivery history, and open native sent-email history.

Recipient selection is customer-specific Credit Memo routing rules, then the Customer Card primary-contact email, then the Customer Card E-Mail field, and finally generic Credit Memo routing rules when no customer-specific rule applies.

Credit memos use the existing GPI Invoice Batch email scenario and Accounting mailbox. They support Send, Save As Draft, Discard, reopening from the GPI Document Delivery Log, and updating the same log entry when the reopened draft is completed.

Successfully sent credit memo PDFs use the existing GPI SharePoint archive process and Sales folder structure.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.16.3.3
- Object range: 70510..70549
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

Validate PDF, routing, Accounting sender, Delivery Log, draft reopening, native Sent Email History, and SharePoint archive URL. For credit memos, test customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, generic routing, Save As Draft, Discard, Send, and Missing Recipient behavior.

## Deferred

- Warehouse Receiving Notice sender policy is TBD.
- Line-exclusion behavior is pending business clarification.
