# Batch-3 Blocker Triage — Plan-Only Declaration (NO POSTING, NO DATA MUTATION)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature before any action.
- Phase posture: Phase 1 — AP Hardening and Controlled Rollout.
  Phase 3 refactor remains paused. Sales / auth / broad refactor are
  not in scope.
- Parent chain:
  - Batch-2 sandbox post (executed, mixed, at least one Mid America
    P-bucket observed, three follow-up classes surfaced).
  - Batch-3 Sandbox Post Declaration (signed as-is 2026-04-30).
  - Batch-3 Phase A attempt: **BLOCKED** — preflight failed on
    `/api/health` at execution time; dry-run aborted; fresh mismatch
    sweep returned `at_risk=2, safe=7`.

## 0. Out-of-scope fence (NON-NEGOTIABLE)

This declaration scopes **triage only**. It does **not**:

- Run any BC post (sandbox or prod).
- Run any new dry-run, preflight, or full batch attempt.
- Mutate any document state.
- Mutate any vendor-master, alias, or profile record.
- Heal any doc — even if triage reveals a known-class contamination.
- Modify `tier1_batch_runner.py`, `vendor_mismatch_sweep.py`, the
  canonical self-heal script, the orphan unstick script, or any
  other AP script.
- Reopen **SMC vendor-record / Buy-from Vendor No.** work **unless**
  triage shows one of the 2 at_risk docs is an SMC doc. Even then,
  this declaration only records the classification; SMC fixes remain
  a separate signed declaration.
- Reopen **SC Warehouses / YANDELL** work **unless** triage shows
  one of the 2 at_risk docs is an SC Warehouses / YANDELL doc. Same
  condition: record-only here.
- Reopen **CITICARGO**, **Smurfit `WROCKCP`/`WESTROCK`**, or
  **cosmetic GROUPWA / SEAQUIS** work under any condition. Those
  classes remain parked.
- Engineer around backend capacity (worker counts, connection
  pools, Gemini quota, async batch sizing, caching). Out of scope.
- Touch `§6.1` live-path symmetry, `§7` alias/profile/intelligence
  cleanup, or the 9 `manual_review_extraction_vs_bc_disagreement`
  cluster.
- Touch any frontend code, auth flow, sales flow, or contract
  intelligence flow (Phase 4C work is paused and separate).
- Ship Batch-3 under a relaxed exclude list. Batch-3 posting
  re-entry is gated on a separate signed re-entry declaration that
  follows this triage.

## 1. Why Batch-3 is blocked (observed)

Phase A of the Batch-3 declaration ran partially and then tripped
two independent blockers:

1. **Preflight unreliability.** Preflight's `/api/health` probe
   failed mid-phase at execution time. The runner's dry-run
   subsequently aborted. This trips Gate G1 in the Batch-3 posting
   declaration (“preflight passes”) and arguably also Gate G0
   (“backend not throttled”) — i.e. whatever capacity / contention
   condition caused the health miss is exactly what G0 is supposed
   to catch.
2. **Fresh mismatch sweep returns `at_risk=2, safe=7`.** The
   Batch-3 declaration's Gate G2 requires `at_risk == 0` after
   subtracting the §0 known-class IDs. Two at_risk docs remain —
   unknown class at the moment of this declaration.

Posting under either of these conditions violates the Batch-3
declaration. Posting under both violates it twice. The correct
disposition is: stop, triage, and re-enter Phase A only after a
separate re-entry sign.

## 2. Goal

Produce a **read-only** triage artifact for the 2 at_risk docs and
the preflight failure, sufficient to:

- Identify each at_risk doc by `id`, vendor canonical, vendor
  number, invoice number, total, and the specific mismatch
  signature recorded by the sweep.
- Classify each at_risk doc against the known follow-up classes
  (SMC / SC Warehouses-YANDELL / CITICARGO / Smurfit /
  GROUPWA-SEAQUIS) — or mark as **NEW-CLASS** if it fits none.
- Recommend a **per-doc disposition**:
  - `EXCLUDE-KNOWN-CLASS` (doc belongs to an already-parked class;
    add ID to the exclude list for any future Batch-N)
  - `EXCLUDE-NEW-CLASS` (doc does not fit a known class; park it
    pending a separate signed investigation declaration)
  - `NO-ACTION-NEEDED` (sweep correctly flagged it but it is
    already promoted to post cleanly — unlikely but possible if
    the sweep heuristic is conservative)
  - `INVESTIGATE` (ambiguous — needs its own signed track)
