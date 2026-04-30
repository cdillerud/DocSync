# Batch-3 Re-Entry — Plan-Only Declaration (NO POSTING, NO DATA MUTATION)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature before any action.
- Phase posture: Phase 1 — AP Hardening and Controlled Rollout.
  Phase 3 refactor remains paused. Sales / auth / broad refactor
  are not in scope.
- Parent chain:
  - Batch-2 sandbox post (executed, mixed; follow-up classes
    surfaced and parked).
  - `BATCH_3_SANDBOX_POST_DECLARATION.md` (signed 2026-04-30).
  - `BATCH_3_BLOCKER_TRIAGE_DECLARATION.md` (signed 2026-04-30).
  - `prod_reports/BATCH_3_TRIAGE.md` (generated 2026-04-30):
    - `at_risk=2, safe=7`
    - 2 at_risk pinned as **NEW-CLASS / EXCLUDE-NEW-CLASS**:
      - `6c3f98e8-122b-4761-a20f-d603d500a568` — T.D. LINES, INC.
      - `6d29133c-3730-4fab-a808-5504184504e0` — Parkway Plastics Inc.
      - Shared resolver signature:
        `vendor_match_method=doc_prestamp_or_fallback →
         bc_vendor_number=CREAT`
    - Preflight verdict: **TRANSIENT-BLIP**
    - Batch-3 remains blocked until this re-entry declaration
      is signed.

## 0. Out-of-scope fence (NON-NEGOTIABLE)

This declaration is the **doorway back into Phase A of Batch-3**.
It is **not** permission to post. It specifically does **not**:

- Run any BC post (sandbox or prod).
- Authorize Phase B of Batch-3. Phase B requires a separate,
  explicit clearance line (see §6).
- Mutate any document state.
- Mutate any vendor-master, alias, or profile record.
- Heal, promote, or demote any doc — including the 2 pinned
  NEW-CLASS docs.
- Investigate the `doc_prestamp_or_fallback → CREAT` resolver
  class. That class is parked as NEW-CLASS; investigation
  requires its own separate signed declaration.
- Modify `tier1_batch_runner.py`, `vendor_mismatch_sweep.py`,
  the canonical self-heal script, the orphan unstick script,
  or any other AP script.
- Modify backend code, frontend code, auth flow, sales flow,
  or contract intelligence flow. Phase 4C work remains paused
  and separate.
- Tighten the mismatch-sweep heuristic, change its thresholds,
  or re-classify its output fields.
- Reopen SMC / SC-Warehouses-YANDELL / CITICARGO / Smurfit
  (`WROCKCP`/`WESTROCK`) / GROUPWA-SEAQUIS cleanup under any
  condition.
- Engineer around backend capacity (worker counts, connection
  pools, Gemini quota, async batch sizing, caching). A
  persistent-degradation signal that emerges during Phase A
  re-entry is **recorded and stops the attempt**, not acted on.
- Run Phase A with a relaxed or expanded exclude list. The
  exclude list for this re-entry is pinned verbatim to the 2
  NEW-CLASS IDs above and nothing else.
- Ship Batch-3 on the basis of a “mostly clean” Phase A. Any
  gate failure in §3 blocks re-entry.

## 1. Goal

Define the **exact, enumerable conditions** under which Batch-3
may re-enter Phase A safely, and the **exact read-only operator
sequence** that produces the evidence required to clear each
gate. Produce a single Phase-A-ready evidence bundle for review.
No posting is authorized by this declaration.

## 2. In-scope

- **G0 — Backend not throttled.** Read-only health-and-capacity
  posture check executed in the same session the Phase A attempt
  will run in.
- **G1 — Preflight clean.** Fresh preflight, in the same session,
  with no HTTP 5xx / timeout / throttle signature.
- **G2 — Dry-run clean.** Fresh dry-run that completes without
  aborting on preflight and without surfacing a new throttle
  signature.
- **Fresh mismatch sweep.** Re-run of `vendor_mismatch_sweep`
  in the same session; artifact pulled to `prod_reports/`.
- **G3 — Candidate-pool snapshot.** Read-only Mongo probe of the
  live Tier-1 candidate pool (status=ReadyForPost,
  workflow_status=ready_for_post, bc_purchase_invoice unset),
  pinned to `prod_reports/`.
- **Pinned exclude list.** Exactly:
  - `6c3f98e8-122b-4761-a20f-d603d500a568`
  - `6d29133c-3730-4fab-a808-5504184504e0`
  No additions, no removals.
- **Separate Phase B sign gate.** Phase B may only begin after
  the operator pastes back the evidence bundle in §5 and
  explicitly delivers the clearance line in §6.

## 3. Hard requirements for re-entry

All of the following must be **observed in the same session**
as the intended Phase A attempt. Any single failure blocks
re-entry; the attempt is stopped and the failure is recorded.

