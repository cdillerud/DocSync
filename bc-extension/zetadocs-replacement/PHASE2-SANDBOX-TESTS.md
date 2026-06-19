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
- Confirm clear errors when the user has no usable email address or matching Business Central Email Account.

## Recipient normalization

- Confirm comma-separated and semicolon-separated addresses are accepted.
- Confirm duplicate addresses are removed case-insensitively.
- Confirm To recipients take priority over duplicate CC and BCC recipients.
- Confirm the sender is removed from default To, CC, and BCC recipients.

## Return documents

- Confirm Sales Return and Purchase Return Gamer Documents actions appear on their card pages.
- Confirm preview works while Open and send is blocked until Released.
- Confirm customer/vendor/contact fallback, routing-rule Add and Replace behavior, sender exclusion, OSR and ISR CC policy, native draft and sent history, Delivery Log tracking, and Sales/Purchase archival.
- Confirm warehouse return documents use Location Card routing, manual CC, warehouse quantity display, and warehouse-only visibility.
- Confirm external return documents contain no pricing and block nonzero lines hidden from the customer/vendor document.

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

## Archive and regression

- Confirm Warehouse Folder appears in GPI SharePoint Archive Setup and defaults to Warehouse for new setup records.
- Confirm Sales and Purchase documents continue using their existing folders.
- Confirm Phase 1 document preview and email actions still open.
- Confirm Warehouse Receiving Notice continues to use Purchase Header ISR as sender.
- Confirm no existing Phase 1 RDLC layout was modified by the Phase 2 sprints.

Do not publish to Production until the complete sandbox checklist passes and Production deployment is explicitly approved.
