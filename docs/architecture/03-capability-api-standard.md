# GPI Hub Capability API Standard

**Status:** Draft

**Purpose:** Define the mandatory contract for every GPI Hub capability exposed to the React application, Copilot Studio, internal automation, or future clients.

---

## 1. Core Rule

Every operation exposed by GPI Hub must be implemented as a named, typed capability.

A capability is not merely an HTTP route. It is a governed unit of business access with:

- a stable name and version;
- an explicit purpose;
- defined inputs and outputs;
- identity and authorization requirements;
- source-system boundaries;
- environment restrictions;
- audit requirements;
- deterministic error behavior;
- data-classification metadata;
- optional confirmation requirements.

Copilot Studio may select and invoke capabilities. It may not invent capabilities, bypass capability policy, or call source systems directly when a Hub capability exists.

---

## 2. Capability Classes

### 2.1 Knowledge capabilities

Read-only operations that retrieve, correlate, explain, or summarize information.

Examples:

- `explain_invoice_exception`
- `search_purchase_orders`
- `get_vendor_context`
- `search_helpdesk_tickets`
- `get_customer_summary`

Knowledge capabilities must not mutate Hub state except for append-only telemetry and audit records.

### 2.2 Action capabilities

Operations that create or change state in the Hub or an external system.

Examples:

- `create_helpdesk_ticket`
- `retry_document_workflow`
- `request_document_review`
- `create_purchase_invoice_draft`
- `attach_document_to_bc_record`

Action capabilities must declare whether they are:

- Hub-only;
- sandbox-only;
- production-read-plus-Hub-write;
- controlled production write.

### 2.3 Administrative capabilities

Restricted operations for configuration, migration, diagnostics, or security administration.

Administrative capabilities must never be exposed to general-purpose Copilot agents.

### 2.4 Background capabilities

Operations initiated by schedulers, polling loops, webhooks, or event handlers.

Background capabilities use service identity but must still pass through the same runtime policy, environment restrictions, idempotency, and audit controls as user-triggered capabilities.

---

## 3. Naming and Versioning

Capability names use lowercase snake case.

Examples:

```text
explain_invoice_exception
search_purchase_orders
create_purchase_invoice_draft
```

Each capability has an independent semantic version.

```json
{
  "name": "explain_invoice_exception",
  "version": "1.0"
}
```

Backward-compatible response additions may remain within the same major version. Breaking input or output changes require a new major version.

HTTP routes are versioned separately at the platform level:

```text
/api/v1/capabilities/...
```

The capability version must also appear in audit records and responses.

---

## 4. Capability Definition Schema

Every capability must be registered using metadata equivalent to the following:

```json
{
  "name": "explain_invoice_exception",
  "version": "1.0",
  "class": "knowledge",
  "description": "Explain the current validation or workflow exception for an AP invoice.",
  "required_roles": ["hub.ap.reader"],
  "record_scope": "ap_invoice",
  "data_classification": "confidential",
  "source_systems": ["gpi_hub", "business_central"],
  "allowed_runtime_modes": [
    "development",
    "shadow",
    "pilot_read_only",
    "sandbox_actions",
    "production_read_only",
    "controlled_production_actions"
  ],
  "allowed_target_environments": ["hub", "bc_production_read"],
  "confirmation_required": false,
  "idempotency_required": false,
  "copilot_exposed": true,
  "audit_level": "standard"
}
```

Capability metadata must be reviewable without reading implementation code.

---

## 5. Request Contract

### 5.1 Required HTTP headers

Every authenticated request must support:

```text
Authorization: Bearer <Entra access token>
X-Correlation-ID: <client-generated UUID, optional>
X-Conversation-ID: <conversation identifier, optional>
X-Client-Application: <registered client name>
Idempotency-Key: <required for designated actions>
```

If `X-Correlation-ID` is absent, the Hub generates one.

The Hub must not trust user identity supplied in a request body or ordinary custom header.

### 5.2 Request envelope

Typed capability endpoints may accept domain-specific request bodies, but all requests are normalized internally to:

```json
{
  "capability": {
    "name": "search_purchase_orders",
    "version": "1.0"
  },
  "parameters": {
    "vendor_name": "Uline",
    "minimum_amount": 5000,
    "status": ["Open"]
  },
  "client_context": {
    "locale": "en-US",
    "time_zone": "America/Chicago"
  }
}
```

The `parameters` object must be validated by a capability-specific Pydantic model.

