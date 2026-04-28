# Tier 1 — AP "Out of Shadow Mode" Execution Plan

**Status:** PLAN ONLY. No code changes until you sign off. Stop-and-wait per directive `x9m2qp`.

**Goal:** prove the AP pipeline can post a controlled batch of 10 invoices into BC sandbox cleanly, end-to-end, with categorized failures and a deterministic re-run loop.

**Non-goal:** flipping to production. Sandbox-only. Production cutover is a separate signed step after this plan converges.

---

## 1. Shadow-mode blockers inventory (verified live)

There are **three layers** of gates, only one of which is the named "shadow mode." Lifting one without the others does nothing.

### Layer 1 — Hard environment guards (backend/.env)
| Var | Current | Effect | Action for Tier 1 |
|---|---|---|---|
| `BC_WRITE_ENABLED` | `true` | Permits BC writes at all | leave on |
| `BC_BLOCK_PRODUCTION_WRITES` | `true` | Refuses any write resolving to Production env | **leave on — this is our prod safety net during Tier 1** |
| `BC_WRITE_ENVIRONMENT` | `Sandbox_11_3_2025` | All writes route here | leave as-is |
| `BC_READ_ENVIRONMENT` | `Production` | Reads still see prod data | leave as-is |
| `BC_WRITEBACK_LINK_ENABLED` | `true` | Links posted invoice back to hub doc | leave on |

**Conclusion**: hard env layer is correctly configured for sandbox-only writes. Do not touch.

### Layer 2 — Soft execution gate (Mongo `hub_settings`)
| Field | Current | Effect |
|---|---|---|
| `hub_settings.type` | `"shadow_mode"` since 2026-02-15 | Auto-post service treats every doc as observe-only; no `create_purchase_invoice` call ever fires from the auto-post path |

**Action for Tier 1**: **don't lift shadow mode yet.** The 10-doc batch will use the **manual posting endpoint** (existing route `POST /api/gpi/documents/{doc_id}/create-purchase-invoice` in `routers/gpi_integration.py:2108`), which bypasses shadow mode by design — it's an explicit operator action. We only lift shadow mode after the manual-batch pass-rate is acceptable.

### Layer 3 — Per-vendor learning gates (Mongo `auto_post_settings`)
| Field | Current | Effect on auto-post |
|---|---|---|
| `auto_post_enabled` | `true` | Service-toggle on |
| `min_confidence` | `"medium"` | Vendor profile must have ≥medium template confidence |
| `min_invoices_analyzed` | `15` | Vendor must have ≥15 invoices learned |

**Verified live data:**
- Total vendor profiles: **605**
- Profiles with ≥15 invoices analyzed: **0**
- Profiles with high/mastered confidence: **0**

**Conclusion**: even if both prior gates lifted, the auto-post path would refuse every doc because no vendor has crossed the maturity threshold. This is the **deepest** blocker and the most important diagnostic finding. **Tier 1 explicitly side-steps this** by using manual posting, not auto-post.

---

## 2. Config + feature-flag map (one place, no surprises)

```
                    ┌──────────────── INTAKE ────────────────┐
                    │ email poller → classify → extract → vendor │
                    │ match → BC ref check → status: Completed │
                    └────────────────────────────────────────┘
                                       │
                                       ▼
       ┌─────────────────────── DECISION POINT ──────────────────────┐
       │                                                             │
       ▼ (auto-post path)                          ▼ (manual path - Tier 1)
┌─────────────────────────┐              ┌────────────────────────────────┐
│ services/auto_post_     │              │ POST /api/gpi/documents/{id}/   │
│   service.py            │              │   create-purchase-invoice       │
│                         │              │ (routers/gpi_integration.py)    │
│ GATES (in order):       │              │                                 │
│  1. shadow_mode == off  │              │ GATES (in order):               │
│  2. AUTO_POST_ENABLED   │              │  1. BC_WRITE_ENABLED=true       │
│  3. doc_type == AP      │              │  2. BC write target != prod     │
│  4. vendor_no resolved  │              │     OR BC_BLOCK_PROD=false      │
│  5. min_invoices≥15     │              │  3. doc has vendor + lines      │
│  6. template_conf≥med   │              │                                 │
│  7. confidence≥0.90     │              │ NO shadow_mode check.           │
│  8. no duplicate        │              │ NO maturity threshold.          │
│  9. no blocked vendor   │              │ NO auto-post settings.          │
└─────────────────────────┘              └────────────────────────────────┘
                                                          │
                                                          ▼
                                       ┌─────────────────────────────────┐
                                       │ services/business_central_      │
                                       │   service.py::                  │
                                       │   create_purchase_invoice       │
                                       │                                 │
                                       │ Hard guard: _check_write_       │
                                       │   protection() refuses if       │
                                       │   resolves to Production +      │
                                       │   BC_BLOCK_PROD=true            │
                                       └─────────────────────────────────┘
                                                          │
                                                          ▼
                                                    BC Sandbox
                                                    creates draft PI
                                                          │
                                                          ▼
                                       writeback to hub_documents:
                                         posted_to_bc=true
                                         bc_invoice_number=<assigned>
                                         bc_document_id=<assigned>
                                         status=Completed (terminal)
                                       insert into bc_invoice_logs
                                       insert into workflow_events
```

