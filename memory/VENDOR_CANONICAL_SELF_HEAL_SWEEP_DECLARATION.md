# §6.2 Implementation Declaration — Retroactive Vendor-Canonical Self-Heal Sweep (CODE-CHANGE PLAN, NO CODE EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any code lands.
- Parent: `memory/SENDER_STAMPING_REMEDIATION_PLAN.md` §6.2.
- Predecessors signed and observed clean: parent declaration + Phase B
  (`memory/SENDER_STAMP_GUARD_PHASE_B_DECLARATION.md`).
- Out of scope (preserved): §6.1 live-path self-heal symmetry, §7
  alias/profile/intelligence cleanup, `sender_vendor_map` edits,
  Batch-2 resumption.

---

## 1. Goal

Correct stale `vendor_canonical` values on AP_Invoice docs that already
have an authoritative BC resolution cached on them, **before any further
posting batch runs**. The sweep heals only the narrowly-defined set of
docs where the contradiction is unambiguous (extracted vendor agrees
with BC, BC disagrees with the current canonical), and emits a structured
audit row per fix that supports per-doc rollback.

The sweep is a one-shot operator-driven script. Read-only by default.
`--apply` for the actual writes. Idempotent (re-running on already-healed
docs is a no-op).

The first concrete win the sweep delivers: the 3
`Mid America Logistics → Brown Warehouse Company` docs flip to
`vendor_canonical = "Mid America Logistics Group LLC"` and
`bc_vendor_number = "MIDAMER"`. Those become eligible for Batch-2 once
the broader Batch-2 disposition is re-evaluated (separate signed step).

## 2. Files touched (exact)

| # | path | change kind | net effect |
|---|---|---|---|
| 1 | `backend/scripts/vendor_canonical_self_heal_sweep.py` | new file (~280 LOC) | the sweep itself — read-only by default, `--apply` for writes, idempotent |
| 2 | `backend/tests/test_vendor_canonical_self_heal_sweep.py` | new file | unit + integration coverage (Class A–D below) |

**No production source code is modified.** No new endpoints, no schema
changes, no env-flag changes, no telemetry-schema changes (the
`vendor.canonical_self_healed` event already has its name reserved by
the parent plan §6).

## 3. Eligibility criteria (a doc qualifies for auto-heal IFF ALL of these)

A doc qualifies for auto-heal only when **every one** of the following is
true. Anything weaker stays in the `manual_review` bucket; anything
ambiguous stays excluded.

1. `document_type == "AP_Invoice"`.
2. `extracted_fields.vendor` is non-empty (we have an extracted name to
   reason about).
3. `validation_results.bc_record_info.number` is present and non-empty
   (BC validation already resolved a vendor on this doc).
4. `validation_results.bc_record_info.displayName` is present and
   non-empty (we have a human-readable canonical to write).
5. `vendor_match_likely(extracted_vendor, bc_record_info.displayName)` is
   **True** — i.e. extraction agrees with BC.
6. `vendor_match_likely(bc_record_info.displayName, vendor_canonical)` is
   **False** — i.e. the current canonical contradicts BC.
7. `bc_purchase_invoice` is **null** (doc has not yet been posted to BC).
   Healing a posted doc would create a hub-vs-BC mismatch on a
   completed transaction; those go to manual review.
