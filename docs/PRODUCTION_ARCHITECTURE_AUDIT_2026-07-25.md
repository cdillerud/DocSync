# Production Architecture Audit

Date: 2026-07-25  
Production branch: `gemini-model-fix-clean`

## Executive summary

The production application already has the beginnings of the correct architecture:

- `backend/main.py` owns the FastAPI application instance.
- `backend/main.py` imports and registers the domain routers.
- `backend/server.py` is no longer the served FastAPI application.
- `backend/server.py` remains a large compatibility and orchestration library.
- Many router modules still import handler functions from `server.py` and register them with `add_api_route()`.

The immediate goal should not be a large rewrite. The safe path is to reduce `server.py` incrementally by moving one cohesive domain at a time into dedicated services and routers while preserving existing route paths and response contracts.

## Current application boundary

### `backend/main.py`

Current responsibilities:

1. Load environment configuration.
2. Validate startup secrets.
3. Create the FastAPI application.
4. Configure CORS.
5. Import and register the application routers.
6. Expose `/api/health`.
7. Delegate shared startup and shutdown behavior to `server.py`.
8. Run several startup-only migrations and index initialization tasks.

This file is already the authoritative application entry point and should remain so.

### `backend/server.py`

Current responsibilities include:

1. Compatibility exports used by older modules.
2. Startup and shutdown orchestration.
3. Microsoft Graph, Business Central, and SharePoint helper wrappers.
4. Document upload and workflow handlers.
5. AP invoice processing and validation orchestration.
6. Email polling and sales polling support.
7. Legacy mock data and demo-mode behavior.
8. Handler implementations registered by router modules.
9. Direct dependencies on a large number of services.

This combination makes `server.py` difficult to test and risky to modify.

## Important finding

The comments in both application files agree on the intended architecture:

- `main.py` owns the served FastAPI app.
- Router modules own route registration.
- `server.py` is used as a library.
- Complex legacy handlers remain in `server.py` only because router modules still depend on them.

This means the architecture migration is already underway. The next work should continue that migration rather than introduce another application entry point.

## Recommended extraction order

### Phase 1: Microsoft and Business Central compatibility helpers

Move these remaining wrappers out of `server.py` and update callers to import the authoritative services directly:

- Graph token acquisition
- Email token acquisition
- Business Central token acquisition
- Business Central company and sales-order lookups
- SharePoint upload and sharing wrappers
- Business Central document linking
- Purchase-invoice draft creation wrappers

Why first:

- Most already delegate immediately to service modules.
- Behavior can be preserved exactly.
- Removing them reduces imports and global configuration in `server.py`.
- Risk is lower than moving document-processing logic.

### Phase 2: Document orchestration

Move the remaining document handler implementations into a dedicated service layer:

- upload orchestration
- file persistence
- workflow initialization
- SharePoint upload and linking
- document reprocessing
- derived-state refresh

Keep route definitions in `routers/documents.py`.

### Phase 3: AP invoice orchestration

Move AP-specific logic into explicit services:

- extraction
- vendor matching
- Business Central validation
- duplicate detection
- auto-clear decisions
- draft creation eligibility
- posting attempts

The router should contain request validation and response formatting only.

### Phase 4: Polling and scheduled work

Move long-running task lifecycle management into a dedicated application lifecycle module:

- AP email polling
- Sales email polling
- pilot summary task
- cancellation and shutdown behavior

Replace scattered global task references with one lifecycle object stored on `app.state`.

### Phase 5: Startup migrations

Move startup-only index creation and data migrations from `main.py` into a startup task registry. Each task should have:

- a name
- an async callable
- failure policy: fatal or warning
- structured logging
- execution timing

## First implementation target

The safest first code change is the token/helper cleanup in Phase 1.

Proposed modules:

```text
backend/services/microsoft_token_service.py
backend/services/integration_facade.py
```

However, where authoritative service modules already exist, callers should import those modules directly rather than create another permanent wrapper layer.

## Guardrails

Every extraction must preserve:

1. Existing API paths.
2. Existing request and response schemas.
3. Existing environment variable names.
4. Production read/write separation for Business Central.
5. Existing startup behavior.
6. Existing smoke-test results.

For each extraction:

1. Record affected routes.
2. Move code without changing behavior.
3. Run syntax and import checks.
4. Run focused tests.
5. Deploy to production.
6. Run `scripts/live_production_smoke_test.sh`.
7. Commit only after production verification when practical.

## Repository policy observations

The production branch is the current source of truth. Changes should continue to target:

```text
gemini-model-fix-clean
```

Do not merge or pull `main` into production during this modularization effort.

## Next concrete task

Create an inventory of every symbol imported from `server.py` by routers and services. Categorize each symbol as:

- compatibility constant
- lifecycle function
- integration helper
- document handler
- AP handler
- sales handler
- obsolete or unused

That inventory will determine the exact extraction sequence and prevent accidental breakage.
