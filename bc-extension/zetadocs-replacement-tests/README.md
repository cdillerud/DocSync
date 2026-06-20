# GPI Sales Document Email Tests

Sandbox-only AL tests for the production `GPI Sales Document Email` extension.

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

The suite does not send real email, open the email editor, upload to SharePoint, or create archive tasks.

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

Codeunit 70708 is the manual transport mock subscriber. Codeunit 70711 contains shared workflow test data and assertions.

Current total: 51 tests.

Do not install this test extension in Production.