Unknown fields should be rejected by default for action capabilities. Knowledge capabilities may allow carefully controlled forward-compatible fields when necessary.

### 5.3 Pagination

Search capabilities use cursor-based pagination where practical.

```json
{
  "limit": 25,
  "cursor": "opaque-value"
}
```

Responses return:

```json
{
  "page": {
    "limit": 25,
    "next_cursor": "opaque-value-or-null",
    "has_more": true
  }
}
```

Clients must not construct or interpret cursor values.

### 5.4 Date and time

All API timestamps use ISO 8601 in UTC.

```text
2026-07-22T19:15:00Z
```

User-local dates may be accepted only when accompanied by a time zone or when the capability explicitly documents date-only semantics.

### 5.5 Monetary values

Money must be represented with explicit currency and decimal-safe values.

```json
{
  "amount": "5250.00",
  "currency": "USD"
}
```

Floating-point values must not be used for authoritative accounting amounts.

---

## 6. Identity Context

After Entra token validation, the Hub creates an immutable request identity context.

```json
{
  "tenant_id": "...",
  "subject_id": "...",
  "user_principal_name": "user@gamerpackaging.com",
  "display_name": "Example User",
  "authentication_type": "delegated",
  "roles": ["hub.ap.reader"],
  "groups": ["..."],
  "client_application": "copilot-studio-gpi-hub",
  "correlation_id": "...",
  "conversation_id": "..."
}
```

Service-initiated requests use a service identity context with no impersonated user unless a separately validated delegated-user assertion is present.

Authorization decisions must use the validated identity context, capability policy, and record scope.

---

## 7. Authorization Contract

Authorization occurs in this order:

1. Validate token and tenant.
2. Validate client application.
3. Resolve Hub roles.
4. Verify capability permission.
5. Verify runtime mode.
6. Verify target environment.
7. Apply record-level scope.
8. Apply field-level filtering where required.
9. Record the authorization result.

A capability-level role does not automatically grant access to every record returned by the source system.

Unauthorized responses must not reveal whether a protected record exists.

---

## 8. Standard Success Response

All capabilities return a common outer envelope.

```json
{
  "success": true,
  "capability": {
    "name": "explain_invoice_exception",
    "version": "1.0"
  },
  "data": {},
  "provenance": {
    "sources": [],
    "retrieved_at": "2026-07-22T19:15:00Z",
    "completeness": "complete"
  },
  "allowed_next_actions": [],
  "warnings": [],
  "correlation_id": "...",
  "operation_id": null
}
```

### 8.1 `data`

Contains the typed capability result. It must not contain unrestricted source-system payloads unless the capability specifically requires them.

### 8.2 `provenance`

Identifies the records and systems used to produce the result.

### 8.3 `allowed_next_actions`

Contains only actions the current identity is authorized to request for the returned context.

This field is advisory for the client. The Action Service must reauthorize every action request.

### 8.4 `warnings`

Contains non-fatal conditions such as stale cache data, partial source availability, truncated result sets, or low-confidence entity resolution.

---

## 9. Provenance Standard

Each factual source used by a capability should be represented as:

```json
{
  "system": "business_central",
  "environment": "Production",
  "record_type": "purchase_order",
  "record_id": "...",
  "record_number": "30360297",
  "retrieved_at": "2026-07-22T19:15:00Z",
  "source_updated_at": "2026-07-22T18:42:11Z",
  "access_mode": "live",
  "fields_used": ["number", "vendorNumber", "status"]
}
```

Allowed `access_mode` values:

- `live`
- `cache`
- `snapshot`
- `derived`

Derived facts must identify their supporting sources.

A language model may summarize capability data, but the Hub response must preserve factual provenance independently of the generated wording.

---

## 10. Completeness and Confidence

The Hub must distinguish between source completeness and AI confidence.

### 10.1 Completeness

Allowed values:

- `complete`
- `partial`
- `unavailable`

### 10.2 Entity-resolution confidence

Used when matching names, email addresses, vendors, customers, or related records.

```json
{
  "match": {
    "status": "matched",
    "confidence": 0.94,
    "method": "exact_email"
  }
}
```

### 10.3 AI-generated confidence

AI confidence may be included as decision-support metadata but must never be used as a substitute for deterministic authorization, accounting validation, or write eligibility.

---

## 11. Standard Error Response

All errors use a stable envelope.

