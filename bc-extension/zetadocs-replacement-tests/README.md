# GPI Sales Document Email Tests

Sandbox-only AL tests for the production `GPI Sales Document Email` extension.

## Coverage

- Recipient parsing, de-duplication, sender exclusion, and recipient precedence
- Sales, Purchase, and Transfer document visibility
- Released-status and transfer-location validation
- Customer Open Order Status no-data validation
- Customer Open Order PDF rendering
- Open Order XML dataset inclusion and exclusion rules
- Hidden nonzero financial-line blocking during report generation
- Sales, Purchase, and Warehouse archive routing
- Archive date formatting, path sanitization, and SharePoint web URL generation
- Open Order Delivery Log metadata, document Blob, and Source-key persistence

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

Current total: 32 tests.

Do not install this test extension in Production.
