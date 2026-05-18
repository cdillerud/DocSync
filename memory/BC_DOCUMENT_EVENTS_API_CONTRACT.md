# BC Document Events API Contract

## Purpose

This contract defines the first safe integration surface between Business Central and GPI Hub for document delivery and attachment activity.

The immediate goal is to let a future Business Central AL extension notify GPI Hub when a BC user sends, fails to send, links, or fails to sync a document/attachment.

This API is intentionally observation-first:

- It records BC document activity.
- It creates or updates `hub_documents` records.
- It stores audit-friendly raw event rows in `bc_document_events`.
- It does not write to Business Central.
- It does not poll email.
- It is safe for sandbox validation while AP smoke testing continues separately.

## Base URL

Sandbox frontend tunnel:

```text
http://localhost:3010/api
```

VM-local backend:

```text
http://127.0.0.1:8010/api
```

## Status Endpoint

```http
GET /bc-document-events/status
```

Example response:

```json
{
  "status": "ready",
  "events_recorded": 1,
  "bc_event_documents": 1,
  "orphan_events": 0,
  "writes_to_bc": false,
  "mailbox_polling": false
}
```

`writes_to_bc` must remain `false` during this phase.

## Event Endpoints

```http
POST /bc-document-events/delivery-sent
POST /bc-document-events/delivery-failed
POST /bc-document-events/attachment-linked
POST /bc-document-events/attachment-sync-failed
```

## Lookup Endpoint

```http
GET /bc-document-events/records/{bc_record_type}/{bc_record_no}
```

Example:

```http
GET /bc-document-events/records/Posted%20Sales%20Invoice/SAMPLE-INV-001
```

Returns matching hub documents and raw BC document event rows.

## Repair Endpoint

```http
POST /bc-document-events/repair-orphans
```

This endpoint repairs any raw event rows that exist without a matching `hub_documents` record. It was added after the first sandbox test exposed an event-first failure path.

## Common Payload Fields

All event payloads share the following fields:

```json
{
  "event_id": "sample-delivery-sent-001",
  "idempotency_key": "sample-document-delivery-001",
  "correlation_id": "sandbox-bc-delivery-test-001",
  "event_timestamp": "2026-05-18T21:15:00Z",
  "source_app": "BC_AL_EXTENSION_SANDBOX",
  "source_system": "BC_NATIVE",
  "actor": "sandbox-user",
  "bc_record": {
    "company_id": "sandbox-company-id",
    "company_name": "Sandbox Company",
    "environment": "Sandbox",
    "record_type": "Posted Sales Invoice",
    "record_id": "sandbox-record-guid",
    "record_no": "SAMPLE-INV-001",
    "record_system_id": "sandbox-system-id",
    "posted": true
  },
  "document_no": "SAMPLE-INV-001",
  "document_type": "SALES_INVOICE",
  "file_name": "SAMPLE-INV-001.pdf",
  "metadata": {
    "test_payload": true
  }
}
```

## Required Fields

Minimum required fields:

```json
{
  "bc_record": {
    "record_type": "Posted Sales Invoice"
  }
}
```

Recommended required fields from the AL extension:

```json
{
  "event_id": "unique-event-id-from-bc-or-generated-guid",
  "idempotency_key": "stable-key-for-this-event",
  "correlation_id": "stable-key-for-this-business-operation",
  "event_timestamp": "2026-05-18T21:15:00Z",
  "actor": "bc-user-or-service-account",
  "bc_record": {
    "company_id": "bc-company-guid",
    "company_name": "company-display-name",
    "environment": "Sandbox-or-Production",
    "record_type": "Posted Sales Invoice",
    "record_id": "bc-api-record-guid",
    "record_no": "document-number",
    "record_system_id": "system-id-if-available",
    "posted": true
  },
  "document_no": "document-number",
  "document_type": "SALES_INVOICE",
  "file_name": "document.pdf"
}
```

## Idempotency Rules

The endpoint is idempotent by `event_id`.

If the same event is posted again, the API returns:

```json
{
  "success": true,
  "duplicate": true,
  "repaired_document": false,
  "orphaned_document": false,
  "event_id": "sample-delivery-sent-001",
  "document_id": "bc_doc_...",
  "message": "Event already recorded; hub document checked and repaired if needed"
}
```

No duplicate event or document should be created.

## Delivery Sent Payload Additions

Use `POST /bc-document-events/delivery-sent`.

Delivery-specific fields:

```json
{
  "delivery_method": "bc_email",
  "delivery_status": "sent",
  "template_code": "SALES_INVOICE_DEFAULT",
  "subject": "Sandbox Invoice SAMPLE-INV-001",
  "email_message_id": "sandbox-message-id-001",
  "recipient_resolution_method": "master_record_fallback",
  "recipients": {
    "to": ["recipient@example.invalid"],
    "cc": [],
    "bcc": []
  },
  "sharepoint": {
    "site_id": "sandbox-site-id",
    "drive_id": "sandbox-drive-id",
    "item_id": "sandbox-item-id",
    "web_url": "https://example.invalid/sandbox/SAMPLE-INV-001.pdf",
    "folder_path": "BC/Customer/SAMPLE/Sales Invoice/2026/SAMPLE-INV-001",
    "file_name": "SAMPLE-INV-001.pdf",
    "storage_status": "synced"
  }
}
```

