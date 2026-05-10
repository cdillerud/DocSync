# GPI Document Hub — Product Requirements Document

## 2026-05-10 — Inbox KPI: auto_validation_rate >100% bug fixed

The dashboard's "Auto-validated" tile was showing 101.3% on the
production VM. Root cause: numerator/denominator filter mismatch
in `/api/dashboard/inbox-stats`. Strict scope: KPI math only — no
Mongo writes, no routing/classifier/matcher changes, no AP pilot
docs touched, no Save/Mark Ready/Post to BC.

- **Backend** (`backend/routers/dashboard.py:933–953`): the
  `auto_validation_rate` numerator counted docs matching
  `{"$or": [automation_decision="auto", auto_cleared=True,
  sales_review_status="auto_approved"]}` *without* the
  `status != "batch_parent"` filter the denominator already
  applied. Batch-parent containers inherit auto status from their
  children; any leaking parent inflated the numerator and pushed
  the ratio above 100. Fix: wrap the auto query in `$and` with the
  same `NON_BATCH = {"status": {"$ne": "batch_parent"}}` filter
  used by the denominator. Belt-and-suspenders clamp at the
  rounding boundary (`round(min(max(raw, 0.0), 100.0), 1)`) so any
  future floating-point edge case can't re-emerge as 100.1.
  Empty-denominator case still yields 0 (not NaN/Infinity) as
  before.
- **Frontend** (`frontend/src/pages/UnifiedQueuePage.js:540–545`):
  defensive render guard. `Number.isFinite(rate) ?
  Math.min(Math.max(rate, 0), 100) + "%" : "—"`. Never masks the
  backend bug (the backend is now correct), only protects the UI
  from null/undefined/NaN/Infinity slipping in via stale cache or
  any future regression.
- **Tests** (`backend/tests/test_inbox_stats_invariants.py`, new):
  5 tests, all green:
  - `test_batch_parent_auto_doc_does_not_inflate_numerator` — the
    exact production regression scenario.
  - `test_all_eligible_docs_auto_yields_exactly_100` — clamp at
    the boundary works.
  - `test_zero_non_batch_denominator_yields_zero` — no NaN/Infinity.
  - `test_invariant_rate_in_zero_to_hundred` — property check
    across a mix of leaking parents + duplicates + all 3 auto
    signals.
  - `test_other_kpis_still_render_after_fix` — smoke check that
    the rest of the inbox-stats payload is structurally intact.
  - Tests are pure unit tests with a tiny in-memory `_FakeDB` /
    `_FakeCollection` matching only the operators dashboard.py
    actually uses (`$and`, `$or`, `$ne`, `$nin`, `$in`, `$gte`,
    `$exists`). No live Mongo, no mongomock dependency.
- **Lint**: ruff clean on the new test file; eslint clean on the
  frontend change. Pre-existing ruff issues elsewhere in
  `dashboard.py` (lines 119, 705, 760, 776, 803) are unrelated to
  this edit and out of scope.
- **Live curl** of `/api/dashboard/inbox-stats` post-fix returns
  `auto_validation_rate: 95.2` with all required fields present.


## 2026-05-10 — Weekend engineering cleanup (4 contained items, no business sign-off needed)

Strict scope held: no Mongo writes, no document reclassification, no
routing/classifier behaviour change, no Save/Mark Ready/Post, no
Square9/cutover/DocuSign/HTTPS/parked-AP work, no AP-facing
materials touched. AP pilot package files in `prod_reports/` left
exactly as delivered.

### 1. Playwright deps persisted in backend Dockerfile
- `backend/Dockerfile` rewritten to `apt-get install` the Chromium
  shared libraries (`libglib2.0-0`, `libnss3`, `libnspr4`,
  `libdbus-1-3`, atk/atk-bridge/atspi, cups/drm/xkbcommon/xcomposite/
  xdamage/xfixes/xrandr, gbm/pango/cairo/asound/xshmfence/x11/xcb/
  xext/xi, fonts-liberation) at build time, plus a best-effort
  `python -m playwright install chromium` so the binary is in the
  image. AP smoke DOM checker now survives a clean
  `docker compose build --no-cache backend`. No browser auto-launch
  at runtime; capability only.

### 2. Document Intelligence empty-state endpoints
- `backend/routers/document_intelligence.py`:
  - `GET /api/document-intelligence/{doc_id}` now returns `{"exists":
    false, "result": null, "document_id": ...}` 200 instead of 404.
  - `GET /api/document-intelligence/decision/{doc_id}` now returns
    `{"exists": false, "decision": null, "document_id": ...}` 200
    instead of 404.
- Browser-console 404 noise on document detail page loads
  eliminated. Existing successful payloads pass through unchanged.
- Curl smoke confirms 200 + new envelope on a missing doc id.
- 4 new tests in `backend/tests/test_document_intelligence_empty_state.py`
  cover both endpoints' empty-state and present-state behaviour.

### 3. AP smoke-set generator dedupe (within-cluster)
- `backend/scripts/build_ap_smoke_test_set.py` `_emit()` now also
  dedupes by `(cluster, hub_doc_id)` in addition to the existing
  `(category, hub_doc_id)`. Categories are clustered by semantic
  intent: `happy_path` (clean + 4 field-populated), `exception`,
  `duplicate`, `misclassified`, `non_invoice`, `ocr`, `permission`,
  `pinned_curated`. A doc in the happy-path cluster only emits
  once (under its strongest/first-emitted category, e.g.
  `clean_ap_invoice` wins over `ap_invoice_invoice_number_populated`).
  Across clusters the same doc may legitimately appear (e.g. clean
  AND duplicate-flagged are two separate findings).
  `metadata_cleanup_example` remains pinned and always emits.
- The duplicate `CS 3000000223 / 29de41c0…` row that surfaced in
  the AP UAT smoke run will not regenerate.
- 4 new tests in `backend/tests/test_build_ap_smoke_test_set_dedupe.py`
  cover within-cluster dedupe, pinned-category exemption, distinct-
  doc-distinct-category preservation, and absolute no-exact-dup
  invariant. One existing test
  (`test_curator_emits_field_populated_rows_per_field`) updated to
  use distinct docs (the old fixture used a single doc to span all
  4 field-populated categories — that was implicitly relying on
  the cosmetic-bug behaviour we just fixed).

### 4. Read-only diagnostic scripts (no writes)
- `backend/scripts/diagnose_missing_routing_status.py`: queries
  `hub_documents` for docs with no `routing_status`, buckets them by
  cause (`pre_classification`, `post_classification_pre_routing`,
  `blocked_before_routing`, `unknown`), captures hub_doc_id /
  filename / doc_type / age / source mailbox / blocking-issue count,
  recommends next step per bucket, marks whether a safe auto-fix is
  apparent. Outputs `prod_reports/MISSING_ROUTING_STATUS_DIAG.{md,
  csv,json}`.
- `backend/scripts/diagnose_stalled_watermarks.py`: probes both
  `hub_settings` (type=`email_poll_watermark`) and `mail_poll_runs`
  (most recent per mailbox via aggregation), filters by `--stale-hours
  N` (default 24), buckets stalled rows into `active_error`,
  `polling_loop_inactive`, `high_consecutive_empty_polls`,
  `watermark_legitimately_quiet`. Outputs
  `prod_reports/STALLED_WATERMARKS_DIAG.{md,csv,json}`.
- Both scripts: zero writes; both surface counts, ages, causes, and
  per-bucket next-step recommendations only.

### Tests run
- `pytest test_document_intelligence_empty_state.py
   test_build_ap_smoke_test_set_dedupe.py
   test_build_ap_smoke_test_set.py
   test_ap_smoke_walk_pack.py
   test_ap_smoke_walk_dom_check.py` → **60 passed**.
- ruff lint clean on all 6 touched files.
- Backend service healthy post-change (`/api/health` → 200,
  document-intelligence/{missing} → 200 with new envelope).
- **Dockerfile rebuild not exercised in this environment** —
  Dockerfile changes are container-only; user must rebuild on the
  VM with `docker compose build --no-cache --pull backend &&
  docker compose up -d --force-recreate backend` then re-run
  `docker compose exec -T backend python -m playwright --version`
  + the smoke DOM checker `--help` to confirm Playwright survives
  the fresh build.
- **Mongo diagnostics not exercised in this environment** — these
  scripts read live data from the production VM's Mongo; user runs
  them on the VM via `docker compose exec backend python
  /app/scripts/diagnose_missing_routing_status.py` and
  `… diagnose_stalled_watermarks.py`.


## 2026-05-10 — AP-facing pilot package created (controlled-pilot release)

Pilot approved by user; package converted from internal drafts to
AP-facing materials. Documentation and pilot materials only — no
code changes, no Mongo writes, no Save / Mark Ready / Post, no
cutover/Square9 work, no DocuSign / HTTPS / parked AP work.

**Files created in `prod_reports/`:**

1. `AP_UAT_PILOT_KICKOFF_HANDOUT.md` (234 lines) — one-page-style
   Day-1 cheat sheet for AP testers. Five rules, 90-minute timing
   table, plain-language walkthrough of the document detail page,
   feedback column-by-column guide, severity guide, "who to call"
   block. Strict guardrails: no Post, no Mark Ready, no Save without
   IT direction, only assigned docs, real-payment fallback to
   Square9.
2. `AP_UAT_PILOT_TEST_PLAN.md` (246 lines) — remedial test plan
   assuming zero Hub knowledge. Sections cover login, opening a
   document, the five-field AP Review panel walkthrough, status
   reading, the 12-scenario checklist (open / preview / vendor /
   invoice # / date / amount / PO / status text / duplicate
   warning / non-invoice attachment / report missing-or-wrong /
   save-nothing-unless-directed), feedback CSV column meanings,
   severity ladder, and what NOT to do. Mirrored guardrails.
3. `AP_UAT_PILOT_FEEDBACK_TEMPLATE.csv` — clean header-only CSV with
   the 12 AP-facing columns: Tester, Date, Document / Vendor,
   Invoice Number, Hub Link, What looked right, What looked wrong,
   What did you expect?, Severity, Screenshot attached?, Notes,
   IT follow-up needed?. No example rows (those live only in the
   internal-draft template).
4. `AP_UAT_PILOT_EMAIL_DRAFT.txt` (128 lines) — concise email from
   Chad to AP testers + supervisor. Covers purpose, 90-min ask,
   guardrails, what to bring, what to expect on screen,
   reassurances about Square9 + no-BC-posting, RSVP request.

**Internal-only language stripped from all four files:**
- No INTERNAL DRAFT banners.
- No engineering file paths or Python/JS module references.
- No "smoke checker", "DOM checker", "Playwright", "Mongo".
- No "cutover" or "go-live" language.
- No "Square9 replacement" or "Square9 retirement" claims.
- No proof-pack terminology.
- No mention of body-reconciliation, vendor extraction profiles, or
  any internal probe / IT memo files.

**Placeholders Chad must fill before sending (consistent across all
four files):**
- `[HUB_URL_TBD]`
- `[FEEDBACK_DROP_LOCATION_TBD]`
- `[IT_ATTENDEE_NAME_TBD]` / `[IT_ATTENDEE_TBD]`
- `[IT_MAILBOX_TBD]`
- `[DATE_TBD]` / `[DATE_TIME_TBD]`
- `[LOCATION_OR_TEAMS_LINK_TBD]`
- `[REPLY_BY_DATE_TBD]`
- `[AP_TESTERS_AND_SUPERVISOR_NAMES]`
- `[CHAD_SIGNATURE]`

**Posture unchanged**: READY for controlled pilot, NOT READY for
floor rollout / cutover.


## 2026-05-10 — AP UAT controlled-pilot package finalized + `po_not_found` fix

Documentation/package update only. No backend code changed; one
already-identified frontend label cleanup applied. No Mongo writes,
no Save/Mark Ready/Post, no cutover, no Square9 work, no DocuSign
or HTTPS work.

- **Test plan updated** (`memory/GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md`):
  added Section 0 (Readiness baseline 2026-05-10, 16/16 smoke,
  explicit non-claims), Section 14 (Day-one pilot plan with the
  30/60/15 timing breakdown), Section 15 (Pilot guardrails — no
  Post-to-BC, no system-of-record, every issue via CSV, only
  assigned docs), Section 16 (Known limitations: doc-intel 404
  noise, OCR exclusion, non-invoice attachments, Square9 parallel,
  no BC posting), Section 17 (Pre-send checklist — testers, AP
  supervisor, URL, login, drop location, mailbox, "no Post" repeated
  three places, on-call IT, ≤48h smoke, CSV examples stripped,
  banners removed, all TBDs resolved, AP supervisor sign-off).
- **Kickoff notes updated** (`memory/GPI_HUB_AP_UAT_KICKOFF_NOTES_DRAFT.md`):
  added Readiness baseline header, Pilot guardrails (read-aloud
  block), Day-one pilot plan, and matching Pre-send checklist.
- **Readiness status updated**
  (`prod_reports/AP_UAT_READINESS_STATUS_2026-05-08.md`): prepended
  a 2026-05-10 controlled-pilot baseline section with the 16/16
  smoke matrix, the two real findings (entity-resolution leak fix,
  Document Status case-insensitive fix), the cosmetic `po_not_found`
  cleanup, what the pilot unlocks vs. does NOT, and gates before
  pilot. Original 2026-05-08 status preserved underneath.
- **Feedback CSV**
  (`memory/GPI_HUB_AP_TEST_FEEDBACK_TEMPLATE.csv`): no change. The
  template already has the right columns plus 2 example rows that
  the kickoff explicitly says to strip before AP-facing send.
- **Cosmetic backlog cleared.** `po_not_found` mapping was **NOT**
  already in `BLOCKER_LABELS` — added it now in
  `frontend/src/lib/blockerLabels.js` as
  *"PO extracted but not found in Business Central"*. Eliminates
  the "Po Not Found" title-case fallback. 19 lib tests + 5
  humanizer tests still green; eslint clean.

### AP UAT readiness summary (2026-05-10)

| Item | Status |
| --- | --- |
| Production VM smoke (P0+P1, 16 docs) | **16/16 pass, exit_code=0** |
| Raw JSON warning leakage | 0 |
| Raw snake_case blocker leakage | 0 |
| AP Review panel above PDF preview | verified on every doc |
| All 5 AP fields visible | verified on every doc |
| `entity_resolution_blocking_items` humanized | shipped |
| `po_not_found` plain-English mapping | shipped |
| Test plan + kickoff + readiness doc updated for pilot | done |
| AP supervisor sign-off | **PENDING** (gate before AP send) |
| Pilot testers identified | **PENDING** |
| Feedback drop location resolved | **PENDING** |

**Posture:** READY for controlled pilot, NOT READY for floor
rollout / cutover.


## 2026-05-10 — AP UAT smoke run is GREEN (16/16) on production VM

End-to-end AP UI readiness validated on the live production VM with
authenticated Playwright. Two real findings surfaced + fixed in the
same session.

- **DOM checker calibration fix.** `Document Status` substring check
  is now case-insensitive (`backend/scripts/ap_smoke_walk_dom_check.py`).
  The Hub UI renders the card label as `DOCUMENT STATUS`; the original
  exact-match assertion was a false negative on every doc.
- **Frontend bug fix — `entity_resolution_blocking_items` no longer
  leaks raw snake_case codes to the AP UI.** `frontend/src/components/
  DocumentIntelligencePanel.js` line 864 was rendering items like
  `vendor_unmatched: 'MRP Solutions'` as raw badges. Now wrapped in a
  new `humanizeBlockingItem()` helper that splits on `:`, runs the
  prefix through `labelForBlocker()`, and preserves any quoted value.
  Renders as `Vendor not matched to a Business Central record yet —
  'MRP Solutions'` instead of the raw code. data-testid added per item
  for future regression testing.
- **Tests.** New `frontend/src/lib/__tests__/humanizeBlockingItem.test.js`
  with 5 tests (mapped-label preservation, unknown-code title-case
  fallback, no-colon delegation, nullish handling, pre-humanised
  passthrough). All 19 frontend lib tests green; all 31 backend tests
  green; lint clean.
- **Production VM run.** After `docker compose build --no-cache --pull
  frontend && docker compose up -d --force-recreate frontend`
  (BuildKit cache-bust required), the DOM checker re-ran against the
  P0+P1 smoke set (16 docs) with the captured storage_state and
  reported `passed: 16 / failed: 0 / exit_code=0`.
- **Operator workflow that worked end-to-end.**
  1. PowerShell heredoc paste created `capture_hub_storage_state.py`
     v2 on Windows (operator-confirmed `input()` instead of
     auto-detect).
  2. Captured 1019-byte storage state with 1 cookie + localStorage
     (`access_token`, `gpi_user`, `gpi_token`).
  3. Base64-pasted via `cat > /tmp/state.b64 <<'B64_EOF' … B64_EOF`
     heredoc (avoided SCP key auth entirely).
  4. `docker compose cp` staged the JSON into the backend container.
  5. In-place Python patch added `--storage-state-path` CLI to the
     VM script (avoided 30 KB base64 paste).
  6. Re-ran DOM checker → 0/16 → 10/16 (after Doc Status fix) →
     **16/16** (after frontend rebuild).
- **Strict scope held.** No backend auth bypass, no Mongo writes, no
  Save/Mark Ready/Post, no matcher/classifier/routing changes, no
  Square9/cutover/DocuSign/HTTPS/parked-AP work. Read-only smoke
  validation only.

### What this unlocks

- AP UAT engagement is now technically clean to start: Hub UI
  passes structural smoke checks on every P0/P1 invoice in the
  internal set with no raw JSON, no raw snake_case, all 5 AP fields
  visible, AP Review panel above the PDF preview, plain-English
  blocker labels.
- The smoke checker is now a repeatable regression tool: every
  future Hub release can be validated in minutes (capture state,
  one bash command, get pass/fail per doc).


## 2026-05-09 — AP smoke DOM checker now supports authenticated Playwright sessions (Option A: storage_state)

The automated AP UI smoke checker is the supported smoke-test path
(no manual click-through). Auth is handled client-side only; no
backend changes, no Mongo writes, no Save/Mark Ready/Post.

- **`backend/scripts/ap_smoke_walk_dom_check.py` patched.** New CLI
  flag `--storage-state-path PATH` threads a Playwright `storage_state`
  JSON into `browser.new_context(storage_state=...)`. New helper
  `validate_storage_state_path()` raises clear errors when the file
  is missing or non-JSON (CLI returns rc=2). New helper
  `build_browser_context_kwargs()` keeps the wiring testable without
  a real browser. Login-wall short-circuit now appends a second error
  line telling the operator to pass `--storage-state-path` and naming
  the capture helper. The script does **not** silently fall back to
  manual testing.
- **`tools/capture_hub_storage_state.py` (new).** Laptop-side helper
  that opens headed Chromium at `--hub-origin`, waits for the operator
  to sign in normally, then exports `storage_state(path=…)`. Prints
  the next runnable command (`ap_smoke_walk_dom_check.py …
  --storage-state-path …`). Read-only — no clicks issued.
- **`tools/run_ap_smoke_dom_check_local.py` (new).** Convenience
  wrapper so the DOM check can run on the same workstation that
  captured login state (no SCP to the VM required). Locates
  `ap_smoke_walk_dom_check.py` via repo-relative or `/app/backend/...`
  fallback; refuses to run if `--storage-state-path` or `--smoke-csv`
  are missing.
- **Docs.** `prod_reports/AP_SMOKE_DOM_CHECK_AUTH_INSTRUCTIONS.md`
  documents the full TL;DR flow, expected outputs, exit codes, and
  the explicit login-failure recovery message.
- **Tests.** New `backend/tests/test_ap_smoke_walk_dom_check.py` —
  10 tests, all green. Covers: storage-state validation (none/missing/
  bad-JSON/valid), context-kwargs construction, login-wall message
  contents, CLI-flag threading via fake Playwright, missing-file fail-
  fast (rc=2). 21 existing `test_ap_smoke_walk_pack.py` tests still
  green (31 total).
- **Lint.** ruff clean on all four touched files.
- **VM-side OS deps.** During this session we resolved the prior
  Playwright Chromium crash (`libglib-2.0.so.0: cannot open shared
  object`) by running `playwright install-deps chromium` inside the
  backend container; sanity launch confirmed. The container now
  needs only an authenticated session to complete the smoke run.
- **Strict scope held.** Client-side auth/session only. No backend
  auth bypass, no Mongo writes, no data changes, no Save/Mark Ready/
  Post, no matcher/classifier/routing/Square9/DocuSign/HTTPS work.

### Operator commands (post-this-change)

```
# laptop, one-time
pip install playwright
python -m playwright install chromium

# 1. capture login state
python tools/capture_hub_storage_state.py \
  --hub-origin http://4.204.41.190:8080 \
  --out hub_storage_state.json

# 2. run DOM check locally with that state
python tools/run_ap_smoke_dom_check_local.py \
  --hub-origin http://4.204.41.190:8080 \
  --storage-state-path hub_storage_state.json
```

Outputs: `prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv`,
`AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md`, `ap_smoke_walk_screens/*.png`.


## 2026-05-08 — AP UAT readiness frontend fixes (live in production)

Three frontend-only fixes shipped to production and verified on the two
P0 metadata-cleanup documents (Hawkemedia, XPO). The Hub is now usable
for an internal IT/Alani smoke walk. Accounting still not engaged.

- **Fix 1 — AP Review panel above PDF preview.** `<APReviewPanel>` block
  in `frontend/src/pages/DocumentDetailPage.js` moved from below the
  PDF preview to immediately after the Stable Vendor Routing card.
  Wrapped in `<div id="ap-review-panel" data-testid="ap-review-panel-anchor">`.
- **Fix 2 — Plain-English warnings.** New `labelForWarning()` helper in
  `frontend/src/lib/blockerLabels.js`. Both warning render sites in
  `DocumentDetailPage.js` (BC Validation card, Derived State Summary)
  routed through it. Mapped seven check_name codes including
  `freight_direction_unknown`. No `JSON.stringify` fallback.
- **Fix 3 — Plain-English blocking issues with sentence-case
  preservation.** `derivedState.blocking_issues` now mapped through
  `labelForBlocker` and deduped by display text. `labelForBlocker`
  short-circuits on whitespace so already-human strings are returned
  unchanged (no Title Case mangling). New BLOCKER_LABELS entries:
  `vendor_match` → "Vendor match failed", `po_validation` → "PO
  validation failed".
- **Tests:** 14 unit tests in
  `frontend/src/lib/__tests__/blockerLabels.test.js`, all green; lint
  clean on touched files.
- **Bundle hash on prod:** `main.17bcddab.js` (was `main.b74d42e1.js`).
- **Strict scope held:** frontend render only. No backend / matcher /
  classifier / routing / Square9 / cutover / DocuSign / HTTPS / Mongo
  writes.

### Engineering hygiene backlog (parked, not started)

- **Document Intelligence empty-state endpoints — normalize 404 → 200
  empty payload.** `GET /api/document-intelligence/{doc_id}` and
  `GET /api/document-intelligence/decision/{doc_id}` raise 404 by
  design when no result has been generated yet (see
  `backend/routers/document_intelligence.py` lines 418–424 and
  373–379). Frontend handles it via `try/catch` and renders the
  "No intelligence result yet" empty state correctly, but the browser
  network layer logs the 404 to DevTools console regardless.
  - **Reason parked:** UI behaves correctly. AP testers will not have
    DevTools open. Does **not** block AP UAT.
  - **Suggested fix:** return 200 with `{"exists": false, "result": null}`
    when no resource exists, mirroring the pattern already used by
    `/resolution/{doc_id}` and `/transaction-matches/{doc_id}` in the
    same router. ~6 lines, two hunks.
  - **Pickup gate:** after AP UAT smoke testing completes.

### Internal status snapshot

`prod_reports/AP_UAT_READINESS_STATUS_2026-05-08.md` written —
captures bundle hash, per-fix file paths, P0 verification, posture
fence, next action (internal IT/Alani smoke walk using the existing
quick-start + smoke set), and the parked Document Intelligence 404
backlog item.


## 2026-02 — Document Body Reconciliation: AP Feedback Loop (`--rerun-rows-csv`)

Targeted rerun mode added to `backend/scripts/document_body_reconciliation_probe.py`
so the AP team can re-score specific Square9↔Hub pairs after backfilling
Hub metadata (without rerunning the entire 100-row sweep).

- New CLI flag `--rerun-rows-csv PATH`. Required columns: `square9_name`,
  `hub_doc_id`. When set, the probe filters the triage source down to
  only rows whose `square9_name` appears in the rerun CSV and seeds
  `hub_doc_id` into the candidate set per row via the existing
  `score_signals_against_hub(priority_hub_doc_id=...)` and
  `probe(priority_hub_doc_id_by_row=...)` plumbing.
- New helpers: `read_rerun_rows_csv()`, `filter_to_rerun_subset()`,
  `RERUN_CSV_REQUIRED_COLUMNS` constant.
- Fail-loud exit codes: missing rerun CSV (rc=4), empty rerun CSV (rc=4),
  zero overlap with triage source (rc=5).
- Tests: 11 new pytests (101 total in
  `tests/test_document_body_reconciliation_probe.py`, all green) covering
  the CSV reader (happy path, missing file, missing columns, empty,
  blank-name skip), `filter_to_rerun_subset()`, priority-doc threading
  in `score_signals_against_hub` and end-to-end through `probe()`, plus
  `main()` smoke tests for happy-path subset filtering, missing CSV,
  empty CSV, and zero-overlap-with-triage refusal.
- Strictly read-only. No Mongo writes. No matcher production changes
  beyond the already-approved probe rerun plumbing. No routing /
  classifier / Square9 / cutover / DocuSign / HTTPS work.


## 2026-05-06 — Cutover Proof Pack v2 + Bucket A Apply (gated)

**Read-only proof pack (no production writes)** — extended with key
counts, a deterministic projection of the post-Bucket-A match rate, and
inline IT/AP ticket detail. Plus the **gated Bucket A apply script**
(strict `--apply --confirm CUTOVER` requirement, mongomock-tested
end-to-end in preview).

Proof-pack changes
- Stage 10 added: `bucket_C_handoff_doc` regenerates the IT/AP ticket
  pack (`bucket_C_handoff.{md,csv}`) on every run; both files are
  snapshotted into the proof_dir.
