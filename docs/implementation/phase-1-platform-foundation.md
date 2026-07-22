# Phase 1 — Platform Foundation and Alignment Plan

## Objective

Introduce the platform foundation inside the existing GPI Hub without creating a second application, duplicating business logic, or interrupting current AP, Sales, document, and integration work.

Phase 1 is complete when the existing Hub starts through a platform bootstrap, every request can carry a shared identity context, every external operation can be checked by centralized runtime policy, every capability can be registered and invoked through one framework, and audit/event infrastructure exists for future migrations.

## Core rule

The current Hub remains the product and deployment unit.

We are adding a platform layer under the existing routes and services—not replacing the repository, not starting a second backend, and not rewriting working integrations.

Use the following migration rule for every existing component:

- REUSE: keep working business logic as-is.
- WRAP: place a platform contract around it.
- MIGRATE: move cross-cutting logic into the platform layer when touched.
- RETIRE: remove old flags, demo auth, or duplicate helpers only after all callers use the new layer.

## Target structure

```text
backend/
  server_new.py
  routes/                 # existing transport adapters
  services/               # existing business and integration logic
  platform/
    __init__.py
    bootstrap.py
    config/
      settings.py
      runtime_policy.py
    security/
      identity.py
      authorization.py
      dependencies.py
    capabilities/
      models.py
      registry.py
      decorators.py
      invocation.py
    audit/
      models.py
      service.py
    events/
      models.py
      publisher.py
      dispatcher.py
    persistence/
      mongo.py
  capabilities/
    ap/
      explain_invoice_exception.py
```

Routes remain FastAPI adapters. Existing services remain the first implementation behind capabilities. The new `platform` package supplies shared infrastructure only.

## Workstream 1 — Application bootstrap and configuration

### Deliverables

Create:

```text
backend/platform/bootstrap.py
backend/platform/config/settings.py
backend/platform/persistence/mongo.py
```

`settings.py` becomes the only place that reads environment variables. Use a validated settings model and fail startup when required production values are missing.

The bootstrap object owns:

- validated settings
- Mongo client and database
- runtime policy
- capability registry
- audit service
- event publisher

`server_new.py` should become composition code rather than the owner of configuration and database globals.

### Existing Hub alignment

Current code reads `MONGO_URL` and `DB_NAME` directly and stores global `db` and `mongo_client` values. Move those responsibilities into `platform.persistence.mongo`, but keep the same database and collections. No data migration is required.

Existing `set_db` and `set_dependencies` route functions may remain temporarily. Bootstrap should call them until routes are converted to FastAPI dependencies.

### Acceptance criteria

- Hub starts with the same database and existing endpoints.
- Configuration is validated once.
- No new code reads `os.environ` outside `platform/config`.
- Startup fails closed for invalid runtime mode or unsafe production-write configuration.

## Workstream 2 — Centralized runtime policy

### Deliverables

Create:

```text
backend/platform/config/runtime_policy.py
```

Implement the operating modes already defined in the architecture:

```text
DEVELOPMENT
SHADOW
PILOT_READ_ONLY
SANDBOX_ACTIONS
PRODUCTION_READ_ONLY
CONTROLLED_PRODUCTION_ACTIONS
```

Define operation classifications:

```text
READ
PREPARE
WORKFLOW
EXTERNAL_WRITE
IRREVERSIBLE
```

The policy service should expose one primary method:

```python
policy.authorize(operation, target_environment, capability_id, identity)
```

The result must be explicit and auditable:

```python
PolicyDecision(
    allowed=True,
    reason="...",
    mode="PILOT_READ_ONLY",
    rule_id="...",
)
```

### Existing Hub alignment

Do not delete `services/pilot_config.py` immediately.

First, change its guard functions to delegate to the new runtime policy while preserving existing function names:

```python
is_export_blocked(...)
is_bc_validation_blocked(...)
is_external_write_blocked(...)
```

This avoids changing every existing caller at once. New code must call runtime policy directly. Old callers continue through compatibility wrappers.

Pilot metadata and reporting thresholds can remain in `pilot_config.py`; only authorization decisions move to runtime policy.

### Acceptance criteria

- Existing pilot behavior remains unchanged.
- All new external operations require a policy decision.
- A single emergency write-disable setting blocks every external write.
- Compatibility wrappers are covered by tests.

## Workstream 3 — Identity context and authorization

### Deliverables

Create:

