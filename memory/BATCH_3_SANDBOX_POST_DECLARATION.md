# Batch-3 Sandbox Post — Plan-Only Declaration (NO POSTING EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature before any post.
- Phase posture: Phase 1 — AP Hardening and Controlled Rollout.
  Phase 3 refactor remains paused. Sales / auth / broad refactor are
  not in scope.
- Parent chain:
  - §6.2 retroactive vendor-canonical self-heal (signed, applied,
    observed clean).
  - δ workflow-status orphan unstick (signed, applied, observed clean).
  - Sender-stamp guard (signed, applied, observed clean).
  - Batch-2 sandbox post attempt (executed; produced at least one
    successful Mid America BC sandbox PI; surfaced three follow-up
    classes (SMC structural rejection, SC Warehouses / YANDELL
    contamination, capacity/timeout under live workload); execution
    was deliberately stopped when backend contention made preflight
    unreliable).

## 0. Out-of-scope fence (explicit, NON-NEGOTIABLE)

This batch does **not** touch any of the following. They are tracked
as separate disposition items each requiring their own signed
declaration when prioritized:

- **SMC vendor-record / Buy-from Vendor No. structural rejection** —
  separate investigation. SMC docs in the candidate pool MUST be
  excluded via `--exclude-ids` if they are still promoted at
  execution time.
- **SC Warehouses / YANDELL mismatch contamination** — separate
  cleanup. Any SC Warehouses / YANDELL doc still showing in the
  candidate pool MUST be excluded via `--exclude-ids`.
- **CITICARGO** — separate investigation. Excluded from this batch.
- **Smurfit `WROCKCP` / `WESTROCK` ambiguity** — permanently excluded
  per Batch-2 declaration; no change.
- **Cosmetic GROUPWA / SEAQUIS normalization** — permanently
  excluded; no change.
- **Mismatch-sweep heuristic tightening** — out of scope. We use the
  current sweep as-is.
- **Backend capacity engineering** (worker counts, connection pools,
  Gemini quota changes, async batch sizing, caching layers) — out of
  scope. We respect current capacity; we do not engineer around it.
- **Any production BC posting** — sandbox tenant only.
- **Frontend work** — out of scope.
- **Any new endpoint or env-flag** — out of scope.
- **Any retroactive doc-state mutation** outside the runner's normal
  post-success update (`bc_purchase_invoice` set on the doc on
  P-bucket).
- **Any vendor-master / alias / profile / intelligence cleanup**
  (§7) — out of scope.
- **§6.1 live-path symmetry** — out of scope.

If any of the above unexpectedly enters the runner's selector pool at
execution time, the operator MUST exclude those doc IDs via
`--exclude-ids`. The batch does not heal them, does not investigate
them, does not work around them.

## 1. Goal

Execute Batch-3 against the **BC sandbox** using the existing
`tier1_batch_runner.py` flow on its **then-current** candidate pool.
The intent is to make AP sandbox posting **repeatable and safe** —
i.e. to demonstrate that, after the Batch-2 lessons, we can run a
full Phase-A → Phase-B cycle without re-tripping any of the surfaced
follow-up classes and without hammering BC under contention.

Mid America residue handling: any clean Mid America docs that
naturally appear in the runner's candidate pool at execution time
SHOULD be included. We do **not** force-include Mid America docs
that fall outside the runner's natural selector window. We do not
add a `--include-ids` flag; we do not bump `BATCH_LIMIT`.

The script is **already written**
(`backend/scripts/tier1_batch_runner.py`). This declaration scopes
the operator playbook only — no new code, no modifications to the
runner, no mutation of any production source file, no env-flag
changes.

## 2. Scope

### In scope

- One invocation of `tier1_batch_runner.py preflight` (read-only).
- One invocation of `tier1_batch_runner.py select` (read-only).
- One invocation of `vendor_mismatch_sweep.py` (read-only).
- A **backend-not-throttled probe** (§3 Gate G0) before any of the
  above are trusted. Read-only; no DB writes, no BC writes.
- A **candidate-pool snapshot** captured to `prod_reports/` for
  audit, including per-doc vendor + bc_vendor_number + workflow_status
  + bc_purchase_invoice.
- One invocation of `tier1_batch_runner.py dry-run` (read-only —
  preflight + select + per-doc validation simulation; no BC writes).
- One invocation of `tier1_batch_runner.py post --confirm` against
  the **BC sandbox endpoint only**, with `--exclude-ids` populated
  by every doc ID belonging to a known follow-up class (§0 fence)
  that is still in the pool at execution time.
