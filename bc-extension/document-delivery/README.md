# GPI Hub Document Delivery Bridge - Business Central Extension

## Purpose

This extension is a disabled-by-default scaffold for sending Business Central document delivery and attachment events to GPI Document Hub.

It is not a Zetadocs replacement yet. It is the first safe bridge layer.

Current scope:

- Store GPI Hub endpoint settings.
- Store the shared API key used by GPI Hub.
- Test the GPI Hub BC document-events status endpoint.
- Build a sample `delivery_sent` payload.
- Send the sample payload to GPI Hub only when integration is enabled.
- Log success, failure, duplicate status, HTTP status, response body, and returned hub document ID.

Out of scope for this scaffold:

- No automatic sending from posted invoices.
- No replacement of current BC document delivery behavior.
- No Zetadocs production behavior changes.
- No Business Central production writeback from GPI Hub.
- No SharePoint upload from AL yet.

## GPI Hub Requirements

GPI Hub sandbox must have the BC document-events API enabled and protected with an API key.

Required GPI Hub status response:

```json
{
  "status": "ready",
  "writes_to_bc": false,
  "mailbox_polling": false,
  "api_key_required": true,
  "api_key_configured": true
}
```

The API key is stored in the GPI Hub sandbox `.env` as:

```text
BC_DOCUMENT_EVENTS_API_KEY=<secret>
```

On the VM, view the key with:

```bash
grep '^BC_DOCUMENT_EVENTS_API_KEY=' /opt/gpi-hub-bc-sandbox/backend/.env
```

## Business Central Setup

Search for:

```text
GPI Document Delivery Setup
```

Recommended sandbox values:

```text
Integration Enabled: false initially
Hub Base URL: https://<temporary-public-sandbox-url>
API Key: <BC_DOCUMENT_EVENTS_API_KEY value from GPI Hub sandbox>
Environment Name: BC sandbox environment name
Company ID: BC company ID or sandbox placeholder
Company Name: BC company display name
Log Successful Events: true
```

Run **Test Connection** first.

Only after Test Connection succeeds, enable:

```text
Integration Enabled: true
```

Then run:

```text
Send Sample Delivery Event
```

The sample event should appear in GPI Hub under:

```text
BC Events
```

## Local BC Log

Search for:

```text
GPI Document Delivery Log
```

The log records:

- Event ID
- Event Type
- Correlation ID
- BC Record Type
- BC Record No.
- Document Type
- File Name
- Endpoint
- HTTP Status Code
- Success
- Duplicate
- Hub Document ID
- Error Message
- Full response body

Use **View Response Body** to inspect the full GPI Hub API response.

## First Test Flow

1. Confirm GPI Hub sandbox smoke test passes:

```bash
cd /opt/gpi-hub-bc-sandbox
bash scripts/test_bc_document_events.sh
```

2. Expose GPI Hub sandbox over HTTPS using the approved temporary tunnel/proxy approach.

3. Install this extension in BC sandbox.

4. Open **GPI Document Delivery Setup**.

5. Enter the public HTTPS GPI Hub base URL and API key.

6. Click **Test Connection**.

7. Set **Integration Enabled** to true.

8. Click **Send Sample Delivery Event**.

9. Confirm local BC log success.

10. Confirm GPI Hub BC Events page shows the AL-created event.

## Guardrails

The extension starts disabled.

Do not wire this into real posted invoice send actions until:

- Test connection works from BC sandbox.
- Sample event reaches GPI Hub.
- GPI Hub logs the AL event correctly.
- BC local log records the returned hub document ID.
- HTTPS exposure approach is approved.
- API key is not committed to source control.

## Next Build Slice

After sandbox connectivity is proven, add one manual page action on Posted Sales Invoice:

```text
Send GPI Hub Test Event
```

That action should only notify GPI Hub. It should not replace or alter the native BC email/send process.
