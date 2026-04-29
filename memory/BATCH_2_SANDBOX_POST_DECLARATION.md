# Batch-2 Sandbox Post — Plan-Only Declaration (NO POSTING EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any post.
- Parent chain:
  - §6.2 retroactive vendor-canonical self-heal (signed, applied, observed clean — 4 docs healed)
  - δ workflow-status orphan unstick (signed, applied, observed clean — 4 docs promoted)
- Out of scope (preserved): prod BC writes, Smurfit `WROCKCP`/`WESTROCK`,
  BC vendor master `displayName` cleanup (the 9 disagreement cluster),
  cosmetic `GROUPWA`/`SEAQUIS` normalizations, broader `doc_re_resolve`
  contamination cleanup, alias/profile/intelligence cleanup (§7),
  §6.1 live-path symmetry, frontend work.

---

## 1. Goal

Execute Batch-2 against the **BC sandbox** using the existing
`tier1_batch_runner.py` flow on its current candidate pool of 10 docs
(0 at_risk, 10 safe). This is the commercial vindication of §6.2 + δ:
the first batch where Mid America docs (specifically `48a153f8` and
`d10f5242`) actually flow through to BC.

The script is **already written** (`backend/scripts/tier1_batch_runner.py`,
existing). This declaration scopes the operator playbook only — no
new code, no modifications to the runner, no mutation of any
production source file, no env-flag changes.

The two remaining promoted Mid America docs (`c10a8b04` and
`c413fe62`) are queued for Batch-3 as the candidate pool naturally
turns over.

## 2. Scope

### In scope

- One invocation of `tier1_batch_runner.py preflight` (read-only).
- One invocation of `tier1_batch_runner.py select` (read-only).
- One invocation of `tier1_batch_runner.py dry-run` (read-only —
  preflight + select + per-doc validation simulation; no BC writes).
- One invocation of `tier1_batch_runner.py post --confirm` against the
  **BC sandbox endpoint only**. Default candidate pool, no
  `--exclude-ids` (because at_risk=0).
- Per-doc result capture, BC PI number capture, elapsed-time capture,
  worksheet append at the runner's existing `WORKSHEET_PATH`.

### Explicitly out of scope

- Any post against the prod BC tenant.
- Any modification to `tier1_batch_runner.py` itself.
- Any modification to `vendor_canonical_self_heal_sweep.py`,
  `workflow_status_orphan_unstick.py`, or any other script.
- Any frontend work.
- Any new HTTP endpoint or env-flag.
- Any vendor-master, alias, or profile cleanup.
- Any retroactive doc-state mutation outside the runner's normal
  post-success update (`bc_purchase_invoice` set on the doc on P-bucket).
- Healing the 2 Smurfit docs (permanently excluded).
- Healing the 11 cosmetic GROUPWA/SEAQUIS docs.
- Touching the 9 `manual_review_extraction_vs_bc_disagreement` docs.
- Posting `c10a8b04` or `c413fe62` in this batch (they're outside
  the current top-10 selector pool; they post in Batch-3).

## 3. Pre-post gates

All three gates must pass within the same operator session before
`post --confirm` is invoked. If any gate fails, the post is aborted
without contacting BC.

### Gate G1 — preflight passes

```
docker compose exec backend python /app/scripts/tier1_batch_runner.py preflight
```

Expected: stdout shows `PHASE 1 — PREFLIGHT` with all probes passing
(BC config loaded, BC vendor cache reachable, Mongo reachable, etc.).
A non-zero exit code aborts.

### Gate G2 — fresh dry-run shows 0 at_risk and clean output

```
docker compose exec backend python /app/scripts/tier1_batch_runner.py dry-run
```

Expected:
- `Selected 10 candidates.`
- Per-doc dry-run validation shows ZERO `F-DATA` / `F-RULE` /
  `F-CONFIG` predictions.
- A fresh `vendor_mismatch_sweep` confirms `at_risk=0` (re-run
  separately if the dry-run output doesn't surface this directly).

If any candidate dry-run shows a predicted `F-bucket` outcome OR if
`at_risk > 0`, the post is aborted; the operator either excludes the
problem doc(s) via `--exclude-ids` or files a new declaration.

### Gate G3 — BC sandbox endpoint reachable

The preflight covers part of this (BC OAuth + vendor cache fetch).
Additionally, the dry-run's per-doc validation will fail loudly with
`F-NETWORK` if the sandbox endpoint stops responding mid-run.

If preflight passes but dry-run shows any `F-NETWORK` predictions,
the operator pauses and re-checks BC sandbox health before posting.

## 4. Stop conditions during posting

The runner already implements these (see
`scripts/tier1_batch_runner.py:691-707`) — operator relies on them
unmodified:

### S1 — F-BUG hard stop

If any single doc's response classifies as `F-BUG` (programming
defect: missing fields the runner should have populated, KeyError,
unexpected exception shape), the runner **prints the abort message
and breaks the post loop immediately**. Remaining candidates are
NOT posted. Operator must investigate before re-running.