- Per-doc result capture, BC PI number capture, elapsed-time capture,
  worksheet append at the runner's existing `WORKSHEET_PATH`.
- Wall-clock start/end timestamps for the batch.

### Explicitly out of scope

Everything in §0. Plus:

- Any post against the prod BC tenant.
- Any modification to `tier1_batch_runner.py`, the mismatch sweep,
  the canonical self-heal, or the orphan unstick scripts.
- Any deferred Mid America force-inclusion logic.
- Any Batch-4 planning. A Batch-4 declaration is filed separately
  after Batch-3 lands clean.

## 3. Pre-post gates

All gates must pass within the **same operator session** before
`post --confirm` is invoked. If any gate fails, the post is aborted
without contacting BC. Gate G0 is new for Batch-3.

### Gate G0 — backend not throttled (NEW for Batch-3)

Before trusting preflight or any other read of state, we must
verify the backend is not under contention. Batch-2 surfaced a
posture where preflight itself became unreliable while the backend
was Gemini-throttled. Posting under that posture is unsafe.

The operator captures:

```bash
# G0.a — last 200 backend log lines should NOT show:
#   - any RESOURCE_EXHAUSTED in the last 5 minutes
#   - any sustained "503" / "timeout" / "queue full" / "throttle"
#     pattern
#   - any preflight or batch-runner subprocess wedged > 60s
docker compose logs --tail=200 backend | tail -n 200

# G0.b — backend health / capacity probe (existing endpoint;
# read-only):
docker compose exec backend curl -s -o /dev/null -w "http=%{http_code} t_total=%{time_total}\n" \
    http://localhost:8001/api/health
# Expected: http=200, t_total well under 2.0 s.
# If t_total > 2.0 s OR http != 200 → ABORT (do not run preflight).

# G0.c — quick Mongo round-trip (read-only):
docker compose exec backend python -c "
import asyncio, os, time
from motor.motor_asyncio import AsyncIOMotorClient
async def go():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    t0 = time.time()
    n = await db.hub_documents.estimated_document_count()
    print(f'mongo count={n} dt={time.time()-t0:.2f}s')
asyncio.run(go())
"
# Expected: dt well under 1.0 s.
# If dt > 1.0 s → ABORT (Mongo / load issue; do not proceed).
```

If any sub-probe fails, **stop here**. File a one-line operator note
("Batch-3 G0 abort: <reason>"), wait for the contention to clear
naturally (no engineering changes — that is out of scope), and
re-run G0 from the top in the next session.

### Gate G1 — preflight passes

```bash
docker compose exec backend python /app/scripts/tier1_batch_runner.py preflight
```

Expected: stdout shows `PHASE 1 — PREFLIGHT` with all probes passing
(BC config loaded, BC vendor cache reachable, Mongo reachable,
runner-internal config sanity). A non-zero exit code aborts. Latency
is observed alongside the success/fail signal — if preflight takes
materially longer than the Batch-2 baseline (operator judgement),
treat that as a soft G0 regression and re-run G0.

### Gate G2 — fresh dry-run shows 0 unexpected failures and clean output

```bash
docker compose exec backend python /app/scripts/tier1_batch_runner.py dry-run
```

Expected:
- `Selected N candidates.` (whatever the runner's natural batch size
  produces — we do not pre-commit to a number).
- Per-doc dry-run validation predicts ZERO `F-BUG` outcomes.
- Per-doc dry-run validation may legitimately predict `F-DATA` /
  `F-RULE` / `F-CONFIG` for known follow-up classes (SMC, SC
  Warehouses / YANDELL, CITICARGO). Those doc IDs are recorded for
  the `--exclude-ids` list.
- A fresh `vendor_mismatch_sweep` confirms `at_risk == 0` for
  everything **after** subtracting the §0 known-class IDs.

If any candidate dry-run shows a predicted `F-BUG` outcome, the post
is aborted. F-BUG is a programming defect by definition; it is
investigated under a separate declaration before any further posting.

### Gate G3 — candidate-pool snapshot recorded

```bash
docker compose exec backend python /app/scripts/tier1_batch_runner.py select \
  > /tmp/batch3_pool_snapshot.txt
docker compose cp backend:/tmp/batch3_pool_snapshot.txt ./prod_reports/
```

The operator reviews the snapshot and confirms:

- No SMC, SC Warehouses / YANDELL, or CITICARGO doc is left
  un-excluded.
