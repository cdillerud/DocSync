# First Capability Design: Explain Invoice Exception

**Capability:** `explain_invoice_exception`

**Version:** `1.0`

**Class:** Knowledge

**Copilot exposure:** Yes, after security release gates are met

**Write access:** None

---

## 1. Objective

Provide a secure, read-only capability that explains why an AP invoice is blocked, pending review, or otherwise unable to continue through the GPI Hub workflow.

This is the recommended first Copilot Studio integration because it exercises the full platform path without introducing transaction risk:

```text
Employee
   ↓
Copilot Studio
   ↓
Entra-authenticated Hub capability
   ↓
Hub document and workflow records
   ↓
Business Central read validation, when needed
   ↓
Structured explanation with provenance
```

Example user questions:

- “Why did invoice 54192 fail?”
- “What is blocking the Uline invoice?”
- “Why is this invoice in BC validation failed?”
- “What does PO_VENDOR_MISMATCH mean for invoice 54192?”

---

## 2. Scope

Version 1.0 will:

- locate one AP invoice using an approved identifier;
- enforce AP record access;
- retrieve the current Hub workflow state;
- retrieve recorded validation and exception codes;
- retrieve related vendor and purchase-order facts when authorized;
- map internal exception codes to approved business explanations;
- return provenance and completeness information;
- return authorized next-action names as informational metadata;
- create an audit event.

Version 1.0 will not:

- change invoice data;
- resolve vendors;
- override validation;
- retry a workflow;
- create or post a Business Central invoice;
- approve or reject an invoice;
- expose raw OCR text or unrestricted document content;
- generate an action confirmation token.

---

## 3. Existing Hub Assets Reused

The capability should orchestrate existing Hub components rather than reimplement them.

Likely sources include:

- `hub_documents` for the invoice record;
- workflow history and workflow status stored on the document;
- AP review service data;
- deterministic exception codes and blocking codes;
- vendor aliases and resolved vendor fields;
- Business Central service or cache for related vendor and PO facts;
- SharePoint metadata for document-location provenance when useful.

The existing deterministic workflow engine remains authoritative for workflow state. The capability only explains the current state.

---

## 4. Capability Metadata

```json
{
  "name": "explain_invoice_exception",
  "version": "1.0",
  "class": "knowledge",
  "description": "Explain the current blocking or review exception for one AP invoice.",
  "required_roles": ["hub.ap.reader"],
  "record_scope": "ap_invoice",
  "data_classification": "confidential",
  "source_systems": ["gpi_hub", "business_central", "sharepoint"],
  "allowed_runtime_modes": [
    "development",
    "shadow",
    "pilot_read_only",
    "sandbox_actions",
    "production_read_only",
    "controlled_production_actions"
  ],
  "allowed_target_environments": [
    "hub",
    "bc_production_read",
    "bc_sandbox_read"
  ],
  "confirmation_required": false,
  "idempotency_required": false,
  "copilot_exposed": true,
  "audit_level": "standard"
}
```

---

## 5. Endpoint

```http
GET /api/v1/knowledge/invoices/{invoice_identifier}/exception
```

Optional query parameter:

```text
identifier_type=auto|hub_document_id|invoice_number|vendor_invoice_number
```

Default:

```text
identifier_type=auto
```

The `auto` mode must use deterministic resolution rules and must reject ambiguous matches.

---

## 6. Identifier Resolution

Resolution order for `identifier_type=auto`:

1. Exact Hub document ID.
2. Exact normalized vendor invoice number.
3. Exact normalized invoice number.
4. Exact Business Central document number already linked to the Hub document.

Fuzzy matching is not permitted in version 1.0.

If no record matches:

```text
RECORD_NOT_FOUND
```

If multiple authorized records match:

```text
AMBIGUOUS_MATCH
```

The error may return safe disambiguation fields such as vendor name, invoice date, and amount only when the user is authorized to view each candidate.

---

## 7. Authorization

Required role:

```text
hub.ap.reader
```

The user must also pass record-level AP scope.

Initial record-level policy may allow all AP readers to view all AP invoices if that matches current business practice. The policy must still be implemented as an explicit scope decision rather than omitted.

Future scope examples:

- assigned reviewer only;
- AP team membership;
- company or legal entity;
- department or cost-center restrictions;
- approver chain.