- `cutover_proof_summary.py` now loads the parity payload AND the two
  remediation-plan JSONs. Surfaces:
  - `parity.matched_count` derived from
    `exact_match + strong_evidence_match + likely_match + possible_match`
    (matches the parity script's match-rate formula);
  - `bucket_A.actionable_cohorts/docs/manual_review`,
    `change_type_counts`;
  - `bucket_C.intake_change_cohorts/exclusion_cohorts` plus per-cohort
    detail (vendor / channel / owner / recommended action / doc count)
    rendered inline in both summary.md and the CLI banner;
  - **PROJECTED MATCH RATE AFTER BUCKET A APPLY** computed as
    `(matched + bucket_A_actionable_docs) / square_count`, tagged as
    "clears the gate" or "Bucket A apply NOT sufficient" against
    `MIN_MATCH_RATE`.
- Robustness fixes from the live VM run:
  - parity log preamble (Graph token, listing prose) parsed by scanning
    for the first `{` line;
  - `Traceback (most recent call last):` in any step log forces rc>=3 in
    both the bash orchestrator AND the summarizer (defense in depth);
  - `PROOF_SINCE_HOURS` env override (default 168h = 1 week);
  - `--triage-square9-only` flag added to the parity stage so the
    triage CSV exists for downstream stages.

Bucket A apply (live writes — gated)
- `scripts/bucket_A_one_shot_data_patch_apply.py` — opt-in apply
  companion to the existing dry-run. Idempotent via
  `remediation_audit.source = "bucket_A_one_shot_patch"`. Writes
  `prod_reports/apply_bucket_A_<UTC-ts>/rollback.json` BEFORE any
  `update_one`. Refuses without `--apply --confirm CUTOVER` (rc=3).
  Exit codes: 2 dry-run / 3 refused / 4 updates applied / 5 all already
  idempotent.
- Tests: `tests/test_bucket_A_one_shot_data_patch_apply.py` —
  mongomock-backed end-to-end coverage of build_set_payload,
  is_already_applied, snapshot_doc_for_rollback, the apply path
  (happy / idempotent / docs missing / non-one-shot cohorts ignored /
  rollback-before-update ordering / cohort-key fidelity), and CLI
  refusal without `--confirm`.

Aggregate green suite: 153/153 (added 9 cutover_proof key-counts +
12 apply tests on top of the existing 132).

Live data observed on this VM (168h window):
- Square9 docs: 247
- Hub AP docs: 298
- matched (computed): 89 → 36.03%
- Bucket A actionable cohorts: 5 / actionable docs: 43 / manual review
  cohorts: 35
- Bucket A change_type_counts: routing_rule_addition=3,
  one_shot_data_patch=1, classifier_signal_uplift=1
- Bucket C intake-channel-change cohorts: 12 / parity exclusions: 1
- Projected match rate after Bucket A apply alone:
  (89 + 43) / 247 = 53.44% (insufficient; Bucket C intake-channel work
  also required to reach 85%).

## 2026-05-06 — Square9 Cutover Proof Pack (read-only, packaged)
**Single-command, repo-owned production verification harness** for the
Square9 cutover. Runs all 9 readiness probes in dependency order,
captures every artifact under one timestamped directory, and renders a
hard **GO / NO-GO** decision based on per-step exit codes plus the
parity report's `match_rate_pct`. Strictly read-only — no Mongo writes,
no Exchange / mailbox / transport-rule changes, no cutover toggle.

- `ops/prod_verify_square9_cutover_readiness.sh` — bash orchestrator.
  Runs ap_cutover_readiness → billing_intake_routing → square9 parity →
  triage_resolver → bucket_A root_cause → bucket_C intake_gap →
  bucket_A remediation plan → bucket_C remediation plan →
  email_poll_watermark probe. Captures stdout/stderr/rc per step into
  `prod_reports/cutover_proof_<UTC-ts>/logs/`, snapshots the parity
  JSON, and assembles `manifest.json`. Final exit code propagates from
  the summarizer (0 = GO, 1 = NO-GO).
- `ops/cutover_proof_summary.py` — pure-Python decision engine. Reads
  the manifest + parity JSON, classifies each step (rc 0 = ok / rc 1-2
  = ok_signal / rc ≥ 3 = fail), derives blockers (failed steps,
  missing `match_rate_pct`, below-threshold `match_rate_pct`), renders
  `summary.json` + `summary.md`, prints a structured GO/NO-GO banner.
- `ops/README.md` — operator documentation: what it does / does NOT do,
  one-line VM run command, output layout, decision rules, stage list.
- `docker-compose.yml` — added `./prod_reports:/app/prod_reports` bind
  mount under the backend service so cutover artifacts persist on the
  host across container rebuilds.
- **Tests**: `backend/tests/test_cutover_proof_summary.py` (24/24
  passed) — synthetic fixtures, covers step classification, match-rate
  extraction (incl. nested `summary` and 0–1 fraction conversion),
  blocker derivation, GO/NO-GO branches, MD/text rendering, manifest
  round-trip via `tmp_path`, and CLI integration via `monkeypatch`.
- **End-to-end smoke**: orchestrator stubbed with rc=0 / rc=2 step
  scripts produces correct manifests and decisions in both branches.
- **Aggregate green suite**: 112/112 (24 cutover_proof + 46 dry-run +
  42 remediation-plan).
- **One VM command** (after `git pull`):
  `docker compose exec backend bash ops/prod_verify_square9_cutover_readiness.sh`

## 2026-05-06 — Square9 Cutover P0: Bucket A + Bucket C Dry-Run Scripts
**New read-only dry-run preview scripts** that show *exactly* what the
Bucket A patch and routing-rule additions would do, plus an operator
handoff doc for the Bucket C intake-channel changes. **No Mongo writes,
no routing-rule registrations, no classifier changes.**

- `backend/scripts/bucket_A_one_shot_data_patch_dryrun.py` — consumes
  `bucket_A_remediation_plan.json` (cohort filter:
  `change_type == "one_shot_data_patch"`) and `bucket_A_root_cause.csv`
  (authoritative per-doc list). For every per-doc row in a one-shot
  cohort, emits the exact `db.hub_documents.update_one` it would run,
  setting `mailbox_category="AP"`, `doc_type="AP_INVOICE"`,
  `suggested_job_type="AP_Invoice"`, plus a `remediation_audit` subdoc
  `{source: "bucket_A_one_shot_patch", cohort_key, applied_at: null}`.
  Outputs `prod_reports/bucket_A_one_shot_data_patch_dryrun.{csv,json}`.
  Exit codes: 0=no one-shot cohorts / 1=cohorts but no matching rows /
  2=patch previews emitted.
- `backend/scripts/bucket_A_routing_rule_addition_dryrun.py` — consumes
  the same plan JSON (cohort filter:
  `change_type == "routing_rule_addition"`) and emits one routing-rule
  preview row per cohort with `(sender_glob, target_mailbox_category,
  target_doc_type, target_suggested_job_type, priority,
  affected_doc_count, source_cohort_*)`. Priority is derived from
  `confidence_band` (high=10 / medium=20 / low=30) with score fallback.
  Outputs `prod_reports/bucket_A_routing_rule_addition_dryrun.{csv,json}`.
  Exit codes: 0=no routing-rule cohorts / 1=all cohorts skipped (no
  email_sender) / 2=rules emitted.
- `backend/scripts/bucket_C_handoff_doc.py` — consumes
  `bucket_C_remediation_plan.json` and renders an operator-friendly
  Markdown grouped by `owner_hint` (IT vs AP) with one table + checklist
  per owner, plus a "Parity exclusions" section and a cutover checklist.
  Mirrors all rows into a CSV importable into ticket trackers. Outputs
  `prod_reports/bucket_C_handoff.{md,csv}`. Exit codes: 0=empty plan /
  1=only exclusions / 2=intake cohorts emitted.
- **Tests**:
  `backend/tests/test_bucket_A_one_shot_data_patch_dryrun.py` (16/16),
  `backend/tests/test_bucket_A_routing_rule_addition_dryrun.py` (18/18),
  `backend/tests/test_bucket_C_handoff_doc.py` (12/12). Pure synthetic
  fixtures, no Mongo, no network. Covers selection, cohort-key matching,
  update_one shape, audit subdoc immutability, priority derivation,
  owner grouping, MD/CSV round-trip via `tmp_path`, and exit-code
  contract.
- **Aggregate green suite (Bucket A/C scope)**: 88/88 passed (42 prior
  remediation-plan tests + 46 new dry-run tests).
- **Live VM smoke**: not yet executed (user runs on remote VM). Run
  commands provided.

---


# GPI Document Hub — Product Requirements Document

## 2026-05-06 — Square9 Cutover P0: Bucket A + Bucket C Remediation Plan Generators
**New read-only plan generators** consume the diagnostic outputs from
`bucket_A_root_cause_report.py` and `bucket_C_intake_gap_report.py` and
emit per-cohort remediation plans for AP-routing reclassification and
intake-channel expansion. No live mutations; no DB writes; no classifier
or routing-logic changes.

- `backend/scripts/bucket_A_misrouting_remediation_plan.py` — reads
  `prod_reports/bucket_A_root_cause.csv`, groups by `(email_sender,
  classification_method, current_mailbox_category, current_doc_type,
  current_suggested_job_type, sharepoint_folder_root)`, emits per-cohort
  proposed targets (`AP / AP_INVOICE / AP_Invoice`), `change_type`
  drawn from a closed taxonomy (`routing_rule_addition`,
  `one_shot_data_patch`, `classifier_signal_uplift`, `manual_review`),
  `confidence_band` (high≥0.90 / medium 0.60–0.89 / low <0.60),
  evidence sample of 3 doc_ids, and risk notes. Cohort cutoff:
  `affected_doc_count >= 2 AND avg_score >= 0.60` to be "actionable";
  everything else → `manual_review_queue`. Outputs CSV/JSON/YAML to
  `prod_reports/bucket_A_remediation_plan.{csv,json,yaml}`.
- `backend/scripts/bucket_C_intake_remediation_plan.py` — reads
  `prod_reports/bucket_C_intake_gap.csv`, partitions into
  `parity_exclusions` (PSTs, treasury, templates, monthly recs, "DO NOT
  PAY" markers) and `intake_channel_changes` (real intake gaps).
  Intake cohorts keyed on `(likely_vendor, candidate_intake_channel)`
  with recommendation drawn from a closed taxonomy
  (`add_sender_to_AP_transport_rule`, `enable_portal_download`,
  `forward_billing_alias_to_hub_ap_intake`, `manual_followup`) plus
  owner_hint (IT/AP). Outputs CSV/JSON/YAML to
  `prod_reports/bucket_C_remediation_plan.{csv,json,yaml}`.
- `backend/scripts/print_top_remediation_plans.py` — convenience CLI to
  print the top N cohorts from both plan JSONs.
- **Tests**: `backend/tests/test_bucket_A_misrouting_remediation_plan.py`
  (24/24 passed) + `backend/tests/test_bucket_C_intake_remediation_plan.py`
  (18/18 passed) — synthetic CSV fixtures, no Mongo. Covers the
  decision matrix, confidence bands, cohort-cutoff thresholds, IO
  round-trip, exit codes, and source-inspection guardrails proving the
  modules import no `pymongo`/`motor` and make no mutating HTTP calls.
- **Aggregate Square9 suite**: 79/79 passed (28 prior diagnostic + 9
  triage + 42 new remediation-plan tests). Lint clean.
- **Exit codes**: `0` empty input; `1` rows present but no actionable
  cohorts; `2` actionable cohorts emitted.
- **Strict scope fence**: no DB writes, no classifier/routing/transport-
  rule changes, no parity-report changes, no CFO summary, no cutover
  call, no DocuSign/HTTPS/parked-AP work.


## 2026-05-06 — Square9 Cutover P0: Invoice-Document-Set Parity Proof
**Patched** `backend/scripts/square9_hub_ap_parity_report.py` to support
strongest-form parity proof per signed declaration "combine a + d":

- New `extract_date_from_filename()` parses ISO / US / compact dates.
- `HubDoc.invoice_date` populated from `extracted_fields.invoice_date`
  (fallback `extracted_fields.inv_date`, fallback top-level
  `invoice_date`).
- `score_pair(..., invoice_date_tolerance_days=None)` adds three
  invoice-date-evidence tiers:
    * `invoice_number_clean+invoice_date_proximity` → strong (0.90)
    * `vendor_canonical+amount_float+invoice_date_proximity` → strong (0.85)
    * `vendor_canonical+invoice_date_proximity` → likely (0.72)
  Date is supporting evidence only, never a sole match key. Default
  kwarg=None preserves legacy behavior (object-identity-grade
  regression guard test added).
- New `pull_expanded_ap_corpus()` does Temp Folder non-recursive +
  AP root recursive, deduped by Graph item id (fallback
  parent_path/name case-insensitive).
- `run_compare()` accepts `match_by_invoice_date` +
  `invoice_date_tolerance_days`; returns `proof_mode` +
  `invoice_date_tolerance_days` keys.
- CLI: `--expanded-ap-corpus`, `--prod-ap-root-path`,
  `--prod-ap-temp-folder-name`, `--match-by-invoice-date`,
  `--invoice-date-tolerance-days` (default 30).
- JSON output exposes `proof_mode`, `hub_window_hours`,
  `square9_modified_window_hours`, `invoice_date_tolerance_days`,
  `expanded_ap_corpus`, `square9_docs_count`, `hub_ap_docs_count`,
  `bucket_counts`, `match_rate`, `blockers`, `warnings`.
- Backward-compat JSON aliases retained: `square_count`, `hub_count`,
  `since_hours`, `prod_modified_since_hours`.

**Tests:** `backend/tests/test_square9_hub_ap_parity_report.py` —
**28/28 passed** (14 prior + 14 new). New tests cover: filename date
extraction (ISO/US/compact/none), invoice-date mode ignores
ingest-time skew, vendor+amount+date passes with filename mismatch,
low match rate still blocks under invoice-date mode, expanded-corpus
dedupe by Graph id and parent_path fallback, proof_mode metadata
round-trip, HubDoc invoice_date parsing, default-kwarg legacy parity.

**Cutover remains blocked.** Operator runs the new command on the VM:

    docker compose exec -T backend python -m scripts.square9_hub_ap_parity_report \
        --since-hours 720 --prod-modified-since-hours 720 \
        --expanded-ap-corpus --match-by-invoice-date \
        --invoice-date-tolerance-days 30 \
        --limit 1000 --top 25 --min-match-rate 0.85 \
        --out-csv prod_reports/square9_hub_ap_parity_invoice_set.csv

Cutover unblocks only when `match_rate >= 0.85` AND `blockers == []`
in invoice-document-set mode.

**Out of scope (preserved):** routing/classification logic, DocuSign
Phase 4, parked AP contamination, HTTPS migration, CFO summary
population, `POST /api/square9/archive-stage-data`.

## 2026-05-06 — Square9 Cutover P0: Email Poll Watermark Strict-gt Cursor Fix
**Root cause identified and patched.** AP intake was silently dead from
2026-04-09 (last successful ingest run `450f2bb4`) through 2026-05-06.
4,199 polling runs in that window all reported `attachments_ingested=0`.

The bug: in `services.email_polling_service.poll_mailbox_for_attachments`
the Graph $filter was `receivedDateTime ge {watermark - 5min}` combined
with `$top=25, $orderby=receivedDateTime asc`. With ≥25 messages clustered
inside a 5-minute window at the watermark, every cycle re-fetched the same
25 oldest, `max(batch.receivedDateTime) == watermark`, watermark never
advanced, polling looped on the same set forever. Production:
hub-ap-intake@gamerpackaging.com watermark stuck at 2026-04-09T21:02:12Z.

**Code patch:**
- `backend/services/email_polling_service.py`:
  - Replaced `ge {watermark - 5min}` with strict `gt {watermark}` (no buffer).
  - Watermark write now requires `newest_received > watermark_time`.
  - When a non-empty batch fails to advance the watermark, record
    `stalled_watermark` audit block on the `mail_poll_runs` row and emit
    a WARNING log line (defense-in-depth canary).
  - Run stats now include `watermark_in`, `watermark_out`,
    `watermark_advanced`.
**Tests added:**
- `backend/tests/test_email_polling_watermark.py` — 4 tests:
  1. strict gt cursor in $filter (no 5-min back-buffer)
  2. 25 dup messages at boundary do not trap polling
  3. watermark advances to max(receivedDateTime) when newer messages seen
  4. stalled_watermark audit block recorded when batch cannot advance
**Test results:** 7/7 passed in prod container (4 new + 3 prior failure-audit).
**Prod verification (within 9 minutes of restart):**
- Watermark advanced 2026-04-09 → 2026-04-14 in 3 cycles.
- Within ~9 hours, watermark caught up to 2026-05-06T01:48:05Z (present).
- AP docs since 2026-04-21 grew from 0 to 264.
- GPI-CUTOVER-TEST ingestion confirmed (1 unique-subject row).
- 0 stalled_watermark events.

**Pre-cursor: Exchange transport rule (no code, write to Exchange config):**
Added `New-TransportRule "GPI-Hub-AP-Intake-Copy-Billing"` (Priority 41,
Enabled, Enforce) — BCCs mail addressed to `billing@gamerpackaging.com`
(M365 Group) into `hub-ap-intake@gamerpackaging.com` (SharedMailbox).
Mirrors the existing `ap@`-targeted rule. Loop-protected via
`-ExceptIfAnyOfRecipientAddressContainsWords hub-ap-intake@…`. Used
`-AnyOfRecipientAddressContainsWords` since `-SentTo` rejects M365 Groups.

**Known follow-ups (NOT for cutover, parked):**
- 3 Graph "Failed to fetch attachments" errors in run `cabd3161`
  (window 2026-05-04T20:50:52Z..2026-05-05T20:22:54Z). Watermark advanced
  past them so no auto-retry. Same behavior as pre-patch (not a
  regression). Manual replay possible if those messages are required.
- 188 historical messages addressed to `billing@` between 4/26 and 5/6
  arrived in `hub-ap-intake@` via the older `ap@` rule but were never
  ingested (trapped behind the stuck watermark). The strict-gt drain has
  now picked up most of them as the watermark advanced; remaining gaps
  can be quantified post-drain.
- `square9@gamerpackaging.com` is still a Subscriber+Member of the
  `billing@` Unified Group. Remove only after Square9 cutover.
- Per-mailbox watermark `mailbox_watermark:hub-ap-intake@` (last value
  `2026-04-21T22:33:35Z`, updated 2026-04-22) is from a separate
  per-mailbox-source code path (`poll_mailbox_for_documents`) that no
  longer runs for this address since `hub-ap-intake@` is not in
  `mailbox_sources`. Stale but inert; safe to leave.

## 2026-05 — Square9 Cutover P0: Mail Poll Audit + AP Source Cleanup
**Code (lint clean, 3/3 regression tests passing in prod):**
- `backend/services/email_polling_service.py` — `poll_mailbox_for_documents`
  rewritten so every poll cycle is observable:
  - Adds `status` (`ok` / `failed_graph` / `failed_token` / `failed_exception`)
    and `graph_http_status` to the stats payload.
  - Captures Graph non-2xx body excerpt on failure.
  - **Always** inserts an audit row to `mail_poll_runs` (was never
    inserted before — the silent-swallow root cause).
  - Logs `Complete:` on success, `FAILED:` on failure with
    mailbox/category/HTTP status/errors.
- `backend/tests/test_mailbox_poll_failure_audit.py` — 3 regression tests
  covering Graph 404, missing token, and steady-state all-duplicate.
**Data (non-destructive):**
- Disabled `billing@gamerpackaging.com` in `mailbox_sources` with
  `enabled=false`, `disabled_at`, `disabled_reason`. Source had been
  silently 404'ing from Graph for ≥7 days. The working AP intake is
  `hub-ap-intake@gamerpackaging.com`.
**Open operational gate (NOT code):**
- `hub-ap-intake@gamerpackaging.com` inbox has had no new mail with
  attachments since 2026-04-09. Verify Exchange forwarding rule
  (`billing@` → `hub-ap-intake@`) before declaring cutover-ready.

## 2026-05 — Square9 Cutover Probe Schema Fix
Patched `backend/scripts/ap_cutover_readiness_report.py` and
`backend/scripts/billing_intake_routing_probe.py` to match the real
`hub_documents` schema:
- `created_utc` is stored as ISO-8601 string. Cutoff comparison switched
  from `datetime` to ISO-string (BSON type-mismatch fix).
- `billing@gamerpackaging.com` is a destination mailbox, not a sender.
  Added `--ap-only` flag (default true) using
  `mailbox_category == "AP"`. `--mailbox` retained as opt-in via
  `--no-ap-only`.
- No tests, routing logic, classification logic, or cutover code
  touched.
**Prod VM 30d-window verification:** READINESS_EXIT=0, BILLING_PROBE_EXIT=0,
0 cutover-blocking findings, 344 AP-tagged docs, 0 in AP Temp Folder, 0
leaks to Operations, 0 weak-fallback anomalies. Outstanding warnings
are legacy `classification_method='mailbox:AP'` on historical docs and
the 7-day AP-intake silence (operational, separate from routing
correctness).

## Latest Phase Shipped — Phase 4C(c): PDF Body Extraction (2026-02)
Deterministic regex-based extraction of contractual fields from legacy
agreement PDFs that DocuSign templates / Navigator metadata cannot
carry. Five field families: freight terms, MOQ (header + per-line),
volume commitment, tooling amortization, payment-term cash discount,
volume tier discount. Opt-in via admin-gated HTTP endpoint
(`POST /api/contracts/agreements/{id}/pdf-extract`) and CLI
(`scripts.contracts_extract_pdf`). Default dry-run; `commit=true`
upserts idempotently into `agreement_terms` (source=`pdf_body`),
`agreement_obligations` (kinds `volume_commitment`,
`tooling_amortization`), and `agreement_pricing.min_quantity`. Same-key
ambiguities surface as `pdf_extraction_ambiguous` low-severity
exceptions. No DocuSign SDK install, no live envelope fetch, no BC
writes, no Document Hub linking. **VM-verified 253 passed / 8 skipped /
1 xfailed (Phase 4C(d) baseline of 192 preserved + 61 new).**

## Original Problem Statement
Build and continuously refine the Sales/AP Modules and Document Inbox with AI autonomy and continuous learning. Goal: aggressively shrink the Inbox "Needs Review" queue by closing validation gaps (PO, Customer, Vendor, SO, Duplicate) so docs are auto-routed.

## Core Product Requirements
1. Per-Document Intelligence Engine
2. Advanced Intelligence Engines (Gap Closers) for POs, Customers, Vendors, SOs, Duplicates
3. Accurate validation gap reporting across monitoring dashboards
4. Auto-resolution of high-confidence vendor aliases
5. Executive Monitoring Dashboard (`/monitor`)
6. Vendor Profile Consolidation
7. Exception and Retry mechanisms
8. Inbox Metrics Panel — Detailed breakdown of docs IN the inbox by Status, Type, Age, Vendor, Blocker
9. Captured Doc Auto-Retry — Docs stuck in "captured" get 4 retries then escalate to Exception Queue

## Architecture
- **Frontend**: React (Vite) with Shadcn UI, dark theme
- **Backend**: FastAPI with MongoDB
- **Deployment**: Docker on Azure VM (git pull → docker compose up)
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## Key File References
- `/app/backend/routers/dashboard.py` — inbox-stats, inbox-metrics, insights endpoints
- `/app/backend/routers/readiness.py` — Force cleanup, Exception retry, PO park/retry, Captured retry
- `/app/backend/routers/documents.py` — Queue endpoints, TERMINAL_STATUSES, is_duplicate filter
- `/app/backend/routers/aliases.py` — Vendor matching & alias suggestions
- `/app/backend/routers/workflow_fix.py` — Batch-fix stuck "captured" docs
- `/app/backend/routers/intake_learning.py` — Hub-wide BC+Spiro learning endpoints (2026-04-18)
- `/app/backend/services/sales_intake_learning_service.py` — Giovanni-pattern orchestrator (2026-04-18)
- `/app/backend/services/order_line_patterns.py` — Core pattern learning engine (Giovanni C-10250)
- `/app/backend/services/unified_validation_service.py` — Validation facade + intake_learning stage
- `/app/backend/server.py` — Main server, background schedulers (PO retry, Captured retry), intake pipeline
- `/app/frontend/src/pages/UnifiedQueuePage.js` — Inbox with metrics panel, retry-stuck button, tabs
- `/app/frontend/src/pages/IntakeLearningPage.js` — Intake-learning dashboard (2026-04-18)
- `/app/frontend/src/components/IntakeLearningPanel.jsx` — Drop-in insights panel (2026-04-18)

### 2026-04-18 — Intake Learning v2.5.1 (Giovanni + Feedback + Cold-Start + Unified Core)
- **v2.2.0**: Generalized Giovanni/Nikki blanket-PO BC learning (C-10250) to every ingested doc + XLS spreadsheet
- **v2.2.1**: IntakeLearningPanel on every Document Detail page; de-pilotized UI labels
- **v2.3.0**: Learning feedback loop — thumbs-up/down buttons, pattern trust/retire, hygiene scheduler, Pattern Health dashboard
- **v2.4.0**: Cold-start peer matching — pure-python TF-IDF fingerprints + inherited suggestions + promote-to-own
- **v2.4.1**: Learning Core U1 — unified `learning_events_v2` collection + dual-write from intake, cold-start, and AP draft feedback
- **v2.5.0**: Proactive Drift Alerts — 5 drift rules scan unified log nightly (trusted-pattern drift, reject spike, bounds drift, AP template drift, catalog explosion), inline Ack/Resolve UI
- **v2.5.1**: Learning Core U2 — shared TF-IDF fingerprint service for both customer (intake) and vendor (AP); unified `scope_fingerprints` collection
- Read-only wrt BC. 42/42 pytest + testing agent iter 210/211/212/213/214 all 100% green. Giovanni data kept pristine.

### 2026-04-28 — P1.K hotfix: lazy MSAL init (insecure-origin white-screen regression)
- **Bug introduced by P1.K**: `frontend/src/lib/msalConfig.js` constructed `new PublicClientApplication(msalConfig)` at module load. On insecure origins (e.g. `http://4.204.41.190:8080` — public IP over plain HTTP), `window.crypto.subtle` is unavailable, MSAL's `BrowserCrypto` constructor threw `crypto_nonexistent`, and the entire React tree crashed before mount → **white screen**, even with `REACT_APP_ENTRA_AUTH_ENABLED=false`. Reported via VM cutover smoke; reproduced and confirmed.
- **Fix scope** (3 files; no new files; no backend touch):
  - `lib/msalConfig.js`: removed eager `msalInstance` export. Added `getMsalInstance()` that lazily constructs the singleton **only when** `flagOn() && window.isSecureContext === true`. Construction errors are caught and downgrade to legacy auth instead of crashing. `entraAuthEnabled()` now also gates on `isSecureContext` so insecure origins always take the legacy path even if the flag is on.
  - `lib/entraAuth.js`: every helper (`acquireEntraToken`, `entraLogin`, `entraLogout`, `getActiveEntraAccount`) reads through `getMsalInstance()` and short-circuits to `null` / no-op when the singleton is null. No behavior change on HTTPS.
  - `index.js`: `<MsalProvider>` is rendered only when `getMsalInstance()` returns non-null; otherwise `<App/>` mounts directly. Pre-P1.K behavior fully restored on insecure origins.
- **Verification**:
  - HTTPS preview, flag OFF: legacy form renders; no Entra UI. ✅
  - HTTPS preview, flag ON: Entra button + legacy fallback both render; no errors. ✅
  - HTTPS preview with `isSecureContext` simulated to `false` and flag ON (mimics VM HTTP origin): page renders legacy form; **zero pageerrors**; no white screen. ✅ (regression fix verified via Playwright `add_init_script` overriding `window.isSecureContext`).
  - Backend P1.H suite: **30/30 passed** in 5.04s — zero regression.
  - `/openapi.json` paths = **858** (unchanged).
- **Lint**: 0 issues across 3 touched frontend files.
- **Posture committed**: `REACT_APP_ENTRA_AUTH_ENABLED=false` default. Cutover on the VM still requires HTTPS origin to actually exercise Entra; the hotfix only ensures the page doesn't white-screen when MSAL can't initialize.
- **Operator action**: pull, `docker compose build --no-cache frontend`, `docker compose up -d`. The legacy login on `http://4.204.41.190:8080` should now work again. To exercise Entra, move the frontend behind an HTTPS origin and register that origin as the SPA redirect URI in the Entra app registration.



### 2026-04-23 — Phase 1 P1.K — MSAL frontend auth (dormant; flag-gated)
- **Packages added** (yarn): `@azure/msal-browser@5.8.0` + `@azure/msal-react@5.3.1` (v5 explicitly supports React 19.2.1+; pin upgraded from the v2/v3 noted in earlier playbook drafts after registry check).
- **New files (3)**: `frontend/src/lib/msalConfig.js` (PublicClientApplication singleton; sessionStorage cache; redirectUri = `window.location.origin`), `frontend/src/lib/entraAuth.js` (`acquireEntraToken` silent → interactive popup fallback, `entraLogin`, `entraLogout`, `getActiveEntraAccount`, `accountToLegacyUser`, `entraAuthEnabled` re-export), `frontend/src/components/EntraSignInButton.jsx` (Microsoft sign-in button styled to match the existing legacy submit button; `data-testid="entra-signin-btn"`).
- **Modified files (4)**: `frontend/src/index.js` wraps `<App/>` with `<MsalProvider>`; `frontend/src/lib/api.js` request interceptor now async — Entra-first when flag on, falls back to legacy `localStorage.gpi_token` on miss/failure; `frontend/src/context/AuthContext.js` `login`/`logout` branch on flag (Entra path persists `accountToLegacyUser(account)` to `gpi_user` so all downstream consumers keep working byte-identically); `frontend/src/pages/LoginPage.js` renders the Entra button + divider above the legacy form when flag on.
- **Frontend `.env` additions** (additive only): `REACT_APP_ENTRA_AUTH_ENABLED=false` (default OFF — dormant on merge), `REACT_APP_ENTRA_TENANT_ID`, `REACT_APP_ENTRA_CLIENT_ID`, `REACT_APP_ENTRA_API_SCOPE`. No protected vars touched.
- **Auth flow when flag ON**: click "Sign in with Microsoft" → `loginPopup` → MSAL session cache → axios interceptor pulls a fresh access token per request via `acquireTokenSilent` (fallback `acquireTokenPopup` on `InteractionRequiredAuthError`). Backend hybrid facade (`get_current_user_hybrid` from P1.H) accepts the Entra Bearer token; legacy bcrypt path stays live behind `LEGACY_AUTH_ENABLED=true` for the migration window.
- **Smoke test (Playwright)**:
  - Flag OFF: `entra_btn=False, legacy_form=True, legacy_email_input=True` ✅ — UI byte-identical to pre-P1.K.
  - Flag ON: `entra_btn=True, entra_section=True, legacy_form=True, legacy_email_input=True` ✅ — both sign-in surfaces render; legacy fallback retained.
- **Backend regression**: P1.H suite re-run **30/30 passed** in 4.45s. `/openapi.json` paths = 858 (unchanged). No backend files touched.
- **Lint**: 0 issues across all 7 touched/new frontend files.
- **Default posture committed**: `REACT_APP_ENTRA_AUTH_ENABLED=false` + `ENTRA_AUTH_ENABLED=false`. Cutover requires flipping both flags + completing the Entra app registration's SPA redirect URI configuration.
- **Out of scope** (per signed declaration): `/api/auth/whoami` debug endpoint, RBAC enforcement (P1.C), actor context propagation (P1.J), `governance_audit_log` (P1.A), legacy auth removal, scope-typo cleanup, multi-tenant federation, MFA tier.
- **Next**: cutover smoke against the live Entra tenant on the production VM, then P1.C (RBAC enforcement on the 30 already-classified mutating endpoints + remaining P0.1 sub-passes).



### 2026-04-23 — Phase 1 P1.H — Backend Entra ID token validation (deps-only, dormant)
- **New canonical module** `backend/services/entra_auth.py` is the sole authority for Entra-issued token validation. Exports: `Actor` dataclass, `JWKSCache` (TTL=900s, kid-miss refresh, stale-on-network-fail), `validate_entra_token()`, `get_current_actor` FastAPI dep, `require_role(*roles)` factory, `require_app_only()` factory, `get_current_user_hybrid` migration facade.
- **Algorithm**: RS256 only; alg=none/HS256 hard-rejected (downgrade-attack guard). Audience exact-match + issuer match + `tid` claim guard + 30s clock leeway. Required claims: `exp`, `iss`, `aud`. Actor identity via `oid` (fallback `sub`). User-delegated tokens carry `scp`; app-only (service principal) tokens carry `roles` only and surface `Actor.is_app_only=True`.
- **Hybrid facade** (`get_current_user_hybrid`) runs Entra-first then falls back to legacy `services.auth_deps.get_current_user` while `LEGACY_AUTH_ENABLED=true`. `routers/auth.py` and the `/api/auth/login`/`logout`/`me` legacy surface are **byte-identically untouched** in P1.H.
- **Env additions** (additive, no protected-var deletions): `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_API_AUDIENCE`, `ENTRA_AUTHORITY`, `ENTRA_JWKS_URL`, `ENTRA_AUTH_ENABLED=false` (default OFF — module is dormant in dev/prod until P1.K lands), `LEGACY_AUTH_ENABLED=true`.
- **Test surface**: `backend/tests/test_entra_auth.py` — **30/30 passed** in 3.05s. Six classes: A) JWKS cache (TTL/kid-miss/stale-fallback/unknown-kid), B) Happy-path (user + app-only), C) Negative (wrong aud/iss/tid, expired, future-nbf, bad sig, missing kid, alg=none rejected, empty token, 30s leeway), D) Role guard (require_role), E) App-only guard (require_app_only), F) Hybrid facade (Entra-on/legacy-on/both-off paths). All offline — self-signed RSA keypair via `tests/fixtures/entra_test_keys.py` + `ENTRA_JWKS_OVERRIDE` test seam; **zero traffic to login.microsoftonline.com**.
- **Runtime impact**: zero. `/openapi.json` paths = **858** (unchanged). Backend supervisor RUNNING. With `ENTRA_AUTH_ENABLED=false`, the new module loads but never fires.
- **Playbook amendment**: pinned `@azure/msal-react` to `^3.1.0` (was v2.0.0) for React 19 compatibility — applied in P1.K.
- **Next**: P1.K (MSAL.js frontend) to establish a token-minting story before flipping `ENTRA_AUTH_ENABLED=true`. Then P1.C consumes the deps to enforce RBAC on the 407 mutating endpoints per `RBAC_MATRIX.md`.