- Capture the preflight failure context: approximate wall-clock of
  the miss, one-line signature (e.g. `HTTP timeout`, `HTTP 503`,
  `HTTP 200 but slow`, `connection reset`), and whether the miss
  was transient (i.e. the follow-up G0 probe returned clean).
- Emit a recommendation on whether the preflight miss was a
  **transient capacity blip** (operator waits and re-runs later)
  or a **persistent degradation** (needs its own track).

The output of this triage is a single markdown report committed to
`prod_reports/BATCH_3_TRIAGE.md`. No doc mutations, no script
mutations, no BC contact.

## 3. In-scope operator actions (all read-only)

All commands run on the prod VM. None of them write to Mongo, BC,
or disk beyond the triage report and the pulled sweep artifact.
Heredocs use `-T` to avoid the TTY contention we already surfaced.

### 3.1 Capture the fresh mismatch sweep artifact

If the sweep produced `VENDOR_MISMATCH_SWEEP.md` / `.json`:

```bash
docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.md \
    ./prod_reports/BATCH_3_TRIAGE_sweep.md 2>/dev/null || true
docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.json \
    ./prod_reports/BATCH_3_TRIAGE_sweep.json 2>/dev/null || true
ls -lt ./prod_reports/BATCH_3_TRIAGE_sweep*
```

If neither exists in the container, re-run the sweep (read-only):

```bash
docker compose exec backend python /app/scripts/vendor_mismatch_sweep.py
docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.md \
    ./prod_reports/BATCH_3_TRIAGE_sweep.md
docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.json \
    ./prod_reports/BATCH_3_TRIAGE_sweep.json
```

### 3.2 Extract the 2 at_risk doc IDs and their mismatch class

Read-only probe — derives the at_risk docs directly from Mongo via
the fields the sweep populates (`bc_match_status`,
`bc_match_confidence`, `vendor_match_method`, etc.). No updates.

```bash
docker compose exec -T backend python - <<'PY'
import asyncio, os, json
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    # The sweep reported at_risk=2 in the live candidate pool.
    # Pull every doc that is currently eligible for Tier-1 posting
    # (status=ReadyForPost, workflow_status=ready_for_post,
    #  bc_purchase_invoice unset) and surface the two at_risk ones.
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
        "sender_email": 1,
        "sender_name": 1,
    })
    rows = await cur.to_list(length=500)

    def is_at_risk(d):
        # Keep the check narrow — mirror the sweep's canonical flag
        # surface. If the sweep writes a specific field, prefer that.
        # Otherwise fall back to the match-method / status heuristic
        # the sweep is known to use.
        bms = (d.get("bc_match_status") or "").lower()
        vmm = (d.get("vendor_match_method") or "").lower()
        if bms in ("at_risk", "mismatch"):
            return True
        if "mismatch" in vmm or "contaminated" in vmm:
            return True
        return False

    at_risk = [d for d in rows if is_at_risk(d)]
    safe = [d for d in rows if not is_at_risk(d)]
    print(json.dumps({
        "pool_size": len(rows),
        "at_risk_count": len(at_risk),
        "safe_count": len(safe),
        "at_risk_docs": at_risk,
    }, indent=2, default=str))

asyncio.run(main())
PY
```

If this probe returns `at_risk_count != 2`, that is itself a signal
worth recording — either the sweep and this probe disagree on the
heuristic (which means the sweep's flag surface is narrower than
our fallback), or the pool has shifted since the sweep ran.

Fallback: pull the exact IDs directly from the sweep markdown /
JSON artifact that already exists in `./prod_reports/`. The sweep
is the canonical source; this Mongo probe is a cross-check.

### 3.3 Per-doc classification

For each of the 2 at_risk doc IDs, the operator (or the agent
reviewing the operator output) classifies the doc into one of:

| Class | Signal |
|---|---|
| `SMC` | `vendor_canonical` starts with or matches SMC Worldwide / SMC* AND `bc_vendor_number` either missing, mismatching, or showing the Batch-2 SMC structural-rejection signature. |
| `SC-WAREHOUSES-YANDELL` | `vendor_canonical` matches SC Warehouses / YANDELL AND the YANDELL/SC contamination signature (Batch-2 mixed vendor record) is present. |
| `CITICARGO` | `vendor_canonical` matches CITICARGO, any flavour. |
| `SMURFIT-AMBIGUITY` | `vendor_canonical` / `bc_vendor_number` hit the WROCKCP ↔ WESTROCK cluster. |
| `GROUPWA-SEAQUIS` | Cosmetic normalization only; these should normally be low-risk safe, but if they're flagged at_risk record it. |
| `NEW-CLASS` | Fits none of the above. Record the full mismatch signature verbatim. |

