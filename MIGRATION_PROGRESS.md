# server.py → routes/ Migration Tracker

**Rule for this migration: NO BEHAVIOR CHANGE.** Move code, don't rewrite logic or
rename fields/collections. That's a separate, later effort (Phase 2/3 of
REFACTOR_PLAN.md — the unified `hub_documents` schema). Mixing the two is what
made the orphaned `routes/documents.py` / `ingestion.py` / `workflows.py` /
`config.py` / `dashboard.py` stubs unsafe to wire up as-is: they were written
against the *future* schema, not the current one. Those 5 files have been
deleted (see Decisions Log). We're rebuilding them as faithful extractions.

**Do not flip `backend/Dockerfile` to `server_new.py` until every group below is
`✅ migrated + verified` and the route-count diff at the bottom is zero.**

## Status legend
- ⬜ not started — still only in server.py
- 🟨 in progress
- ✅ migrated to routes/ + verified (route path/method + response shape diffed against original)
- ❌ removed per REFACTOR_PLAN (not migrated — intentionally dropped)

## Groups

| # | Group | Target file | Routes (count) | Status |
|---|-------|-------------|-----------------|--------|
| 1 | Auth | `routes/auth.py` | 2 | ✅ (already done, already wired) |
| 2 | AP review | `routes/ap_review.py` | n/a | ✅ (already done, already wired) |
| 3 | SharePoint migration | `routes/sharepoint_migration.py` | n/a | ✅ (already done, already wired) |
| 4 | Spiro | `routes/spiro.py` | n/a | ✅ (already done, already wired) |
| 5 | Documents core + Square9 | `routes/documents.py` | 13 (corrected count) | ✅ verified: py_compile OK, 152→152 route count unchanged (139 server.py + 13 routes/documents.py) |
| 6 | Dashboard (stats/doc-types) | `routes/dashboard.py` | 3 | ✅ verified: py_compile OK, 152 total (136 server.py + 3 dashboard.py + 13 documents.py) |
| 7 | BC company/sales-order lookups | `routes/bc.py` | 2 | ✅ verified: py_compile OK, 152 total (134 server.py + 13 documents.py + 3 dashboard.py + 2 bc.py) |
| 8 | Settings/config core | `routes/config.py` | 6 | ⚠️ **BLOCKED - moved to end of order, see Decisions Log** |
| 9 | Ingestion/classification engine | `core/job_config.py`, `services/ingestion_engine.py`, `routes/ingestion.py` | 4 routes + ~20 shared business-logic functions | ✅ verified: py_compile + pyflakes clean (only pre-existing bug flagged, see below), 152 total (130 server.py + 13+3+2+4 routes/) |
| 10 | Graph webhook + email polling + AP mailbox backfill | `services/email_polling_engine.py`, `routes/email_ingestion.py` | 6 | ✅ verified: py_compile + pyflakes clean, 152 total (124 server.py + 28 across routes/) |
| 11 | Sales backfill/migrate/polling | `services/sales_polling_engine.py`, `routes/sales_admin.py` | 2 | ✅ verified: py_compile + pyflakes clean, real import test passes (214 routes), 122+2=124 in server.py+routes/ |
| 12 | Job types / email watcher settings | `routes/job_type_settings.py` | 6 | ✅ verified: py_compile + pyflakes clean, real import test passes (214 routes) |
| 13 | Workflows — ap_invoice specific | `routes/workflows.py` | 12 (7404-8097, 9472) | ⬜ |
| 14 | Workflows — generic multi-type | `routes/workflows.py` | 12 (7589-8695) | ⬜ |
| 15 | Migration tools | `routes/migration.py` (new) | 5 (8695-8906) | ⬜ |
| 16 | Pilot (non-simulation) | — | 8 (8940-9408) | ❌ per REFACTOR_PLAN §Step 5 |
| 17 | Mailbox source settings | `routes/config.py` | 8 (9528-9674) | ⬜ |
| 18 | Vendor aliases | `routes/aliases.py` (new) | 4 (9855-9911) | ⬜ |
| 19 | Metrics/reporting | `routes/metrics.py` (new) | ~14 (10090-11483) | ⬜ |
| 20 | BC sandbox validation | `routes/bc_sandbox.py` (new) | 13 (11620-11789) | ⬜ |
| 21 | Pilot simulation | — | ~17 (11887-12584) | ❌ per REFACTOR_PLAN §Step 5 |
| 22 | Sales file import | `routes/sales_import.py` (new) | 6 (12604-12783) | ⬜ |
| 23 | Health check | `server_new.py` (inline) | 1 (12817) | ⬜ |