### 2026-04-23 — Phase 0 P0.1 Refinement Pass (4 two-tier router files)
- **Documentation only — no code changes, no Phase 1 implementation.**
- Refined per-endpoint role assignment in `/app/memory/RBAC_MATRIX.md` for the 4 ambiguous two-tier router files identified during Phase 0 review: `routers/auth.py` (3 endpoints), `routers/dashboard.py` (11), `routers/governance.py` (1), `routers/sales_dashboard.py` (15). 30 endpoints total.
- Approved taxonomy applied: `admin` / `approver` / `reviewer` / `viewer` / `service` (background only). Two pseudo-buckets used where applicable: `public` (login bootstrap only) and `authenticated` (token required, no role gate — for `/auth/me` and `/auth/logout`).
- Endpoint count by role: `public` 1, `authenticated` 2, `viewer` 18, `reviewer` 3, `approver` 2, `admin` 4, `service` 0 (no routes in these 4 files require service-role today).
- Two prior file-level matrix entries corrected by source-of-truth audit: `dashboard.py` ("mutations: reviewer" → **zero mutations** in current code) and `governance.py` ("mutations=admin" → **zero mutations** — module docstring is explicit "READ-ONLY"; mutating governance work lives in other routers).
- File-level table cross-linked: 4 files now show "resolved P0.1 ↓" pointing at the per-endpoint refinement section below.
- **P1.H remains BLOCKED on user-supplied Entra credentials**: Tenant ID, API Client ID, API Scope URI, and optionally SPA Client ID. P1.K (MSAL.js) and P1.C (RBAC enforcement on the 407 mutating endpoints) are downstream of P1.H.
- Phase 3 monolith refactoring remains paused; frozen helpers untouched.



### 2026-04-21 — AP Path Consolidation v2.5.25 (Phases 2 + 3)
- Single canonical AP mutation surface: **`POST /api/ap-review/documents/{doc_id}/{action}`** for `set-vendor`, `update-fields`, `override-bc-validation`, `start-approval`, `approve`, `reject`.
- All Path A mutation routes JWT-gated via `Depends(get_current_user)`; all delegate to `services/workflow_handlers.py` so every transition drives through `WorkflowEngine.advance_workflow`.
- Legacy `/api/workflows/ap_invoice/{doc_id}/{action}` kept live for one release with `deprecated=True` in OpenAPI and `X-Deprecated` headers attached to every response (including HTTPException paths).
- Frontend `lib/api.js` helpers (`setVendor`, `updateFields`, `overrideBcValidation`, `startApproval`, `approveDocument`, `rejectDocument`) repointed to Path A with bodies normalized to canonical Pydantic shapes.
- New regression suite `tests/test_ap_path_consolidation.py` — 36/36 passing. Phase 4 (deletion of Path B) scheduled for next release.



### 2026-04-22 — Deprecation observability + Partial-post integrity v2.5.26
- **Server-side observability of Path B hits:** every `/api/workflows/ap_invoice/{id}/{action}` call emits a `WARNING` log and increments a template-keyed counter in `db.deprecation_hits`. New admin endpoint `GET /api/admin/deprecation-metrics?days=N` aggregates hit counts — used as the hard gate before Phase 4 route removal.
- **Partial-post integrity (auto-post path):** `routers/gpi_integration.py::create_purchase_invoice_from_document` now mirrors `business_central_service` partial-post detection. Header-accepted + lines-rejected flips `success=False`, attempts orphan-draft deletion, and blocks `ap_auto_post_service` from writing `bc_posting_status="posted"`. Financial-integrity leak closed; 4/4 integration tests green.
- **Phase 4 removal plan:** `/app/memory/PATH_B_REMOVAL_PLAN.md` locks the symbols to delete, the hard metric gate (zero hits for 7 days), the rollback path, and the sequence.


- `/app/frontend/src/pages/MonitoringDashboard.js` — Vendor mapping UI

## Critical Data Rule

### 2026-04-22 — Phase 4 gate projection + 422 disclosure v2.5.27
- **Phase 4 one-curl gate check:** `GET /api/admin/deprecation-metrics` response now includes a `phase_4_gate` object with `gate_met` boolean, `offending_callers[]` (caller IP + UA), `hits_by_template`, and `action_if_gate_not_met`. The 7-day window is hard-coded so `?days=N` cannot narrow the gate accidentally.
- **422 blind-spot disclosed in three places:** `_deprecate()` docstring, admin endpoint docstring, `phase_4_gate.observability_limitations[]` field in the payload, plus a dedicated §2c in `PATH_B_REMOVAL_PLAN.md` with a covered-vs-uncovered scenario table. We explicitly say `deprecation_hits` captures valid Path B requests that reach the wrapper — not every malformed attempt.
- **Backlog reorder:** retry/backoff + posting-attempt history sit ahead of server.py decomposition per workflow-integrity priority.
- 7 new tests (`test_deprecation_metrics.py`), full regression 122/125 (3 concurrency skips by design).

- `is_duplicate: {"$ne": True}` must be included in ALL inbox-related queries (documents list, inbox-stats, inbox-metrics) to match the actual inbox view. The documents endpoint enforces this at line 180.


### 2026-04-23 — Phase 3 Step 2R: AP compute-wrapper cleanup
- **Audit correction before signing**: original Phase 3 audit claimed ~220L of AP compute business logic in `server.py:1478-1700`. Reality: 5 one-line compatibility shims totaling ~45L; the real logic was already extracted into `services/ap_computation.py` and `services/document_intel_helpers.py` by a prior step. Scope revised to wrapper-cleanup only.
- **Micro-amendment before coding**: `_build_vendor_resolution` discovered to contain a real try/except fallback (not a pure shim) — intentionally excluded to preserve behavior. Deletion scope narrowed to 5 pure `compute_*` wrappers.
- **Deletions from `server.py`** (5 wrapper functions): `compute_ap_normalized_fields`, `compute_ap_validation`, `compute_ap_status`, `compute_canonical_fields` (legacy alias, zero callers), `compute_draft_candidate_flag`.
- **Direct-import block added** at `server.py` near line 1699: clearly labeled `DIRECT CANONICAL IMPORTS: AP compute functions`. Names preserved, so all 6 call sites (3078, 3150, 3889, 3916, 4760, 5506) resolve to the authoritative service symbols with zero call-site rename.
- **`policies/ap_invoice.py` docstring** corrected (factual, minimal): stale "migration from server.py:3333-3634" sentence replaced with a statement naming `services.ap_computation`, `services.document_intel_helpers`, and `services.vendor_resolution_service` as the authoritative compute-lane sources.
- **`_build_vendor_resolution` preserved** per signed narrowing — future step can migrate the fallback into the service or formalize it otherwise.
- **Parity probe**: new `tests/test_ap_wrapper_cleanup_parity.py` — 8/8 passed. Three classes: byte-identical output probe, source-inspection confirming deletions, guardrail asserting `_build_vendor_resolution` and its fallback are preserved.
- **`server.py`: 7,889 → 7,854 lines (−35 net)**. Phase 3 cumulative reduction: 8,903 → 7,854 = −1,049 lines (−11.8%) across Steps 1 + 2R.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). Path A auth-gated routes unaffected. Canonical service logic untouched.
- **Targeted regression**: 409 passed. Known unrelated baseline failures (`TestRouteCountStable::test_count` stale magic number; `test_reprocess_uses_direct_import` asserts on a file 2R did not touch) unchanged.



### 2026-04-23 — Phase 3 Step 1: Shadow-handler deletion from `server.py`
- **Deleted Block A** (4 Pydantic model shadows): `SetVendorRequest`, `UpdateFieldsRequest`, `BCValidationOverrideRequest`, `ApprovalActionRequest` — canonical copies remain in `services/workflow_handlers.py:34–58`.
- **Deleted Block B** (15 handler function shadows + 3 section headers + stale "Moved to" comment): `set_vendor_for_document`, `update_document_fields`, `override_bc_validation`, `start_approval`, `approve_document`, `reject_document`, `mark_ready_for_review`, `mark_reviewed`, `start_approval_generic`, `approve_generic`, `reject_generic`, `complete_triage`, `link_credit_to_invoice`, `tag_quality_doc`, `export_document` — canonical copies remain in `services/workflow_handlers.py`.
- **Single file touched**: `server.py`. Zero edits to `services/workflow_handlers.py`, routers, frontend, or DB schema.
- **`server.py`: 8,903 → 7,889 lines (−1,014, −11.4%)**.
- **Runtime behavior**: zero change. OpenAPI path count = 858 (unchanged); Path A `/api/ap-review/documents/{doc_id}/*` all functional; generic workflow mutation routes (`/api/workflows/{doc_id}/*`) all functional; Path B (`/api/workflows/ap_invoice/{doc_id}/*`) still 404 from Phase 4 removal.
- **Regression**: Lane C + workflow-extraction aggregate **379/379 passed**. Only remaining failure is the pre-existing stale `TestRouteCountStable::test_count` (expects 427, actual 901 — same as Phase 4 baseline, not introduced by this work).
- **Phase 3 sequence established**: Step 1 (shadow deletion, ✅ done) → Step 2 (AP compute-function extraction into `policies/ap_invoice.py`, next signed step).



### 2026-04-23 — Phase 4 Path B Removal (Lane A completion)
- **Production gate met**: prod VM returned `gate_met: true`, `total_hits_in_window: 0` across all six AP mutation Path B templates, empty `offending_callers[]`, zero hits in the full 14-day lookback.
- **Removed**: six deprecated `/api/workflows/ap_invoice/{doc_id}/{action}` routes (set-vendor, update-fields, override-bc-validation, start-approval, approve, reject) from `routers/workflows.py`. Path A under `/api/ap-review/documents/{doc_id}/{action}` becomes the sole authority.
- **Removed orphan functions**: `_record_deprecation_hit`, `_deprecate` (the wrapper factory) in `routers/workflows.py`, plus the `from functools import wraps` import and the 6 unused handler imports from `services.workflow_handlers`.
- **Deleted tests**: 6 Path B negative tests in `tests/test_workflow_handler_extraction.py::TestAPInvoiceRouteAvailability`.
- **Repointed error text** (correctness fix, signed in declaration):
  - `server.py` lines 6612 / 6670 / 6728 — `"use /api/workflows/ap_invoice/{doc_id}/..."` → `"use /api/ap-review/documents/{doc_id}/..."` (×3)
  - `services/workflow_handlers.py` lines 690 / 749 / 808 — same (×3)
- **Explicitly NOT touched** (per signed scope fence):
  - `routers/admin.py` `phase_4_gate` projection + `AP_MUTATION_TEMPLATES` list — stays in place, will report `gate_met=true, hits=0` forever (harmless).
  - `frontend/src/lib/api.js` comment.
  - Path A handler logic in `services/workflow_handlers.py` (beyond 3 error-text strings).
- **Verification**:
  - `/openapi.json` path count: **864 → 858** (exactly -6).
  - `POST /api/workflows/ap_invoice/bogus/approve` → **HTTP 404** (route gone).
  - `POST /api/workflows/ap_invoice/bogus/set-vendor` → **HTTP 404** (route gone).
  - `POST /api/ap-review/documents/bogus/approve` → **HTTP 401** (route auth-gated, still works).
  - Full Lane C regression: **379/379 passed** (only remaining failure `TestRouteCountStable::test_count` is a pre-existing stale-magic-number baseline test, unchanged by this work).
  - Ruff clean on all touched files.
  - Backend + frontend supervisor RUNNING.
- **Lane A (AP Path Consolidation) is now complete**: canonical AP mutation surface lives exclusively at Path A.



### 2026-04-23 — Lane C Step 8: Planning / Import (Coloplast, Option A foundation)
- **New top-level package** `workflows/planning/` — parser + validator + typed row model. No persistence. No routes. No scheduler. No wire-in. No LLM.
  - `__init__.py` (42 lines) — re-exports.
  - `module.py` (10 lines) — scope doc.
  - `types.py` (90 lines) — frozen dataclasses: `PlanningRow`, `PlanningRowError`, `PlanningSheet`, `PlanningParseResult`; `PlanningRowSeverity` literal.
  - `coloplast.py` (297 lines) — `parse_coloplast_sheet(sheet)` deterministic parser. Recognizes canonical column aliases (Item/SKU/Part No; UOM/UM/Unit; Description), weekly period headers (`W15`, `Week 15`, `2026-W15`) via ISO calendar, numeric/named monthly headers (`2026-04`, `04/2026`, `Apr 2026`, `April 2026`). Emits structured `PlanningRowError` on ambiguity — never invents intent. Skips blank rows and footer totals (`total`, `grand total`, `sum`, `totals`).
  - `validate.py` (135 lines) — `validate_planning_rows(rows, customer_no=None, today=None, horizon_weeks=26, backlog_weeks=1)`. Row-level policy: item_no non-empty, customer_no present & matching expected, qty finite & non-negative, period within ±26-week horizon. Warn-level for horizon violations; error-level for integrity violations. Pure — never mutates rows.
- **Tests**: `tests/test_planning_coloplast_parser.py` — **33/33 passed** (canonical shape, 12 column-alias parametrizations, structural errors, row skipping, determinism, separation-from-inventory-staging, separation-from-sales-workflow, unwired + LLM-free guardrails). `tests/test_planning_validator.py` — **16/16 passed** (happy path, required fields, qty discipline incl. NaN/inf, horizon bounds, error structure, row-non-mutation).
- **Separation proof**:
  - Static scan asserts `workflows/planning/` contains no references to `STAGING_COLL`, `inv_import_staging`, `inv_xls_learned_mappings`, or `workflows.inventory.planning.staging`.
  - Static scan asserts no references to `so_rules_engine`, `document_readiness_service`, `hub_documents`, `workflow_engine`, `business_central_service`, or `evaluate_and_persist`.
  - Static scan asserts no LLM references (`emergentintegrations`, `LlmChat`, `openai`, `anthropic`, `gemini`, `EMERGENT_LLM_KEY`).
- **Runtime**: zero. `/openapi.json` = 864 paths (unchanged). `workflows/inventory/planning/staging.py` (26,499 bytes) and `services/sales_intake_learning_service.py` (38,117 bytes) untouched.
- **Aggregate Lane C suite**: **361/361 passed** in 1.30s.
- **Deferred for later signed steps**: staging collection (`planning_import_staging`), router, SO-generation consumer (forecast → SO drafts / blanket-PO drawdowns), scheduler, BC writes, non-Coloplast customer formats.



### 2026-04-23 — Lane C Step 7b: Reselling COW — Evidence enrichment (Option 1)
- **Chose Option 1** after semantic re-declaration: Reselling COW is a **cross-cutting ownership refinement**, not a new sales archetype. No `reselling_cow/` package was created. Single COW truth surface (`cp_item_registry` + `classify_item_ownership` + `get_cp_item`) preserved.
- **Single file touched**: `workflows/inventory/ownership.py` — additive ~35 lines:
  - `_RESALE_SIGNAL_KEYS` tuple locks the three-field surface: `resale_authorization_id`, `resale_authorized_by`, `resale_authorization_date`.
  - `_extract_resale_context(doc)` reads those three signals exclusively from `doc.extracted_fields`; returns `None` when all absent/empty; trims string values.
  - `check_cow_so_uses_base_item` extended to attach `resale_context` **only** on `cow_so_wrong_customer` evidence rows and **only** when `_extract_resale_context` returns non-empty.
- **Enforcement unchanged**: `BLOCKER_CODE_SO_WRONG_CUSTOMER` still appends to `readiness.blocking_reasons`; no severity downgrade. Authorization presence is documentary only.
- **Scope strictly**: no new package, no new collection, no new HTTP route, no new ownership accessor, no frontend touches, no readiness-pipeline changes.
- **Tests**: `tests/test_cow_reselling_evidence.py` — **12/12 passed**.
  - Attachment: full-signal / partial-signal / empty-string rejection / whitespace-trimming.
  - Scoping: resale_context attaches ONLY to wrong-customer rows (not same-customer base-item code, not unknown_cp_pattern code, not when no signals present).
  - Enforcement invariants: block code still appended; authorization presence never downgrades the block.
  - Single-truth-surface: static source-inspection asserts `_extract_resale_context` reads only `extracted_fields` and never touches `cp_item_registry`/`classify_item_ownership`/`get_cp_item`; module carries no drift symbols (`classify_resale_ownership`, `get_resale_item`, `resale_item_registry`).
- **Regression**: Step-1 COW 28/28 unchanged, Step-2 consignment 27/27 unchanged, full Lane C aggregate **312/312 passed** in 1.22s. `/openapi.json` paths = 864 (unchanged).
- **Future step (unsigned)**: if the business later decides authorizations should downgrade the block to warn, that layer builds on this evidence foundation rather than requiring a rework.



### 2026-04-23 — Lane C Step 7 (narrowed): Customer Storage + Reroute
- **Scope split** — Reselling COW **deferred** out of Step 7 and will be re-declared separately; this step lands only Customer Storage and Reroute as signal-driven, unwired-foundation gate surfaces.
- **New package** `workflows/sales/subtypes/customer_storage/` — two gates, signal-driven (no classifier, no registry, no writes):
  - `customer_storage_without_storage_agreement` → **warn**
  - `customer_storage_ship_out_missing_release` → **block**
  - Signals read: `extracted_fields.is_customer_storage`, `extracted_fields.storage_agreement_id`, `extracted_fields.storage_release_id`, line-level `from_customer_storage=true` + `quantity>0` for ship-out detection.
- **New package** `workflows/sales/subtypes/reroute/` — two gates, `location_code=="001"`-driven (no classifier):
  - `reroute_location_without_original_so` → **warn** (mirrors freight-side `rerouted_missing_so` warning at sales-archetype layer)
  - `reroute_requires_drop_ship_linkage` → **warn** (non-duplicative with live SO-008 — orthogonal trigger axes: keyword-detection vs location_code)
  - Freight-side authority (`workflows/freight/item_charges.LOCATION_REROUTED`, `services/freight_gl_routing_service`, `services/bc_reference_cache_service.find_so_for_rerouted_po`) **untouched**.
- **Runtime behavior**: zero. Opt-in `register_*_gates` only; no auto-registration; `/openapi.json` paths = 864 (unchanged); `services/so_rules_engine.py` / `workflows/freight/item_charges.py` / `workflows/inventory/ownership.py` bytes on disk unchanged.
- **Tests**: `tests/test_customer_storage.py` 15/15 + `tests/test_reroute.py` 19/19 = 34/34 green. Prior-step regression (Steps 1–6 + EOD + shipment-method + taxonomy + Lane C registries) 266/266 green. Aggregate Lane-C suite: **300/300** passed in 1.18s.
- **Non-duplication proof for Reroute**: pytest `TestNonDuplicationWithLiveSo008` asserts the live `so_rules_engine._check_drop_ship_rules` uses keyword detection while the new reroute gates use location-code detection; both can flag the same doc without conflict.
- **Deferred**: Reselling COW (separate declaration), Step 9 warn→block upgrade, DS env-flag shadow mode.



### 2026-04-23 — Lane C Step 6: Drop Ship formalization (extraction seam)
- **New package** `workflows/sales/subtypes/drop_ship/` with three gate classes as authoritative-equivalent scaffolding for the Drop Ship archetype. Adapter-driven over the canonical gate framework. No classifier (defers to live `services.document_intel_helpers._classify_so_subtype`). Trigger axis is `doc.so_subtype == "DS_Sales_Order"`.
- **Severity ledger (parity with live `so_rules_engine._check_drop_ship_rules`):**
  - `drop_ship_po_missing` → **block** (SO-008 parity)
  - `drop_ship_po_cost_unverified` → **warn** (SO-009 parity)
  - `drop_ship_inventory_line_not_marked` → **warn** (ancillary parity)
- **Convergence mechanic**: extraction seam — chosen over move/wrap to keep live consumers (`server.py:2776`, `routers/inside_sales_pilot.py:785`) undisturbed. `services/so_rules_engine.py` bytes unchanged. No auto-registration; callers opt in via `register_drop_ship_gates(registry)`.
- **Runtime behavior**: zero change. No new routes (`/openapi.json` paths = 864, unchanged). No readiness pipeline, router, frontend, or DB schema touches.
- **Tests**: `tests/test_drop_ship_order.py` 24/24 green (SO-008/009/ancillary parity, opt-in registration, archetype-scoped, idempotent double-register, unwired guardrail asserting no external imports of the package and `so_rules_engine._check_drop_ship_rules` still owns live DS logic). Full prior-step regression 242/242 unchanged.


## Completed Features

### 2026-04-23 — Phase 3 Step 4c.2: thin-shim helpers substitution
- **Pre-sign empirical audit gate executed** (per user direction before signing). All 4 Tier-2 helpers classified **THIN_SHIM** with `resolves_to_svc: True`:
  - `classify_document_with_ai` (4-line body, local `_impl` alias of `services.document_intel_helpers.classify_document_with_ai`).
  - `make_automation_decision` (8-line body, local `_impl` alias of `services.document_intel_helpers.make_automation_decision`).
  - `classify_document_type` (10-line body, local `_impl` alias of `services.classification_helpers.classify_document_type`).
  - `create_sharing_link` (3-line body, local `_impl` alias of `services.sharepoint_service.create_sharing_link`).
  - None failed the gate → tier stayed intact, no further split needed.
- **Committed audit artifact**: `tests/audit_shim_substitution.py` — reusable classifier (IDENTITY / THIN_SHIM / DRIFTED verdicts via AST introspection + runtime `is` check). CLI contract (`python tests/audit_shim_substitution.py {tier}`) exits 0 iff every helper passes; exits 1 if any DRIFTED. Designed to be rerun pre-sign for future tiers (4c.3 and beyond).
- **Substitutions landed** inside `services/document_handlers.py::intake_document_from_bytes` lazy-import block:
  - `from services.document_intel_helpers import classify_document_with_ai, make_automation_decision`
  - `from services.classification_helpers import classify_document_type`
  - `from services.sharepoint_service import create_sharing_link`
  - Removed the 4 corresponding names from the `from server import (...)` block.
  - Short factual comment added: `# Phase 3 Step 4c.2: direct authoritative imports for thin-shim helpers`.
- **Zero other files touched.** `server.py` shims preserved unchanged (they have external callers beyond `_internal_intake_document` — per-shim signed step required to delete each).
- **Parity probe**: new `tests/test_helper_substitution_4c2_parity.py` — **26 passed, 2 skipped by design** (behavioral-call signature-mismatch skips for `make_automation_decision` and `classify_document_type` — not failures). 6 classes:
  - **Class A** Pre-sign audit re-run at test time: the committed classifier re-proves IDENTITY/THIN_SHIM with `resolves_to_svc=True` for each of the 4 Tier-2 helpers. If any fails, the whole suite fails.
  - **Class B** Behavioral call parity per helper: signature-introspected calls across both import paths; identical outputs or graceful skip on signature mismatch; exception-class parity for I/O-bound helpers.
  - **Class C** Source-inspection guardrail: each helper absent from `from server` block inside the function body; present in the correct `from services.<home>` import; both Step 4c.1 and Step 4c.2 comments present; `server.py` shims preserved.
  - **Class D** Moved-body byte-identity held: Step 4b baseline sha256 `ce7a32bd…` still matches.
  - **Class E** Live surface smoke: `/openapi.json` = 858; wrapper coroutine with correct signature.
  - **Class F** Audit-script self-proof: CLI invocation `python tests/audit_shim_substitution.py 2` exits 0 with "Failing (0):" in stdout. Environment passes `PYTHONPATH=backend/` to resolve `import server`.
- **`server.py`: 6,642 lines (unchanged)**. `services/document_handlers.py`: 2,345 → 2,346 lines (+1 net: 4 new imports + 1 comment minus 4 removed lazy-import entries ≈ +1).
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). The function objects bound inside the moved body are the canonical service-module functions, skipping the one-level `return [await] _impl(...)` tail call on each invocation.
- **Combined targeted regression**: **329 passed, 2 skipped (by design), 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — same pre-Step-3 baseline). Zero regressions introduced.


### 2026-04-23 — Phase 3 Step 4c.1: re-exported helpers substitution
- **Narrow tier-split per user direction**: user declined the one-pass all-8-helper plan and split Step 4c into 3 tiers. This is tier 1 — the 2 safest helpers (pure re-exports where `server.py` does not define the function; it only re-imports from the authoritative service module). Tiers 2 (4 thin-shim helpers) and 3 (2 COMPATIBILITY WRAPPER helpers) are separately signed future steps.
- **Substitutions landed**:
  - `compute_ap_normalized_fields`: `from server import …` → `from services.document_intel_helpers import compute_ap_normalized_fields`.
  - `compute_ap_validation`: `from server import …` → `from services.ap_computation import compute_ap_validation`.
