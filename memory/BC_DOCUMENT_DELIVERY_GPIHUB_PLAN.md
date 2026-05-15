# BC Document Delivery + GPI Hub Integration Plan

## Purpose

This branch exists to design and build the Business Central document delivery and attachment replacement work without disturbing the AP smoke-test path.

The goal is not to build a standalone Zetadocs clone. The goal is to make Business Central, SharePoint, and GPI Hub work together as a single document operating model:

- Business Central remains the transactional system of record.
- SharePoint becomes the durable document and attachment store.
- GPI Hub becomes the document intelligence, workflow, validation, and observability layer.
- A Business Central AL extension becomes the native BC user experience bridge.

## Branch

Working branch:

`feature/bc-document-delivery-gpihub`

This branch should remain isolated from AP smoke-test work until explicitly merged.

## Non-Negotiable Guardrails

1. Do not break the AP invoice smoke-test flow.
2. Do not alter production write guards.
3. Do not enable automatic BC writes from this branch.
4. Do not replace existing AP review behavior during early development.
5. Treat all new BC document delivery work as additive until smoke-test results are reviewed.
6. Keep BC Production read-only and continue routing any experimental writes through the existing sandbox/write-guard model.
7. Preserve current hub_documents as the unified document record model unless a specific migration requirement proves otherwise.

## Current GPI Hub Fit

The existing system already has the correct foundation:

- Unified document queue through `hub_documents`.
- Email/file/manual ingestion paths.
- SharePoint storage integration.
- Business Central service integration.
- AP review workspace and BC posting safety model.
- Workflow engine and document status tracking.
- Legacy Square9 and Zetadocs document classification mappings.
- Shadow/pilot mode discipline.

This new work should extend that foundation instead of creating a parallel document system.

## Target Architecture

```text
Business Central UI
  |
  | native send / attach / open actions
  v
BC AL Extension
  |
  | document delivery events
  | attachment events
  | recipient routing metadata
  | delivery log metadata
  v
GPI Hub API
  |
  | creates/updates hub_documents records
  | records delivery/audit/workflow events
  | enriches with classification, matching, validation, status
  v
SharePoint Online
  |
  | PDF output
  | sent document copies
  | attachments
  | migrated Square9/Zetadocs archive files
  v
Business Central APIs
  |
  | read validation from Production
  | sandbox-only write experiments until go-live approval
```

## What the BC AL Extension Should Own

The AL extension should own only the BC-native experience and BC-local orchestration:

- Send via Document Delivery actions.
- BC report rendering to PDF.
- Email template selection and merge fields.
- Customer/vendor recipient routing.
- Delivery log capture.
- Native BC attachment event handling.
- SharePoint upload handoff or direct SharePoint upload where appropriate.
- FactBox visibility for linked attachments/documents.
- Optional event calls to GPI Hub after send/upload/link activity.

It should not become the intelligence engine.

## What GPI Hub Should Own

GPI Hub should own the durable intelligence and operational layer:

- Unified document records.
- Document classification.
- Square9/Zetadocs migration context.
- BC entity matching.
- Vendor/customer/PO/invoice validation.
- Duplicate detection.
- Workflow status and exception queues.
- Readiness scoring.
- Audit trail and observability.
- Human review workspace.
- Reporting dashboards.
- Safe BC API write-preflight and sandbox write workflows.

## SharePoint Storage Model

SharePoint should be treated as the durable document store, not just a temporary handoff location.

Recommended folder pattern:

```text
GPI Hub Documents/
  BC/
    Customer/{CustomerNo}/
      Sales Invoice/{Year}/{DocumentNo}/
      Credit Memo/{Year}/{DocumentNo}/
      Statement/{Year}/{DocumentNo}/
    Vendor/{VendorNo}/
      Purchase Order/{Year}/{DocumentNo}/
      Purchase Invoice/{Year}/{DocumentNo}/
  Intake/
    AP/{Year}/{Month}/
    Sales/{Year}/{Month}/
    Other/{Year}/{Month}/
  Legacy/
    Square9/{WorkflowName}/...
    Zetadocs/{SetCode}/...
```

Folder design should remain configurable. Do not hardcode final folder names until tested against actual AP, sales, and delivery use cases.

## Data Model Additions to Evaluate

Additive fields to evaluate for `hub_documents`:

```json
{
  "bc_source": {
    "company_id": "...",
    "environment": "Production|Sandbox_11_3_2025",
    "record_type": "Sales Invoice|Sales Order|Purchase Order|Customer|Vendor|Statement",
    "record_id": "...",
    "record_no": "...",
    "posted": true
  },
  "delivery": {
    "delivery_status": "draft|sent|failed|resent",
    "delivery_method": "bc_email|graph|smtp",
    "template_code": "...",
    "recipient_resolution_method": "specific|wildcard|master_record_fallback",
    "to": [],
    "cc": [],
    "bcc": [],
    "sent_at": "...",
    "sent_by": "...",
    "error": null
  },
  "sharepoint": {
    "site_id": "...",
    "drive_id": "...",
    "item_id": "...",
    "web_url": "...",
    "folder_path": "...",
    "storage_status": "pending|synced|failed"
  },
  "legacy_context": {
    "source_system": "SQUARE9|ZETADOCS|GPI_HUB_NATIVE|BC_NATIVE",
    "zetadocs_set_code": "...",
    "square9_workflow": "..."
  }
}
```

