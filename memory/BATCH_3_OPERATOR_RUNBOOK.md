# Batch-3 Operator Runbook — Rapid Execution (PLAN-ONLY)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature.
- Scope: replace bespoke per-step shell rituals with a single
  clean operator sequence for Batch-3 Phase A evidence capture,
  exclude-list confirmation, safe sandbox posting of the clean
  set, and post-batch verification.
- Governing declarations (all must remain in force):
  - `BATCH_3_SANDBOX_POST_DECLARATION.md`
  - `BATCH_3_BLOCKER_TRIAGE_DECLARATION.md`
  - `BATCH_3_RE_ENTRY_DECLARATION.md`
  - `prod_reports/BATCH_3_TRIAGE.md`
- This runbook is plan-only. It does **not** change any script.
  It does **not** itself authorize a post. Phase B still requires
  the verbatim §6 clearance line of the re-entry declaration.

## 0. Out-of-scope fence (NON-NEGOTIABLE)

- No script edits to `tier1_batch_runner.py`,
  `vendor_mismatch_sweep.py`, self-heal, orphan unstick, or
  any AP script.
- No doc state mutations outside the runner's own authorized
  write path during a signed Phase B.
- No vendor-master / alias / profile mutations.
- No reopening of parked classes.
- No expansion or silent shrink of the pinned exclude list.
- No production BC writes.

## 1. Golden rules for this runbook

1. **Never paste a line that starts with three backticks into
   the shell.** The runbook intentionally uses indented bare
   lines for commands so you can copy line-by-line without
   tripping the markdown fence corruption we already hit.
2. **Same-session rule.** All gates (G0 → G1 → G2 → sweep →
   G3) must be captured in one continuous SSH session. If the
   session drops, restart from G0.
3. **Evidence lands on host.** Every command redirects output
   into `prod_reports/BATCH_3_REENTRY_*` on the host. If a file
   ends up 0 bytes, the command did not execute cleanly — do
   not proceed; re-run that specific step.
4. **Stop at the sign gate.** Nothing in this runbook is
   permission to run the `post` subcommand. That requires the
   verbatim §6 clearance line.

## 2. Operator sequence

### Step 0 — Sanity-check the terminal

Run each line by itself. Every one must print its expected
output before continuing.

    echo HELLO

    date -u +%FT%TZ

    cd /opt/gpi-hub

    mkdir -p prod_reports

    ls -la prod_reports/ | head

If `echo HELLO` is silent, stop and `reset` or reconnect SSH
before continuing. Paste-state corruption is not recoverable
mid-run.

### Step 1 — G0 backend-not-throttled