**Total live routes to migrate: ~113** (152 minus ~26 pilot/simulation dropped, minus 13 already wired via existing modules — auth/ap_review/sharepoint_migration/spiro overlap with the count above).

## Decisions Log
- **2026-07-07** Root architectural blocker identified and fixed: business
  logic (Graph/BC/SharePoint API calls, the upload-and-link workflow
  orchestrator, mock data, all config env vars, the Mongo connection) was
  defined as free functions directly in `server.py`, not in `services/`.
  That's what made a clean route-file split impossible without circular
  imports back into `server.py`. **Fixed:** extracted verbatim into:
  - `backend/core/db.py` — Mongo client/db (same MONGO_URL/DB_NAME env vars)
  - `backend/core/config.py` — all env-derived config constants
  - `backend/core/legacy_hub_helpers.py` — get_graph_token, get_email_token,
    get_bc_token, upload_to_sharepoint, create_sharing_link, get_bc_companies,
    get_bc_sales_orders, link_document_to_bc, run_upload_and_link_workflow,
    FOLDER_MAP, MOCK_COMPANIES, MOCK_SALES_ORDERS
  `server.py` now imports these names unchanged instead of defining them
  inline. **Verified:** `python -m py_compile` passes on server.py + all 3
  new core/ files; route count in server.py unchanged at 152 before/after
  (confirms this was a pure move, no routes lost). This unlocks every
  subsequent group in the table above — they can import from `core/` without
  touching `server.py`.
  - **Known limitation:** could not runtime-import `server.py` end-to-end in
    this sandbox (no MongoDB, and the full dependency list — google-genai,
    boto3, stripe, etc. — wasn't installed to keep this check fast). The
    py_compile + route-count-diff check is syntax + structure only. **Before
    deploying:** run `uvicorn server:app --reload` locally once against a
    real `.env` to confirm the app actually boots — this is the one gap in
    verification.
  - **Flagged, not fixed (out of scope for this move):**
    `services/business_central_service.py` has its own separate
    `get_bc_token()` for the `BusinessCentralService` class (vendors/POs/
    invoices/sales-order creation). Different code path from
    `core/legacy_hub_helpers.get_bc_token()` (used for generic doc-upload
    company/sales-order lookups + attachment linking) — not duplicate in
    scope, but the credential-fetch logic itself is now duplicated in two
    places. Worth consolidating later, not now.
- **Pilot/simulation removal**: `REFACTOR_PLAN.md` already recorded this as
  confirmed ("✅ Simplify pilot/simulation - confirmed", Step 5). Flagging again
  here before deleting ~26 endpoints in case that's changed — **confirm before
  group 16/21 are actioned.**

- **2026-07-07** Caught and fixed a real regression introduced by the
  `core/legacy_hub_helpers.py` extraction: `PUT /api/settings/config` hot-reloads
  BC/Graph/SharePoint credentials into module globals with no server restart
  (`global BC_CLIENT_ID; BC_CLIENT_ID = ...`, per its own docstring "no .env
  write = no server restart"). Before the extraction this worked because the
  reader (`get_bc_token()` etc.) and the writer (`update_settings_config`)
  were the same module, so Python's normal global lookup picked up the
  change automatically. After extraction they were different modules, and a
  `from core.config import BC_CLIENT_ID`-style import snapshots the value at
  import time - the moved helper functions would have silently kept using
  stale/demo credentials after any Settings-page update. **Fixed:**
  `core/legacy_hub_helpers.py` now does `from core import config` and reads
  `config.BC_CLIENT_ID` etc. inside function bodies (dynamic lookup each
  call); `server.py`'s `_load_config_from_db()` and `update_settings_config()`
  now write through to `core.config.X` in addition to their own `global`s.
  Verified: py_compile passes, route count still 152 total. **This same
  trap applies to every future group** that reads BC_CLIENT_ID/TENANT_ID/etc.
  (bc-sandbox, ap_invoice workflows, ingestion) - use `config.X` attribute
  access, never `from core.config import X`, for anything that can change
  via the Settings page.

- **2026-07-07** Second real bug caught (same family as the config hot-reload
  one above): `POST /workflows/{wf_id}/retry` (still in server.py, not yet
  migrated) calls `link_document(doc_id)` **as a plain Python function**, not
  through HTTP - it's directly invoking the other route handler's function
  body to reuse its logic. Once `link_document` moved to
  `routes/documents.py`, this call site would have raised `NameError` at
  runtime the first time that endpoint was hit - not caught by py_compile
  (only checks syntax) or by the route-count diff (only checks route paths
  exist, not internal call graphs). **Fixed:** `server.py` now does
  `from routes.documents import link_document as _link_document` and the
  call site uses that. **New standing check added to this migration's
  process:** after moving any group, grep `server.py` for calls to every
  function name defined in that group (not just route paths) before
  declaring it done - route handlers sometimes call each other directly as
  plain functions to reuse logic, and that's invisible to a route-count
  check.

- **2026-07-07** Third finding, this one changes migration ORDER: the
  Settings group (`_load_config_from_db`, `update_settings_config`, and
  friends) can't move to `routes/config.py` yet. `DEMO_MODE`, `BC_CLIENT_ID`,
  `TENANT_ID`, etc. are read as bare module-level names 12-23 times each in
  parts of `server.py` that haven't been migrated yet (bc-sandbox validation,
  ingestion, test-connection, more). That currently works only because the
  settings-update code's `global X; X = ...` reassignment lives in the same
  module as all those readers. Moving the writer out now, while ~150 reader
  references still exist in `server.py` as bare names, would silently break
  live credential hot-reload for everything not yet migrated - the same bug
  class as the `core/legacy_hub_helpers.py` one, but in the opposite
  direction. **Decision:** Settings moves LAST, after every other group's
  config references have been converted to `config.X` attribute access (which
  happens naturally as each group gets migrated using the `from core import
  config` pattern established in Group 5). At that point `server.py`'s own
  bare references will be the only stale ones left, and converting those in
  one final pass makes Settings safe to move.

- **2026-07-07** Group 9 (Ingestion engine) complete - the big one. Actual
  scope: ~2,000 lines of business logic (not the ~600 originally estimated)
  split across three new files:
  - `core/job_config.py` — DEFAULT_JOB_TYPES, VENDOR_ALIAS_MAP,
    AutomationLevel/POValidationMode/VendorMatchMethod/TransactionAction
    enums, DRAFT_CREATION_CONFIG, and the Pydantic models (MailboxSource,
    EmailWatchConfig, JobTypeConfig, DocumentIntake, AIClassificationResult,
    ValidationCheck). Shared because settings, metrics, migration, and
    aliases groups (not yet migrated) all reference these too.
  - `services/ingestion_engine.py` — the actual AP-invoice processing
    pipeline: AI classification, field normalization, vendor/customer
    matching (exact/normalized/alias/fuzzy against BC), duplicate detection,
    BC validation, automation decision, workflow status transitions.
  - `routes/ingestion.py` — the 4 thin HTTP endpoints over that engine.
  **Scope correction found mid-move:** lines 2303-2604 of the original
  server.py (email watcher helpers + a dead/uncalled `on_document_ingested`)
  were textually interspersed in this region but aren't part of the
  ingestion engine - they're only used by not-yet-migrated Email/Webhook and
  Job-types-settings groups. Left in place in `server.py` on purpose.
  **Pre-existing bug found, NOT fixed:** `intake_document`'s Phase-4
  draft-creation path calls `is_eligible_for_draft_creation`,
  `check_duplicate_purchase_invoice`, and `create_purchase_invoice_header` -
  none of which are defined or imported anywhere in the original codebase.
  This predates the migration entirely (confirmed via pyflakes on the
  extracted file, then verified those names never existed in git history of
  this region). It's dead/unreachable code today: `ENABLE_CREATE_DRAFT_HEADER`
  defaults to false, and even if enabled, `DEFAULT_JOB_TYPES["AP_Invoice"]`
  has `automation_level: 1`, so `make_automation_decision()` can never
  return `"auto_create"` - the only way this branch is entered. Preserved
  verbatim rather than guessed-and-fixed; flagged in a code comment in
  `services/ingestion_engine.py` for whenever Phase 4 is actually built out.
  **New verification step added:** `pyflakes` (installed via pip) is now run
  on every new/touched file in addition to py_compile - it catches undefined
  names that py_compile's syntax-only check misses (this is how the
  `hashlib` and `WorkflowStatus`/`WorkflowEvent`/`logger` omissions in this
  group were caught before they became runtime NameErrors). Retroactively
  ran it on Groups 5-7's files too - all clean.