Unauthorized responses must not reveal whether the invoice exists.

---

## 8. Retrieval Flow

```text
1. Validate Entra token.
2. Build immutable identity context.
3. Resolve capability metadata.
4. Authorize capability use.
5. Validate runtime mode.
6. Resolve invoice identifier within authorized scope.
7. Read Hub document fields required for explanation.
8. Read workflow status and relevant workflow-history entries.
9. Read recorded extraction, validation, and exception results.
10. Resolve related vendor and PO identifiers.
11. Query Business Central only when required facts are absent or stale.
12. Normalize exception codes.
13. Build deterministic explanation data.
14. Calculate provenance and completeness.
15. Calculate allowed next-action names.
16. Write audit event.
17. Return typed response.
```

The capability may call an LLM only for optional wording after the deterministic data object exists. The initial implementation should use approved static explanation templates and require no LLM call.

---

## 9. Minimum Hub Fields

The capability should read only fields needed for its response.

Representative fields:

```text
id
doc_type
workflow_status
status
vendor_id
vendor_canonical
vendor_name
invoice_number_clean
invoice_date
amount_float
currency
po_number
bc_document_id
bc_document_number
bc_posting_status
blocking_codes
validation_results
workflow_history
classification_confidence
ai_extraction.confidence
sharepoint_web_url
created_utc
updated_utc
```

Actual field names must be verified during implementation against current documents.

A field adapter should normalize legacy variations rather than spreading fallback chains throughout the capability.

---

## 10. Exception Normalization

Create a central exception catalog.

Initial known codes include:

```text
VENDOR_NOT_FOUND
DUPLICATE_INVOICE
PO_NOT_FOUND
PO_VENDOR_MISMATCH
PO_NOT_RECEIVED
REMIT_MISMATCH
MISSING_KEY_FIELDS
MISSING_AMOUNT
MISSING_PO
STALE_CONTACT_EMAIL_SUSPECTED
NO_CONTACT_EMAIL_MATCH
```

Only invoice-relevant codes should be returned by this capability.

Catalog entry:

```json
{
  "code": "PO_VENDOR_MISMATCH",
  "title": "Purchase-order vendor mismatch",
  "description": "The vendor identified on the invoice does not match the vendor on the referenced purchase order.",
  "severity": "blocking",
  "category": "business_central_validation",
  "recommended_resolution_type": "manual_review",
  "recommended_resolution": "Verify the purchase-order number and vendor before continuing.",
  "safe_for_end_user": true
}
```

The catalog—not Copilot—defines the approved explanation and recommended resolution type.

Unknown internal codes must be represented safely:

```json
{
  "code": "UNRECOGNIZED_EXCEPTION",
  "description": "The invoice has an exception that requires AP review.",
  "severity": "blocking"
}
```

The original unknown code may be retained in restricted telemetry but should not automatically be exposed to general users.

---

## 11. Response Model

```json
{
  "success": true,
  "capability": {
    "name": "explain_invoice_exception",
    "version": "1.0"
  },
  "data": {
    "invoice": {
      "hub_document_id": "doc_...",
      "invoice_number": "54192",
      "vendor_invoice_number": "54192",
      "vendor": {
        "number": "V10000",
        "name": "Example Vendor"
      },
      "invoice_date": "2026-07-15",
      "amount": {
        "value": "5250.00",
        "currency": "USD"
      },
      "workflow_status": "bc_validation_failed",
      "workflow_status_description": "Business Central validation failed"
    },
    "summary": "The invoice is blocked because the vendor does not match the vendor on purchase order 30360297.",
    "exceptions": [
      {
        "code": "PO_VENDOR_MISMATCH",
        "title": "Purchase-order vendor mismatch",
        "description": "The vendor identified on the invoice does not match the vendor on the referenced purchase order.",
        "severity": "blocking",
        "category": "business_central_validation",
        "related_records": [
          {
            "type": "purchase_order",
            "number": "30360297"
          }
        ],
        "recommended_resolution": {
          "type": "manual_review",
          "description": "Verify the purchase-order number and vendor before continuing."
        }
      }
    ],
    "last_relevant_event": {
      "event": "on_bc_invalid",
      "timestamp": "2026-07-22T18:42:11Z"
    }
  },
  "provenance": {
    "sources": [
      {
        "system": "gpi_hub",
        "environment": "Production",
        "record_type": "document",
        "record_id": "doc_...",
        "retrieved_at": "2026-07-22T19:15:00Z",
        "access_mode": "live",
        "fields_used": [
          "workflow_status",
          "blocking_codes",
          "workflow_history"
        ]
      },
      {
        "system": "business_central",
        "environment": "Production",
        "record_type": "purchase_order",
        "record_id": "...",
        "record_number": "30360297",
        "retrieved_at": "2026-07-22T19:15:00Z",
        "access_mode": "live",
        "fields_used": [
          "number",
          "vendorNumber",
          "status"
        ]
      }
    ],
    "retrieved_at": "2026-07-22T19:15:00Z",
    "completeness": "complete"
  },
  "allowed_next_actions": [
    "request_document_review"
  ],
  "warnings": [],
  "correlation_id": "...",
  "operation_id": null
}
```

