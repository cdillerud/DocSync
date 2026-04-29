# Workflow-Status Orphan Unstick — Targeted Promotion Declaration (CODE-CHANGE PLAN, NO CODE EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any code lands.
- Parent: §6.2 retroactive vendor-canonical self-heal (signed, applied,
  observed clean: 4 Mid America docs healed 2026-04-29T16:08:42Z–16:08:45Z).
- Out of scope (preserved): §6.1 live-path symmetry, §7
  alias/profile/intelligence cleanup, Smurfit `WROCKCP`/`WESTROCK`
  decision (excluded permanently from auto-heal scope), broader
  `workflow_status` normalization, any UI work, Batch-2 posting itself.

---

## 1. Goal

Promote exactly four `vendor_canonical`-healed Mid America docs into a
status combination that the `tier1_batch_runner.py select` selector
recognises. None of these docs are picked up today because their
`status`/`workflow_status` pair sits outside every selector tier:

| doc | current status | current workflow_status | reason invisible to selector |
|---|---|---|---|
| `c413fe62-7f99-4584-b56f-4d30bf8b173d` | `Completed` | `processed` | tier 3 needs `workflow_status ∈ {approved, ready_for_post}` |
| `d10f5242-0c8a-41fe-b713-e34223de0c52` | `Completed` | `processed` | same |
| `c10a8b04-a49f-46ac-a78e-a5b448891307` | `batch_parent` | `ready_for_post` | no tier accepts `status="batch_parent"` |
| `48a153f8-41c0-46bd-bc93-52e2cc8238e5` | `batch_parent` | `ready_for_post` | same |

After promotion, the four docs satisfy tier 1 (`status="ReadyForPost"`)
and become eligible for the existing tier1 candidate-selection /
dry-run / post pipeline.

The script is a one-shot operator-driven tool. Read-only by default.
`--apply` for the actual writes. Hard-coded to those 4 doc_ids only —
refuses any other id. Idempotent. Per-doc reversible.

This declaration does **NOT**:
- promote any other doc, ever, under any flag
- post anything to BC
- alter `vendor_canonical`, `bc_vendor_number`, or any vendor field
  (those were settled in §6.2)
- introduce a generalised "promote workflow_status" endpoint or button
- modify production source code (server.py, routers, services)

## 2. Files touched (exact)

| # | path | change kind | net effect |
|---|---|---|---|
| 1 | `backend/scripts/workflow_status_orphan_unstick.py` | new file (~220 LOC) | the unstick — read-only by default, `--apply` for writes, idempotent, refuses any doc_id outside the hard-coded set |
| 2 | `backend/tests/test_workflow_status_orphan_unstick.py` | new file | unit + integration coverage (Class A–D below) |

**No production source code is modified.** No new endpoints, no schema
changes, no env-flag changes, no telemetry-schema changes.
`workflow.status_promoted_for_batch2` is a fresh event name reserved
by this declaration; no live consumer reads it.

## 3. Eligibility (per-doc, hard-coded)

The script declares an `ALLOWED_DOC_IDS` constant containing exactly
these four UUIDs:

```python
ALLOWED_DOC_IDS = frozenset({
    "c413fe62-7f99-4584-b56f-4d30bf8b173d",
    "d10f5242-0c8a-41fe-b713-e34223de0c52",
    "c10a8b04-a49f-46ac-a78e-a5b448891307",
    "48a153f8-41c0-46bd-bc93-52e2cc8238e5",
})
```

Any `--apply --doc-id <X>` where `X ∉ ALLOWED_DOC_IDS` is rejected
with a hard error and a non-zero exit code. The set cannot be
extended via flag — only by editing the source file (which would
require a new signed declaration).

A doc qualifies for promotion in this run IFF **every one** of the
following is true. Anything weaker stays in the `manual_review`
bucket; anything ambiguous stays excluded.

1. `id ∈ ALLOWED_DOC_IDS`.
2. `document_type == "AP_Invoice"`.
3. `vendor_canonical == "Mid America Logistics Group LLC"` (exact —
   confirms §6.2 heal landed and was not reverted).
