# GPI Hub Current-State Architecture Inventory

**Status:** Initial as-built assessment  
**Repository:** `cdillerud/DocSync`  
**Baseline branch reviewed:** `main`  
**Architecture branch:** `architecture/copilot-platform`

## 1. Purpose

This document records the current architecture of GPI Hub as implemented in the repository. It is intended to be the factual baseline for the Copilot platform design, security model, capability API, and 18-month roadmap.

The inventory distinguishes between:

- Implemented production code
- Refactor code that exists but is not necessarily the active entry point
- Pilot and simulation controls
- Planned architecture
- Security and operational gaps that must be closed before conversational access is enabled

## 2. Current System Shape

GPI Hub is currently a FastAPI and React application using MongoDB for operational persistence. It integrates with Microsoft Graph, SharePoint Online, Business Central, email mailboxes, Spiro, and AI classification services.

The codebase is best described as a **transitioning modular monolith**:

- `backend/server.py` remains a large composition root with routes, configuration, token acquisition, background tasks, and integration logic.
- Dedicated route and service modules already exist.
- `backend/server_new.py` demonstrates a cleaner target composition but is not yet a complete replacement.
- `REFACTOR_PLAN.md` defines a unified-document and modular-route direction.

This is compatible with the proposed enterprise platform architecture. A microservice rewrite is not warranted.

## 3. Application Entry Points

### 3.1 Current primary server

`backend/server.py` currently performs multiple responsibilities:

- FastAPI application construction
- MongoDB connection
- Environment-variable loading
- Router registration
- Authentication compatibility endpoints
- Graph token acquisition
- Business Central token acquisition
- SharePoint operations
- Email polling configuration
- Sales polling configuration
- Pilot summary scheduling
- Service dependency wiring
- Mock data and demo-mode behavior

Architectural implication: this file should be reduced to application composition, middleware, startup, shutdown, and router registration.

### 3.2 Refactored server candidate

`backend/server_new.py` already demonstrates:

- Lifespan-based startup and shutdown
- Centralized MongoDB initialization
- Dedicated route modules
- Index creation
- A smaller application entry point

It is not yet production-ready because it still contains:

- Demo `admin/admin` authentication
- A fixed demo token
- Unrestricted CORS using `allow_origins=["*"]`
- Placeholder workflow routing
- Direct global database dependency wiring

Recommendation: use this file as evidence and a migration aid, but do not simply swap it into production without completing identity, authorization, workflow routing, and integration wiring.

## 4. Route Inventory

Dedicated route modules identified in the repository include:

- `routes/auth.py`
- `routes/documents.py`
- `routes/ingestion.py`
- `routes/workflows.py`
- `routes/dashboard.py`
- `routes/config.py`
- `routes/ap_review.py`
- `routes/sharepoint_migration.py`
- `routes/spiro.py`

The current architecture also retains significant endpoint logic inside `server.py` and a large `sales_module.py`.

### 4.1 Functional API groups

The current API surface can be grouped into these domains:

| Domain | Current responsibility |
|---|---|
| Authentication | Demo login and current-user response |
| Documents | Upload, list, detail, update, linking, classification |
| Ingestion | Email, upload, file intake, deduplication |
| AP review | Invoice review, vendor resolution, validation |
| Workflows | State transitions, retries, queue processing |
| Sales | Sales document intake, order handling, email polling |
| Business Central | Company, vendor, PO, invoice, sales-order lookups and writes |
| SharePoint | Document storage, migration, links, metadata |
| Spiro | CRM synchronization and context |
| Dashboard | Counts, metrics, pilot and simulation reporting |
| Configuration | Mailboxes, feature flags, integration status |
| Migration | Square9, Zetadocs, JSON, file, and SharePoint migration |

### 4.2 Future API boundary

Existing UI-oriented endpoints should remain functional during transition. New enterprise capabilities should be introduced under:

```text
/api/v1/
```

This prevents Copilot contracts from becoming coupled to current React pages or legacy workflow endpoints.

## 5. Service Inventory

### 5.1 Core business services

- `workflow_engine.py`
- `file_ingestion_service.py`
- `ai_classifier.py`
- `invoice_extractor.py`
- `auto_post_service.py`
- `square9_workflow.py`
- `pilot_config.py`
- `pilot_summary.py`
- Migration services and sources

