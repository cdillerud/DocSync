# GPI Sales Document Email

A small Business Central-only replacement for the first Zetadocs workflow.

## Phase 1 scope

Adds **Preview and Email Order Confirmation** to the standard Sales Order page.

The action:

1. Validates that the record is a Sales Order.
2. Resolves the recipient in this order:
   - Sell-to Contact email
   - Sales Order Sell-to Email
   - Customer email
3. Adds the Salesperson email to CC.
4. Attempts to locate the existing custom Inside Salesperson or ISR field dynamically and adds that salesperson's email to CC.
5. Excludes duplicates, the To recipient, and the initiating user from CC.
6. Generates report **50020** as PDF.
7. Names the file `Sales-Order <order no>.pdf`.
8. Opens the native Business Central Email Editor modally.
9. Requires the user to review and send the message manually.

## Explicitly not included

- Automatic sending
- GPI Hub
- API keys
- Cloudflare tunnels
- SharePoint archiving
- Batch invoice delivery

## Extension details

- Name: `GPI Sales Document Email`
- Version: `0.1.0.0`
- Object range: `70151000..70151049`
- Permission set: `GPI DOC EMAIL`
- Target: Business Central 28.x, runtime 17.0

## Publish

Open this folder as the VS Code workspace, download symbols for the target BC sandbox, package, and publish. Assign `GPI DOC EMAIL` to pilot users.

## Validation checklist

- Report 50020 exists in the target environment.
- The Sales Order recipient resolves correctly.
- OSR email is populated from Salesperson/Purchaser.
- ISR email is found from the existing custom Sales Header field.
- PDF opens and matches the current Zetadocs output.
- User can edit To, CC, subject, body, sender account, and attachment before sending.
- Canceling the editor sends nothing.
