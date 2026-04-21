# GPI Document Hub - Changelog


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
