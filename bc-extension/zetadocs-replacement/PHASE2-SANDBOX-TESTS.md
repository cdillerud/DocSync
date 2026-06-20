# Phase 2 Sandbox Tests

Target environment: Sandbox_5_5_2026

## Build

- Download Business Central 28.1 symbols.
- Compile version 0.20.0.0.
- Confirm no duplicate object IDs in ranges 70510..70549 and 70550..70649.
- Confirm the GPI PH2 DOC EMAIL, GPI SALES RETURN DOCS, GPI PURCHASE RETURN DOCS, GPI TRANSFER DOCS, and GPI CUSTOMER OPEN ORDERS permission-set extensions compile.
- Confirm all seven Phase 2 RDLC layouts compile without schema or dataset errors.
- Confirm the explicit current-user Email.Send overload compiles.
- Confirm the Sales Line delivery-date fields, Purchase Line receipt-date fields, and Customer, Customer List, and Delivery Log page-extension targets compile.

## Shared sender and routing

- Confirm a user whose User ID is an email address resolves to the matching Business Central Email Account.
- Confirm a user whose User ID is not an email can resolve through the User Setup email field.
- Confirm clear errors when the user has no usable email address or matching Business Central Email Account.
- Confirm comma-separated and semicolon-separated routing addresses are accepted.
- Confirm duplicate addresses are removed case-insensitively.
- Confirm To recipients take priority over duplicate CC and BCC recipients.
- Confirm the sender is removed from default To, CC, and BCC recipients.

## Return and transfer regression

- Confirm Sales Return, Purchase Return, and Transfer Gamer Documents actions still appear and open.
- Confirm return and transfer preview, Released-status enforcement, routing, line visibility, draft handling, Delivery Log tracking, native sent history, and Sales, Purchase, and Warehouse archival still work.
- Confirm no existing Phase 1 RDLC layout was modified by the Phase 2 sprints.

## Customer Open Order Status report

- Open a Customer Card with outstanding Sales Order item lines and confirm the Gamer Open Orders actions appear.
- Preview the report and confirm no sender-account validation occurs.
- Confirm only Sales Order item lines with Outstanding Quantity greater than zero appear.
- Confirm fully shipped lines do not appear.
- Confirm partially shipped lines appear with the remaining quantity and Partially Shipped status.
- Confirm both warehouse and drop-ship lines appear in one customer report.
- Confirm Supply displays Warehouse or Drop Ship correctly.
- Confirm the linked Purchase Order number appears without vendor name, vendor contact, cost, margin, or internal notes.
- Confirm the expected date uses the linked Purchase Line date when available and falls back to Sales Line delivery dates.
- Confirm past expected dates display Overdue.
- Confirm other statuses display as Awaiting Supplier, On Purchase Order, Scheduled, or Open when appropriate.
- Confirm the report date uses Work Date.
- Confirm expected dates are labeled as estimates that may change.
- Confirm lines hidden from the customer-facing document follow the existing line-visibility safeguard.
- Confirm the landscape PDF renders without clipping or extra blank pages.

## Individual Open Order email

- Confirm recipient fallback order: customer-specific routing, primary contact, Customer Card email, then generic routing.
- Confirm Add and Replace routing-rule behavior.
- Confirm OSR and ISR are added to CC when available.
- Confirm the sender and To recipients are not duplicated in CC.
- Confirm the native Email Editor opens from the initiating user's matching Email Account.
- Confirm Send, Save As Draft, Discard, and draft reopening.
- Confirm the native sent-email relation appears for the customer.
- Confirm the Delivery Log records the as-of date, included order count, included line count, and included Sales Order numbers.
- Confirm sent PDFs archive under the Sales folder using the customer as the archive party.

## Open Order batch

- Select multiple customers in Customer List and run Gamer Send Open Order Status Batch.
- Repeat with a Customer List filter rather than a manual selection.
- Confirm preflight counts report ready, missing-recipient, and no-open-line customers.
- Confirm the confirmation message states that repeat sends are allowed.
- Confirm each ready customer receives one report.
- Confirm customers with no outstanding item lines are skipped.
- Confirm customers with no resolved recipient are skipped and counted.
- Confirm a rendering or send failure creates a Failed Delivery Log entry and does not stop the remaining customers.
- Confirm the completion message reports sent, failed, missing-recipient, and no-open-line totals.
- Send the same customer again and confirm a new Delivery Log entry is created rather than the customer being skipped.
- Confirm each successful batch PDF archives under Sales.

## Delivery Log display

- Open a Customer Open Order Status Delivery Log entry.
- Confirm Open Order As Of Date, Open Order Count, Open Order Line Count, and Included Order Nos. are visible and read-only.
- Confirm those fields are hidden for unrelated document types.

## Production gate

- Confirm Phase 1 document preview and email actions still open.
- Confirm Warehouse Receiving Notice continues to use Purchase Header ISR as sender.
- Confirm Sales, Purchase, and Warehouse archive folders remain correctly separated.

Do not publish to Production until the complete sandbox checklist passes and Production deployment is explicitly approved.
