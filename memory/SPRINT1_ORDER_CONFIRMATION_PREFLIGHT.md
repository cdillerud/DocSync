# Sprint 1: Sales Order Confirmation Preflight

## Purpose

Sprint 1 establishes the first production-shaped contract between Business Central and GPI Document Hub for replacing Zetadocs outbound delivery.

Business Central remains responsible for generating report 50020, attaching the PDF to a native BC email, and showing the email editor to the user. GPI Hub evaluates deterministic routing, renders the email metadata, records an auditable delivery package, and returns warnings before BC creates the draft.

## Current safety state

This slice is preview-only.

- No email is sent.
- No Business Central record is written.
- No SharePoint file or folder is created.
- No mailbox is polled.
- GPI Hub only records the preflight package in MongoDB.
- The existing Zetadocs process remains unchanged.

## Sandbox endpoint

```http
POST /api/document-delivery/v1/preflight
X-GPI-Hub-Api-Key: <BC_DOCUMENT_EVENTS_API_KEY>
Content-Type: application/json
```

Status:

```http
GET /api/document-delivery/v1/status
X-GPI-Hub-Api-Key: <BC_DOCUMENT_EVENTS_API_KEY>
```

Package lookup:

```http
GET /api/document-delivery/v1/packages/{package_id}
X-GPI-Hub-Api-Key: <BC_DOCUMENT_EVENTS_API_KEY>
```

## Supported workflow

Sprint 1 supports only:

```text
SALES_ORDER_CONFIRMATION
```

The report ID must be:

```text
50020 - Sales - Confirmation
```

Requests for another document type or report ID are rejected before a package is created.

## Sample request

Use `scripts/sample_document_delivery_preflight.json`.

```bash
curl -X POST http://127.0.0.1:8010/api/document-delivery/v1/preflight \
  -H "Content-Type: application/json" \
  -H "X-GPI-Hub-Api-Key: ${BC_DOCUMENT_EVENTS_API_KEY}" \
  --data @scripts/sample_document_delivery_preflight.json | python3 -m json.tool
```

## Returned package

The response includes:

- Package ID and correlation ID
- `PREFLIGHT_READY` or `PREFLIGHT_BLOCKED`
- BC report ID and PDF file name
- Resolved sender, To, CC, and BCC recipients
- Rendered subject and body from the existing Zetadocs parity template
- Logical SharePoint destination, without writing to SharePoint
- Deterministic routing context
- Blocking and nonblocking warnings
- Audit events
- Original normalized request

## Routing behavior

The endpoint reuses the routing rules already proven in the Zetadocs mirror.

Standard Sales Orders remain eligible for ISR/OSR participation and sales-tile visibility. Transfer orders and affected internal Gamer transactions are owned by Logistics/Accounting and therefore exclude automatic sales copies and sales-tile visibility unless an explicit override is provided.

The sender, recipients, document type, process owner, and transfer/internal status are deterministic inputs. AI is not used for delivery authorization or recipient resolution.

## Blocking rules

The preflight is blocked when any of these are missing:

- Customer organization
- External recipient
- Sender

A missing customer PO/external document number is currently a warning, not a block.

BC must not create the email draft when `can_create_email_draft` is false.

## Idempotency

`correlation_id` identifies one business operation.

- Same correlation ID and same normalized payload: return the existing package.
- Same correlation ID and materially different payload: return HTTP 409.
- Package IDs are deterministic from the correlation ID.

The sandbox database uses sparse unique indexes so earlier Zetadocs mirror package records that do not contain a correlation ID remain valid.

## Sandbox server

The existing production server entry point is unchanged. `docker-compose.bc-sandbox.yml` explicitly runs:

```text
uvicorn server_sprint1:app --host 0.0.0.0 --port 8001
```

`server_sprint1.py` imports the existing app and mounts the new router under `/api`. This keeps Sprint 1 isolated from the normal deployment path.

## Automated tests

`backend/tests/test_document_delivery_preflight.py` covers:

1. Standard Sales Order Confirmation readiness
2. Transfer-order exclusion of sales copies and tiles
3. Missing-recipient blocking
4. Idempotent repeat requests
5. Correlation ID collision protection
6. Report 50020 enforcement

## Next build slice

The next slice is the Business Central AL client and Sales Order page action:

```text
Preview GPI Order Confirmation
```

That action will collect authoritative BC values, call this preflight endpoint, generate report 50020 into a temporary stream, and open the native BC email editor. It will remain draft/preview-only until parity is validated against Zetadocs.