### 5.2 Integration services

- `business_central_service.py`
- `bc_sandbox_service.py`
- `bc_simulation_service.py`
- `email_service.py`
- `sharepoint_migration_service.py`
- `services/spiro/*`

### 5.3 Observability and pilot services

- `simulation_metrics_service.py`
- Pilot logs and summary generation
- Workflow history embedded in operational documents
- Email poll logs and intake logs

## 6. Workflow Architecture

The workflow engine is one of the strongest parts of the current design.

It is explicitly implemented as deterministic business logic without direct HTTP or database calls. It supports multiple document types and maps events to state transitions.

Current modeled document types include:

- AP invoice
- Sales invoice
- Purchase order
- Sales credit memo
- Purchase credit memo
- Statement
- Reminder
- Finance charge memo
- Quality document
- Other/manual triage

Current workflow concepts include:

- Capture
- Classification
- Extraction
- Vendor resolution
- Business Central validation
- Data correction
- Review
- Approval
- Export
- Archive
- Failure and retry
- Pilot simulation events

### Architectural decision

The workflow engine should remain deterministic and become the shared workflow authority for requests originating from:

- React UI
- Email ingestion
- Background automation
- Copilot Studio
- Future APIs

No Copilot action should directly set `workflow_status`. It should submit a validated workflow event.

## 7. Data and MongoDB Inventory

The repository refactor plan identifies 27 collections and proposes consolidation around a unified `hub_documents` collection.

### 7.1 Proposed core collections already identified

- `hub_documents`
- `hub_config`
- `mailbox_sources`
- `vendor_aliases`

### 7.2 Existing or referenced supporting collections

The code and refactor documentation reference collections for:

- Sales documents
- Sales customers
- Sales items
- Warehouses
- Open-order headers and lines
- Inventory positions
- Workflow runs
- Mail intake logs
- Mail poll runs
- Pilot simulations
- Simulation metrics
- File-ingestion logs
- Spiro synchronization
- Migration jobs

### 7.3 Current direction

The existing refactor plan proposes:

- One unified document collection
- Embedded workflow history
- Embedded source metadata
- Consolidation of duplicate sales-document and mail-ingestion storage
- Retention of true master data outside `hub_documents`

This direction should be preserved, with one amendment: enterprise capability execution and security audit events should use dedicated append-oriented collections rather than being embedded only in documents.

Recommended future additions:

- `capability_definitions`
- `capability_executions`
- `audit_events`
- `entity_links`
- `action_confirmations`
- `source_sync_state`

## 8. Business Central Integration Inventory

### 8.1 General Business Central service

`business_central_service.py` supports real and mock API access and includes:

- Client-credential authentication
- Token caching
- Company resolution
- Vendor lookup
- Purchase-order lookup
- Purchase-invoice operations
- Writeback feature flags

It can fall back from `BC_*` credentials to `BC_SANDBOX_*` credentials. This flexibility is convenient but creates environment ambiguity.

### 8.2 Sandbox service

`bc_sandbox_service.py` is explicitly documented as read-only and supports:

- Vendor lookups
- Customer lookups
- Purchase-order lookups
- Purchase-invoice lookups
- Sales-invoice lookups
- Observation-mode logging

It includes pilot write-block exceptions and mock-mode behavior.

### 8.3 Auto-post service

`auto_post_service.py` evaluates AP invoices for automatic Business Central posting using:

- AI confidence
- Required extracted fields
- Vendor resolution
- SharePoint storage confirmation
- Duplicate posting status

The auto-post feature flag currently defaults to enabled.

### 8.4 Environment risk

The current code contains overlapping controls:

- `PILOT_MODE_ENABLED`
- `DEMO_MODE`
- `BC_MOCK_MODE`
- `BC_WRITEBACK_LINK_ENABLED`
- `AUTO_POST_ENABLED`
- `ENABLE_CREATE_DRAFT_HEADER`
- `AUTO_CREATE_SALES_ORDER_ENABLED`
- Production and sandbox credential variables

These controls are not yet expressed through one central environment and action policy.

### Required future model

Every Business Central operation should be classified as:

```text
READ_PRODUCTION
READ_SANDBOX
WRITE_SANDBOX
WRITE_PRODUCTION
```

