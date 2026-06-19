# GPI Sales Document Email Tests

This is a sandbox-only AL test extension for the production `GPI Sales Document Email` extension.

## Initial automated coverage

- Recipient parsing for comma-separated and semicolon-separated addresses
- Case-insensitive recipient de-duplication
- Sender exclusion from To, CC, and BCC
- To-over-CC-over-BCC precedence
- Recipient list formatting
- Sales and Purchase line Document Visibility behavior
- Financial-line visibility safeguards and expected errors
- Transfer Pick List and Receipt Notification visibility behavior
- Open Sales Return, Purchase Return, and Transfer sending restrictions
- Transfer source and destination validation
- Customer Open Order Status rejection when no outstanding item lines exist

The initial suite deliberately does not send real email, open the email editor, upload to SharePoint, or create scheduled archive tasks.

## Build sequence

1. Build the production extension first.
2. Run `scripts/Prepare-GPIALTests.ps1` from the repository.
3. The script copies the newest production `.app` and downloaded Microsoft symbol packages into this test project's `.alpackages` folder.
4. In the test project, run `AL: Download Symbols` if needed and then build with `Ctrl+Shift+B`.
5. Publish the production app and the test app only to `Sandbox_5_5_2026`.

## Running the tests

In the sandbox, open **AL Test Tool** or **Test Tool** and add the test codeunits:

- 70700 GPI Recipient Tests
- 70701 GPI Line Visibility Tests
- 70702 GPI Transfer Visibility Tests
- 70703 GPI Workflow Validation Tests

Run all tests and export or capture the result list.

Do not install this test extension in Production.
