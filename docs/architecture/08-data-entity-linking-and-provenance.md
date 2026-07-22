# GPI Hub Data, Entity-Linking, and Provenance Architecture

## Purpose

Define how GPI Hub connects records across Business Central, SharePoint, Spiro, Fathom, Help Desk, Exchange, and MongoDB without replacing the source systems that own those records.

The Hub provides a canonical cross-system identity layer, relationship graph, source snapshots, and field-level provenance.

## Core principle

A canonical entity is a Hub identity, not a new system of record.

Business Central continues to own ERP facts. SharePoint owns governed document binaries and metadata. Spiro owns CRM records. Fathom owns meeting recordings and transcripts. The Help Desk owns tickets. The Hub owns links, workflow context, derived explanations, and orchestration state.

## Canonical entity types

Initial entity types:

- organization
- person
- customer
- vendor
- item
- purchase_order
- sales_order
- purchase_invoice
- sales_invoice
- shipment
- document
- meeting
- help_desk_ticket
- crm_activity
- mailbox_message

Each canonical entity receives a stable Hub identifier such as `ent_vendor_<uuid>`.

## Source references

A source reference identifies one record in one source system and environment.

Required fields:

```json
{
  "source_system": "business_central",
  "environment": "production",
  "tenant": "gamerpackaging",
  "company": "Gamer Packaging, Inc.",
  "record_type": "vendor",
  "source_id": "<BC systemId>",
  "business_key": "V001234",
  "web_url": null
}
```

The tuple of source system, environment, company or partition, record type, and source ID must be unique.

## Canonical entity collection

Proposed collection: `entities`

```json
{
  "entity_id": "ent_vendor_...",
  "entity_type": "vendor",
  "display_name": "Example Vendor",
  "status": "active",
  "source_refs": [],
  "attributes": {},
  "created_utc": "...",
  "updated_utc": "..."
}
```

The `attributes` section contains only normalized convenience values. Every material value must retain provenance.

## Entity-link collection

Proposed collection: `entity_links`

```json
{
  "link_id": "lnk_...",
  "from_entity_id": "ent_invoice_...",
  "relationship": "references_purchase_order",
  "to_entity_id": "ent_po_...",
  "status": "confirmed",
  "method": "exact_business_key",
  "confidence": 1.0,
  "evidence": [],
  "approved_by": null,
  "created_utc": "..."
}
```

Supported link status values:

- proposed
- confirmed
- rejected
- superseded

AI may propose a link. It may not mark a link confirmed unless an approved deterministic rule allows it.

## Match methods

Preferred matching order:

1. Exact immutable source identifier
2. Existing confirmed alias or override
3. Exact normalized business key
4. Exact email address
5. Approved domain alias
6. Deterministic composite match
7. Fuzzy candidate requiring review

Examples of deterministic composite evidence:

- vendor number plus company
- invoice number plus vendor plus amount
- PO number plus vendor
- meeting attendee email plus confirmed Spiro contact

## Confidence is not authorization

A high confidence score does not permit a write, merge, or confirmed relationship by itself.

The match method, evidence, policy, and review state determine what the Hub may do.

## Alias and override records

Use explicit collections for reviewed exceptions:

- `entity_aliases`
- `domain_aliases`
- `source_overrides`

Every override must include scope, reason, approver, effective date, and optional expiration.

A domain alias must never silently override an exact-email mismatch.

## Source snapshots

Proposed collection: `source_snapshots`

Snapshots provide traceability for capability results and protect against source changes after a response is generated.

```json
{
  "snapshot_id": "snap_...",
  "entity_id": "ent_invoice_...",
  "source_ref": {},
  "retrieved_utc": "...",
  "source_modified_utc": "...",
  "etag": "...",
  "schema_version": "1.0",
  "payload_hash": "sha256:...",
  "selected_fields": {},
  "expires_utc": "..."
}
```

Do not store full sensitive payloads when selected fields are sufficient.

## Field-level provenance

Capability responses must identify the source of material facts.

```json
{
  "field": "invoice.total_amount",
  "value": 1250.00,
  "source_system": "business_central",
  "source_ref": {},
  "retrieved_utc": "...",
  "snapshot_id": "snap_..."
}
```

Derived fields must list all inputs and the deterministic rule or model version that produced the result.

## Source ownership matrix

| Fact | Authoritative source |
|---|---|
| Vendor and customer master | Business Central |
| Orders, invoices, shipments, item ledger | Business Central |
| Original document binary | SharePoint after governed storage |
| Hub workflow state and exception history | GPI Hub |
| CRM company, contact, activity | Spiro |
| Meeting recording and transcript | Fathom |
| Support ticket and ticket status | GPI Help Desk |
| User identity and groups | Microsoft Entra ID |
| Cross-system links and reviewed aliases | GPI Hub |

## Document identity

A document entity is separate from the business transaction it supports.

One purchase invoice may have multiple document entities: original invoice, corrected invoice, email attachment, approval evidence, and posting copy.

The relationship graph must express this explicitly rather than embedding all files into one transaction record.

## Entity resolution workflow

```text
Source record received
      ↓
Normalize identifiers
      ↓
Check existing source reference
      ↓
Run deterministic match rules
      ↓
Confirmed match OR proposed candidates OR new entity
      ↓
Persist evidence and audit event
```

Ambiguous matches go to an exception queue. They do not silently select the highest score.

## Temporal behavior

Source facts change over time. The Hub must distinguish:

- current source value
- value observed at capability execution time
- historical workflow value
- derived value

Capability results should include `as_of_utc` and freshness information.

## Deletion and retention

Deleting a source record does not automatically delete its Hub audit history.

The Hub should retain minimal tombstone metadata when required for traceability, subject to legal, privacy, and retention policy.

Sensitive snapshots must have explicit retention classes.

## Search architecture

Search indexes may contain normalized copies for discovery, but search results must point back to authoritative source references.

An index hit is not itself proof of the current source value.

For high-impact facts, the capability should perform a live or policy-approved cached lookup before responding.

## Copilot behavior

Copilot receives resolved entities and provenance from the Hub. It must not independently infer that two records belong to the same organization or transaction.

When resolution is ambiguous, Copilot should present the candidates returned by the Hub and ask the user to choose.

## Initial implementation order

1. Define `SourceRef`, `CanonicalEntity`, `EntityLink`, and `ProvenanceRecord` models.
2. Create unique indexes for source references.
3. Add entity IDs to existing Hub documents without removing legacy keys.
4. Implement deterministic links for AP invoice to vendor, PO, and SharePoint document.
5. Add provenance to `explain_invoice_exception`.
6. Add an entity-link review queue.
7. Extend to Spiro contacts and Fathom meetings.

## Acceptance criteria

- No canonical entity replaces a source of record.
- Every cross-system link records method and evidence.
- Ambiguous links remain proposed.
- Material capability facts include provenance.
- Production and sandbox source references cannot collide.
- The first invoice-exception capability can identify its invoice, vendor, PO, document, and source freshness.