1. **G0 pass, fully:**
   - backend log-tail (last 1h) clean of sustained
     `RESOURCE_EXHAUSTED` / `GeminiReturnedResourceExhausted` /
     503 clusters / connection-reset clusters;
   - `/api/health` returns HTTP 200 in `< 2 s`;
   - Mongo round-trip (via `-T` heredoc probe) completes in
     `< 1 s`.
2. **G1 preflight pass, fully:** runner preflight completes
   without HTTP timeout / 5xx / throttle signature.
3. **G2 dry-run completes:** runner dry-run returns a clean
   summary, does not abort on preflight, and does not surface
   a new throttle signature.
4. **Mismatch sweep shows no remaining `at_risk` after
   subtracting the pinned exclude list.** If the sweep reports
   `at_risk > 0` and any of those IDs is not in the pinned
   exclude list, re-entry is aborted and a fresh blocker-triage
   round is required (under its own signed declaration).
5. **Candidate-pool snapshot captured** to
   `prod_reports/BATCH_3_CANDIDATE_POOL.md` (+ `.json`). The
   snapshot is read-only evidence; it is not wired into the
   runner.
6. **No new at_risk class.** Any at_risk doc outside the pinned
   exclude list blocks re-entry, even if its resolver signature
   resembles an existing class.
7. **No new throttle signature.** Any new HTTP 5xx / timeout /
   RESOURCE_EXHAUSTED pattern during G0 / G1 / G2 blocks
   re-entry.
8. **Pinned exclude list integrity.** The `--exclude-ids`
   argument used in Phase B (when/if later authorized) must
   match exactly:
   `6c3f98e8-122b-4761-a20f-d603d500a568,
    6d29133c-3730-4fab-a808-5504184504e0`
   (order-insensitive; no additions; no removals).

If every hard requirement above passes, Phase A re-entry is
**review-ready**. It is still **not** Phase B. Phase B requires
§6.

## 4. Exact operator sequence (Phase A only, read-only)

All commands run on the prod VM. Heredocs use `-T` to avoid the
TTY contention surfaced during triage. None of these commands
write to Mongo, BC, or disk beyond the evidence artifacts in
`prod_reports/`.

### 4.1 G0 — backend-not-throttled

```bash
# Log tail (last 1h) — clean of sustained throttle / 5xx clusters
docker compose logs --since 1h backend | \
  grep -E "RESOURCE_EXHAUSTED|GeminiReturnedResourceExhausted|\
HTTP/1.1\" 5|timeout|connection reset|queue depth|throttle" \
  | tail -n 60

# /api/health latency (must be HTTP 200 in < 2 s)
time curl -s -o /tmp/gpi_health.out -w "HTTP %{http_code}\n" \
    http://localhost:8001/api/health
cat /tmp/gpi_health.out

# Mongo round-trip (-T heredoc; must be < 1 s)
docker compose exec -T backend python - <<'PY'
import asyncio, os, time
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    t0 = time.time()
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    count = await db.hub_documents.count_documents({})
    print({"hub_documents_count": count,
           "elapsed_seconds": round(time.time()-t0, 3)})
asyncio.run(main())
PY
```

### 4.2 G1 — preflight

```bash
docker compose exec -T -w /app backend \
    python scripts/tier1_batch_runner.py --preflight-only \
    | tee prod_reports/BATCH_3_REENTRY_G1_preflight.txt
```

### 4.3 G2 — dry-run

```bash
docker compose exec -T -w /app backend \
    python scripts/tier1_batch_runner.py --dry-run \
    --exclude-ids "6c3f98e8-122b-4761-a20f-d603d500a568,\
6d29133c-3730-4fab-a808-5504184504e0" \
    | tee prod_reports/BATCH_3_REENTRY_G2_dryrun.txt
```

If the runner flag names differ from `--preflight-only` /
`--dry-run` / `--exclude-ids` in the current `tier1_batch_runner.py`,
the operator substitutes the runner's actual flag names
verbatim without modifying the runner. Flag rename is a
recording-only deviation, not a code change.

### 4.4 Fresh mismatch sweep

```bash
docker compose exec -T -w /app backend \
    python scripts/vendor_mismatch_sweep.py

docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.md \
    ./prod_reports/BATCH_3_REENTRY_sweep.md
docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.json \
    ./prod_reports/BATCH_3_REENTRY_sweep.json
```

### 4.5 G3 — candidate-pool snapshot

```bash
docker compose exec -T backend python - <<'PY' \
  | tee prod_reports/BATCH_3_CANDIDATE_POOL.json
import asyncio, os, json
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cur = db.hub_documents.find({
        "status": "ReadyForPost",
        "workflow_status": "ready_for_post",
        "$or": [
            {"bc_purchase_invoice": {"$in": [None, ""]}},
            {"bc_purchase_invoice": {"$exists": False}},
        ],
    }, {
        "_id": 0,
        "id": 1,
        "vendor_canonical": 1,
        "bc_vendor_number": 1,
        "vendor_match_method": 1,
        "bc_match_status": 1,
        "bc_match_confidence": 1,
        "invoice_number": 1,
        "extracted_fields.invoice_number": 1,
        "extracted_fields.total": 1,
    })
    rows = await cur.to_list(length=500)
    print(json.dumps({
        "pool_size": len(rows),
        "rows": rows,
    }, indent=2, default=str))

asyncio.run(main())
PY
```