- **Single change site**: lazy-import block inside `services/document_handlers.py::intake_document_from_bytes` (the Step-4b moved body). Two names removed from the `from server import (…)` block; two new authoritative-home imports added with a short factual comment `# Phase 3 Step 4c.1: direct authoritative imports for re-exported helpers`.
- **Zero other files touched**: `server.py` re-exports at lines 1659 (`compute_ap_validation`) and 1663 (`compute_ap_normalized_fields`) preserved unchanged for any other callers still using `from server import X` pattern.
- **Object-identity parity proof (STRONGEST possible)**: `from server import X is services.<home>.X` passes for both helpers. CPython guarantees behavioral equivalence at the memory-address level.
- **Parity probe**: new `tests/test_helper_substitution_4c1_parity.py` — **12/12 passed**. Five classes:
  - **Class A** Object identity: `srv_X is svc_X` for both helpers (the strongest proof).
  - **Class B** Pure-call parity: `compute_ap_normalized_fields` called with canonical AP-invoice payload across both paths produces identical output; `compute_ap_validation` called with canonical 6-positional-args + `possible_duplicate` kwarg across both paths produces identical output.
  - **Class C** Source-inspection guardrail: both helpers removed from `from server` block; authoritative-home imports present; Step 4c.1 comment present; `server.py` re-exports preserved.
  - **Class D** Moved body byte-identity held: Step 4b baseline sha256 `ce7a32bd…` still matches — Step 4c.1 did not drift the body.
  - **Class E** Live surface smoke: OpenAPI = 858 paths; wrapper signature unchanged.
- **Stale-test update**: `tests/test_intake_body_move_parity.py::test_every_baseline_name_is_resolvable` (from Step 4b) updated to consider names imported from ANY module at the function-body top, not just `from server`. Required because Step 4c.1 moved 2 names from `from server` into `from services.*`, and the Step 4b test's `_lazy_import_names` helper only inspected `from server` imports. Added a new `_all_function_body_import_names` helper and repointed the resolvability test at it.
- **`server.py`: 6,642 lines (unchanged)**. `services/document_handlers.py`: 2,344 → 2,345 lines (+1 net: 2 new imports + 1 comment line, offset by the 2 removed lazy-import entries).
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). The function objects bound inside the moved body are literally identical across the old and new import paths — proven by `is` check.
- **Rollback posture (per signed declaration)**: single-line-per-helper reversibility. Atomic single-commit merge. If either Class A test fails pre-merge, rollback is one-line diff per affected helper. Class A's `is` check gates pre-merge so effective rollback probability is ~0.
- **Targeted regression**: **303 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — same pre-Step-3 baseline). Zero regressions introduced.


### 2026-04-23 — Phase 3 Step 4b: `_internal_intake_document` body move
- **Sequence strictly followed**: (1) baseline captured via AST → `tests/fixtures/intake_body_move_baseline.json` (746 body lines, 34,231 chars, sha256 `ce7a32bd…`); (2) stability verified across 3 consecutive runs (byte-identical md5); (3) body moved whole; (4) parity suite added; (5) regression verified — zero delta.
- **Canonical destination**: the 760-line body moved verbatim from `server.py::_internal_intake_document` into the Step-4a seam `services/document_handlers.py::intake_document_from_bytes`. The Step-4a wrapper body was replaced with the moved implementation. Signature unchanged. The 6 external callers rewired in Step 4a **require zero further changes** — they already called the new seam.
- **server.py deletion**: `_internal_intake_document` deleted entirely. Zero remaining callers after Step 4a. One-line factual marker comment left at the deletion site (`# _internal_intake_document moved to services/document_handlers.py::intake_document_from_bytes (Phase 3 Step 4b, 2026-04-23)`).
- **Helper-cascade strategy — CONSERVATIVE lazy-import** (signed guardrail: no helper substitution in this pass):
  - Single `from server import (…)` block prepended to the moved body lazy-importing **33 names** covering:
    - 7 `server.py`-exclusive helpers: `_attempt_llm_vendor_ranking`, `_build_vendor_resolution`, `_derive_workflow_status`, `_emit_intake_events`, `_update_ap_workflow_status`, `_update_standard_workflow_status`, `_update_vendor_profile_incremental`.
    - 12 cross-cutting helpers: `check_duplicate_document`, `classify_document_type`, `classify_document_with_ai`, `compute_ap_normalized_fields`, `compute_ap_validation`, `create_sharing_link`, `emit_document_received`, `evaluate_auto_clear`, `get_auto_clear_update`, `get_auto_resolve_service`, `get_event_service`, `lookup_vendor_alias`, `make_automation_decision`, `upload_to_sharepoint_with_routing`, `get_pilot_capture_channel`, `get_pilot_metadata`.
    - `db` (Motor handle) — lazy-imported so the moved body uses the **same** DB handle as server.py (preserves multi-worker reference).
    - Module globals: `UPLOAD_DIR`, `PILOT_MODE_ENABLED`, `DEFAULT_JOB_TYPES`.
    - Enums: `DocType`, `SourceSystem`, `CaptureChannel`, `WorkflowStatus`, `WorkflowEvent`, `AutoClearDecision`.
  - Rationale: preserves byte-identical server.py dispatch for every helper. Some of these helpers have authoritative service-module homes (e.g., `classify_document_with_ai` in `services.document_intel_helpers`) that `document_handlers.py` already imports at module-top for the sibling `intake_document(UploadFile...)` handler. Substituting them here would be a **behavioral change**, not a body move — deferred to a future "Step 4c" with per-helper parity proof.
- **Parity probes**:
  - `tests/capture_intake_body_baseline.py` — AST-based pre-move baseline capture; stability-verified.
  - `tests/test_intake_body_move_parity.py` — **21/21 passed**. 4 classes:
    - **Class A — Body source byte-identity**: moved body (excluding lazy-import block and docstring) is SHA-256-identical to the pre-move baseline (`ce7a32bd53f5d77cb4b1c1f5c392c441f1e30fe3aa2a944e8d362d8b8b4c1308`). 746 lines, 34,231 chars.
    - **Class B — Baseline referenced-names resolvability**: all 164 pre-move body-referenced names resolvable post-move via lazy-import block, module-top of `document_handlers.py`, or Python builtins. Lazy-import block explicitly covers all 7 server.py-exclusive helpers + 10 required module globals.
    - **Class C — Live surface + caller-import smoke**: `/openapi.json` path count = **858**; all 6 Step-4a caller modules import cleanly (no NameError); wrapper resolves as coroutine with declared signature.
    - **Class D — Source-inspection guardrails**: `server.py` no longer defines the function; move-marker comment present; `server.py` shrank into the expected 6620–6660 band (actual: 6642); wrapper body ≥ 500 code lines (actual: well above); single contiguous lazy-import block at body top; no module-top backward import.
  - **Stale-test updates required** (stale = pre-4b source-text assertions that no longer match):
    - `tests/test_intake_caller_rewire_parity.py` — rewritten from 22 → 11 assertions. "Thin wrapper" assertions obsolete since the wrapper IS now the body; "all 6 callers use the seam" + "no backward import" + "OpenAPI stable" assertions retained.
    - `tests/test_ap_finalize_decision_parity.py::test_finalize_ap_decision_called_exactly_twice` — now checks the total of 2 call sites is split 1-in-server (reprocess branch) + 1-in-document_handlers (moved intake body).
    - `tests/test_ap_auto_post_service.py::test_server_skips_auto_clear_for_ap_invoice` — source-text assertion moved to `document_handlers.py` for the intake-branch skip logic; reprocess-branch skip remains in `server.py`.
- **`server.py`: 7,402 → 6,642 lines (−760 net, −10.3%)**. Phase 3 cumulative: **8,903 → 6,642 = −2,261 lines (−25.4%)** across Steps 1 + 2R + 2B + 3 + 4a + 4b. `services/document_handlers.py`: 1,572 → 2,344 lines (+772, the moved body).
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). All 6 ingestion paths dispatch to the same implementation, just via a new import path.
- **Rollback posture** (per signed declaration): atomic 2-file change (`server.py` + `services/document_handlers.py`). Pre-move baseline fixture committed before the body move so `git revert` is byte-stable. Single-commit rollback expectation held.
- **Targeted regression**: **291 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — identical pre-vs-post stash, unchanged from pre-Step-3 baseline). Zero regressions introduced.


### 2026-04-23 — Phase 3 Step 4a: `_internal_intake_document` caller rewire (seam-only)
- **Scope split upfront (Step 4 → 4a + 4b)**: audit found `_internal_intake_document` (760-line function at `server.py:2861–3621`) references 8 `server.py`-module-scope helpers (`_attempt_llm_vendor_ranking`, `_build_vendor_resolution`, `_derive_workflow_status`, `_emit_intake_events`, `_update_ap_workflow_status`, `_update_standard_workflow_status`, `_update_vendor_profile_incremental`, `make_automation_decision`) plus module globals. Moving the body alongside 6 caller rewires is a real blast-radius step. User signed the split — Step 4a rewires callers to a thin seam; Step 4b later does the body move.
- **Canonical destination**: new public thin-seam wrapper `services.document_handlers.intake_document_from_bytes(**kwargs)`. Byte-identical signature to `server._internal_intake_document`. Pure forwarder — lazy-imports the target and dispatches kwargs verbatim. NO preprocessing, NO normalization, NO logging, NO metrics, NO branching (signed guardrail).
- **Caller inventory — all 6 rewired**:
  1. `routers/sales_pipeline_demo.py:287–297` (demo ingestion, `source="demo_pipeline"`).
  2. `routers/pilot.py:918` (pilot mailbox, `source="email"`). Note: this caller previously had a **latent NameError** — no import statement existed for `_internal_intake_document`; the rewire adds an explicit `from services.document_handlers import …` so the call path is now correctly bound.
  3. `services/email_polling_service.py:501–502` (AP email polling, `source="email_poll"`).
  4. `services/email_polling_service.py:867–868` (Sales email polling, `source="email"`).
  5. `services/inside_sales_pilot_service.py:387–389` (`source="inside_sales_pilot"`).
  6. `services/batch_po_splitter.py:162+232` (child ingestion, propagates parent `source`).
- **Explicitly untouched** (in-file self-reference, Step 4b scope): `server.py::intake_document` (HTTP route at line ~3670) still calls `_internal_intake_document` in-file.
- **Parity probe**: new `tests/test_intake_caller_rewire_parity.py` — **22/22 passed**. 5 classes:
  - **Class A — Wrapper identity**: parameter list + defaults byte-identical to `_internal_intake_document`; kwargs forward unchanged across explicit and default-using invocations.
  - **Class B — Per-caller source-code verification**: each of the 6 caller files imports the new seam, no longer contains `from server import _internal_intake_document`, and the `await intake_document_from_bytes(` call count matches per-file expectation.
  - **Class C — Per-ingest-mode kwarg preservation**: 6 parametrized modes (`demo_pipeline`, `pilot_email`, `ap_email_poll`, `sales_email_poll`, `inside_sales_pilot`, `batch_po_splitter_child`) — each caller's kwarg bundle arrives at the underlying function byte-identical.
  - **Class D — Live OpenAPI surface**: path count remains **858** on `localhost:8001`; `/api/documents/intake` still registered.
  - **Class E — Guardrails**: `_internal_intake_document` signature byte-stable; `server.py` does NOT import the wrapper (would create circular risk); wrapper source contains no forbidden content (no logger calls, no DB ops, no metrics, no source-branching); wrapper body ≤ 25 code lines.
- **`server.py`: 7,402 lines (unchanged — pure topology change)**. Phase 3 cumulative: still **8,903 → 7,402 = −1,501 lines (−16.9%)** through Steps 1 + 2R + 2B + 3 + 4a. The value of Step 4a is decoupling the 6 external callers from `from server import …` so Step 4b can move the body without coordinating caller updates.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). All 6 ingestion paths continue to dispatch to the identical function via the wrapper.
- **Targeted regression**: **278 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — identical pre-vs-post stash; same failure as after Step 3). Zero regressions introduced.


### 2026-04-23 — Phase 3 Step 3: AP auto-post branch extraction
- **Scope split upfront**: original user direction named "Step 3/4 — AP auto-post orchestration and intake-branch migration". Blast-radius audit showed meaningful asymmetry: intake branch is ~30 lines with 2 in-file call sites, while `_internal_intake_document` external-caller migration touches 6+ callers across 4 external modules. User signed the split — this declaration covered Step 3 only; Step 4 deferred to a separate declaration.
- **Canonical destination**: new helper `services.ap_auto_post_service.finalize_ap_decision` (co-located with `attempt_ap_auto_post` — single module owning the full AP auto-post lifecycle). Explicitly NOT `policies/ap_invoice.py` — that module is a `PolicyModule` evaluator pattern, not a home for effectful DB-writing orchestration.
- **Helper signature** (narrowly behavior-preserving per signed guardrail — no retry, no metrics, no shadow-mode, no policy semantics added):
  ```python
  async def finalize_ap_decision(
      doc_id, db, *, source,
      emit_reprocess_events=False,
      on_exception_fallback_status=None,
  ) -> {"status", "posted", "reason", "bc_record_no", "events_emitted"}
  ```
- **Server.py rewires** (2 call sites — total):
  1. `server.py::_internal_intake_document` lines 3346–3373 (~28 lines) → `finalize_ap_decision(doc_id, db, source="auto")`. Outer `try/except` preserved for intake-parity "swallow" semantics.
  2. `server.py::_reprocess_document_inner` lines 4698–4722 (~25 lines) → `finalize_ap_decision(doc_id, db, source="reprocess", emit_reprocess_events=True, on_exception_fallback_status="NeedsReview")`. Plus removed the previously-inlined 35-line reprocess-events-emission + derived-state-refresh block at lines 4732–4758 (now absorbed by helper when `emit_reprocess_events=True`).
- **Preserved inline by declared scope**: `bc_vendor_number` pre-update in reprocess branch (depends on `validation_results` not passed through helper), the "[REPROCESS] Auto-clear SKIPPED" log line (belongs to auto-clear skip semantics, not finalize semantics).
- **Parity probe**: new `tests/test_ap_finalize_decision_parity.py` — **20/20 passed**. 4 classes:
  - **Class A — Pure-result parity**: recreates the inline intake decision tree, asserts helper return values match across 5 canonical `attempt_ap_auto_post` response shapes + 2 exception paths (intake swallow / reprocess fallback-to-NeedsReview).
  - **Class B — DB-mutation golden-file parity**: in-memory `_DbDouble` captures the exact sequence of `update_one` / `insert_one` calls the helper makes across 6 scenarios (intake × {posted,ready,needs_review} + reprocess × {posted,ready,needs_review}); asserts against golden fixture `tests/fixtures/ap_finalize_golden.json` (scope-filtered to the 3 direct mutations the helper is responsible for — status flip + 2 workflow_events; derived-state side-effects filtered out as DerivedStateService's own contract).
  - **Class C — Source-inspection guardrail**: `server.py` has exactly 2 `finalize_ap_decision` call sites and 0 remaining `attempt_ap_auto_post(` calls; `services/ap_auto_post_service.py` defines exactly 1 `finalize_ap_decision`; helper signature exactly matches the declared contract.
  - **Class D — Live-surface smoke**: `/api/documents/intake` + `/api/documents/{id}/reprocess` routes still registered on live `localhost:8001` backend; OpenAPI path count remains **858** (unchanged).
- **`server.py`: 7,437 → 7,402 lines (−35 net, −0.5%)**. Phase 3 cumulative: **8,903 → 7,402 = −1,501 lines (−16.9%)** across Steps 1 + 2R + 2B + 3. `services/ap_auto_post_service.py`: 807 → 939 lines (+132, helper + docstrings).
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged — no route surface touched). Intake and reprocess pipelines continue to produce identical status flips, identical workflow_events emission, identical derived-state refresh.
- **Existing test update**: `tests/test_ap_auto_post_service.py::TestCodePathVerification::test_server_imports_ap_auto_post_service` updated to assert the new post-Step-3 import pattern (`finalize_ap_decision`) instead of the removed direct `attempt_ap_auto_post` import. The authoritative module is still exercised — the helper calls `attempt_ap_auto_post` internally.
- **Targeted regression**: **256 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — fails identically pre-stash and post-stash, unrelated auth/live-backend issue). Lane C aggregate 174/174 green.


### 2026-04-23 — Phase 3 Step 2B: AP queue/count shadow-def deletion
- **Audit correction before signing**: original user directive named Step 2B as "AP queue/count helpers **migration** into `policies/ap_invoice.py`". Reality was 10 already-undecorated, zero-caller dead shadow `async def`s in `server.py` — same shape as Step 1 shadows, not a migration candidate. Live canonical copies already run from `routers/workflows.py` (Domain 8). `policies/ap_invoice.py` is a `PolicyModule` class pattern, not a routes/queries container. User signed revised scope as **pure shadow deletion**.
- **Deletions from `server.py`** (10 shadow `async def`s + 2 bracketing `# Moved to routers/workflows.py (Domain 8)` comments + 1 orphaned `# ==================== GENERIC WORKFLOW QUEUE API ====================` header + 1 orphaned `# ==================== WORKFLOW METRICS ====================` header + trailing-blank runs):
  1. `get_ap_workflow_status_counts`
  2. `get_vendor_pending_queue`
  3. `get_bc_validation_pending_queue`
  4. `get_bc_validation_failed_queue`
  5. `get_data_correction_pending_queue`
  6. `get_ready_for_approval_queue`
  7. `get_workflow_queue`
  8. `get_status_counts_by_doc_type`
  9. `get_workflow_metrics_by_doc_type`
  10. `get_ap_workflow_metrics`
- **`policies/ap_invoice.py`** minimal factual docstring amendment: names `routers/workflows.py` as the live queue/count surface; left policy class contract untouched.
- **Out of scope per signed fence** (preserved): `routers/workflows.py` (live routes), `routers/pilot.py::get_ap_workflow_metrics` (separate live route under `/pilot` prefix), 3 unrelated `list_workflows`/`get_workflow`/`retry_workflow` shadows at `server.py:1197-1225` (their own removal needs a separate signed declaration), auto-post orchestration, intake branches, `_build_vendor_resolution`, frontend, DB schema.
- **Parity probe**: new `tests/test_ap_queue_shadow_deletion_parity.py` — **36/36 passed**. 3 classes: OpenAPI route-registration presence (all 10 live routes still registered + path-count floor sanity), source-inspection confirming 10 symbols absent from `server.py`, guardrails asserting live copies in `routers/workflows.py`, unrelated pilot route preserved, `APInvoicePolicy` class contract byte-stable.
- **`server.py`: 7,854 → 7,437 lines (−417 net, −5.3%)**. Phase 3 cumulative: **8,903 → 7,437 = −1,466 lines (−16.5%)** across Steps 1 + 2R + 2B.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged — shadows had no decorators). Live smoke: `GET /api/workflows/ap_invoice/status-counts`, `/vendor-pending`, `/generic/queue`, `/ap_invoice/metrics` all return HTTP 200.
- **Targeted regression**: zero delta — exact same 20 pre-existing failures before/after (`TestPathBDeprecationHeaders` stale after Phase 4 Path B removal, `TestAuthEndpoints` using rejected `admin/admin` creds, `TestRouteCountStable::test_count` stale magic number, `test_reprocess_uses_direct_import` pre-existing). Lane C aggregate **174/174 passed** unchanged.


### 2026-04-22 — Blocker-Code Rendering Tidy v2.5.34
- **New shared util** `frontend/src/lib/blockerLabels.js` — `BLOCKER_LABELS` map + `labelForBlocker(code)` function. Covers all 8 Lane C COW/consignment codes + 6 common pre-Lane-C codes. Unknown codes gracefully fall through to the existing snake→Title Case behavior — zero risk of "???".
- **6 call sites swapped** across 3 files: `DashboardPage.js` (failure-reasons chart label + top-blockers + top-warnings), `DocumentDetailPage.js` (plain blocking_reasons + warning_reasons lists below the ownership evidence panel), `AutomationMetricsCard.js` (blocking + warning lines).
- **Wording tweak per signoff:** `consigned_item_post_lifecycle_on_so` → "Consigned item on Sales after lifecycle closed".
- **Zero backend changes, zero new endpoints, zero data mutations.** Raw blocker codes remain unchanged in `readiness.blocking_reasons[]` / `top_blocking_reasons[]` payloads — display-layer only.
- **Verification** — 0 lint issues across 4 touched files; Lane B regression unchanged at 317P/35F/14E; COW+consignment 55/55 unchanged; OpenAPI path set byte-identical at 862; screenshot smoke confirmed all mapped codes render with human labels, unmapped code falls through correctly.
- **Deferred**: `BCResolutionWidget.js` line 178 renders BC resolution miss-reasons from a *different* taxonomy (`missReasons`, not readiness blockers) — not in scope; flagged for a future BC-telemetry pass.