```text
backend/platform/security/identity.py
backend/platform/security/authorization.py
backend/platform/security/dependencies.py
```

Define an immutable `IdentityContext` containing:

- subject/object ID
- tenant ID
- display name
- email/UPN
- roles
- permissions
- authentication type
- correlation ID

Create a FastAPI dependency that resolves identity for every protected request.

During Phase 1, support two providers:

1. Entra bearer-token provider for development/test integration.
2. Explicit local-development provider, enabled only in `DEVELOPMENT` mode.

Do not preserve the current `admin/admin` endpoint as an accepted production authentication path.

### Existing Hub alignment

Keep current frontend behavior operational during transition by putting local development identity behind an environment setting. Replace the demo token endpoint only after the frontend can consume Entra authentication or the temporary development identity header.

Existing services should accept `IdentityContext` as a new optional argument when first migrated. Do not rewrite every service immediately.

### Acceptance criteria

- Protected routes receive an `IdentityContext`.
- Production modes reject local/demo identities.
- Permissions are checked centrally.
- Identity and correlation data are available to audit and capability invocation.

## Workstream 4 — Capability framework

### Deliverables

Create:

```text
backend/platform/capabilities/models.py
backend/platform/capabilities/registry.py
backend/platform/capabilities/decorators.py
backend/platform/capabilities/invocation.py
```

A capability definition must include:

- stable capability ID
- version
- display name and description
- request and response models
- required permissions
- operation classification
- target environment
- Copilot exposure flag
- handler

The registry must support:

```python
registry.register(...)
registry.get(capability_id)
registry.list(identity=None)
registry.invoke(capability_id, request, identity)
```

Invocation order:

1. resolve capability
2. validate request
3. authorize identity
4. authorize runtime policy
5. record invocation start
6. execute handler
7. record result/failure
8. publish event where applicable

### Existing Hub alignment

Do not move all routes into capabilities in Phase 1.

Register one proof capability: `explain_invoice_exception`.

Its handler should call existing Hub services and repositories. It must not duplicate invoice matching, BC lookup, validation, or exception logic.

The existing REST route can call `registry.invoke(...)`. A future Copilot connector will call the same invocation path.

### Acceptance criteria

- Registry can list and invoke capabilities.
- Authorization and runtime policy cannot be bypassed through the normal invocation path.
- `explain_invoice_exception` uses existing data/services.
- Existing UI endpoint continues to function through a thin route adapter.

## Workstream 5 — Audit foundation

### Deliverables

Create:

```text
backend/platform/audit/models.py
backend/platform/audit/service.py
```

Create an append-only Mongo collection:

```text
hub_audit_events
```

Minimum fields:

- audit ID
- timestamp UTC
- event/action type
- actor identity
- capability ID and version
- correlation ID
- target entity references
- runtime mode
- policy decision
- outcome
- duration
- error code
- sanitized metadata

Do not store secrets, bearer tokens, raw document content, or unrestricted prompts.

### Existing Hub alignment

Existing workflow history remains in place. Audit does not replace workflow history in Phase 1.

Use audit for platform-level facts: authentication, authorization, policy decisions, capability invocation, and external-write attempts.

Later, selected workflow history entries may also publish audit events, but there should be no bulk rewrite now.

### Acceptance criteria

- Every capability invocation creates start/result audit records or one complete structured record.
- Denied operations are recorded.
- Audit writes never prevent a read operation from returning unless compliance policy explicitly requires fail-closed behavior.
- Indexes exist for timestamp, correlation ID, capability ID, actor ID, and entity references.

## Workstream 6 — Minimal event foundation

### Deliverables

Create:

```text
backend/platform/events/models.py
backend/platform/events/publisher.py
backend/platform/events/dispatcher.py
```

Create Mongo collection:

```text
hub_events
```

Phase 1 supports durable publication and manual/background dispatch, not a full distributed event platform.

The event envelope includes:

- event ID and type
- schema version
- occurred and recorded timestamps
- source system
- source entity reference
- correlation and causation IDs
- actor
- payload
- dispatch status and attempts

### Existing Hub alignment

Do not convert current workflows to event-driven execution in Phase 1.

Publish only a few observational events from the proof capability and platform lifecycle, such as:

```text
CapabilityInvoked
InvoiceExceptionExplained
CapabilityFailed
```

Existing workflow engine remains authoritative for current document processing.

### Acceptance criteria

- Events can be persisted idempotently.
- Dispatcher can find pending events and invoke registered subscribers.
- Subscriber failure does not roll back the originating capability.
- No existing workflow depends on the event dispatcher yet.