### S2 — Repeatable malformed posting behaviour

If two consecutive non-success buckets share the **same response
signature** (HTTP code + error code/family), the runner aborts
("repeatable malformed posting behavior detected"). Prevents
hammering BC with the same broken request shape.

### S3 — Pass criterion

After the run completes, `phase_summary` enforces:

> ≥70% of attempted posts in (P1+P2+POLICY) with zero F-BUG → ✅ TIER 1 VIABLE
> otherwise → ❌ NOT YET

If the result is `❌ NOT YET`, **do not run another batch** until the
worksheet is reviewed and a follow-up declaration scopes the fix.

## 5. Reporting

The runner already produces all of this. Operator captures it for the
sign-off report:

### Per-doc

For each candidate, the post phase prints:

```
      → bucket=<P1|P2|P1-POLICY|P2-POLICY|F-DUP|F-CONFIG|F-AUTH|F-REF|F-DATA|F-RULE|F-NETWORK|F-BUG>
        http=<status>  bc_no=<BC PI number or '-'>  (<elapsed_ms> ms)
```

Plus an entry in the markdown worksheet at the runner's
`WORKSHEET_PATH` (carries doc_id, vendor, invoice number, total,
duplicate-check, bucket, BC PI number, HTTP status, elapsed ms,
detail snippet).

### Batch summary (Phase 5)

The runner prints:

- `Posted: <n>` total attempted
- Per-bucket counts (`P1`, `P2`, `P1-POLICY`, `P2-POLICY`, `F-DUP`,
  `F-CONFIG`, `F-AUTH`, `F-REF`, `F-DATA`, `F-RULE`, `F-NETWORK`,
  `F-BUG`)
- Pass count vs threshold (`≥ ⌈70% of n⌉`)
- `RESULT: ✅ TIER 1 VIABLE` or `❌ NOT YET`
- Worksheet path

The operator additionally captures:

- Wall-clock start and end timestamps for the full batch.
- A copy of the worksheet pulled out of the container to host
  `./prod_reports/`.

## 6. Rollback / safety posture

| layer | rollback action | notes |
|---|---|---|
| Per-doc post failure | None needed — `bc_purchase_invoice` is only written on a P-bucket. F-bucket leaves the doc as it was. | Existing runner behaviour. |
| Per-doc post success but later regret | Manual: invalidate the BC PI in the BC sandbox UI; clear `bc_purchase_invoice` on the doc via a separate signed declaration if needed. | Sandbox PIs are cheap to discard; this is acceptable. |
| Whole-batch rollback | Not provided. Posting is intentionally one-way to BC. | If the batch needs reversal, that's a sandbox-cleanup declaration of its own. |
| Tier-1-not-viable verdict | No more batches until the worksheet is reviewed and a follow-up declaration scopes either fixes or `--exclude-ids` for the failing class. | Enforced by operator discipline. |
| `--apply` semantics | The runner's `post` subcommand requires `--confirm`. The dry-run subcommand does not write. | Existing runner behaviour. |

The runner is already wired to write `bc_purchase_invoice` on the doc
only after BC returns success (i.e. P-bucket). Failure leaves the doc
untouched — perfectly safe.

## 7. Expected effect on the 2 not-in-top-10 Mid America docs

`c10a8b04` (M10208, $250) and `c413fe62` (M10177, $250) are correctly
promoted (`status=ReadyForPost`, `workflow_status=ready_for_post`,
`vendor_canonical=Mid America Logistics Group LLC`,
`bc_vendor_number=MIDAMER`, `vendor_match_method=self_healed_bc_validation`)
but ranked outside the current top-10 by `created_utc` due to newer AP
docs flowing in. They are **not posted** in Batch-2.

After Batch-2 posts the current 10:

- `48a153f8` (newest Mid America) → posted in Batch-2
- `d10f5242` → posted in Batch-2
- The 2 PROGRESSIVE / 1 Tomahawk / 1 CITICARGO / 2 Tumalo Creek / 1
  Mexus docs → posted in Batch-2
- `c10a8b04` and `c413fe62` → eligible for Batch-3 once the freshly
  posted docs are removed from the candidate pool (post sets
  `bc_purchase_invoice`, dropping them from the selector's
  `bc_purchase_invoice in (None, "", missing)` filter)

A `select` re-run after Batch-2 posts is the verification that they
re-surface. No code change required; this is purely the natural
selector turnover.

If the operator wants to post all 4 Mid America in Batch-2 instead,
the cleanest path is a small follow-up declaration to add a
`--include-ids` flag (or to bump `BATCH_LIMIT` for a single run). NOT
in scope for this declaration.

