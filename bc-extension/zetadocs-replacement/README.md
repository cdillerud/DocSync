# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, batch delivery, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, and Customer Statement.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, and Posted Purchase Credit Memo.

## Customer Statements

Customer Card actions create an individual statement for a selected date range, preview the branded PDF, open the native Business Central email editor, show Delivery Log history, show native sent-email history, and configure routing and sender setup.

The Customer List includes a batch statement action with customer filters and a selectable date range. The batch skips customers with no activity or balance, customers missing a recipient, and customers already sent for the exact period. It reports sent, failed, missing-recipient, no-activity, and already-sent totals.

Recipient selection is customer-specific Customer Statement routing rules, then the Customer Card primary-contact email, then the Customer Card E-Mail field, and finally generic Customer Statement routing rules when no customer-specific rule applies.

Statements use the dedicated GPI Customer Statement email scenario, which should be assigned to the Accounting mailbox. Individual statements support Send, Save As Draft, Discard, and draft reopening. Batch statements send directly through the assigned scenario.

Successfully sent statement PDFs automatically archive under the SharePoint Sales folder structure.

## Posted Sales Credit Memos

Posted Sales Credit Memo card and list pages include Gamer actions to preview, email, open delivery history, and open native sent-email history. Recipient selection uses customer-specific rules, primary-contact email, Customer Card E-Mail, and generic routing. Credit memos use the GPI Invoice Batch Accounting sender scenario and automatically archive under Sales.

## Posted Purchase Credit Memos

Posted Purchase Credit Memo card and list pages include Gamer actions to preview, email, open delivery history, open native sent-email history, and configure routing and sender setup. Recipient selection uses vendor-specific rules, document-contact email, Vendor Card E-Mail, and generic routing. Purchase credit memos use the GPI Purchase Credit Memo scenario and automatically archive under Purchase.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## SharePoint archival

When a Delivery Log entry is completed with email status Sent, the extension queues a one-time scheduled task. The task starts in a separate background session after the email transaction commits and performs the SharePoint upload.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.17.0.0
- Object range: 70510..70549
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

Assign GPI Customer Statement to the Accounting email account. Test individual preview, Send, Save As Draft, Discard, reopened draft, customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, generic routing, native sent history, Delivery Log history, and automatic Sales-folder archival.

Test the Customer List batch action with a customer selection and with filters. Confirm the batch skips no-activity, missing-recipient, and exact-period already-sent customers and reports accurate totals.

## Deferred

- Warehouse Receiving Notice sender policy is TBD.
- Line-exclusion behavior is pending business clarification.