**Key takeaway:** Tier 1 drives the right-hand path. No flag needs to be flipped. Operator-initiated post is already permitted and lands in sandbox.

---

## 3. 10-document sandbox batch methodology

### 3.1 Candidate selection (the "10 most posting-ready" docs)

Selection query (read-only, write-safe):
```
hub_documents WHERE
  doc_type = 'AP_INVOICE'
  AND status IN ['Completed', 'NeedsReview', 'ReadyForPost']
  AND vendor_no NOT IN (NULL, '')      ← non-empty resolved vendor
  AND extracted.invoice_number NOT IN (NULL, '')
  AND extracted.total NOT IN (NULL, 0)
  AND (validation_results.checks.duplicate_check NOT IN ['fail','pending'])
ORDER BY
  vendor_match_confidence DESC,
  extraction.confidence DESC
LIMIT 10
```

**Liveness sanity check first** — verified earlier: zero AP_INVOICE docs currently have `vendor_no` populated AND status in {NeedsReview, ReadyForPost}. **This is itself a finding.** Selection probably needs to fall back to:
```
status IN ['Completed', 'NeedsReview', 'ReadyForPost']
AND (vendor_no NOT IN (NULL, '') OR extracted.vendor_name NOT IN (NULL, ''))
```
…and then do a **vendor re-resolution pass** on the selected 10 before posting attempts (see §3.3). If even the broader query returns <10, that's a Tier-0.5 finding: vendor persistence on docs is broken upstream. We surface it explicitly rather than paper over it.

### 3.2 Batch worksheet (one row per doc)

Each of the 10 docs gets a row in a markdown table tracked at `/app/memory/TIER1_BATCH_RESULTS.md` with these columns:

| # | doc_id | vendor_name | invoice_number | extracted_total | vendor_no | match_conf | duplicate? | line_count | pre-post status | post result | bc_invoice_no | category | failure_detail |

This is the artifact you review at the end of each run.

### 3.3 Pre-post normalization pass (read-only diagnostic)

Before any POST, for each candidate doc:

