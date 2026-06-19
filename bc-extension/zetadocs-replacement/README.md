# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, batch delivery, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, and Customer Statement.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, and Posted Purchase Credit Memo.

## Phase 2 infrastructure

Version 0.19.0.0 starts the shared infrastructure for these planned documents:

- Sales Return Authorization
- Sales Return Warehouse Notification
- Purchase Return Order
- Purchase Return Pick Ticket
- Transfer Pick List
- Transfer Receipt Notification
- Customer Open Order Status

The Phase 2 email service resolves the initiating user's email address, requires a matching Business Central Email Account, removes duplicate recipients, and excludes the sender from default To, CC, and BCC recipients. A dedicated Warehouse archive folder setting is available for transfer and warehouse-owned documents.

The Phase 2 document reports, page actions, email workflows, and Delivery Log creation are not included in the infrastructure release. They will be added in document-specific releases after this shared layer compiles and is validated in the sandbox.

## Document line visibility

Sales Order, Blanket Sales Order, and Purchase Order lines include Document Visibility with four options: All Documents, Customer/Vendor Documents Only, Warehouse Documents Only, and Do Not Print.

Sales Order Confirmations, Prepayment Notices, Blanket Sales Orders, Drop Ship Purchase Orders, and Warehouse Purchase Orders are customer/vendor-facing documents. Pick Tickets and Warehouse Receiving Notices are warehouse documents.

Customer/vendor-facing reports stop with a clear error when a nonzero financial line is configured as Warehouse Documents Only or Do Not Print. This prevents a document total from including financial detail that is hidden from the recipient. Posted invoices and posted credit memos continue to show all posted lines in this release. The visibility value is retained on posted lines for traceability.

Existing lines default to All Documents, so the feature does not require data migration.

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

## Warehouse Receiving Notices

Warehouse Receiving Notices are addressed to the Location Card E-Mail value, with Warehouse Receiving Notice routing rules available to add or replace recipients. The Purchase Header purchaser and ISR are added to CC when applicable.

The sender is the ISR identified on the Purchase Header. That ISR must have an email address on the Salesperson/Purchaser Card and a matching Business Central Email Account. The native email editor opens with that account explicitly selected, the sender is excluded from CC, and the Delivery Log records the sender policy as `Purchase Header ISR`.

## Saved drafts

The GPI Document Delivery Log includes Open Draft Email and Email Outbox. Reopened drafts preserve the native Business Central message, sender account, recipients, body, and attachment.

## SharePoint archival

When a Delivery Log entry is completed with email status Sent, the extension queues a one-time scheduled task. The task starts in a separate background session after the email transaction commits and performs the SharePoint upload.

## Extension details

- Name: GPI Sales Document Email
- Publisher: Gamer Packaging
- Version: 0.19.0.0
- Object ranges: 70510..70549 and 70550..70649
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

For Phase 2 infrastructure, confirm the extension compiles, the Warehouse Folder field appears in SharePoint Archive Setup, and GPI Phase 2 Email Mgt. can resolve the initiating user's configured Business Central Email Account.

Test all four Document Visibility values on Sales Order, Blanket Sales Order, and Purchase Order lines. Confirm each line appears only in its intended document category.

Confirm a nonzero line configured as Warehouse Documents Only or Do Not Print blocks customer/vendor document preview and email with the line number, amount, and visibility in the error. Confirm zero-value instruction lines can use those settings.

Post representative sales invoices, sales credit memos, and purchase credit memos. Confirm the visibility value transfers to posted lines while all posted report lines remain visible.

For Warehouse Receiving Notices, confirm that preview remains available without sender validation, sending fails clearly when the Purchase Header ISR is missing or lacks a registered email account, the editor opens from the ISR account when configured, the ISR is not duplicated in CC, saved drafts reopen with the same sender, and sent documents archive under Purchase.

Assign GPI Customer Statement to the Accounting email account. Test individual preview, Send, Save As Draft, Discard, reopened draft, customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, generic routing, native sent history, Delivery Log history, and automatic Sales-folder archival.

Test the Customer List batch action with a customer selection and with filters. Confirm the batch skips no-activity, missing-recipient, and exact-period already-sent customers and reports accurate totals.

## Remaining work

- Compile and validate Phase 2 shared infrastructure in Sandbox_5_5_2026.
- Connect Transfer Header archive entries to the Warehouse folder.
- Implement the Phase 2 document-specific reports, actions, routing, Delivery Log entries, and archive filenames.
- Complete the production-readiness review and sandbox regression checklist before any Production publication.