```json
{
  "success": false,
  "error": {
    "code": "CAPABILITY_FORBIDDEN",
    "message": "You are not authorized to use this capability.",
    "category": "authorization",
    "retryable": false,
    "details": {}
  },
  "capability": {
    "name": "explain_invoice_exception",
    "version": "1.0"
  },
  "correlation_id": "..."
}
```

Public error messages must be safe for display. Sensitive diagnostics remain in server-side logs associated with the correlation ID.

### 11.1 Standard error codes

#### Authentication and authorization

- `AUTHENTICATION_REQUIRED`
- `TOKEN_INVALID`
- `TENANT_NOT_ALLOWED`
- `CLIENT_NOT_ALLOWED`
- `CAPABILITY_FORBIDDEN`
- `RECORD_ACCESS_FORBIDDEN`

#### Validation

- `REQUEST_INVALID`
- `PARAMETER_INVALID`
- `CONFIRMATION_REQUIRED`
- `CONFIRMATION_INVALID`
- `CONFIRMATION_EXPIRED`
- `IDEMPOTENCY_KEY_REQUIRED`

#### Runtime policy

- `RUNTIME_MODE_BLOCKED`
- `TARGET_ENVIRONMENT_BLOCKED`
- `PRODUCTION_WRITE_BLOCKED`
- `FEATURE_NOT_AVAILABLE`

#### Domain and source systems

- `RECORD_NOT_FOUND`
- `AMBIGUOUS_MATCH`
- `SOURCE_UNAVAILABLE`
- `SOURCE_TIMEOUT`
- `SOURCE_RESPONSE_INVALID`
- `WORKFLOW_TRANSITION_INVALID`
- `BUSINESS_RULE_FAILED`

#### General

- `RATE_LIMITED`
- `OPERATION_CONFLICT`
- `INTERNAL_ERROR`

---

## 12. Action Preview and Confirmation Contract

Controlled actions use two stages.

### 12.1 Preview

```http
POST /api/v1/actions/create-purchase-invoice-draft/preview
```

Preview performs:

- authentication;
- authorization;
- business validation;
- target-environment resolution;
- source-record retrieval;
- proposed-change generation;
- duplicate and conflict detection.

Preview must not execute the external write.

Response:

```json
{
  "success": true,
  "capability": {
    "name": "create_purchase_invoice_draft",
    "version": "1.0"
  },
  "data": {
    "proposed_changes": {},
    "target": {
      "system": "business_central",
      "environment": "Sandbox_11_3_2025"
    },
    "validation": {
      "eligible": true,
      "checks": []
    },
    "confirmation": {
      "token": "opaque-single-use-token",
      "expires_at": "2026-07-22T19:20:00Z",
      "summary": "Create a purchase invoice draft for vendor V10000."
    }
  },
  "correlation_id": "..."
}
```

### 12.2 Execute

```http
POST /api/v1/actions/create-purchase-invoice-draft/execute
```

```json
{
  "confirmation_token": "opaque-single-use-token"
}
```

Execution must verify:

- the token signature;
- requesting identity matches preview identity;
- capability and version match;
- token has not expired or been used;
- source records have not changed materially;
- target environment remains allowed;
- runtime policy still allows the action;
- idempotency requirements are met.

Any failed check aborts the action.

---

## 13. Idempotency

Every externally mutating action must support idempotency.

The client supplies:

```text
Idempotency-Key: <unique value>
```

The Hub stores the key with:

- capability name and version;
- authenticated identity;
- normalized request hash;
- operation state;
- resulting external identifiers;
- expiration policy.

Repeating the same request returns the original result. Reusing a key with a different request returns `OPERATION_CONFLICT`.

---

## 14. Long-Running Operations

Capabilities that cannot complete within the normal request window return an operation resource.

```json
{
  "success": true,
  "operation_id": "op_...",
  "data": {
    "status": "accepted"
  },
  "correlation_id": "..."
}
```

Status endpoint:

```http
GET /api/v1/operations/{operation_id}
```

Allowed states:

- `accepted`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Copilot-facing actions should prefer short, bounded operations. Long-running tasks must not cause the conversational client to retry the mutation blindly.

---

## 15. Audit Contract

Every capability invocation generates an audit event, whether allowed, denied, successful, or failed.

Minimum fields:

