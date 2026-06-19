# Phase 2 Sandbox Tests

Target environment: Sandbox_5_5_2026

## Build

- Download Business Central 28.1 symbols.
- Compile version 0.19.1.0.
- Confirm no duplicate object IDs in ranges 70510..70549 and 70550..70649.
- Confirm the GPI PH2 DOC EMAIL and GPI SALES RETURN DOCS permission-set extensions compile.
- Confirm both new RDLC layouts compile without schema or dataset errors.

## Sender resolution

- Confirm a user whose User ID is an email address resolves to the matching Business Central Email Account.
- Confirm a user whose User ID is not an email can resolve through the User Setup email field.
- Confirm a clear error appears when the user has no usable email address.
- Confirm a clear error appears when the email address has no matching Business Central Email Account.

## Recipient normalization

- Confirm comma-separated and semicolon-separated addresses are accepted.
- Confirm duplicate addresses are removed case-insensitively.
- Confirm To recipients take priority over duplicate CC and BCC recipients.
- Confirm CC recipients take priority over duplicate BCC recipients.
- Confirm the sender is removed from default To, CC, and BCC recipients.

## Sales Return Authorization

- Open a Sales Return Order and confirm the Gamer Documents actions appear.
- Preview while the return order is Open and confirm no sender-account validation occurs.
- Attempt to email while Open and confirm sending is blocked until Released.
- Release the return order and confirm the email editor opens from the initiating user's matching Email Account.
- Confirm recipient fallback order: customer-specific routing, return-order contact, customer primary contact, Customer Card email.
- Confirm OSR and ISR are added to CC when available.
- Confirm the sender and To recipients are not duplicated in CC.
- Confirm an Add routing rule supplements defaults.
- Confirm a Replace routing rule replaces defaults.
- Confirm the PDF displays return order details, items, quantities, units of measure, and return reason codes without pricing.
- Confirm the PDF states that final credit is subject to receipt and inspection.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, native sent-email history, and Sales-folder archival.

## Sales Return Warehouse Notification

- Preview while the return order is Open.
- Attempt to email while Open and confirm sending is blocked until Released.
- Confirm Location Code is required for sending.
- Confirm the Location Card email is the default To recipient.
- Confirm location-specific and generic routing rules can add or replace recipients.
- Confirm OSR and ISR are not added automatically.
- Add a manual CC recipient in the Email Editor and confirm it is recorded in the Delivery Log.
- Confirm warehouse quantities use the warehouse display policy.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, native sent-email history, and Sales-folder archival.

## Sales Return line visibility

Test all four values on Sales Return Order lines:

- All Documents appears on both Sales Return documents.
- Customer/Vendor Documents Only appears only on the Sales Return Authorization.
- Warehouse Documents Only appears only on the Warehouse Notification.
- Do Not Print appears on neither document.
- A nonzero line using Warehouse Documents Only or Do Not Print blocks the customer authorization.
- A zero-value instruction line may be hidden from the customer authorization.

## Archive setup

- Open GPI SharePoint Archive Setup.
- Confirm Warehouse Folder appears.
- Confirm new setup records default Warehouse Folder to Warehouse.
- For existing setup records, enter Warehouse manually if the field is blank.

## Regression

- Confirm Phase 1 document preview and email actions still open.
- Confirm Warehouse Receiving Notice continues to use Purchase Header ISR as sender.
- Confirm existing Sales and Purchase archive folders are unchanged.
- Confirm no existing Phase 1 RDLC layout was modified by the Sales Return sprint.

Do not publish to Production until the complete sandbox checklist passes and Production deployment is explicitly approved.