- All Mid America docs in the pool are correctly promoted
  (`status=ReadyForPost`, `workflow_status=ready_for_post`,
  `vendor_match_method=self_healed_bc_validation` or equivalent
  clean tag), and have `bc_purchase_invoice` empty (i.e. they have
  not been previously posted).
- No new `at_risk` candidate — i.e. no doc that the mismatch sweep
  did not have a chance to evaluate before this snapshot.

If the snapshot shows a new `at_risk` candidate that the sweep
missed, **abort**. The mismatch-sweep is treated as the canonical
gate; if a doc bypasses it, that is a sweep concern (out of scope
for this batch — file a separate declaration).

### Gate G4 — BC sandbox endpoint reachable

Preflight covers part of this (BC OAuth + vendor cache fetch). Dry-run
covers the rest (per-doc validation will fail loudly with `F-NETWORK`
if sandbox endpoint stops responding mid-run). Operator does not run
extra BC probes outside the runner.

If preflight passes but dry-run shows any `F-NETWORK` predictions on
candidates that should otherwise post cleanly, the operator pauses
and re-checks BC sandbox health (out of band) before posting.

## 4. Stop conditions during posting

The runner already implements the F-BUG and repeatable-malformed
halts. The operator additionally enforces two new aborts for
Batch-3.

### S1 — F-BUG hard stop (existing runner behaviour)

If any single doc's response classifies as `F-BUG`, the runner
**prints the abort message and breaks the post loop immediately**.
Remaining candidates are NOT posted. Operator stops, captures the
worksheet, files a follow-up declaration before any further
posting.

### S2 — Repeatable malformed posting behaviour (existing runner behaviour)

If two consecutive non-success buckets share the **same response
signature** (HTTP code + error code/family), the runner aborts. The
operator does not override this.

### S3 — Contention re-emergence (NEW for Batch-3)

If, during the post loop, any single per-doc post latency spikes
materially above the Batch-2 baseline (operator judgement; rough
threshold: 2× the median per-doc elapsed observed earlier in the
same run), the operator pauses, manually re-runs G0, and either
resumes (if G0 still passes) or aborts (if G0 now fails). This
guards against attempting to post into a now-throttled backend.

The operator does NOT modify the runner to enforce S3 mechanically.
S3 is operator-driven, by design — capacity engineering is out of
scope.

### S4 — New at_risk candidate (NEW for Batch-3)

If, between dry-run and post, any new `at_risk` candidate could
have entered the pool (e.g. an inbound document was promoted in the
last few minutes and shows as `at_risk` under a fresh mismatch
sweep), abort. Re-run from G0 in the next session.

In practice: the operator MUST not let more than ~5 minutes elapse
between G3 (snapshot) and Phase B (post). If more time elapses, a
fresh G2 + G3 is required.

### S5 — Pass criterion

After the run completes, `phase_summary` enforces:

> ≥70% of attempted posts in (P1+P2+POLICY) with zero F-BUG → ✅ TIER 1 VIABLE
> otherwise → ❌ NOT YET

If the result is `❌ NOT YET`, **do not run another batch** until the
worksheet is reviewed and a follow-up declaration scopes the fix.

## 5. Reporting

The runner already produces all of this. Operator captures it for
the sign-off report.

### Per-doc

```
      → bucket=<P1|P2|P1-POLICY|P2-POLICY|F-DUP|F-CONFIG|F-AUTH|F-REF|F-DATA|F-RULE|F-NETWORK|F-BUG>
        http=<status>  bc_no=<BC PI number or '-'>  (<elapsed_ms> ms)
```

Plus an entry in the markdown worksheet at the runner's
`WORKSHEET_PATH` (carries doc_id, vendor, invoice number, total,
duplicate-check, bucket, BC PI number, HTTP status, elapsed ms,
detail snippet).

### Batch summary (Phase 5 of the runner)

The runner prints:

- `Posted: <n>` total attempted
- Per-bucket counts (`P1`, `P2`, `P1-POLICY`, `P2-POLICY`, `F-DUP`,
  `F-CONFIG`, `F-AUTH`, `F-REF`, `F-DATA`, `F-RULE`, `F-NETWORK`,
  `F-BUG`)
- Pass count vs threshold (`≥ ⌈70% of n⌉`)
- `RESULT: ✅ TIER 1 VIABLE` or `❌ NOT YET`
- Worksheet path

### Operator-captured (in addition to the runner)

- Wall-clock start and end timestamps for the full batch.
- Median and max per-doc elapsed (eyeballed from the per-doc lines).
- A copy of the worksheet pulled out of the container to host
  `./prod_reports/`.