1. **Vendor re-resolution** — call `services/vendor_resolution.resolve_vendor(doc)` and **report** what would be written (don't write yet). This tells us whether vendor data is recoverable.
2. **Duplicate check** — call existing `check_duplicate_against_bc(invoice_number, vendor_no)` against the 278K-row BC reference cache.
3. **Line-item completeness** — count extracted lines; flag any doc with 0 lines.
4. **PO linkage** — flag any doc that has a `po_number` extracted but no matching BC PO in cache.

This produces a **dry-run report** before the first POST. You see the candidate list and can veto individual docs before anything writes.

### 3.4 Posting cadence

- **Sequential, not parallel.** One doc at a time, ~2 second pause between, so log noise is correlatable.
- **Single operator account.** Use `hub-admin@gamerpackaging.com` (legacy auth).
- **Single command/runbook step per doc.** Operator clicks or curls; agent observes.
- **Hard stop at 10.** Even if all pass, batch stops; you decide whether to run a second batch.

### 3.5 Where the batch is driven from

Two equivalent paths; you pick:

**Path A — Existing Review Queue UI** (`/document-review`)
   - Walk to each candidate doc, click "Post to BC" (existing UI button).
   - Pro: tests the real operator flow Square9/Zetadocs would replace.
   - Con: slower; harder to script; DOM clicks not inherently logged.

**Path B — Curl-driven runbook**
   - For each doc: `POST {API}/api/gpi/documents/{doc_id}/create-purchase-invoice`
   - Pro: scriptable, deterministic, every call logged.
   - Con: bypasses the UI's pre-post checks (we replicate them in §3.3 instead).

**Recommendation**: Path B for the first batch (cleanest signal). Path A for the second batch (validates UX). Both write the same workflow_events + bc_invoice_logs rows.

---

## 4. Pass/fail rubric (per document)

Each of the 10 docs lands in exactly one bucket:

### PASS buckets
- **P1 — Clean post**: `posted_to_bc=true`, BC returned a draft PI number, hub doc has `bc_invoice_number` populated, workflow_events has `bc_post.success`, no warnings.
- **P2 — Post with advisory**: posted successfully, but with non-blocking advisories (e.g., extraction quality warning, alias-fuzzy-match used). Operator review required next batch but the workflow completed.

### FAIL buckets (categorized by root cause)
- **F-CONFIG** — env or settings-level guard rejected the request (`BC_WRITE_ENABLED=false`, write target resolves to prod, etc.). Should be zero with current `.env`.
- **F-AUTH** — BC OAuth token refresh failed, tenant/client mismatch, scope-revoked.
- **F-REF** — vendor not found in BC, GL account missing, location code not in BC, currency code not configured. **Reference-data resolution failure.**
- **F-DATA** — extraction missing critical field (invoice number, date, amount), line items don't sum to total, vendor on doc but doesn't match any BC vendor.
- **F-DUP** — invoice already posted in BC (caught by the duplicate-check). **This is a PASS-by-design** (the system correctly refused).
- **F-RULE** — BC rejected due to posting-rule violation (closed period, document date out of range, vendor on hold). **BC-side rule, not hub bug.**
- **F-NETWORK** — transient: timeout, 5xx from BC, retry exhausted.
- **F-BUG** — an actual hub bug (uncaught exception, malformed payload). These are the only items that block the next batch.

### Batch-level PASS criterion
- ≥7/10 in P1+P2.
- 0 F-BUG.
- All F-DATA items have a clear "fix in extraction" remediation note.
- All F-REF items have a clear "fix in BC reference data" remediation note.

If batch hits these, declare **Tier 1 viable**, schedule batch-2 with the fixes from batch-1.

If batch misses, **fix only the highest-frequency failure category first**, rerun the same 10 docs (idempotent — duplicate-check protects against double-post).

---

## 5. Rollback / safety posture

### Pre-batch verification (must pass before posting #1)

Five checks, run as a single curl-sequence:
1. `GET /api/bc/health` returns `{"status":"healthy","write_environment":"Sandbox_11_3_2025","block_production_writes":true}`.
2. `GET /api/bc/sandbox/info` confirms tenant + sandbox env name match `.env` exactly.
3. `GET /api/admin/deprecation-metrics` returns 200 (smoke test — generic health).
4. `GET /api/dashboard/ap-metrics` returns expected counts.
5. **Sandbox idempotency probe**: post a known-test doc, capture `bc_invoice_number`, post the same doc again, expect `F-DUP` not double-write. (Use a pre-existing test seed — don't add new seed data.)

If any of those 5 checks fails, **abort batch**.

### During-batch safety
- Hard cap: 10 docs per batch.
- Per-doc timeout: 60 seconds. After timeout, mark the doc `F-NETWORK` and continue.
- Auto-pause on first F-BUG: stop the batch immediately, report.
- Every POST has correlation_id logged so we can grep workflow_events post-hoc.

### Rollback (if a doc posts incorrectly to sandbox)
Sandbox PIs can be deleted via:
- `DELETE /api/bc/purchase-invoices/{bc_invoice_number}` — already exists in BC service for sandbox-only deletes (verified at `services/business_central_service.py`).
- Or in BC sandbox UI directly.

Rolling back is **manual + per-doc**. There is no "undo this batch" button. That's acceptable for sandbox; production cutover would warrant something stronger.

### Production safety
**Production writes remain physically impossible during Tier 1.**
- `BC_WRITE_ENVIRONMENT=Sandbox_11_3_2025` (env)
- `BC_BLOCK_PRODUCTION_WRITES=true` (env)
- `_check_write_protection()` raises `WriteProtectedError` if either is changed mid-batch
- `BC_PROD_*` credentials are present in `.env` but **not consumed** by the write path; they're reserved for future cutover

No code path during Tier 1 can write to production. This is verified by the unit tests at `tests/test_phase6_shadow_mode.py` (existing coverage).

---

## 6. Files / modules / flags Tier 1 will touch

### Read-only / observed (NOT modified):
- `services/business_central_service.py` — write path; observed via logging only
- `services/bc_write_safety_guard.py` — gate; observed
- `services/auto_post_service.py` — bypassed; not invoked
- `services/vendor_resolution.py` — invoked for the §3.3 normalization pass; not modified
- `routers/gpi_integration.py:2108` — the `create_purchase_invoice_from_document` endpoint we drive
- `hub_settings` collection — observed; not mutated
- `auto_post_settings` collection — observed; not mutated

### Will be written (new files only, no overwrite):
- `/app/memory/TIER1_BATCH_RESULTS.md` — append-only worksheet, one row per doc (§3.2)
- `/app/backend/scripts/tier1_batch_runner.py` — **single new** runbook script that:
   1. Runs the 5 pre-batch checks
   2. Selects 10 candidates per the §3.1 query
   3. Runs the §3.3 dry-run normalization pass and prints it for operator review
   4. **Pauses for operator confirmation** before any POST
   5. Posts sequentially, captures result, classifies into pass/fail bucket
   6. Appends the worksheet row
   7. Stops at 10 or first F-BUG
- `/app/backend/scripts/tier1_post_batch_report.py` — **single new** read-only summarizer that produces the operator-readable batch report

### Flags / env: **none touched in Tier 1**
- All gates remain at current values.
- `hub_settings.type` stays `shadow_mode`.
- `auto_post_settings` stays as-is.
- `.env` BC vars stay as-is.

If batch passes, **lifting `shadow_mode` is a separate signed step**, not part of Tier 1.

### Test files (new, not modifying existing tests):
- `/app/backend/tests/test_tier1_batch_dry_run.py` — verifies the candidate-selection query and §3.3 normalization pass deterministically against a fixture set. **No live BC calls.**

### Frontend: **untouched in Tier 1.** No UI changes.

---

## 7. Explicit out-of-scope

Tier 1 will **NOT**:

- ❌ Lift `hub_settings.type=shadow_mode`
- ❌ Modify any `auto_post_settings` value
- ❌ Modify any `BC_*` env var
- ❌ Modify the auto-post service code path
- ❌ Modify the `create_purchase_invoice` write code path
- ❌ Modify the BC write safety guard
- ❌ Touch frontend pages
- ❌ Touch sales mailbox / SO pipeline
- ❌ Touch CP/consigned registries
- ❌ Touch the Entra/MSAL auth surface
- ❌ Touch the Phase 3 monolith refactor (frozen helpers)
- ❌ Build outbound delivery / branded PDFs (Tier 3)
- ❌ Build search/retrieval UX (Tier 4)
- ❌ Add `/api/auth/whoami`
- ❌ Touch RBAC enforcement (P1.C / P1.J / P1.A / P1.F)
- ❌ Run any batch larger than 10 documents
- ❌ Run any batch against production BC

---

## 8. What I need from you to proceed

Single decision point: **Sign as-is, or amend.**

If signed, I execute in this order:
1. Write the two new scripts (`tier1_batch_runner.py`, `tier1_post_batch_report.py`) and the dry-run test (`test_tier1_batch_dry_run.py`).
2. Run only the 5 pre-batch verification curls. Report results.
3. Run only the dry-run normalization pass on 10 candidates. Report. **Stop and wait** for your go/no-go on the candidate list.
4. On your go, post sequentially to sandbox, populate the worksheet, report.
5. On batch completion, classify all 10 + recommend the highest-priority fix for batch-2.

Estimate: ~30 minutes of agent time end-to-end if no F-BUG appears. Each F-BUG adds ~30 minutes of triage.

---

## 9. Acceptance signal for "Tier 1 viable"

Tier 1 is declared viable — and the sales-side / Zetadocs-replacement work can begin — **only when** a single batch of 10 sandbox-posted docs hits ≥7/10 in P1+P2 with zero F-BUG.

Below that bar, the next sprint is more Tier 1 (fix-and-rerun), not Tier 2.

---

**Awaiting your `Sign as-is` (or amendments).** No code, scripts, or test files written until then.