- **2026-07-07** Group 10 (Graph webhook + email polling + AP mailbox
  backfill) complete. Split into `services/email_polling_engine.py` (pure
  logic: process_incoming_email, poll_mailbox_for_attachments, the
  duplicate-detection/skip-attachment helpers, email_polling_worker's loop
  body) and `routes/email_ingestion.py` (6 thin HTTP endpoints). Kept in
  `server.py` on purpose: the `_email_polling_task` background-task
  lifecycle (created on startup, cancelled on shutdown) - that's app
  lifecycle plumbing, not business logic. Also found and dropped a harmless
  duplicate `_email_polling_task = None` module-level declaration that
  existed inside the moved region (the real one used by startup/shutdown is
  elsewhere in server.py, untouched).
  **Note:** `routes/workflows.py` still shows old orphaned-stub content (the
  pre-migration file from before this session started, never wired into
  server.py, targets the future unified schema). Harmless dead file - will
  be overwritten with a faithful extraction when Group 13/14 (workflows) is
  actually done, same as documents.py/dashboard.py were.

## IMPORTANT: Branch base correction (2026-07-07)
This refactor was originally built on top of `main` (commit `9976b53a`).
It turned out `main` was stale - the actively-developed branch is
`feature/sales-order-intake-preflight`, which forked directly from that
same `main` commit (6 minutes after its last commit) and added 78 more
commits through 2026-06-24 that `main` never got. Verified this branch's
changes don't overlap with anything in this refactor except
`backend/routes/__init__.py` (they added a `sales_order_review` side-effect
import; this refactor removed stale eager imports - both changes coexist
fine, resolved via cherry-pick). `backend/server.py` was byte-identical
between the two branches at the fork point, so this refactor's diffs applied
directly with no other conflicts.

