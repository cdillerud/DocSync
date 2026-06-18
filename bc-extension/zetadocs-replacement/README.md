# GPI Sales Document Email

A Business Central-only replacement for selected Zetadocs sales, invoice, and purchasing document-email workflows.

## Supported documents

### Sales

- Sales Order Confirmation
- Prepayment Notice
- Pick Ticket
- Blanket Sales Order

These documents are reviewed and sent by the current Business Central user.

### Accounts receivable

- Posted Sales Invoice
- Filterable posted-invoice queue
- Refresh recipients and readiness
- Send selected invoices
- Send all filtered ready invoices
- Skip missing-recipient and previously sent invoices

Invoice batches use the dedicated **GPI Invoice Batch** email scenario rather than the current user's mailbox.

### Purchasing and logistics

- Drop Ship Purchase Order for Location Code `00`
- Warehouse Purchase Order for populated Location Codes other than `00`
- Warehouse Receiving Notice with a required Warehouse Receipt Date

Purchase Order actions are consolidated under **Actions > Gamer Documents**.

## Delivery logging

Each email workflow can record:

- Document type and source record
- Customer, vendor, or location
- To, CC, and BCC recipients
- Subject and attachment filename
- Sender user, sender account, connector, and sender policy
- Applied routing rules
- Email and external delivery IDs
- Sent, failed, draft, or discarded status
- Stored PDF content

Preview actions do not create delivery-log entries.

## Routing rules

Routing rules can target a document type and optionally narrow by:

- Customer No.
- Vendor No.
- Location Code
- Effective dates
- Priority
- Replace or Add recipient behavior

## Accounting invoice sender setup

1. Add or confirm the Accounting invoice mailbox in **Email Accounts**.
2. Open **GPI Posted Sales Invoice Queue**.
3. Choose **Configure Accounting Sender**.
4. Assign the **GPI Invoice Batch** scenario to the Accounting mailbox.
5. Return to the queue and confirm the Accounting Invoice Sender status shows **Configured** with the expected account name, address, and connector.

The invoice batch is blocked when the scenario is not assigned.

## Extension details

- Name: `GPI Sales Document Email`
- Publisher: `Gamer Packaging`
- Version: `0.13.0.0`
- Object range: `70510..70549`
- Permission set: `GPI DOC EMAIL`
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation checklist

For each document type, confirm:

1. Correct source document and branded PDF
2. Correct default and rule-based recipients
3. Correct sender account or current-user sender policy
4. Successful send through native Business Central email
5. Delivery Log status and metadata
6. Stored PDF opens correctly
7. Native Sent Email History resolves correctly

Invoice batches should additionally confirm that the Delivery Log and posted invoice fields show the configured Accounting sender address.
