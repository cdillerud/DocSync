# GPI Document Hub - Changelog


## [2026-02-XX] Contract Intelligence Phase 4C(c) — PDF Body Extraction for Legacy Agreements

**Scope:** Pull contractual fields that DocuSign templates and Navigator
metadata cannot carry — freight terms, MOQ (header + per-line), volume
commitment, tooling amortization, payment-term cash discounts, and
volume-tier discounts — directly from agreement PDF bodies. Fully
deterministic regex; no LLM. Opt-in via a new admin-gated HTTP endpoint
and CLI; Navigator import and DocuSign webhook flows remain untouched.

### New
- `services/contracts/pdf_text_extractor.py` — pypdf wrapper. Soft-fails
  on encrypted / unreadable / image-only PDFs into `PDFExtractionError`.
- `services/contracts/pdf_field_extractors.py` — five regex-only
  extractors with consistent confidence scoring (0.55–0.95) plus an
  aggregator that dedupes per-line MOQs from header MOQs.
- `services/contracts/pdf_extraction.py` — orchestrator that turns PDF
  bytes into an `ExtractionResult` preview and detects same-key
  ambiguities for low-severity exception emission.
- `routers/contracts.py` — `POST /api/contracts/agreements/{id}/pdf-extract?commit=false|true`.
  Admin-gated multipart upload; default dry-run preview; `commit=true`
  upserts via `ContractIntelligenceService.ingest_pdf_extraction`.
- `scripts/contracts_extract_pdf.py` — CLI wrapping the same shared
  service so the two ingest paths cannot drift.
- `services/contracts/contract_intelligence_service.py` —
  `ingest_pdf_extraction()`. Idempotent upserts keyed by
  `(agreement_id, term_key, source="pdf_body")` for terms,
  `(agreement_id, kind, description)` for obligations, and
  `(agreement_id, item_label)` overlay for per-line MOQs. Ambiguity
  exceptions are open-state-aware so replays update the same row
  rather than fanning out duplicates.

### Schema additions (additive, no migration)
- `TermSource`, `PricingSource`: added `"pdf_body"`.
- `ObligationKind`: added `"volume_commitment"`, `"tooling_amortization"`.
- `ExceptionCode`: added `"pdf_extraction_ambiguous"`,
  `"pdf_extraction_failed"`.
- `AgreementPricing.min_quantity: Optional[float]` — per-line MOQ overlay.

### Fixtures
- `tests/fixtures/contracts/pdfs/_build_fixtures.py` —
  deterministic synthetic-PDF builder (no real customer data).
- Three committed synthetic PDFs:
  - `bragg_supply_excerpt.pdf` (freight + header MOQ + per-line MOQs + 1%/10 net 30)
  - `tooling_amortization_excerpt.pdf` (lump sum + amortized $/unit + volume commitment)
  - `volume_commitment_with_tiers.pdf` (volume commitment + tier table + 2/15 net 45 + DAP)

### Tests (+61 new, all passing)
- `test_contracts_pdf_text_extractor.py` — happy path + error paths.
- `test_contracts_pdf_field_extractors.py` — per-family unit tests
  with positive + negative cases (incl. ambiguity dedup).
- `test_contracts_pdf_extraction_orchestrator.py` — full bytes → preview
  pipeline + ambiguity detection + idempotency.
- `test_contracts_pdf_endpoint.py` — admin-gated HTTP + service-level
  ingest, including replay idempotency and 404/400 guards.
- Suite total: **253 passed, 8 skipped, 1 xfailed** (Phase 4C(d)
  baseline of 192 preserved + 61 new).

### Out of scope (explicitly not delivered)
- DocuSign SDK install, live envelope fetch, Connect webhook activation.
- Agreement ↔ Document Hub cross-link.
- LLM augmentation.
- BC writes, DocuSign writes.
- Any change to Navigator import or AP / posting / poller / vendor /
  classification flows.


## [2026-02-XX] Contract Intelligence Phase 4C(c) housekeeping (immediate predecessor)

**Scope:** Stabilize the test baseline before PDF extraction lands.

### Fixed
- `backend/requirements.txt` — added `mongomock-motor==0.0.36` and
  `mongomock==4.3.0` so the production VM container's image bake
  preserves the in-memory async MongoDB driver used across the
  `test_contracts_*` suites.
- `tests/test_contracts_endpoints.py`, `tests/test_contracts_phase3.py`
  — replaced the `asyncio.get_event_loop().run_until_complete(...)`
  pattern (which raises `RuntimeError` on Python 3.10+ once an earlier
  test has closed the default loop) with a fresh-loop helper. Restores
  22 tests to green on the production VM that had been failing at
  fixture setup.

### Suite
- 192 passed, 8 skipped, 1 xfailed across the focused Phase 4C(d)
  scope (was the same on /app dev container before; the housekeeping
  closes the dev/prod parity gap).


## [2026-02-XX] Hotfix — Contract Intelligence upsert path-conflict (post-Phase-4C(a))

**Root cause:** `_upsert_parties / _upsert_terms / _upsert_pricing /
_upsert_documents` in `contract_intelligence_service.py` sent the same
field path (`id`, `created_at`) in both `$set` and `$setOnInsert`.
Real MongoDB 6.x raises `WriteError code 40 — Updating the path 'id'
would create a conflict at 'id'`. Mongomock-motor (used in the test
suite) silently tolerated it, so CI was green while the prod VM
failed mid-pipeline. Caught when Charlie's first commit of the Bragg
Navigator export landed only the `agreements` row (no parties / terms
/ pricing / documents / bc_links / exceptions, event `processed=false`).

### Fixed
- Pop `id` and `created_at` out of the `model_dump()` payload before
  feeding it to `$set`; `$setOnInsert` now exclusively owns the
  immutable seeds. All four `_upsert_*` helpers patched.
- Wrapped `process_event`'s post-normalize section in a defensive
  `try/except`: a partial failure now flips the event to
  `processed=true` with a captured error string, opens a high-severity
  `normalization_failed` exception with stage=`post_normalize`,
  error_type, error message, and truncated traceback, and emits an
  ERROR-level log under `services.contracts.contract_intelligence_service`.
  Stuck-event recovery is now self-driving.
- `commit_one` (CLI + HTTP) now reports `post_normalize_failed` as a
  proper row error rather than masking it as silent success.

### New regression coverage
- `tests/test_contracts_upsert_path_conflict.py` — unit-level guard
  that records every `update_one` payload and asserts no immutable
  field appears in both halves. Catches the bug at the unit layer
  without spinning up a real Mongo container, so mongomock can't
  hide it again.