- The `batch3_pool_snapshot.txt` already pulled from G3.
- The operator's S3 / S4 notes if any were triggered (timestamp +
  what was observed + whether the run continued or aborted).
- **Next-state selector pool**: a one-line note of which doc IDs
  remain in the natural selector pool *after* this batch (i.e. those
  that did NOT get a `bc_purchase_invoice` written and so will
  re-surface in the next `select` call). This feeds the Batch-4
  declaration.

## 6. Rollback / safety posture

| layer | rollback action | notes |
|---|---|---|
| Per-doc post failure | None needed — `bc_purchase_invoice` is only written on a P-bucket. F-bucket leaves the doc untouched. | Existing runner behaviour. |
| Per-doc post success but later regret | Manual: invalidate the BC PI in the BC sandbox UI; clear `bc_purchase_invoice` on the doc via a separate signed declaration if needed. | Sandbox PIs are cheap to discard; this is acceptable. |
| Whole-batch rollback | Not provided. Posting is intentionally one-way to BC. | If reversal is needed, file a sandbox-cleanup declaration. |
| `❌ NOT YET` verdict | No more batches until the worksheet is reviewed and a follow-up declaration scopes either fixes or `--exclude-ids` for the failing class. | Enforced by operator discipline. |
| `--apply` / `--confirm` semantics | The runner's `post` subcommand requires `--confirm`. The dry-run subcommand does not write. | Existing runner behaviour. |
| Backend contention mid-run (S3 abort) | Phase B partial: docs already in P-bucket keep their BC PI numbers; remaining candidates are not posted. The S3 abort is treated as a clean partial — operator files a one-line note and either re-runs from G0 in a fresh session or files a follow-up declaration. | Same as F-BUG partial behaviour. |

The runner is already wired to write `bc_purchase_invoice` on the
doc only after BC returns success (i.e. P-bucket). Failure leaves
the doc untouched — perfectly safe.

## 7. Mid America residue handling

Per the user's signed direction:

- Any remaining clean Mid America docs that **are** in the natural
  selector pool at execution time SHOULD be included.
- Mid America docs that **are not** in the natural selector pool at
  execution time MUST NOT be force-included. We do not add
  `--include-ids`. We do not bump `BATCH_LIMIT`. We do not lower
  the selector ranking threshold.
- If the natural selector pool yields zero Mid America docs at
  execution time, that is acceptable — Batch-3 is judged on its
  posture, not on Mid America coverage.

## 8. Operator command sequence

All commands run on the prod VM. Container path is `/app/scripts/`.
Two-phase sequence with an explicit sign gate between A and B.

### Phase A — Pre-post gates (read-only, no BC writes)

```bash
# G0 — backend-not-throttled probe
docker compose logs --tail=200 backend | tail -n 200
docker compose exec backend curl -s -o /dev/null -w "http=%{http_code} t_total=%{time_total}\n" \
    http://localhost:8001/api/health
docker compose exec backend python -c "
import asyncio, os, time
from motor.motor_asyncio import AsyncIOMotorClient
async def go():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    t0 = time.time()
    n = await db.hub_documents.estimated_document_count()
    print(f'mongo count={n} dt={time.time()-t0:.2f}s')
asyncio.run(go())
"
# All three must look healthy (no RESOURCE_EXHAUSTED, http=200, t_total<2s, mongo dt<1s).
# If anything is off, STOP. Do not proceed. Wait, re-run G0 in next session.

# G1 — preflight
docker compose exec backend python /app/scripts/tier1_batch_runner.py preflight

# G2 — dry-run + mismatch sweep
docker compose exec backend python /app/scripts/tier1_batch_runner.py dry-run
docker compose exec backend python /app/scripts/vendor_mismatch_sweep.py
docker compose cp backend:/app/memory/. ./prod_reports/

# G3 — candidate-pool snapshot
docker compose exec backend python /app/scripts/tier1_batch_runner.py select \
  > /tmp/batch3_pool_snapshot.txt
docker compose cp backend:/tmp/batch3_pool_snapshot.txt ./prod_reports/

# Operator review checklist (manual):
#   - G0 clean
#   - G1 preflight all green
#   - G2 dry-run: 0 predicted F-BUG; SMC / SC Warehouses-YANDELL /
#     CITICARGO doc IDs noted for --exclude-ids
#   - G2 mismatch sweep: at_risk == 0 (after subtracting §0 IDs)
#   - G3 snapshot reviewed; no surprise at_risk candidates
#
# Compose the --exclude-ids list. Format:
#   --exclude-ids "<id1>,<id2>,<id3>"
#
# STOP HERE. Do NOT proceed to Phase B without operator sign-off.
```

