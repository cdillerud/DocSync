# Phase 2 Sandbox Tests

Target environment: Sandbox_5_5_2026

## Build

- Download Business Central 28.1 symbols.
- Compile version 0.19.3.0.
- Confirm no duplicate object IDs in ranges 70510..70549 and 70550..70649.
- Confirm the GPI PH2 DOC EMAIL, GPI SALES RETURN DOCS, GPI PURCHASE RETURN DOCS, and GPI TRANSFER DOCS permission-set extensions compile.
- Confirm all six Phase 2 RDLC layouts compile without schema or dataset errors.

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
- Confirm Add and Replace routing-rule behavior.
- Confirm the PDF contains no pricing and states that final credit is subject to receipt and inspection.
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

- All Documents appears on both Sales Return documents.
- Customer/Vendor Documents Only appears only on the Sales Return Authorization.
- Warehouse Documents Only appears only on the Warehouse Notification.
- Do Not Print appears on neither document.
- A nonzero line using Warehouse Documents Only or Do Not Print blocks the customer authorization.

## Purchase Return Order

- Open a Purchase Return Order and confirm the Gamer Documents actions appear.
- Preview while the return order is Open and confirm no sender-account validation occurs.
- Attempt to email while Open and confirm sending is blocked until Released.
- Confirm recipient fallback order: vendor-specific routing, document contact, vendor primary contact, Vendor Card email.
- Confirm OSR and ISR are added to CC when identifiable on the Purchase Header.
- Confirm Add and Replace routing-rule behavior.
- Confirm the PDF contains no pricing.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, native sent-email history, and Purchase-folder archival.

## Purchase Return Pick Ticket

- Preview while the return order is Open.
- Attempt to email while Open and confirm sending is blocked until Released.
- Confirm Location Code is required for sending.
- Confirm the Location Card email is the default To recipient.
- Confirm location-specific and generic routing rules can add or replace recipients.
- Confirm OSR and ISR are not added automatically.
- Confirm warehouse quantities and units of measure use the warehouse display policy.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, native sent-email history, and Purchase-folder archival.

## Purchase Return line visibility

- All Documents appears on both Purchase Return documents.
- Customer/Vendor Documents Only appears only on the vendor Purchase Return Order.
- Warehouse Documents Only appears only on the Purchase Return Pick Ticket.
- Do Not Print appears on neither document.
- A nonzero line using Warehouse Documents Only or Do Not Print blocks the vendor Purchase Return Order.

## Transfer Pick List

- Open a Transfer Order and confirm the Gamer Documents actions appear.
- Confirm the Transfer Order and Transfer Order Subform extension targets compile and open.
- Preview while the Transfer Order is Open and confirm no sender-account validation occurs.
- Attempt to email while Open and confirm sending is blocked until Released.
- Confirm transfer-from and transfer-to locations are required and cannot be the same.
- Confirm the transfer-from Location Card email is the default To recipient.
- Confirm location-specific and generic Transfer Pick List routing rules can add or replace recipients.
- Confirm no sales-team CC recipients are added automatically.
- Add a manual CC recipient and confirm it is recorded in the Delivery Log.
- Confirm the PDF shows transfer-from and transfer-to locations, shipment date, in-transit code, items, quantities, and units of measure.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, and native sent-email history.
- Confirm sent PDFs archive under the Warehouse folder using the transfer-from location as the archive party.

## Transfer Receipt Notification

- Preview while the Transfer Order is Open and confirm no sender-account validation occurs.
- Attempt to email while Open and confirm sending is blocked until Released.
- Confirm the transfer-to Location Card email is the default To recipient.
- Confirm location-specific and generic Transfer Receipt Notification routing rules can add or replace recipients.
- Confirm no sales-team CC recipients are added automatically.
- Add a manual CC recipient and confirm it is recorded in the Delivery Log.
- Confirm the PDF shows transfer-from and transfer-to locations, expected receipt date, shipment date, items, quantities, and units of measure.
- Confirm Send, Save As Draft, Discard, draft reopening, Delivery Log, and native sent-email history.
- Confirm sent PDFs archive under the Warehouse folder using the transfer-to location as the archive party.

## Transfer line visibility

- Both Transfer Documents appears on both transfer documents.
- Pick List Only appears only on the Transfer Pick List.
- Receipt Notification Only appears only on the Transfer Receipt Notification.
- Do Not Print appears on neither document.

## Archive setup

- Open GPI SharePoint Archive Setup.
- Confirm Warehouse Folder appears.
- Confirm new setup records default Warehouse Folder to Warehouse.
- For existing setup records, enter Warehouse manually if the field is blank.
- Confirm Sales and Purchase documents continue using their existing folders.

## Regression

- Confirm Phase 1 document preview and email actions still open.
- Confirm Warehouse Receiving Notice continues to use Purchase Header ISR as sender.
- Confirm no existing Phase 1 RDLC layout was modified by the Phase 2 sprints.

Do not publish to Production until the complete sandbox checklist passes and Production deployment is explicitly approved.