### 4.6 Compose effective exclude list

The effective exclude list for this re-entry attempt is
**exactly** the pinned list:

```
6c3f98e8-122b-4761-a20f-d603d500a568
6d29133c-3730-4fab-a808-5504184504e0
```

No additions (even if a new at_risk surfaces — that aborts
re-entry). No removals (even if a pinned doc appears to have
drifted out of the pool — that also aborts re-entry for
evidence-capture reasons).

### 4.7 Stop for review

After §4.1–§4.6 complete, the operator **stops**. No Phase B.
No posting. No runner invocation without `--dry-run` /
`--preflight-only`.

## 5. Reporting requirements

The operator pastes back a single message containing all of:

1. **G0 results:**
   - Log-tail grep output (or explicit "no matches").
   - `/api/health` HTTP code and `time` output.
   - Mongo probe JSON (`hub_documents_count`, `elapsed_seconds`).
2. **G1 preflight stdout:** verbatim, from
   `prod_reports/BATCH_3_REENTRY_G1_preflight.txt`.
3. **G2 dry-run stdout:** verbatim, from
   `prod_reports/BATCH_3_REENTRY_G2_dryrun.txt`.
4. **Mismatch sweep totals:** `at_risk` count, `safe` count,
   any at_risk IDs; confirmation that every at_risk ID (if any)
   is in the pinned exclude list.
5. **Candidate-pool snapshot:** `pool_size` and the summary
   rows from `prod_reports/BATCH_3_CANDIDATE_POOL.json`.
6. **Effective exclude list for this re-entry attempt:**
   verbatim, both pinned UUIDs.

The agent's response to this paste is limited to:
- acknowledging pass/fail of each hard requirement in §3;
- recording any observed deviation;
- either declaring the attempt **Phase-A-clear / review-ready**
  or declaring it **aborted** and naming the failing gate.

The agent does **not** proceed to Phase B on the basis of a
review-ready verdict. Phase B requires §6.

## 6. Explicit Phase B gate

Phase B (actual sandbox posting) may only begin after the
operator delivers the following clearance line **verbatim** in
a subsequent message, after reviewing the §5 evidence bundle:

> `Phase B clear — proceed with --exclude-ids "6c3f98e8-122b-4761-a20f-d603d500a568,6d29133c-3730-4fab-a808-5504184504e0"`

Any deviation from that line (different IDs, additional IDs,
removed IDs, reworded clearance, missing `--exclude-ids`
argument) is treated as **not cleared**. Phase B does not begin.

The Phase B clearance line is scoped to a single attempt. A
second attempt requires a new §5 evidence bundle and a new
clearance line.

## 7. Out-of-scope fence (restated)

Still out of scope for this declaration and for the Phase A
re-entry it authorizes:

- Investigation of the NEW-CLASS `doc_prestamp_or_fallback →
  CREAT` docs or the resolver path behind them.
- SMC investigation.
- SC Warehouses / YANDELL cleanup.
- CITICARGO investigation.
- Smurfit (`WROCKCP` / `WESTROCK`) cleanup.
- GROUPWA / SEAQUIS cosmetic normalization.
- Mismatch-sweep heuristic tightening or re-classification.
- Backend capacity engineering.
- Any production BC posting.
- Any script, backend, or frontend code change.

Each deferred item is its own signed declaration, not a
side-effect of this one.

## 8. Sign request

To proceed to Phase A re-entry execution:

- **"Sign as-is"** → agent emits the §4 command block as a
  single operator-ready script sequence; operator runs, pastes
  back the §5 evidence bundle; agent records the pass/fail of
  each hard requirement in §3 and declares the attempt
  Phase-A-clear or aborted. No code is modified, no doc state
  is touched, no runner script is modified. No posting occurs.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

## 9. What this declaration deliberately does NOT do

- It does not authorize any BC post (sandbox or prod).
- It does not authorize Phase B. Phase B requires the §6
  clearance line.
- It does not modify `tier1_batch_runner.py`, the mismatch
  sweep, the canonical self-heal, or any other script.
- It does not heal, promote, demote, or otherwise mutate any
  doc — including the 2 pinned NEW-CLASS docs.
- It does not investigate the NEW-CLASS resolver class or any
  other parked class.
- It does not engineer around backend capacity. A persistent
  throttle signature during G0/G1/G2 is recorded and aborts
  re-entry; it does not trigger an in-line fix.
- It does not expand the exclude list beyond the 2 pinned
  NEW-CLASS doc IDs.
- It does not grant a standing Phase A clearance. Each Phase
  A re-entry attempt requires a fresh session's G0/G1/G2
  evidence and a fresh review.