### 3.4 Per-doc disposition recommendation

Strict mapping:

| Class | Recommended disposition |
|---|---|
| `SMC` | `EXCLUDE-KNOWN-CLASS` — add ID to the `--exclude-ids` list of any future Batch-N. SMC investigation remains out of scope for this triage. |
| `SC-WAREHOUSES-YANDELL` | `EXCLUDE-KNOWN-CLASS` — add ID to `--exclude-ids`. SC/YANDELL cleanup remains out of scope. |
| `CITICARGO` | `EXCLUDE-KNOWN-CLASS` — add ID to `--exclude-ids`. CITICARGO investigation remains out of scope. |
| `SMURFIT-AMBIGUITY` | `EXCLUDE-KNOWN-CLASS` — add ID to `--exclude-ids`. Smurfit remains permanently excluded per Batch-2 declaration. |
| `GROUPWA-SEAQUIS` | `EXCLUDE-KNOWN-CLASS` — parked per prior declaration. |
| `NEW-CLASS` | `EXCLUDE-NEW-CLASS` — park the ID; file a new named investigation declaration if/when that class is prioritized. Do not attempt any inline fix here. |

No doc is marked `NO-ACTION-NEEDED` without an explicit,
documented reason. Any ambiguous case is recorded as `INVESTIGATE`
and held for operator review; no doc state is touched.

### 3.5 Preflight-failure triage

Capture (read-only):

```bash
# When did /api/health last fail, and what did it look like?
docker compose logs --since 1h backend | \
  grep -E "/api/health|503|timeout|queue|throttle|RESOURCE_EXHAUSTED|GeminiReturnedResourceExhausted" \
  | tail -n 40

# Current /api/health response + latency (re-check now):
time curl -s -o /tmp/gpi_health.out -w "HTTP %{http_code}\n" \
    http://localhost:8001/api/health
cat /tmp/gpi_health.out

# Current Mongo round-trip (re-check now, -T for heredoc):
docker compose exec -T backend python - <<'PY'
import asyncio, os, time
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    t0 = time.time()
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    count = await db.hub_documents.count_documents({})
    print({"hub_documents_count": count, "elapsed_seconds": round(time.time()-t0, 3)})
asyncio.run(main())
PY
```

Verdict options (mutually exclusive):

- `TRANSIENT-BLIP`: the earlier miss does not repeat, current
  `/api/health` is 200 in < 2 s, Mongo round-trip < 1 s, and logs
  show no sustained RESOURCE_EXHAUSTED / 503 cluster. Recommend
  waiting and re-running Phase A in a fresh session.
- `PERSISTENT-DEGRADATION`: the miss reproduces, or logs show a
  sustained RESOURCE_EXHAUSTED / throttle pattern, or current
  `/api/health` > 2 s / Mongo > 1 s. Recommend holding Phase A and
  filing a **capacity-posture** declaration (which itself is out of
  scope for *this* triage — it's a separate track, NOT a
  capacity-engineering declaration).

## 4. Triage report — required shape

Operator (or agent) writes `prod_reports/BATCH_3_TRIAGE.md` with
this layout. The report is the only artifact this declaration
produces beyond the sweep copy.

```markdown
# Batch-3 Blocker Triage Report

- Generated: <UTC timestamp>
- Parent: Batch-3 Sandbox Post Declaration (signed 2026-04-30),
  Phase A blocked.

## A. Mismatch sweep summary (verbatim)
- at_risk: 2
- safe: 7
- source artifact: prod_reports/BATCH_3_TRIAGE_sweep.md

## B. At-risk docs

### Doc 1
- id: <UUID>
- vendor_canonical: <...>
- bc_vendor_number: <... or missing>
- vendor_match_method: <...>
- bc_match_status: <...>
- invoice_number: <...>
- total: <...>
- mismatch signature (verbatim from sweep): <one line>
- class: <SMC | SC-WAREHOUSES-YANDELL | CITICARGO | SMURFIT-AMBIGUITY | GROUPWA-SEAQUIS | NEW-CLASS>
- disposition: <EXCLUDE-KNOWN-CLASS | EXCLUDE-NEW-CLASS | INVESTIGATE>
- rationale: <one paragraph>

### Doc 2
…

## C. Preflight-failure triage
- miss signature (from logs): <...>
- approximate miss wall-clock (UTC): <...>
- current /api/health: <HTTP code, t_total>
- current Mongo round-trip: <elapsed_seconds>
- verdict: <TRANSIENT-BLIP | PERSISTENT-DEGRADATION>
- rationale: <one paragraph>

## D. Recommended re-entry posture
- exclude list for any future Batch-N re-entry:
  - <UUID>  (class)
  - <UUID>  (class)
- fresh stability check required before Phase A re-entry:
  - full G0 (-T heredoc on Mongo probe)
  - G1 preflight clean
  - fresh mismatch sweep showing at_risk == 0 after subtracting
    the exclude list above
- no batch re-entry before a separate signed
  BATCH_3_RE_ENTRY_DECLARATION.md
```

