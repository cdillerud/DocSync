# Sprint 1: Sales Order Confirmation Preflight

## Purpose

Sprint 1 establishes the first production-shaped contract between Business Central and GPI Document Hub for replacing Zetadocs outbound delivery.

Business Central supplies the authoritative Sales Order, customer, salesperson, and current-user context. GPI Hub evaluates deterministic routing, renders the email metadata, records an auditable delivery package, and returns warnings. Business Central then presents a read-only delivery preview and allows the user to run report 50020 as a PDF preview.

## Current safety state

This slice is preview-only.

- No email message is created or sent.
- No Business Central transaction record is written.
- No SharePoint file or folder is created.
- No mailbox is polled.
- GPI Hub records only the preflight package in MongoDB.
- Business Central records the API result in GPI Document Delivery Log.
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

## Business Central action

Extension version `0.2.0.0` adds this Sales Order action:

```text
Preview GPI Order Confirmation
```

The action:

1. Saves the current Sales Order.
2. Verifies that the record is a Sales Order with a sell-to customer.
3. Resolves the customer email from Sales Header and Customer.
4. Resolves the OSR from Salesperson Code and Salesperson/Purchaser email.
5. Uses the current BC user as the initiating sender for this pilot.
6. Builds a stable correlation ID from order number, system row version, and user security ID.
7. Calls the GPI Hub preflight endpoint with the configured API key.
8. Stores the full API response in GPI Document Delivery Log.
9. Opens a read-only GPI Order Confirmation Preview page.
10. Allows the user to run report 50020 using the current Sales Order filter.

The preview page displays:

- Preflight status
- Package and correlation IDs
- Sender and recipients
- Subject and email body
- Attachment file name
- Planned SharePoint path
- Routing rule
- Warnings

The PDF action runs the BC report only. It does not create an email draft or send anything.

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

The preview page still opens for a blocked package so the user can see the exact reason. A future draft action must refuse to continue when `can_create_email_draft` is false.

## Idempotency

`correlation_id` identifies one BC user previewing one saved version of a Sales Order.

- Same user, same system row version, and same payload: return the existing package.
- A saved Sales Order change produces a new system row version and correlation ID.
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

`.github/workflows/sprint1-document-delivery.yml` compiles the Sprint 1 Python modules and runs these tests on pushes and pull requests that affect the preflight contract.

## Next build slice

After the extension compiles and the preview is validated in the BC sandbox, add a separately gated action:

```text
Create GPI Email Draft (Sandbox)
```

That action will reuse the successful preflight package, generate report 50020 to a temporary stream, attach it to a native BC email message, and open the BC email editor. Automated sending will remain disabled.
