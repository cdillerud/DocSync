# GPI Sales Document Email

A Business Central replacement for selected Zetadocs document-generation, email, delivery-log, and SharePoint archival workflows.

## Supported documents

### Sales

- Sales Order Confirmation
- Prepayment Notice
- Pick Ticket
- Blanket Sales Order

Sales Order Confirmation and Pick Ticket can be previewed while Open, but sending requires a Released Sales Order. Prepayment Notice can be previewed in any status, but sending requires the installed prepayment-status field to be Pending Prepayment.

Customer-specific routing rules are evaluated first. When no customer-specific rule supplies the recipient, Sales Order Confirmation, Blanket Sales Order, and Prepayment Notice use the contact selected on the source order. Pick Ticket uses the Location Card email.

### Accounts receivable

- Posted Sales Invoice
- Filterable posted-invoice queue
- Refresh recipients and readiness
- Send selected invoices
- Send all filtered ready invoices
- Skip missing-recipient and previously sent invoices

Invoice batches use the dedicated **GPI Invoice Batch** email scenario rather than the current user's mailbox. Customer-specific Invoice routing rules are evaluated first; otherwise, the recipient is the Customer Card primary contact.

### Purchasing and logistics

- Drop Ship Purchase Order for Location Code `00`
- Warehouse Purchase Order for populated Location Codes other than `00`
- Warehouse Receiving Notice with a required Warehouse Receipt Date

Purchase Order actions are consolidated under **Actions > Gamer Documents**.

Warehouse Purchase Orders and Warehouse Receiving Notices can be previewed while Open, but sending requires a Released Purchase Order. Warehouse Purchase Orders are composed from the Business Central Email Account whose address matches the ISR email on the Purchase Header. Each ISR sender address must therefore be registered in **Email Accounts**.

## Warehouse unit of measure

Pick Ticket and Warehouse Receiving Notice line quantities use the Item Card **Whse Unit of Measure Code**. The displayed quantity is calculated as:

`Quantity (Base) / Item Unit of Measure."Qty. per Unit of Measure"`

For example, 117,936 base eaches with a pallet conversion of 39,312 display as 3 pallets. Items whose warehouse UOM is `CS` use the `CS` Item Unit of Measure conversion line.

## Customer and Vendor Cards

Customer Card and Vendor Card include **Gamer Documents > Gamer Document Routing Rules**, filtered to the current customer or vendor. These cards do not send documents and do not expose Delivery Log or Sent Email History actions.

## SharePoint archival

Successfully sent GPI-generated documents can be archived through the **GPI Document Archive** External File Storage scenario.

The archive uses the existing Zetadocs document library and preserves the familiar structure:

`MM-DD-YYYY / Customer or Vendor / Sales or Purchase / Document`

The Delivery Log records archive status, path, URL, attempts, and errors. The Business Central PDF BLOB can be cleared only after SharePoint confirms that the file was created.

## Drag-and-drop and manual documents

Business Central 28 includes the standard **Doc. Attachment List Factbox**, which supports native multiple-file upload and drag-and-drop on document and master-data pages.

To store those attachments in SharePoint:

1. Open **GPI SharePoint Archive Setup**.
2. Choose **Configure Drag-and-Drop Storage**.
3. Assign **Doc. Attach. - External Storage** to the same SharePoint file account used for **GPI Document Archive**.
4. Complete **External Storage Setup** and choose a root folder such as `Manual Documents`.
5. Enable external attachment storage.

GPI-generated outbound PDFs continue to use the Zetadocs-compatible date/customer structure. Manually uploaded attachments use Microsoft's standard external-attachment folder structure beneath the selected manual-document root.

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
- Temporary stored PDF content
- SharePoint archival status and location

Preview actions do not create delivery-log entries.

## Routing rules

Routing rules can target a document type and optionally narrow by:

- Customer No.
- Vendor No.
- Location Code
- Effective dates
- Priority
- Replace or Add recipient behavior

For customer-facing sales documents, customer-specific rules are processed before standard fallback recipients. Document-wide rules remain available when no customer-specific rule applies.

## Accounting invoice sender setup

1. Add or confirm the Accounting invoice mailbox in **Email Accounts**.
2. Open **GPI Posted Sales Invoice Queue**.
3. Choose **Configure Accounting Sender**.
4. Assign the **GPI Invoice Batch** scenario to the Accounting mailbox.
5. Return to the queue and confirm the Accounting Invoice Sender status shows **Configured** with the expected account name, address, and connector.

The invoice batch is blocked when the scenario is not assigned.

## Warehouse PO ISR sender setup

1. Confirm the Purchase Header ISR field is populated.
2. Confirm that ISR exists in **Salespeople/Purchasers** and has the correct email address.
3. Open **Email Accounts** and register the mailbox or shared mailbox with the same address.
4. Test the account connection.
5. Send a Warehouse Purchase Order and confirm the email editor opens with the ISR account selected.

Business Central requires a registered Email Account, including Account ID and connector, to select a specific From account in the native email editor.

## Extension details

- Name: `GPI Sales Document Email`
- Publisher: `Gamer Packaging`
- Version: `0.16.0.0`
- Object range: `70510..70549`
- Permission set: `GPI DOC EMAIL`
- Platform: Business Central 28.0
- Application: 28.1
- Runtime: 17.0

## Sandbox validation checklist

For each document type, confirm:

1. Correct source document and branded PDF
2. Correct default and rule-based recipients
3. Correct Released or Pending Prepayment send enforcement
4. Correct sender account or current-user sender policy
5. Successful send through native Business Central email
6. Delivery Log status and metadata
7. SharePoint archive status and link
8. Native Sent Email History resolves correctly

For Pick Ticket and Warehouse Receiving Notice, test both pallet and case Item UOM conversions. For manual attachments, confirm multiple files can be added from the standard Documents factbox and that the external-storage fields show the files as stored externally.

## Deferred items

- Purchase Order and Warehouse Receiving Notice sent-indicator integration requires the exact existing field IDs and captions from the Gamer sandbox metadata.
- Warehouse Receiving Notice sender policy is still TBD.
- Line exclusion remains pending business clarification.
- Posted Sales Credit Memo email workflow is not currently implemented.