Current state: local branch `refactor-on-sales-order-branch`, built as
`origin/feature/sales-order-intake-preflight` + the two refactor commits
(cherry-picked, one conflict resolved in `routes/__init__.py`). Verified via
py_compile + pyflakes + a real `import server` test: clean, 214 routes
(206 from the refactor + 8 sales-order-review endpoints from this branch).

**Before any further group migrations continue, confirm with the user which
branch this should ultimately land on** (push as a new branch? replace
`feature/sales-order-intake-preflight`? merge to `main` first?) - that's a
repo-workflow decision, not a technical one.

## Next up
Group 5 (Documents core + Square9, 15 routes) is next: extract into
`routes/documents.py`, remove from `server.py`, wire into `server_new.py`,
diff-verify. Every group after that follows the same now-unblocked pattern.

## Verification approach (no live Mongo/BC/SharePoint in this sandbox)
Since this sandbox has no live MongoDB/BC-sandbox/SharePoint credentials, each
migrated group is verified by:
1. `python -m py_compile` on the new module (syntax/import correctness)
2. Diffing extracted route list (path/method) against the original slice in
   server.py — zero missing, zero added
3. Diffing the function body text (post-refactor only changes: imports, `db`
   access pattern via dependency injection, router prefix) — no logic edits
4. Full integration/DB-backed test run is **your responsibility** before
   flipping the Dockerfile — the existing `backend/tests/` suite needs a real
   Mongo instance this sandbox doesn't have network access to provision.
