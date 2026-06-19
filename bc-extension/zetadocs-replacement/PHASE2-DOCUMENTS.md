# Phase 2 Documents

## Shared policy

- Sender: the Business Central user who initiates the email action.
- Sender requirement: the initiating user must resolve to a matching Business Central Email Account.
- Sender exclusion: the sender is removed from default To, CC, and BCC recipients.
- Email behavior: open the native Business Central Email Editor. Do not send automatically.
- Tracking: use the existing Delivery Log, native email relation, draft reopening, sent-email history, and SharePoint archival framework.
- Validation target: Sandbox_5_5_2026.

## Implemented documents

### Sales Return Authorization

- Version: 0.19.1.0.
- Source: Sales Return Order.
- Default To: customer-specific routing, return-order contact, customer primary contact, then Customer Card email.
- Default CC: OSR and ISR, excluding the sender and existing To recipients.
- Pricing is not displayed; final credit is subject to receipt and inspection.
- Sending requires Released status; preview does not.

### Sales Return Warehouse Notification

- Version: 0.19.1.0.
- Source: Sales Return Order.
- Default To: Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor.
- Sending requires Released status; preview does not.

### Purchase Return Order

- Version: 0.19.2.0.
- Source: Purchase Return Order.
- Default To: vendor-specific routing, return-order contact, vendor primary contact, then Vendor Card email.
- Default CC: OSR and ISR when identifiable, excluding the sender and existing To recipients.
- Pricing is not displayed.
- Sending requires Released status; preview does not.

### Purchase Return Pick Ticket

- Version: 0.19.2.0.
- Source: Purchase Return Order.
- Default To: Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor.
- Uses the warehouse quantity and unit-of-measure display policy.
- Sending requires Released status; preview does not.

### Transfer Pick List

- Version: 0.19.3.0.
- Source: Transfer Order.
- Purpose: notify the transfer-from location to pick and ship inventory.
- Default To: transfer-from Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor or supplied by a routing rule.
- No sales-team recipients are added automatically.
- Sending requires Released status; preview does not.

### Transfer Receipt Notification

- Version: 0.19.3.0.
- Source: Transfer Order.
- Purpose: notify the transfer-to location of incoming inventory.
- Default To: transfer-to Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor or supplied by a routing rule.
- No sales-team recipients are added automatically.
- Sending requires Released status; preview does not.

Transfer lines use a dedicated visibility field with Both Transfer Documents, Pick List Only, Receipt Notification Only, and Do Not Print. Transfer PDFs archive under the Warehouse folder using the relevant transfer-from or transfer-to location as the archive party.

## Planned document

### Customer Open Order Status

- Scope: one report per customer.
- Include open warehouse and drop-ship Sales Order lines with outstanding quantity greater than zero, including partially shipped lines.
- Default To: customer-specific routing, primary contact, then Customer Card email.
- Default CC: OSR and ISR, excluding the sender.
- Show customer-facing order, item, quantity, supply-type, purchase-order, and expected-date details.
- Do not show vendor cost, margin, internal notes, vendor contacts, or escalation notes.

## Implementation order

1. Shared Phase 2 infrastructure, version 0.19.0.0: implemented.
2. Sales return documents, version 0.19.1.0: implemented.
3. Purchase return documents, version 0.19.2.0: implemented.
4. Transfer documents, version 0.19.3.0: implemented, pending compile and sandbox validation.
5. Customer Open Order Status, version 0.20.0.0: next sprint.