## Workstream 7 — Testing and delivery controls

Create tests for:

- settings validation
- each runtime mode and operation class
- emergency write disable
- local identity rejection outside development
- permission denial
- capability registration and duplicate IDs
- invocation audit
- compatibility behavior in `pilot_config.py`
- event idempotency
- proof capability happy path, not found, ambiguous, unauthorized, and stale-data scenarios

Add a CI check that rejects direct `os.environ` access in newly added platform/capability code and prevents new write-capable routes from bypassing runtime policy.

## Implementation sequence

### Iteration 1 — Bootstrap without behavior change

- Add platform package.
- Add validated settings.
- Move Mongo lifecycle behind bootstrap.
- Keep all current routes and services working.
- Add startup and health tests.

### Iteration 2 — Runtime policy compatibility

- Implement runtime policy.
- Adapt `pilot_config.py` guards to delegate to policy.
- Add emergency write disable.
- Test parity with current pilot behavior.

### Iteration 3 — Identity and audit

- Add identity context and development provider.
- Add Entra token validation integration point.
- Add audit collection and service.
- Protect only the new capability endpoints initially.

### Iteration 4 — Capability framework

- Implement registry, decorator, and invocation pipeline.
- Add capability-list endpoint for administrators/developers.
- Register a diagnostic capability first, then `explain_invoice_exception`.

### Iteration 5 — Event publication and proof migration

- Add durable event publisher.
- Publish capability lifecycle events.
- Route the existing explain endpoint through capability invocation.
- Compare old and new responses in tests before removing old direct execution.

## How current feature development stays aligned

All ongoing Hub work may continue, but follow these rules:

1. Do not build a second service for functionality that already exists.
2. Put new business logic in a domain service, not directly in a route.
3. Routes perform HTTP translation only.
4. New external writes must call runtime policy even before full migration.
5. New user-sensitive features accept or propagate identity context.
6. New reusable operations should be registered as capabilities.
7. Existing collections and document schemas remain authoritative unless a migration is explicitly approved.
8. Existing integrations remain connectors/services; the platform wraps them rather than cloning them.
9. Do not convert stable workflows to events merely to satisfy the architecture.
10. Every refactor must preserve endpoint behavior until consumers are migrated.

## Alignment decision matrix

| Existing component | Phase 1 treatment | Reason |
|---|---|---|
| `server_new.py` | Slim and retain | It remains the FastAPI composition root, but bootstrap owns infrastructure. |
| `routes/*` | Retain and gradually thin | Existing UI/API compatibility must remain. |
| `services/*` | Reuse | Current business and connector logic is implementation behind capabilities. |
| `workflow_engine.py` | Retain | Do not replace current processing with events in Phase 1. |
| `pilot_config.py` | Wrap | Preserve metadata/metrics; delegate authorization guards to runtime policy. |
| Mongo collections | Retain | Add only `hub_audit_events` and `hub_events`; no duplicate operational data store. |
| Demo auth | Transitional retirement | Local identity may exist only under explicit development mode. |
| BC services | Reuse behind policy | No duplicate BC connector or data-access layer. |
| SharePoint services | Reuse behind policy | No duplicate document repository. |
| AI classifier/extraction | Reuse | Capability framework orchestrates it; it does not reimplement it. |
| Existing frontend | Retain | Change endpoints/auth incrementally after backend compatibility is proven. |

## Definition of done

Phase 1 is done when:

- the current Hub still runs and its existing primary workflows pass regression tests;
- platform bootstrap owns settings and Mongo lifecycle;
- centralized runtime policy governs all newly touched external operations;
- identity context and centralized authorization exist;
- a capability registry and invocation pipeline exist;
- audit and durable event collections exist;
- `explain_invoice_exception` runs through the capability framework using existing services;
- no duplicate Hub, database, BC connector, SharePoint storage layer, or invoice-processing implementation has been created;
- compatibility wrappers and migration notes identify all temporary legacy paths.

## First implementation pull request

The first code PR should contain only:

1. `backend/platform/config/settings.py`
2. `backend/platform/persistence/mongo.py`
3. `backend/platform/bootstrap.py`
4. minimal `server_new.py` integration
5. configuration/bootstrap tests

It should not change invoice processing, workflow behavior, authentication, or external integrations. That gives the platform a safe foundation and establishes the incremental migration pattern before cross-cutting behavior is changed.