### Suite
- 175 passed, 8 skipped, 1 xfailed (was 172/7/1 before hotfix; +3
  new path-conflict tests, pricing-side test gracefully skips when
  the synth fixture doesn't produce a pricing row).
- Zero existing-test regressions.




## [2026-02-XX] Contract Intelligence Phase 4C(a) — Navigator Import Endpoint + UI Drop Zone

**Scope:** Charlie can upload a Navigator AI Metadata Export directly
through the Contract Intelligence page; no SCP, `docker cp`, or VM
file handling required. Default is dry-run; commit is a deliberate
second click. CLI and HTTP share one service so they cannot drift. No
DocuSign SDK install, no live envelope fetch, no webhook activation,
no BC writes, no PDF body extraction.

### New shared service: `backend/services/contracts/navigator_import.py`

- `parse_upload(data, filename, content_type, sheet)` — size-capped,
  extension-validated bytes → row dicts. Raises `NavigatorImportError`
  (subclass of `ValueError`) on every client-recoverable failure.
- `dryrun_rows(rows, *, db, filename)` — async; computes `would_create`
  vs. `would_update` against the live `agreements` collection.
- `commit_rows(rows, *, db, filename)` — async; routes rows through
  `ContractIntelligenceService.record_event` + `process_event`.
  Idempotent (`navigator::{envelope_id}` event id; replays no-op).
- Returns dataclass-backed `ImportSummary` with rollup counts and a
  per-row report list.
- Size cap: env var `CONTRACT_NAVIGATOR_IMPORT_MAX_BYTES` (default 5 MB,
  hard ceiling 50 MB).

### New endpoint: `POST /api/contracts/navigator/import`

- Admin-gated via `services.auth_deps.require_admin` (403 otherwise).
- Multipart `file`. Accepts `.xlsx`, `.xlsm`, `.csv`, `.json`.
- Default `?commit=false` (dry-run); pass `?commit=true` to persist.
- Optional `?sheet=<name>` for xlsx with multiple worksheets.
- Returns the `ImportSummary` shape (full row-level diagnostics).
- Oversize → 413; bad shape → 400.

### CLI refactor: `backend/scripts/contracts_import_navigator.py`

- Now a thin wrapper around the shared service. CLI args + output
  unchanged.
- Backwards-compat adapter exposes the legacy `load_rows`,
  `dryrun_row`, `commit_row` helpers so prior tests pass without edits.
- All 16 CLI tests still green.

### UI: `frontend/src/pages/ContractIntelligencePage.jsx`

- Added 6th tab "Import" (`data-testid="tab-navigator-import"`).
- `NavigatorImportTab` component: drag-and-drop file zone, client-side
  extension validation, "Run Dry-Run" → preview card → "Commit Import"
  with confirm dialog summarizing would_create/would_update.
- Per-row table shows envelope id, status, title, P/T/Pr/D counts, and
  outcome (committed / skipped / error / would import). Rows with
  ambiguity exceptions get a yellow `AMBIGUOUS` badge.
- Lucide icons (no emoji), shadcn primitives, sonner toasts.
- All interactive elements carry `data-testid` attributes for E2E.

### Tests

- New `tests/test_contracts_navigator_import_endpoint.py` — 11 tests:
  auth gating, validation (extension/size/missing-file), dry-run
  structured response, xlsx + csv parsing, no-write guarantee in
  dry-run, commit persistence, idempotent replay, dry-run after commit
  → `would_update`, mixed-row error reporting.
- Full Contract Intelligence suite: **172 passed, 7 skipped, 1 xfailed**
  (Phase 4B baseline: 161 passed).
- Zero regressions in normalizer, Connect SIM path, matcher, golden
  fixtures, orchestrator, phase3 / phase3.1, endpoints, models, CLI.

### Documentation

- `/app/memory/BRAGG_DOCUSIGN_VALIDATION_FINDINGS.md` §13 added with
  endpoint contract, request/response shape, UI testid surface,
  remaining items.

### VM deployment

```bash
cd /opt/gpi-hub
git pull
docker compose build backend
docker compose up -d backend
# Verify (same 7-file subset as Phase 4B; new endpoint test requires
# mongomock_motor which is intentionally not in the prod image):
docker compose exec -w /app backend python -m pytest \
    tests/test_contracts_bragg_fixture.py \
    tests/test_contracts_navigator_normalizer.py \
    tests/test_contracts_import_navigator_cli.py \
    tests/test_contracts_matcher.py \
    tests/test_contracts_normalizer.py \
    tests/test_contracts_models.py \
    tests/test_contracts_golden_fixtures.py -v
```
Expected: **114 passed, 7 skipped, 1 xfailed** — identical to Phase 4B
on the VM (CLI suite refactor is regression-clean). The new HTTP
endpoint suite (11 tests) lives at
`tests/test_contracts_navigator_import_endpoint.py` and runs on any
container that has `mongomock_motor` available.

### Not yet shipped (out of Phase 4C(a) scope)

- DocuSign SDK install / live envelope fetch / Connect webhook
  activation.
- Agreement ↔ Document Hub cross-link.
- Suggested-threshold widget.
- Template-side `payment_term_discount` split.
- PDF body extraction (freight / MOQ / commitment / tooling /
  1%-10 discount).




## [2026-02-XX] Contract Intelligence Phase 4B — Navigator import CLI + matcher ambiguity hardening

**Scope:** One-shot Navigator import CLI (dry-run default, idempotent
commit) plus matcher ambiguity detection. Converts 1 of the 2 remaining
Phase 4A xfails. No DocuSign SDK, no HTTP upload endpoint, no webhook
activation, no BC writes, no UI changes, no route changes, no new
dependencies (openpyxl 3.1.5 + pandas 3.0.0 already in the container).

### New CLI: `backend/scripts/contracts_import_navigator.py`

- Accepts `.xlsx` (optional `--sheet`), `.csv`, `.json` (single row,
  `{"row": ...}` wrapper, `{"rows": [...]}` wrapper, or top-level list).
- **Dry-run is the default.** Writes require explicit `--commit`.
- Per-row diagnostics: envelope id, status, title, Navigator UUID,
  party / term / pricing / document / warning counts, inline warning
  codes, commit outcome.
- Commit path reuses `ContractIntelligenceService.record_event` +
  `process_event` — the same orchestrator live Connect webhooks use.
  Matcher + audit + exception pipeline all fire automatically.
- **Idempotency:** deterministic event id `navigator::{envelope_id}`;
  replays are a no-op at the `agreement_events` unique-index layer.
  Manual mappings (`linked_by != "system"`, or `status in
  {confirmed, rejected}`) survive reruns untouched per the existing
  orchestrator replay rule.
- `--limit N` for debugging. Exit codes: 0 clean, 2 unreadable file,
  3 one-or-more row failures.

Usage (VM):
```bash
# Dry-run:
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx
# Commit:
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --commit
```

### Matcher ambiguity hardening: `backend/services/contracts/bc_agreement_matcher.py`

- New env-tunable `CONTRACT_MATCH_AMBIGUITY_BAND` (default `0.02`).
- **Ambiguity detection:** when ≥2 candidates sit within the band of
  the top score AND all clear the propose threshold, the matcher emits
  every candidate as a `proposed` link (never auto-confirmed) and opens
  one high-severity `party_unmatched` exception with
  `details.ambiguous=True`, `details.candidate_bc_nos=[...]`,
  `details.candidate_count`, `details.top_score`, `details.ambiguity_band`.
- **Exact-BC-code short-circuit:** when the repository tags a single
  candidate with `method="exact_no"` (i.e. a direct BC code hit from a
  `bc_customer_code` / `bc_vendor_code` custom field), that candidate
  wins outright. No ambiguity analysis runs.
- No schema change. Only the emitted `(links, exceptions)` shape
  differs in the ambiguity branch. Manual-mapping flows untouched.

### xfail conversion

- **Converted to passing** (Phase 4B fixed):
  - `test_ambiguous_match_emits_both_plus_exception` — ambiguity now
    surfaces both candidates + a structured exception.
  - `test_current_matcher_silently_picks_one` replaced by a canonical
    positive test `test_ambiguous_candidates_emit_proposed_plus_exception`.
- **Still xfail** (external template gate):
  - `test_payment_term_discount_exposed_as_own_term` — requires a
    DocuSign template change to surface the discount as its own custom
    field. Normalizer preserves whatever DocuSign sends.

### Tests

- New `tests/test_contracts_import_navigator_cli.py` — 16 tests
  (loaders, dry-run, commit idempotency, row-error isolation, exit codes).
- Updated `tests/test_contracts_bragg_fixture.py` — ambiguity section
  rewritten; one xfail deleted, one xfail converted to pass.
- Full Contract Intelligence suite: **161 passed, 7 skipped, 1 xfailed**
  (previously 144 passed, 2 xfailed after Phase 4A).
- Zero regressions in normalizer, orchestrator, endpoints, golden
  fixtures, phase3, or phase3.1 suites.

### Documentation

- `/app/memory/BRAGG_DOCUSIGN_VALIDATION_FINDINGS.md` §12 added with CLI
  usage, ambiguity behavior table, xfail inventory post-4B, and
  remaining items before live DocuSign SDK / webhook activation.

### Not yet shipped (explicitly out of Phase 4B scope)

- `POST /api/contracts/navigator/import` HTTP upload endpoint. CLI is
  the current operator interface.
- DocuSign SDK install / live envelope fetch / webhook activation.
- Agreement ↔ Document Hub cross-link. Suggested-threshold widget.
  Template-side `payment_term_discount` split.




## [2026-02-XX] Contract Intelligence Phase 4A — Dual-path normalizer

**Scope:** Payload Shape Reconciliation. DocuSign Connect webhook JSON
and DocuSign Navigator AI Metadata Export rows now feed the same
canonical `NormalizedAgreement` output through a single entry point.
Read-only historical backfill + live webhook paths coexist. No DocuSign
SDK install, no BC writes, no envelope fetch, no webhook activation
changes, no UI, no route changes, no new endpoints.

### Schema additions (additive, non-breaking)
- `Agreement.provider_agreement_id: Optional[str]` — Navigator UUID
  (distinct from envelope id).
- `Agreement.alternate_envelope_ids: List[str]` — secondary envelope ids
  stamped into signed PDF trails.
- `AgreementPricing.location: Optional[str]` — per-line ship-to (e.g.
  "Garden Grove, CA"); extracted from `line_N_location` tabs.

### New service
- `services/contracts/navigator_normalizer.py`:
  - `build_connect_sim_payload(row)` — flat Navigator row → Connect-SIM dict.
  - `normalize_navigator_row(row)` — one-shot Navigator → `NormalizedAgreement`.
  - Handles 54-column Navigator schema, concatenates `value + unit` pairs,
    splits `Parties` on `;`/`|`, maps Navigator `Status="Active"` → canonical
    `"completed"`, emits `source="navigator_adapter"` warnings for any
    schema gap rather than silently dropping data.

### Unified entry point
- `services/contracts/agreement_normalizer.normalize_envelope()` detects a
  flat Navigator row (≥2 signature columns, no Connect wrapper keys) and
  dispatches to the Navigator adapter. Connect SIM path unchanged.

### Connect path enhancements (backfill)
- Reads `envelopeSummary.alternateEnvelopeIds` into the new list field.
- Reads `providerAgreementId` envelope-summary hint and
  `provider_agreement_id` / `agreement_navigator_uuid` custom fields.
- Pricing tab extractor now captures `line_N_location` into
  `AgreementPricing.location`.

### xfail conversions (Bragg fixture)
- **Converted to passing** (Phase 4A fixed):
  - `test_normalizer_can_read_raw_xlsx_row` (flat row dispatch).
  - `test_navigator_uuid_is_first_class_field` (new Agreement field).
  - `test_alternate_envelope_id_captured` (new Agreement field + fixture).
  - `test_pricing_row_has_location_field` (new AgreementPricing field).
- **Still xfail** (explicitly out of Phase 4A scope):
  - `test_ambiguous_match_emits_both_plus_exception` — matcher hardening
    (not schema; deferred to follow-up).
  - `test_payment_term_discount_exposed_as_own_term` — requires DocuSign
    template change; normalizer preserves whatever DocuSign sends.

### Tests
- New `tests/test_contracts_navigator_normalizer.py` — 22 tests covering
  SIM synthesis, end-to-end normalization, unified-dispatch routing,
  negative cases.
- `tests/test_contracts_bragg_fixture.py` — 23 passed, 2 xfailed
  (previously 19 passed, 6 xfailed).
- Full Contract Intelligence suite: 144 passed, 7 skipped, 2 xfailed.
- Zero regressions in Connect-path unit tests or golden-fixture suite.

### Documentation
- `/app/memory/BRAGG_DOCUSIGN_VALIDATION_FINDINGS.md` §11 appended with
  Phase 4A outcomes, live-vs-import path matrix, remaining gaps before
  live DocuSign SDK/webhook activation.

### Not yet shipped
- `POST /api/contracts/navigator/import` bulk upload endpoint — adapter
  is plumbed but no HTTP wrapper. Out of scope per signed Phase 4A.
- Matcher ambiguity fix — out of scope per signed Phase 4A.
- DocuSign SDK / live webhook activation / PDF body fallback — out of
  scope per signed Phase 4A.




## [2026-04-22] v2.5.28 — Lane A Integrity (A1 + A2 + A4 shipped; A3 ready-to-merge)

**Scope:** Three of four Lane A integrity items land. A3 (Phase 4 Path B route deletion) is externally gated on the 7-UTC-day drain clock per signed scope §1; the PR is ready and will merge when the clock matures. Ship order honored the dependency chain.

### A1 — Historical posting-attempts array (shipped)
- **New service** `services/bc_posting_attempts.py`: `build_attempt()`, `next_attempt_n()`, `attempts_push_fragment()`, `record_standalone_attempt()`, `migrate_legacy_bc_posting_error()`.
- **`services/bc_post_claim.py::release_claim`** accepts an optional `attempt=` arg that atomically `$push`es an entry alongside the terminal-state `$set`, so state and audit can never drift.
- **`routers/ap_review.py::post_document_to_bc`** wired on all three release paths (success, BC failure, exception) — every post leaves one attempt entry.
- **`services/ap_auto_post_service.py::attempt_ap_auto_post`** wired on all four paths (success, pending_retry, permanent failure, transient failure) — partial posts land with `status="partial"` not a flat `failed`.
- **`GET /api/ap-review/documents/{doc_id}/bc-status`** response now carries the full `bc_posting_attempts[]` history.
- **Startup migration** idempotently synthesizes legacy entries for any doc with `bc_posting_error` set but no `bc_posting_attempts` array.
- **Frontend** new `PostingAttemptsHistory.jsx` component: collapsed by default, auto-expands on `bc_posting_status ∈ {failed, partial, pending_retry}` per signed UX spec; timestamp, actor, truncated error with expand-for-full, gate_id when blocked pre-submission, newest-first.
- **Tests** `tests/test_posting_attempts_history.py` — 12/12 green (shape invariants, error truncation, next_attempt_n, append-only semantics, release_claim integration, legacy migration idempotency, auto-post success/partial paths).

### A2 — Retry/backoff on BC 429/503 (shipped)
- **`services/business_central_service.py`** new `bc_http_with_retry(send, op, max_attempts)` helper + `BCRetriesExhausted` exception.
- Retries 429 / 502 / 503 / 504 plus `httpx.ConnectError / ConnectTimeout / ReadTimeout / ReadError / PoolTimeout / WriteTimeout`. Non-retriable 4xx passes through immediately.
- 3 attempts max, base 1 s / 2 s / 4 s backoff, ±25 % jitter. Env-tunable via `BC_RETRY_MAX_ATTEMPTS` / `BC_RETRY_BASE_SECONDS`.
- Wrapped the header POST in `create_purchase_invoice` and per-line POST in `_add_invoice_lines`. On exhaustion, `create_purchase_invoice` returns `{success: False, retries_exhausted: True, retry_reasons: [...]}` so the caller writes a single honest attempt entry.
- **Tests** `tests/test_bc_retry_backoff.py` — 9/9 green (immediate 2xx return, 4xx passthrough, 429→200 recovery, exhaustion at 3×503, exception retriability, `max_attempts=1` disables retry, end-to-end `create_purchase_invoice` retries_exhausted shape, jitter band sanity).

### A4 — Pre-claim `workflow_engine.advance_workflow` (shipped)
- **New workflow events** `ON_BC_POSTING_STARTED`, `ON_BC_POSTED`, `ON_BC_PARTIAL_POSTED`, `ON_BC_POST_FAILED` in `services/workflow_engine.py`.
- **New workflow states** `BC_POSTING_IN_PROGRESS`, `BC_POSTED`, `BC_POST_PARTIAL`.
- **Transitions added** to the `AP_INVOICE` workflow:
  - `APPROVED` or `READY_FOR_APPROVAL` + `ON_BC_POSTING_STARTED` → `BC_POSTING_IN_PROGRESS`
  - `BC_POSTING_IN_PROGRESS` + `ON_BC_POSTED` → `BC_POSTED`
  - `BC_POSTING_IN_PROGRESS` + `ON_BC_PARTIAL_POSTED` → `BC_POST_PARTIAL`
  - `BC_POSTING_IN_PROGRESS` + `ON_BC_POST_FAILED` → `APPROVED` (retry-eligible)
  - `BC_POSTED` / `BC_POST_PARTIAL` / `EXPORTED` + `ON_ARCHIVED` → `ARCHIVED`
  - `BC_POST_PARTIAL` + `ON_RETRY` → `APPROVED`
- **`routers/ap_review.py::post_document_to_bc`** now fetches doc → advances engine via `ON_BC_POSTING_STARTED` → folds new `workflow_status`/`workflow_history` into the claim's atomic `$set`. On claim rejection (race), the engine state is reverted so no doc is stranded in `BC_POSTING_IN_PROGRESS` without an in-flight post. Post-result paths advance the engine via the appropriate terminal event, folded into `release_claim`'s `extra_set` alongside the attempt entry.
- **Tests** `tests/test_bc_posting_engine_lifecycle.py` — 10/10 green (event/state enum presence, valid-state transitions, invalid-state rejection, happy/partial/hard-failure lifecycles, no-jump-back invariant, history recording with actor+metadata).

### A3 — Phase 4 Path B route deletion (ready; gated)
Per signed scope §1 clock semantics, A3 merges when `phase_4_gate.gate_met=true` for 7 consecutive UTC days AND regression green. Clock starts from the v2.5.28 deploy. See `/app/memory/PATH_B_REMOVAL_PLAN.md` for the exact deletions. A3 PR prepped as a single atomic commit that can be executed by Chad when the drain matures.

### Regression
Full suite: **153 passed, 3 skipped** across 11 test files. No regressions. One existing `test_bc_line_routing.py` fake-response class made the retry wrapper trip on `.extensions` — guarded with `hasattr` so pre-existing tests stay unaware of the new metadata surface.

### Deploy note (remote VM)
`cd /opt/gpi-hub && git pull && docker compose build --no-cache && docker compose up -d`. Startup log should show one-time legacy migration for existing docs with `bc_posting_error` set.




## [2026-04-22] v2.5.27 — Phase 4 Gate Projection + 422 Blind-Spot Disclosure

**Scope:** Three user-directed follow-ups on top of v2.5.26:
1. **Drain-window confirmation** — collapse the "is Phase 4 safe?" check into a single boolean that can be answered with one curl. User's directive: "confirmation during the drain window whether any callers still remain".
2. **Explicit 422 observability limitation** — disclose the Pydantic-before-wrapper blind spot in three places (response payload, `_deprecate` docstring, removal plan). User's directive: "I want truthfulness about that blind spot".
3. **Backlog reorder** — retry/backoff and posting-attempt history sit ahead of server decomposition. User's directive: "closer to workflow integrity than server decomposition".

Explicitly **not** done in this release per user directive: no Slack/email deprecation alert (deferred until after Phase 4 removal ships).

### A. Phase 4 gate projection (`routers/admin.py`)
`GET /api/admin/deprecation-metrics` response now carries a `phase_4_gate` object:
```json
{
  "phase_4_gate": {
    "gate_met": true,
    "gate_description": "Zero hits on all six AP mutation Path B templates across 7 consecutive days AND regression suite green.",
    "window_days": 7,
    "window_since_day_bucket": "2026-04-15",
    "ap_mutation_routes_monitored": [ ...6 templates... ],
    "total_hits_in_window": 0,
    "hits_by_template": { "...": 0, ... },
    "offending_callers": [],
    "action_if_gate_not_met": "Identify caller via last_client_host + last_user_agent, repoint to the canonical Path A URL, then restart the 7-day drain clock.",
    "observability_limitations": [ ...3 items, first mentions 422... ]
  }
}
```

Properties:
- The 7-day window is hard-coded inside the endpoint — the caller's `days=N` query param only affects the detailed `route_totals` breakdown, never the gate window. Prevents accidental narrowing.
- `offending_callers[]` carries `last_client_host` and `last_user_agent` so any outlier is identifiable in one read.
- `gate_met = True` only when all six templates have zero hits inside the 7-day window.

### B. 422 blind-spot disclosure (in three places)
Pydantic body validation and HTTP method matching run **before** the `routers/workflows.py::_deprecate()` wrapper. Therefore `db.deprecation_hits` only records Path B requests that pass Pydantic/method validation. HTTP 422 responses (malformed bodies) and 405 responses (wrong method on a registered path) never reach the counter.

Impact in practice: narrow. Real production callers (BC extensions, AL scripts, automated flows, our own frontend) send well-formed bodies; 422s typically originate from ad-hoc human testing. But we say so explicitly rather than let the gate be perceived as a complete census.

Disclosure locations (all added in v2.5.27):
- `_deprecate()` docstring in `routers/workflows.py`
- `deprecation_metrics()` docstring in `routers/admin.py`
- `phase_4_gate.observability_limitations[]` field in the response payload
- `/app/memory/PATH_B_REMOVAL_PLAN.md` §2c "Observability limitation — disclosed truthfully" (with a table of covered vs uncovered scenarios)

### C. Backlog priority shift (per user directive)
PRD and Next-Actions list reorder: retry/backoff on BC 429/503 and historical posting-attempts array sit **ahead of** `server.py` decomposition. Both closer to workflow integrity.

### Tests
- NEW `tests/test_deprecation_metrics.py` — **7/7 passing**:
  - 401 without JWT (auth regression)
  - 422 on `days=0` (query validator)
  - Response shape guarantees (`phase_4_gate` + 422 disclosure literal)
  - `gate_met=true` on empty collection
  - `gate_met=false` on a single in-window hit, with caller identification
  - `gate_met=true` when the only hit is outside the 7-day window
  - Gate window immune to caller's `days=N` narrowing
- Full regression: **122 passed, 3 skipped** across all suites.




## [2026-04-22] v2.5.26 — Path B Observability + Partial-Post Integrity + Phase 4 Plan

**Scope:** Three user-directed deliverables on top of v2.5.25:
1. Server-side observability for deprecated Path B hits (directive: "do not add client-side console warning; add logging/metrics").
2. End-to-end partial-post integrity on the auto-post path (directive: "partial-post detection is a financial-integrity concern and matters more than decomposition").
3. Concrete, measurable Phase 4 removal plan for Path B (directive: "temporary deprecations must not become permanent drift").

### A. Path B observability (`routers/workflows.py`, `routers/admin.py`)
- `_deprecate()` wrapper extended to:
  - Log a `WARNING` line on every Path B hit: `[DEPRECATED] METHOD /path -> canonical /path status=N client=IP auth=BOOL ua=STRING`.
  - `$inc` a counter in `db.deprecation_hits`, **keyed by route template** `(method, deprecated_path_template, day_bucket)` so hits with different `doc_id` substitutions collapse into one row.
  - Fire-and-forget on persistence failure — never block the caller's response.
- New endpoint `GET /api/admin/deprecation-metrics?days=N` (admin-gated via `require_admin`): returns route totals + daily breakdown, sorted by hit count desc. Used as the hard gating signal before Phase 4 removal.
- Headers (`X-Deprecated`, `X-Deprecated-Sunset`, `X-Deprecated-Use`) still attached to every response including HTTPException paths.

### B. Partial-post integrity on the auto-post path (`routers/gpi_integration.py`)
**Pre-existing silent bug found and fixed:**
- `create_purchase_invoice_from_document` (called from `ap_auto_post_service.attempt_ap_auto_post`) previously based `result["success"]` solely on BC *header* creation. If `add_purchase_invoice_lines` returned `added=0, total=N>0`, the doc was marked `bc_posting_status="posted"` and `workflow_status="posted"` while BC held only an orphan empty draft.
- Now mirrors the detection already in `services/business_central_service.create_purchase_invoice`:
  - Detects `lines_added < lines_total`.
  - Best-effort delete of the orphan draft header via `bc_service._try_delete_draft_invoice`.
  - Flips the returned dict to `success=False, error="partial_post", partial_post=True, error_message="partial_post: ..."`.
  - Hub doc write-back records `bc_purchase_invoice.success=False, lines_added, lines_total, error_message`, so downstream auto-post falls through to the failure branch (`bc_posting_status="pending_retry"`, NOT `"posted"`).
- Single failure contract shared between both BC write entry points (manual `POST /api/ap-review/documents/{id}/post-to-bc` and auto-post via `ap_auto_post_service`).

### C. Phase 4 removal plan (`/app/memory/PATH_B_REMOVAL_PLAN.md`)
Measurable gating criterion, exact symbols/routes to delete, rollback path, and sequencing:
- Exact six Path B AP mutation registrations to delete in `routers/workflows.py`.
- Three dead orphan functions in `server.py` L6590–6760 (`start_approval_generic`, `approve_generic`, `reject_generic`) queued for deletion (confirmed no callers via grep).
- Hard gate: zero hits on all six AP mutation templates in `/api/admin/deprecation-metrics?days=7` for 7 consecutive days, AND full pytest suite green.
- Rollback: pure subtraction, revertable by re-adding six `add_api_route` calls.

### Tests
- `tests/test_partial_post_detection.py` (new) — **4/4 passing**:
  - `bc_service` flips success=False when lines rejected (patched httpx).
  - `bc_service` keeps success=True when all lines accepted.
  - Auto-post path `create_purchase_invoice_from_document` flips success=False + records partial truth in hub doc.
  - `ap_auto_post_service.attempt_ap_auto_post` never writes `bc_posting_status="posted"` / `workflow_status="posted"` on partial post (true end-to-end proof).
- Full regression green: 115 passed, 3 skipped across `test_auth_enforcement`, `test_bc_post_claim`, `test_bc_line_routing`, `test_pi_preflight_reconcile`, `test_vendor_profile_fallbacks`, `test_ap_path_consolidation` (36), `test_partial_post_detection` (4).

### What did NOT happen (intentionally)
- No client-side console warning added (user directive). Observability is entirely server-side via logs + Mongo counter + admin metrics endpoint.
- No changes to Path A routes or frontend `lib/api.js` — still pointing at canonical surface as shipped in v2.5.25.
- No deletion of Path B routes in this release — that is the explicit Phase 4 action gated by the drain metric.




## [2026-04-21] v2.5.25 — AP Path Consolidation (Phases 2 + 3)

**Scope:** Completes AP_PATH_CONSOLIDATION.md Phases 2 and 3. Eliminates the dual AP workflow paths documented in the 2026-04-21 engineering review (Finding #8). Pure backend/frontend hygiene — no user-facing behavior change.

### Canonical Path A surface (`routers/ap_review.py`)
Six new mutation endpoints, each gated by `Depends(get_current_user)` JWT and delegating to the authoritative handlers in `services/workflow_handlers.py`:
- `POST /api/ap-review/documents/{doc_id}/set-vendor`
- `POST /api/ap-review/documents/{doc_id}/update-fields`
- `POST /api/ap-review/documents/{doc_id}/override-bc-validation`
- `POST /api/ap-review/documents/{doc_id}/start-approval`
- `POST /api/ap-review/documents/{doc_id}/approve`
- `POST /api/ap-review/documents/{doc_id}/reject`

Every transition now flows through a single `WorkflowEngine.advance_workflow` callsite regardless of entry point.

### Path B deprecation (`routers/workflows.py`)
- Six `/api/workflows/ap_invoice/{id}/{action}` routes marked `deprecated=True` in OpenAPI.
- New `_deprecate(handler, canonical_path)` wrapper attaches three response headers on **every** response — including HTTPException paths (404/400):
  - `X-Deprecated: true`
  - `X-Deprecated-Sunset: next-release`
  - `X-Deprecated-Use: <canonical Path A URL>`
- Query-only routes (`status-counts`, `*-pending`, `metrics`) untouched — no drift risk.

### Frontend (`frontend/src/lib/api.js`)
- `setVendor`, `updateFields`, `overrideBcValidation`, `startApproval`, `approveDocument`, `rejectDocument` repointed to `/api/ap-review/documents/{id}/{action}`.
- Request bodies normalized to match the canonical Pydantic models (`SetVendorRequest`, `UpdateFieldsRequest`, `BCValidationOverrideRequest`, `ApprovalActionRequest`).

### Tests
- New `tests/test_ap_path_consolidation.py` — **36/36 passing**:
  - Path A route registration (6)
  - Path B retained + deprecated flag in OpenAPI (12)
  - Path A JWT enforcement (401 without, 400/404 with) (12)
  - Path B X-Deprecated headers on error responses (6)
- No regression: `test_auth_enforcement.py`, `test_bc_post_claim.py`, `test_bc_line_routing.py`, `test_pi_preflight_reconcile.py`, `test_vendor_profile_fallbacks.py` — all green (75/75).

### Deferred to Phase 4 (next release)
- Delete the Path B AP mutation routes and `start_approval_generic` / `approve_generic` / `reject_generic` dead orphan functions in `server.py` L6590–6760.
- Remove now-unused `APWorkflowsPage.js` / `WorkflowQueue.js` AP paths.




## [2026-04-21] v2.5.24 — Security Hardening (Reviewer Findings #1, #3, #4 bundle)

**Scope:** Three reviewer-flagged defects resolved in one release plus a decision memo for the fourth:
1. **Line-item BC routing** (Finding: "posts to BC using a single FREIGHT item code for every line")
2. **Partial-post silent success** (Finding: header-created + lines-rejected reported as success)
3. **AP path consolidation decision** (Finding #8: dual `/ap-review/` vs `/workflows/ap_invoice/` paths)
4. **Auth enforcement + startup validator** (Findings #1, #10: no auth, JWT default, hardcoded admin/admin)

### Fix 1 — Per-line BC routing honors preflight classification (`services/business_central_service.py`)
- `_add_invoice_lines` rewritten: each line's `lineType` + `lineObjectNumber` (from `build_smart_pi_lines`) is now respected.
  - `Account` → resolves GL number → BC `accountId` (GUID) → `POST {lineType:"Account", accountId:...}`
  - `Item` → resolves item number → BC `itemId` → `POST {lineType:"Item", itemId:...}`
  - Per-call caches so N lines with the same GL don't trigger N lookups.
- **No more silent FREIGHT fallback:** an unresolvable `lineObjectNumber` produces a per-line error; BC is NOT called with a substituted Item. Legacy `BC_DEFAULT_ITEM_CODE` fallback still runs ONLY when a line arrives with neither lineType nor lineObjectNumber (truly unclassified) — and emits a WARNING log so the gap is visible.
- New helper `_get_account_id_by_number` mirrors the existing `_get_item_id_by_code` pattern.

### Fix 2 — Partial-post detection in `create_purchase_invoice`
- After `_add_invoice_lines` returns, compare `added` vs `total`. If any line failed:
  - Return `{"success": False, "error": "partial_post", ...}` so downstream flow marks the doc `failed` not `posted`.
  - Best-effort DELETE of the orphan draft header in BC (supported only while Draft; logged either way).
  - Response includes `lineErrors[]`, `orphan_header_deletion` status, BC doc id/number for manual cleanup if the delete fails.
- Previously: header-created + all-lines-rejected returned `success=True, linesAdded=0`, and the doc was marked "posted" while BC held an empty draft. This was a silent bookkeeping trap.

### Fix 3 — AP path consolidation decision (`/app/memory/AP_PATH_CONSOLIDATION.md`)
- Declared **`/api/ap-review/*` the canonical AP workflow** going forward. All 5 hardening releases (v2.5.20–24) landed there; `/workflows/ap_invoice/*` serves a removed frontend page.
- 5-phase consolidation plan documented with bounded effort (~3 days total), rollback path, and explicit Phase 5 adoption of `workflow_engine.py` state transitions into Path A.

### Fix 4 — Auth enforcement + startup validator (Findings #1 + #10)

**New modules:**
- `services/auth_deps.py` — single source of truth for:
  - `hash_password` / `verify_password` (bcrypt, constant-time)
  - `create_access_token` / `decode_access_token` (PyJWT, 8-hour TTL, explicit `type: "access"` claim)
  - `get_current_user` FastAPI dependency — extracts token from `Authorization: Bearer` OR `access_token` cookie, decodes, validates, loads user from `db.users`, raises 401 on any failure
  - `require_admin` — layers role check on top of `get_current_user`
  - `seed_admin_user` — idempotent bcrypt-hashed admin seed from `ADMIN_EMAIL` + `ADMIN_PASSWORD` env
  - **Refuses to operate** with any known-insecure `JWT_SECRET` default (`gpi-hub-secret-key`, `changeme`, `secret`, empty)
- `services/startup_validator.py` — runs at import time. Crashes the process with a clear checklist if `JWT_SECRET` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `MONGO_URL` are missing or set to known-insecure defaults.

**Replaced:**
- `routers/auth.py` — new secure login/me/logout. Login now bcrypt-verifies against MongoDB `users` collection (no more hardcoded `admin/admin`). Returns JWT in both response body AND httpOnly cookie for flexibility. `/me` is now `Depends(get_current_user)` (the pre-fix version returned a hardcoded dict).
- `main.py` — loads `.env` → runs `validate_startup_secrets()` → registers `app.state.db` → seeds admin user on every boot (idempotent; re-hashes if env password rotated).

**Protected endpoints (high-risk mutating routes the reviewer flagged):**
- `POST /api/admin/backfill-ap-mailbox` — now `Depends(require_admin)`
- `POST /api/admin/backfill-sales-mailbox` — now `Depends(require_admin)`
- `POST /api/ap-review/documents/{id}/post-to-bc` — now `Depends(get_current_user)`

**Deferred to follow-up PR (scoped but not in this release):**
- Apply `Depends(get_current_user)` to the remaining 140+ mutating routes (needs coordinated frontend AuthContext change to inject the token on every fetch).
- Brute-force rate limiting on `/auth/login` (per-IP + per-email).
- Frontend AuthContext reset on 401 (today the UI silently fails).

**Env additions required on production VM (via docker-compose.yml):**
- `JWT_SECRET` — 64+ char random hex (`python -c "import secrets; print(secrets.token_hex(48))"`)
- `ADMIN_EMAIL` — seed admin email
- `ADMIN_PASSWORD` — seed admin password (bcrypt-hashed on first boot)

**⚠ DEPLOYMENT WARNING:** The startup validator will **crash the backend** on the next deploy if any of these env vars are missing. This is intentional. Add them to `docker-compose.yml` before `git pull && docker compose build`.

### Testing
- **78/78 pytests pass** across all of today's fixes:
  - `test_auth_enforcement.py` — 26 tests (hashing, tokens, startup validator, live login flow, protected-endpoint rejections)
  - `test_bc_line_routing.py` — 10 tests (per-line routing, partial-post detection)
  - `test_bc_post_claim.py` — 18 tests (atomic claim + real concurrency)
  - `test_pi_preflight_reconcile.py` — 16 tests (line reconciliation + invoice total sanity)
  - `test_vendor_profile_fallbacks.py` — 8 tests (profile learning fallback chain)
- Live backend verified: login → JWT → `/me` → 200; anonymous → 401; wrong password → 401; unknown email → 401.

### Known follow-ups
- REFACTOR_PLAN.md Phase 3 still outstanding (`server.py` decomposition)
- Sales order BC write-back closure (Finding #5)
- Inventory module (Finding #7)
- Per-field extraction confidence (Finding #4 discussed in reviewer's writeup but not in my remediation scope today)




## [2026-04-21] v2.5.23 — Atomic BC Post Claim (Race Condition Fix, P0 Financial Integrity)

**Problem (from external engineering review, Finding #2):**
Three BC-write paths used a non-atomic "update status, then call BC" sequence:
1. `services/auto_post_service.attempt_auto_post` (AP auto-post)
2. `services/auto_post_service.attempt_auto_create_sales_order` (SO auto-create)
3. `routers/ap_review.post_document_to_bc` (manual Post-to-BC button)

All three were racy. Two concurrent triggers — background poller + manual retry, two worker pods, UI double-click, browser retry — could both:
1. Read the document and see an eligible status
2. Both set `bc_posting_status` to an in-flight value via `update_one`
3. Both call `bc_service.create_purchase_invoice` / `create_sales_order`

Result: **duplicate purchase invoices or sales orders in Business Central** — a real-money financial defect requiring manual correction.

**Fix — shared atomic claim primitive (`services/bc_post_claim.py`):**
- `claim_for_bc_post(db, doc_id, target_state, worker_id, extra_set)` — single `find_one_and_update` that:
  - Rejects documents in terminal success states (`posted`, `created`, `auto_posted`) to prevent re-posting.
  - Rejects documents already claimed by another worker (`auto_posting`, `posting`, `auto_creating`) unless their claim has exceeded the TTL (default 300s, env-tunable via `BC_POST_CLAIM_TTL_SECONDS`).
  - On success, atomically sets the new state + `bc_posting_claimed_at` + `bc_posting_claimed_by` + any caller-provided `extra_set` fields.
- `release_claim(db, doc_id, final_state, extra_set)` — finalizes the claim (success or failure path), clears the `claimed_*` fields idempotently.
- **Self-healing:** If a worker crashes mid-BC-call, the in-flight claim becomes reclaimable by any other worker after TTL — no document stranded forever.
- **Legacy-row tolerance:** Documents left in an in-flight state by pre-fix code (no `bc_posting_claimed_at`) are treated as stale and reclaimable on first retry.

**All three call sites refactored:**
- `attempt_auto_post` → claims with `target_state="auto_posting"`, releases to `posted` or `auto_post_failed`.
- `attempt_auto_create_sales_order` → claims with `target_state="auto_creating"`, releases to `created` or `auto_create_failed`.
- `post_document_to_bc` (manual) → claims with `target_state="posting"`, returns HTTP 409 with explanatory message if another worker holds the claim (UX signal that prevents confused double-clicks).

**Verified:**
- 18/18 pytests in `tests/test_bc_post_claim.py` pass, including:
  - 15 filter-logic tests (every state × TTL × holder combination)
  - **3 real-MongoDB concurrency tests** that launch 50 parallel asyncio claimers at a single document and assert exactly **1 wins**, with the other 49 returning `reason="active_claim"`. These are the regression tests that would have caught the pre-fix defect.
  - Terminal-state protection: 30 concurrent claims against an already-posted doc → all 30 rejected with `ALREADY_TERMINAL`, DB state unchanged.
  - Retry path: released-to-failed → new thundering-herd retry wave → exactly 1 wins.
- 42/42 pytests pass across reconciliation + fallback + claim suites combined.
- Lint clean on new code; backend service healthy.

**Other non-atomic posting/creation paths audited:**
The three patched sites are the only BC-write paths in the backend. Grep for all `bc_service.create_*` calls confirms each is now gated by `claim_for_bc_post`. Background poll loop (`email_service.py`) queues docs for `attempt_auto_post` which goes through the claim — the poller itself holds no BC writes directly.

**User impact (production VM):**
After `cd /opt/gpi-hub && git pull && docker compose build --no-cache && docker compose up -d`, the system is safe against:
- UI double-click posting
- Two worker pods (future horizontal scaling)
- Background poller colliding with manual retry
- Crashed-worker recovery (automatic after TTL)
- Any sequence of concurrent attempts at the same doc

Duplicate BC records from race conditions are eliminated as a defect class.

**Schema additions to `hub_documents`:**
- `bc_posting_claimed_at` (ISO-8601 string or null) — when the current in-flight claim was acquired
- `bc_posting_claimed_by` (string or null) — worker id that holds the claim

No migration required — fields default to null on first write; legacy docs in in-flight states are handled by the "stale / no claimed_at" fallback clause of the filter.




## [2026-04-20] v2.5.22 — Pre-existing BC API `$select` Bug + Manual Profile Override

**Two issues surfaced during v2.5.21 live validation on XPOLOGI (`76410e9e`):**

1. **`fetch_vendor_invoices_from_bc` has been 400-ing on this BC tenant since day one.**
   ```
   BC API 400: Could not find a property named 'totalAmountExcludingTax' 
   on type 'Microsoft.NAV.purchaseInvoiceLine'
   ```
   The `$expand=purchaseInvoiceLines($select=...,totalAmountExcludingTax)` selected a header-level field on the line sub-entity. Valid field is `amountExcludingTax`. Every open-invoice line-pattern learning request has been silently failing — affecting every vendor, not just XPOLOGI.

2. **This BC tenant doesn't expose `postedPurchaseInvoices` on `/api/v2.0/`** (404). My v2.5.21 Tier B fallback can't help tenants whose posted invoices live only on v1.0 or a custom API page. Without line-level historical data, the profile builder legitimately cannot learn a default GL for a vendor — so reviewers need a way to teach it directly.

**Fixes:**

1. **`services/vendor_invoice_profile_service.fetch_vendor_invoices_from_bc`** — line `$select` corrected: `totalAmountExcludingTax` → `amountExcludingTax`. Profile builder now successfully learns from open-invoice lines on this BC tenant. Benefits every vendor with open PIs, not just XPOLOGI.
2. **`fetch_vendor_posted_invoices_from_bc`** — 404 response now logged at DEBUG level instead of WARNING (it's a tenant-config reality, not an error), and falls through cleanly to the other fallback tiers.
3. **NEW** `POST /api/ap-review/vendor-profile/{vendor_no}/overrides` — reviewers can set `default_line_type`, `default_gl_account`, `default_item_code`, and `description_pattern` directly. Stored in the profile cache with `sources.manual_override` provenance (who set it, when, which fields) for auditability. Body: `{"default_gl_account": "60500", "actor": "admin"}` — only the keys provided are updated, the rest stay intact.

**Verified:**
- 24/24 pytests pass across reconciliation + fallback suites
- Backend healthy, 13 routes on `ap_review_router`, imports clean
- Lint clean on new code

**User impact (XPOLOGI demo path):**
After redeploy, run a one-shot curl to teach the system XPOLOGI's GL, then re-run preflight:
```bash
curl -s -X POST "http://localhost:8080/api/ap-review/vendor-profile/XPOLOGI/overrides" \
  -H "Content-Type: application/json" \
  -d '{"default_gl_account":"60500","actor":"admin"}' | jq

curl -s "http://localhost:8080/api/ap-review/pi-preflight/76410e9e-d6bb-4957-b4fb-6b4a46644037" \
  | jq '{default_gl: .profile_summary.default_gl_account, fallback_warnings: [.deviations[] | select(.type=="default_fallback")] | length, line_sources: [.planned_lines[].source] | unique}'
```
Expected: `default_gl: "60500"`, `fallback_warnings: 0`, `line_sources: ["vendor_profile_gl"]`. The audit trail (`sources.manual_override.set_by/set_at/fields`) is visible via `GET /api/ap-review/vendor-profile/XPOLOGI`.




## [2026-04-20] v2.5.21 — Vendor Profile Learns from Posted Invoices (Empty-GL Fix)

**Problem surfaced from v2.5.20 preflight output on XPOLOGI doc `76410e9e`:**
Even after line-reconciliation corrected the freight math, the preflight still emitted 4× `default_fallback` warnings — every line falling back to env_default GL `60500` despite the vendor profile reporting `bc_invoices_analyzed: 1108`.

```json
"profile_summary": {
  "default_gl_account": "",           ← empty, despite 1108 historical PIs
  "sample_count": 1108
}
```

**Root cause:**
`fetch_vendor_invoices_from_bc` queries only BC's `purchaseInvoices` endpoint (open/draft records). For vendors whose invoices are immediately posted — freight carriers (XPOLOGI), utilities, high-volume AP — this endpoint returns 0 because there are no open drafts. The 1108 historical invoices live on the separate `postedPurchaseInvoices` endpoint, which the profile builder never queried. Result:
- `bc_invoices = []` (API open-endpoint empty)
- `line_patterns = {}` (no lines to analyze)
- `default_gl_account = ""` (falls through to `[{}]` sentinel)
- Every PI line uses env_default GL with `default_fallback` warning

The `bc_reference_cache` aggregation fallback captured header stats (`sample_count: 1108`, amount stats, po_rate) but header fields only — no line-level data.

**Fix — three-tier learning fallback chain in `build_vendor_profile`:**

1. **NEW `fetch_vendor_posted_invoices_from_bc`** (`services/vendor_invoice_profile_service.py`):
   Queries BC's `postedPurchaseInvoices` with `$expand=postedPurchaseInvoiceLines(...)` when the open endpoint is empty. Normalizes `postedPurchaseInvoiceLines` → `purchaseInvoiceLines` so `_analyze_line_patterns` consumes both uniformly. Includes a two-step header+lines fallback (`_fetch_posted_invoices_lines_fallback`) for BC tenants that reject `$expand` on posted invoices (HTTP 400).

2. **NEW `_extract_lines_from_local_history`**:
   When both BC endpoints are empty/unreachable, harvests `bc_pi_lines_posted` from our own successful postings in `hub_documents` and re-shapes them as synthetic invoice records. These are authoritative: we know the posting succeeded. Feeds `_analyze_line_patterns` via the same code path.

3. **Fallback order in `build_vendor_profile`:**
   - A. Open/draft `purchaseInvoices` (pre-existing, unchanged for active vendors)
   - B. `postedPurchaseInvoices` (NEW — fills XPOLOGI-class gap)
   - C. Local `bc_pi_lines_posted` (NEW — works in air-gapped/creds-down scenarios)
   - D. `bc_reference_cache` header stats (pre-existing, amount/po_rate only)

**Verified:**
- 8 new pytests in `tests/test_vendor_profile_fallbacks.py` — all green. Covers: empty history, malformed docs, synthetic re-shaping, end-to-end line-pattern extraction, each fallback tier fires in order, open-invoices take precedence (no unnecessary API calls), whiteout yields safe empty GL.
- Combined 24/24 pytests across reconciliation + fallback suites.
- Backend service healthy (`/api/health` 200).

**User impact (production VM):**
After `cd /opt/gpi-hub && git pull && docker compose build --no-cache && docker compose up -d`, rebuild the XPOLOGI profile:
```bash
curl -s -X POST "http://localhost:8080/api/ap-review/vendor-profile/XPOLOGI/refresh" | jq
curl -s "http://localhost:8080/api/ap-review/pi-preflight/76410e9e-d6bb-4957-b4fb-6b4a46644037" \
  | jq '{default_gl: .profile_summary.default_gl_account, warnings: [.deviations[] | select(.type=="default_fallback")] | length}'
```
Expected: `default_gl_account` populated with XPOLOGI's most-common historical GL, `default_fallback` warnings drop to 0 (lines now source from `vendor_profile_gl` instead of `env_default`). Every AP reviewer stops seeing the "no vendor history available" warning for every freight carrier line.




## [2026-04-20] v2.5.20 — PI Line Reconciliation + Invoice-Total Sanity Gate

**Problem surfaced from demo prep (XPOLOGI freight invoice `76410e9e`):**
`pi-preflight` returned `ready: true` for an AP invoice whose `planned_lines` summed to **$715,398.29** vs the actual invoice total of **$649.97** — a 1000× discrepancy that would have posted a catastrophic purchase invoice to Business Central.

**Root cause — three layers of missing reconciliation:**
1. **LLM extraction** (`invoice_extractor.py`): For freight carrier invoices with weight/class/rate columns, the LLM populated `{quantity: 2600 (weight), unit_price: 277.68 (garbage), total: 7219.68 (correct)}`. `quantity × unit_price ≠ total`, but the trio was stored as-is.
2. **PI builder** (`vendor_invoice_profile_service.build_smart_pi_lines`): Read `quantity` and `unit_price` blindly and multiplied them for BC. The correct `total` field sat unused.
3. **Preflight endpoint** (`ap_review.pi_preflight`): Summed `qty × unitCost` of planned lines for the BC payload but never compared that sum against the invoice's extracted total amount. Additionally, `ready` was hardcoded to `True` regardless of critical deviations.

**Fix — three defensive layers (all idempotent, no-op on clean data):**

1. **New shared helper** (`services/line_reconciliation.py`):
   `reconcile_line_amounts(li)` — treats the line's printed `total` as ground truth. When `qty × unit_price` disagrees (tolerance max of $0.01 or 0.1% of total), derives `unit_cost = total / qty` if qty > 0 (preserve-qty strategy) or collapses to `qty=1, unit_cost=total`. Returns `(qty, unit_cost, info)` where `info` is non-None only when reconciliation fired. Accepts camelCase/snake_case key variants (`quantity`/`qty`, `unit_price`/`unitCost`/`rate`, `total`/`amount`/`line_total`).
2. **PI builder hardening** (`vendor_invoice_profile_service.build_smart_pi_lines`):
   Every incoming line now passes through `reconcile_line_amounts`. Reconciled lines are tagged `{reconciled: true, reconcile_info: {...}}` and their BC description is suffixed with `[reconciled: qty=N x rate=$X.XXXX = $Y.YY]` for full audit trail.
3. **Preflight sanity gate** (`vendor_invoice_profile_service.detect_deviations`):
   New `total_mismatch` deviation with `severity: critical`. Compares `sum(qty × unitCost)` across planned lines against the invoice's extracted total (tolerance max of $1.00 or 0.5%). Any material drift is flagged critical.
4. **Preflight endpoint bug fix** (`routers/ap_review.pi_preflight`):
   `ready` is now `not has_critical` (was hardcoded `True`). New `critical_deviations` field surfaces the blocking reasons so the UI / CLI can render them without filtering the full `deviations` array.
5. **Extraction-time reconciliation** (`services/invoice_extractor.py`):
   Same reconciler is applied to the LLM's `line_items` output before writing to Mongo. Raw LLM values preserved under `_raw_extracted` + `_reconcile_reason` for audit. Prompt also hardened to prefer `quantity=1, unit_price=<line total>` when freight-style columns are ambiguous.

**Verified:**
- 16 new pytests in `tests/test_pi_preflight_reconcile.py` — all green. Covers: consistent lines (no-op), XPOLOGI regression payload, zero-qty collapse, missing-qty default, absent-total fallback, tolerance absorption, camelCase/snake_case interop, PI-builder integration, and all 5 branches of the invoice-total sanity check.
- Backend service healthy (`/api/health` 200).
- Pre-existing code-shape tests (`test_vendor_profile_learning`, `test_knowledge_seed`, `test_validation_gaps`) unchanged — their failures predate this work (verified via git stash).

**User impact (production VM):**
After `cd /opt/gpi-hub && git pull && docker compose build --no-cache && docker compose up -d`, the same preflight curl on doc `76410e9e` will now return `ready: false` with a critical `total_mismatch` deviation explaining the $715K vs $649.97 disagreement — posting is blocked until the line data is fixed. Clean invoices remain unaffected.




## [2026-04-19] v2.5.10 — Email-Poller Dedup Fix + Auto-Proposed Filename Rules

**Problem surfaced from prod triage-scan dump**
- `GET /api/admin/triage/duplicate-scan` showed identical attachments (`GAMMIN_AR_20260316.xls`, `W9.pdf`, etc.) ingested 10–12× per day.
- `GET /api/admin/filename-heuristics/unmatched-sample` revealed 187 Ball Metal + 13 MRP Solutions docs stuck in NeedsReview — no existing rule matches them.

**Root cause of dup ingestion (3 compounding bugs):**
1. Dynamic poller (`poll_mailbox_for_documents`) deduped by `attachment_name` but the static AP poller (`poll_mailbox_for_attachments`) wrote the same `mail_intake_log` rows with field `filename`. Cross-worker blindness → same file ingested twice.
2. Dynamic poller used a **hardcoded 1-hour rolling lookback** and ran every 60 s → replayed the same messages up to 60× an hour.
3. No unique index on `mail_intake_log(internet_message_id, attachment_hash)` — nothing enforced uniqueness at the DB layer.

**Fixes (`services/email_polling_service.py`):**
- `check_duplicate_mail_intake(...)` now matches across BOTH legacy schemas (`filename` + `attachment_name`) AND has a global hash-only fallback so the same content forwarded from a different email still dedups.
- `record_mail_intake_log` writes BOTH `filename` and `attachment_name` for forward interop; swallows `DuplicateKeyError` from the unique index (concurrent-worker race → treated as "already processed").
- New `ensure_mail_intake_indexes()` creates a UNIQUE partial index on `(internet_message_id, attachment_hash)` + lookup indexes. Called at startup in `server.py` before any poller task is spawned.
- Dynamic poller now uses hash-first dedup (same path as static) + a **per-mailbox watermark** stored in `hub_settings` with key `mailbox_watermark:<address>`, so we no longer replay a 1-hour window every minute.

**New feature — Auto-Proposed Filename Heuristic Rules (`services/admin/filename_heuristics_auto_service.py`):**
Zero-manual-input rule generation. Mines each vendor's own already-classified docs in `hub_documents` (excluding its own heuristic decisions, to avoid feedback loops) and proposes a rule when one `doc_type` carries ≥70% of ≥5 samples.
- `auto_propose(...)` → `{proposals, deferred, projected_coverage, ...}`
- `apply_auto_proposed(execute, min_unmatched_count, min_confidence, actor)` → upserts into `filename_heuristic_custom_rules`, invalidates classifier cache.
- `list_custom_rules(only_enabled)` + `set_custom_rule_enabled(rule_id, enabled)`.

**Classifier consults custom rules (`services/admin/filename_heuristics_service.py`):**
- New `classify_filename_async()` — safe in any async context; cached for 60 s.
- Built-in rules always win over custom rules (custom is a fallback, not an override).
- `apply()` and `preview()` upgraded to use `classify_filename_async`.

**5 new admin endpoints:**
- `GET  /api/admin/filename-heuristics/auto-propose`
- `POST /api/admin/filename-heuristics/auto-apply?execute=&min_unmatched_count=&min_confidence=`
- `GET  /api/admin/filename-heuristics/custom-rules?only_enabled=`
- `POST /api/admin/filename-heuristics/custom-rules/{rule_id}/toggle?enabled=`

**Verified:**
- 8 new pytests in `tests/test_email_polling_dedup.py` — all green.
- 13 new pytests in `tests/test_filename_heuristics_auto.py` — all green.
- Testing agent iter_232: **107/107 PASS** across related suites. Full round-trip seeded, verified persisted + toggled + regression on `/filename-heuristics/*`, `/duplicate-docs/*`, `/email-polling/status`, `/documents`. Startup log confirms `mail_intake_log indexes ensured`.

**Operator playbook (on prod — remember to `cd /opt/gpi-hub && git pull && docker compose build --no-cache && docker compose up -d` first):**
```bash
# 1. Dry-run to see what would be proposed
curl http://localhost:8080/api/admin/filename-heuristics/auto-propose?min_group_size=3 | jq

# 2. Commit the rules
curl -XPOST 'http://localhost:8080/api/admin/filename-heuristics/auto-apply?execute=true&min_unmatched_count=5&min_confidence=0.75'

# 3. Backfill the existing Unknowns now that rules exist
curl -XPOST 'http://localhost:8080/api/admin/filename-heuristics/apply?execute=true&min_confidence=0.70'

# 4. Clean up the dup docs from prior runs
curl -XPOST 'http://localhost:8080/api/admin/duplicate-docs/resolve?execute=true&keep=oldest'
```


## [2026-04-19] v2.5.2 — Phase B Readiness Report (stub ready)

Companion stub to the Phase B.0 observer — turns raw observation data into a categorized test-coverage matrix with a READY / NOT READY verdict. When production observations accumulate (~7 days), the readiness endpoint tells us EXACTLY which caller × doc_type paths Phase B must preserve with green tests in the new home.

**Added:**
- `services/workflow_state_observer.build_phase_b_readiness_report(days, min_coverage)` — emits `{ready_to_extract, verdict, counts, matrix, markdown}`. Categories: `must_preserve` (≥ `min_coverage` calls), `should_cover` (2..min-1), `edge_case` (1). Matrix sorted desc by calls. Built-in markdown renderer produces a PR-ready block with 3 section headers + pipe-escaped tables.
- `GET /api/admin/workflow-observer/phase-b-readiness?days=&min_coverage=&format=json|markdown` — JSON by default, `format=markdown` returns `text/markdown` via `PlainTextResponse`. Query bounds: days ∈ [1, 90], min_coverage ∈ [2, 100], format ∈ {json, markdown}. All validated by FastAPI → 422 on violation.
- 4 new pytest in `tests/test_workflow_state_observer.py` — not-ready-on-empty, categorizes-and-verdicts-ready, not-ready-below-threshold, clamps-min-coverage
- Testing agent also authored `tests/test_phase_b_readiness_http.py` (15 HTTP integration tests) against the live preview URL

**Verdicts:**
- **NOT READY** — when `total_calls=0` OR no path hits the threshold. Verdict string tells the user which case + what to do.
- **READY** — at least one `must_preserve` path. Verdict string names the count + prescribes the action ("Phase B extraction should ship with a pytest covering each of those pairs").

**Verified:**
- Testing agent iter_223: **96/96 total** (9 observer + 72 regression + 15 HTTP integration) PASS. Zero critical issues. JSON and markdown paths both verified with seeded+cleaned data. Parameter validation returns 422 on all bad inputs. Fixtures (C-10250, C-DEMO-OVRD-1, digest 2026-W15) untouched.
- Code-review note: Report rightly separates threshold (min_coverage) from time window (days). Markdown escapes pipes in caller/doc_type. With `min_coverage=2` the `should_cover` range is degenerate (empty); noted as expected behavior, not a bug.

**How to use after 7 days of production traffic:**
```
# Machine-readable (for CI / scripts)
curl /api/admin/workflow-observer/phase-b-readiness?days=7 | jq

# Human-readable (paste into the Phase B PR description)
curl "/api/admin/workflow-observer/phase-b-readiness?days=7&format=markdown"
```

## [2026-04-19] v2.5.2 — Phase B.0: Workflow State Observer

De-risking pre-flight for the upcoming Phase B extraction (moving the 427-line `_update_standard_workflow_status` out of `server.py`). Captures caller attribution + doc_type for every invocation into a TTL-bounded collection so we have production data — which callers exercise which branches — before the real move.

**Added:**
- `services/workflow_state_observer.py` — `record_workflow_call()` + `get_observer_summary()` + `list_recent_observations()`. Fire-and-forget: wrapped in try/except, never blocks the primary workflow. Auto-creates a 30-day TTL index on `created_at` plus `by_caller`/`by_doc_type` indexes. Uses `inspect.stack()` to attribute to the REAL caller by walking past (a) its own frame AND (b) the instrumented `_update_standard_workflow_status` frame.
- `routers/workflow_observer.py` — 2 new endpoints under `/api/admin/workflow-observer/`: `GET /summary?days=` (ge=1, le=90) and `GET /recent?limit=&caller_func=` (ge=1, le=500). Both strip `_id`.
- `main.py` — include_router wiring
- `server.py` L2013-2028 — instrumented `_update_standard_workflow_status` with a fire-and-forget observe call at the top (before the find_one early-return so EVERY invocation is captured)
- 5 new pytest in `tests/test_workflow_state_observer.py` — real-caller attribution, never-raises-on-db-error, summary groups by caller × doc_type, days clamp at service layer, recent filters + limits

**Verified:**
- Testing agent iter_222: 68/68 pytest (5 new + 63 regression) PASS. Live E2E: triggered `record_workflow_call` from a named function and confirmed `caller_func` came back as that function's name (not `_update_standard_workflow_status`). TTL index verified present with expireAfterSeconds=2592000. Zero regressions on `/api/learning/*`, `/api/sales-dashboard/*`, `/api/intake/*`, `/api/documents`, `/api/health`. Giovanni C-10250 + fixtures (C-DEMO-OVRD-1, digest 2026-W15) untouched.

**Known minor spec inconsistency (non-blocking):** The router returns HTTP 422 for out-of-range `days` while the service layer also clamps defensively. Both layers work; only the public HTTP contract matters (422). Left as-is — consistent with the `/recent` endpoint's behavior.

**Soft hardening opportunity (deferred)** noted by testing agent: `SKIP_FUNCS = {"_update_standard_workflow_status"}` is a magic string that must be updated in lockstep if the function is renamed. Fine for now (observer explicitly exists to support this one function). Consider parameterizing in Phase B.

**When to read the data:** Let this shim run in production for ~7 days, then hit `GET /api/admin/workflow-observer/summary?days=7` to see which callers + doc_types actually exercise the function. Phase B extraction can then proceed with production-grounded test-coverage targets.

## [2026-04-19] v2.5.2 — Orchestration Extraction Phase A

First scoped extraction pass on `server.py` (8,900 lines → progress toward `/backend/policies/`). User picked **Option A** (smallest, lowest-risk scope) — extract the 2 small functions that `document_handlers.py` imports from `server.py`. Larger extractions (`_update_standard_workflow_status` 427 lines, `_internal_intake_document` 771 lines) deferred to their own focused iterations.

**Added:**
- `services/vendor_profile_helpers.py` (132 lines) — new authoritative home for `update_vendor_profile_incremental()` (dropped leading underscore — now public API). Self-contained: only needs `re`, `datetime`, and the passed-in `db`. No server-side module state dependencies.
- 5 new pytest in `tests/test_vendor_profile_helpers.py` — noop-on-empty-name, create-profile, increment-existing, stable-vendor-flag-at-10+, server-compat-wrapper-delegates.

**Refactored:**
- `server.py` L2580: the 91-line `_update_vendor_profile_incremental` body is now a 10-line compat wrapper that late-imports from `services.vendor_profile_helpers`. Preserved so server-internal callers continue to work during the 30-day dual-path window.
- `services/document_handlers.py` L733: `from server import _update_vendor_profile_incremental` → `from services.vendor_profile_helpers import update_vendor_profile_incremental`
- `services/document_handlers.py` L1075: split the `from server import _update_standard_workflow_status, compute_ap_normalized_fields` into two — `compute_ap_normalized_fields` now imported directly from its authoritative home `services.document_intel_helpers` (server's version was already a thin wrapper). `_update_standard_workflow_status` remains from server (deferred to next extraction pass per scope choice).

**Net impact:**
- `document_handlers.py` late-imports from server.py: **3 → 1** (only `_update_standard_workflow_status` remains)
- `server.py` active function bodies shrunk by ~85 lines
- Zero behavior change (compat wrapper preserves all legacy paths)

**Verified:**
- Testing agent iter_221: 63/63 pytest across 9 test files PASS (5 new + 58 existing). Full E2E MongoDB roundtrip via the compat wrapper verified. Backend starts cleanly — no ImportError / circular import. Zero regressions.
- Giovanni C-10250 + all persisted fixtures (C-DEMO-OVRD-1, digest 2026-W15) untouched.

**Remaining late-imports from `server` in services/** (intentionally out-of-scope this iteration):
- `document_handlers.py` L1079 → `_update_standard_workflow_status` (427 lines)
- `email_polling_service.py` L420, L763 → `_internal_intake_document` (771 lines)
- `inside_sales_pilot_service.py` L387 → same
- `batch_po_splitter.py` L162 → same

## [2026-04-19] v2.5.2 — WoW Delta Banner + ~~Rep Overrides Admin UI~~ (rolled back — dup)

**Week-over-Week Delta Banner** shipped as planned. **Rep Overrides admin UI rolled back** — a tab for it already existed inside `/config` (Settings → Rep Overrides) via `components/RepOverridesPanel.js`. Main agent failed to grep the codebase before building. Duplicate deleted; sidebar link + route removed.

**Added (Week-over-Week Delta Banner):**
- `frontend/src/components/WeekOverWeekDeltaBanner.jsx` — slim banner at the top of `/learning/ops` ("Did we move the needle?") that pulls the latest 2 digests via `GET /api/learning/digest?limit=2` and computes client-side deltas for: events total, active reviewers, new drift alerts. Drift delta is inverted (DOWN is green). Gracefully falls back to a "Baseline week" message when only one digest exists. Zero new backend work.

**Rolled back:**
- `frontend/src/pages/RepOverridesPage.js` — **deleted**
- Route `/admin/rep-overrides` — removed from `App.js`
- Sidebar nav link "Rep Overrides" + `UserCheck` icon — removed from `Layout.js`
- Page title entry — removed

**Retained:**
- `C-DEMO-OVRD-1` / Acme Demo Co. → Demo Rep fixture stays — it's now useful for the existing Settings → Rep Overrides tab (already confirmed rendering the row)
- `2026-W15` prior-week digest fixture — still needed for the WoW banner

**Verified:**
- Testing agent iter_220 had validated both features before rollback — WoW banner tests all still apply; Rep Overrides tests are now stale but harmless (endpoint-level coverage still valid)
- Confirmed post-rollback: `/config` (Settings) → "Rep Overrides" tab renders `RepOverridesPanel` with the `C-DEMO-OVRD-1` seed row visible; sidebar no longer shows the dup link

**Lesson:** Before building a new page, grep for existing component/panel/tab implementations (`grep -rln "<feature-name>"`). Should have been standard practice here.

## [2026-04-19] v2.5.2 — Weekly Learning Digest + U6 SO-Learning Telemetry

Closed the Learning-Core unification loop with a **preview-only weekly digest** surface and **U6 telemetry instrumentation** on the sales_order_learning suggestion workflow so every reviewer action — intake, AP, AND sales-order — now feeds the same Learning Ops leaderboard, sparklines, and digest.

**Added (Weekly Digest):**
- `services/learning_core/digest_service.py` — `build_weekly_digest()` assembles a one-week snapshot (top-3 reviewers, event totals by domain + event_type, new drift alerts in window, pattern-health snapshot, 7-day trend) and upserts into `learning_digests` collection keyed by ISO `week_key` (e.g. `2026-W16`) for idempotence
- 4 new endpoints: `POST /api/learning/digest/rebuild[?week_of=YYYY-MM-DD]`, `GET /api/learning/digest/latest`, `GET /api/learning/digest/{week_key}`, `GET /api/learning/digest?limit=N`
- `Weekly Digest scheduler` (24h interval, 20-min startup delay) — rebuilds the current-week digest continuously so `/api/learning/digest/latest` always reflects live state
- `frontend/src/components/WeeklyDigestCard.jsx` — headline + 4 KPI cards (Events/Top Reviewer/New Drift/Generated) + top-reviewer pills with 🥇🥈🥉 + JSON download + Rebuild; week selector dropdown for history browsing
- Mounted at the top of `/learning/ops`
- 6 new pytest in `tests/test_weekly_digest.py` (empty-week headline, aggregation narrative, idempotent upsert, invalid-date error, latest-returns-newest, list-clamps-limit) + 7 new API regression tests (authored by testing agent)

**Added (U6 — SO-Learning Telemetry):**
- `sales_order_learning_suggestion_apply_service.py` — `_transition()` (approve/reject) and `apply_suggestion()` now emit unified `learning_events_v2` rows with `domain=sales_intake`, `event_type=so_suggestion_{approved|rejected|applied}`, `scope_value=customer_no`, `source=sales_order_learning_suggestion_apply_service`. Invalid transitions still return `{error}` without emitting telemetry
- This means Inside Sales reviewer activity on sales-order learning suggestions now contributes to the Ops leaderboard + weekly digest — sparklines light up from **three** feedback surfaces instead of two
- 3 new pytest in `tests/test_u6_so_telemetry.py` (approve emits, reject emits, invalid-transition no-emit)

**Scope decision:**
- Original handoff claimed "5 redundant `sales_order_learning_*` services to collapse." Inspection showed only 3 files, and they are NOT redundant with `learning_core/` (they mine BC sales order history for customer posting profiles — distinct concern). U6 pivoted to light-touch **telemetry instrumentation** instead of shim consolidation — higher value, zero regression risk, and the Ops page immediately benefits. Deeper refactor deferred to post-v2.5.2.

**Design call on the digest:**
- Preview-only, **no email integration** (Resend / MS Graph deliberately NOT wired). JSON download button on the card gives stakeholders a copy-pasteable artifact today; email delivery can layer on later without changing the build pipeline.

**Verified:**
- 58/58 pytest passing across 8 learning-core test files
- Testing agent iter 219: 9/9 unit tests + 7/7 API regression + full UI smoke PASS on `/learning/ops`, `/intake/learning`, `/ai-learning` — zero regressions
- Scheduler logged on startup; idempotent upsert by week_key confirmed; Giovanni C-10250 untouched; no seed data leaked

**Non-blocking observation:**
- `GET /api/learning/digest` returns `{total, digests:[...]}` envelope while sibling endpoints return bare arrays or `{items:[...]}`. Inconsistency flagged for future naming harmonization pass.

## [2026-04-19] v2.5.2 — U5: Reusable PatternHealthPanel + Learning Ops Command Center

Completed the U1–U6 unification backbone: extracted the inline Pattern Health markup into a single reusable `<PatternHealthPanel domain="..." />` component, mounted it across three surfaces (Intake Learning, AI Learning, Learning Ops), and shipped a new `/learning/ops` command-center page with a **reviewer activity leaderboard** that aggregates `learning_events_v2` by actor.

**Added:**
- `frontend/src/components/PatternHealthPanel.jsx` — single reusable component for cross-domain OR per-domain pattern health, fetches `/api/learning/pattern-health/unified`, renders summary metrics + per-scope table + trend sparkline + recent events, with `refreshKey` prop for parent-triggered reloads
- `frontend/src/pages/LearningOpsPage.js` — read-only command center at `/learning/ops`: top-line KPIs (total events, open drift, active reviewers, feedback events) + cross-domain health + reviewer leaderboard (7/14/30d window selector, medal emojis for top 3, per-domain badges, top_event_type column) + drift alerts panel + recent events feed
- `backend/services/learning_core/events_service.get_reviewer_leaderboard(days, limit)` — aggregates by actor, excludes bot actor `test`, clamps window to [1, 90]
- `GET /api/learning/reviewers/leaderboard?days=&limit=` endpoint on `routers/learning_core.py`
- Sidebar nav link "Learning Ops" (Gauge icon) → `/learning/ops`; new route in `App.js`; page title entry in `Layout.js`
- 2 new pytest for leaderboard; 16 new API regression tests in `test_u5_ops_leaderboard_api.py` (authored by testing agent)

**Refactored:**
- `IntakeLearningPage.js` — ~150 lines of inline Pattern Health markup deleted; replaced with `<PatternHealthPanel domain="sales_intake" />` + `<PatternHealthPanel />` (cross-domain)
- `LearningDashboard.js` (AI Learning) — `<PatternHealthPanel domain="ap_posting" />` mounted under Automation Rate widget (first time AP surface shows trust/drift/retire metrics)

**Verified:**
- 49/49 pytest passing across 6 learning-core test files
- Testing agent iter 218: 16/16 API regression + full UI smoke PASS on all 3 pages; leaderboard ranking correct (sally.rep 7 > marcus.ap 4 > jenna.admin 2); window selector + sidebar nav work; every testid present
- Seed data (13 scoped events) created + cleaned up; Giovanni C-10250 untouched
- Clarified: the React hydration warnings seen in prior iterations come from the Emergent visual-editor's `<span data-ve-dynamic>` wrappers — **preview-env-only artifact**, not an app bug

**Non-blocking code-review observations (not fixed):**
- `days` clamp is enforced at function-level AND router-level (`Query(ge=1, le=90)`) — router returns 422 for days>90 before the function clamp runs; harmless but slightly inconsistent
- `LearningOpsPage` fires two drift endpoints (alerts + summary) that overlap slightly; future cleanup candidate

## [2026-04-19] v2.5.2 — U4: Shared Feedback Ingest + AP Telemetry Tick

Consolidated reviewer-feedback ingestion behind a single polymorphic endpoint `POST /api/learning/feedback` discriminated by `scope_type` (`customer` | `vendor`). Also closed the telemetry gap so AP reviewer thumbs-up/down now emits to `learning_events_v2` — meaning the 7-day sparklines on `/intake/learning` light up organically as both Inside Sales AND AP reviewers work their queues.

**Added:**
- `services/learning_core/feedback_service.py` — `record_unified_feedback()` dispatcher
- `POST /api/learning/feedback` on `routers/learning_core.py` with `UnifiedFeedbackBody` polymorphic Pydantic model (customer shape: `event_type + scope_value=customer_no + doc_id/item_no/trigger_item`; vendor shape: `document_id + reviewer_assessment + final_human_decision + disagreed_fields + notes`)
- AP telemetry tick: `record_unified_feedback` writes a `learning_events_v2` row (domain=`ap_posting`, event_type=`ap_review_{assessment}`) on every successful vendor feedback — skipped cleanly on error paths (e.g. Document not found)
- 7 new pytest in `tests/test_unified_feedback.py`: unknown scope, missing required fields (customer + vendor × 2), customer dual-write, vendor telemetry write, vendor-error no-telemetry

**Design notes:**
- Validation errors return 200 + `{error: "...", scope_type, known_event_types?}` — intentional so callers never need to parse HTTP status for input issues
- Legacy endpoints (`/api/intake/insights/feedback`, `/api/ap-advisory/feedback/{doc_id}`) remain live during the 30-day dual-write window

**Verified:**
- 47/47 pytest passing across 6 learning-core test files (7 new U4 + 40 existing)
- Testing agent iter 217: 7/7 backend curl spec cases + 7/7 pytest + frontend smoke PASS; zero regressions
- No real customer (C-10250) or vendor records touched


## [2026-04-19] v2.5.2 — U3: Shared Pattern Health & Hygiene + 7-Day Activity Sparklines

Consolidated AP (`posting_pattern_analysis`, confidence-tier-based) and Intake (`order_line_patterns`, accept-rate-based) pattern trust/drift/retire state into a single normalized `HealthReport` shape behind pluggable adapters — dashboards, schedulers, and alerts can now treat every domain identically. Follow-up enhancement layers per-domain 7-day activity sparklines so managers can eyeball whether patterns are trending healthier or noisier week-over-week.

**Added:**
- `services/learning_core/pattern_health_service.py` — normalized HealthReport aggregator with `HEALTH_ADAPTERS` + `HYGIENE_ADAPTERS` registries (sales_intake + ap_posting)
- 2 new endpoints on `/api/learning/*`:
  - `GET /api/learning/pattern-health/unified?domain=&limit=` — cross-domain OR per-domain report
  - `POST /api/learning/hygiene/run?domain=all|sales_intake|ap_posting` — cross-domain hygiene trigger (delegates to each adapter, writes audit row to `pattern_hygiene_runs`)
- AP-side hygiene: auto-retires `posting_pattern_analysis` docs when confidence tier drops to `none`
- New **Cross-domain (AP + Intake)** roll-up section inside the Pattern Health panel on `/intake/learning` — renders unified Trusted/Drifting/Retired/Unscored metrics plus per-domain breakdown pills
- **`events_service.get_trend(domain, days)`** — returns dense, zero-filled per-day event counts from `learning_events_v2`; attached as `trend_7d` to each domain's HealthReport
- **Inline SVG Sparkline component** on `/intake/learning` — renders a 7-day polyline per domain (testids `sparkline-sales_intake`, `sparkline-ap_posting`) with native tooltip ("Last 7d — N events") and numeric total sibling

**Verified:**
- 40/40 pytest passing across 5 learning-core test files (3 new `get_trend` tests + 37 existing)
- Testing agent iter 215 (U3 core): 11/11 frontend UI + 2/2 backend endpoints PASS, zero regressions
- Testing agent iter 216 (sparkline enhancement): 8/8 frontend + trend_7d shape PASS, zero regressions
- Giovanni C-10250 state confirmed pristine (16 patterns, 0 feedback mutations); sparkline seed data cleaned up post-validation

**Version:** `APP_VERSION` remains **2.5.1** in header (bump deferred until U4+U5 ship the full unification)


## [2026-04-18h] v2.5.0 + v2.5.1 — Drift Alerts + Shared Fingerprint Service

### v2.5.0 — Proactive Drift Alerts
Scans the unified `learning_events_v2` log (built in U1) every 24h for anomalies and surfaces them as structured alerts with severity + evidence.

**5 drift rules:**
1. **TRUSTED_PATTERN_DRIFT** (critical) — a trusted line getting rejected ≥2× in 7d
2. **CUSTOMER_REJECT_SPIKE** (warn) — ≥5 rejections in 14d
3. **BOUNDS_DRIFT** (warn) — ≥3 bounds overrides in 7d
4. **AP_TEMPLATE_DRIFT** (warn) — vendor had ≥3 draft BC corrections in 7d
5. **CATALOG_EXPLOSION** (info) — ≥5 new items confirmed in 30d

**Added:**
- `services/drift_alert_service.py` — idempotent scanner + ack/resolve lifecycle
- 5 new endpoints under `/api/learning/drift/*`: scan, alerts, summary, acknowledge, resolve
- Nightly `Drift Alert scheduler` (24h, 15-min startup delay)
- New **Drift Alerts panel** on `/intake/learning` with severity-colored rows, inline Ack/Resolve buttons, "Scan drift" manual trigger
- All thresholds env-configurable (`DRIFT_*_MIN_*`, `DRIFT_*_WINDOW_DAYS`)

### v2.5.1 — U2: Shared Fingerprint Service
Moved the TF-IDF cosine math into `learning_core.fingerprint_service` so it powers **both** customer (sales intake) and vendor (AP) similarity — one codebase, polymorphic `scope_type` discriminator.

**Added:**
- `services/learning_core/fingerprint_service.py` — domain-agnostic build/cache/invalidate/find_similar
- Unified `scope_fingerprints` collection (unique index on `scope_type, scope_value`)
- Pluggable `SCOPE_EXTRACTORS` — `customer` reads `order_line_patterns`, `vendor` reads `posting_pattern_analysis`
- 2 new endpoints: `POST /api/learning/fingerprints/rebuild?scope_type=...`, `GET /api/learning/fingerprints/similar?scope_type=...&scope_value=...`
- Legacy `cold_start_matcher_service` now **delegates** to the shared service — dual-writes to legacy `intake_customer_fingerprints` for 30-day migration window

**Impact:** AP team gets free vendor-peer discovery ("which other vendor is Acme most similar to?") with zero new code — same surface as the customer one we already shipped.

### Verified
- 42/42 pytest unit tests passing (9 new + 33 existing)
- Testing agent iter 214: **56/56 backend + 100% frontend, zero issues, zero regressions**
- Scrubbed all test-customer residue (`C-TEST-*`) from `learning_events_v2`, `intake_learning_events`, `learning_drift_alerts`. Giovanni state confirmed pristine: 16 patterns, 0 feedback fields, 0 events.

### Version
- `APP_VERSION` bumped to **2.5.1** in `/app/frontend/src/lib/version.js`



## [2026-04-18g] v2.4.1 — Phase U1: Unified Event Log (Shared Plumbing)

### Context
Audit of the codebase surfaced 3 parallel event collections (`intake_learning_events`, `posting_learning_events`, `learning_events`) and 4 separate schedulers across AP + intake sides — the "AI Learning" and "Intake Learning" tabs are mirror images of each other but the underlying plumbing never consolidated. Started shared-plumbing refactor with the highest-ROI piece first: a canonical cross-domain event log.

### Added
- **`services/learning_core/`** package — new home for shared plumbing
- **`learning_core.events_service`** with `record_event()`, `list_events()`, `get_domain_summary()`; writes to `learning_events_v2` with indexes auto-created on (domain, created_at), (scope_type, scope_value, created_at), (event_type, created_at)
- **Schema**: `{id, domain, event_type, actor, scope_type, scope_value, target, applied, extra, source, created_at}` — scope_type polymorphic across `vendor`/`customer`/`xls_staging`/`global`
- **`routers/learning_core.py`** — 2 new endpoints:
  - `GET /api/learning/events` (filter by domain/type/scope/time)
  - `GET /api/learning/events/summary` (dashboard aggregates)
- **Dual-write** wired into 3 callsites:
  - `intake_learning_feedback_service.record_feedback_event` (Phase D feedback)
  - `cold_start_matcher_service.promote_inherited_suggestion` (Phase E promotions)
  - `draft_feedback_service._record_feedback_events` (AP draft BC feedback)
- Legacy collections still receive writes during the 30-day migration window — zero risk.

### Not in U1 (planned for v2.5.0+)
- U2 — Shared TF-IDF fingerprint service (merge vendor + customer similarity)
- U3 — Shared pattern-health service + unified hygiene scheduler
- U4 — Unified feedback ingest endpoint (`POST /api/learning/feedback`)
- U5 — Shared `<PatternHealthPanel>` React component
- U6 — Retire duplicate sales_order_learning_* service family

### Verified
- 33/33 pytest unit tests pass (5 new + 28 existing)
- New test `test_intake_feedback_dual_writes_to_learning_core` proves dual-write lands in both collections
- Live `GET /api/learning/events/summary` returns clean shape with zero events (nothing triggered yet in this environment)
- Lint: all checks passed
- Backend restarts clean; no regressions

### Version
- Bumped `APP_VERSION` to **2.4.1** in `/app/frontend/src/lib/version.js`



## [2026-04-18f] v2.4.0 — Phase E: Cold-Start Peer Matching

### Goal
Continue the "AI keeps tuning" thread from v2.3.0. Brand-new customers start with zero BC history, so the learning is cold — no suggested lines, no bounds, no guidance for the reviewer. Fix that by automatically finding the most similar known customer and offering their patterns as "inherited suggestions" that can be promoted to the new customer's own pattern with one click.

### Added
- **`services/cold_start_matcher_service.py`** — pure-python TF-IDF fingerprint matcher:
  - `build_fingerprint()` / `get_or_build_fingerprint()` / `invalidate_fingerprint()` / `rebuild_all_fingerprints()` — TTL-cached in `intake_customer_fingerprints` (24h)
  - `find_similar_customers()` — cosine-similarity against all known fingerprints, returns top-K with matched-token receipts
  - `promote_inherited_suggestion()` — reviewer-driven; seeds a real pattern on the target customer and records an `inherited_suggestion_promoted` audit event
  - Tokenizer keeps SKU-style tokens (`C-9874-10001833`) intact, drops stopwords/pure-numbers/short-tokens
- **Wired into `sales_intake_learning_service`** at 3 cold-start branches (unresolved customer, resolved-no-history, XLS staging). Result surfaces as `intake_insights.peer_matches`.
- **Fingerprint auto-invalidation** on every pattern feedback (accept/reject/promote) so cold-start matches stay fresh.
- **3 new endpoints**: `POST /api/intake/insights/promote-inherited`, `POST /api/intake/learning/rebuild-fingerprints`, `GET /api/intake/learning/similar-customers`.
- **Frontend**: `IntakeLearningPanel` renders a new purple "Peer-matched suggestions" block right after the cold-start notice, with matched-token pills + one-click ArrowUpRight promote buttons.
- **28/28 pytest unit tests passing** (9 new + 8 feedback + 11 intake).
- **Testing agent iter 213: 100% backend (39/39) + 100% frontend. Giovanni state stayed pristine.**

### Design notes
Chose pure-python TF-IDF over LLM embeddings deliberately:
- Dataset is tiny (≤200 customers × ~100 tokens)
- Domain vocabulary is sparse and highly discriminative (SKU prefixes like `C-9874` are natural TF-IDF gold)
- Deterministic → reviewers can literally see which tokens matched
- Zero API cost, zero network dep, zero sklearn bloat

### Version
- Bumped `APP_VERSION` to **2.4.0** in `/app/frontend/src/lib/version.js`.



## [2026-04-18e] v2.3.0 — Phase D: Learning Feedback Loop

### Goal
User: *"I want the AI to keep tuning and getting better — that is the best ROI."*

Turn every reviewer click into training data so pattern confidence adapts in real time.

### Added
- **`services/intake_learning_feedback_service.py`** — new service with:
  - `record_feedback_event()` — 6 event types (suggestion_accepted / suggestion_rejected / bounds_violation_confirmed / bounds_violation_overridden / unmatched_item_confirmed_new / unmatched_item_mapped)
  - Pattern mutations: accepts bump `occurrences` + `frequency`, rejects decay them, acceptance <40% over ≥5 samples → `retired=true`, ≥90% → `trusted=true`
  - Bounds overrides widen `qty_history.std_dev` by 10% per override
  - Unmatched items seed `intake_item_candidates` / `intake_item_aliases` collections
  - `get_pattern_health()` — dashboard aggregation (trusted / drifting / retired / unscored counts, per-customer drill-down, recent events feed)
  - `run_pattern_hygiene()` — nightly safety-net pass
- **4 new endpoints**:
  - `POST /api/intake/insights/feedback`
  - `GET /api/intake/learning/pattern-health`
  - `POST /api/intake/learning/hygiene`
  - `GET /api/intake/learning/events`
- **Nightly hygiene scheduler** in `server.py` (24h interval, 10-min startup delay)
- **`IntakeLearningPanel`** — inline ThumbsUp / ThumbsDown / Check buttons on every suggestion, bounds violation, and unmatched item. One-click state transitions to "kept ✓" / "dropped" / "new ✓".
- **`IntakeLearningPage`** — new Pattern Health panel: 4 trust-state counters, per-customer table, 72h reviewer-feedback activity feed. "Pattern hygiene" button for on-demand cleanup.
- **Version** bumped to **v2.3.0** in `/app/frontend/src/lib/version.js`.

### Verified live
- Giovanni C-10250 has 16 learned patterns. Accepting OIPALLET moved occurrences 15 → 16, frequency → 100%. 5 rejects of OITIERSHEET correctly retired it (retired count 0 → 1 on `/pattern-health`).
- 19/19 pytest unit tests pass (8 new + 11 existing)
- Testing agent iter 212: 100% backend (19/19 unit + 14/14 API) + 100% frontend (Pattern Health panel, feedback buttons, hygiene flow all verified). Zero issues.



## [2026-04-18d] v2.2.1 — Phase B (De-pilotization) + Phase C (Doc Detail Panel)

### Phase B — De-pilotized UI framing
The Inside Sales Pilot is now part of the overall hub, not a feature flag. Renamed the user-facing labels:
- Tab `Inside Sales Pilot` → `Sales Intake` (`SalesInventoryHubPage.js:19`)
- Page header `Inside Sales Pilot` → `Sales Intake` (`InsideSalesPilotPage.js:222`)
- Stat cards `Pilot Docs` → `Intake Docs` (InsideSalesPilotPage + SpiroBCCrossRefDashboard)
- Disabled banner `Pilot is disabled` → `Sales intake polling is disabled`
- Corpus comparison column `Inside Sales Pilot` → `Sales Intake`

Backend endpoints + DB fields intentionally preserved (`/api/inside-sales-pilot/*`, `inside_sales_pilot: true`, `sales_pilot_extraction`, `pilot_mailbox`) to avoid regression. Only the human-facing labels were neutralized.

### Phase C — IntakeLearningPanel on every Document Detail page
- `DocumentDetailPage.js` now renders `IntakeLearningPanel` directly below `ReadinessPanel` (around line 820), so every doc shows its BC/Spiro insights the moment it's opened. No more drawer-digging.
- Component is the same one used in the XLS staging drawer — single source of truth.

### Version
- Bumped `APP_VERSION` to **2.2.1** in `/app/frontend/src/lib/version.js`.

### Verified
- 11/11 pytest unit tests pass
- Testing agent: 100% backend + 100% frontend, zero issues, zero action items (iteration_211.json)



## [2026-04-18c] BC Write-Back Auto-Refresh Hook

### Problem
Daily scheduler (added in 2026-04-18b) was time-based — a user posting a sales order to BC would wait up to 24h before the hub learned the fresh pattern. Tight feedback loop requested.

### Added
- **`refresh_customer_after_bc_write(customer_no)`** — fire-and-forget service that re-learns patterns for a single customer the instant their BC sales order is posted successfully. Errors are swallowed so the main BC-write path is never blocked.
- **Hook in `gpi_integration.create_sales_order_from_document`** — on `result["success"]=True`, spawns an `asyncio.create_task` to refresh that customer's patterns in the background.
- **AP invoices intentionally excluded** — they already run `posting_pattern_analyzer.learn_from_posting` at the same callsite, which is the AP-side equivalent (vendor-based, not customer-based). The Giovanni pattern is a sales-side concept.

### Verified
- 11/11 unit tests pass (3 new tests covering happy path, empty customer skip, error swallowing)
- Live `/api/intake/learning/refresh-active` manual endpoint still works
- Backend restarts clean; hook is a no-op when BC write fails so no regression risk



## [2026-04-18b] Daily Intake Learning Refresh Scheduler

### Problem
Phase A shipped the orchestrator but required manual `backfill` calls to pick up new BC posted orders. Nikki would post a batch of Giovanni orders to BC, but the hub wouldn't re-learn until someone clicked "Force re-run all."

### Added
- **`refresh_active_customers()`** — discovers customers with BC posted-order activity in the last N hours (via `bc_reference_cache` timestamps), re-runs `learn_from_bc_posted_orders`, then re-runs `run_intake_learning` on their open hub docs + pending XLS staging. Read-only.
- **Daily scheduler** in `server.py` — fires once every 24h (5-min startup delay). Configurable via `INTAKE_LEARNING_INTERVAL_SECONDS` and `INTAKE_LEARNING_LOOKBACK_HOURS`.
- **`POST /api/intake/learning/refresh-active`** — manual trigger with `lookback_hours` + `max_customers` + `refresh_docs` query params.

### Verified
- 8/8 unit tests pass (2 new tests for the refresh function)
- Live curl: `POST /api/intake/learning/refresh-active?lookback_hours=720` returned empty result cleanly (no BC activity in sandbox)
- Backend log confirms scheduler registered: `Intake Learning Refresh scheduler started (interval: 24h)`



## [2026-04-18] Intake Learning — Hub-wide Giovanni Pattern (Phase A)

### Problem
The Giovanni/Nikki blanket-PO learning (customer C-10250) — product-level
dunnage patterns, customer-level recurring lines (Energy Surcharge),
±2σ quantity bounds — only fired inside Sales-Order preflight. Every
other PO, sales order, AP invoice, freight invoice, and inventory XLS
ingested by the hub silently bypassed it. User asked to generalize it
so every ingest gets the same BC + Spiro learning treatment.

### Added
- **`services/sales_intake_learning_service.py`** — Orchestrator that runs
  the Giovanni pipeline (seed → suggest → bounds check → item catalog)
  on any hub doc or XLS staging record. Stores `intake_insights` on the
  document, never writes to BC.
- **`routers/intake_learning.py`** — New router with 6 endpoints:
  `GET /api/intake/learning/summary`,
  `POST /api/intake/learning/backfill`,
  `POST /api/intake/learning/run/{doc_id}`,
  `POST /api/intake/learning/run-xls/{staging_id}`,
  `GET /api/intake/insights/{doc_id}`,
  `GET /api/intake/insights-xls/{staging_id}`,
  `GET /api/intake/flagged`.
- **`unified_validation_service`** — Added `intake_learning` stage; runs for
  pilot_sales, sales_order, ap_invoice, purchase_order policies.
- **`document_readiness_service.evaluate_and_persist`** — Post-readiness hook
  fires learning for every in-scope doc_type, so every doc the hub
  processes picks up BC history automatically.
- **`inventory_xls_staging_service.stage_import`** — Runs learning inline on
  every new staging record (before auto-approve gate).
- **Frontend**: `IntakeLearningPage` at `/intake/learning` (hub-wide KPIs,
  top customers by learning coverage, flagged-for-review list, backfill
  buttons). `IntakeLearningPanel` drop-in component wired into the
  InventoryImportsPage staging drawer. Nav link added.
- **Cold-start transparency**: When a customer is extracted but no BC
  history exists, `intake_insights.cold_start=true` + a clear
  `cold_start_reason` is stored and rendered with a blue info tile so
  reviewers see "no BC learning yet" instead of silence.

### Verified
- 24/24 backend tests pass (6 unit + 18 API via testing subagent)
- Live backfill processed 6 hub docs + 50 XLS staging records; 39
  actionable findings correctly flagged
- Zero regressions on existing endpoints (pilot, inventory-xls, inventory
  health, sales-order preflight)

### Next
- Phase B — remove the "pilot" framing from UI/API labels and migrate to
  canonical `/intake/*` terminology across the hub
- Phase C — surface `intake_insights` on the individual Document Detail
  page (not just XLS staging drawer)



## [2026-04-17] Round 5 — Filename-Aware Customer Suggestion

### Problem
Brokers (like Gamer Packaging) email inventory reports for their downstream customers. Files like `Gamer Inventory Summary - Water Barons.xlsx` were being auto-suggested as the **sender** (Gamer) instead of the **actual inventory owner** (Water Barons) named in the filename.

### Fixed — 3-tier suggestion cascade in `suggest_customer_workspace`
1. **Filename suffix pattern**: `... - <Customer>.xlsx` → extracts `<Customer>` → matches against registered workspaces (name or code, bidirectional prefix match).
2. **Filename prefix pattern**: `<Customer>. <Vendor> ...xlsx` or `<Customer> <Vendor> ...` where `<Vendor>` ∈ known broker tokens (gamer, pretium, mrp, ompi, ball, lagersmith). Extracts tokens BEFORE the vendor marker.
3. **Sender domain** (priority 3, previous default): used only when filename parsing yields no match.

### Added helpers
- `_resolve_customer_text(text, customers)` — normalized bidirectional match (strips punctuation, case-insensitive, ≥3 char minimum, prefers exact/prefix over substring).

### Added endpoint & UI
- `POST /api/inventory-xls/staging/re-suggest-customers?only_unassigned=false` — re-runs the new logic on existing `pending_review` staging rows. Returns `{updated, total_pending, changed: [{staging_id, filename, new_customer}]}`.
- New UI button **"Re-suggest Customers"** (violet, `Sparkles` icon) in `/inventory/imports` header. One click re-resolves all pending stagings to their correct customer via filename parsing.

### Verified
- Live E2E on 6 test patterns:
  - `Gamer Inventory Summary - Water Barons.xlsx` → **Water Barons** ✅
  - `Ryl Co Inventory vs Ryl Co Needs.xlsx` → **Ryl Co** ✅
  - `Ryl Co. Gamer Can Forecast.xlsx` (broker pattern) → **Ryl Co** (not Gamer) ✅
  - `Coloplast On Hold Orders.xlsx` → **Coloplast** ✅
  - `Gamer Can Forecast.xlsx` (no downstream) → **Gamer** (fallback to sender) ✅
  - `open_orders_report_17-APR-26.xlsx` → Pretium (via sender when no filename hint) ✅



## [2026-04-17] Round 4 — Description Fallback + Manual Mapping Editor

### Bug fix: "0 rows" on Ryl Co Inventory files
- **Root cause**: Spreadsheets like `Ryl Co Inventory vs Ryl Co Needs 4.17.26.xlsx` have a `Description` column but no dedicated SKU/Item column. Mapper tagged Description→item_description, then every row failed with "missing item".
- **Fix** (`inventory_xls_parser.py`):
  - If `item` is unmapped but `item_description` IS mapped, `normalize_rows` falls back to using description as the item identifier (legitimate for inventory summaries).
  - Heuristic mapper no longer reports `missing_required: item` when description is mapped.
  - Item string capped at 120 chars to keep ledger clean.

### Bug fix: `\binventory\b` missing underscored filenames
- Changed to `(^|[\s_\-.])inventory($|[\s_\-.])` so `Ryl_Co_Inventory.xlsx` matches.

### Added: Manual column-map editor in UI
- `pages/InventoryImportsPage.js` — side-drawer now has an **Edit** button next to the column map. Opens dropdowns for every canonical field with options from the staged headers.
- **Save Mapping** calls `POST /api/inventory-xls/staging/{id}/update` with the new mapping, THEN automatically calls `POST /api/inventory-xls/staging/{id}/re-normalize` to re-run row normalization against the new map — no re-upload needed.

### Added: `POST /api/inventory-xls/staging/{id}/re-normalize`
- Recovers original file bytes from `hub_documents` (via `source_doc_id` or file_hash match), re-parses, and re-runs `normalize_rows` with the current column_map. Returns parsed/error counts.

### Fixed: Approval UX for 0-row staging
- UI blocks Approve when `row_count == 0` with explanatory message pointing user to fix the column map.
- Backend approval errors now surface the first error's actual text instead of "undefined".

### Verified
- Live: `Ryl_Co_Inventory_test.xlsx` with only Description + Available columns → staged with 3/3 rows, item populated from description.
- Manual editor UI: dropdowns rendered, Save Mapping triggers re-normalize automatically.
- Classification fix: filename with underscores now matches correctly.



## [2026-04-17] Round 3 — Learning-Backed Automation + Drift Alarm

### Added — Auto-approve gate
- `services/inventory_xls_staging_service.py` — `_should_auto_approve(staging_doc)` checks: assigned_customer ≠ null + rows present + column_map.source=="learned" + confidence ≥ 0.95 + learned `approval_count ≥ 3`. When all true, `stage_import` immediately calls `approve_staging` with `approved_by="auto:learned-mapping"`.
- `services/inventory_xls_parser.py` — learned confidence formula updated to `min(0.99, 0.80 + 0.05 * approval_count)`. Thus 1→0.85, 2→0.90, 3→0.95 (auto threshold), 4→0.99.
- Response shape now includes `auto_applied: bool` on `/ingest`; staging record carries `auto_approved: true` flag.

### Added — Ingest-time XLS side-channel in pilot enrichment
- `server.py :: _maybe_stage_inventory_xls(doc_id)` is called from `_run_pilot_enrichment` after BC validation + Spiro + SO rules. For every pilot-ingested `.xlsx/.xls/.csv`, runs the classifier → if inventory, auto-stages via `stage_import` (which may auto-approve per the gate above). Marks source doc with `inventory_xls_backfilled=true` to prevent re-runs.

### Added — Bulk backfill endpoint
- `POST /api/inventory-xls/backfill-pilot-docs?dry_run=true|false&limit=N` — scans all pilot-ingested XLS/CSV docs in `hub_documents` and either reports (dry_run) or stages them. Idempotent via `inventory_xls_backfilled` marker. Returns per-doc trace + classification breakdown.

### Added — Cache Drift Alarm (frontend)
- `InsideSalesPilotPage.js :: MatchTierDonut` now renders an amber alarm banner when matched ≥ 10 AND (`exact/matched < 0.80` OR `fuzzy/matched > 0.10`). Turns the donut from a passive metric into an active safety signal for extraction or BC-cache drift.

### Added — Inventory Imports sidebar nav + backfill UI
- `components/Layout.js` — new "Inventory Imports" sidebar entry (FileSpreadsheet icon).
- `pages/InventoryImportsPage.js` — "Scan Pilot XLS" (dry run) + "Backfill Pilot XLS" buttons with a rich result card showing scanned / inventory / staged / already_staged / skipped / errors + by-classification breakdown.

### Fixed — Customer auto-suggest prefix match
- `suggest_customer_workspace` — bidirectional prefix match. Previous regex failed when the sender domain was LONGER than the customer code (e.g. `gamerpackaging` sender, `gamer` code). Now tests both `code.startsWith(hint)` AND `hint.startsWith(code)` with 3-char minimum code length to avoid false positives.

### Verified
- `testing_agent_v3_fork` iteration 208: **37/37 tests passed (17 new + 20 regression), 0 issues.**
- Live E2E: 3 human approvals of same `(domain, header_hash)` → 4th file from same domain **auto-applied in one shot** with `created_by: auto:learned-mapping`.
- Docs: `/app/BACKFILL_PILOT_XLS.md`, `/app/DEPLOY_INVENTORY_XLS.md`.



## [2026-04-17] Inventory XLS Inference Pipeline — Phases A+B+C+D

### Added — Phase A (Classifier)
- `services/inventory_xls_classifier.py` — `classify_xls(filename, headers, sender_email) → XlsClassification`. Rule-based detector for 6 inventory doc types with filename + header signals, confidence scoring, and filename+header agreement bonus.

### Added — Phase B (Column Mapper + Row Normalizer)
- `services/inventory_xls_parser.py`:
  - `build_column_map` — cascade: learned → heuristic → LLM (Claude Haiku via Emergent LLM Key).
  - `normalize_rows` — applies column_map, parses dates/numbers, skips zero-qty/missing-item rows.
  - `compute_header_hash` — stable sha256[:16] over sorted-normalized headers (shared across services).
  - `extract_effective_date_from_filename` — detects "As Of" dates in filenames.

### Added — Phase C (Staging + Approval)
- `services/inventory_xls_staging_service.py` — stage_import / update_staging / approve_staging / reject_staging / suggest_customer_workspace.
- `routers/inventory_xls.py` — 8 REST endpoints under `/api/inventory-xls/`:
  - `POST /ingest` (multipart file upload)
  - `POST /ingest-pilot-doc/{doc_id}` (retroactive for hub_documents)
  - `GET /staging[?status=&customer_id=&limit=&skip=]`
  - `GET /staging/{id}`
  - `POST /staging/{id}/update`
  - `POST /staging/{id}/approve?approved_by=`
  - `POST /staging/{id}/reject?rejected_by=&reason=`
  - `GET /learning-summary`
- New collections: `inv_import_staging`, `inv_xls_learned_mappings` (indexes ensured at startup).
- Forecast rows route to `inv_incoming_supply` (planned); everything else to `inv_movements`.
- `effective_date` additive field on movements (never overrides `created_at`).

### Added — Phase D (Learning Loop)
- On approval, persists `{sender_domain, header_hash, column_map, classification, approval_count}`.
- Future ingests with matching `(sender_domain, header_hash)` auto-resolve via `source: "learned"` with conf = 0.80 + 0.03·approvals.
- `get_learning_summary` returns aggregates for AI Learning dashboard.

### Added — Phase E (UI)
- `frontend/src/pages/InventoryImportsPage.js` — full review/approval dashboard at `/inventory/imports`:
  - Status filter chips (pending_review / applied / rejected / all)
  - Upload button (.xlsx / .xls / .csv)
  - Learning summary strip (top senders by approval count)
  - Staging list with classification + map source pills
  - Side-drawer: classification signals, column map preview, first 80 rows, customer selector, Approve / Reject actions

### Verified
- `testing_agent_v3_fork` iteration 207: **20/20 backend tests passed, 0 issues.**
- Live smoke test on preview env:
  - Ingest: 3-row OpenOrders XLS → classified at 0.95 conf, mapped at 0.82 heuristic
  - Approval: 3 movements in `inv_movements` with `effective_date` preserved
  - Learning: second file from same domain → `source: "learned"` at 0.83 confidence
  - UI: Renders correctly with learning strip, staging list, and detail drawer
- Deploy instructions + backfill script in `/app/DEPLOY_INVENTORY_XLS.md`.

### Deferred
- Auto-stage from pilot mailbox ingestion (currently requires explicit `POST /ingest-pilot-doc/{id}` per doc, or the bulk backfill loop).
- Teams Adaptive Card webhook (user input still pending).
- P1 Phase 3 (policy extraction from server.py).



## [2026-04-17] Match-Tier Distribution Donut Chart

### Added
- **`GET /api/inside-sales-pilot/match-tier-distribution`** — aggregation endpoint returning match-tier buckets (`exact`, `scoped`, `fuzzy`, `live`, `no_match`, `no_ref`) + `by_entity_type` breakdown + overall `match_rate_pct`.
- **`MatchTierDonut` component** (pure-SVG, no chart library) — rendered at top of Inside Sales Pilot dashboard showing donut + color-coded legend. Serves as canary metric: a drop in the exact slice while fuzzy rises is an early warning of extraction / BC cache drift BEFORE the overall match rate changes.
- Lint clean. Backend smoke-tested (empty preview env returns zero-state correctly).

### Added — Inventory XLS Proposal
- **`/app/INVENTORY_XLS_PROPOSAL.md`** — 4-phase architecture for routing inventory-related `.xlsx`/`.xls` emails into the `inv_movements` ledger with pilot-style human-in-the-loop safety (Phase A classifier → B column mapping with LLM fallback → C staging + approval → D learning loop). Awaiting user scope decision (A only, A+B, or all four).



## [2026-04-17] P1 Phase 2 + Batch Enhancements

### Added — Order Match fuzzy tier
- `_check_order` in `services/bc_prod_validator.py` gains a final **fuzzy_normalized_search** tier (runs when `bc_customer_no` is null and ref is ≥6 chars). Searches `normalized_document_no`, `normalized_external_ref`, and regex on raw `bc_external_document_no` across `sales_order + posted_sales_invoice + posted_sales_shipment`.
- Diagnostic endpoint reports new `hit_via_fuzzy_normalized` bucket.

### Added — UI BC Match column on Inside Sales Pilot dashboard
- New column in Recent Pilot Documents table with color-coded `bc_entity_type` badge:
  - 🟢 Open SO · 🟡 Posted Inv · 🔵 Shipment · ⚪ no match
- Tier suffix: `~` for fuzzy, `c` for customer-scoped (tooltips on hover).
- Gives reviewers instant visibility into whether a doc matched an open order vs an already-posted invoice — a key pilot-safety signal.

### Added — Low-volume vendor gate
- `document_readiness_service.evaluate_and_persist` now counts prior non-duplicate docs for the vendor. Fewer than 5 → readiness downgrades `ready_auto_*` → `needs_review` with `warning_reason: low_volume_vendor`.
- Prevents first-time / rare vendors from auto-filing before training data exists.

### Added — BOL / Tracking / Carrier extraction on pilot docs
- `_extract_sales_fields` now captures `bol_number`, `tracking_number`, and `carrier` from the main pipeline onto `sales_pilot_extraction`.
- Pilot remains ingest-only — fields are persisted/displayable, NOT written to BC.

### Changed — P1 Phase 2: callers migrated to unified facade
- 8 call sites now import from `services.unified_validation_service` instead of directly:
  - `server.py` — intake readiness, gap-closer, PO retry (3 sites)
  - `server.py :: _run_pilot_enrichment` (done in Phase 1)
  - `routers/readiness.py` — `/evaluate/{doc_id}` + PO retry endpoint
  - `routers/inside_sales_pilot.py` — `/validate/{doc_id}` + re-extract loop
  - `services/inside_sales_pilot_service.py` — polling loop
  - `services/gap_closer_service.py` — re-evaluation loop
- Delegators (`run_bc_prod_validation`, `run_readiness`) are one-liners — zero behavior change.

### Verified
- `testing_agent_v3_fork` iteration 206: **22/22 backend tests passed, 0 issues**.
- Facade imports work, policy registry returns 4 policies with archive fallback.
- All pilot endpoints respond correctly; diagnostic reports new `hit_via_fuzzy_normalized` bucket.
- Low-volume gate (threshold=5) and BOL/tracking code paths verified via introspection.
- Fuzzy normalized tier verified present in `_check_order` with 6-char minimum.

### Deferred with user input required
- **Teams Adaptive Card webhook** — needs Azure AD app + Teams webhook URL + user sign-off on whether "Approve" should bypass the ingest-only pilot constraint.
- **P1 Phase 3 (full server.py policy extraction)** — 1000+ lines of behavioral migration. Needs dedicated session with full regression testing.
- **Evergreen multi-PO container allocation** — needs sample spreadsheet + schema clarification.



## [2026-04-17] P1 Refactor Started — Unified Validation + Policy Modules

### Added
- **`services/unified_validation_service.py`** — single canonical entry point for document validation. Exposes:
  - `validate_document(doc_id, policy_hint=None)` → orchestrates bc_prod + readiness + pilot_readiness per `POLICY_STAGES` table
  - Thin delegators `run_bc_prod_validation`, `run_readiness`, `run_pilot_readiness`
  - `POLICY_STAGES` map declaring which validation stages apply per doc_type
  - `_infer_policy_hint(doc)` auto-detects the right pipeline based on `inside_sales_pilot` + `doc_type`
- **`policies/` package** — pluggable policy modules (architectural review §2.3):
  - `policies/base.py` — `PolicyModule` ABC + `PolicyResult` dataclass
  - `policies/registry.py` — `register_policy`, `get_policy`, `list_policies`; fallback to archive policy
  - `policies/archive.py` — 30-line policy for unknowns / no-op doc types
  - `policies/warehouse.py` — BOL / shipment policy (thin wrapper, readiness-driven)
  - `policies/ap_invoice.py` — AP routing by readiness state
  - `policies/sales_order.py` — Pilot pilot_review enforcement + non-pilot readiness routing
  - All 4 policies auto-register on package import

### Changed
- **`server.py :: _run_pilot_enrichment`** now calls `validate_document(pid, policy_hint="pilot_sales")` instead of importing bc_prod_validator + pilot_readiness_review_service directly (first canary migration; behavior unchanged — same stages run in same order).

### Verified
- Lint clean across all new files.
- Registry correctly maps 14 doc_type strings → 4 policy modules.
- `get_policy("garbage")` falls back to archive (no silent drops).
- Policy `evaluate()` smoke test: pilot sales → `stage=pilot_review` with `hold_for_pilot_review` action (ingest-only constraint preserved).
- Backend starts cleanly with no new errors.

### Next migration steps (scheduled)
- Migrate remaining `validate_document_against_bc` / `evaluate_and_persist` direct callers (~30 sites across server.py, routers/readiness.py, routers/inside_sales_pilot.py) to the unified facade.
- Once call sites are consolidated, extract shared primitives (`field_completeness`, `entity_exists`, `po_match`, `amount_range`, `duplicate_risk`, `extraction_quality`) from the 5 readiness services into `unified_validation_service`.
- Extract doc_type branches from `server.py` (lines 2065-2438, 3333-3634) into policy modules fleshing out real logic (currently thin wrappers).



## [2026-04-17] BC Order Match Rate Restored (P0 Fix)

### Diagnosed
- **Root cause**: Reported 0/222 Order Match was stale data. Earlier `validate-all` runs skipped docs with existing `bc_prod_validation` and didn't use `force=true`, so pre-fix results persisted.
- **Confirmed**: `_check_order` query logic was functionally correct — diagnostic endpoint showed 42.1% live hit rate on the very first probe.

### Added
- `GET /api/inside-sales-pilot/diagnose-order-match` — read-only diagnostic endpoint reporting:
  - `cache_health` — total sales_order records + external-ref coverage
  - `extraction_health` — PO / order number coverage across pilot docs
  - `sample_matches` — per-doc trace of refs_tried, direct cache hits, `_check_order` result
  - `raw_cache_samples` — shape of `bc_external_document_no` values
  - `summary` — hit rate broken down by match method

### Changed
- `_check_order` (in `services/bc_prod_validator.py`) now cascades across 3 BC entity types:
  1. `sales_order` (open, preferred — unchanged behavior for already-matching docs)
  2. `posted_sales_invoice` (catches 6-digit posted order numbers like `109301`, `111092`)
  3. `posted_sales_shipment` (catches shipment / BOL / warehouse refs)
- Customer-scoped fallback extended to the same 3 entity types.
- `match_method` now includes entity-type suffix (e.g., `cache_multi_search:posted_sales_invoice`) for observability.

### Verified (prod VM)
- Post-fix: **58.8%** Order Match hit rate on 50-doc sample (20/34 docs with refs matched)
- 225 pilot docs re-validated with `force=true`, 0 errors, avg overall score = **34**
- Docs files: `/app/DIAGNOSE_ORDER_MATCH.md`, `/app/DEPLOY_ORDER_MATCH_FIX.md`



## [2026-03-25] Learned Dunnage Patterns Feature

### Added
- **Learned Dunnage Patterns** — AI service that learns dunnage/ancillary line associations from historical orders and auto-suggests them during Sales Order review
  - Backend: `order_line_patterns.py` pattern learning service with `get_suggested_lines()` and `learn_patterns_from_history()`
  - Backend: Preflight endpoint injects `suggested` lines with metadata (confidence, frequency, occurrences)
  - Frontend: `PatternSuggestions` component with "Add All" and per-line "Add" buttons
  - Frontend: Sparkle icon visual distinction for pattern-sourced lines in editable table
  - Demo: Batch PO Split seeds Giovanni glass jar dunnage patterns (pallets, tier sheets, top frames)
  - Fixed UOM-aware qty_ratio calculations for M (per 1000) quantities

### Changed
- `CreateBCSalesOrderPanel` wrapped with `forwardRef` for parent access to edited lines
- Pattern-sourced lines separated from PO lines at preflight load time (shown in Suggested Additions panel, not mixed into line table)

### Added — Energy Surcharge / Customer-Level Patterns
- **Customer-level patterns** (trigger_item="*") for items that appear across ALL orders for a customer (not tied to specific products)
- `learn_from_bc_posted_orders()` function: queries BC for posted sales invoices, identifies recurring line items above threshold (default 75% of last 10 orders)
- ENERGY surcharge auto-suggested for Giovanni: Qty 1 EA, Price $497.36 (editable), "seen in 80% of orders"
- Preflight endpoint auto-triggers BC history learning on first encounter
- Demo batch seed includes ENERGY pattern alongside existing dunnage patterns

### Added — Quantity Bounds Checking
- **Statistical bounds checking** (±2σ from historical mean) on PO line quantities
- `check_quantity_bounds()` function compares PO qty against historical stats per item per customer
- Preflight response includes `bounds_check` with `in_bounds` flag and violation details (item, expected range, deviation factor, severity)
- Out-of-bounds: document flagged with `bounds_alert: true`, `workflow_status: bounds_review`, `ready: false`
- Red "Quantity Out of Bounds — Review Required" banner with per-violation CRITICAL/WARNING badges
- "Approve & Submit to BC" button blocked ("Blocked — Qty Review Required")
- Queue shows "Bounds Review" red status and "QTY ALERT" badge
- Validation checklist includes "Quantity bounds check" item
- Demo seed: `qty_history` with mean, std_dev, min, max, sample_count per item


## [2026-03-16] SharePoint Folder Routing Feature

### Added
- **SharePoint Folder Routing Management Page** (`/sharepoint-routing`)
  - Folder tree visualization based on "Temp Folder Structure 9.15.25.docx"
  - Vendor-to-folder mapping CRUD (31 default mappings)
  - Processor assignment management (Andy, Ellie, Meg, Rhonda, Aaron)
  - Interactive test routing tool
  - Re-seed defaults functionality

- **Backend Router** (`/api/sharepoint-routing/*`)
  - Full CRUD for folder rules, vendor mappings, processor assignments
  - Document folder suggestion endpoint
  - Document folder assignment and move-to-SharePoint endpoints
  - Batch suggest and batch move operations
  - Auto-seeding of default configuration on first access

- **Folder Routing Service** (updated `folder_routing_service.py`)
  - Complete routing logic matching the accounting folder structure
  - Priority-based rules: Canpack override -> Credit Memos -> Tooling -> Freight -> S&H -> Standard
  - Vendor pattern matching for Ball, Canpack, Anchor, OI, freight carriers
  - International/domestic routing
  - Warehouse subfolder routing (Assembly, GT's, Ball Orders, UPS Orders, etc.)

- **AI Classification Enhancement**
  - Updated Gemini prompt with SharePoint routing context
  - Added extraction of routing fields: is_international, is_tooling, is_storage_handling, is_credit_memo, is_dunnage, freight_direction
  - Return_Request classification updated for credit memos

- **Document Pipeline Integration**
  - Auto-compute SharePoint folder suggestion after document classification
  - Store `sharepoint_folder_suggested` and `sharepoint_folder_reason` on hub_documents
  - Display folder suggestion in document detail page with breadcrumb path

- **Document Detail "Move to SharePoint" Button**
  - "Get Folder Suggestion" button when no folder suggestion exists
  - "Move to SharePoint" one-click button after folder is suggested
  - Shows folder path breadcrumbs, routing reason, and move timestamp
  - Both buttons integrated directly in the SharePoint card on document detail page

### Fixed
- **P0: Multi-Page PDF Misclassification** - Root cause: entire multi-page PDF was sent to Gemini, causing shipping content from later pages to overwhelm the classification. Fix: extract first page only using pypdf for classification of multi-page PDFs.
- **Regression: Purchase Invoice Line Items Missing in BC** - Root cause: `create_purchase_invoice_from_document` created the PI header but never called `add_purchase_invoice_lines` to add line items. Fix: added `add_purchase_invoice_lines` function to `gpi_integration_service.py` (mirrors `add_sales_order_lines` pattern) and integrated it into the PI creation flow. Lines are now extracted from `extracted_fields.line_items` and sent via `purchaseInvoices({id})/purchaseInvoiceLines` standard BC API. Frontend updated to show lines_added/lines_total/line_errors.

### Dependencies Added
- `pypdf` - For extracting first page of multi-page PDFs

### Test Results
- Backend: 20/20 tests passed (100%)
- Frontend: 12/12 UI tests passed (100%)
- Test report: `/app/test_reports/iteration_123.json`

## 2026-05-02 — Square9 Cutover Readiness Flipped to READY

### Cleared
- **G2 sales-email polling verified on prod VM.** `run_sales_email_poll()` returned `run_id ef19bb9b`, `messages_detected: 0`, no errors. Poller is connected and idle-correct against the configured sales mailbox.
- **C1 = No.** Operator confirmed no Hub flow relies on Square9 as archive-of-record after cutover.
- **C5 = No.** Operator confirmed no scanner / MFP path drops files into Square9 that Hub does not already ingest.
- **UI smoke** deferred by operator as not materially relevant to the Square9 cutover decision; SearchPage v2 endpoints already validated server-side prior to deploy.

### State change
- `/app/memory/SQUARE9_READY_FOR_CUTOVER.md` flipped from **DRAFT** to **READY**.
- Cutover authorized under §6 of `SQUARE9_CUTOVER_PLAN.md` pending the verbatim Friday clearance line for `POST /api/square9/archive-stage-data`.
- Rollback path (`POST /api/square9/restore-stage-data`) remains in place as the safety hatch.

### No code changes
- No backend or frontend code shipped in this step. Closeout was strictly a readiness declaration based on operator-side verification of preconditions.

## 2026-05-02 — Square9 Cutover Business-Proof Package

### Added
- `/app/memory/SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md` — non-negotiable proof standard for CFO sign-off (critical groups, critical workflows, pass/fail bar, blocker vs minor definitions, required shadow-period evidence, decision matrix, final readiness statement template).
- `/app/memory/SQUARE9_USER_TEST_SCRIPTS.md` — task-based test scripts for AP, warehouse/shipping, sales/CS (and optional management) using real-world tasks, four-column response format (completed in hub? / needed Square9? / confusing-or-slower? / notes).
- `/app/memory/SQUARE9_FALLBACK_LOG_TEMPLATE.md` — per-tester per-day fallback evidence log with explicit severity definitions (blocker / important / minor) and end-of-day summary.

### No code or feature changes
- This package is purely operational artifacts to drive a 1–2 day shadow / UAT window. No backend, frontend, or schema changes.

## 2026-05-02 — Square9 CFO Summary Template

### Added
- `/app/memory/SQUARE9_CFO_SUMMARY_TEMPLATE.md` — one-page executive template the operator fills out after the shadow window. Sections: objective, shadow window dates, tester groups, overall result (Ready / Ready w/ minor exceptions / Not ready), critical workflows tested, pass/fail counts, fallback totals + severity breakdown, top 3 issues, what was proven, what remains open, CFO decision (approve / delay), sign-off, evidence-sources footer. No new gates introduced; this is the cover page for the existing acceptance / scripts / fallback packet.

### No code or feature changes
- Real next step is unchanged: run the 1–2 day shadow / UAT window and collect evidence.

## 2026-05-02 — Square9 Cutover: Authoritative AP SharePoint Destination Locked

### Corrected
- The authoritative production AP destination is the **Temp Folder** under Accounts Payable, not the parent Accounts Payable folder. Locked path:
  `/sites/GamerAccounting/Shared Documents/General/Accounting/Accounts Payable/Temp Folder`

### Updated artifacts
- `SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md`
  - §2 Accounting / AP: added "Authoritative SharePoint destination — Accounts Payable" anchor block; tightened A5 / A6; added A8 (routing-correctness spot check) requiring AP-classified docs to land at the locked Temp Folder path.
  - §4 Blockers: added B9 (AP docs landing outside the Temp Folder destination = blocker, not minor); B1 expanded to include A8.
  - §6 Evidence: added E5b (AP destination correctness sample list).
- `SQUARE9_USER_TEST_SCRIPTS.md`
  - Group A (Accounting / AP): added A11 task asking the tester to confirm an AP invoice opened from Hub lands under the locked Temp Folder path.
- `SQUARE9_CFO_SUMMARY_TEMPLATE.md`
  - "What was proven": added explicit yes/no with sampled / off-path counts for AP destination correctness against the locked path.
- `SQUARE9_READY_FOR_CUTOVER.md`
  - "What was validated": added the locked AP destination as the source of truth for AP routing and retrieval validation.

### No code or feature changes
- Real next step remains the 1–2 day shadow / UAT window.

## 2026-05-02 — SharePoint AP Folder Fuzzy Comparator

### Added
- `backend/scripts/sharepoint_ap_compare.py` — new, stdlib-only fuzzy comparator. Replaces strict filename matching with a multi-signal scorer:
  - Aggressive filename normalization (diacritics, separators, common noise suffixes such as `DO NOT PAY` / `BOL` / `copy` / `Final` / `scan`).
  - Invoice/PO/reference token extraction with digit-required capture and stop-word filtering.
  - Vendor token overlap.
  - File-size equality and ±1% / ±5% bands.
  - Modified-date proximity in days.
  - SequenceMatcher ratio backstop on the normalized filename.
  - Bucketing: `exact_match` / `likely_match` / `possible_match` / `no_match`, with a `previously_missed` flag when a prior strict-match CSV is supplied.
- `/app/memory/SQUARE9_AP_FUZZY_COMPARE_RUNBOOK.md` — operator runbook with bare-line invocation, input CSV schema, output interpretation, and tuning surface.

### Validated locally (preview env)
- Synthetic prod-vs-test fixtures with the four documented filename divergence patterns (`DO NOT PAY` suffix, separator swap, token reorder, `Final` suffix). Strict matcher would return 0; fuzzy comparator returns 3 `exact_match` + 1 `likely_match`, all flagged `previously_missed`. Linter clean.

### Operator next step
- Dump prod and test AP Temp Folder listings to CSV (`name,size,modified` required), then run the bare-line invocation in the runbook to produce `prod_reports/sp_ap_compare_fuzzy.csv` and the stdout summary. Feed result counts into acceptance checklist evidence E5b.

### No backend / frontend behavior changes
- This is a read-only diagnostic; no API, schema, or service changes.

## 2026-05-02 — SharePoint AP Fuzzy Comparator: --graph-pull Mode

### Added
- `--graph-pull` mode in `backend/scripts/sharepoint_ap_compare.py`. Pulls both prod and test folder listings live from Microsoft Graph (no CSV export step).
  - Reuses existing backend env vars: `TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `SHAREPOINT_SITE_HOSTNAME`.
  - Read-only — requires only `Sites.Read.All` (Application) with admin consent.
  - Refuses to run when `DEMO_MODE=true`.
  - Prod defaults anchored on the locked AP destination: `/sites/GamerAccounting` :: `Shared Documents` :: `General/Accounting/Accounts Payable/Temp Folder`. All four prod components are overridable.
  - Test side requires explicit `--test-site-path` and `--test-folder-path`; library defaults to `Shared Documents`.
  - Pages Graph results via `@odata.nextLink` (`$top=999`), files-only (subfolders skipped for an apples-to-apples flat AP compare).

### Preserved
- CSV mode (`--prod-csv` / `--test-csv`) is unchanged and remains as fallback. Same output shape; same stdout summary; same `previously_missed` semantics.

### Validated
- CSV-mode regression: synthetic fixtures still return 3 `exact_match` + 1 `likely_match` (1 previously_missed), unchanged from prior iteration. Linter clean.
- `--graph-pull` argument plumbing validated: missing `--test-site-path` / `--test-folder-path` errors out with a directive message; mode mutual-exclusivity enforced; help output documents all flags and the locked AP destination defaults.
- Live Graph fetch must be exercised on the prod VM (where real `TENANT_ID` / `GRAPH_CLIENT_*` and `DEMO_MODE=false` exist). The preview environment is `DEMO_MODE=true`, so the script correctly refuses there.

### Operator next step
- Run the bare-line `--graph-pull` invocation in the runbook with the actual test-environment site path and folder path. Output CSV and stdout summary are identical in shape to CSV mode, so the existing acceptance-checklist E5b evidence flow is unchanged.

## 2026-05-02 — Fuzzy Comparator Invocation Path Corrected

### Fixed
- Operator runbook + script docstring referenced `python -m backend.scripts.sharepoint_ap_compare`. Container WORKDIR is `/app/backend`, so the existing repo convention (matches `scripts.contracts_import_navigator`, `scripts.contracts_dryrun_normalizer`, etc.) is `python -m scripts.sharepoint_ap_compare`. Updated `/app/memory/SQUARE9_AP_FUZZY_COMPARE_RUNBOOK.md` and the script's own docstring. No script logic change.

### Correct one-liner

    docker compose exec -T backend python -m scripts.sharepoint_ap_compare --graph-pull --test-site-path "/sites/GPI-DocumentHub-Test" --test-folder-path "Accounts Payable/Temp Folder" --out-csv prod_reports/sp_ap_compare_fuzzy.csv --top 25

## 2026-05-02 — Fuzzy Comparator: Recursive Graph Enumeration

### Fixed
- `--graph-pull` mode previously enumerated only the immediate children of the configured prod / test folder root. Prod's AP Temp Folder is nested (vendor / year / sub-category subfolders), so the operator's first run loaded only 1 prod doc and reported 0 matches across all buckets — a false negative driven by enumeration depth, not absent overlap.

### Changed
- `pull_listing_via_graph()` rewritten as a BFS over folder items by id (not by path), with per-folder pagination via `@odata.nextLink`. Files are emitted; subfolders are queued for further enumeration.
- Recursion is now the **default** for both prod and test legs in `--graph-pull` mode. Added `--no-recursive` flag for the legacy flat behavior, and `--max-depth` (default 25) to cap traversal.
- `parent_path` is now recorded per-Doc (relative to the listed root) and surfaced in the output CSV as `prod_parent_path` / `test_parent_path`. This makes triage of nested overlaps straightforward without changing the comparison signals.
- stderr now logs per-leg "visited N folder(s), M file(s)" so the operator can immediately see whether enumeration reached real depth.

### Preserved
- CSV-mode behavior is unchanged. Output schema gained two columns (`prod_parent_path`, `test_parent_path`) which are empty for CSV-mode rows unless the input CSV has a `parent_path` column.

### Validated
- CSV-mode regression on the existing synthetic fixtures: still 3 exact_match + 1 likely_match (1 previously_missed). Linter clean.
- Graph-pull recursion must be exercised on the prod VM. Operator one-liner unchanged in shape; just re-run.

## 2026-05-02 — Mailbox-Category Propagation + Classification Safety

### Root cause
- `classify_from_mailbox_category("AP")` unconditionally returned `DocType.AP_INVOICE`. Combined with the deterministic-first pipeline in `classify_document_type()` (mailbox step ran BEFORE AI), every attachment to an AP-lane mailbox — including non-invoice docs sent to billing@ — was being force-classified as `AP_INVOICE`. The dynamic mailbox poller does propagate `mailbox_sources.category` correctly to `mailbox_category` on `hub_documents`; the bug was downstream in the classifier treating the lane tag as proof of doc type, not as source context.

### Fix (surgical, no architectural rewrite)
- `backend/workflows/core/engine.py` — `classify_from_mailbox_category(category, evidence: bool = False)`. Default behavior now returns `DocType.OTHER`. Lane-implied type only fires when the caller passes `evidence=True`, indicating extracted fields support the lane.
- `backend/services/classification_helpers.py` —
  - Added `_has_lane_evidence(mailbox_category, extracted_fields)` (AP needs invoice_number / vendor / amount / due_date / bill_to / invoice_date; Sales needs customer/invoice/SO/PO; Purchase needs PO/vendor/line_items; Operations: no auto-promote).
  - Step 1c now passes `evidence=…` and uses classification_method `"mailbox:{cat}+evidence"` so audit trails distinguish evidence-backed lane classifications from the legacy unconditional path.
  - Added a post-AI **AP-lane review fallback**: when nothing definitively classifies and `mailbox_category ∈ {AP, Sales, Purchase}`, the result carries `mailbox_lane_needs_review=True` and `classification_method="mailbox_lane:{cat}:needs_review"`. doc_type stays `OTHER` (no force-classification), but downstream routing/derive_workflow_status can hold the doc in the AP review lane instead of dropping it into Operations.
- `backend/services/email_polling_service.py` —
  - Added `normalize_mailbox_category()` with conservative alias map (`Billing → AP`, `Accounts Payable → AP`, `AR → Sales`, `Accounts Receivable → Sales`, `Purchasing/PO → Purchase`, `Warehouse/Shipping/Ops → Operations`). Unknown values pass through verbatim with a WARNING log so misconfigurations surface immediately.
  - Both intake call sites (legacy `poll_mailbox_for_attachments` and dynamic `poll_mailbox_for_documents`) now log `mailbox_id`, `mailbox`, `configured_category`, `resolved_category`, `filename` immediately before `intake_document_from_bytes`. The legacy hardcoded `"AP"` is now routed through `normalize_mailbox_category()` for consistency.

### What is **not** changed
- AP posting path, SharePoint routing, AP auto-post service, vendor matching, BC validation, doc_handlers byte-parity (intake body unchanged).
- Operations-lane documents (warehouse/shipping). Lane tag remains; nothing promotes them.
- Existing AP_INVOICE intake when there IS invoice evidence — still classifies as AP_INVOICE via Step 1c (now with `+evidence` audit suffix).

### Tests
- New: `backend/tests/test_mailbox_category_propagation.py` — 18 tests covering normalize_mailbox_category alias map (Billing→AP, AR→Sales, Operations passthrough, blanks, unknown passthrough), `_has_lane_evidence` for AP/Sales/Purchase/Operations, classify_document_type integration (clear AP invoice → AP_INVOICE; non-invoice on billing → NOT auto-forced + mailbox_lane_needs_review=True; Operations doc → no promotion), and DocumentClassifier defaults.
- Updated: `backend/tests/test_suggested_type_sync.py` — replaced legacy assertion that mailbox-AP unconditionally returns AP_INVOICE with the new evidence-gated behavior; refreshed two source-grep tests that pinned legacy server.py line ranges (sync logic and is_ap_invoice check) to look in both `server.py` and `services/document_handlers.py` after the Phase 3 Step 4b carve-out.

### Test results (local)
- `pytest backend/tests/test_mailbox_category_propagation.py` → 18/18 PASS.
- `pytest backend/tests/test_suggested_type_sync.py backend/tests/test_email_polling_dedup.py backend/tests/test_mailbox_category_propagation.py` → 48/48 PASS.
- Pre-existing failures unrelated to this fix (verified by re-running on stashed `main`): `test_intake_caller_rewire_parity::test_openapi_path_count_858` (route-count drift, 875 vs pinned 858); `test_helper_substitution_4c2_parity::test_post_4c2_body_sha256_matches_step_4b_baseline` (intake-body sha drift from prior unrelated commits); HTTP-based phase7 / classification_bootstrap tests that need a live backend URL.

### Prod verification commands

Confirm `mailbox_sources.category` for the three lanes:

    docker compose exec -T backend python -m scripts.bootstrap_learning --noop 2>/dev/null; docker compose exec -T backend python -u -c "import asyncio,os,json;from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    rows=await db.mailbox_sources.find({},{'_id':0,'mailbox_id':1,'email_address':1,'category':1,'enabled':1}).to_list(50)
    print(json.dumps(rows,default=str,indent=2))
asyncio.run(m())"

Confirm a fresh ingest from billing@ persists `mailbox_category="AP"` (after this fix is deployed and a poll cycle runs):

    docker compose exec -T backend python -u -c "import asyncio,os,json;from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    cur=db.hub_documents.find({'email_sender':{'$exists':True},'mailbox_category':{'$exists':True}}).sort('created_utc',-1).limit(20)
    rows=await cur.to_list(20)
    out=[{'id':r.get('id'),'file_name':r.get('file_name'),'mailbox_category':r.get('mailbox_category'),'doc_type':r.get('doc_type'),'classification_method':r.get('classification_method')} for r in rows]
    print(json.dumps(out,default=str,indent=2))
asyncio.run(m())"

Tail logs to see the new structured intake line:

    docker compose logs -f backend --tail 200 | grep -E '\[Intake:(legacy_ap|dynamic)\]'

### Expected outcome
- Documents ingested from billing@gamerpackaging.com persist `mailbox_category="AP"` as source context.
- Only docs with invoice-like evidence classify as `AP_INVOICE`. Non-invoice or mis-sent docs stay `doc_type=OTHER` with `mailbox_lane_needs_review=True` and a `mailbox_lane:AP:needs_review` classification_method, so they go to AP review rather than being silently mislabeled or dropped into Operations.
- Operations-lane mailboxes (whdocuments@) continue to persist `mailbox_category="Operations"` with no auto-promotion.

## 2026-05-02 — AP Routing: Square9 Temp Folder Staging Guard

### Root cause (routing half)
Even though `mailbox_category` was now propagating correctly, `services/folder_routing_service.determine_folder_path()` was still scattering AP_INVOICE auto-ingest documents into the detailed accounting structure (Canpack / Dropship / Warehouse / Vendor Credit Memos / Freight Issues / Miscellaneous) before accounting had reviewed them. The AP team works out of the `Accounts Payable/Temp Folder` (Square9 parity destination), so Hub auto-routing past that staging step is what made the prod-vs-test fuzzy comparison return near-zero overlap.

### Fix
- `backend/services/folder_routing_service.py`
  - Added module-level constants: `AP_STAGING_FOLDER = "Accounts Payable/Temp Folder"`, `AP_LANE_REVIEW_FOLDER = "Accounts Payable/Temp Folder/_NeedsReview"`, plus `_AP_INVOICE_DOC_TYPES` and `_FORBIDDEN_AP_FOLDER_ROOTS`.
  - Added helpers `_is_ap_lane_doc(doc)` and `_accounting_override_set(doc)` (true when `accounting_routing_override=True` OR `approved=True` OR `status="Approved"`).
  - **PRIORITY 1 rule** at the top of `determine_folder_path`: if `mailbox_lane_needs_review=True` (set by classification_helpers), route AP/Sales/Purchase lane docs to `AP_LANE_REVIEW_FOLDER` instead of letting them leak to Operations folders.
  - **PRIORITY 2 rule**: if doc is AP-lane and accounting has not opted in, route to `AP_STAGING_FOLDER`. The detailed accounting structure (Canpack / Dropship / Warehouse / Credit Memos / Freight Issues / Misc) only fires once accounting flips `accounting_routing_override=True` or `approved=True`.
  - Routing details now include `mailbox_category`, `mailbox_lane_needs_review`, and `accounting_routing_override` for full audit-trail transparency.

### What's preserved
- Every existing detailed-routing rule (Canpack vendor → Dropship/Canpack, credit-memo keywords → Vendor Credit Memos, WH_ files → Warehouse, freight vendor → Freight Issues, MSC location → Miscellaneous, etc.) still works **once accounting has reviewed** the document. They are now opt-in via `accounting_routing_override=True` rather than fired at auto-ingest.
- Non-AP doc types (Sales_Order, Shipping_Document, Inspection_Form, Credit_Memo without AP_INVOICE doc_type, etc.) keep their existing routing untouched.
- LocationCode=MSC rule still fires for non-AP docs; AP-lane MSC docs stage first and only hit the MSC rule after override.

### Tests
- New: `backend/tests/test_ap_routing_square9_parity.py` — 16 routing tests covering AP staging defaults (Canpack, freight vendor, credit-memo keywords, warehouse hint, missing PO all stage to Temp Folder), forbidden-destination checks (no AP_INVOICE auto-routes into the seven Operations-style roots), mailbox_lane_needs_review routing for AP/Sales/Purchase, accounting-override path restoring detailed routing (Canpack, Vendor Credit Memos), and non-AP docs unchanged.
- Updated: `backend/tests/test_s9_routing_fix.py` — `make_doc()` helper now seeds `accounting_routing_override=True` so the existing S9 detailed-routing assertions cover the post-override path; auto-ingest staging is now asserted by the new file.
- Updated: `backend/tests/test_folder_routing_fix.py` — three WH_-prefix AP_Invoice fixtures now seed `accounting_routing_override=True` for the same reason.

### Test results (local)
- `pytest tests/test_ap_routing_square9_parity.py tests/test_mailbox_category_propagation.py tests/test_suggested_type_sync.py tests/test_email_polling_dedup.py tests/test_s9_routing_fix.py tests/test_folder_routing_fix.py tests/test_document_routing.py tests/test_bc_line_routing.py` → **all green**.
- Wider sweep (`+ test_so_type_routing.py`) reports 152 pass / 3 fail; the three failures are env-dependent HTTP calls against a missing `REACT_APP_BACKEND_URL` and are unrelated to this diff.
- Linter clean on all changed/new files.

### New cutover-readiness probe
- `backend/scripts/billing_intake_routing_probe.py` — read-only script that pulls recent billing@gamerpackaging.com ingests and prints counts by mailbox_category, doc_type, classification_method, and SharePoint folder root. Detects two **cutover-blocking findings** (billing→Operations leak; AP_INVOICE in forbidden folder roots without override) and warning-level findings (legacy `mailbox:AP` classification_method without `+evidence` suffix; missing classification_method; empty window).
  - Exit codes: `0` clean, `1` warnings, `2` cutover-blockers.
  - Operator one-liner:
        docker compose exec -T backend python -m scripts.billing_intake_routing_probe --since-hours 24 --limit 200
  - JSON variant: append `--json` for machine-readable output.

### Prod verification command (single line)

    docker compose exec -T backend python -u -c "import asyncio,os,json;from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    cur=db.hub_documents.find({'email_sender':{'\$regex':'billing@gamerpackaging.com','\$options':'i'}}).sort('created_utc',-1).limit(20)
    rows=await cur.to_list(20)
    out=[{'file_name':r.get('file_name'),'email_sender':r.get('email_sender'),'email_subject':r.get('email_subject'),'mailbox_category':r.get('mailbox_category'),'doc_type':r.get('doc_type'),'suggested_job_type':r.get('suggested_job_type'),'classification_method':r.get('classification_method'),'sharepoint_folder_path':r.get('sharepoint_folder_path'),'folder_routing_reason':r.get('folder_routing_reason'),'sharepoint_web_url':r.get('sharepoint_web_url')} for r in rows]
    print(json.dumps(out,default=str,indent=2))
asyncio.run(m())"

### Acceptance criteria status
- billing@ docs persist `mailbox_category="AP"`. Verified by classifier + propagation tests.
- Clear invoices on AP lane classify as `AP_INVOICE` (`mailbox:AP+evidence`). Verified.
- Mis-sent / non-invoice docs on AP lane stay `OTHER` with `mailbox_lane_needs_review=True` → AP review folder. Verified.
- AP_INVOICE docs do not auto-scatter into Warehouse Reports / Dropship / Freight Issues / Vendor Credit Memos / Miscellaneous. Verified by 16 dedicated routing tests.
- Cutover readiness: not declared yet. Run `billing_intake_routing_probe` after deploy + a poll cycle; expect exit code 0 and `Accounts Payable/Temp Folder` showing as the dominant SharePoint folder root for billing@ ingests. Then re-run the fuzzy comparator (`scripts.sharepoint_ap_compare --graph-pull`) for the prod-vs-test overlap evidence E5b. Only then is the app described as Square9 cutover-ready.

## 2026-05-02 — AP Routing Correction: Evidence-Based, Not Blanket Staging

### What was wrong with the prior fix
The prior change made every AP-lane invoice without `accounting_routing_override` route to `Accounts Payable/Temp Folder`, defeating the purpose of automation. Hub's job is to classify and route AP documents using vendor / PO / file-pattern / BC / extracted-field evidence. Temp Folder should be a **fallback**, not the default.

### Corrected model
- Remove the blanket "AP-lane → Temp Folder" rule. AP_INVOICE documents now flow through the existing deterministic rule chain (Canpack vendor, credit-memo keywords, WH_/AS_/ML_ filename patterns, freight vendor, resolved BC PO, etc.) and land in the **correct final accounting folder** with no override required.
- Keep the mailbox-lane needs-review hint (PRIORITY 1): `mailbox_lane_needs_review=True` for AP/Sales/Purchase still routes to AP review folder. This catches non-invoice docs sent to billing@.
- New thin **AP-lane weak-fallback wrapper** at the top-level `determine_folder_path`: after the rule chain runs, if the chosen destination is the bottom-of-chain `"Default routing for ..."` path or `Misc Invoices - need approval` (excluding strong-signal placements like `LocationCode=` or `DO NOT PAY status`), redirect AP-lane docs to AP Temp Folder for review. Detailed:
  - `bc_po_resolved=False` AP invoice (BC contradicts the vendor signal) → Temp Folder.
  - AP invoice that genuinely matches no rule → Temp Folder.
  - High-confidence rule matches (Canpack, credit memo, WH_, freight vendor, resolved PO, MSC, DO NOT PAY) → final folder, unchanged.
- `accounting_routing_override` / `approved=True` is now an **opt-out** of the wrapper for the rare case accounting wants the legacy Misc landing — almost never used in practice.

### Files changed
- `backend/services/folder_routing_service.py`
  - Removed `_FORBIDDEN_AP_FOLDER_ROOTS` (unused under the new model — specific rule destinations are valid AP placements).
  - Renamed the existing rule-chain function to `_determine_folder_path_core`. New top-level `determine_folder_path` calls core, then applies the weak-fallback wrapper. Rule chain itself is otherwise untouched.
  - `_is_weak_fallback_routing(path, reason)` skips strong-signal reasons (`LocationCode=`, `Document marked Do Not Pay`).
- `backend/tests/test_ap_routing_square9_parity.py` — rewritten around the new model: `TestHighConfidenceAPAutoRoutes` (Canpack/credit-memo/WH_/freight/resolved-PO/MSC each auto-route to final folder, no override), `TestWeakFallbackRedirect` (BC-unresolved AP → Temp Folder; non-AP docs unchanged), `TestMailboxLaneNeedsReview`, `TestAccountingOverrideForceBypass` (override keeps legacy Misc on bc_po_resolved=False), `TestNonAPRoutingUnchanged`.
- `backend/tests/test_s9_routing_fix.py` — removed the `accounting_routing_override=True` default from `make_doc()` (no longer needed since detailed rules now run for AP_INVOICE without override). Updated the two AP_Invoice "weak-evidence" tests (`test_ap_invoice_unresolved_po_goes_to_miscellaneous`, `test_freight_vendor_unresolved_po_goes_to_miscellaneous`) to expect the correct new redirect destination (Temp Folder); shipping-doc tests are unchanged because non-AP docs are not redirected.
- `backend/tests/test_folder_routing_fix.py` — removed `accounting_routing_override=True` from the three WH_ AP_Invoice fixtures.
- `backend/scripts/billing_intake_routing_probe.py` — replaced the broad `_FORBIDDEN_AP_FOLDER_ROOTS` blocker with a tighter `_path_is_weak_fallback(path, reason)` check (un-redirected `Default routing for ...` or `Misc Invoices - need approval`). Added an informational warning when the AP_INVOICE → AP Temp Folder ratio exceeds 50% in the window (signal of low classification confidence or rule-coverage gap, not a blocker).

### What's preserved
- Mailbox-category propagation, normalization aliases (Billing → AP), and structured intake logging — unchanged.
- AP-lane mis-sent docs review fallback — unchanged.
- Detailed accounting rule chain (Canpack / credit memo / WH_ / freight / etc.) — unchanged.
- AP posting path, byte-parity in `document_handlers.py` — unchanged.

### Test results (local)
- `pytest tests/test_ap_routing_square9_parity.py tests/test_s9_routing_fix.py tests/test_folder_routing_fix.py tests/test_mailbox_category_propagation.py tests/test_suggested_type_sync.py tests/test_email_polling_dedup.py tests/test_document_routing.py tests/test_bc_line_routing.py` → **127/127 PASS**.
- `tests/test_sharepoint_routing.py` failures are HTTP tests against a missing `REACT_APP_BACKEND_URL` (environment, not code).
- Linter clean on all changed/new files.

### Acceptance criteria status
- `mailbox_category` propagation from `mailbox_sources` to `hub_documents`: ✅
- Clear AP invoices auto-route to final accounting folder (Canpack → Dropship/Canpack, credit memo → Vendor Credit Memos, WH_ → Warehouse, freight vendor → Freight, resolved PO → Dropship/Warehouse): ✅ — locked by 6 high-confidence routing tests.
- Uncertain / contradictory AP-lane docs → AP Temp Folder for review (no random Operations folders): ✅ — locked by weak-fallback tests.
- Non-invoice on billing lane → AP review folder via `mailbox_lane_needs_review`: ✅.
- AP_INVOICE blocked from Operations folders unless valid AP rule routed it there: ✅ — only specific rule destinations are reachable; the bottom-of-chain weak-fallback path is intercepted.
- Cutover not declared. Operator must re-run `billing_intake_routing_probe` and the fuzzy comparator (`scripts.sharepoint_ap_compare --graph-pull`) against the corrected pipeline before claiming Square9 parity.

## 2026-05-02 — AP Routing: Structured Evidence-Based Decision Contract

### Mission alignment
Hub auto-classifies and auto-routes AP documents using evidence; Temp Folder is fallback-only. Prior commits established the wrapper guard; this commit adds the **structured decision contract** + **defense-in-depth scatter guard** + **cutover-readiness report**, so routing is auditable end-to-end.

### Files changed
- `backend/services/folder_routing_service.py`
  - New `determine_ap_routing_decision(doc, ...)` returning `{folder_path, routing_status, routing_reason, routing_details}`. `routing_status` enum: `auto_routed` / `needs_review` / `exception` / `manual_override`. `routing_details` carries mailbox_category, doc_type, suggested_job_type, classification_method, ai_confidence, vendor_canonical, vendor_match_method, po_number_clean, invoice_number_clean, amount_float, validation_results, possible_duplicate, manual_override_applied, evidence_signals_used, scatter_guard_blocked_destination (when applicable).
  - Defense-in-depth **scatter guard**: AP-lane doc landing in any Operations folder root with a *weak* reason ("Default routing for ..." or "Misc Invoices - need approval") is redirected to AP review folder with `routing_status="exception"`. Named-rule reasons are trusted (Canpack vendor, credit-memo description, WH_ pattern, freight vendor, resolved BC PO, "All Others" domestic, LocationCode=, etc.).
- `backend/tests/test_ap_evidence_based_routing.py` (new, 12 tests):
  - Decision-shape contract: required keys + audit field presence + evidence_signals_used population.
  - `auto_routed`: Canpack vendor, credit-memo description, WH_ pattern, resolved BC PO — each lands at the correct final accounting folder, no override.
  - `needs_review`: BC-unresolved AP → AP Temp Folder; mailbox_lane_needs_review on AP/Sales lanes → AP review folder.
  - `manual_override`: override flag preserves legacy Misc landing with `manual_override_applied=True`.
  - Non-AP unchanged: Inventory_Report → Warehouse Reports; Shipping_Document weak case → Misc (not redirected, AP-lane wrapper does not fire).
- `backend/scripts/ap_cutover_readiness_report.py` (new): full audit-grade breakdown of recent billing/AP intake by mailbox_category, doc_type, suggested_job_type, routing_status, folder_root, classification_method, top reasons. Sample sets for `auto_routed_ap_invoice`, `needs_review`, `exception`. Blocker findings (billing→Operations leak, AP_INVOICE in Operations roots via weak reason without override) and warnings (legacy classification_method, Temp Folder ratio > 50%). Synthesizes `routing_status` from persisted folder_path + reason + override flags so older rows are usable.

### What's preserved
- Mailbox-category propagation, intake logging, alias normalization (Billing → AP).
- Classification evidence-gating (`mailbox:AP+evidence` / `mailbox_lane:AP:needs_review`).
- All detailed accounting routing rules.
- AP posting path, intake byte-parity.
- `billing_intake_routing_probe.py` (the smoke-gate probe) — unchanged in shape; complementary to the readiness report.

### Test results (local)
- `pytest tests/test_ap_evidence_based_routing.py tests/test_ap_routing_square9_parity.py tests/test_s9_routing_fix.py tests/test_folder_routing_fix.py tests/test_mailbox_category_propagation.py tests/test_suggested_type_sync.py tests/test_email_polling_dedup.py tests/test_document_routing.py tests/test_bc_line_routing.py` → **139/139 PASS**.
- Linter clean on all changed/new files.

### Operator commands
- Deploy:
        docker compose build backend && docker compose up -d backend
- One billing poll cycle (existing wrapper):
        docker compose exec -T backend python -u -c "import asyncio; from services.email_polling_service import run_sales_email_poll; from server import set_db; from motor.motor_asyncio import AsyncIOMotorClient; import os; set_db(AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]); print(asyncio.run(run_sales_email_poll()))"
  (Or whichever AP-lane poll wrapper the operator already uses.)
- Smoke-gate probe:
        docker compose exec -T backend python -m scripts.billing_intake_routing_probe --since-hours 24 --limit 200
- Audit-grade readiness report:
        docker compose exec -T backend python -m scripts.ap_cutover_readiness_report --since-hours 48 --limit 500
- Prod-vs-test fuzzy comparator:
        docker compose exec -T backend bash -lc "mkdir -p prod_reports && python -m scripts.sharepoint_ap_compare --graph-pull --prod-folder-path 'General/Accounting/Accounts Payable/Temp Folder' --test-site-path '/sites/GPI-DocumentHub-Test' --test-folder-path 'AP_Invoices' --out-csv prod_reports/sp_ap_compare_fuzzy.csv --top 25"

### Cutover readiness statement
GPI Hub is **not** cutover-ready until both of the following hold for a real production window:
1. `billing_intake_routing_probe` returns exit code 0 (no blockers).
2. `ap_cutover_readiness_report` shows `auto_routed` as the dominant `routing_status` for AP_INVOICE in the window, with `needs_review`/`exception` confined to genuinely uncertain cases.
3. `scripts.sharepoint_ap_compare --graph-pull` reports non-zero `exact_match` + `likely_match` counts proving prod-vs-test AP overlap.

## 2026-02 — Bucket A Post-Apply Verifier Rendering Patch
- `scripts/verify_bucket_A_apply.py::render()` now prints `routing_status`,
  `routing_reason`, and `sharepoint_folder_path` inline with the existing
  per-doc block (right after `suggested_job_type`, before `remediation_audit`).
- `tests/test_verify_bucket_A_apply.py::test_render_shows_all_seven_required_fields`
  extended to assert the three new labels and their values appear in the
  rendered text. All 5 tests in the file pass.
- `ops/run_bucket_A_apply_and_verify.sh` confirmed intact (preflight →
  gated apply → verify → re-run proof pack → SUMMARY block).
- Strict scope respected: no Square9 cutover, no archive call, no
  additional Mongo writes, no CFO summary, no DocuSign / HTTPS / parked
  AP contamination work, no unrelated refactors.
- Single packaged VM command:
  `docker compose exec backend bash ops/run_bucket_A_apply_and_verify.sh`

## 2026-02 — Bucket A Preflight Idempotency Fix
- `scripts/bucket_A_apply_preflight.py`:
  - Added `evaluate_already_applied(live_doc)` — strict 4-field predicate
    (mailbox_category=AP, doc_type=AP_INVOICE, suggested_job_type=AP_Invoice,
    remediation_audit.source=bucket_A_one_shot_patch).
  - `preflight()` now classifies each candidate into already_applied / safe /
    unsafe (in that priority order). Already-applied is an idempotent
    success, NOT a regression: it is no longer reported as unsafe.
  - `_exit_code` returns 0 when `unsafe_count==0` and
    `safe_count + already_applied_count == candidate_count`.
  - `render_text` prints `already_applied_count`, an "ALREADY APPLIED DOC IDS"
    section, and a stable machine-friendly status line:
      `[preflight-status] candidate_count=N safe_count=N already_applied_count=N unsafe_count=N`
- `scripts/bucket_A_wrapper_decision.py` — NEW. Pure decision helper that
  reads `BUCKET_A_APPLY_PREFLIGHT.json` and emits one of
  `DECISION=apply | skip_apply | abort` plus a REASON line. Exits 0 when
  decision in {apply, skip_apply}, 1 on abort, 2 on bad input.
- `ops/run_bucket_A_apply_and_verify.sh`:
  - cd respects optional `BUCKET_A_APP_ROOT` env override (for tests; defaults
    to `/app`).
  - Calls preflight with `--proof-dir`, then runs the decision helper.
  - DECISION=skip_apply -> Step 3 prints "Apply SKIPPED — every candidate
    is already in the expected post-apply state" and APPLY_RC=0; verify
    + proof-pack still run.
  - DECISION=abort -> wrapper exits before any apply.
  - DECISION=apply -> existing gated apply (`--apply --confirm CUTOVER`)
    runs unchanged.
  - SUMMARY block now also prints `decision` and `preflight_json`.
- Tests:
  - `tests/test_bucket_A_apply_preflight.py` — added 7 new tests covering
    already_applied classification, exit-code matrix (already-only,
    mixed-safe-and-already-applied, already-applied-with-unsafe, partial
    final state stays unsafe), the strict 4-field predicate, and the new
    rendered status line. Updated the "doc already applied" case to
    expect exit 0 instead of 1.
  - `tests/test_run_bucket_A_apply_and_verify.py` — NEW. 6 unit tests on
    `decide()` plus 4 end-to-end bash tests that build a fake app root
    with stub scripts and assert: skip_apply path runs verify+proof but
    NOT apply; safe path runs apply+verify+proof; unsafe path aborts
    before any of the three; SUMMARY block content.
- Test results: `pytest tests/test_bucket_A_apply_preflight.py
  tests/test_run_bucket_A_apply_and_verify.py
  tests/test_verify_bucket_A_apply.py` -> 39 passed.
- Sibling regression: `pytest tests/test_bucket_A_one_shot_data_patch_apply.py
  tests/test_bucket_A_one_shot_data_patch_dryrun.py` -> 31 passed.
- Strict scope respected: no Mongo writes, no live apply rerun, no
  cutover, no Square9 archive, no CFO summary, no routing/classification
  changes, no unrelated refactors.

## 2026-02 — Hub-only Audit (read-only investigation of 307 hub_only docs)
- `scripts/hub_only_audit.py` — NEW. Reads the latest
  `prod_reports/cutover_proof_*/square9_hub_ap_parity*.csv`, filters to
  `match_bucket=="hub_only"`, classifies each doc into one of:
  non_ap_in_ap_scope / duplicate_or_backlog_artifact / square9_scope_gap /
  matcher_miss / true_hub_extra / uncertain. Each bucket maps to a
  recommended_action: fix_ap_scope_filter / exclude_from_parity_denominator
  / improve_matcher / no_action_hub_extra / manual_review. Predicate order
  matters (non-AP -> backlog -> identity-signals -> lane/folder ->
  uncertain). Outputs three artifacts:
    - prod_reports/hub_only_audit.csv  (per-doc classification)
    - prod_reports/hub_only_audit.json (cohort summary + top lists)
    - prod_reports/hub_only_audit.md   (human-readable report)
  Exit codes:
    - 0 mostly explainable
    - 1 uncertain >10%
    - 2 matcher_miss >=10% OR non_ap_in_ap_scope >=10%
- `tests/test_hub_only_audit.py` — NEW. 20 fixture-driven tests covering
  every bucket, exit-code matrix, IO discovery (proof-pack dir vs
  fallback vs missing), and CSV/JSON/MD output shapes.
- Test results: pytest -> 20 passed. CLI smoke run on synthetic parity
  CSV emits all three artifacts and the expected console banner.
- Strict scope respected: NO Mongo writes, no cutover, no Bucket A
  routing-rule changes, no classifier changes, no CFO summary, no
  DocuSign/HTTPS/contamination work.

## 2026-02 — Matcher-miss Vendor Diagnostic (read-only)
- `scripts/matcher_miss_vendor_diagnostic.py` — NEW. For a single
  --sender (default billing@tumalocreek.us) and configurable name
  fragments (default tumalo,tumalocreek,tumalo creek), pulls hub_only
  rows from that sender and no_match (square9_only) rows whose
  Square9 name/parent_path/web_url contains a fragment, then scores
  each Hub doc against each candidate on four signals:
    - invoice_number_match   weight 0.85 (digits-only invoice number
                                          inside digits-only Square9
                                          name+parent_path)
    - filename_token_overlap weight 0.07 (Jaccard of normalized fname
                                          tokens; stop-word filtered)
    - vendor_token_overlap   weight 0.04 (vendor_canonical + sender
                                          domain root vs Square9
                                          name+parent_path tokens)
    - date_proximity         weight 0.04 (1.0 within 7d, linear decay
                                          to 0 at 90d)
  Score >= 0.85 = strong. Three artifacts emitted:
    - prod_reports/matcher_miss_vendor_diagnostic.csv
    - prod_reports/matcher_miss_vendor_diagnostic.json
    - prod_reports/matcher_miss_vendor_diagnostic.md
  Exit codes: 0 (>=80% strong -> matcher fix), 1 (30..80% -> mixed),
  2 (<30% -> Square9 scope gap, not matcher bug). Recommended
  matcher_rule attribution counts which winning signal drove each
  strong match and emits the most common rule in the JSON summary.
- `tests/test_matcher_miss_vendor_diagnostic.py` — NEW. 20 tests
  covering normalizers (digits_only, normalize_filename, jaccard,
  vendor_root_from_sender, date_proximity_score), score_pair (strong
  alignment, zero overlap), best_candidate (winner selection, empty
  corpus), filtering (sender / fragments / wrong bucket exclusion),
  run_diagnostic exit-code matrix (all-strong / none / partial),
  CSV/JSON/MD output shape, and CLI smoke test.
- Test results: 20 passed in 0.07s.
- Strict scope respected: NO Mongo writes, NO matcher logic touched,
  NO cutover, NO Square9 archive, NO scope-filter changes, NO CFO
  summary, NO DocuSign/HTTPS work.

## 2026-02 — Square9-side no_match Audit (read-only)
- `scripts/no_match_square9_audit.py` — NEW. Reads the latest parity
  CSV, filters to `match_bucket=="no_match"` (Square9-only docs that
  the matcher could not pair with Hub), and classifies each into:
  non_ap_in_square9_corpus / pre_hub_corpus /
  matcher_miss_with_hub_candidate / vendor_not_in_hub_intake / uncertain.
  Predicate priority: non-AP keyword signal -> pre-hub-corpus date
  cutoff -> Hub invoice-digit substring match -> Hub filename Jaccard
  >= 0.34 -> Hub vendor/sender token overlap -> uncertain.
  Mongo touch is a SINGLE read-only `find` projection on
  `hub_documents` to build an in-memory token index (vendor_canonical,
  email_sender domain root, invoice_number_clean digits, file_name
  tokens). Tests inject a synthetic index directly.
  Projects four match-rate scenarios (baseline, after_exclude_only,
  after_improve_only, after_both) using exact integer arithmetic with
  a denominator floor of 1.
  Exit codes: 0 (after_both >= 85%), 1 (>=70% but <85%), 2 (<70%).
  Outputs:
    - prod_reports/no_match_square9_audit.csv  (per-doc)
    - prod_reports/no_match_square9_audit.json (cohort summary +
      projections + top examples per bucket)
    - prod_reports/no_match_square9_audit.md   (human readable)
- `tests/test_no_match_square9_audit.py` — NEW. 18 fixture-driven
  tests covering tokenization, hub-index build, every classification
  bucket (one test each, plus filename-overlap path), projection
  arithmetic, denominator floor, decide_exit_code matrix, full
  build_summary integration with both EXIT_GO and EXIT_NO_GO
  populations, all three output writers, and a CLI smoke test using
  mongomock to inject a Hub corpus.
- Test results: 18 passed in 0.16s.
- Strict scope respected: NO Mongo writes, NO matcher/scope-filter
  logic touched, NO cutover, NO Square9 archive, NO CFO summary, NO
  DocuSign/HTTPS/parked AP contamination work.

## 2026-02 — Square9 Uncertain Deep Triage (read-only)
- `scripts/uncertain_square9_deep_triage.py` — NEW. Reads the 105
  uncertain rows from the prior `no_match_square9_audit` and
  reclassifies each into recoverable_matcher_miss / square9_scope_exclusion
  / true_intake_gap / manual_review_required, using a richer signal set:
  invoice digit runs (>=4 digits), PO tokens (regex requires >=1 digit
  to avoid prose false positives), filename token Jaccard >= 0.30,
  email-subject Jaccard >= 0.45, vendor + amount overlap, broader
  non-AP keyword list (treasury / wire / template / payroll / bank
  statement / 1099 / chargeback / etc.). Predicate priority:
  scope_exclusion -> recoverable -> intake_gap -> manual_review.
  Reads prior audit JSON to combine prior_recoverable=19 and
  prior_excludable=14 into the projection math:
    current
    after_recoverable_only = (matched + prior_R + new_R) / square_count
    after_exclusions_only  = matched / max(square_count - prior_E - new_E, 1)
    after_both             = (matched + prior_R + new_R)
                             / max(square_count - prior_E - new_E, 1)
  Three artifacts (csv / json / md) with top-25 tables per bucket.
  Exit codes: 0 if after_both >= 85%, 1 if 70..85%, 2 if <70%.
  Mongo touch is one read-only `find` projection on `hub_documents`.
- `tests/test_uncertain_square9_deep_triage.py` — NEW. 20 tests
  covering tokenizers (invoice digits / PO with digit-required regex /
  amount with commas), hub-index build (all six signal kinds),
  classification (one test per bucket plus PO and filename-Jaccard
  paths), projection arithmetic (combining prior + new), exit-code
  matrix, full build_summary integration including an EXIT_GO
  population, all three output writers, and a CLI smoke test using
  mongomock.
- Test results: 20 passed in 0.14s.
- Strict scope respected: NO Mongo writes, NO matcher logic touched,
  NO parity scope changed, NO cutover, NO archive, NO CFO summary
  populate, NO DocuSign / HTTPS / parked AP contamination work.

## 2026-02 — Document-Body Reconciliation Probe (read-only)
- New objective: build the next layer of GPI Hub document
  intelligence. Header-only reconciliation has reached its ceiling
  (~57.7%); the remaining work needs the actual document content,
  not more parity math.
- `scripts/document_body_reconciliation_probe.py` — NEW.
  Reads ``manual_review_required`` rows from
  `prod_reports/uncertain_square9_deep_triage.csv`, attempts to extract
  document text via an injectable ``BodyExtractor`` callable
  (production stub returns ``no_access`` so the script never makes
  unwired network calls), pulls AP-relevant identity signals from the
  body (invoice number, PO, amount, invoice date, vendor hint,
  generic reference numbers), then scores each Square9 doc against a
  read-only Hub index (single Mongo ``find`` projection on
  ``hub_documents``). Each Square9 doc gets classified:
    - content_match_found
    - likely_same_invoice_different_attachment_granularity
    - square9_only_true_gap
    - ocr_required
    - insufficient_content_access
    - manual_review_still_required
  Emits per-doc CSV with extracted body fields + best Hub fingerprint
  + per-row recommended_next_action; cohort JSON; human-readable MD
  with plain-English summary, bucket counts, top-25 examples per
  bucket, and recommended engineering next steps.
- `tests/test_document_body_reconciliation_probe.py` — NEW. 18 tests
  covering body-signal regex extraction (invoice / PO / amount with
  commas / long-form date / empty body), hub-index build,
  invoice+amount strong scoring, classification (one test per bucket
  including same-invoice-different-attachment-granularity), summary
  builder + recommendations, all three output writers, and a CLI
  smoke test using mongomock and an injected extractor (no network,
  no Mongo writes).
- Test results: 18 passed in 0.16s.
- Strict scope respected: NO Mongo writes, NO matcher logic
  touched, NO routing changes, NO classifier changes, NO Square9
  changes, NO cutover triggers, NO CFO memo work, NO header-only
  parity audit work.

## 2026-02 — SharePoint/Graph Body Fetcher (read-only)
- `scripts/sharepoint_body_fetcher.py` — NEW. Wires the document body
  reconciliation probe to real SharePoint content via Microsoft Graph,
  reusing the existing client-credentials auth (TENANT_ID,
  GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET) already used by
  `sharepoint_ap_compare.acquire_graph_token`. No new env vars, no
  new auth flow.
  - Resolves `square9_web_url` to a Graph drive item via the
    `/shares/u!{base64url}/driveItem/content` endpoint.
  - 30-second hard timeout per file. 4xx / 5xx / network errors /
    parse failures all return `("", "no_access")` and never raise.
  - PDF text via pypdf. >= 50 non-whitespace chars -> ("text", "ok");
    less -> ("", "ocr_required").
  - Image / TIFF / PNG / JPG / GIF / BMP suffixes (with optional
    query string) short-circuit to `("", "ocr_required")`.
  - Cache at `/tmp/body_probe_cache/<sha256>.bin`, keyed by SHA-256
    of the web URL. Cache write failures are swallowed; cache reads
    that fail fall through to a network fetch.
  - `--no-cache` CLI flag on the probe forces a re-fetch.
  - GraphBodyFetcher is constructor-injected with token_provider and
    http_client_factory so tests run completely offline.
- `scripts/document_body_reconciliation_probe.py`: `main()` now
  builds a production fetcher via
  `sharepoint_body_fetcher.build_production_fetcher(no_cache=...)`
  unless an extractor is injected; falls back to the no-op default
  if production fetcher build fails. Added `--no-cache` flag.
- `tests/test_document_body_sharepoint_fetcher.py` — NEW. 17 offline
  tests covering: graph share-id encoding; stable cache key;
  classify_bytes for image/tiff (with and without query string),
  blank-page PDF, monkey-patched long-text PDF; happy-path fetch +
  OK; empty-text PDF -> ocr_required; image suffix short-circuits
  pypdf; missing/empty web_url -> no_access; 404 / 403 / timeout /
  token-failure -> no_access (no raise); cache reuse on second
  call; --no-cache forces refetch; cache-write failure does not
  crash the fetcher.
- Sibling regression: `tests/test_document_body_reconciliation_probe.py`
  still 18/18 passing.
- Combined run: 35 passed in 0.22s.
- Strict scope respected: NO Mongo writes, NO matcher logic
  touched, NO routing changes, NO classifier changes, NO Square9
  changes, NO cutover triggers, NO new env vars, NO new auth flows.