```json
{
  "event_id": "...",
  "timestamp": "...",
  "correlation_id": "...",
  "conversation_id": "...",
  "operation_id": "...",
  "capability_name": "...",
  "capability_version": "...",
  "capability_class": "knowledge",
  "identity": {
    "subject_id": "...",
    "user_principal_name": "...",
    "client_application": "..."
  },
  "authorization": {
    "result": "allowed",
    "roles_evaluated": [],
    "record_scope": "..."
  },
  "runtime": {
    "mode": "production_read_only",
    "target_system": "business_central",
    "target_environment": "Production"
  },
  "request_summary": {},
  "record_ids": [],
  "outcome": "success",
  "duration_ms": 421,
  "error_code": null
}
```

Do not store raw secrets, access tokens, complete email bodies, complete document OCR text, or unrestricted prompts in standard audit events.

---

## 16. Logging and Telemetry

Application logs must be structured and include:

- timestamp;
- severity;
- service and module;
- correlation ID;
- operation ID when present;
- capability name;
- safe error code;
- duration;
- source-system dependency timing.

Logs must redact:

- bearer tokens;
- client secrets;
- confirmation tokens;
- document contents;
- sensitive personal information unless explicitly approved.

Metrics should include:

- invocation count by capability;
- success and failure rates;
- authorization denials;
- source-system latency;
- retries;
- rate-limit events;
- LLM usage and cost where applicable;
- preview-to-execute conversion for actions.

---

## 17. Copilot Exposure Rules

A capability may be marked `copilot_exposed: true` only when:

- its inputs and outputs are fully typed;
- authentication and authorization tests exist;
- error codes are stable;
- provenance is returned;
- prompt-derived text cannot control authorization or target environment;
- all write paths use required confirmation and idempotency;
- audit events are verified;
- production behavior is documented;
- a capability owner is assigned.

Copilot descriptions must clearly state when a capability is read-only, sandbox-only, or requires confirmation.

Tool descriptions must not imply permissions the caller may not possess.

---

## 18. Prompt-Injection Boundary

Text retrieved from documents, email, meetings, SharePoint, or external systems is untrusted data.

Capabilities must never interpret retrieved text as instructions to:

- invoke another capability;
- change target environment;
- disclose credentials;
- bypass authorization;
- alter workflow state;
- execute a write;
- ignore policy.

The Hub returns structured records. The conversational layer may summarize them, but tool invocation decisions remain governed by registered capability policy and authenticated user intent.

---

## 19. Initial Endpoint Pattern

The first read-only capability should use a narrow endpoint:

```http
GET /api/v1/knowledge/invoices/{invoice_identifier}/exception
```

Equivalent capability:

```text
explain_invoice_exception v1.0
```

Expected response data:

```json
{
  "invoice": {
    "hub_document_id": "...",
    "invoice_number": "...",
    "vendor_number": "...",
    "vendor_name": "...",
    "workflow_status": "bc_validation_failed"
  },
  "exceptions": [
    {
      "code": "PO_VENDOR_MISMATCH",
      "description": "The invoice vendor does not match the purchase-order vendor.",
      "severity": "blocking",
      "related_records": []
    }
  ],
  "recommended_resolution": {
    "type": "manual_review",
    "explanation": "Verify the vendor and purchase-order relationship before continuing."
  }
}
```

No write action is included in version 1.0.

---

## 20. Implementation Guidance

Recommended internal structure:

```text
backend/app/
├── capabilities/
│   ├── registry.py
│   ├── models.py
│   ├── executor.py
│   ├── knowledge/
│   │   └── explain_invoice_exception.py
│   └── actions/
├── core/
│   ├── identity.py
│   ├── authorization.py
│   ├── runtime_policy.py
│   ├── idempotency.py
│   └── telemetry.py
├── audit/
│   ├── models.py
│   └── repository.py
└── api/v1/
    ├── knowledge.py
    ├── actions.py
    └── operations.py
```

The capability executor should be the common entry point for React, Copilot, internal API clients, and background services.

---

## 21. Definition of Done for a Capability

A capability is complete only when all of the following exist:

- registered metadata;
- typed input model;
- typed output model;
- identity validation;
- capability authorization;
- record-level authorization;
- runtime-policy validation;
- deterministic business logic;
- provenance generation;
- audit event generation;
- stable error mapping;
- unit tests;
- authorization tests;
- integration tests;
- OpenAPI documentation;
- operational metrics;
- owner and support notes;
- Copilot exposure review, when applicable.

---

## 22. Architectural Decision

GPI Hub will expose business capabilities, not raw source-system APIs.

The platform will prefer a small number of secure, domain-oriented capabilities over broad generic endpoints. This approach provides predictable authorization, better testing, clearer Copilot behavior, stronger auditability, and safer evolution toward controlled actions.