Every adapter call must receive an explicit environment policy. Credentials must not silently fall back between Production and Sandbox.

Recommended adapter structure:

```text
integrations/business_central/
├── production_reader.py
├── sandbox_reader.py
├── sandbox_writer.py
├── production_writer.py
├── token_provider.py
├── policy.py
└── models.py
```

The production writer should remain disabled until the controlled-action phase of the roadmap.

## 9. Microsoft Graph and SharePoint Inventory

The Hub currently uses Microsoft Graph for:

- SharePoint document storage
- SharePoint links and metadata
- Mailbox polling and attachment retrieval
- Email intake

Credentials are currently loaded from environment variables, and token acquisition occurs in more than one area.

### Current concerns

- Separate Graph and email credentials can fall back to one another.
- Application permissions may be broader than an individual capability requires.
- User identity is not yet propagated through Hub requests.
- There is no central Graph permission policy by capability.

### Future direction

Introduce one token-provider abstraction per application identity and maintain explicit clients for:

- SharePoint document operations
- Mail intake
- User-delegated Graph operations, where required

Copilot must never receive these credentials or direct Graph access through the Hub connector.

## 10. Email and Background Processing Inventory

The application contains background-task configuration for:

- AP mailbox polling
- Sales mailbox polling
- Pilot summary generation
- Email lookback windows
- Maximum message counts
- Attachment size limits

The current implementation keeps global references to asynchronous polling tasks inside the API process.

### Architectural concern

Running polling jobs in the web process can cause:

- Duplicate pollers when multiple web workers are started
- Missed jobs during restarts
- Difficult ownership and health monitoring
- Coupling between API scaling and job execution

### Recommended transition

Near term:

- Keep one API instance responsible for polling.
- Add a distributed lease in MongoDB.
- Record poller ownership, heartbeat, and last-success timestamps.

Later, if justified:

- Move polling and long-running work to a dedicated worker process.
- Use a queue or durable job model.

Do not introduce a large messaging platform solely for Copilot.

## 11. Authentication and Authorization Inventory

### 11.1 Current state

Current authentication remains development-grade:

- Test credentials are `admin/admin`.
- JWT secret has a default fallback value.
- The current-user endpoint does not validate an access token.
- Similar demo authentication appears in both the current and refactored server paths.
- No record-level authorization layer is evident.

### 11.2 Required state before Copilot

Release blockers:

1. Entra ID authentication for the React application.
2. Bearer-token validation in FastAPI.
3. Tenant, audience, issuer, signature, and expiry validation.
4. Entra group or app-role mapping.
5. A request-scoped user context.
6. Capability-level authorization.
7. Record-level filtering.
8. Removal of test authentication from production builds.
9. Security audit events for allow and deny decisions.

## 12. Pilot and Simulation Controls

`pilot_config.py` defaults pilot mode to enabled and implements global blocking for:

- Exports
- Business Central validation calls
- External writes

It also adds pilot metadata, capture channels, workflow annotations, and stuck-document thresholds.

The pilot period recorded in code ended on March 8, 2026. The code remains valuable, but the architecture should not continue to use an expired pilot phase as the permanent production safety model.

### Key policy inconsistency

- Pilot mode defaults to blocking external writes.
- Auto-post independently defaults to enabled.

Even if current call paths prevent an actual conflict, this is too difficult to reason about safely.

### Recommendation

Replace overlapping Boolean flags with a central runtime policy object:

```python
class RuntimePolicy:
    deployment_environment: str
    operating_mode: str
    allow_external_reads: bool
    allow_sandbox_writes: bool
    allow_production_writes: bool
    allowed_action_names: set[str]
```

Suggested operating modes:

- `DEVELOPMENT`
- `SHADOW`
- `PILOT_READ_ONLY`
- `SANDBOX_ACTIONS`
- `PRODUCTION_READ_ONLY`
- `CONTROLLED_PRODUCTION_ACTIONS`

Fail closed when configuration is incomplete or contradictory.

## 13. AI Inventory

The backend dependencies and services support multiple AI providers and abstractions, including OpenAI, Google AI, LiteLLM, and related tokenization libraries.

AI is currently used for:

- Document classification
- Field extraction
- Confidence scoring
- Potential workflow automation eligibility

### Architectural concern

Provider flexibility is useful, but model access, prompts, cost tracking, and data handling should be centralized before conversational usage expands.