## 5. Fresh stability check (required before Phase A re-entry)

Re-entry into Phase A of Batch-3 is gated on **all** of:

1. A freshly-signed `BATCH_3_RE_ENTRY_DECLARATION.md` that cites
   this triage report, pins the exclude list, and re-acknowledges
   the §0 fence.
2. A full G0 pass in the session where Phase A resumes
   (log-tail clean, `/api/health` 200 < 2 s, Mongo round-trip
   < 1 s with `-T` heredoc).
3. A fresh `vendor_mismatch_sweep` showing `at_risk == 0` **after
   subtracting** the exclude list pinned in the re-entry
   declaration. If a new at_risk candidate appears that is not on
   the pinned list, re-entry is aborted; a fresh triage round runs.
4. Operator sign-off on the re-entry declaration before any
   `tier1_batch_runner.py` command is run.

The triage declaration itself does **not** authorize any of the
above. It just makes them executable once the re-entry declaration
is signed.

## 6. Reporting requirements

Only three artifacts are produced by this triage:

1. `prod_reports/BATCH_3_TRIAGE_sweep.md` and `.json` — the
   canonical sweep output, pulled verbatim from the container.
2. `prod_reports/BATCH_3_TRIAGE.md` — the triage report, shape
   specified in §4.
3. A one-line operator note summarizing the verdict:
   `"Batch-3 blocked; 2 at_risk classified as <...> / <...>;
   preflight verdict <TRANSIENT-BLIP|PERSISTENT-DEGRADATION>;
   re-entry blocked until BATCH_3_RE_ENTRY_DECLARATION.md is
   signed."`

No other commits, no other state changes.

## 7. Safety posture

| layer | posture |
|---|---|
| Mongo | read-only across the whole triage. Probes use `find` / `count_documents` only. |
| BC | not contacted. |
| Scripts | not modified. |
| Doc state | not mutated. Even a doc we classify as `SMC` stays promoted in whatever status it currently has. |
| Exclude list | emitted to the report only; not yet wired into any runner invocation. That wiring happens only at Phase A re-entry time under the separate re-entry declaration. |

## 8. Sign request

To proceed to triage execution:

- **"Sign as-is"** → agent emits the Phase-A-style read-only probes
  (sweep artifact pull, at_risk doc Mongo probe, preflight-failure
  log grep, current health + Mongo re-check) as a single script
  block for the operator; operator runs, pastes output; agent
  synthesizes the report (§4 shape) and commits it under
  `prod_reports/BATCH_3_TRIAGE.md`. No code is modified, no doc
  state is touched, no sweep or runner script is modified. No
  batch is attempted.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

## 9. What this declaration deliberately does NOT do

- It does not authorize any BC post (sandbox or prod).
- It does not authorize any dry-run or preflight re-attempt with
  the intent of posting.
- It does not heal, promote, demote, or otherwise mutate any doc.
- It does not modify `tier1_batch_runner.py`, the mismatch sweep,
  the canonical self-heal, or the orphan unstick scripts.
- It does not reopen SMC, SC Warehouses / YANDELL, CITICARGO,
  Smurfit, or GROUPWA / SEAQUIS investigations. It only records
  whether a flagged doc belongs to one of those classes so the
  exclude list can be composed correctly later.
- It does not engineer around backend capacity. A
  `PERSISTENT-DEGRADATION` verdict is recorded, not acted on. The
  response to that verdict is its own separately-signed track.
- It does not re-enter Phase A of Batch-3. Re-entry is gated on
  `BATCH_3_RE_ENTRY_DECLARATION.md`, which this triage will
  *inform* but not *replace*.

Each deferred item is its own signed declaration after this one is
complete and observed clean.
