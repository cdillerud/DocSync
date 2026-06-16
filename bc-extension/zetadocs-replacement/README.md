# GPI Sales Document Email

A small Business Central-only replacement for selected Zetadocs document-email workflows.

## Supported document actions

The extension adds these actions to the standard Sales Order page:

- **Preview and Email Order Confirmation**
  - Report 50020
  - Customer/contact recipient logic
  - Attachment: `Sales-Order <order no>.pdf`

- **Preview and Email Prepayment Notice**
  - Report 50003
  - Customer/contact recipient logic
  - Attachment: `Pre-Payment - Order <order no>.pdf`

- **Preview and Email Pick Ticket**
  - Report 50013
  - Recipient comes from the Sales Order Location Card email field
  - Supports multiple location recipients separated by semicolons or commas
  - Attachment: `Pick-Ticket - Order <order no>.pdf`

## Shared behavior

Each action:

1. Validates that the record is a Sales Order.
2. Resolves the appropriate To recipient or recipients.
3. Adds the Salesperson email to CC.
4. Attempts to locate the existing custom Inside Salesperson or ISR field dynamically and adds that salesperson's email to CC.
5. Excludes duplicates, To recipients, and the initiating user from CC.
6. Generates the selected report as a PDF.
7. Opens the native Business Central Email Editor modally.
8. Requires the user to review and send the message manually.

## Customer recipient order

For Order Confirmations and Prepayment Notices, the recipient is resolved in this order:

1. Sell-to Contact email
2. Sales Order Sell-to Email
3. Customer email

## Pick Ticket routing

For Pick Tickets, the Sales Order must have a Location Code. The extension reads the email field from that Location Card and adds each semicolon- or comma-separated address as a separate To recipient.

Example for Location 012:

- `KLOGILGamerPkg@kochlogistics.com`
- `egonzalez@kochlogistics.com`

## Explicitly not included

- Automatic sending
- GPI Hub
- API keys
- Cloudflare tunnels
- SharePoint archiving
- Batch invoice delivery

## Extension details

- Name: `GPI Sales Document Email`
- Version: `0.3.0.0`
- Object range: `70510..70549`
- Permission set: `GPI DOC EMAIL`
- Target: Business Central 27.4 or later, runtime 16.0

## Publish

Open this folder as the VS Code workspace, use the existing Business Central symbol cache, package, and upload the generated `.app` through Extension Management. Assign `GPI DOC EMAIL` to pilot users.

## Validation checklist

- Report 50020 generates the correct Sales Order Confirmation.
- Report 50003 generates the correct Prepayment Notice.
- Report 50013 generates the correct Pick Ticket.
- Customer recipients resolve correctly for customer-facing documents.
- Pick Ticket recipients come from the Sales Order Location Card.
- OSR email is populated from Salesperson/Purchaser.
- ISR email is found from the existing custom Sales Header field.
- User can edit To, CC, subject, body, sender account, and attachment before sending.
- Canceling the editor sends nothing.
