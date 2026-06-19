# Phase 2 Documents

## Shared policy

- Sender: the Business Central user who initiates the email action.
- Sender requirement: the initiating user must resolve to a matching Business Central Email Account.
- Sender exclusion: the sender is removed from default To, CC, and BCC recipients.
- Individual delivery opens the native Business Central Email Editor.
- Batch delivery sends directly after preflight and confirmation.
- Tracking uses the existing Delivery Log, native email relation, draft reopening, sent-email history, and SharePoint archival framework.
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
- Default To: transfer-from Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor or supplied by a routing rule.
- No sales-team recipients are added automatically.
- Sending requires Released status; preview does not.

### Transfer Receipt Notification

- Version: 0.19.3.0.
- Source: Transfer Order.
- Default To: transfer-to Location Card email with location-specific and generic routing-rule support.
- Default CC: entered by the sender in the Email Editor or supplied by a routing rule.
- No sales-team recipients are added automatically.
- Sending requires Released status; preview does not.

Transfer lines use Both Transfer Documents, Pick List Only, Receipt Notification Only, and Do Not Print. Transfer PDFs archive under Warehouse using the relevant transfer-from or transfer-to location as the archive party.

### Customer Open Order Status

- Version: 0.20.0.0.
- Source: Customer plus live Sales Orders and outstanding Sales Lines.
- Scope: one report per customer.
- Includes warehouse and drop-ship item lines with Outstanding Quantity greater than zero, including partially shipped lines.
- Default To: customer-specific routing, primary contact, then Customer Card email.
- Default CC: OSR and ISR, excluding the sender and existing To recipients.
- Shows Sales Order number, customer PO, order date, item, description, outstanding quantity, unit of measure, supply type, linked Purchase Order number, expected date, and customer-facing status.
- Does not show vendor identity, vendor contacts, vendor cost, margin, internal purchasing notes, or escalation notes.
- Expected dates are estimates and may change.
- Individual delivery supports preview, Email Editor, Send, Save As Draft, Discard, Delivery Log, sent-email history, and Sales-folder archival.
- Batch delivery supports selected or filtered customers, current-user sending, preflight counts, direct send, repeat sends, and result totals.
- Repeat sends are intentionally allowed and create new Delivery Log entries.
- Delivery Log records the as-of date, included order count, line count, and Sales Order numbers.

## Phase 2 implementation status

1. Shared infrastructure, version 0.19.0.0: implemented.
2. Sales Return documents, version 0.19.1.0: implemented.
3. Purchase Return documents, version 0.19.2.0: implemented.
4. Transfer documents, version 0.19.3.0: implemented.
5. Customer Open Order Status, version 0.20.0.0: implemented, pending compile and sandbox validation.
