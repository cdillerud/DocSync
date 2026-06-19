# Phase 2 Shared Infrastructure Sandbox Tests

Target environment: Sandbox_5_5_2026

## Build

- Download Business Central 28.1 symbols.
- Compile version 0.19.0.0.
- Confirm no duplicate object IDs in ranges 70510..70549 and 70550..70649.
- Confirm the GPI PH2 DOC EMAIL permission-set extension compiles.

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

## Archive setup

- Open GPI SharePoint Archive Setup.
- Confirm Warehouse Folder appears.
- Confirm new setup records default Warehouse Folder to Warehouse.
- For existing setup records, enter Warehouse manually if the field is blank.

## Regression

- Confirm Phase 1 document preview and email actions still open.
- Confirm Warehouse Receiving Notice continues to use Purchase Header ISR as sender.
- Confirm existing Sales and Purchase archive folders are unchanged.

Do not use the Phase 2 infrastructure build for document delivery until the document-specific workflows are implemented and validated.