---

## 12. Summary Generation

Version 1.0 summary text should be deterministic.

Template examples:

```text
The invoice is blocked because {exception_description}.
```

```text
The invoice has {count} blocking exceptions: {exception_titles}.
```

```text
The invoice is waiting for AP review because {exception_description}.
```

Do not send invoice data to an LLM merely to construct one sentence.

Copilot Studio may paraphrase the structured response, but the exact exception list and sources must remain available.

---

## 13. Business Central Read Strategy

The capability should prefer existing validated Hub data when it is current and sufficient.

A Business Central live read is appropriate when:

- a related PO fact is missing;
- cached source data exceeds an approved freshness threshold;
- the current PO/vendor relationship is needed to explain the exception;
- the user requests the current status and the capability contract promises current data.

The BC adapter must explicitly use a read-only Production or Sandbox operation class.

The capability must never inherit a general-purpose BC client that can write merely because the specific method performs a GET.

---

## 14. Completeness Rules

Return `complete` when:

- the Hub invoice is resolved;
- workflow and exception information is available;
- all facts required for the explanation are available;
- required source calls succeed.

Return `partial` when:

- the core exception is known but a supporting source is unavailable;
- a related PO or vendor lookup fails but the stored validation code remains explainable;
- provenance timestamps are incomplete.

Return `unavailable` only when the capability cannot produce a reliable explanation.

A partial response must include a warning.

Example:

```json
{
  "code": "BC_SOURCE_UNAVAILABLE",
  "message": "The stored exception is shown, but current Business Central details could not be retrieved."
}
```

---

## 15. Allowed Next Actions

Version 1.0 may return action names that are both contextually relevant and currently authorized.

Initial candidates:

- `request_document_review`
- `open_invoice_in_hub`

Do not return:

- `override_bc_validation`
- `post_invoice`
- `approve_payment`
- `change_vendor`

until those actions have their own registered capability, authorization model, confirmation flow, and production release approval.

The client must not treat `allowed_next_actions` as proof of authorization at execution time.

---

## 16. Error Cases

### Authentication or authorization

- `AUTHENTICATION_REQUIRED`
- `TOKEN_INVALID`
- `CAPABILITY_FORBIDDEN`
- `RECORD_ACCESS_FORBIDDEN`

### Identifier resolution

- `REQUEST_INVALID`
- `RECORD_NOT_FOUND`
- `AMBIGUOUS_MATCH`

### Source and domain

- `SOURCE_UNAVAILABLE`
- `SOURCE_TIMEOUT`
- `SOURCE_RESPONSE_INVALID`
- `BUSINESS_RULE_FAILED`
- `INTERNAL_ERROR`

The capability must not return stack traces, MongoDB filters, BC endpoint URLs containing tenant details, tokens, or raw source errors.

---

## 17. Audit Event

Each invocation records:

```json
{
  "capability_name": "explain_invoice_exception",
  "capability_version": "1.0",
  "capability_class": "knowledge",
  "identity": {},
  "authorization": {
    "result": "allowed",
    "record_scope": "ap_invoice"
  },
  "runtime": {
    "mode": "production_read_only",
    "target_systems": ["gpi_hub", "business_central"],
    "target_environments": ["Production"]
  },
  "request_summary": {
    "identifier_type": "invoice_number"
  },
  "record_ids": ["doc_..."],
  "outcome": "success",
  "duration_ms": 421,
  "error_code": null
}
```

