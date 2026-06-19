# Phase 2 Documents

## Shared policy

- Sender: the Business Central user who initiates the email action.
- Sender requirement: the initiating user must resolve to a matching Business Central Email Account.
- Sender exclusion: the sender is removed from default To, CC, and BCC recipients.
- Email behavior: open the native Business Central Email Editor. Do not send automatically.
- Tracking: use the existing Delivery Log, native email relation, draft reopening, sent-email history, and SharePoint archival framework.
- Validation target: Sandbox_5_5_2026.

## Planned documents

### Sales Return Authorization

- Source: Sales Return Order.
- Purpose: authorize a customer return.
- Default To: customer-specific routing, return-order contact, then Customer Card email.
- Default CC: OSR and ISR, excluding the sender.
- Customer-facing document.

### Sales Return Warehouse Notification

- Source: Sales Return Order.
- Purpose: notify the receiving warehouse of an incoming return.
- Default To: location-specific routing, then Location Card email.
- Default CC: entered by the sender in the Email Editor.
- Warehouse document.

### Purchase Return Order

- Source: Purchase Return Order.
- Purpose: notify a supplier of items being returned and request or record return authorization.
- Default To: vendor-specific routing, return-order contact, then Vendor Card email.
- Default CC: OSR and ISR when reliably available, excluding the sender.
- Vendor-facing document.

### Purchase Return Pick Ticket

- Source: Purchase Return Order.
- Purpose: notify the warehouse to pick and ship items back to the supplier.
- Default To: location-specific routing, then Location Card email.
- Default CC: entered by the sender in the Email Editor.
- Warehouse document.

### Transfer Pick List

- Source: Transfer Order.
- Purpose: notify the transfer-from location to pick and ship inventory.
- Default To: transfer-from location routing, then Location Card email.
- Default CC: entered by the sender in the Email Editor.
- Warehouse-owned document. Do not add sales-team recipients automatically.

### Transfer Receipt Notification

- Source: Transfer Order.
- Purpose: notify the transfer-to location of incoming inventory.
- Default To: transfer-to location routing, then Location Card email.
- Default CC: entered by the sender in the Email Editor.
- Warehouse-owned document. Do not add sales-team recipients automatically.

### Customer Open Order Status

- Scope: one report per customer.
- Include: open warehouse and drop-ship Sales Order lines with outstanding quantity greater than zero.
- Include partially shipped lines while outstanding quantity remains.
- Default To: customer-specific routing, primary contact, then Customer Card email.
- Default CC: OSR and ISR, excluding the sender.
- Show: order number, customer PO, order date, requested date, promised or expected date, item, description, ordered quantity, shipped quantity, outstanding quantity, supply type, purchase order number, and customer-facing status.
- Do not show: vendor cost, margin, internal purchasing notes, vendor contacts, or internal escalation notes.

## Recommended implementation order

1. Shared Phase 2 infrastructure, version 0.19.0.0.
2. Sales return documents, version 0.19.1.0.
3. Purchase return documents, version 0.19.2.0.
4. Transfer documents, version 0.19.3.0.
5. Customer Open Order Status, version 0.20.0.0.

## Current infrastructure status

- New object range added: 70550..70649.
- New delivery document type values added.
- Current-user sender-account resolution service added.
- Recipient parsing, de-duplication, and sender exclusion added.
- Warehouse archive folder setup added.
- Transfer Header archive routing hook remains to be connected after the shared infrastructure compiles successfully.