4. `bc_vendor_number == "MIDAMER"` (exact — same).
5. `vendor_match_method == "self_healed_bc_validation"` (exact —
   provenance confirms heal source).
6. `bc_purchase_invoice` is **null** (doc has not been posted yet).
7. `is_duplicate` is **not** True AND `duplicate_of_document_id`
   is **null** (don't promote duplicates).
8. The doc's current `(status, workflow_status)` pair matches the
   declared "from" pair for that doc (criterion 9). Mismatch ⇒
   `manual_review_unexpected_state`.
9. The exact "from → to" mapping is hard-coded:
   - `c413fe62`: `(Completed, processed) → (ReadyForPost, ready_for_post)`
   - `d10f5242`: `(Completed, processed) → (ReadyForPost, ready_for_post)`
   - `c10a8b04`: `(batch_parent, ready_for_post) → (ReadyForPost, ready_for_post)`
   - `48a153f8`: `(batch_parent, ready_for_post) → (ReadyForPost, ready_for_post)`

If criterion 8 fails on a given doc, that doc is reported
`manual_review_unexpected_state` and **not** touched. The other docs
proceed independently.

## 4. Exact fields updated (per promotion)

For each qualifying doc in `--apply` mode, the script performs ONE
Mongo update with these fields and **nothing else**:

```python
{
    "$set": {
        "status": "<target.status>",
        "workflow_status": "<target.workflow_status>",
        "promoted_for_batch2_at": "<iso8601 utc>",
        "promoted_for_batch2_source": "workflow_status_orphan_unstick_v1",
    },
    "$push": {
        "workflow_promotion_history": {
            "promoted_at": "<iso8601 utc>",
            "previous_status": <prior status>,
            "previous_workflow_status": <prior workflow_status>,
            "new_status": <target status>,
            "new_workflow_status": <target workflow_status>,
            "source": "workflow_status_orphan_unstick_v1",
            "run_id": "<uuid for this invocation>",
        }
    }
}
```

`workflow_promotion_history` is a fresh array carrying the FULL prior
values needed to revert this single doc's promotion. The reverse-path
uses the most-recent entry to restore prior state.

## 5. Exact event emitted (per promotion)

ONE `workflow_events` row per doc promoted:

```json
{
  "event_id": "<uuid>",
  "event_type": "workflow.status_promoted_for_batch2",
  "status": "completed",
  "source_service": "workflow_status_orphan_unstick",
  "timestamp": "<iso8601 utc>",
  "actor": null,
  "document_id": "<doc.id>",
  "payload": {
    "from": {
      "status": "<prior status>",
      "workflow_status": "<prior workflow_status>"
    },
    "to": {
      "status": "<target status>",
      "workflow_status": "<target workflow_status>"
    },
    "vendor_canonical": "Mid America Logistics Group LLC",
    "bc_vendor_number": "MIDAMER",
    "source": "workflow_status_orphan_unstick_v1",
    "run_id": "<run_id>"
  }
}
```

`run_id` lets you find every doc touched by a single invocation —
useful for bulk-revert if needed.

## 6. Exclusions / manual-review categorisation

The script produces a markdown report at
`/app/memory/WORKFLOW_STATUS_ORPHAN_UNSTICK_REPORT_<run_id>.md` with
per-doc disposition:

| bucket | meaning | action by script |
|---|---|---|
| `promoted` | passes all 9 criteria | promoted in `--apply` mode |
| `clean_already_promoted` | doc already at the target `(status, workflow_status)` (idempotency) | nothing |
| `manual_review_vendor_drift` | criterion 3/4/5 fails (heal regressed?) | flagged in report; refuses to promote |
| `manual_review_already_posted` | criterion 6 fails | flagged in report; refuses to promote |
| `manual_review_duplicate` | criterion 7 fails | flagged in report; refuses to promote |
| `manual_review_unexpected_state` | criterion 8 fails (status pair drifted) | flagged in report; refuses to promote |
| `rejected_unknown_doc_id` | `--doc-id` value not in `ALLOWED_DOC_IDS` | hard error, non-zero exit |

Any `manual_review_*` row blocks that single doc; the other 3 still
proceed independently.

## 7. Expected effect on the Batch-2 selector

Pre-promotion (current prod state):

| doc | tier hit | selector visibility |
|---|---|---|
| `c413fe62` | none | invisible |
| `d10f5242` | none | invisible |
| `c10a8b04` | none | invisible |
| `48a153f8` | none | invisible |

Post-promotion (predicted, dry-run will confirm):

| doc | tier hit | selector visibility |
|---|---|---|
| `c413fe62` | tier 1 (ReadyForPost gold) | visible |
| `d10f5242` | tier 1 | visible |
| `c10a8b04` | tier 1 | visible |
| `48a153f8` | tier 1 | visible |

After `--apply`, the next `tier1_batch_runner.py select` invocation
includes all 4 Mid America docs. Whether they are **posted** is a
separate signed step (the existing tier1_batch_runner `dry-run` then
`post --confirm` flow, with the 2 CREAT at_risk docs excluded via
`--exclude-ids`).

## 8. Rollback posture

| layer | rollback action | takes |
|---|---|---|
| Single doc | `--revert <doc_id>` reads most-recent `workflow_promotion_history` entry; restores `status` and `workflow_status` from `previous_*`; pops the entry; emits `workflow.status_promoted_for_batch2_reverted` | one Mongo update |
| Single run | `--revert-run <run_id>` queries `workflow_events` for `workflow.status_promoted_for_batch2` rows with that `run_id`; reverts each | one script invocation |
| All ever | `--revert-all` (only with explicit `--i-mean-it`) | bulk; logged |
| The tool itself | `git revert` of the new files; production unaffected | one commit |

`--apply` writes are wrapped in a per-doc try/except so a single
failure doesn't abort the run. Failures are logged with full context.

## 9. Tests (new file `backend/tests/test_workflow_status_orphan_unstick.py`)

### Class A — Eligibility classification (pure-function)
- A1 doc with all criteria met (each of the 4) → `promoted`
- A2 doc already at target (status=ReadyForPost, workflow_status=ready_for_post) → `clean_already_promoted`
- A3 doc with `vendor_canonical != "Mid America Logistics Group LLC"` → `manual_review_vendor_drift`
- A4 doc with `bc_purchase_invoice` set → `manual_review_already_posted`
- A5 doc marked duplicate → `manual_review_duplicate`
- A6 doc with unexpected `(status, workflow_status)` pair → `manual_review_unexpected_state`
- A7 attempting `--doc-id <unknown_uuid>` → `rejected_unknown_doc_id`, non-zero exit

### Class B — Dry-run mode
- B1 dry-run produces correct per-doc bucket dispositions
- B2 dry-run does NOT write to `hub_documents` or `workflow_events`
- B3 dry-run produces a markdown report at the expected path

### Class C — Apply mode
- C1 `--apply --doc-id <id>` writes target `status`+`workflow_status`, sets `promoted_for_batch2_at`, `promoted_for_batch2_source`, pushes a `workflow_promotion_history` entry
- C2 `--apply` emits exactly one `workflow.status_promoted_for_batch2` event per promoted doc with correct payload + run_id
- C3 `--apply` is idempotent: running twice on the same doc produces no second promotion (criterion: doc now at target ⇒ `clean_already_promoted`)
- C4 `--apply --doc-id <unknown_uuid>` raises before any DB call
- C5 each of the 4 hard-coded "from" pairs maps correctly to its declared "to" pair

### Class D — Revert mode
- D1 `--revert <doc_id>` restores `status` and `workflow_status` to `previous_*`
- D2 `--revert <doc_id>` pops the most-recent `workflow_promotion_history` entry
- D3 `--revert <doc_id>` emits `workflow.status_promoted_for_batch2_reverted`
- D4 `--revert-run <run_id>` reverts every doc touched by that run
- D5 `--revert <unknown_doc_id>` returns `reverted=False` with reason `doc_not_found` or `no_promotion_history` (no exception)

Pass criterion: every test green; no regression in existing tests
(including §6.2 sweep tests and sender-stamp guard tests).

## 10. Operator usage (CLI surface)

```
python /app/scripts/workflow_status_orphan_unstick.py
  # default — DRY RUN. Scans the 4 hard-coded doc_ids; classifies; writes report.

python /app/scripts/workflow_status_orphan_unstick.py --apply
  # APPLIES promotion to every doc in the `promoted` bucket (max 4).

python /app/scripts/workflow_status_orphan_unstick.py --apply --doc-id <id>
  # APPLIES promotion to ONE doc only. Rejects unknown ids.

python /app/scripts/workflow_status_orphan_unstick.py --revert <doc_id>
  # REVERT one doc's most-recent promotion.

python /app/scripts/workflow_status_orphan_unstick.py --revert-run <run_id>
  # REVERT every doc touched by one run_id.
```

Recommended first run sequence on prod:

1. Dry run → review the report. Confirm all 4 docs land in `promoted`
   with the declared "from → to" mapping.
2. `--apply --doc-id c413fe62-7f99-4584-b56f-4d30bf8b173d` (one doc).
3. Verify `tier1_batch_runner.py select` now picks up `c413fe62`.
4. `--apply --doc-id d10f5242-…`. Verify selector sees it.
5. `--apply --doc-id c10a8b04-…`. Verify.
6. `--apply --doc-id 48a153f8-…`. Verify.
7. Run the full `tier1_batch_runner.py select` once more → confirm
   all 4 Mid America docs in the candidate pool.
8. STOP. Batch-2 dry-run + post is a SEPARATE signed step.

Each step is independently reversible.

## 11. Out-of-scope fence (explicit)

This declaration MUST NOT:

- Modify any production source code (server.py, document_handlers.py,
  vendor_matching.py, routers/*, services/*, workflows/*).
- Modify any function signature.
- Modify the `vendor.canonical_self_healed` event schema or behaviour.
- Modify `vendor_aliases`, `vendor_invoice_profiles`,
  `vendor_intelligence_profiles`, `sender_vendor_map`, or any other
  vendor-learning collection.
- Promote any doc whose id is not in `ALLOWED_DOC_IDS`.
- Touch the 2 Smurfit docs (`bdeef718`, `6e9b6a78`) — permanently
  excluded from auto-heal scope by the previous decision.
- Touch any of the 11 cosmetic GROUPWA/SEAQUIS auto_heal candidates.
- Touch any of the 9 `manual_review_extraction_vs_bc_disagreement`
  docs.
- Touch the 5 protected duplicates (`2606d9b4`, `f4a446d7`,
  `2619152e`, `c69dfd94`, `0bbdd46d`, `5eecd131`, `6d29133c`).
- Run §7 alias/profile/intelligence cleanup.
- Modify `services/document_handlers.py:1204` (still deferred — §6.1).
- Resume Batch-2 posting.
- Touch the frontend.
- Add new HTTP endpoints.

If, during implementation, any change appears to require touching
something on this list, work stops and the declaration is amended
before proceeding.

## 12. Sign request

To proceed to actual code:

- **"Sign as-is"** → I implement the script + tests, run the dry-run
  against the preview database (synthetic data, expected to find no
  `promoted` candidates because the 4 doc_ids only exist in prod —
  proves wiring), summarise the diff and tests, stop. **No
  production deploy. No --apply on prod. No Batch-2 action.**
- **"Sign with amendments: [paste]"** → I revise; you re-sign; then
  implement.
- **"Reject"** → tell me what to re-scope.

## 13. What this declaration deliberately does NOT do

- It does not deploy.
- It does not run `--apply` on any database.
- It does not modify alias / profile / intelligence /
  sender_vendor_map rows.
- It does not resume Batch-2.
- It does not extend §6.2 sweep eligibility.
- It does not implement §6.1 live-path symmetry (deferred).
- It does not introduce a "Promote to Ready for Post" UI button.
- It does not create a generalised workflow_status promotion endpoint.

Each of those is its own signed declaration after this one is signed,
implemented, dry-run-verified on prod, applied per-doc, and observed
clean.