### Future AI gateway responsibilities

- Approved model/provider list
- Prompt-template versioning
- Data-classification policy
- Token and cost telemetry
- Redaction rules
- Structured-output validation
- Retry and fallback policy
- Correlation with capability execution

The Hub should not send unrestricted source documents or system payloads to an LLM by default.

## 14. Frontend Inventory

The current frontend contains multiple domain and pilot-specific pages. The refactor plan recommends consolidation into:

- Dashboard
- Unified Queue
- Document Detail
- Upload
- File Import
- Settings
- Login
- Optional Audit Dashboard

This remains appropriate.

Copilot should be treated as an additional experience layer, not a replacement for the operational queue UI. Complex review, correction, reconciliation, and administration will continue to require purpose-built screens.

## 15. Deployment Inventory

Docker Compose currently defines:

- MongoDB 6
- FastAPI backend
- React/Nginx frontend
- Named volumes
- Internal Docker networking

Positive controls already present:

- Backend is exposed internally rather than mapped directly to a host port.
- MongoDB has a health check.
- Persistent volumes are defined.

Current gaps:

- MongoDB authentication is not visible in Compose.
- Frontend build configuration contains a fixed public IP.
- TLS termination and external ingress are not represented in the file.
- Secret management relies on `.env` files.
- Environment separation is not explicit.
- Backup, restore, retention, and disaster-recovery controls are not documented in the reviewed deployment definition.

## 16. Test Inventory

The repository contains tests for:

- Workflow engine
- Multi-type workflows
- AI classification
- Intake classification
- Business Central sandbox service
- Business Central simulation service
- Spiro integration
- Migration
- General Hub behavior

This existing test investment is a major strength.

### Required additions for enterprise capabilities

- Authentication tests
- Authorization allow/deny matrix
- Record-level security tests
- Production-write denial tests
- Environment-policy tests
- Capability contract tests
- Audit-event tests
- Idempotency tests
- Confirmation-token tests
- Prompt-injection and untrusted-content tests
- Copilot connector contract tests

## 17. Current Architectural Strengths

1. Deterministic workflow engine.
2. Existing route and service separation work.
3. Unified document-store direction.
4. Mock and simulation support.
5. Real Business Central and Graph integration experience.
6. Existing AP and Sales domains.
7. Feature-flag experience.
8. Meaningful automated test coverage.
9. SharePoint as the document system of record.
10. MongoDB as flexible workflow and metadata persistence.

## 18. Priority Risks

| Priority | Risk | Required response |
|---|---|---|
| Critical | Demo authentication and default secrets | Implement Entra authentication before Copilot |
| Critical | Ambiguous BC environment and overlapping write flags | Central environment/action policy |
| High | Large `server.py` composition and duplicated token logic | Incremental modularization |
| High | Background polling in API process | Lease/heartbeat, then worker separation if needed |
| High | Broad connector credentials | Capability-specific integration policies |
| High | Missing record-level authorization | User context and data filtering |
| Medium | Duplicate or scattered MongoDB collections | Continue unified-document migration |
| Medium | Pilot code has become permanent complexity | Replace with explicit runtime modes |
| Medium | Multiple AI providers without one governance layer | Introduce AI gateway policy |
| Medium | Fixed deployment values and `.env` secrets | Environment-specific configuration and Key Vault |

## 19. Recommended Near-Term Work Order

1. Finish the as-built route, collection, and feature-flag inventory during implementation work.
2. Establish central runtime configuration and fail-closed policy validation.
3. Implement Entra authentication and request-scoped identity.
4. Add capability and audit schemas.
5. Create `/api/v1/capabilities`.
6. Implement the read-only `explain_invoice_exception` vertical slice.
7. Connect that capability to Copilot Studio.
8. Continue modular refactoring without disrupting current Hub operations.

## 20. Inventory Conclusion

The current Hub is not a prototype that should be discarded. It already contains the essential domain knowledge, integrations, workflows, and operational experience needed for the enterprise platform.

The main challenge is now **control and coherence**, not raw functionality:

- One identity model
- One authorization model
- One runtime policy
- One Business Central environment policy
- One capability standard
- One audit model
- One integration boundary

These controls will allow the existing Hub to become the safe foundation for Copilot Studio and future conversational clients.