# GPI Sales Document Email Tests

Sandbox-only AL tests and UAT utilities for the production `GPI Sales Document Email` extension, which is part of the Business Central Zetadocs Replacement.

## Coverage

- Recipient parsing, de-duplication, sender exclusion, and recipient precedence
- Sales, Purchase, and Transfer document visibility
- Released-status and transfer-location validation
- Customer Open Order Status validation and PDF/XML rendering
- Archive routing, date formatting, path sanitization, and SharePoint URL generation
- Delivery Log metadata, Blob, and Source-key persistence
- Customer, vendor, and location routing scope isolation
- Routing priority, audit order, Add and Replace behavior, date filtering, and location constraints
- Mocked email send success and failure
- Mocked email editor actions
- Mocked archive success, returned identifiers, and safe unhandled failure
- End-to-end mocked Sales Return, Purchase Return, Transfer, and Open Order workflow Delivery Logs
- End-to-end mocked SharePoint archive success, failure, PDF retention, and retry protection
- TestPage-driven UAT simulations for the eight Phase 2 user actions
- UAT Replace-rule recipient isolation and page-level Send simulation
- Persistent sandbox UAT sample-pack generation for visual PDF review

The automated suite does not send real email, open the email editor, upload to SharePoint, or create archive tasks.

## UAT sample pack

The test extension adds two actions to the GPI Document Delivery Log:

- `Generate UAT Sample Pack`
- `Open UAT Sample Packs`

The generator creates persistent sandbox source records and seven reviewable PDFs:

- Sales Return Authorization
- Sales Return Warehouse Notification
- Purchase Return Order
- Purchase Return Pick Ticket
- Transfer Pick List
- Transfer Receipt Notification
- Customer Open Order Status

The PDFs are stored in the Delivery Log with status `Ready`, sender policy `UAT Sample Pack`, and a shared pack identifier. The generator does not send email or upload files to SharePoint.

## Build

Run `scripts/Prepare-GPIALTests.ps1`. Publish both apps only to `Sandbox_5_5_2026`.

## Test codeunits

- 70700 GPI Recipient Tests
- 70701 GPI Line Visibility Tests
- 70702 GPI Transfer Visibility Tests
- 70703 GPI Workflow Validation Tests
- 70704 GPI Open Order Report Tests
- 70705 GPI Archive Path Tests
- 70706 GPI Delivery Log Tests
- 70707 GPI Routing Resolver Tests
- 70709 GPI Delivery Transport Tests
- 70710 GPI Workflow Return Tests
- 70712 GPI Workflow Warehouse Tests
- 70713 GPI Archive Workflow Tests
- 70714 GPI UAT Simulation Tests
- 70718 GPI UAT Sample Pack Tests

Codeunit 70708 is the manual transport mock subscriber. Codeunit 70711 contains shared workflow test data and assertions. Codeunit 70715 contains UAT simulation setup and assertions. Codeunit 70716 generates the manual UAT sample pack. Page extension 70717 exposes the sample-pack actions.

Current total: 60 tests.

Do not install this test extension in Production.