## 8. Operator command sequence

All commands run on the prod VM. Container path is `/app/scripts/`.

### Phase A — Pre-post gates (read-only, no BC writes)

```bash
# 1. Preflight (G1)
docker compose exec backend python /app/scripts/tier1_batch_runner.py preflight

# 2. Dry-run (G2 + part of G3)
docker compose exec backend python /app/scripts/tier1_batch_runner.py dry-run

# 3. Fresh mismatch sweep — confirm at_risk == 0
docker compose exec backend python /app/scripts/vendor_mismatch_sweep.py
docker compose cp backend:/app/memory/. ./prod_reports/
# Open the new VENDOR_MISMATCH_SWEEP.md, confirm Batch-2 impact section
# shows "0 at_risk".

# 4. STOP HERE. Operator reviews:
#    - preflight passed (no F probes)
#    - dry-run shows 10 candidates, zero predicted F-buckets
#    - mismatch sweep at_risk = 0
#    - all 4 expected Mid America docs are still promoted
#      (re-grep the select output for c413fe62/d10f5242/c10a8b04/48a153f8)
```

If anything in Phase A fails, **do not run Phase B**. Capture the
failure context, file a follow-up declaration, sign, and only then
return to Phase A from the top.

### Phase B — Sandbox post (the actual write to BC)

Only proceed if Phase A is fully clean.

```bash
# Capture wall-clock start
date -u +"%Y-%m-%dT%H:%M:%SZ"

# 5. Post — sandbox tenant, --confirm, default 10-doc pool, no exclusions
docker compose exec backend python /app/scripts/tier1_batch_runner.py post --confirm

# Capture wall-clock end
date -u +"%Y-%m-%dT%H:%M:%SZ"

# 6. Pull the worksheet
docker compose cp backend:/app/memory/. ./prod_reports/
ls -lt ./prod_reports/TIER1_BATCH_WORKSHEET*.md | head -1
cat $(ls -t ./prod_reports/TIER1_BATCH_WORKSHEET*.md | head -1)

# 7. Verify the 2 Mid America docs got BC PI numbers
docker compose exec backend bash -lc 'cat > /tmp/verify_batch2.py << "PYEOF"
import asyncio, os, json
from motor.motor_asyncio import AsyncIOMotorClient
async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for did in ["48a153f8-41c0-46bd-bc93-52e2cc8238e5",
                "d10f5242-0c8a-41fe-b713-e34223de0c52"]:
        d = await db.hub_documents.find_one({"id": did}, {"_id":0,
            "id":1,"status":1,"workflow_status":1,"bc_purchase_invoice":1})
        print(json.dumps(d, indent=2, default=str))
asyncio.run(go())
PYEOF
python /tmp/verify_batch2.py'

# 8. STOP. Do not run another batch. Review summary first.
```

### Phase C — Post-batch review (mandatory before any further posting)

The operator reviews the runner's `RESULT` line + the worksheet:

- ✅ `TIER 1 VIABLE` → file the result, sign next-step declaration
  (e.g. Batch-3 to mop up `c10a8b04` and `c413fe62`).
- ❌ `NOT YET` → do not run another batch. Diagnose via the worksheet's
  per-doc detail snippet, file a follow-up declaration scoping the
  fix, sign, then re-attempt.

## 9. Sign request

To proceed to actual execution:

- **"Sign as-is"** → I have nothing to implement (no new code; runner
  is already in place). I just hand you Phase A as the next operator
  step, you run it, paste back the output, I evaluate G1/G2/G3, then
  we sign Phase B separately. **Two-step signing**: this declaration
  signs Phase A; a tiny follow-up sign confirms Phase B (the actual
  post) only after Phase A is clean.
- **"Sign with amendments: [paste]"** → I revise; you re-sign.
- **"Reject"** → re-scope direction.

The two-step sign is intentional: Phase A is read-only and cheap;
Phase B writes to BC and benefits from a fresh look at the gate
output before pulling the trigger.

## 10. What this declaration deliberately does NOT do

- It does not modify `tier1_batch_runner.py`.
- It does not introduce a `--halt-on-failure` flag (runner already
  has F-BUG and repeatable-malformed halts).
- It does not introduce `--include-ids` (so `c10a8b04` / `c413fe62`
  wait for Batch-3).
- It does not implement a Batch-3 plan. Batch-3 is its own signed
  declaration after Batch-2 lands clean.
- It does not address Smurfit, GROUPWA cosmetics, the 9 disagreement
  cluster, alias/profile cleanup, or any §6.1/§7 deferral.
- It does not run anything against prod BC.
- It does not run anything against the BC sandbox until **two** sign
  steps have landed (this declaration + the Phase-B confirmation).

Each deferred item is its own signed declaration after this one is
complete and observed clean.
