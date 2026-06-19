# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, and Blanket Sales Order.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, and Posted Purchase Credit Memo.

## Posted Sales Credit Memos

Posted Sales Credit Memo card and list pages include Gamer actions to preview, email, open delivery history, and open native sent-email history.

Recipient selection is customer-specific Credit Memo routing rules, then the Customer Card primary-contact email, then the Customer Card E-Mail field, and finally generic Credit Memo routing rules when no customer-specific rule applies.

Credit memos use the existing GPI Invoice Batch email scenario and Accounting mailbox. They support Send, Save As Draft, Discard, reopening from the GPI Document Delivery Log, and updating the same log entry when the reopened draft is completed.

Successfully sent credit memo PDFs use the existing GPI SharePoint archive process and Sales folder structure.

## Posted Purchase Credit Memos

Posted Purchase Credit Memo card and list pages include Gamer actions to preview, email, open delivery history, open native sent-email history, and configure routing and sender setup.

Recipient selection is vendor-specific Purchase Credit Memo routing rules, then the document Buy-from Contact email, then the Vendor Card E-Mail field, and finally generic Purchase Credit Memo routing rules when no vendor-specific rule applies.

Purchase credit memos use the GPI Purchase Credit Memo email scenario, which should be assigned to the Accounts Payable mailbox. They support Send, Save As Draft, Discard, reopening from the GPI Document Delivery Log, and updating the same log entry when the reopened draft is completed.

Successfully sent purchase credit memo PDFs automatically archive through the GPI SharePoint archive process under the Purchase folder structure.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## SharePoint archival

When a Delivery Log entry is completed with email status Sent, the extension queues a one-time scheduled task. The task starts in a separate background session after the email transaction commits and performs the SharePoint upload. Archive status changes made by the background task do not queue duplicate tasks.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.16.4.3
- Object range: 70510..70549
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

Validate PDF, routing, sender selection, Delivery Log, draft reopening, native Sent Email History, and SharePoint archive URL.

For sales credit memos, test customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, generic routing, Save As Draft, Discard, Send, Missing Recipient behavior, and automatic Sales-folder archival.

For purchase credit memos, assign GPI Purchase Credit Memo to the Accounts Payable email account, then test vendor-specific routing, document-contact fallback, Vendor Card E-Mail fallback, generic routing, Save As Draft, Discard, Send, Missing Recipient behavior, and automatic Purchase-folder archival.

## Deferred

- Warehouse Receiving Notice sender policy is TBD.
- Line-exclusion behavior is pending business clarification.
