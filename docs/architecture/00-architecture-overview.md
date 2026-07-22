# GPI Hub Enterprise Platform Architecture

**Status:** Initial draft  
**Branch:** `architecture/copilot-platform`  
**Planning horizon:** 18 months

## Purpose

GPI Hub will evolve from a document workflow application into Gamer Packaging's secure enterprise information and action platform.

The Hub remains the authoritative integration boundary. Microsoft Copilot Studio provides a conversational interface, but it does not own GPI business rules, authorization, workflow transitions, or source-system credentials.

## Target relationship

```text
Employee
   |
Microsoft Teams / Microsoft 365
   |
Copilot Studio Agent
   |
GPI Hub API
   |-- Knowledge capabilities
   |-- Context capabilities
   |-- Action capabilities
   |-- Workflow engine
   |-- Authorization and audit
   |
   |-- Business Central
   |-- SharePoint / Microsoft Graph
   |-- MongoDB
   |-- GPI Help Desk
   |-- Spiro
   |-- Fathom
   `-- Future systems
```

## Current foundation

The repository already contains the principal building blocks:

- FastAPI backend and React frontend
- MongoDB persistence
- SharePoint and Microsoft Graph integration
- Business Central integration
- AP and sales workflows
- Email ingestion
- AI classification and extraction
- Spiro integration
- Deterministic workflow state transitions
- Pilot, simulation, and production-write controls
- Existing backend refactor plan and route modules

The target architecture therefore evolves the existing modular monolith rather than replacing it.

## Architectural principles

1. **The Hub owns business logic.** Copilot may interpret user intent and present results; Hub services validate and execute operations.
2. **Source systems remain authoritative.** Business Central owns transactions, SharePoint owns documents, Entra owns identity, and MongoDB owns Hub workflow state.
3. **Identity is propagated end to end.** Every user-triggered request carries a validated Entra identity and Hub authorization context.
4. **Retrieval and actions are separate.** Read-only knowledge capabilities may be invoked automatically; write capabilities require additional authorization and usually preview and confirmation.
5. **AI is not the source of truth.** Responses include source records, timestamps, and provenance.
6. **Production writes are deny-by-default.** Environment policy is enforced in the Hub adapter layer, not by prompts or Copilot configuration.
7. **Every operation is observable.** Capability use, authorization decisions, source queries, confirmations, outcomes, and errors are audited.
8. **Typed capabilities come before a general `/ask` endpoint.** Narrow APIs are easier to secure, test, govern, and expose to Copilot Studio.

## Logical services

### Knowledge Service

Retrieves trusted information from Hub records and connected systems.

Initial examples:

- Search documents
- Locate an invoice
- Explain an invoice exception
- Search purchase orders
- Search sales orders
- Search Help Desk tickets
- Search knowledge-base articles

### Context Service

Builds a bounded 360-degree view of a business entity by combining permitted data from multiple systems.

Initial entities:

- Customer
- Vendor
- Invoice
- Purchase order
- Sales order
- Employee
- Device

### Action Service

Executes controlled operations through a consistent lifecycle:

```text
Requested -> Authenticated -> Authorized -> Validated -> Previewed
          -> Confirmed -> Executed -> Verified -> Audited
```

Initial low-risk actions may include:

- Create a Help Desk ticket
- Request document review
- Retry an eligible Hub workflow
- Send an internal notification
- Create a Business Central sandbox draft

### Workflow Service

Uses the existing deterministic workflow engine. Conversational actions raise workflow events rather than directly changing workflow status fields.

### Authorization Service

Maps Entra users and groups to Hub roles and enforces both capability-level and record-level access.

### Audit Service

Stores append-only events for user identity, capability, authorization decision, systems queried, records affected, confirmation, result, and correlation identifiers.

## API direction

A versioned capability API will be introduced alongside existing routes:

```text
/api/v1/me
/api/v1/capabilities

/api/v1/knowledge/documents/search
/api/v1/knowledge/invoices/{id}/exception
/api/v1/knowledge/purchase-orders/search
/api/v1/knowledge/sales-orders/search

/api/v1/context/customers/{id}
/api/v1/context/vendors/{id}

/api/v1/actions/{action}/preview
/api/v1/actions/{action}/execute
/api/v1/actions/{action}/status/{operation_id}

/api/v1/workflows/{id}
/api/v1/audit/events
```

## First vertical slice

The recommended first Copilot-enabled capability is:

```text
explain_invoice_exception
```

Example request:

```json
{
  "invoice_number": "54192"
}
```

The Hub will:

1. Validate the caller's Entra token.
2. Resolve Hub roles and AP access.
3. Retrieve the invoice, workflow state, extraction result, and validation result.
4. Retrieve related Business Central records when required.
5. Return approved exception descriptions and source metadata.
6. Record an audit event.

The first release is read-only and performs no Business Central write.

## Near-term security blockers

The following must be resolved before a broad Copilot pilot:

- Replace test `admin/admin` authentication with Entra SSO.
- Validate tokens on every protected endpoint.
- Remove default JWT secrets and demo identity behavior.
- Centralize Graph and Business Central token providers.
- Move secrets toward Key Vault or managed identity.
- Separate Production Read and Sandbox Write adapters.
- Enforce production-write policy in shared code.
- Add structured audit and correlation IDs.
- Restrict CORS and backend ingress.
- Add MongoDB authentication and private network controls.

## Delivery strategy

The application should remain a modular monolith during the initial roadmap. Internal service boundaries will be strengthened before independently deploying services.

### Months 1-3

Identity, authorization, audit, API versioning, configuration cleanup, and first read-only Copilot capability.

### Months 4-6

Document, AP, purchase-order, sales-order, Help Desk, and knowledge retrieval capabilities.

### Months 7-9

Customer, vendor, invoice, and meeting-preparation context capabilities.

### Months 10-12

Low-risk actions and Business Central sandbox draft creation.

### Months 13-15

Preview-and-confirm controls, approval integration, idempotency, reconciliation, and tightly governed production actions.

### Months 16-18

Executive summaries, exception trends, recommendations, cost optimization, wider rollout, and production support model.

## Next architecture documents

1. `01-current-state-inventory.md`
2. `02-security-model.md`
3. `03-capability-api-standard.md`
4. `04-copilot-studio-integration.md`
5. `05-data-provenance-and-audit.md`
6. `06-18-month-roadmap.md`
7. Architecture Decision Records under `docs/architecture/adr/`