These should be added only after reviewing existing document models and route logic.

## Phase 0 - Branch Safety and Design Alignment

Status: started on this branch.

Tasks:

- Create isolated feature branch.
- Document architecture and guardrails.
- Review current backend routes and services.
- Identify minimum additive API surface for BC extension callbacks.
- Avoid code changes that affect AP smoke testing.

Acceptance criteria:

- Branch exists.
- Scope is documented.
- No existing AP code path has been changed.
- Next implementation slices are clearly defined.

## Phase 1 - GPI Hub API Surface for BC Document Events

Build additive backend endpoints only.

Candidate endpoints:

```text
POST /api/bc-document-events/delivery-sent
POST /api/bc-document-events/delivery-failed
POST /api/bc-document-events/attachment-linked
POST /api/bc-document-events/attachment-sync-failed
GET  /api/bc-document-events/{bcRecordType}/{bcRecordNo}
```

Purpose:

- Allow BC AL extension to notify GPI Hub about document sends and attachments.
- Create or update `hub_documents` records.
- Preserve audit history.
- Store SharePoint links and BC record context.
- Avoid any automatic BC writeback.

Acceptance criteria:

- Endpoints are additive.
- No AP review behavior changes.
- Mock/test payloads can create delivery/attachment event records.
- All events are traceable in MongoDB.

## Phase 2 - AL Extension Scaffold

Create a separate AL app folder, likely:

```text
bc-extension/document-delivery/
```

Initial objects:

- Document Delivery Setup
- Email Template
- Delivery Recipient
- Delivery Log
- Attachment Mirror table
- SharePoint Setup
- Document send codeunit
- Recipient resolution codeunit
- Template render codeunit
- SharePoint client codeunit
- GPI Hub client codeunit
- Page extensions for posted invoices, credit memos, sales orders, purchase orders, customer/vendor cards

Acceptance criteria:

- AL compiles in sandbox.
- No production deployment.
- Send actions can be tested side-by-side with existing BC behavior.
- GPI Hub callback can be disabled by setup toggle.

## Phase 3 - SharePoint Document Store Integration

Confirm whether SharePoint upload should be handled by:

1. AL extension directly through Microsoft Graph, or
2. GPI Hub API receiving file metadata/file stream and handling Graph upload.

Recommended default:

- BC renders/sends and reports the event.
- GPI Hub owns durable document intelligence record.
- SharePoint upload can begin in AL for native BC attachment workflows, but GPI Hub must receive the final SharePoint item metadata.

Acceptance criteria:

- SharePoint item metadata lands in `hub_documents`.
- File can be opened from GPI Hub.
- BC page can open the stored SharePoint item.
- Upload failures do not crash BC send/attach flow.

## Phase 4 - Square9/Zetadocs Parity Review

Map current legacy behavior to replacement behavior:

| Legacy Need | Replacement Owner |
| --- | --- |
| Send posted documents by email | BC AL Extension |
| Recipient routing | BC AL Extension, mirrored to GPI Hub |
| Delivery audit | BC AL Extension + GPI Hub |
| Drag/drop attachment UX | BC native Documents FactBox + AL subscriber |
| Archive/search | SharePoint + GPI Hub |
| Workflow queues | GPI Hub |
| AP validation/readiness | GPI Hub |
| BC linking | GPI Hub + BC API |
| Migration context | GPI Hub |

Acceptance criteria:

- Each current Zetadocs/Square9 use case has a replacement owner.
- Missing features become explicit backlog items.
- No duplicate system of record is created.

## Phase 5 - Controlled Pilot

Pilot in this order:

1. BC sandbox only.
2. One document type, likely posted sales invoice delivery.
3. One or two internal test customers/vendors.
4. SharePoint upload and GPI Hub event logging enabled.
5. No automated BC writes.
6. Expand to attachments after send/delivery flow is stable.

Acceptance criteria:

- Users can complete the same basic motion they use today.
- Delivery and attachment records appear in GPI Hub.
- SharePoint files are retrievable.
- Errors are visible and actionable.
- Nothing touches the AP smoke-test path.

## Immediate Next Work Items

1. Review backend route registration in `server.py` or `server_new.py`.
2. Review current document model shape in `routes/documents.py` and related services.
3. Identify the least invasive place to add BC document event ingestion.
4. Create backend route file for BC document events.
5. Add mock tests for event ingestion.
6. Only after backend event ingestion is stable, scaffold the AL extension.

## Working Principle

Do not start by replacing Zetadocs inside BC. Start by letting BC events become first-class GPI Hub document events. Once the event model is reliable, the native BC delivery extension can be added safely around it.