### 2026-04-22 — Reviewer UI Polish: Ownership Evidence Panel v2.5.33
- **New component** `frontend/src/components/OwnershipEvidencePanel.jsx` — structured renderer for `readiness.cow_items[]`, `readiness.cow_so_items[]`, and `readiness.consigned_items[]`. Three guarded sections, each shown only when its array is non-empty. Zero visual impact on docs without ownership evidence.
- **Integration** — inserted into `pages/DocumentDetailPage.js` inside the existing Readiness card, after Warnings. Reads the payload that `GET /api/documents/{doc_id}` already returns — **zero backend changes, zero new fetches, zero new endpoints**.
- **Per-row actions** — "Update registry" deep-links to `/config?tab={cp-items|consigned-items}&filter_item=<item_no>`; "Correct line" scrolls+highlights the extracted-data card via anchor `#doc-line-items` (guarded, no-ops cleanly when the card doesn't render).
- **Deep-link behavior in admin tabs** — `CpItemRegistryPanel.jsx` and `ConsignedItemRegistryPanel.jsx` now read `filter_item` from `useSearchParams`, pre-fill a new `item_no` text filter input, set the status filter to `all` on deep-link, and highlight the matched row with a primary ring. **Does NOT auto-open the create modal per signed amendment** — navigation only.
- **Verification** — 0 lint issues across 4 touched frontend files; backend Lane B regression 317P/35F/14E unchanged; COW+consignment 55/55 unchanged; OpenAPI path set byte-identical (862); screenshot smoke confirmed panel renders, deep-link navigation works with prefilled filter + highlighted row.

### 2026-04-22 — Lane C Step 2: Vendor Consignment v2.5.32
- **`consigned_item_registry` collection** — separate from `cp_item_registry`. Schema: `item_no` (unique), `vendor_no`, `physical_location`, `state ∈ {consigned_in, consumed, returned}`, `linked_receipt_ids[]`, `linked_consumption_ids[]`, `linked_return_ids[]` (all append-only), audit fields. Vendor-only consignor per signed Q2.
- **State machine** — exactly two legal transitions: `consigned_in → consumed` and `consigned_in → returned`. Terminal states; no reopen path. Transition requires `CONSIGNMENT_STATE_ACTOR_EMAIL` (env, default `items@gamerpackaging.com`) + mandatory `evidence_id` appended to the relevant link array.
- **5 hard-block rules** (all append to `readiness.blocking_reasons`, evidence in new `readiness.consigned_items[]`):
  - `consigned_item_on_ap_invoice` — AP invoice / PO with a `consigned_in` item
  - `consigned_item_wrong_state_on_ap` — AP invoice on a `consumed`/`returned` item
  - `consigned_item_on_sales_doc` — **any** sales doc with a `consigned_in` item (R3 widened per signoff)
  - `consigned_item_post_lifecycle_on_so` — sales doc on a `consumed`/`returned` item (R4 upgraded from warn per signoff)
  - `consigned_item_wrong_location_on_adj` — adjustment journal with non-matching `physical_location`
- **Wire-in** — single `try` block in `services/document_readiness_service.py::evaluate_and_persist`, immediately after the two existing COW blocks. Symmetric structure with idempotent clear on explicit re-eval.
- **Admin HTTP surface** — new `routers/consigned_item_registry.py` with 4 JWT-gated operations across 3 paths (`GET /api/consigned-items`, `GET /api/consigned-items/{item_no}`, `POST /api/consigned-items`, `POST /api/consigned-items/{item_no}/transition`).
- **Admin UI** — new `Consigned Items` tab in `SettingsHubPage.js`, component `ConsignedItemRegistryPanel.jsx`. List + vendor/state filters + create modal + per-row Consume/Return buttons (visible only in `consigned_in`). Evidence doc ID required on every transition; terminal-state policy explained in footer.
- **Tests**: `tests/test_cow_step2_consignment.py` — **27/27 green** (K1–K22 + helpers). Combined Step 1 + Step 2 ownership suite: **55/55**.
- **Regression**: Lane B-adjacent suite unchanged at 317P / 35F / 14E (normalized diff empty). OpenAPI: exactly +3 paths (862 total), 0 removed.

### 2026-04-22 — Lane C Step 1 Follow-up: COW SO-side gate + admin UI v2.5.31
- **SO-side hard block** — new `check_cow_so_uses_base_item` in `workflows/inventory/ownership.py`; fires for `SALES_INVOICE`, `SALES_ORDER`, `SO_CONFIRMATION`, `DS_SALES_ORDER`, `WH_SALES_ORDER`. Wired into `services/document_readiness_service.py::evaluate_and_persist` alongside the Step 1 PO block. Same canonical path, same explicit-reeval semantics, no new schedulers.
- **Two distinct blocker codes (per amendment):**
  - `cow_so_uses_base_item` — active registered CP or unknown CP-pattern item billed on a sales doc; evidence carries `recommended_base_item_no` for the base-item correction.
  - `cow_so_wrong_customer` — CP registered to customer A but billed on a doc for customer B; evidence carries `registered_customer_no` + `doc_customer_no`.
- **SO-side evidence lives in `readiness.cow_so_items[]`** (additive field, distinct from PO-side `readiness.cow_items[]`). Retired CP items still allow sales docs (registry retirement = customer consent to re-use as regular SKU).
- **Admin UI** — new tab `CP Items` in `SettingsHubPage.js`, component `components/CpItemRegistryPanel.jsx`. List + customer_no filter + status filter + refresh + create/upsert modal + per-row retire button with actor-email prompt. All elements have `data-testid` attributes. No charts, no bulk tools, no CSV — intentionally restrained per Amendment 3.
- **Zero new HTTP endpoints** — the 4 Step 1 endpoints cover the UI entirely.
- **Tests**: `tests/test_cow_step1.py` grew to **28/28 green** (+11 SO-side scenarios S1–S9 plus 2 apply-helper tests). Full Lane B-adjacent regression stays at 317P/35F/14E — diff empty. OpenAPI stays at 859 paths.

### 2026-04-22 — Lane C Step 1: Customer-Owned Ware v2.5.30
- **CP-item registry** — new MongoDB collection `cp_item_registry` with unique `item_no` index + `{customer_no, status}` compound index. Signed §4b schema: item_no, customer_no, base_item_no, canonical_location, linked_invoice_ids[] (append-only), status (active|retired), audit fields. Never programmatically retired — only `items@gamerpackaging.com` (env-configurable via `COW_RETIREMENT_ACTOR_EMAIL`) can flip status.
- **Ownership module** (`workflows/inventory/ownership.py`) — single source of truth for item ownership classification (`classify_item_ownership` returns `gamer | customer_owned_active | customer_owned_retired | unknown_cp_pattern`), CRUD helpers, CP-pattern regex `.*-CP[A-Z0-9]+$`, and the hard-block check `check_cow_item_on_po(doc)`.
- **Hard-block enforcement** — wired into the canonical readiness path (`services/document_readiness_service.py::evaluate_and_persist`). Block logic: active-registered CP item on PO → block; unknown-CP-pattern on PO → block; retired CP on PO → allow; inventory adjustment journal into `canonical_location` with positive qty → allow (signed §4b carve-out); adjustment journal into any other location → block. Writes `"cow_item_on_po"` to `readiness.blocking_reasons`, detail to `readiness.explanations`, structured evidence to `readiness.cow_items[]` (additive field).
- **Admin HTTP surface** — `routers/cp_item_registry.py` (3 paths / 4 operations): `GET /api/cp-items`, `GET /api/cp-items/{item_no}`, `POST /api/cp-items` (upsert), `POST /api/cp-items/{item_no}/retire`. All JWT-gated; retire also guards on actor email.
- **Test matrix** — `tests/test_cow_step1.py` 17/17 green (T1–T14 per signed pre-change declaration + 3 supplementary). T13/T14 use explicit canonical re-evaluation (not any background propagation, per amendment).
- **What is NOT included** — no gate_framework coupling (deferred to Step 2.75), no SO-side `COW_SO_USES_BASE_ITEM` gate, no frontend admin UI, no BC read/write of registry, no background re-evaluator.
- **OpenAPI diff**: +3 paths, 0 removals (additive). Regression: 317P/35F/14E on Lane B-adjacent suite unchanged; +17 new passes from COW suite.

### 2026-04-22 — Lane B Structural Carve-out v2.5.29
- **New `backend/workflows/` tree** per signed §2.1: 7 real files moved (workflow_engine → workflows.core.engine; learning_core dir; line_reconciliation; vendor_profile_helpers → rules/vendor_profile; freight_business_rules → freight/item_charges; inventory_ledger_service → inventory/ledger/service; inventory_xls_staging_service → inventory/planning/staging). 32 inert scaffold modules + 3 READMEs.
- **Real-file rule honored**: `vendor_profile_helpers.py` used in place of signed `vendor_profile_service.py` (file not present on disk); `bc_preflight` omitted (no source file existed).
- **163 import rewrites** across 54 files. Removed dead re-export from `services/__init__.py` (no shim layer per Amendment 2).
- **Verification**: `/openapi.json` byte-identical (856 paths, sha256 match). pytest diff empty vs baseline (317P/35F/14E). Supervisor clean.

### 2026-04-22 — Hygiene patch (post-Lane-A)
- JWT auth added to `GET /api/ap-review/documents/{id}/bc-status` (was unauthenticated).
- Frontend `limit=0` callers fixed for endpoints with `ge=1` constraint: `UnifiedQueuePage.js` (readiness exception-queue + po-pending), `SalesInventoryHubPage.js` (triage-queue). `/documents?limit=0` left untouched (backend accepts it).

### 2026-04-22 — Lane A Integrity v2.5.28
- **A1 Historical posting-attempts array** — `hub_documents.bc_posting_attempts[]` append-only audit log replaces overwrite-on-failure `bc_posting_error`. Frontend accordion on the AP review panel (collapsed by default, auto-expands on failed/partial/pending_retry). Legacy migration on startup.
- **A2 Retry/backoff on BC 429/503** — `bc_http_with_retry()` wraps the header POST and per-line POST inside `create_purchase_invoice`. 3 retries, 1s/2s/4s + jitter, circuit-break on exhaustion. Non-retriable 4xx passes through immediately.
- **A4 Pre-claim `workflow_engine.advance_workflow`** — BC post lifecycle is now a first-class engine concern via new events `ON_BC_POSTING_STARTED/ON_BC_POSTED/ON_BC_PARTIAL_POSTED/ON_BC_POST_FAILED` and states `BC_POSTING_IN_PROGRESS/BC_POSTED/BC_POST_PARTIAL`. Engine refuses ON_BC_POSTING_STARTED from invalid states → 409 before BC is called. On claim race, engine state reverts.
- **A3 gated** — Phase 4 Path B route deletion PR ready; merges when `phase_4_gate.gate_met=true` for 7 consecutive UTC days.
- Regression: 153/156 (3 concurrency skips by design) across 11 suites.

- Expanded TERMINAL_STATUSES (Validated, ReadyForPost, etc.)
- 20-Rule Force Cleanup Engine (`POST /api/readiness/sync-status`)
- Auto-Post Revert Bug Fix (non-AP docs no longer revert)
- Exception Queue + Retry System (4x retry → escalate)
- Vendor Matching Gap Closer (variants, manual BC search, dismiss)
- PO Auto-Retry Queue (park, 4h retry, 3d escalation, UI tab)
- Inbox Metrics Panel — `GET /api/dashboard/inbox-metrics` (2026-04-09)
- Captured Doc Auto-Retry — Background scheduler + manual endpoint + UI button (2026-04-09)
- **Bugfix: is_duplicate filter** — Added to inbox-metrics and inbox-stats pending_review so numbers match inbox table (2026-04-09)
- **ReadyForPost Auto-Post Scheduler** — Background loop (5min interval, 5 retries) posts ReadyForPost docs to BC when BC_WRITE_ENABLED=true. Manual trigger: `POST /api/readiness/retry-ready-to-post`. UI "Post Ready" button added. (2026-04-10)
- **Transient BC error resilience** — Failed BC posts now keep docs at ReadyForPost (not NeedsReview) so the scheduler retries. Permanent errors (404/422) still revert to NeedsReview. (2026-04-10)
- **Draft Auto-Approve in scheduler** — `auto_approve_drafts` now runs automatically every 2h cycle alongside draft feedback sync + continuous learning. High-confidence vendors auto-approved. (2026-04-10)
- **Cross-document dedup guard** — Gate 2b in `check_auto_draft_eligibility` prevents duplicate PI creation when another doc for same vendor+invoice already has a PI. (2026-04-10)
- **Posted to BC stats widget** — Inbox stats strip now shows `posted_to_bc_7d` and `ready_for_post` counts in real-time. (2026-04-10)
- **Vendor maturity fix** — Fixed maturity level labels to match frontend (mastered/proficient/developing/learning/novice), lowered thresholds (75/60/40/20), field_coverage defaults to 50 when no extraction patterns exist. (2026-04-10)
- **Bulk Classify endpoint + UI** — `POST /api/documents/bulk-classify` assigns doc_type to multiple docs with AI learning feedback. Dropdown + button in Inbox selection bar. (2026-04-10)
- **Vendor learning backfill** — Background scheduler backfills amount/line data from approved drafts' BC records for vendors showing $0. (2026-04-10)
- **Auto gap closer** — Gap closer now runs automatically in intelligence maintenance scheduler (2h cycle), re-evaluating docs with blocking validation gaps. (2026-04-10)
- **Freight Business Rules Engine** — Codified controller's (Meghan) freight processing rules into `freight_business_rules.py`. Includes: order number pattern detection (W/WR=inbound, 6-digit=outbound), location code routing (00=dropship, 001=rerouted), international vendor detection (CARGOMO/USCUSTO), shipment method codes (PPDADD/PPD/Delivered), freight item code validation, $100 variance threshold, multi-order invoice detection, LTL carrier duplicate risk (XPO/R&L), invoice naming convention parser. (2026-04-10)
- **Enhanced Freight GL Routing** — Controller rules now feed into freight GL classification as high-weight signals. Results include `controller_rules` with review flags persisted to document. (2026-04-10)
- **Freight-Specific Readiness Checks** — High freight variance blocks readiness. Multi-order invoices and LTL duplicate risk generate warnings. (2026-04-10)
- **Enhanced Duplicate Detection** — LTL carriers flagged with duplicate risk warning. In-hub duplicate check now includes order reference. (2026-04-10)
- **Noise Learning Events Cleanup** — Readiness self-corrections no longer pollute `posting_learning_events`. Dashboard queries filter out noise. Startup cleanup removes existing bad data. (2026-04-10)

## Key API Endpoints
- `POST /api/readiness/fix-validation-gaps` — Targeted PO learning + vendor resolution + re-evaluation
- `POST /api/posting-patterns/system/run-full-cycle` — 8-step intelligence orchestration
- `POST /api/readiness/sync-status` — Force cleanup engine
- `POST /api/readiness/retry-failed` — Batch retry extraction-failed docs
- `POST /api/readiness/retry-captured` — Retry stuck captured docs (4 max → exception)
- `POST /api/readiness/retry-ready-to-post` — Post ReadyForPost docs to BC
- `POST /api/documents/bulk-classify` — Bulk assign document type with AI learning
- `POST /api/readiness/po-pending/park` / `POST /api/readiness/po-pending/retry`
- `GET /api/dashboard/inbox-stats` / `GET /api/dashboard/inbox-metrics`
- `GET /api/aliases/vendors/unmatched-gaps` / `GET /api/aliases/vendors/search`

## Bugfix: "Needs Review" Status-Readiness Mismatch (2026-04-10)
**Root cause**: Three bugs caused ~270 documents to be stuck in "Needs Review" despite readiness being "ready_auto_draft"/"ready_auto_link":
1. **Bug 1 (server.py:7770, 7983)**: Gap closer scheduler and PO retry scheduler passed full document dicts instead of `doc["id"]` strings to `evaluate_and_persist()`, causing ALL background re-evaluations to silently fail.
2. **Bug 2 (readiness.py)**: `sync_readiness_to_status` excluded `auto_cleared=True` docs. If a doc was previously cleared but had its status reverted (e.g., by AP auto-post failure), it became invisible to the sync.
3. **Bug 3 (server.py)**: `sync_readiness_to_status` only ran once at startup — no periodic scheduler to catch docs that fall through cracks.
**Fixes applied**:
- Fixed `evaluate_and_persist(doc_id)` calls in gap closer (line 7770) and PO retry (line 7983) — now correctly pass `doc["id"]`
- Added Rule 21 (reverted auto_cleared docs) and Rule 22 (readiness-status mismatch) to `sync_readiness_to_status`
- Added periodic sync scheduler (every 30 minutes) alongside the existing startup-only sync

## Bugfix: AI Learning Dashboard Issues (2026-04-10)
1. **Vendor Maturity showing `/100` with no score**: `get_deep_learning_summary()` returned raw DB documents with `composite_score` field, but frontend expected `score`. Fixed by mapping field in summary response.
2. **$0/blank learning events**: Added composite filter to exclude events with no amount AND no line_count AND no items_used. Extended startup cleanup to delete ghost events from DB.
3. **Stuck "Needs Review" docs (server.py)**: Fixed `evaluate_and_persist()` call bugs in gap closer (line 7770) and PO retry (line 7983) schedulers — were passing full dict instead of `doc["id"]`. Added Rule 21/22 to `sync_readiness_to_status` and periodic 30-min sync scheduler.

## UX Simplification: One Button to Rule Them All (2026-04-10)
**Problem**: Too many manual buttons (Run All Learning, Re-evaluate All, Auto-Approve, Force Cleanup, Retry Failed, Backfill All 7, Self-Correct, Score Vendors, Recalibrate, Backfill History) — user didn't know which to press or when.
**Fix**:
- Created unified `POST /api/posting-patterns/system/run-full-cycle` endpoint running 7 steps in correct order: cleanup → intelligence backfill → readiness re-eval → auto-approve → recalibrate → learning pulse → deep learning
- Monitor page: single "Run Full Cycle" button with step-by-step result display
- AI Learning page: all individual buttons hidden behind `<details>` "Advanced Operations" toggles
- Background schedulers handle everything automatically; button is only for "I want it NOW"

## Bugfix: "0 Posted to BC" Field Name Mismatch (2026-04-10)
Posting code wrote `bc_purchase_invoice.bc_record_no` and `bc_record_no`, but dashboard counted `bc_purchase_invoice_no` (never written). Fixed all 3 write paths + added startup backfill migration.

## Bugfix: Automation Health 49% → 67%+ (2026-04-10)
Vendor maturity level names (`mastered/proficient`) didn't match what monitor expected (`stable/autonomous`). Fixed mapping in MonitoringDashboard.js. Also softened validation gaps formula (threshold 50 instead of 20).

## Freight Gaps Closed — Meghan Alignment (2026-04-10)
Three gaps from Meghan's controller rules now implemented:

**Gap 1: PO Notes → SO for Rerouted (001) Orders**
- `extract_so_from_document_text()` scans extracted fields, notes, remarks, `_po_all_candidates` for 6-digit SO refs
- `find_so_for_rerouted_po()` in BC cache service provides fallback via base-number matching
- If no SO found → flags `rerouted_missing_so` for manual review

**Gap 2: Inbound Freight Cost Box Comparison**
- `lookup_po_freight_details()` queries BC PO lines for freight item codes (FREIGHT, DETENTION, DRAYAGE, CUSTOMS, TARIFF, WHSEFRT)
- `compare_freight_to_bc_reference()` compares invoice vs PO freight total with $100 threshold
- Persisted as `freight_comparison` in freight GL classification

**Gap 3: Additional Charges via SO**
- `lookup_so_freight_lines()` queries BC SO lines for freight codes
- When invoice exceeds PO freight, checks if SO freight covers the gap (approved additional charges)
- If SO covers → severity=low, reason explains additional charges approved
- Also validates PI freight codes match SO codes (Meghan: "The codes should match the Sales Order")

Files modified: `freight_business_rules.py`, `freight_gl_routing_service.py`, `bc_reference_cache_service.py`

## Validation Gap Auto-Fixer (2026-04-11)
**Problem**: 45 documents stuck with blocking validation gaps (23 PO validation, 18 vendor match) preventing auto-filing. Specifically:
- TUMALOC vendor sends non-standard PO formats (`001307`, `19326`, `SI-02-26-31777`) that consistently fail BC PO validation
- "SC Warehouses, LLC" and similar vendors have no alias mapping to their BC counterpart

**Fix — 3 New Gap Closers**:

**GAP CLOSER 8: PO Validation Learning**
- `learn_vendor_po_validation_rate()` in `gap_closer_service.py` analyzes per-vendor PO resolution history
- If >70% failure rate with >=3 docs, auto-sets `vendor_invoice_profiles.po_expected = false`
- Integrated into `evaluate_and_persist()` — when PO is unresolved, checks/learns vendor's PO pattern
- Once learned, `compute_signals()` sets `po_not_required_by_vendor = True`, skipping BC PO check

**GAP CLOSER 9: Vendor Auto-Resolution**
- `auto_resolve_unmatched_vendor()` in `gap_closer_service.py` uses 4 strategies:
  1. Exact normalized alias match
  2. Fuzzy match against `vendor_invoice_profiles` (name + variants + BC card)
  3. Word-level + abbreviation matching (e.g., "Warehouses" → "WAREHOU")
  4. Auto-creates vendor alias for future matching
- Integrated into `evaluate_and_persist()` — for docs with `vendor_unresolved` blocker

**Batch Orchestrator: `fix_all_validation_gaps()`**
- Step 1: PO Learning — finds vendors with chronic PO failures, auto-learns profiles
- Step 2: Vendor Resolution — fuzzy-matches all unresolved vendor docs
- Step 3: Re-evaluates all gap-blocked docs to clear them through the pipeline
- Exposed as `POST /api/readiness/fix-validation-gaps`
- Also integrated as Step 2.5 in Run Full Cycle

## Comprehensive Inbox Cleanup (2026-04-11)
**Problem**: 267 documents stuck in "Needs Review" across multiple categories:
- ~120+ TUMALOC AP Invoices with non-standard PO formats
- ~30+ CARGOMO Shipping/AP docs
- ~12 ROTONDO Shipping/Warehouse docs
- ~10 XPOLOGI Account Statement splits
- Various junk, statement, remittance, and unmatched vendor docs

**Fixes Applied**:

1. **Run Full Cycle upgraded to 9 steps** (was 7→8→9):
   - Step 8: Final Cleanup — runs force_cleanup AFTER readiness re-evaluation to sync all newly-ready docs

2. **Force Cleanup Rules 23-25** added to `readiness.py`:
   - Rule 23: PO-relaxed vendor — auto-clears docs from vendors whose `po_expected=false` was learned
   - Rule 24: Shipping supporting docs — catches packing lists, commercial invoices, entry summaries, BOLs misclassified as AP
   - Rule 25: Broadest catchall — NeedsReview docs with NO blocking reasons + vendor resolved → auto-clear

3. **Enhanced PO Learning** (`gap_closer_service.py`):
   - Now counts ALL docs for a vendor (not just those with po_resolution attempted)
   - Also detects docs where PO was never extracted (skipped/no_po_extracted)
   - More aggressive vendor discovery: searches both po_resolution failures AND readiness.warning_reasons=po_missing

Files modified: `gap_closer_service.py`, `readiness.py`, `posting_patterns.py`
Test reports: `test_reports/iteration_203.json` (25/25), `test_reports/iteration_204.json` (24/24)

## Decision Explainer Service (2026-04-12)
- `GET /api/documents/{document_id}/explain` — plain-English explanation of document workflow state
- Service: `services/decision_explainer_service.py` — uses LLM router abstraction with `gemini-2.0-flash` default
- Route: `routers/explain.py` — JWT-protected, read-only, returns ExplainerResult JSON
- Returns: explanation, blocking_reason, next_action, model_used, generated_at, error (if any)
- Graceful error handling: missing LLM key, parse failures, import errors all return HTTP 200 with error in payload

## LLM Provider Abstraction Layer (2026-04-12)
- `services/providers/base_provider.py` — `BaseLLMProvider` ABC with `complete()` method + `LLMProviderError`
- `services/providers/emergent_provider.py` — `EmergentProvider` wrapping existing `emergentintegrations` LlmChat
- `services/providers/ollama_provider.py` — `OllamaProvider` using httpx to call Ollama `/api/chat`
- `services/llm_router.py` — `get_provider(task)` routes to correct provider per env var
- Env vars: `LLM_CLASSIFICATION_PROVIDER`, `LLM_EXTRACTION_PROVIDER`, `LLM_EXPLANATION_PROVIDER` (all default: `emergent`), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`
- `decision_explainer_service.py` migrated to use `get_provider("explanation")` — existing behavior unchanged
- ai_classifier.py and invoice_extractor.py NOT yet migrated (future task)

## Side-by-Side Extraction Comparison Endpoint (2026-04-12)
- `POST /api/dev/compare-extraction` — runs invoice extraction against baseline (emergent/gemini-2.0-flash) and candidate provider in parallel
- Route: `routers/dev_tools.py` — JWT-protected, read-only, never writes to DB
- Uses vision-based extraction (FileContentWithMimeType) for Emergent providers, text fallback for Ollama
- Returns structured diff: fields_agreed, fields_disagreed, fields_missing_in_candidate/baseline, confidence_delta
- Diff compares: invoice_number, invoice_date, due_date, vendor_name, po_number, total_amount, tax_amount, currency

## Vendor Resolution Ranking Assist (2026-04-12)
- Service: `services/vendor_resolution_assist_service.py` — LLM-assisted vendor candidate ranking when fuzzy matching is uncertain
- `rank_vendor_candidates(vendor_raw, candidates, document_context)` → `VendorRankingResult`
- Uses `get_provider("classification")` slot for disambiguation
- Safety: rejects model selection not in candidate list, caps at 10 candidates, skips LLM for trivial single-candidate case
- Test endpoint: `POST /api/dev/test-vendor-ranking` in `routers/dev_tools.py`
- NOT wired into live ingestion pipeline yet

## LLM Vendor Ranking — Live Pipeline Integration (2026-04-12)
- Wired `rank_vendor_candidates()` into both ingestion paths in `server.py` (`_internal_intake_document` + `intake_document`)
- Feature flag: `ENABLE_LLM_VENDOR_RANKING=false` (default OFF — must be explicitly enabled)
- Threshold: `VENDOR_RANKING_CONFIDENCE_THRESHOLD=0.80` (env-configurable)
- Decision gate: skips LLM for high-confidence methods (alias, exact_name, bc_search); activates only for uncertain/no-match cases
- On success: updates vendor_canonical/vendor_match_method, appends `llm_vendor_ranking_applied` to workflow_events
- On failure/low-confidence: logs, preserves original resolution unchanged
- Full audit: `llm_vendor_ranking` dict always persisted on document when ranking attempted
- Also created `vendor_resolution_service.py` (renamed from `vendor_resolution_assist_service.py` per user note)

## Daily Random Trace System (2026-04-12)
- Background scheduler runs 15 random invoice traces every 24 hours (also runs 2 min after startup)
- Picks random vendors from `vendor_invoice_profiles` (604 vendors), fetches real invoices from BC Production
- Compares human-posted lines vs AI template lines, stores results in `daily_trace_results` collection
- Endpoints: `POST /api/posting-patterns/daily-trace/run` (manual trigger), `GET /api/posting-patterns/daily-trace/latest`, `GET /api/posting-patterns/daily-trace/results`
- Frontend: "Daily Trace Feed" card on Invoice Trace page with summary stats, clickable vendor rows, "Run Now" button
- Configurable: `DAILY_TRACE_COUNT=15` (env var)

## Daily Trace Trend Tracking (2026-04-12)
- `GET /api/posting-patterns/daily-trace/trend?days=30` — returns historical avg match rates + vendor leaderboard
- Frontend: SVG sparkline chart showing match rate trend over time, vendor performance leaderboard (collapsible)
- Trend auto-populates as daily runs accumulate; sparkline appears after 2+ data points

## Daily Trace — PROD PI Comparison (2026-04-12)
- Rewrote `_run_daily_traces` to fetch recent PIs from BC Production (last 3 months via `invoiceDate ge` filter)
- Scans up to 500 PROD PIs across all vendors, filters to those with vendor profiles, randomly samples 10-20
- Each trace compares PROD human-posted lines vs AI template simulation
- Results include `has_template` flag, `prod_invoices_scanned`, `cutoff_date`, `status` per invoice
- Frontend shows "PROD vs AI Template (last 3 months)" label and template indicator badge per row

## Template Value Injection Service (2026-04-12)
- Service: `services/template_value_injector.py` — merges template structure with live extracted values
- `inject_extracted_values(template_lines, extraction_result, vendor_id, document_context)` → `InjectionResult`
- Injection rules: amounts from extraction (multi-line preserves template ratios), descriptions via ref injection (LLM or extracted PO/BOL), GL/tax/UOM/line_type always from template
- Full audit_trail per line per field showing source ("extracted" or "template")
- Test endpoint: `POST /api/dev/test-template-injection` in dev_tools.py
- NOT wired into live draft creation yet

## Template Injection — Live Pipeline Integration (2026-04-12)
- Wired `inject_extracted_values()` into `_build_pi_lines_with_mapping` in `gpi_integration.py`
- Feature flag: `ENABLE_TEMPLATE_INJECTION=false` (default OFF)
- Threshold: `TEMPLATE_INJECTION_CONFIDENCE_THRESHOLD=0.70` (env-configurable, lower than vendor ranking)
- Injection runs after template line selection, before BC API call
- On success: replaces bc_lines with injected lines, stores full audit trail as `template_injection`, appends `template_injection_applied` to workflow_events
- On failure/low-confidence: logs, uses original lines, still stores audit trail
- Both auto-draft and manual PI creation paths covered (single injection point in `_build_pi_lines_with_mapping`)

## Sales Order Learning Foundation (2026-04-13)
- Service: `services/sales_order_learning_service.py` — reads BC sales orders, builds customer posting profiles
- Collection: `customer_posting_profiles` (one doc per customer_no) + `sales_posting_learning_events` + `sales_learning_jobs`
- Functions: `build_all_customer_posting_profiles()` (bulk BC backfill), `analyze_customer_ordering_patterns()` (per-customer), `learn_from_sales_order_posting()` (incremental), `detect_posted_sales_drafts()` (feedback loop)
- Wired into `run_all_learning_engines()` in continuous_learning_service.py
- Admin endpoints: `POST /api/admin/sales-learning/backfill-bc-orders`, `GET /api/admin/sales-learning/customer-profiles`, `POST /api/admin/sales-learning/detect-posted-drafts`
- Profile includes: common_items, common_uoms, po_number_pattern, typical_order_value, amount_range, typical_ship_to, days_to_ship_p50, line_count_distribution
- NOT wired into SO draft creation yet

## Sales Order Readiness Reviewer (2026-04-13)
- Service: `services/sales_order_readiness_reviewer.py` — LLM-assisted advisory layer for SO readiness
- Uses `get_provider("classification")` from LLM router — no hardcoded provider logic
- Returns structured JSON: readiness_status (ready/needs_review/suspicious/incomplete), confidence, summary, blocking_issues, warnings, unusual_patterns, profile_matches, recommended_next_step
- Evaluates: item familiarity, UOM consistency, order value range, PO format, ship-to, line count vs customer history
- Full observability: model_used, latency_ms, schema_valid, retry_count, customer_profile_id/version
- Integration: runs advisory-only in sales workflow (server.py line ~2279), stores result as `so_readiness_review` on document
- Test endpoint: `POST /api/dev/test-so-readiness` in dev_tools.py
- NEVER changes posting decisions — recommendation mode only

## Sales Order Readiness Evaluator (2026-04-13)
- Service: `services/sales_order_readiness_evaluator.py` — batch evaluation harness for readiness reviewer
- `run_batch_evaluation(db, limit)` — loads historical sales docs, runs reviewer, compares against known outcomes, stores results
- Collections: `so_readiness_evaluations` (run summaries), `so_readiness_eval_details` (per-doc results)
- Per-doc detail: doc_id, customer, readiness_status, confidence, profile/blocking/warning/pattern counts, model_used, latency_ms, schema_valid, known_outcomes
- Summary metrics: status distribution, avg confidence, avg latency, no-profile %, posted-cleanly %, top recurring warnings, top unusual patterns
- Admin endpoints: `POST /api/admin/sales-learning/evaluate-readiness` (sync or background), `GET /api/admin/sales-learning/readiness-evaluations`, `GET /api/admin/sales-learning/readiness-evaluations/{run_id}`
- Evaluation only — never changes workflow or posting decisions

## Sales Order Decision Explainer (2026-04-13)
- Service: `services/sales_order_decision_explainer.py` — plain-English explanation layer for SO readiness
- Endpoint: `GET /api/documents/{document_id}/sales-order-explainer` (JWT-protected, on existing explain router)
- Prefers explaining existing `so_readiness_review` data (`review_reused: true`) — no unnecessary LLM calls
- Falls back to deterministic signals from validation_results and document state when no review exists
- Output: headline, plain_english_summary, why_it_was_flagged, what_looks_normal, what_needs_attention, recommended_next_steps, reviewer_confidence, readiness_status
- Logging: doc_id, review_reused, latency_ms, readiness_status, confidence
- Explanation only — never alters posting decisions or routing

## Sales Order Reviewer Feedback (2026-04-13)
- Service: `services/sales_order_reviewer_feedback_service.py` — captures human feedback on advisory reviews
- Collection: `so_reviewer_feedback` (structured, queryable by customer/assessment/model/reviewer)
- Endpoints: `POST /api/documents/{id}/sales-order-review-feedback`, `GET /api/documents/{id}/sales-order-review-feedback`
- Payload: reviewer_assessment (5 values), final_human_decision, disagreed_fields, notes, auto-captured reviewer_user_id from JWT
- Snapshots linked_review (readiness_status, confidence, model, profile_id/version) at feedback time
- Also stores `so_review_feedback_latest` summary on document for quick display
- Frontend: `SOReviewFeedbackPanel` component added to DocumentDetailPage — expandable panel with explainer + feedback form (assessment buttons, decision override, disagreed fields, notes)
- Feedback capture only — never changes posting, routing, or validation

## Sales Order Feedback Analytics (2026-04-13)
- Service: `services/sales_order_feedback_analytics_service.py` — MongoDB aggregation pipelines for reviewer feedback analysis
- Admin endpoints:
  - `GET /api/admin/sales-learning/reviewer-feedback-summary` — rates, distributions, confidence by assessment, by model/customer/reviewer, top disagreed fields + combos
  - `GET /api/admin/sales-learning/reviewer-feedback-details` — paginated individual records
  - `GET /api/admin/sales-learning/reviewer-feedback-by-customer` — per-customer breakdown
- Full filter support: date_from/to, customer_no, reviewer, model, readiness_status, assessment, decision
- Analytics only — never changes workflow or decisions

## Unified SO Advisory Panel (2026-04-13)
- Consolidated backend endpoint: `GET /api/documents/{id}/sales-order-advisory` — single call returns explainer + review + customer profile + feedback
- Frontend: Rewrote `SOReviewFeedbackPanel` as unified panel — compact, collapsible, shows full advisory story:
  - Status badge + confidence in header (collapsed view: headline only)
  - Expanded: summary, 4-stat row (blocking/warnings/unusual/matches), detail sections with icons, customer profile context, next steps
  - Feedback section: shows existing feedback or inline form (assessment, decision, disagreed fields, notes)
  - Loading/empty/no-review/no-profile states all handled
- Reuses all existing services — no changes to underlying logic

## Sales Order Disagreement Diagnostics (2026-04-13)
- Service: `services/sales_order_disagreement_diagnostics_service.py` — root-cause classification of reviewer disagreements
- Classifies disagreements into 10 root-cause categories: no_customer_profile, profile_too_sparse, order_value_range_too_strict, ship_to_sensitivity_too_high, item_uom_sensitivity_too_high, upstream_extraction_weakness, confidence_overestimation, prompt_wording_issue, new_customer_low_history, other_unknown
- Outputs: root-cause distribution, per-customer/per-model hotspots, disagreement rate by advisory confidence band, disagreed_field-to-cause mapping, example documents per cause
- Admin endpoints: `GET /api/admin/sales-learning/disagreement-diagnostics` (full filters), `GET .../examples?root_cause=X`
- Diagnostics only — never changes workflow or advisory logic

## Sales Order Confidence Calibration (2026-04-13)
- Service: `services/sales_order_confidence_calibration_service.py` — heuristic calibration layer
- Penalties: no_profile (-20%), weak_profile (-10%), per_warning (-5%), per_unusual (-7%), per_blocker (-15%), new_customer (-15%), overconfidence_history (-12%)
- Preserves raw_confidence, adds calibrated_confidence + confidence_band + calibration_reasons + penalties_applied
- Integrated into `sales-order-advisory` consolidated endpoint (on-demand calibration)
- Admin endpoints: `POST /calibrate-confidence` (batch), `GET /calibration-comparison` (raw vs calibrated bands), `POST /calibrate-document/{id}` (single)
- Frontend: unified panel shows calibrated confidence with "cal" indicator, expanded view shows raw→calibrated with reasons
- Advisory/display only — never changes routing or posting decisions

## Low-History Profile Handling Improvements (2026-04-13)
- Reviewer: profile-state-aware prompts (none/weak/medium/strong) — reduces over-assertive anomaly language
  - No profile: caps confidence at 0.60, avoids speculative anomalies, uses "limited comparison basis" phrasing
  - Weak profile: caps confidence at 0.70, phrases deviations as "differs from limited sample"
  - Medium: flags deviations as "worth verifying"
  - Strong: full comparison (existing behavior)
- Added `profile_state` field to ReadinessReviewResult and advisory endpoint response
- Explainer: adjusted headlines ("Limited customer history — manual review recommended"), attention items, and next steps for low-history cases
- Frontend: "No History" / "Limited History" badge in advisory panel header for low-history documents
- All existing schemas backward-compatible (profile_state is additive)

## Ship-To Sensitivity Tuning (2026-04-13)
- New service: `services/ship_to_analysis_service.py` — normalization + context-aware comparison
- Match types: exact | normalized_match | known_alternate | plausible_new | unknown_new
- Severity levels: none | low | medium | high — determined by profile strength + other signal context
- Normalization handles: casing, whitespace, punctuation, abbreviations (st/ave/blvd/whse/dist/etc.)
- Integrated pre-LLM: analysis runs before prompt, injected as structured context with explicit instructions to LLM
- Results stored on review as `ship_to_analysis` (match_type, severity, context_notes, known_locations)
- Frontend advisory endpoint includes ship_to_analysis in response

## Item/UOM Sensitivity Tuning (2026-04-13)
- New service: `services/item_uom_analysis_service.py` — pre-LLM item and UOM normalization + comparison
- Item match types: exact | normalized | known_alternate | new_plausible | unknown
- UOM match: exact | alias_match | known_alternate | unknown — with 14 canonical UOM groups (ea/cs/pk/bx/pl/ct/lb/kg etc.)
- Severity: context-aware (profile strength × other signals × count of unknown lines)
- Normalization: casing, punctuation, spacing, UOM alias resolution (case=cs, each=ea, pallet=pl, etc.)
- Integrated pre-LLM with explicit instructions: "Do NOT flag items as unusual" when severity=none
- Results stored on review as `item_uom_analysis` and included in advisory endpoint

## Explanation Wording Refinement (2026-04-13)
- Rewrote `sales_order_decision_explainer.py` with evidence-calibrated tone system
- 6 tone categories: direct (blockers), confident (ready), cautious (low-history), concerned (strong anomaly), attentive (moderate deviation), neutral (default)
- Headline, summary, flagged items, attention items, and steps now consistent per tone — no mixed signals
- Uses structured pre-analysis (ship_to severity, item_uom severity, profile state, calibrated confidence) to determine wording strength
- Low-evidence patterns qualified with "minor:" prefix; no-profile cases get "limited comparison basis" language
- Added `explanation_tone` field to SOExplanation output for observability

## Post-Tuning Calibration & Impact Review (2026-04-13)
- Service: `services/sales_order_post_tuning_review_service.py` — comprehensive post-tuning impact analysis
- Outputs: agreement rates, disagreement root-cause distribution, raw vs calibrated confidence band agreement, profile-state outcomes, ship-to/item-UOM disagreement counts, explanation-tone distribution, tuning impact signals, calibration weight assessment
- Calibration assessment: checks monotonicity of agreement across confidence bands, recommends penalty adjustments if warranted
- Tuning impact signals: per-area assessment (ship_to, item_uom, no_profile, wording) with positive/needs_monitoring verdict
- Detail endpoint: individual records enriched with profile_state, ship_to_severity, item_uom_severity, calibrated_confidence
- Admin endpoints: `GET /post-tuning-review`, `GET /post-tuning-review/details` — full filter support
- Analysis only — never changes workflow, weights, or prompts

## Strong-Profile Behavior Tuning (2026-04-13)
- Ship-to: strong profile with 3+ known locations + normal signals → severity downgraded from medium to low ("likely normal expansion")
- Ship-to: strong profile where everything else matches → severity downgraded from medium to low ("all other signals match")
- Ship-to: only escalates to medium when combined with other atypical signals
- Item/UOM: considers profile item diversity (6+ items = diverse); unknown item with diverse profile + normal signals → low not medium
- Item/UOM: majority rules — if >75% of lines are clean, caps overall severity one level lower
- Item/UOM: unknown item with all-normal signals → low ("not previously seen — other signals match established pattern")
- Reviewer LLM prompt: strong-profile instruction explicitly states "mature customers naturally evolve" and "one new item/destination is routine expansion"
- All structured outputs backward-compatible

## Strong-Profile Validation Review (2026-04-13)
- Service: `services/sales_order_strong_profile_review_service.py` — pre vs post tuning comparison for strong-profile cases
- Compares: agreement rate, disagreement drivers, ship-to/item-UOM frequency, confidence behavior, status distribution
- Customer-level breakdown: per-customer agreement + disagreement drivers
- Examples: improved cases (agreement rose) + still-problematic cases (with severity context)
- Verdict engine: positive/marginally_positive/neutral/needs_investigation with specific recommendations
- Admin endpoints: `GET /strong-profile-review`, `GET /strong-profile-review/details` — full filter support
- Analysis only — never changes workflow, weights, or prompts

## Bug Fix: Auto-Split Unknown Children Silently Exported (2026-04-19 — P0)
- **Root cause**: `auto_clear_service.evaluate_auto_clear()` had `confidence_threshold=0.0` with no `require_minimum_extraction` for `Unknown` / `Other` / `DEFAULT` doc_types. Auto-split child PDFs (e.g., `..._p11.pdf`) that the AI re-classified as `Unknown` with 0.00 confidence and zero extracted fields trivially satisfied the one confidence check (0.0 ≥ 0.0) → "All 1 checks passed" → exported/completed, bypassing manual review.
- **Fixes**:
  1. `services/auto_clear_service.py` — early guard rejects `Unknown`/`Unknown_Document`/`Unknown_Sales`/`Other`/empty/`DEFAULT` doc_types when `confidence < 0.70` OR meaningful fields < 2. Returns `NEEDS_REVIEW` with `unclassified_guard_triggered=True`.
  2. `services/batch_po_splitter.py` — new `_inherit_parent_and_reevaluate` helper: when a split child returns Unknown/low-confidence, inherits parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical` onto the child, preserves original AI values under `*_from_split_ai` for audit, and forces `status=NeedsReview`.
  3. `routers/auto_clear.py` — repaired missing import block (`evaluate_auto_clear`, `get_auto_clear_config`, `update_threshold`, etc.) that had been causing 500 on `/api/auto-clear/evaluate/{id}`, `/config`, `/config/threshold`. Discovered by testing agent iter_224.
- **KPI Fix (same iteration)**: `routers/dashboard.py` — `posted_to_bc_7d` query was too strict (required literal `status == "Posted"` AND `posted_to_bc_at` timestamp). Now matches any of `bc_purchase_invoice_no`/`bc_record_no`/`bc_document_no`/`bc_record_id` present WITH any of `posted_to_bc_at`/`bc_posted_at`/`posted_at`/`updated_utc` within 7 days. `ready_for_post` query's self-contradictory filter (`status=="ReadyForPost"` AND `status $nin ["Posted","Completed","Archived"]`) simplified.
- **CI Gate**: `.github/workflows/phase-b-gate.yml` drafted — enforces Phase B observer + unknown-guard tests and blocks new external callers of `_update_standard_workflow_status` ahead of Phase B extraction.
- **Tests**: `tests/test_auto_clear_unknown_guard.py` (8/8 pass), `tests/test_iter224_unknown_guard_http.py` (10/10 HTTP regression, added by testing agent), full suite 50/50 green (iteration_224.json).

## Pattern Health Implicit-Trust + Confidence Calibration Tightening (2026-04-19 — v2.5.3)
- **Observed on prod dashboard**: `Pattern Health — AP` showed `Trusted=3 / Drifting=216` despite 97.5% auto-rate + zero recent negative feedback for the majority of those 216 vendors. Also: `Confidence Calibration` 85–95% band at 91% accuracy vs 70–85% at 98% and 95–100% at 99% — the AI was over-confident specifically in the 85–95% window.
- **Fix A — Implicit Trust (`services/learning_core/pattern_health_service.py`)**: `_ap_health()` now uses implicit-success signals. New `_fetch_ap_negative_events_by_vendor()` aggregates `learning_events_v2` (domain=ap_posting, types in `{draft_bc_feedback, draft_rejected, pattern_rejected, suggestion_rejected, correction_applied, drift_flagged}`) once per call. Classification order: retired → explicit_high_tier → drift_signal → implicit_success (`samples >= AP_IMPLICIT_TRUST_MIN_SAMPLES=10` AND zero negative events in last 30 days) → medium_tier_still_maturing → unscored. Every `per_scope` row now carries `trust_reason` + `negative_events_30d` for transparency.
- **Fix B — Calibration Curve (`services/per_document_learning_service.py`)**: `compute_effective_confidence()` curve tightened. Old curve: scale=1.0 at completeness>=0.50 (no penalty). New piecewise curve: full pass at >=0.75, mild penalty (scale~0.88) at 0.50, moderate (scale~0.67) at 0.25, heavy (scale~0.35) at 0.00. A 90%-confident doc with only 2 of 4 core fields now calibrates to ~79% and shifts from the 85–95% band into the 70–85% band where manual review catches it. Monotonicity preserved (test_curve_is_monotonic).
- **Tests**: `tests/test_pattern_health_implicit_trust.py` (8/8) + `tests/test_confidence_calibration_curve.py` (10/10) + `tests/test_pattern_health_core.py` updated to assert new semantics. Full 32/32 unit tests + 6/6 HTTP endpoints green (iteration_225.json).

## Drift Watchlist Weekly Notification (2026-04-19 — v2.5.4)
- **Purpose**: Turn the passive Pattern Health dashboard into an actionable weekly alert. Aggregates vendors with corrective events in the last 30 days (`learning_events_v2` negative event types) OR open rows in `learning_drift_alerts`, ranks by score (`2 × open_alerts + negative_events_30d`), and dispatches.
- **Service** (`services/learning_core/drift_watchlist_service.py`): `build_watchlist` (one aggregation + one find + one enrichment query — no N+1), `format_teams_card` (Adaptive Card with 15-vendor cap + "+N more" footer), `format_email_html` (HTML table with clickable vendor deep-links via `APP_PUBLIC_URL`), `send_watchlist` (per-channel dispatcher with failure isolation — one failing channel never kills siblings).
- **Channels** (via `DRIFT_WATCHLIST_CHANNELS` comma-separated env — any combination):
  - `teams_webhook` → `TEAMS_DRIFT_WEBHOOK_URL`
  - `graph_channel` → MS Graph `/teams/{id}/channels/{id}/messages` using existing `GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` (requires `ChannelMessage.Send`)
  - `email` → MS Graph `/users/{from}/sendMail`
- **Scheduler** (`server.py`): fires weekly, gated by `DRIFT_WATCHLIST_ENABLED=true`, `DRIFT_WATCHLIST_CRON_DOW` (0=Mon), `DRIFT_WATCHLIST_CRON_HOUR` (default 7). Hourly-poll design that sends at most once per target day.
- **Router endpoints** (`routers/learning_core.py`):
  - `GET /api/learning/drift-watchlist/preview` — dry-run, returns `{watchlist, teams_card, email_html}` without sending
  - `POST /api/learning/drift-watchlist/send-now?channels=` — manual dispatch with optional channel override
  - `GET /api/learning/drift-watchlist/runs` — audit history of past dispatches (persisted in `drift_watchlist_runs`)
- **Safety**: empty-watchlist short-circuit (no noise), per-run audit even on skip, `{_id: 0}` projection everywhere.
- **Tests**: `tests/test_drift_watchlist.py` (16/16). Full iteration_226 report: 16 unit + 6 HTTP + 26 regression tests green.

## Unknown-Doc Reclaim Sweep (2026-04-19 — v2.5.5)
- **Purpose**: Counterpart to the v2.5.3 `unclassified_guard`. Sweeps docs that were auto-cleared to Completed/Exported BEFORE the guard existed and kicks them back to NeedsReview so humans can resolve them.
- **Service** (`services/admin/unknown_doc_reclaim_service.py`): `preview` + `run` + `recent_runs`. Filter requires ALL three type fields (`doc_type`, `document_type`, `suggested_job_type`) to be in the unknown set (`$and` — fixed an initial `$or` bug where missing-field defaulted to None/Unknown and caused false positives on real AP_Invoice docs).
- **Safety**: hard guard against any BC-write evidence (`bc_purchase_invoice_no`, `bc_record_no`, `bc_document_no`, `bc_record_id`). Idempotent via `reclaim_to_needs_review_at` timestamp. Dry-run default.
- **Audit**: preserves `auto_cleared=True` / `auto_cleared_at` history, appends workflow_history event, persists per-run summary to `unknown_doc_reclaim_runs`.
- **Endpoints** (`routers/admin.py`):
  - `GET /api/admin/unknown-doc-reclaim/preview?limit=` — counts + sample + breakdown (how many from batch-split, by doc_type)
  - `POST /api/admin/unknown-doc-reclaim/run?execute=false&limit=&actor=` — dry-run by default; `execute=true` required to mutate; optional `limit` for staged rollout
  - `GET /api/admin/unknown-doc-reclaim/runs?limit=` — audit history
- **Tests**: `tests/test_unknown_doc_reclaim.py` (9/9 via mongomock-motor). Full iteration_227: 48/48 green. Live preview DB verified end-to-end (1 real candidate found and reclaimed).
- **Deps**: added `mongomock-motor==0.0.36` to test stack.

## Unknown-Doc Reclaim — Smart + Skip-Noise Modes (2026-04-19 — v2.5.6)
- **Purpose**: Dramatically reduce the review-queue load before the user runs the full 372-doc sweep. Sampling showed 62% batch-split children (whose parents ARE classified) and 40%+ `OTHER` doc-type garbage, plus a cluster of email-sprite noise (`linkedin_*.png`, `cmn_*.png`, `image.png`).
- **New flags** (opt-in, both default False for backward compat):
  - `smart=true` — batch-split children whose parent is classified inherit parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical` before routing to NeedsReview. Original child `doc_type` preserved under `doc_type_from_reclaim_ai`. `parent_inheritance_applied=true` flag set. Reviewer sees enriched context instead of bare "Unknown".
  - `skip_noise=true` — filenames matching 15 regex patterns (email sprites, signatures, tracking pixels, `image*.png`, `logo.svg`) get marked `noise_filtered=true`, `queue_visible=false`, and KEPT OUT of NeedsReview entirely. `reclaim_to_needs_review_at` is still stamped for idempotency.
- **Precedence**: noise wins over smart (an email sprite with a classified parent is still noise).
- **Shape changes**: response now has `reclaimed_plain_count` / `reclaimed_inherited_count` / `filtered_noise_count` / `total_mutated`. Legacy `reclaimed_count = plain + inherited` (noise separate) for back-compat.
- **Preview extension**: `smart_inheritable` + `filtered_as_noise` counters in `sample_breakdown` (returns null when flag is off — distinguishes "feature disabled" from "zero").
- **Endpoints** (`routers/admin.py`) now accept `smart` + `skip_noise` query params on both `/preview` and `/run`.
- **Tests**: `tests/test_unknown_doc_reclaim_smart.py` (11) + `tests/test_unknown_doc_reclaim.py` (9) = 20/20 unit. Full iteration_228: 38/38 (20 unit + 18 HTTP). Verified NOISE_FILENAME_PATTERNS do NOT match real doc filenames (W117505.pdf, MARCH 2026 ACTIVITY.pdf, 0303382.pdf etc).

## Retroactive Post-Process Sweep (2026-04-19 — v2.5.7)
- **Purpose**: Fix the prod situation where operator ran v2.5.5 plain reclaim on 372 docs BEFORE v2.5.6 (smart + skip_noise) shipped. Those docs went to NeedsReview without parent-inheritance enrichment and with email-sprite noise still in the queue. This sweep retroactively applies the two modes.
- **Service** (`services/admin/unknown_doc_reclaim_service.py`): `_build_post_process_filter` + `post_process` + `recent_post_process_runs`. Filter scopes to docs with `reclaim_to_needs_review_at` set AND `post_process_applied_at` unset AND still queue-visible AND no BC evidence.
- **Three paths per doc** (evaluated in order):
  1. `skip_noise` + filename matches noise → revert OUT of NeedsReview (`status=Completed`, `queue_visible=false`, `noise_filtered=true`)
  2. `smart` + batch_parent_id + classified parent + no prior inheritance → inherit parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical`; stays in NeedsReview but enriched
  3. Otherwise → stamp-only (`post_process_applied_at` set; prevents re-picks)
- **Audit**: `unknown_doc_reclaim_post_process_runs` collection + `workflow_history` events (`post_process_noise_filtered`, `post_process_parent_inheritance`).
- **Endpoints** (`routers/admin.py`):
  - `POST /api/admin/unknown-doc-reclaim/post-process?execute=&smart=&skip_noise=&limit=&actor=`
  - `GET  /api/admin/unknown-doc-reclaim/post-process/runs`
- **Tests**: `tests/test_unknown_doc_reclaim_post_process.py` (11 tests). iteration_229: 43/43 (30 unit + 13 HTTP), zero bugs.

## Filename Heuristics Classifier (2026-04-19 — v2.5.8)
- **Purpose**: Pattern-based fallback classifier targeting the ~335 "stamp-only" docs left in NeedsReview after the v2.5.7 post-process sweep — docs the standalone page-level AI couldn't type but whose filename + vendor clearly signals the type.
- **Service** (`services/admin/filename_heuristics_service.py`): 12 rules derived from real prod samples (TUMALOC freight, CARGOMO invoices, Valley Distributing receiving reports, Brown monthly statements, Progressive Logistics rebills, Crown/Apex outbound, GROUPWA W-prefix, GAMMIN AR, Lone Star numeric, SMC Scan-WA, etc.). Every rule carries an `evidence note` so reviewers see *why* the AI reclassified each doc.
- **Safety**: 
  - Filter requires ALL three type fields in UNKNOWN_DOC_TYPES (never touches known-typed docs)
  - Never touches docs with BC evidence
  - Idempotent via `filename_heuristic_applied_at` sentinel
  - `keep_in_review=True` default — status stays at current (NeedsReview) pending human signoff; heuristic NEVER auto-clears
  - `doc_type_before_heuristic` audit field preserves the original (garbage) doc_type
  - `min_confidence=0.70` default gate (each rule has its own confidence, tunable per call)
- **Endpoints** (`routers/admin.py`):
  - `GET  /api/admin/filename-heuristics/rules`
  - `GET  /api/admin/filename-heuristics/preview`
  - `POST /api/admin/filename-heuristics/apply?execute=&smart=&min_confidence=&limit=&actor=`
  - `GET  /api/admin/filename-heuristics/runs`
- **Tests**: `tests/test_filename_heuristics.py` (34: 15 real-prod-filename matches + 8 false-positive checks + 11 behavioral). Iteration_230: 78/78 (64 unit + 14 HTTP), zero bugs. 15 real prod filenames from the user's iteration_227/229 sample all classified correctly.

## Triage Tools: Unmatched-Sample + Duplicate Scan/Resolve (2026-04-19 — v2.5.9)
- **Context**: v2.5.8 heuristics matched 56 of 417 candidates on prod (13%), leaving 361 unmatched. Also surfaced 12x duplicate ingestion of `GAMMIN_AR_20260316.xls` in a single day — proof of email-poller dedup miss.
- **Service** (`services/admin/triage_tools_service.py`): `filename_shape` (single-pass tokenizer using `#+` for digits + `A+` for letters — fixed an initial bug where `\\d+` replacement got letter-consumed by a second pass), `unmatched_sample`, `duplicate_scan`, `duplicate_resolve`, `recent_duplicate_runs`.
- **Endpoints** (`routers/admin.py`):
  - `GET /api/admin/filename-heuristics/unmatched-sample?limit=&top_n=&min_group_size=` — groups unmatched filenames by (vendor, shape). Includes defensive rescan — docs that `classify_filename` WOULD match are excluded from rule_candidates.
  - `GET /api/admin/duplicate-docs/scan?same_day=&limit=&min_count=` — groups docs by (file_name + vendor_canonical [+ YYYY-MM-DD]) where count ≥ 2. Skips `duplicate_resolved_at`-set docs (idempotent).
  - `POST /api/admin/duplicate-docs/resolve?execute=&keep=oldest|newest&same_day=&actor=` — keeps one per group (oldest or newest), marks rest `duplicate_of=<keeper>`, `status=Completed`, `queue_visible=false`, appends `duplicate_resolved` workflow_history event, persists audit row.
  - `GET /api/admin/duplicate-docs/runs`
- **Safety**: dry-run defaults, idempotent via `duplicate_resolved_at`, keeper never mutated, router guards invalid `keep` values.
- **Tests**: `tests/test_triage_tools.py` (18 tests incl. GAMMIN-12x scenario). Iteration_231: 101/101 (82 regression + 19 HTTP), zero bugs. filename_shape collisions verified symmetric (e.g., ROT12345_p1.pdf ≡ FED99887_p12.pdf).

## Upcoming Tasks
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future/Backlog
- P2: Evergreen multi-PO container allocation spreadsheet integration
- P2: BOL / Tracking No field storage in BC
- P2: Low-volume vendor review routing (<5 docs skip auto-file)
- P2: Activate correction replay engine
- P2: Email sender → vendor mapping
- P3: `server.py` extraction/refactoring (8,500+ lines)

## Inside Sales Pilot — Controlled Ingestion (2026-04-14)
- **Purpose**: Controlled ingest-only pilot for Inside Sales mailboxes — learn from real sales documents without creating operational risk
- **Pilot mailboxes**: `mkoch@gamerpackaging.com`, `nhannover@gamerpackaging.com`, `ASaumweber@gamerpackaging.com`
- **Feature flag**: `INSIDE_SALES_PILOT_ENABLED` (default: `false` — must be explicitly enabled in `.env`)
- **Service**: `services/inside_sales_pilot_service.py` — dedicated polling, relevance filtering, structured extraction, logging
- **Router**: `routers/inside_sales_pilot.py` — full endpoint suite:
  - Core: `GET /status`, `POST /poll-now`, `GET /documents`, `GET /runs`, `GET /logs`, `GET /extraction-review`
  - BC Validation: `POST /validate/{id}`, `POST /validate-all`, `GET /validation-results`
  - Corpus: `POST /validate-sales-corpus`, `GET /corpus-validation-summary`
  - Maintenance: `POST /re-extract-all`, `POST /smart-reclassify`
  - Spiro: `POST /spiro-match/{id}`, `POST /spiro-match-all`, `GET /spiro-results`, `GET /spiro-search`
- **Safety guards (6 layers)**:
  1. `source="inside_sales_pilot"` check in server.py SO auto-create path
  2. `inside_sales_pilot` flag check in `auto_post_service.check_sales_order_eligibility()`
  3. `inside_sales_pilot` flag check in `auto_post_service.check_auto_post_eligibility()`
  4. `auto_create_so_blocked=True` persisted on document
  5. `bc_write_blocked=True` persisted on document
  6. Sales workflow guard — pilot docs stop at `pilot_review` status, never progress to exported/posted
- **Relevance filtering**: keyword + filename matching, noise rejection (certificates, dunnage, signatures, info sheets)
- **Smart PO extraction**: validates AI-extracted POs, rejects garbage (rate, intment, number.), catches real patterns (W117579, WR112624)
- **Smart reclassifier**: auto-tags non-sales docs (certificates→Certificate, dunnage→BOL, reports→Report, etc.)
- **BC Production cross-validation**: read-only customer match, order lookup, item validation, amount range check
- **Sales corpus validation**: batch validation of existing 1000+ sales docs with side-by-side comparison
- **Spiro CRM integration**: company lookup, opportunity/quote matching, PO-to-quote matching
- **Frontend**: Inside Sales Pilot tab on Sales page + Build Roadmap page
- **Config vars**: `INSIDE_SALES_PILOT_ENABLED`, `INSIDE_SALES_PILOT_MAILBOXES`, `INSIDE_SALES_PILOT_INTERVAL_MINUTES`, `INSIDE_SALES_PILOT_LOOKBACK_MINUTES`, `INSIDE_SALES_PILOT_MAX_MESSAGES`
- **Spiro config**: `SPIRO_CLIENT_ID`, `SPIRO_CLIENT_SECRET`, `SPIRO_REFRESH_TOKEN`, `SPIRO_API_BASE`, `SPIRO_OAUTH_URL`
- **Version**: v2.1.0
- **NO BC writes, NO auto-create sales orders, NO downstream automation**

## Sales Order Draft Context Service (2026-04-13)
- Service: `services/sales_order_draft_context_service.py` — profile-based draft assistance
- Endpoint: `GET /api/documents/sales-orders/draft-context/{customer_id}` — JWT-protected
- Returns: ship_to_suggestions (primary + alternates), item_suggestions (core/regular/occasional with per-item UOM alternates), value_context (typical/min/max), common_uoms, po_pattern, guidance messages, profile richness/variability indicators
- No-profile: graceful degradation with "No customer history — draft will use extracted data only"
- Assistive only — never forces values or overrides user data

## Feedback-to-Learning Pipeline (2026-04-13)
- Service: `services/sales_order_feedback_learning_service.py` — converts reviewer feedback into candidate profile-learning suggestions
- Collection: `so_learning_suggestions` — one doc per suggestion with full audit (suggestion_id, type, customer, evidence, confidence, proposed_change, status, fingerprint)
- Suggestion types: add_alternate_ship_to, add_occasional_valid_item, add_alternate_uom_for_item, widen_order_value_tolerance, revise_po_pattern, increase_variability_tolerance
- Status lifecycle: pending → (approved / rejected / applied) — never auto-applied
- Deduplication via fingerprint (customer + type + change key)
- Confidence: evidence-weighted (0.3 base + 0.15 per supporting feedback, capped)
- Insufficient evidence: single-occurrence suggestions stored as "insufficient_evidence"
- Admin endpoints: `POST /generate-learning-suggestions?sync=true`, `GET /learning-suggestions`, `GET /learning-suggestions/{id}`
- Full filter support: customer, type, status, min_confidence, date range
- Suggestion generation only — never mutates profiles

## Learning Suggestion Approval/Apply Workflow (2026-04-13)
- Service: `services/sales_order_learning_suggestion_apply_service.py` — governed approval + apply workflow
- State machine: pending → approved → applied (terminal), pending → rejected, rejected → pending (un-reject)
- Mutation logic per type: add ship-to, add item, add UOM-for-item, widen amount range (±15-20%), relax PO pattern, increase variability (+0.15)
- Duplicate detection: no-op if value already present in profile
- Guard: cannot apply rejected/pending — must be approved first
- Full audit: `so_learning_apply_audit` collection with pre/post snapshots, applier, change summary
- Admin endpoints: `/approve`, `/reject`, `/apply` per suggestion_id
- Never auto-applies — explicit human approval required

## Learning Suggestions Admin UI (2026-04-13)
- Component: `components/LearningSuggestionsPanel.js` — admin governance UI for learning suggestions
- Placed at top of AI Learning Intelligence page (LearningDashboard.js)
- Features: filterable list (status + type), expandable detail rows, approve/reject/apply action buttons
- Detail view: evidence summary, supporting docs count, proposed change, profile snapshot, audit info
- Action guards: only shows valid actions per status (approve/reject for pending, apply/reject for approved, no actions for applied/rejected)
- Loading/empty/error states handled
- Uses existing admin endpoints — no new backend needed

## Learning Apply-Impact Review (2026-04-13)
- Service: `services/sales_order_learning_impact_review_service.py` — pre/post apply outcome comparison
- Compares: agreement rate, disagreement field frequency, root-cause changes per customer and suggestion type
- Outputs: improved/no_change/regressed counts, per-type and per-customer deltas, examples, actionable recommendations
- Recommendation engine: suggests lowering thresholds for high-impact types, flags regressions, notes insufficient data
- Admin endpoints: `GET /learning-impact-review`, `GET /learning-impact-review/details` — full filter support
- Analysis only — never changes thresholds or behavior

## Profile Drift & Change History Controls (2026-04-13)
- Service: `services/sales_order_profile_drift_service.py` — drift detection and change history
- Risk indicators: change cadence (>8/30d), ship-to growth (>8), occasional item growth (>15), variability (>0.90), richness jumps (>25pts)
- Risk classification: low/medium/high based on weighted signal count
- Outputs: per-customer risk assessment, risk distribution, change type breakdown, timeline, current profile metrics
- Admin endpoints: `GET /profile-drift`, `GET /profile-drift/{customer_id}`, `GET /profile-change-history/{customer_id}`
- Full filter support: date range, customer, drift_risk, suggestion_type, applied_by
- Governance/visibility only — never reverts or blocks changes

## Evidence Threshold Tuning (2026-04-13)
- Per-type configurable thresholds via env vars: `LEARN_THRESH_SHIP_TO=1`, `LEARN_THRESH_ITEM=1`
- Only low-risk types relaxable: add_alternate_ship_to, add_occasional_valid_item
- Higher-risk types unchanged: increase_variability, widen_amount, revise_po (default threshold=2-3)
- Drift-aware: high-drift customers automatically use default (conservative) thresholds even for relaxable types
- Suggestions record: threshold_used, relaxed_threshold (bool), drift_risk_at_generation
- All governance preserved: suggestions still require explicit approve + apply

## Rep Overrides Management UI (2026-04-13)
- Component: `components/RepOverridesPanel.js` — full admin CRUD for rep overrides
- Placed in Settings Hub as "Rep Overrides" tab
- Features: list/search/filter overrides, expandable detail, create/edit/disable, type badges
- Override types: rep_assignment, ship_to_exception, item_uom_exception, draft_preference, business_note
- Backend extended: added override_type, reason, notes, expires_at, updated_by fields + filter support
- Overrides remain separate from learned profiles — no silent merging
- Audit: created_utc, updated_utc, updated_by on every change

## Customer Hotspot Review (2026-04-13)
- Service: `services/sales_order_customer_hotspot_review_service.py` — cross-signal friction analysis
- Combines: feedback, disagreement fields, overrides, applied suggestions, audit count, profile richness/confidence
- Hotspot score: weighted (incorrect×3, ship_to×2, item_uom×2, overrides×2, drift audit, low richness bonus)
- Root causes: low_profile_richness, override_dependence, extraction_quality, threshold_tuning_needed, ship_to_friction, item_uom_friction, profile_drift_risk, high_volume_low_learning, monitor_only
- Fix paths: profile_improvement, override_management, extraction_improvement, threshold_tuning, monitor_only
- Detail endpoint: recent feedback + pending suggestions
- Admin endpoints: `GET /customer-hotspots`, `GET /customer-hotspots/{customer_id}` — full filter support
- Analysis only — never changes profiles, overrides, or thresholds

## Maturity Checkpoint & Reusability Review (2026-04-13)
- Service: `services/sales_order_maturity_checkpoint_service.py` — system-wide maturity assessment
- 7 dimensions scored: feedback_volume, agreement_quality, profile_coverage, learning_loop, governance_controls, drift_health, override_governance
- Maturity bands: mature (≥75) / operational (≥50) / developing (<50) → ready_to_reuse / mostly_ready / not_ready
- Component inventory: 13 generic framework components (72.2% reuse ratio), 5 domain-specific
- Next workflow recommendation: AP Invoice Vendor Advisory (fit=0.90, 12 reusable components, effort=low)
- Admin endpoints: `GET /maturity-checkpoint`, `GET /maturity-checkpoint/reusability`
- Assessment only — never triggers expansion

## AP Invoice Vendor Advisory — Phase 1 (2026-04-13)
- Framework reuse from Sales Order advisory pattern (72% component reuse)
- New AP-specific services:
  - `services/ap_invoice_advisory_reviewer.py` — vendor-profile-aware LLM advisory with profile-state prompts
  - `services/ap_invoice_decision_explainer.py` — evidence-calibrated tone system (direct/confident/cautious/concerned/neutral)
  - `services/ap_invoice_feedback_service.py` — feedback capture + basic analytics (reuses generic pattern)
- New router: `routers/ap_advisory.py` — 7 endpoints:
  - `POST /api/ap-advisory/review/{id}` — run advisory
  - `GET /api/ap-advisory/explain/{id}` — explainer
  - `GET /api/ap-advisory/advisory/{id}` — consolidated view
  - `POST /api/ap-advisory/feedback/{id}` — submit feedback
  - `GET /api/ap-advisory/feedback/{id}` — get feedback
  - `GET /api/ap-advisory/feedback-summary` — analytics
- Collections: `ap_reviewer_feedback` (feedback), `ap_advisory_review` (stored on doc)
- Phase 2 (not yet built): disagreement diagnostics, calibration, learning suggestions, approval/apply

## AP Invoice Vendor Advisory — Phase 2 (2026-04-13)
- Disagreement diagnostics: `ap_invoice_disagreement_diagnostics_service.py` — AP-specific root causes (vendor_match_ambiguity, extraction_ambiguity, po_reference_mismatch, amount_tolerance_sensitivity, duplicate_sensitivity, confidence_overestimation, explanation_wording)
- Confidence calibration: `ap_invoice_confidence_calibration_service.py` — penalty-based calibration preserving raw values (no_profile -20%, weak -10%, per_warning -5%, per_unusual -7%, per_blocker -15%)
- Learning suggestions: `ap_invoice_feedback_learning_service.py` — governed suggestion generation (add_vendor_alias, add_accepted_reference_pattern, widen_amount_tolerance, add_accepted_po_behavior, increase_vendor_variability)
- Collection: `ap_learning_suggestions` — same lifecycle as SO suggestions (pending → approved → applied)
- Endpoints on ap_advisory router: GET /diagnostics, POST /calibrate/{id}, POST /generate-suggestions, GET /suggestions

## AP Invoice Vendor Advisory — Phase 3 (2026-04-14)
- Suggestion approval workflow: `ap_invoice_learning_suggestion_apply_service.py` — governed approve/reject/apply lifecycle
  - State machine: pending → approved → applied (terminal), pending → rejected, rejected → pending (un-reject)
  - Mutation logic per type: add vendor alias, add accepted reference pattern, widen amount tolerance, relax PO requirement, increase vendor variability
  - Duplicate detection: no-op if value already present in profile
  - Full audit: `ap_learning_apply_audit` collection with pre/post snapshots
  - Endpoints: POST `/suggestions/{id}/approve`, `/reject`, `/apply`
- Learning impact review: `ap_invoice_learning_impact_review_service.py` — pre/post apply outcome comparison per vendor/type
  - Outputs: improved/no_change/regressed counts, per-type and per-vendor deltas, actionable recommendations
  - Endpoints: GET `/learning-impact-review`, GET `/learning-impact-review/details`
- Profile drift controls: `ap_invoice_profile_drift_service.py` — vendor profile evolution monitoring
  - Risk indicators: change cadence (>8/30d), alias growth (>10), variability (>0.90), amount range swing (>50%)
  - Endpoints: GET `/profile-drift`, GET `/profile-drift/{vendor_no}`, GET `/profile-change-history/{vendor_no}`
- Vendor hotspot review: `ap_invoice_vendor_hotspot_review_service.py` — cross-signal friction analysis
  - Root causes: low_profile_maturity, vendor_match_ambiguity, extraction_quality, amount_sensitivity, po_reference_friction, duplicate_sensitivity, profile_drift_risk, high_volume_low_learning
  - Endpoints: GET `/vendor-hotspots`, GET `/vendor-hotspots/{vendor_no}`
- All 14 new endpoints added to `routers/ap_advisory.py`
- Integration tests: `tests/test_ap_phase3.py` (12/12 passing)
- AP Invoice Advisory is now at feature parity with Sales Order governed learning pipeline

## Unified Governance Dashboard (2026-04-14)
- Backend: `routers/governance.py` — single consolidated endpoint aggregating SO + AP + system health
- Endpoint: `GET /api/governance/dashboard` — returns cross-pipeline metrics
- Sections: sales_orders (suggestions, feedback, drift_30d, hotspots), ap_invoices (same), system_health (7 metrics), combined_drift
- Frontend: `pages/GovernanceDashboard.js` — new standalone page at `/governance`
- System health strip: 7 stat cards (Total Docs, Pending, Completed, Posted 7D, Ready, Vendor Profiles, Auto Rate)
- Combined drift risk distribution: stacked bar chart (low/medium/high) — front and center
- Pipeline cards: SO + AP side-by-side with suggestion counts, agreement rates, drift mini-bars, expandable hotspot lists
- Actionable alert: shows when suggestions need attention
- Sidebar: "Governance" nav item with Shield icon
- Tested: 18/18 backend + 7/7 frontend tests passing (iteration_205.json)

## Bug Fix: Draft PI Preview Showing Identical Amounts (2026-04-14)
- **Root cause**: `posting_patterns.py` line 1348 — `preview_draft_pi()` assigned the FULL extracted total to EVERY template line instead of distributing it
- **Impact**: A $3,300 invoice with 3 template lines showed $3,300 × 3 = $9,900, or a $1,100 invoice showed $1,100 on all 3 lines
- **Fix**: Uses template `usage_rate` to distribute amounts proportionally. Falls back to even split when usage_rates are zero. Includes rounding correction to ensure line total matches document total exactly
- **Note**: The actual `create-draft` path (which posts to BC) was NOT affected — it uses the `template_value_injector.py` service which already handled ratios correctly. Only the preview modal was wrong

## Bug Fix: Readiness Completed with 0% Extraction (2026-04-13)
- **Root cause:** `evaluate_readiness()` would mark docs as `ready_auto_draft` when vendor was resolved via email sender BUT zero fields were extracted (e.g., .xls files the AI couldn't read)
- **Fix:** Added extraction quality gate — requires ≥2 meaningful extracted fields AND (invoice_number OR amount) before allowing auto-clear
- **Also tightened:** terminal short-circuit threshold from 1 to 2 meaningful fields, excluding boolean flags
- **Tested:** GAMMIN doc (0 fields) now correctly goes to `needs_review`; normal TUMALOC doc still auto-clears

## Status Model Cleanup (2026-04-13)
- **Bug 1 (Critical):** `derived_state_service.py` line 234 — when BC validation returned `all_passed=false` without `validation_status` field, the system defaulted to PASS instead of FAIL. Fixed: now correctly sets FAIL.
- **Bug 2:** AP validation "pass" event was overriding prior WARNING/FAIL states. Fixed: only upgrades validation_state if no prior failure/warning exists.
- **Bug 3:** `ReadyForPost` automation decision was silently overriding FAIL validation state. Fixed: only upgrades to PASS when validation hasn't already failed.
- **Bug 4 (Loop):** Reprocess loop — docs already decided as ReadyForPost were re-evaluated every full cycle (20+ times). Fixed: skip re-evaluation if `auto_post_attempted=true` and status already `ReadyForPost`.
- **Frontend:** Top badge now distinguishes "Ready to Post" (workflow=ready + validation=pass) from "Validated" (validation=pass), "Warnings", "Failed", and "Posted".
- Hierarchy enforced: Failed > Warnings > Validated > Ready to Post > Posted


## Bug Fix: Vendor Confirmations Falsely Triggering SO Rules (2026-04-15)
- **Root cause**: `pilot_smart_reclassifier.py` had no rules for order confirmations, order acknowledgments, or proforma invoices. Docs from vendors like Herdez, Aptar, O-I with filenames like "Order Confirmation", "OrderAck_W117579", "_ack.pdf" were classified as SALES_INVOICE and fed into the SO Rules Engine, triggering false SO-005 (missing cost) failures.
- **Fix 1 (Reclassifier)**: Added 6 new rules to Section 3 of `_RULES`: `order_confirmation`, `order_acknowledgment`, `vendor_confirmation`, `acknowledgment_file`, `ack_suffix`, `proforma_invoice`. All reclassify to `Vendor_Document`. Certificate negative lookahead prevents false positives. Already-reclassified docs are now skipped (checks `reclassified_from`).
- **Fix 2 (SO Rules Engine)**: `evaluate_all_pilot_sales_orders()` now excludes docs with `reclassified_from` in its query. `_check_cost_rules()` and `_check_customer_po()` expanded with additional vendor indicators (`_ack.`, `_ack_`, `acknowledg`, `proforma`) and `doc_type` check for `Vendor_Document`/`Purchase_Order`.
- **Tests**: 17/17 passing (`tests/test_p0_fixes.py`)

## Bug Fix: Incorrect Customer Extraction on Inbound Customer POs (2026-04-15)
- **Root cause**: `inside_sales_pilot_service.py` and `so_rules_engine.py` both used `vendor_canonical` as the primary customer source. When a customer (e.g., Giovanni) sends a PO to Gamer, the main pipeline sometimes resolves "Gamer" as `vendor_canonical` because Gamer appears in the Ship-To address on the PO.
- **Fix (Pilot Service)**: When `vendor_canonical` resolves to "Gamer", skip it and fall back to: extracted_fields customer/bill_to, then email sender domain-derived name (e.g., `orders@giovannis.com` → "Giovannis"). Gamer-related customer_no values (GAMER, GAMERPA, GAMER1) are cleared.
- **Fix (SO Rules Engine)**: Same Gamer-aware resolution in `_build_order_context()`. When `vendor_canonical` is Gamer, falls back to extracted fields and pilot extraction.

## Bug Fix: Total Amount Field Hit Rate at 0% (2026-04-15)
- **Root cause**: `inside_sales_pilot_service.py` checked `doc.get("total_amount")` first, but the main pipeline stores amount as `amount_float` at the top level (line 3229 of `server.py`). The field `total_amount` was never set by the main pipeline for most docs.
- **Fix**: Changed primary lookup to `doc.get("amount_float")` in both `inside_sales_pilot_service.py` and `so_rules_engine.py`. Extended fallback chain to also check `ef.get("amount")`, `ef.get("grand_total")`, `ef.get("invoice_total")`, `ef.get("net_amount")`.


## Spiro ↔ BC Name Reconciliation (2026-04-15)
- **Problem**: Companies like "Ortho Molecular Products" appeared in both "Spiro Only" and "BC Only" because no single document had both a Spiro match AND a BC match simultaneously. The cross-reference only linked companies when a single doc had both.
- **Fix**: Added `_reconcile_by_name()` to `spiro_bc_cross_ref_service.py`. After building spiro_only and bc_only lists, performs a normalized name comparison (stripping suffixes like Inc/LLC/Ltd/NA, normalizing punctuation/case). Moves matched pairs from both "only" lists into the "both" list.
- **Also fixed**: `bc_prod_validator.py` had same `doc.get("total_amount")` bug → fixed to `doc.get("amount_float")`. Added Gamer customer guard (clears Gamer-resolved customer_no, falls back to email sender domain).

## SO Rules Engine — Flowchart Alignment (2026-04-15)
- **Problem**: All 37 pilot sales docs evaluated as "Exception / Needs Review" with 32 Non-Compliant. The rules engine was treating early-stage docs (Draft/Open) the same as Released docs, pushing any missing field into a hard blocker.
- **Root cause**: Per the user's canonical Sales Order flowchart, Draft/Open docs are at the BEGINNING of the workflow — missing cost, confirmation, picks are expected. Those are action items for later stages, not blockers.
- **Fixes applied**:
  1. **SO-001 (Customer PO)**: Inbound customer PO documents (filename contains "PO", "Purchase Order", etc.) now have PO control marked as "inherently satisfied" — the document itself IS the PO.
  2. **SO-005 (Cost)**: Only blocks at Released+ stage. At Draft/Open, cost absence is informational ("will need cost entry before release").
  3. **SO-011 (Customer resolution)**: Only blocks at Released/Posted. At Draft/Open, it's an action item ("must resolve in BC before release").
  4. **Stage determination**: Draft/Open docs stay as "Draft / Open" with guidance. Only hard blockers (e.g., Gamer-is-customer, reclassification needed) push to Exception.
  5. **Compliance**: Draft/Open docs with PO + customer identified → "Conditionally Compliant" (can proceed to SO creation).
- **Expected impact**: Most pilot docs should now show "Draft / Open" + "Conditionally Compliant" with clear next-action guidance, instead of being dumped into exceptions.


## Pilot BC Prod Profile Comparison (2026-04-15)
- **Service**: `services/pilot_readiness_review_service.py` — bridges pilot docs with SO Readiness Reviewer + customer posting profiles
- **Endpoints**: `POST /api/inside-sales-pilot/readiness-review/{doc_id}`, `POST /readiness-review-all`, `GET /readiness-review-results`
- **Resolution chain**: customer_no from extraction → BC validation → Spiro external_id → vendor_canonical → fuzzy name → bc_reference_cache bridge
- **Validation gate**: Rejects false profile matches by verifying customer name overlap (first-word comparison)
- **Results**: 10/37 docs with accurate BC Prod profiles (Giovanni→GIOVANN, Herdez→HERDEZ, Ortho→ORTHO)
- **Intelligence**: "Order value within typical range", "New ship-to address detected", "Item matches customer history"
- Advisory only — never writes to BC

## Spiro Vendor Gate (2026-04-15)
- **Problem**: Docs from Spiro-designated Vendor companies (Owens, Phoenix, Ball Corp, Aptar, etc.) were entering the sales pipeline as customer POs. These companies are suppliers TO Gamer, not customers ordering FROM Gamer.
- **Fix**: Added Spiro `relationship_type` check to three services:
  1. **Reclassifier**: Vendor-company docs with SALES_INVOICE type → reclassified to Vendor_Document
  2. **SO Rules Engine**: Vendor docs → "Not a Sales Order" stage with routing guidance
  3. **Readiness Review**: Vendor docs → "not_applicable" with vendor context
- **Impact**: 3 vendor docs reclassified, pipeline reduced from 37 → 36 genuine sales docs
- **ISR context**: Jon Hawkes handles all vendor relationships (0 opportunities, 43% in BC) — vendor docs are supply-side communications

## Status Normalization Fix (2026-04-15)
- **Root cause**: `_normalize_status()` in `so_rules_engine.py` returned raw status strings for unrecognized values (e.g., "captured", "extracted"). These fell through all stage checks to the final "Exception / Needs Review" return.
- **Fix**: Added 10+ hub internal statuses to the mapping (captured, extracted, classified, ingested, processing, queued, new, pending → Draft/Open; exception, failed, error → Exception). Unrecognized statuses now default to "Draft / Open" instead of raw passthrough.
- **Impact**: All 37 docs moved from "Exception / Needs Review" to "Draft / Open"


## v2.5.10 — Email Dedup + Auto-Proposed Filename Rules (2026-04-19)
- **Fixed**: Email-poller ingesting same attachment 10–12×/day (GAMMIN_AR, W9.pdf). Root cause: static + dynamic pollers used incompatible dedup schemas in shared `mail_intake_log`, dynamic poller had 1h hardcoded lookback replayed every 60 s, and no DB-layer uniqueness. Fix: unified hash-first dedup across both pollers, per-mailbox watermarks, UNIQUE partial index on `(internet_message_id, attachment_hash)`, and `ensure_mail_intake_indexes()` at startup.
- **Added**: Auto-Proposed Filename Heuristic Rules — mines each vendor's own classified-doc history in `hub_documents` to derive new rules without manual input. Persisted in `filename_heuristic_custom_rules` collection and consulted by `classify_filename_async` (60 s cache). Built-in rules always win; custom rules serve as fallback. 5 new admin endpoints under `/api/admin/filename-heuristics/{auto-propose, auto-apply, custom-rules, custom-rules/{id}/toggle}`.
- **Tests**: 8 dedup + 13 auto-propose pytests + testing-agent iter_232 HTTP suite — 107/107 PASS.
- **Known follow-ups** (all P2 — see ROADMAP.md):
  - Frontend tooltip on Document Detail showing `filename_heuristic_rule` + `filename_heuristic_note`.
  - Surface the custom-rules list in an admin UI panel (currently API-only).
  - Phase B/C orchestration extraction from `server.py`.



### 2026-02 — Contract Intelligence Module: **Phase 1** (DB Models + DocuSign Scaffold)

**Status:** ✅ Phase 1 landed — awaiting user review checkpoint before Phase 2.
**Sign-off authority:** user signed-as-is on the 3-phase plan with these guardrails:
sequential phases (no bundling), DocuSign Connect push only (3a), BC matching scope
Customers + Vendors + Items but **read-only / advisory** (no BC writes), top-level
`/contracts` route. Carry-over items (LLM throttling, SMC/SC/CITICARGO Batch 2,
contaminated alias rows, Phase 4 Path B removal) explicitly out of scope.

**Files added (Phase 1, additive only — no existing files mutated except `.env`):**
- `backend/models/contracts.py` — 10 Pydantic v2 models + `CONTRACTS_COLLECTIONS`
  registry + `CONTRACTS_INDEXES` declaration. Models: `Agreement`,
  `AgreementParty`, `AgreementTerm`, `AgreementPricing`, `AgreementObligation`,
  `AgreementDocument`, `AgreementBCLink`, `AgreementEvent`, `AgreementException`,
  `AgreementMatchAudit`. All ids are UUID4 strings (no `_id`); all timestamps
  timezone-aware UTC; status/role/kind fields constrained via `Literal` unions;
  extras ignored on every model.
- `backend/services/integrations/__init__.py` — package marker.
- `backend/services/integrations/docusign_client.py` — env-driven scaffold.
  Surface: `DocuSignSettings.from_env()`, `DocuSignClient.is_configured()`,
  `is_webhook_ready()`, `status()`, `build_jwt_assertion()` (pure CPU),
  `oauth_consent_url(redirect_uri)`, `validate_webhook_signature(body, sig)`,
  `get_access_token()` (raises `DocuSignLiveCallsDisabled` in Phase 1).
  Module fn `validate_connect_hmac(body, sig, secrets)` for HMAC-SHA256
  with constant-time comparison and rotation support (multiple secrets).
  **No live network calls; `docusign-esign` SDK intentionally NOT installed
  in Phase 1.**
- `backend/services/contracts/__init__.py` — placeholder for Phase 2
  (`agreement_normalizer.py`, `bc_agreement_matcher.py` land here).
- `backend/scripts/contracts_init_indexes.py` — one-shot, idempotent index
  initializer for the 10 new collections. Run via
  `docker compose exec backend python -m backend.scripts.contracts_init_indexes`
  on the remote VM after pull.
- `backend/tests/test_contracts_models.py` — 25 tests covering required
  fields, enum constraints, confidence bounds, defaults, idempotency-key
  shape `(provider, provider_event_id)`, registry/index sanity.
- `backend/tests/test_docusign_client_scaffold.py` — 23 tests covering env
  parsing, configured/unconfigured status, JWT claim shape (`iss`/`sub`/`aud`/
  `iat`/`exp`/`scope`) verified with an ephemeral RSA keypair, TTL clamp at
  3600s, OAuth consent URL shape, HMAC happy-path/tampering/rotation/missing
  inputs, and the live-call guard (`get_access_token` raises even when the
  flag is on, until Phase 2 lands).

**Files mutated:**
- `backend/.env` — additive only: `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`,
  `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_BASE_URI`, `DOCUSIGN_PRIVATE_KEY_PATH`,
  `DOCUSIGN_OAUTH_HOST` (default `account-d.docusign.com`),
  `DOCUSIGN_HMAC_SECRET`, `DOCUSIGN_HMAC_SECRET_2`,
  `DOCUSIGN_LIVE_CALLS_ENABLED=false`. All blank by default — current behavior
  is byte-identical to pre-Phase-1.

**Tests:** 48/48 green (`tests/test_contracts_models.py` + `tests/test_docusign_client_scaffold.py`).
Backend `/api/health` still 200; no router mounted, no `server.py` touched, no
existing test regression. Lint clean (`ruff`) on all 7 new files.

**Out-of-scope confirmations (Phase 1 deliberately omits these):**
- No webhook receiver (`POST /api/docusign/webhook`) — that's Phase 2.
- No agreement normalizer or BC matcher — that's Phase 2.
- No `/contracts` UI / analytics endpoints — that's Phase 3.
- No `docusign-esign` SDK install — deferred to Phase 2 when live calls land.
- No mount in `server.py` — Phase 1 is dormant code.

**Next steps:**
- ⏸️ User review checkpoint (per signed sequencing rule).
- ▶️ Phase 2 (after sign-off): webhook receiver with HMAC validation +
  idempotency, agreement normalizer, BC matcher (read-only/advisory),
  manual mapping endpoints, accompanying tests.
- ▶️ Phase 3 (after Phase 2 sign-off): `/contracts` UI tabs, analytics
  endpoints, manual mapping UI.



### 2026-02 — Contract Intelligence Module: **Phase 2** (Webhooks + Normalizer + Matcher + Manual Mapping)

**Status:** ✅ Phase 2 landed locally, lint clean, 97/97 Phase-1+Phase-2 tests green,
backend boots cleanly with the new router mounted, no regression on unrelated tests.
Awaiting user review checkpoint before Phase 3 (UI + analytics).
**Sign-off authority:** user signed exact scope + guardrails (no BC writes, no
DocuSign writes, no live calls without explicit env flag, no unrelated refactors).

**Files added (Phase 2, additive only):**
- `backend/services/contracts/agreement_normalizer.py` — pure function
  `normalize_envelope(payload, event_id=None) → NormalizedAgreement`. Parses
  DocuSign Connect SIM payloads (or polled envelope dicts). Maps envelope
  status, signer/CC/sender recipients, custom fields → terms, `formData` tabs
  → terms + pricing (line-bucket convention `line_N_<attr>`), `envelopeDocuments`
  → documents. Defensive: missing fields become warnings, never raise.
- `backend/services/contracts/bc_agreement_matcher.py` — read-only/advisory
  matcher with injectable `BCLookupRepository` Protocol. Confidence-scored
  (auto-confirm ≥ 0.95, propose ≥ 0.80, exception below). Customers + Vendors
  + Items per signed scope. `InMemoryBCRepository` provided for tests.
- `backend/services/contracts/contract_intelligence_service.py` — orchestrator.
  `record_event()` performs idempotent insert into `agreement_events` (catches
  `DuplicateKeyError`, returns `duplicate=True`). `process_event()` runs
  normalize → upsert agreement+children → match → persist links/exceptions →
  emit audit rows → mark event processed. **Critical replay semantic:
  manually-confirmed/-rejected links survive replays untouched; only
  auto-generated `linked_by='system'` rows in {proposed, auto_confirmed} get
  refreshed.** Manual `manual_link()`, `confirm_link()`, `reject_link()`,
  `resolve_exception()` write paths each emit an `agreement_match_audit` row.
- `backend/routers/contracts.py` — FastAPI router. Endpoints:
  - `POST /api/docusign/webhook` (unauthenticated; HMAC-validated;
    503 if not configured, 401 invalid sig, 400 malformed JSON, 200 ack).
  - `GET /api/contracts/agreements` (auth, paginated, filters status / has_unmatched).
  - `GET /api/contracts/agreements/{id}` (auth; returns agreement + parties +
    terms + pricing + documents + links + exceptions).
  - `POST /api/contracts/agreements/{id}/links` (auth; manual confirmed link).
  - `POST /api/contracts/agreements/{id}/links/{link_id}/{confirm|reject}` (auth).
  - `GET /api/contracts/exceptions` (auth, filters status/code/agreement_id).
  - `POST /api/contracts/exceptions/{id}/resolve` (auth).
  - `GET /api/contracts/health` (no auth; diagnostic surface — secret-free).
- `backend/tests/test_contracts_normalizer.py` — fixture-driven, covers happy
  path + 8 edge cases (unknown status, missing envelope id, direct envelope
  summary, invalid email drop, voided status, empty recipients, pricing
  warnings, microsecond truncation).
- `backend/tests/test_contracts_matcher.py` — covers high-confidence
  auto-confirm, partial-match propose-vs-exception, no-candidates customer
  exception, dedupe of same-company multi-signer, witness-role skip,
  item match + miss + missing-label-warn, threshold contract.
- `backend/tests/test_contracts_orchestrator.py` — uses `mongomock-motor`
  with the production unique indexes pre-created. Covers: new event insert,
  duplicate event ack-without-double-write, full pipeline persistence
  (agreement + parties + terms + pricing + documents + links + audit),
  replay no-op idempotency, normalizer-failure event marking, manual link
  audit row, confirm/reject flow, exception resolution audit, **manual
  link survives replay** (the critical replay semantic test).
- `backend/tests/test_contracts_endpoints.py` — FastAPI `TestClient` against
  a tiny app that mounts only the contracts router with mongomock + auth
  override. Covers: webhook 503 when unconfigured, 401 missing/tampered
  signature, 400 malformed JSON, 200 + duplicate=False on first delivery,
  200 + duplicate=True on replay (and event row count == 1), GET health,
  GET agreements (empty + 404), full manual flow (create → reject + new
  proposed → confirm), resolve_exception (+ 404 on missing), auth gating
  on all read endpoints (401 without bearer).

**Files mutated (1, minimal as promised):**
- `backend/main.py` — single block added: 2-line import + `app.include_router(
  contracts_router, prefix="/api")`. No other line changed. Reported here
  per signed guardrail.

**Tests run locally:**
```
cd /app/backend && python -m pytest \
  tests/test_contracts_models.py \
  tests/test_docusign_client_scaffold.py \
  tests/test_contracts_normalizer.py \
  tests/test_contracts_matcher.py \
  tests/test_contracts_orchestrator.py \
  tests/test_contracts_endpoints.py -q
→ 97 passed
```
Backend `/api/health` still 200; `/api/contracts/health` returns the
diagnostic surface (currently `webhook_ready=false` until you populate
`DOCUSIGN_HMAC_SECRET`); webhook returns 503 when unconfigured (proven via
curl). Lint (`ruff`) clean on all 6 new files + the 1 mutated file.

**Assumptions made (calling them out explicitly for your review):**
1. **Pricing tab convention.** The normalizer expects pricing tabs named
   `line_N_<attr>` (where attr ∈ {item, qty, price, uom, total, description,
   ...}). If your DocuSign templates use a different naming scheme, no
   pricing rows will be emitted and a per-line `pricing_missing_item`
   warning will appear. **Tell me your real tab convention and I'll
   parameterize this in Phase 2.x.**
2. **Webhook event id derivation.** DocuSign's modern Connect SIM provides
   `eventId`; older configurations don't. When absent we synthesize a stable
   key from `(event, envelopeId, generatedDateTime)`. The synthesized key
   is still unique-indexed and idempotent.
3. **Vendor exceptions are noisy by default.** A signer who isn't a vendor
   would emit an exception row for every envelope, so vendor-side party
   misses do NOT generate exceptions (only customer-side do). Vendor
   matches still emit `proposed` links when the score is high enough.
4. **Match thresholds (0.80 propose, 0.95 auto-confirm).** Tunable in code
   today; if you want them in env vars, say the word.
5. **Replay semantics for system-emitted rows.** On reprocessing, all
   `linked_by='system'` rows in {proposed, auto_confirmed} are wiped and
   re-emitted; manually-confirmed/-rejected rows AND user-resolved
   exceptions are preserved. Verified by `test_replay_does_not_clobber_manual_link`.
6. **Webhook is unauthenticated by design.** DocuSign cannot present a
   bearer token. HMAC-SHA256 is the sole auth gate; we refuse with 503
   if no secret is configured (no silent acceptance of unsigned events).

**Operator action required to actually receive events:**
1. Set `DOCUSIGN_HMAC_SECRET` (and optionally `DOCUSIGN_HMAC_SECRET_2`
   for rotation) in `backend/.env` on the production VM.
2. Rebuild + restart: `cd /opt/gpi-hub && git pull && docker compose build
   --no-cache backend && docker compose up -d`.
3. In DocuSign Admin → Connect, point a JSON SIM webhook at
   `https://<vm-public-host>/api/docusign/webhook` with the same HMAC
   secret. Events checked: `envelope-sent`, `envelope-completed`,
   `envelope-declined`, `envelope-voided` (recommended starter set).
4. Verify with `curl -s https://<host>/api/contracts/health` —
   `docusign.webhook_ready` should flip to `true`.

**Out-of-scope (Phase 2 deliberately omits — Phase 3 territory):**
- No `/contracts` UI page, no analytics endpoints (`/contracts/summary`,
  `/contracts/expiring`, etc.).
- No live DocuSign API calls (no envelope fetch / list / download).
  `get_access_token()` still raises `DocuSignLiveCallsDisabled`.
- No `docusign-esign` SDK install yet.
- No Agreement → Document Hub cross-link panel (parked per your direction).

**What requires your review before Phase 3:**
1. Decide on the pricing-tab convention (assumption #1 above).
2. Confirm webhook URL path (`/api/docusign/webhook`) is acceptable for
   your DocuSign Connect configuration, or specify an alternative.
3. Confirm match thresholds (0.80 / 0.95) — push to env if you want
   per-environment tuning.
4. Approve Phase 3 kickoff (UI + analytics + manual-mapping screens).

**Carry-over status (still parked, untouched as instructed):**
- P1: LLM throttling / Gemini RESOURCE_EXHAUSTED — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal (time-gated drain) — UNCHANGED.



### 2026-02 — Contract Intelligence Module: **Phase 3** (UI + Analytics + Env-Driven Tunables)

**Status:** ✅ Phase 3 landed. 111/111 backend tests green. Frontend smoke-tested
on the preview environment — `/contracts` renders all 5 tabs (Agreements,
Exceptions, BC Links, Expirations, Analytics) with the existing shadcn dark
theme, nav entry visible. No regression on backend baseline.
**Sign-off authority:** user signed exact scope + 4 assumption decisions:
- Pricing tab convention parameterized via `CONTRACT_PRICING_TAB_REGEX` env
  (default `^line[_\-]?(\d+)[_\-]?(.+)$` retained).
- Webhook URL `/api/docusign/webhook` confirmed.
- Match thresholds moved to env vars
  (`CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD=0.95`,
   `CONTRACT_MATCH_PROPOSE_THRESHOLD=0.80`).
- Vendor-side party misses still suppressed in exception queue, but volume
  surfaced in `/contracts/health` + Analytics dashboard.

**Backend files mutated (additive only on behavior, no breaking changes):**
- `services/contracts/bc_agreement_matcher.py` — thresholds now read from env
  (`CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD`, `CONTRACT_MATCH_PROPOSE_THRESHOLD`)
  with safe fallback on bad/missing values; defaults unchanged (0.95 / 0.80).
- `services/contracts/agreement_normalizer.py` — pricing tab regex now read
  from env (`CONTRACT_PRICING_TAB_REGEX`), with fail-soft fallback when the
  regex is invalid or has fewer than 2 capture groups.
- `routers/contracts.py` — added 5 analytics endpoints + extended `/health`
  with vendor-link telemetry:
    * `GET /api/contracts/health` (now includes `vendor_link_telemetry`)
    * `GET /api/contracts/summary` — agreements/exceptions/links/events counts
    * `GET /api/contracts/expiring?within_days=N` — upcoming expirations
      (excludes voided/declined/expired)
    * `GET /api/contracts/coverage` — customer/vendor/item coverage ratios +
      pricing-line match ratios
    * `GET /api/contracts/threshold-telemetry?days=N` — system-emitted vs.
      human-overridden link counts, override rate, band distribution
    * `GET /api/contracts/audit/{agreement_id}` — newest-first audit trail
  All read-only, all auth-gated.
- `backend/.env` — additive only: `CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD=0.95`,
  `CONTRACT_MATCH_PROPOSE_THRESHOLD=0.80`, `CONTRACT_PRICING_TAB_REGEX=`
  (blank means default).

**Backend files added:**
- `tests/test_contracts_phase3.py` — 14 tests covering env-driven thresholds
  (override + invalid fallback), parameterized pricing convention (default,
  custom alt naming, invalid regex fallback), summary endpoint, expiring
  endpoint (excludes voided), coverage ratios, threshold telemetry counts,
  audit trail, vendor telemetry on /health.

**Frontend files added:**
- `frontend/src/pages/ContractIntelligencePage.jsx` — new top-level
  `/contracts` page. 5 tabs:
    * **Agreements** — paginated table with status filter; row click opens
      detail dialog with parties, pricing, terms, BC links (with
      Confirm/Reject inline actions), exceptions, audit timeline, and a
      "+ Manual link" dialog with link_type / bc_no / bc_name / notes.
    * **Exceptions** — filterable list (status + code) with inline Resolve.
    * **BC Links** — overview cards by status + by type (read-only summary).
    * **Expirations** — agreements expiring within N days (configurable).
    * **Analytics** — top-level counts, BC coverage card, **Auto-Confirm
      Threshold Telemetry** panel (precision@threshold from audit log;
      override rate; band distribution), **Vendor-side activity** card
      (suppressed-exception telemetry per signed guardrail).
  All shadcn UI, all dark-theme parity, every interactive element has
  `data-testid`. Manual link / confirm / reject / resolve toasted via sonner.

**Frontend files mutated (3, all minimal):**
- `frontend/src/lib/api.js` — added 13 new API helpers under
  "CONTRACT INTELLIGENCE APIs (Phase 3)" comment block. Nothing else touched.
- `frontend/src/App.js` — 1 import line + 1 route line. No restructuring.
- `frontend/src/components/Layout.js` — added `FileSignature` import +
  1 nav item entry. Nothing else changed.

**Tests run:**
```
cd /app/backend && python -m pytest \
  tests/test_contracts_models.py \
  tests/test_docusign_client_scaffold.py \
  tests/test_contracts_normalizer.py \
  tests/test_contracts_matcher.py \
  tests/test_contracts_orchestrator.py \
  tests/test_contracts_endpoints.py \
  tests/test_contracts_phase3.py -q
→ 111 passed
```
Frontend smoke: live preview at `/contracts` → page renders, 5 tabs visible,
nav entry highlighted, empty-state shown, no console errors.

**Assumptions made (calling them out for the record):**
1. **Threshold-telemetry algorithm.** "Override rate" = count of audit rows
   with `action=rejected_link` AND `actor != system` for any link previously
   emitted by the system. This conflates "rejected after auto-confirm" with
   "rejected after propose"; the band breakdown helps separate. If you want
   stricter precision (e.g., only auto-confirmed rejected = override), say
   the word and I'll add a stricter computation.
2. **Vendor telemetry on `/health` is unauth.** Same posture as before for
   the diagnostic endpoint. Counts are non-sensitive (no names, no payloads).
3. **Manual link confirm/reject prompts.** Used `window.prompt()` for the
   reason/note string for speed — fine for an internal admin UI. A proper
   inline form (Textarea in Dialog) is a 10-minute polish if you want it.
4. **No frontend tests.** Per system prompt's testing rules, single-component
   smoke is sufficient for this size of change; backend tests cover the
   contract surface. If you want Playwright coverage, I can add it.

**Out-of-scope (Phase 3 deliberately omits, per signed guardrails):**
- No DocuSign SDK install, no live envelope fetch (still Phase 2.x territory).
- No Agreement → Document Hub cross-link panel (parked for post-Phase-3 review).
- No BC writes, no DocuSign writes, no AP pipeline / email poller / vendor
  alias / posting changes. Confirmed via diff inspection.

**Carry-over status (still parked, untouched):**
- P1: LLM throttling / Gemini RESOURCE_EXHAUSTED — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal (time-gated drain) — UNCHANGED.

**Operator activation steps for the new tunables (no rebuild needed for
defaults — already wired into .env):**
1. To re-tune match thresholds without a code change:
   ```
   docker compose exec backend env CONTRACT_MATCH_AUTO_CONFIRM_THRESHOLD=0.93 ...
   ```
   (or set in docker-compose.yml env block, restart the backend container).
2. To use a custom DocuSign tab naming convention:
   ```
   CONTRACT_PRICING_TAB_REGEX=^lineitem[_\\-]?(\d+)[_\\-]?(.+)$
   ```
3. Frontend nav entry "Contracts" appears automatically — no extra step.



### 2026-02 — Contract Intelligence Module: **Phase 3.1** (Hardening Pass)

**Status:** ✅ Phase 3.1 landed. 120/120 backend tests green
(9 new + 111 carried forward). 10/10 Playwright e2e tests pass against the
live preview environment (2 fixture-gated tests skip gracefully when no
seeded exceptions exist — by design). Lint clean across all 5 touched files.
**Sign-off authority:** user signed exact 4-item scope (no scope creep):
prompt() replacement, banded telemetry, exception → manual-mapping inline
workflow, lightweight Playwright e2e.

**Backend changes (additive only):**
- `routers/contracts.py` —
  * **Tighter threshold telemetry**: `GET /contracts/threshold-telemetry`
    now returns separated `auto_confirm_override_rate` and
    `propose_override_rate` plus `by_band_overrides` breakdown. Combined
    `override_rate` retained for back-compat. Empty state preserves all keys
    so the UI shape is stable.
  * **New endpoint** `GET /contracts/bc-search?q=…&link_type=customer|vendor|item`
    — read-only, scoped to the existing `bc_reference_cache` collection.
    Customer/vendor: substring match on name regex (special chars escaped) +
    exact match on bc_no. Item: returns empty matches + `hint` field
    (the BC reference cache doesn't index items by display name in this
    codebase). Auth-gated. Dedupes results by bc_no.
  * Switched `regex=` → `pattern=` on the `link_type` Query param to silence
    Pydantic deprecation warning.
- `tests/test_contracts_phase3_1.py` (NEW) — 9 tests:
  * Banded telemetry separates auto-confirm rejection from propose rejection
    with the right denominators.
  * Empty-state preserves shape.
  * BC search for customer by name + by exact no.
  * Vendor search isolated from customer (no cross-contamination).
  * Item link_type returns hint + empty matches.
  * Invalid link_type → 422.
  * Regex-special characters escaped (no 500 / no ReDoS).
  * Auth required (401 without token).

**Frontend changes (additive — only `ContractIntelligencePage.jsx` and
`lib/api.js` touched, no Layout / App / unrelated files mutated this round):**
- `lib/api.js` — 1 new helper `contractsBCSearch({q, link_type, limit})`.
- `pages/ContractIntelligencePage.jsx` —
  * Removed both `window.prompt()` calls. Replaced with a reusable
    `<NoteDialog>` modal (Textarea + Cancel/Confirm) used for:
      - Reject link note (in agreement-detail dialog)
      - Resolve exception note (in Exceptions tab)
  * **Exception → inline mapping** (Exceptions tab):
      - "Map" button on every open `party_unmatched` / `item_unmatched` row.
      - `<ExceptionMappingDialog>` opens with link_type selector pre-set
        from the exception code, BC search box pre-filled with the party
        org/name or item label from `details`.
      - Auto-search on open + on link_type change.
      - Result list (clickable cards) populates BC No. + Name fields.
      - Optional manual override of BC No. text (for items, where search
        returns empty + a hint).
      - "Mark exception as resolved after creating the link" checkbox
        (default: ON). When ON: 1 click does manual_link → resolve_exception
        → 2 audit rows (`confirmed_link` + `exception_resolved`).
      - Toast feedback, never silently fails.
  * **Banded telemetry rendered** in the Analytics tab — two new cards
    showing `auto_confirm_override_rate` (with guidance "higher than ~5%
    suggests the auto-confirm threshold is too low") and
    `propose_override_rate` (with guidance "higher rejection here is
    expected — propose links are reviewed by humans"). Combined override
    rate kept above the divider as the headline number.
  * Every new interactive element carries `data-testid` for e2e:
      - `resolve-exception-dialog-{textarea,submit,cancel}`
      - `reject-link-dialog-{textarea,submit,cancel}`
      - `exception-mapping-{dialog,link-type,query,search-btn,results,
        bcno,bcname,resolve-after,submit,cancel,hint,pick-{bc_no}}`
      - `map-exception-{exception_id}` (per-row button)
      - `telemetry-{auto-confirm,propose}-band`

**E2E test coverage (NEW):**
- `tests/e2e/__init__.py`
- `tests/e2e/test_contracts_page_e2e.py` — 12 Playwright sync tests via
  `/opt/plugins-venv/bin/python`:
  * Page renders with H1 "Contract Intelligence".
  * All 5 tabs visible (parametrized).
  * Tab switching works for Exceptions, Analytics (incl. all 4 top-level
    cards verified), Expirations (days input visible), BC Links (all 4
    status cards visible).
  * Resolve-exception dialog opens + textarea visible (skipped gracefully
    if no open exceptions seeded).
  * Exception-mapping dialog opens with link-type selector + search button
    (skipped gracefully if no party/item-unmatched exceptions seeded).
  * Tests are read-only — every mutation is followed by Cancel; no
    persisted writes against the live DB.
- Run command:
  ```
  /opt/plugins-venv/bin/python -m pytest tests/e2e/test_contracts_page_e2e.py -q
  ```
- Live verification on preview: **10 passed, 2 skipped in 5.11s**.

**Tests run:**
```
backend: 120/120 passed (9 new Phase 3.1 + 111 carried forward)
e2e:     10/10 passed, 2 skipped (fixture-gated, by design)
```
Frontend hot-reload picked up changes; webpack compiled with only pre-existing
react-hooks/exhaustive-deps warnings (intentional — refresh callbacks are
referentially unstable; eslint-disable-next-line comments retained).

**Assumptions made (calling them out):**
1. **BC search relies on the existing `bc_reference_cache` collection**.
   Customer/vendor names there come from cached BC documents (POs, SOs,
   invoices). Coverage equals BC's "active" entities — customers/vendors
   that have never had a transaction recorded won't appear. This matches
   the user's "use existing reference cache/API patterns" directive.
2. **Items aren't searchable yet** — the cache doesn't index items by
   display name. The UI surfaces a hint asking the operator to enter the
   BC item number directly. This is documented in the response payload
   (`hint` field) and on the Mapping dialog. Item indexing → Phase 4
   backlog if/when needed.
3. **Mapping dialog auto-resolves the exception by default** — toggle is
   visible and on by default. If the user unchecks it, the link is created
   but the exception stays open (useful when partial fix only).
4. **`window.prompt()` cleanup verified by grep** — the only remaining
   reference is a code comment on the NoteDialog component documenting
   what it replaces. No live calls remain.

**What requires your review before live DocuSign work:**
1. Run a few real DocuSign envelopes through the webhook (after setting
   `DOCUSIGN_HMAC_SECRET` in production) so the BC search + mapping flows
   can be exercised end-to-end with seeded exceptions.
2. Confirm the banded override-rate guidance copy ("higher than ~5%…",
   "higher here is expected…") matches your operational view, or give me
   tighter numbers / language.
3. Approve moving to **Phase 4** (DocuSign SDK install + live envelope
   fetch) — still gated by `DOCUSIGN_LIVE_CALLS_ENABLED=true` until you
   sign.

**Out-of-scope (Phase 3.1 deliberately omits, per signed guardrails):**
- No DocuSign SDK install yet.
- No live envelope fetch yet.
- No Agreement → Document Hub cross-link yet.
- No BC writes, no AP / posting / email-poller / vendor-alias touch.

**Carry-over status (still parked, untouched):**
- P1: LLM throttling / Gemini RESOURCE_EXHAUSTED — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal (time-gated drain) — UNCHANGED.



### 2026-02 — Contract Intelligence Module: **Phase 3.2** (Real Webhook Validation — Tooling Shipped)

**Status:** ⏸️ Tooling delivered. **Awaiting user-driven live validation pass.**
This phase is fundamentally human-driven — agent cannot SSH into the
production VM, configure DocuSign Connect, or fire real envelopes from the
user's DocuSign account. To make the round-trip cheap, agent shipped:
1. A dry-run normalizer probe (paste a captured Connect payload → see
   exactly what the parser would extract, no DB writes).
2. A read-only post-event inspector (dumps full agreement state for one
   envelope after it lands, including events / parties / terms / pricing
   / docs / links / exceptions / audit trail).
3. A step-by-step runbook covering Steps 0-6 (pre-flight dry-run → deploy
   → set HMAC secret → configure Connect → fire test envelope → verify →
   file findings).

**Files added (3, all read-only, all inside the Contract Intelligence boundary):**
- `backend/scripts/contracts_dryrun_normalizer.py` — pure CPU probe. Reads a
  payload file (or `-` for stdin), runs `normalize_envelope`, prints the
  resolved Agreement / Parties / Terms / Pricing / Documents + warnings.
  No DB connection, no network. Verified locally with a synthetic SIM
  payload — reports the right party_count, term sources, pricing line.
- `backend/scripts/contracts_validation_probe.py` — read-only Mongo
  inspector with three modes:
    * `--envelope-id <id>` — full state for one envelope
      (events ➜ agreement ➜ children ➜ links ➜ exceptions ➜ audit)
    * `--latest` — most recent event + the agreement it produced
    * `--recent-events N` — last N events regardless of envelope
  Verified import + CLI help + empty-state behavior in preview.
- `memory/PHASE_3_2_VALIDATION_RUNBOOK.md` — 6-step playbook for the user:
    * Step 0: Dry-run normalizer against a captured Connect payload BEFORE
      production. **Critical step** — catches pricing-tab-convention
      mismatches and field-shape gaps without firing real events.
    * Step 1: Deploy on the VM (`git pull && docker compose build --no-cache
      backend && docker compose up -d`).
    * Step 2: Set `DOCUSIGN_HMAC_SECRET`. Verify `webhook_ready=true` via
      `/api/contracts/health`.
    * Step 3: Configure DocuSign Connect (JSON SIM, recommended events,
      include Custom Fields + Form Data, install HMAC key).
    * Step 4: Fire a real / sandbox envelope.
    * Step 5: 16-row validation checklist covering raw payload landing,
      idempotent replay, agreement upsert, sender/parties/terms/pricing/
      documents persistence, BC matching, audit completeness, UI surfacing,
      inline mapping, reject flow.
    * Step 6: Findings report template (envelope used, checklist results,
      payload-assumption adjustments needed, UI findings, recommended
      Phase 4 scope).
  Includes a quick-reference one-liners section: `--latest`, `--envelope-id`,
  `--recent-events 20`, dry-run command, health probe, unsigned-event
  rejection check, **AND** a fully-formed openssl-signed `curl` recipe to
  smoke-test the webhook against your real HMAC secret + a replay variant
  to confirm idempotency over HTTP.

**No production code mutated.** `routers/contracts.py`, models, services,
.env — none touched this round. The 3 new files are scripts + a markdown
runbook, all inside the Contract Intelligence boundary.

**Tests:** 120/120 backend regression unchanged (no behavior changes).
Lint clean on both new scripts.

**Why this approach (assumption I'm flagging):**
- Phase 3.2 is operational, not code work. The fastest path to a real
  validation pass is *not* "agent tries to predict failure modes" but
  "user fires one envelope and we look at the dump". Both scripts make
  that cheap. The dry-run script in particular catches the highest-risk
  finding (pricing-tab convention mismatch) without a single production
  HTTP call.

**Activation steps for the user (the playbook is the spec):**
Read `/app/memory/PHASE_3_2_VALIDATION_RUNBOOK.md` end-to-end. Steps 0
(preview-side dry-run with a captured payload) and the smoke-test curl
in Quick Reference can be done on the preview VM today. Steps 1-5 require
production access + DocuSign admin rights.

**What I'm waiting for from the user before any further code change:**
1. Step 0 dry-run output (parties / terms / pricing all populate as
   expected? Any `Pricing (0)` when lines were expected?).
2. Step 4-5 inspector output for one real envelope (paste the
   `--envelope-id <id>` dump) + the filled-in 16-row checklist.
3. Recommended Phase 4 scope based on findings.

**Out-of-scope (Phase 3.2 deliberately omits, per signed guardrails):**
- No DocuSign SDK install.
- No live envelope fetch.
- No Agreement → Document Hub cross-link.
- No suggested-threshold widget.
- No code changes to existing routes/services.
- No AP / posting / email-poller / vendor-alias / unrelated touch.

**Carry-over status (still parked, untouched):**
- P1: LLM throttling / Gemini RESOURCE_EXHAUSTED — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal (time-gated drain) — UNCHANGED.



### 2026-02 — Contract Intelligence Module: **Phase 3.2 cont.** (Golden-Fixture Pipeline Pre-built)

**Status:** ⏸️ Pipeline ready. **Awaiting one real (sanitized) DocuSign payload
from the user.** Once dropped into `backend/tests/fixtures/docusign/`, the
auto-discovery harness produces 7 regression assertions per fixture without
any further code change.

**What I shipped this round (3 files, all read-only / additive):**
- `backend/scripts/contracts_redact_payload.py` — deterministic redaction
  helper. Walks any DocuSign Connect SIM payload and:
  * Replaces `email`, `name`, `userName`, `companyName` with stable
    placeholders **only inside person blocks** (dict has both an `email`
    field AND a name-ish field). This was the key insight after the
    initial v1 wrongly redacted document names + custom-field names + tab
    names. Fixed in this round before commit; verified end-to-end.
  * Replaces `accountId` / `userId` with stable placeholders.
  * Drops `documentBase64` / `pdfBytes` / signing tokens entirely.
  * Preserves: tab/term naming convention, dates, status enums, line
    structure — everything regression-testing actually needs.
  * Optional `--extra-paths data.envelopeSummary.subject` to scrub
    additional dotted JSON paths per fixture.
  * Prints a redaction-audit summary to stderr (key, before, after) so the
    operator can review the diff before committing.

- `backend/tests/test_contracts_golden_fixtures.py` — auto-discovering
  parametrized harness. Default checks per fixture:
    1. Normalizer accepts payload (no ValueError).
    2. `provider_envelope_id` resolved and non-empty.
    3. `status` mapped to a known value (NOT `unknown`).
    4. At least one party (sender or signer).
    5. Warnings JSON-serializable (round-trip safe).
    6. All persisted rows JSON-serializable via `model_dump(mode="json")`.
    7. Per-fixture pinned expectations (skipped unless
       `_FIXTURE_EXPECTATIONS[<filename_stem>]` defines `min_parties` /
       `min_terms` / `min_pricing_lines` / `expected_status` / `min_documents`).
  Plus 3 harness sanity tests (dir exists, README present, no non-JSON
  files picked up).

- `backend/tests/fixtures/docusign/README.md` — redaction contract
  + step-by-step "how to add a fixture" recipe + table of preserve-vs-redact
  fields. Documents the convention before any fixture lands so you have a
  one-page reference next to your validation pass.

**Files materialized for plumbing (empty markers):**
- `backend/tests/fixtures/__init__.py`
- `backend/tests/fixtures/docusign/__init__.py`
- `backend/tests/fixtures/docusign/.gitkeep`

**Tests:** 123/123 passed + 7 fixture-gated skips (gracefully empty
parametrize when no `*.json` fixtures exist; auto-populates the moment
one lands). Lint clean on both new scripts + the harness. No production
code mutated.

**End-to-end pipeline verified locally:**
1. Synthetic SIM payload → redactor → produces correct placeholders for
   sender/signers and preserves `customFields[*].name`, `formData[*].name`,
   and `envelopeDocuments[*].name` exactly.
2. Redacted file dropped into `fixtures/docusign/` → harness automatically
   parametrized 7 cases against it, all green.
3. Synthetic fixture removed (per user spec — "first committed fixture
   should be real, not synthetic"). Harness back to graceful-empty state.

**Why I bailed on writing speculative regression assertions:**
The whole value of the golden-fixture pattern is that it pins down what
DocuSign **actually** emits for the user's templates. Pre-writing
fixture-specific expectations against a fictional payload would defeat
that. The harness is structurally complete; the pinning happens once you
share a sanitized real payload and we agree on the right thresholds
(min_parties, min_terms, etc.) for that template.

**What I'm waiting on from you:**
1. **Step 0 (preview-safe, today)**: capture any DocuSign Connect message
   JSON into a file on the VM, then:
   ```
   docker compose exec backend python -m scripts.contracts_redact_payload \
       /tmp/connect_raw.json \
       --extra-paths data.envelopeSummary.subject \
       --extra-paths data.envelopeSummary.emailSubject \
       > /tmp/connect_redacted.json
   ```
   Review the stderr audit summary; spot-check the output JSON.
2. Run the dry-run normalizer against the redacted file — confirm
   `Pricing` / `Terms` / `Parties` populate as expected.
3. Paste the dry-run output here. If anything looks off (especially
   `Pricing (0)` when lines were expected), we adjust the
   `CONTRACT_PRICING_TAB_REGEX` env var — no code change.
4. Once dry-run is clean, commit the redacted file as
   `backend/tests/fixtures/docusign/<descriptor>__<status>.json`.
5. Then proceed with Steps 1-6 in `PHASE_3_2_VALIDATION_RUNBOOK.md`
   (deploy → set HMAC secret → configure Connect → fire envelope → file
   the 16-row checklist).

**Out-of-scope (Phase 3.2 boundary still strictly held):**
- No DocuSign SDK install. No live envelope fetch. No Agreement → Doc Hub
  cross-link. No suggested-threshold widget. No code changes to existing
  routes / services. No AP / posting / email-poller / vendor-alias touch.

**Carry-over status (still parked, untouched):**
- P1: LLM throttling — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal — UNCHANGED.