Run each line by itself.

    docker compose logs --since 1h backend 2>&1 | grep -E "RESOURCE_EXHAUSTED|GeminiReturnedResourceExhausted|HTTP/1.1\" 5|timeout|connection reset|queue depth|throttle" | tail -n 60 > prod_reports/BATCH_3_REENTRY_G0_logtail.txt

    wc -l prod_reports/BATCH_3_REENTRY_G0_logtail.txt

    ( time curl -s -o /tmp/gpi_health.out -w "HTTP %{http_code}\n" http://localhost:8001/api/health ) > prod_reports/BATCH_3_REENTRY_G0_health.txt 2>&1

    cat /tmp/gpi_health.out >> prod_reports/BATCH_3_REENTRY_G0_health.txt

    cat prod_reports/BATCH_3_REENTRY_G0_health.txt

    docker compose exec -T backend python -u -c "import asyncio,os,time,json; from motor.motor_asyncio import AsyncIOMotorClient; \
async def m():\
 t=time.time(); db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]; c=await db.hub_documents.count_documents({}); print(json.dumps({'hub_documents_count':c,'elapsed_seconds':round(time.time()-t,3)}))\nasyncio.run(m())" > prod_reports/BATCH_3_REENTRY_G0_mongo.json

    cat prod_reports/BATCH_3_REENTRY_G0_mongo.json

**G0 pass criteria (all three):**
- log-tail file lines = 0
- /api/health HTTP 200 in < 2s
- Mongo round-trip < 1s

If any fails, **stop here**. G0 is hard.

### Step 2 — G1 preflight

    docker compose exec -T -w /app backend python -u scripts/tier1_batch_runner.py preflight > prod_reports/BATCH_3_REENTRY_G1_preflight.txt 2>&1

    echo "exit: $?"

    wc -l prod_reports/BATCH_3_REENTRY_G1_preflight.txt

    tail -n 40 prod_reports/BATCH_3_REENTRY_G1_preflight.txt

**G1 pass criteria:**
- file size > 0
- exit = 0
- no `error`, `timeout`, `RESOURCE_EXHAUSTED`, or `HTTP 5xx`
  strings in tail

If file is 0 bytes, re-run Step 2 once. If still 0 bytes,
stop and report.

### Step 3 — G2 dry-run

Note: the runner's `dry-run` subcommand does **not** accept
`--exclude-ids`. Exclusion is applied at Phase B `post` time
only. This is a recording-only deviation per §4.3 of the
re-entry declaration.

    docker compose exec -T -w /app backend python -u scripts/tier1_batch_runner.py dry-run > prod_reports/BATCH_3_REENTRY_G2_dryrun.txt 2>&1

    echo "exit: $?"

    wc -l prod_reports/BATCH_3_REENTRY_G2_dryrun.txt

    tail -n 60 prod_reports/BATCH_3_REENTRY_G2_dryrun.txt

**G2 pass criteria:**
- file size > 0
- exit = 0
- tail shows a summary line (preflight ok → select → dry-run)
- no abort, timeout, or throttle strings

### Step 4 — Fresh mismatch sweep

    docker compose exec -T -w /app backend python -u scripts/vendor_mismatch_sweep.py > prod_reports/BATCH_3_REENTRY_sweep_run.txt 2>&1

    echo "exit: $?"

    tail -n 30 prod_reports/BATCH_3_REENTRY_sweep_run.txt

    docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.md ./prod_reports/BATCH_3_REENTRY_sweep.md

    docker compose cp backend:/app/memory/VENDOR_MISMATCH_SWEEP.json ./prod_reports/BATCH_3_REENTRY_sweep.json

    grep -E "^- at_risk|^- safe|^\| .* \|" prod_reports/BATCH_3_REENTRY_sweep.md | head -n 40

**Sweep pass criteria:**
- totals line shows `at_risk` count equal to length of pinned
  exclude list (currently 2 if both pinned docs still surface,
  or 1 if T.D. LINES has drifted out per the last attempt's
  finding)
- all at_risk IDs are members of the pinned exclude list
- no new at_risk outside the pinned list

### Step 5 — G3 candidate-pool snapshot

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; \
async def m():\
 db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]; \
 cur=db.hub_documents.find({'status':'ReadyForPost','workflow_status':'ready_for_post','\$or':[{'bc_purchase_invoice':{'\$in':[None,'']}},{'bc_purchase_invoice':{'\$exists':False}}]}, {'_id':0,'id':1,'vendor_canonical':1,'bc_vendor_number':1,'vendor_match_method':1,'bc_match_status':1,'bc_match_confidence':1,'invoice_number':1,'extracted_fields.invoice_number':1,'extracted_fields.total':1}); \
 rows=await cur.to_list(length=500); print(json.dumps({'pool_size':len(rows),'rows':rows},indent=2,default=str))\nasyncio.run(m())" > prod_reports/BATCH_3_CANDIDATE_POOL.json

    head -n 80 prod_reports/BATCH_3_CANDIDATE_POOL.json

    echo "--- pool_size ---"; grep pool_size prod_reports/BATCH_3_CANDIDATE_POOL.json

**G3 pass criteria:**
- file non-empty; valid JSON
- all currently-pinned exclude IDs are **present** in the pool
  (§4.6). If any pinned ID is missing, re-entry aborts; the
  pinned list needs a signed amendment before a new attempt.
- any row in the pool with weak resolution (no
  `bc_vendor_number` or `vendor_canonical=""`) that is not in
  the pinned list is flagged for review, not silently accepted.

### Step 6 — Exclude-list confirmation

    cat > prod_reports/BATCH_3_REENTRY_exclude_list.txt <<EOF
    6c3f98e8-122b-4761-a20f-d603d500a568
    6d29133c-3730-4fab-a808-5504184504e0
    EOF

    cat prod_reports/BATCH_3_REENTRY_exclude_list.txt

If the pinned list has been amended (e.g., T.D. LINES drifted
out and the amendment was signed), substitute the amended
contents verbatim here. **Do not amend the list inline without
a signed declaration.**

### Step 7 — STOP and paste back

Paste back to the agent, in one message:

1. `prod_reports/BATCH_3_REENTRY_G0_logtail.txt` (line count;
   content only if > 0 lines).
2. `prod_reports/BATCH_3_REENTRY_G0_health.txt` (verbatim).
3. `prod_reports/BATCH_3_REENTRY_G0_mongo.json` (verbatim).
4. `prod_reports/BATCH_3_REENTRY_G1_preflight.txt`
   (tail -n 40 is fine).