Expected hub document state:

```json
{
  "status": "sent",
  "workflow_status": "exported",
  "last_bc_event_type": "delivery_sent"
}
```

## Delivery Failed Payload Additions

Use `POST /bc-document-events/delivery-failed`.

Delivery-specific fields:

```json
{
  "delivery_method": "bc_email",
  "delivery_status": "failed",
  "template_code": "SALES_INVOICE_DEFAULT",
  "subject": "Sandbox Invoice SAMPLE-INV-002",
  "recipient_resolution_method": "master_record_fallback",
  "recipients": {
    "to": ["recipient@example.invalid"],
    "cc": [],
    "bcc": []
  },
  "error": "Sandbox simulated send failure"
}
```

Expected hub document state:

```json
{
  "status": "delivery_failed",
  "workflow_status": "exception",
  "last_bc_event_type": "delivery_failed"
}
```

## Attachment Linked Payload Additions

Use `POST /bc-document-events/attachment-linked`.

Attachment-specific fields:

```json
{
  "attachment_id": "sandbox-attachment-id-001",
  "attachment_source": "bc_document_attachment",
  "content_type": "application/pdf",
  "file_size_bytes": 123456,
  "storage_status": "synced",
  "sharepoint": {
    "site_id": "sandbox-site-id",
    "drive_id": "sandbox-drive-id",
    "item_id": "sandbox-item-id",
    "web_url": "https://example.invalid/sandbox/SAMPLE-PO-001.pdf",
    "folder_path": "BC/Vendor/SAMPLE/Purchase Order/2026/SAMPLE-PO-001",
    "file_name": "SAMPLE-PO-001.pdf",
    "storage_status": "synced"
  }
}
```

Expected hub document state:

```json
{
  "status": "attachment_linked",
  "workflow_status": "captured",
  "last_bc_event_type": "attachment_linked"
}
```

## Attachment Sync Failed Payload Additions

Use `POST /bc-document-events/attachment-sync-failed`.

Attachment-specific fields:

```json
{
  "attachment_id": "sandbox-attachment-id-002",
  "attachment_source": "bc_document_attachment",
  "content_type": "application/pdf",
  "file_size_bytes": 123456,
  "storage_status": "failed",
  "error": "Sandbox simulated SharePoint upload failure"
}
```

Expected hub document state:

```json
{
  "status": "attachment_sync_failed",
  "workflow_status": "exception",
  "last_bc_event_type": "attachment_sync_failed"
}
```

## Collections Updated

### `bc_document_events`

Raw event/audit collection. Stores the full incoming event context and event-specific payload.

Primary key:

```text
event_id
```

### `hub_documents`

Unified document record. One document row is created or updated from the BC event.

Stable document id:

```text
bc_doc_<sha256-derived-key>
```

Important fields:

```json
{
  "source": "bc_document_event",
  "source_system": "BC_NATIVE",
  "capture_channel": "API",
  "doc_type": "SALES_INVOICE",
  "category": "Sales",
  "status": "sent",
  "workflow_status": "exported",
  "bc_source": {
    "record_type": "Posted Sales Invoice",
    "record_no": "SAMPLE-INV-001"
  },
  "last_bc_event_type": "delivery_sent",
  "delivery": {},
  "attachments": []
}
```

## AL Extension Guidance

The AL extension should treat this API as a notification target only.

Initial AL responsibilities:

- Generate or reuse stable `event_id` values.
- Create a deterministic `idempotency_key` for each send/attachment event.
- Include enough BC record context for GPI Hub to link the event back to BC.
- Include SharePoint item metadata after upload/sync succeeds.
- Send failure events when BC email delivery, template resolution, recipient resolution, or SharePoint sync fails.

The AL extension should not expect GPI Hub to write back into BC during this phase.

## Sandbox Test Commands

Status:

```bash
curl http://127.0.0.1:8010/api/bc-document-events/status | python3 -m json.tool
```

Delivery sent:

```bash
curl -X POST http://127.0.0.1:8010/api/bc-document-events/delivery-sent \
  -H 'Content-Type: application/json' \
  -d @scripts/sample_bc_delivery_sent_event.json | python3 -m json.tool
```

Delivery failed:

```bash
curl -X POST http://127.0.0.1:8010/api/bc-document-events/delivery-failed \
  -H 'Content-Type: application/json' \
  -d @scripts/sample_bc_delivery_failed_event.json | python3 -m json.tool
```

Attachment linked:

```bash
curl -X POST http://127.0.0.1:8010/api/bc-document-events/attachment-linked \
  -H 'Content-Type: application/json' \
  -d @scripts/sample_bc_attachment_linked_event.json | python3 -m json.tool
```

Attachment sync failed:

```bash
curl -X POST http://127.0.0.1:8010/api/bc-document-events/attachment-sync-failed \
  -H 'Content-Type: application/json' \
  -d @scripts/sample_bc_attachment_sync_failed_event.json | python3 -m json.tool
```

Lookup sample sales invoice:

```bash
curl "http://127.0.0.1:8010/api/bc-document-events/records/Posted%20Sales%20Invoice/SAMPLE-INV-001" | python3 -m json.tool
```