If anything in Phase A fails, **do not run Phase B**. Capture the
failure context, file a follow-up declaration, sign, and only then
return to Phase A from the top.

### Sign gate — between Phase A and Phase B (MANDATORY)

After Phase A is clean, the operator pastes the Phase A outputs +
the proposed `--exclude-ids` list back to the agent. The agent
evaluates G0 / G1 / G2 / G3 against this declaration's criteria and
emits **one of**:

- ✅ `Phase B clear — proceed with --exclude-ids "<list>"`
- ❌ `Phase B blocked — reason: <reason>`

This is the second sign gate. The operator does not run Phase B
until that explicit clearance is received.

The two-step sign is intentional: Phase A is read-only and cheap;
Phase B writes to BC and benefits from a fresh look at the gate
output before pulling the trigger.

### Phase B — Sandbox post (the actual write to BC)

Only proceed if Phase A is fully clean **and** the sign-gate clearance
has been received.

```bash
# Capture wall-clock start
date -u +"%Y-%m-%dT%H:%M:%SZ"

# Post — sandbox tenant, --confirm, with --exclude-ids populated
# from Phase A's known-class list.
docker compose exec backend python /app/scripts/tier1_batch_runner.py post \
    --confirm \
    --exclude-ids "<paste-list-from-Phase-A-sign-gate>"

# Capture wall-clock end
date -u +"%Y-%m-%dT%H:%M:%SZ"

# Pull the worksheet
docker compose cp backend:/app/memory/. ./prod_reports/
ls -lt ./prod_reports/TIER1_BATCH_WORKSHEET*.md | head -1
cat $(ls -t ./prod_reports/TIER1_BATCH_WORKSHEET*.md | head -1)

# Verify any expected Mid America docs got BC PI numbers (if any
# were in the natural pool). The operator inspects the worksheet
# directly; no script changes.

# STOP. Do not run another batch. Phase C review is mandatory.
```

### Phase C — Post-batch review (mandatory before any further posting)

The operator reviews the runner's `RESULT` line + the worksheet:

- ✅ `TIER 1 VIABLE` → file the result, sign next-step declaration
  (Batch-4 if more candidates remain; or a stand-down note if the
  pool is exhausted).
- ❌ `NOT YET` → do not run another batch. Diagnose via the
  worksheet's per-doc detail snippet, file a follow-up declaration
  scoping the fix, sign, then re-attempt.

Phase C report bundle (committed to `prod_reports/`):

- `tier1_batch_runner` per-doc stdout
- `TIER1_BATCH_WORKSHEET*.md`
- `batch3_pool_snapshot.txt`
- `VENDOR_MISMATCH_SWEEP.md` (the one captured at G2)
- Wall-clock start/end + median/max per-doc elapsed
- S3 / S4 abort notes (if any)
- Next-state selector pool one-liner

## 9. Sign request

To proceed to actual execution:

- **"Sign as-is"** → I have nothing to implement (no new code; runner
  is already in place). I just hand you Phase A as the next operator
  step, you run it, paste back the output, I evaluate G0/G1/G2/G3,
  emit the Phase-B clearance, **then** you run Phase B.
  **Two-step signing**: this declaration signs Phase A; the sign
  gate clearance signs Phase B (the actual post) only after Phase A
  is clean.
- **"Sign with amendments: [paste]"** → I revise; you re-sign.
- **"Reject"** → re-scope direction.

## 10. What this declaration deliberately does NOT do

- It does not modify `tier1_batch_runner.py`.
- It does not introduce a `--halt-on-failure` flag (runner already
  has F-BUG and repeatable-malformed halts).
- It does not introduce `--include-ids` (Mid America residue is
  handled by the natural selector pool, per §7).
- It does not implement a Batch-4 plan. Batch-4 is its own signed
  declaration after Batch-3 lands clean.
- It does not address SMC, SC Warehouses / YANDELL, CITICARGO,
  Smurfit, GROUPWA / SEAQUIS, the 9 disagreement cluster, or any
  alias / profile / intelligence cleanup. Each is its own track
  (§0 fence).
- It does not engineer around backend capacity. G0, S3 are operator
  abort gates only.
- It does not run anything against prod BC.
- It does not run anything against the BC sandbox until **two**
  sign steps have landed (this declaration + the Phase-B sign-gate
  clearance).

Each deferred item is its own signed declaration after this one is
complete and observed clean.