The raw invoice number may be stored in the record identifier set if approved. Full invoice content must not be stored in the audit event.

---

## 18. Suggested Internal Models

```python
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class ExceptionSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class Money(BaseModel):
    value: Decimal
    currency: str = Field(min_length=3, max_length=3)


class RelatedRecord(BaseModel):
    type: str
    number: str | None = None
    record_id: str | None = None


class RecommendedResolution(BaseModel):
    type: str
    description: str


class InvoiceException(BaseModel):
    code: str
    title: str
    description: str
    severity: ExceptionSeverity
    category: str
    related_records: list[RelatedRecord] = []
    recommended_resolution: RecommendedResolution | None = None


class ExplainInvoiceExceptionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice: dict
    summary: str
    exceptions: list[InvoiceException]
    last_relevant_event: dict | None = None
```

Implementation should replace generic `dict` fields with typed nested models before release.

---

## 19. Suggested Components

```text
backend/app/
├── capabilities/
│   ├── registry.py
│   └── knowledge/
│       └── explain_invoice_exception.py
├── domains/ap/
│   ├── invoice_repository.py
│   ├── invoice_field_adapter.py
│   ├── exception_catalog.py
│   └── authorization.py
├── integrations/business_central/
│   └── read_client.py
├── audit/
│   └── service.py
└── api/v1/
    └── knowledge.py
```

---

## 20. Test Plan

### Unit tests

- exact document ID resolution;
- exact invoice-number resolution;
- normalization of invoice identifiers;
- exception-code mapping;
- unknown exception behavior;
- deterministic summary templates;
- completeness calculation;
- field adapter handling of legacy field variations.

### Authorization tests

- valid AP reader allowed;
- authenticated non-AP user denied;
- record outside scope denied;
- unauthorized response does not confirm record existence;
- service identity without delegated user rejected for Copilot route.

### Integration tests

- Hub-only exception response;
- Hub plus live/mock BC PO retrieval;
- BC unavailable returns partial response when safe;
- ambiguous identifier rejected;
- provenance contains correct sources;
- audit event created for success;
- audit event created for denial;
- correlation ID propagated.

### Security tests

- malicious invoice text cannot change capability behavior;
- unknown request fields rejected where required;
- raw source exceptions are not returned;
- tokens and secrets do not appear in logs;
- capability cannot call BC write methods.

### Contract tests

- OpenAPI schema matches response model;
- Copilot custom connector can invoke endpoint;
- response remains stable across representative exceptions.

---

## 21. Acceptance Criteria

The capability is ready for a limited Copilot pilot when:

1. Entra authentication is active on the endpoint.
2. `admin/admin` is not accepted on the capability API.
3. AP role and record-scope authorization are enforced.
4. The endpoint performs no writes.
5. BC access is through an explicitly read-only adapter.
6. Known exception codes use the approved catalog.
7. Unknown codes fail safely.
8. Every response includes provenance and a correlation ID.
9. Every invocation creates an audit event.
10. Unauthorized requests do not reveal invoice existence.
11. Unit, integration, authorization, security, and contract tests pass.
12. Copilot Studio presents the response without inventing a different exception or unsupported resolution.

---

## 22. Recommended Delivery Sequence

### Step 1

Create the exception catalog and invoice field adapter without exposing a new route.

### Step 2

Implement the capability service and tests using a synthetic identity context.

### Step 3

Implement Entra token validation and Hub role mapping.

### Step 4

Add the `/api/v1` route and audit service.

### Step 5

Add provenance and optional BC read enrichment.

### Step 6

Publish the endpoint through an OpenAPI definition to a development Copilot Studio agent.

### Step 7

Run a limited AP/IT pilot using non-sensitive test invoices and then approved production-read data.

---

## 23. Architectural Outcome

This vertical slice proves the complete GPI Hub enterprise pattern:

```text
Natural-language request
        ↓
Typed capability selection
        ↓
Validated user identity
        ↓
Capability and record authorization
        ↓
Deterministic Hub business logic
        ↓
Read-only source retrieval
        ↓
Structured facts and provenance
        ↓
Audited conversational explanation
```

Once this pattern is proven, additional knowledge capabilities can reuse the same identity, policy, audit, provenance, and Copilot integration layers.