8. `is_duplicate` is **not** True AND `duplicate_of_document_id` is
   **null** (don't heal docs that have been superseded).
9. No manual override is set. Conservative inclusion test:
   `vendor_canonical_manual_override` is **falsy** AND
   `vendor_match_method` is **not** in `{"manual", "manual_override",
   "operator_correction"}`.

If all 9 are true, the doc is in the `auto_heal` bucket. If 1, 2, 3, or
4 are missing → `not_applicable`. If 5 fails (extraction disagrees with
BC) → `manual_review_extraction_vs_bc_disagreement`. If 6 holds but 7,
8, or 9 disqualify → `manual_review_protected`.

## 4. Exact fields updated (per heal)

For each doc in the `auto_heal` bucket, in `--apply` mode the sweep
performs ONE Mongo update with these fields and **nothing else**:

```python
{
    "$set": {
        "vendor_canonical": bc_info["displayName"],
        "bc_vendor_number": bc_info["number"],   # mirrors the existing line-1204 self-heal
        "vendor_match_method": "self_healed_bc_validation",
        "self_healed_at": "<iso8601 utc>",
        "self_heal_source": "vendor_canonical_self_heal_sweep_v1",
    },
    "$push": {
        "self_heal_history": {
            "healed_at": "<iso8601 utc>",
            "previous_vendor_canonical": <prior value>,
            "previous_vendor_match_method": <prior value>,
            "new_vendor_canonical": bc_info["displayName"],
            "new_bc_vendor_number": bc_info["number"],
            "source": "vendor_canonical_self_heal_sweep_v1",
        }
    }
}
```

`self_heal_history` is an array carrying the FULL prior values needed to
revert this single doc's heal. The reverse-sweep uses the most-recent
entry to restore prior state.

## 5. Exact event emitted (per heal)

ONE `workflow_events` row per doc healed:

```json
{
  "event_id": "<uuid>",
  "event_type": "vendor.canonical_self_healed",
  "status": "completed",
  "source_service": "vendor_canonical_self_heal_sweep",
  "timestamp": "<iso8601 utc>",
  "actor": null,
  "document_id": "<doc.id>",
  "payload": {
    "from": {
      "vendor_canonical": "<prior value>",
      "vendor_match_method": "<prior value>",
      "bc_vendor_number": "<prior value>"
    },
    "to": {
      "vendor_canonical": "<bc_info.displayName>",
      "vendor_match_method": "self_healed_bc_validation",
      "bc_vendor_number": "<bc_info.number>"
    },
    "extracted_vendor": "<extracted_fields.vendor>",
    "source": "vendor_canonical_self_heal_sweep_v1",
    "sweep_run_id": "<uuid for the sweep invocation>"
  }
}
```

`sweep_run_id` lets you find every doc touched by a single invocation —
useful for bulk-revert if needed.

`vendor.canonical_self_healed` is the same name reserved by the parent
plan; this declaration is the canonical place where it gets emitted.

## 6. Exclusions / manual-review categorisation

The sweep produces a markdown report at
`/app/memory/VENDOR_CANONICAL_SELF_HEAL_REPORT_<sweep_run_id>.md` with
per-bucket counts and sample doc_ids:

| bucket | meaning | action by sweep |
|---|---|---|
| `auto_heal` | passes all 9 criteria | healed in `--apply` mode |
| `clean_no_change_needed` | criteria 6 fails (current canonical agrees with BC) | nothing |
| `not_applicable_no_extracted_vendor` | criterion 2 missing | nothing |
| `not_applicable_no_bc_resolution` | criterion 3 or 4 missing | nothing |
| `manual_review_extraction_vs_bc_disagreement` | extracted name disagrees with BC display name (rung-1 BC vs rung-2 extraction conflict) | flagged in report |
| `manual_review_protected_already_posted` | criterion 7 fails (already in BC) | flagged in report |
| `manual_review_protected_duplicate` | criterion 8 fails | flagged in report |
| `manual_review_protected_manual_override` | criterion 9 fails | flagged in report |

`manual_review_*` rows are written to a JSON sidecar
(`VENDOR_CANONICAL_SELF_HEAL_MANUAL_REVIEW_<sweep_run_id>.json`) so a
human can act on them in a separate signed step.

## 7. Expected effect on the currently held Batch-2 candidates

Per the latest tightened sweep (2026-04-28), the four at-risk Batch-2
candidates today are:

| doc_id | extracted vendor | current canonical | predicted bucket |
|---|---|---|---|
| `2606d9b4-…` | Mid America Logistics Group, LLC | Brown Warehouse Company | **auto_heal → MIDAMER** |
| `f4a446d7-…` | Mid America Logistics Group, LLC | Brown Warehouse Company | **auto_heal → MIDAMER** |
| `d10f5242-…` | Mid America Logistics Group, LLC | Brown Warehouse Company | **auto_heal → MIDAMER** |
| `71a6cb28-…` | SC Warehouses, LLC | YANDELL | `not_applicable_no_bc_resolution` (alias_driven, BC never resolved this) — **stays excluded** |

Predicted post-sweep state of Batch-2:
- 3 Mid America candidates flip to `MIDAMER` and are no longer at risk.
- SC Warehouses candidate stays excluded (its remediation is alias retire,
  which is §7 — not in scope here).
- 5 genuinely-safe candidates remain unchanged.
- Net Batch-2 eligible after sweep: 5 (unchanged from before sweep —
  the sweep moves 3 docs from "at risk" to "needs Batch-2 disposition
  re-evaluation", but does not authorise their posting).

The sweep does NOT trigger any Batch-2 action. Whether to add the 3
healed Mid America docs to Batch-2 is a SEPARATE signed step after the
sweep is observed clean.

The broader 37-doc `doc_prestamp_or_fallback` cluster (CARGOMO,
TUMALOC, CREAT, etc.) — most are likely
`not_applicable_no_bc_resolution` because BC validation never returned
a clean match (the MKC trace showed `bc_record_info: {}`). Sweep will
report exact counts.

## 8. Rollback posture

| layer | rollback action | takes |
|---|---|---|
| Single doc | locate the doc's most-recent `self_heal_history` entry; restore `vendor_canonical`, `vendor_match_method`, `bc_vendor_number` from `previous_*` fields; pop the entry; emit a `vendor.canonical_self_heal_reverted` event | one Mongo update; supplied as a `--revert <doc_id>` flag on the same script |
| Single sweep run (every doc touched) | `--revert-sweep-run <sweep_run_id>` queries `workflow_events` for all `vendor.canonical_self_healed` rows with that run id and reverts each | one script invocation |
| All sweeps ever run | `--revert-all` (only available with explicit `--i-mean-it` flag) | bulk operation; logged |
| The sweep tool itself | `git revert <commit>` of the new files; production code unaffected | one commit |

The `self_heal_history` array means revert never requires guessing the
prior state — it's recorded on the doc itself plus mirrored in
`workflow_events`.

`--apply` writes are wrapped in a per-doc try/except so a single failure
doesn't abort the run. Failures are logged with full context and
included in the report.

## 9. Tests (new file `backend/tests/test_vendor_canonical_self_heal_sweep.py`)

### Class A — Eligibility criteria (pure-function `_classify_doc(doc)`)
- A1 doc with `vendor_canonical` matching BC → `clean_no_change_needed`
- A2 doc with `vendor_canonical` disagreeing with BC, all other criteria pass → `auto_heal`
- A3 doc missing `bc_record_info.number` → `not_applicable_no_bc_resolution`
- A4 doc missing extracted vendor → `not_applicable_no_extracted_vendor`
- A5 doc with already-posted `bc_purchase_invoice` → `manual_review_protected_already_posted`
- A6 doc marked duplicate → `manual_review_protected_duplicate`
- A7 doc with `vendor_canonical_manual_override=True` → `manual_review_protected_manual_override`
- A8 doc where extraction disagrees with BC (the dangerous ambiguous case) → `manual_review_extraction_vs_bc_disagreement`

### Class B — Dry-run mode (no `--apply`)
- B1 sweep over fake DB with mixed docs produces correct bucket counts
- B2 dry-run does NOT write to `hub_documents` or `workflow_events`
- B3 dry-run produces a markdown report at the expected path

### Class C — Apply mode
- C1 `--apply` heals an `auto_heal` doc: writes `vendor_canonical`, `bc_vendor_number`, `vendor_match_method`, `self_healed_at`, `self_heal_source`, and pushes a `self_heal_history` entry
- C2 `--apply` emits exactly one `vendor.canonical_self_healed` workflow_event per healed doc with the full from/to/sweep_run_id payload
- C3 `--apply` is idempotent: running the sweep twice produces no second heal on the same doc (the first run's heal makes criterion 6 false on the second pass)
- C4 `--apply` failure on one doc does NOT abort the run; the failure is recorded in the report and the next doc proceeds

### Class D — Revert mode
- D1 `--revert <doc_id>` restores `vendor_canonical`, `bc_vendor_number`, `vendor_match_method` to the `previous_*` values from `self_heal_history`
- D2 `--revert <doc_id>` pops the most-recent `self_heal_history` entry
- D3 `--revert <doc_id>` emits a `vendor.canonical_self_heal_reverted` workflow_event
- D4 `--revert-sweep-run <sweep_run_id>` reverts every doc touched by that run

### Class E — Real-world prediction
- E1 a fixture mirroring the Mid America doc shape (extracted="Mid America Logistics Group, LLC", bc_record_info.number="MIDAMER", bc_record_info.displayName="Mid America Logistics Group LLC", vendor_canonical="Brown Warehouse Company") classifies as `auto_heal`
- E2 a fixture mirroring the SC Warehouses doc shape (no bc_record_info) classifies as `not_applicable_no_bc_resolution`

Pass criterion: every test green; no regression in existing tests.

## 10. Operator usage (CLI surface)

```
python /app/backend/scripts/vendor_canonical_self_heal_sweep.py
  # default — DRY RUN. Scans, classifies, writes report to /app/memory/.

python /app/backend/scripts/vendor_canonical_self_heal_sweep.py --apply
  # APPLIES heals to every doc in the auto_heal bucket.
  # Default --batch-size=50, --max=unlimited.

python /app/backend/scripts/vendor_canonical_self_heal_sweep.py --apply --max 5
  # APPLIES at most 5 heals — useful for first cautious run.

python /app/backend/scripts/vendor_canonical_self_heal_sweep.py --revert <doc_id>
  # REVERT one doc's most-recent heal.

python /app/backend/scripts/vendor_canonical_self_heal_sweep.py --revert-sweep-run <run_id>
  # REVERT every doc touched by one sweep invocation.
```

Everything writes to `/app/memory/` inside the container; pull with
`docker compose cp` after each run (same pattern as the prior reports).

Recommended first run sequence on prod:
1. Dry run → review the report (especially `auto_heal` count + sample
   doc_ids; confirm the 3 Mid America docs are present).
2. `--apply --max 5` → heal at most 5 docs (will include the 3 Mid America
   docs first since they're top of the list by stale-date; ordering will
   actually be doc_id-stable so the operator can predict the set).
3. Verify the 3 Mid America docs flipped to `MIDAMER` via direct doc
   lookup.
4. `--apply` (no max) → heal the rest.
5. Run the vendor-mismatch sweep again → confirm contamination dropped.

## 11. Out-of-scope fence (explicit)

This declaration MUST NOT:

- Modify any production source code (server.py, document_handlers.py,
  vendor_matching.py, etc.).
- Modify any function signature.
- Modify the `vendor.sender_disagreed` event schema or behavior.
- Modify `sender_vendor_map`, `vendor_aliases`,
  `vendor_invoice_profiles`, `vendor_extraction_profiles`,
  `vendor_intelligence_profiles`, or any other vendor-learning collection.
- Run any §7 cleanup.
- Modify `services/document_handlers.py:1204` (still deferred — §6.1).
- Resume Batch-2 posting.
- Touch the frontend.
- Add new HTTP endpoints.
- Auto-heal docs whose extraction disagrees with BC validation (those
  always go to manual review).
- Auto-heal already-posted docs (criterion 7).

If, during implementation, any change appears to require touching
something on this list, work stops and the declaration is amended before
proceeding.

## 12. Sign request

To proceed to actual code:

- **"Sign as-is"** → I implement the sweep + tests, run dry-run against
  the preview database (synthetic data, expected to find no `auto_heal`
  candidates — proves wiring), summarize the diff, stop. **No
  production deploy. No --apply on prod. No Batch-2 action.**
- **"Sign with amendments: [paste]"** → I revise; you re-sign; then
  implement.
- **"Reject"** → tell me what to re-scope.

## 13. What this declaration deliberately does NOT do

- It does not deploy.
- It does not run `--apply` on any database.
- It does not modify alias / profile / intelligence / sender_vendor_map
  rows.
- It does not resume Batch-2.
- It does not extend the live-path guard (already done in Phase B).
- It does not implement §6.1 live-path symmetry (deferred).

Each of those is its own signed declaration after this one is signed,
implemented, dry-run-verified on prod, applied with `--max` limited
first, then applied unbounded.
