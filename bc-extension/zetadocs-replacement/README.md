# GPI Sales Document Email

Business Central replacement for selected Zetadocs document generation, email, delivery logging, native draft and sent history, batch delivery, and SharePoint archival workflows.

## Supported documents

Sales: Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, Customer Statement, Sales Return Authorization, and Sales Return Warehouse Notification.

Accounts receivable: Posted Sales Invoice, filtered invoice queue, and Posted Sales Credit Memo.

Purchasing and accounts payable: Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, Posted Purchase Credit Memo, Purchase Return Order, and Purchase Return Pick Ticket.

## Phase 2 infrastructure

The shared Phase 2 email service resolves the initiating user's email address, requires a matching Business Central Email Account, removes duplicate recipients, and excludes the sender from default To, CC, and BCC recipients. A dedicated Warehouse archive folder setting is available for transfer and warehouse-owned documents.

Planned later Phase 2 documents are Transfer Pick List, Transfer Receipt Notification, and Customer Open Order Status.

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

## Document line visibility

Sales Order, Blanket Sales Order, Sales Return Order, Purchase Order, and Purchase Return Order lines include Document Visibility with four options: All Documents, Customer/Vendor Documents Only, Warehouse Documents Only, and Do Not Print.

Sales Order Confirmations, Prepayment Notices, Blanket Sales Orders, Drop Ship Purchase Orders, Warehouse Purchase Orders, Sales Return Authorizations, and Purchase Return Orders are customer/vendor-facing documents. Pick Tickets, Warehouse Receiving Notices, Sales Return Warehouse Notifications, and Purchase Return Pick Tickets are warehouse documents.

Customer/vendor-facing reports stop with a clear error when a nonzero financial line is configured as Warehouse Documents Only or Do Not Print. This prevents financial return lines from being silently omitted from external documents. Posted invoices and posted credit memos continue to show all posted lines. The visibility value is retained on posted lines for traceability.

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
- Version: 0.19.2.0
- Object ranges: 70510..70549 and 70550..70649
- Permission set: GPI DOC EMAIL
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation

For Sales Return Authorization, test customer-specific routing, contact and Customer Card fallback, OSR and ISR CC, sender exclusion, routing-rule Replace behavior, preview, Send, Save As Draft, Discard, draft reopening, Delivery Log history, native sent history, line visibility, and Sales-folder archival.

For Sales Return Warehouse Notification, test Location Card fallback, location-specific and generic routing, manual CC entry, preview, Send, Save As Draft, Discard, draft reopening, Delivery Log history, native sent history, warehouse line visibility, and Sales-folder archival.

For Purchase Return Order, test vendor-specific routing, document-contact and Vendor Card fallback, OSR and ISR CC when available, sender exclusion, routing-rule Replace behavior, preview, Send, Save As Draft, Discard, draft reopening, Delivery Log history, native sent history, line visibility, and Purchase-folder archival.

For Purchase Return Pick Ticket, test Location Card fallback, location-specific and generic routing, manual CC entry, preview, Send, Save As Draft, Discard, draft reopening, Delivery Log history, native sent history, warehouse line visibility, warehouse unit-of-measure conversion, and Purchase-folder archival.

Confirm all return send actions block an Open return order while preview remains available. Confirm both external return documents block a nonzero line configured as Warehouse Documents Only or Do Not Print.

Test all four Document Visibility values on Sales Order, Blanket Sales Order, Sales Return Order, Purchase Order, and Purchase Return Order lines. Confirm each line appears only in its intended document category.

Post representative sales invoices, sales credit memos, and purchase credit memos. Confirm the visibility value transfers to posted lines while all posted report lines remain visible.

For Warehouse Receiving Notices, confirm that preview remains available without sender validation, sending fails clearly when the Purchase Header ISR is missing or lacks a registered email account, the editor opens from the ISR account when configured, the ISR is not duplicated in CC, saved drafts reopen with the same sender, and sent documents archive under Purchase.

Assign GPI Customer Statement to the Accounting email account. Test individual preview, Send, Save As Draft, Discard, reopened draft, customer-specific routing, primary-contact fallback, Customer Card E-Mail fallback, generic routing, native sent history, Delivery Log history, and automatic Sales-folder archival.

## Remaining work

- Compile and validate version 0.19.2.0 in Sandbox_5_5_2026.
- Connect Transfer Header archive entries to the Warehouse folder.
- Implement Transfer documents and Customer Open Order Status.
- Complete the production-readiness review and sandbox regression checklist before any Production publication.