5. `prod_reports/BATCH_3_REENTRY_G2_dryrun.txt`
   (tail -n 60 is fine).
6. Sweep totals + at_risk table (grep from Step 4).
7. `prod_reports/BATCH_3_CANDIDATE_POOL.json` (`pool_size`
   + rows; tail -n 120 if full file is too large).
8. `prod_reports/BATCH_3_REENTRY_exclude_list.txt` (verbatim).

Agent returns one of:
- **Phase-A-clear / review-ready** with a per-gate pass grid.
- **Aborted** with the specific failing gate(s).

Nothing else happens until the §6 clearance line is delivered.

## 3. Phase B — safe sandbox posting (only after §6 clearance)

Only execute this section if the agent has declared
Phase-A-clear **and** the operator has personally delivered
the §6 clearance line verbatim in a subsequent message:

> `Phase B clear — proceed with --exclude-ids "<pinned-list-csv>"`

Where `<pinned-list-csv>` is the exact comma-separated pinned
exclude list confirmed in Step 6.

### Step 8 — sandbox post (SINGLE ATTEMPT)

    docker compose exec -T -w /app backend python -u scripts/tier1_batch_runner.py post --confirm --exclude-ids "<pinned-list-csv>" > prod_reports/BATCH_3_POST_stdout.txt 2>&1

    echo "exit: $?"

    tail -n 80 prod_reports/BATCH_3_POST_stdout.txt

**Post execution rules:**
- Single attempt per signed clearance. No retries without a new
  clearance line.
- Exit codes: 0 = success (some P-bucket posts landed);
  1 = no P-bucket posts; 2 = preflight/arg failure; 3 = hard
  guard refused (unresolved vendor / empty pool after
  exclusion). Any non-zero exit is recorded, not silently
  retried.
- The only acceptable `--exclude-ids` value is the pinned list
  as confirmed in Step 6. If the confirmed list differs from
  the clearance line, **do not run**. Re-sign instead.

### Step 9 — post-batch verification (read-only)

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; \
async def m():\
 db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]; \
 cur=db.hub_documents.find({'status':'ReadyForPost','bc_purchase_invoice':{'\$nin':[None,'']}}, {'_id':0,'id':1,'vendor_canonical':1,'bc_vendor_number':1,'bc_purchase_invoice':1,'posting_updated_at':1}); \
 rows=await cur.to_list(length=500); print(json.dumps({'posted_count':len(rows),'rows':rows[-50:]},indent=2,default=str))\nasyncio.run(m())" > prod_reports/BATCH_3_POST_verification.json

    head -n 60 prod_reports/BATCH_3_POST_verification.json

    echo "--- posted_count ---"; grep posted_count prod_reports/BATCH_3_POST_verification.json

Paste back Step 8 stdout + Step 9 verification. Agent records
per-doc bucket breakdown (P/E/S) and updates
`TIER1_BATCH_RESULTS.md` via a separate signed declaration.

## 4. Stop conditions (during any step)

Stop **immediately** and paste back what you have if any of:

- G0 fails any sub-check.
- G1 or G2 exits non-zero or leaves a 0-byte file after one
  re-run.
- Sweep shows a new at_risk ID not in the pinned list.
- G3 shows a pinned ID missing from the pool.
- Step 8 shows an exit code other than 0 and the tail indicates
  a hard guard (exit 3) or preflight abort (exit 2).
- Backend log-tail (Step 1) picks up a sustained throttle /
  503 cluster at any point during the run.
- The SSH session drops. Restart from Step 1 under a new
  runbook pass, since the same-session rule is broken.

## 5. What this runbook deliberately does NOT do

- Does not invoke `post` without a verbatim §6 clearance line.
- Does not modify the runner, the sweep, the self-heal, or any
  other script.
- Does not amend the pinned exclude list. Any amendment goes
  through a separate signed declaration.
- Does not retry failed steps more than once per gate.
- Does not open a capacity-engineering track; throttle signals
  stop the run and are recorded only.
- Does not open a resolver-investigation track for
  `doc_prestamp_or_fallback → CREAT`.
- Does not touch sales flow, contract intelligence flow, auth,
  or any non-AP surface.

## 6. Sign request

- **"Sign as-is"** → this runbook becomes the canonical
  Phase A + Phase B execution script for Batch-3. Operator
  runs it end-to-end under the existing re-entry declaration
  and the subsequent §6 clearance line. No other Batch-3
  execution path is used.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.
