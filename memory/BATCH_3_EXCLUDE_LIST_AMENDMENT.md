# Batch-3 Exclude-List Amendment — Plan-Only Declaration
# (NO POSTING, NO DATA MUTATION, NO CODE CHANGES)

- Author/agent: Emergent fork agent
- Generated: 2026-05-01 (UTC)
- Status: DRAFT — awaiting user signature.
- Amends: `/app/memory/BATCH_3_RE_ENTRY_DECLARATION.md`
  (signed 2026-04-30) — specifically §2, §3.8, §4.6, §5, and §6.
- Parent chain:
  - `BATCH_3_SANDBOX_POST_DECLARATION.md` (signed 2026-04-30)
  - `BATCH_3_BLOCKER_TRIAGE_DECLARATION.md` (signed 2026-04-30)
  - `prod_reports/BATCH_3_TRIAGE.md` (committed 2026-04-30)
  - `BATCH_3_RE_ENTRY_DECLARATION.md` (signed 2026-04-30)
  - `FAST_TRACK_EXECUTION_PLAN.md` (signed 2026-04-30)
  - `BATCH_3_OPERATOR_RUNBOOK.md` (signed 2026-04-30)
  - Lane 1 Phase A re-entry attempt (2026-05-01):
    - G0/G1/G2/sweep/G3 all mechanically clean
    - Dry-run surfaced two KNOWN-CLASS risks outside the
      original 2-ID pinned list (CITICARGO vendor mismatch;
      header-only Tumalo PI)
    - `prod_reports/BATCH_3_REENTRY_G2_dryrun.txt` is the
      authoritative evidence for the amendment below.

## 0. Out-of-scope fence (NON-NEGOTIABLE, unchanged)

This amendment does **not**:

- Authorize any BC post (sandbox or prod).
- Grant Phase B by itself. Phase B still requires a separate,
  verbatim §6 clearance line under the amended list.
- Modify `tier1_batch_runner.py`, `vendor_mismatch_sweep.py`,
  self-heal, orphan unstick, or any other AP script.
- Mutate any hub document, vendor master, alias, or profile.
- Heal, promote, or demote any document — including the 4
  amended-list IDs.
- Reopen the CITICARGO investigation, the header-only PI
  policy track, or the `doc_prestamp_or_fallback → CREAT`
  resolver track. These remain parked. The amendment only
  records that the 4 docs are EXCLUDED from Batch-3. Their
  underlying investigations are separate, not opened here.
- Reopen SMC, SC-Warehouses / YANDELL, Smurfit
  (`WROCKCP` / `WESTROCK`), or GROUPWA / SEAQUIS tracks.
- Tighten, change, or replace the mismatch-sweep heuristic.
  The sweep's narrow at_risk surface missed CITICARGO and the
  header-only Tumalo; that gap is recorded here, not fixed.
- Engineer around backend capacity.
- Expand the amended list further without another signed
  amendment. Any later addition (e.g., new at_risk class,
  new sweep miss) requires its own signed amendment.
- Shrink the amended list. No silent removals. If any of the
  4 IDs drifts out of the candidate pool, re-entry aborts per
  §4.6 of the re-entry declaration and a fresh amendment is
  required.
- Touch frontend, auth, sales, or contract-intelligence
  surfaces.

## 1. Why this amendment

The Lane 1 Phase A re-entry attempt on 2026-05-01 produced a
clean G0/G1/G2/sweep/G3 bundle, but the dry-run (authoritative
for "what the runner will post") enumerated 9 candidates and
flagged three risk annotations the narrow sweep at_risk heuristic
did not surface:

- `3ee0b684-…` CITICARGO & STORAGE → `112522` — `VENDOR MISMATCH`
- `3fcfa433-…` Tumalo Creek → `TUMALOC` — `zero line items;
  header-only PI`

Combined with the two already-pinned NEW-CLASS docs
(`6c3f98e8-…` T.D. LINES → CREAT and `6d29133c-…` Parkway →
CREAT), the safe Phase B exclude set is **4 IDs**, not 2.

Per §3.8 of the re-entry declaration, the pinned exclude list
cannot change silently. This amendment replaces it.

## 2. Amended pinned exclude list (REPLACES §3.8 and §4.6 list)

The exclude list for Batch-3 Phase B is now exactly:

| # | doc_id | Vendor (extracted → resolved) | Invoice # | $ | Class | Reason |
|---|---|---|---|---|---|---|
| 1 | `6c3f98e8-122b-4761-a20f-d603d500a568` | T.D. LINES, INC. → `CREAT` | 113798 | 3,000.00 | NEW-CLASS | `doc_prestamp_or_fallback → CREAT` resolver collapse. Parked per triage report §B Doc 1. No inline fix. |
| 2 | `6d29133c-3730-4fab-a808-5504184504e0` | Parkway Plastics Inc. → `CREAT` | 1062002 | 852.90 | NEW-CLASS | Same `doc_prestamp_or_fallback → CREAT` resolver collapse. Parked per triage report §B Doc 2. No inline fix. |
| 3 | `3ee0b684-cfee-4559-a49c-275b6b1a58e2` | CITICARGO & STORAGE → `112522` | SI338725 | 3,426.45 | KNOWN-CLASS | CITICARGO is a parked vendor class. Dry-run confirms `VENDOR MISMATCH: extracted 'CITICARGO & STORAGE' vs resolved '112522'`. Posting would attribute to the wrong BC vendor. |
| 4 | `3fcfa433-de88-40ba-baaa-226a46d62391` | Tumalo Creek Transportation → `TUMALOC` | 0303103 | 1,725.00 | KNOWN-CLASS | Header-only PI Policy is parked in backlog. Dry-run confirms `zero line items extracted — endpoint may post a header-only PI`. |

Canonical CSV form (for the §6 clearance line and the
`--exclude-ids` argument):

```
6c3f98e8-122b-4761-a20f-d603d500a568,6d29133c-3730-4fab-a808-5504184504e0,3ee0b684-cfee-4559-a49c-275b6b1a58e2,3fcfa433-de88-40ba-baaa-226a46d62391
```

Order of IDs in the CSV is not semantically significant;
however the CSV above is the canonical form and is what the
§6 clearance line must cite verbatim.

## 3. Resulting clean posting set (informational; 5 docs)

Under the amended list, the remaining Phase B candidates are:

| # | doc_id | Vendor (extracted → resolved) | Invoice # | $ |
|---|---|---|---|---|
| 1 | `2afa5aeb-dd57-4a9a-9741-3730022b8364` | PROGRESSIVE LOGISTICS | 130461 | 13.00 |
| 2 | `4a282510-4306-4f25-bdf6-9e7565519706` | PROGRESSIVE LOGISTICS | 00130390 | 321.50 |
| 3 | `0813830a-b564-4a72-8b92-c119363fa4fa` | Tumalo Creek Transportation → `TUMALOC` | 0304874 | 3,450.00 |
| 4 | `83a5bbbf-6c6a-41b1-8f1c-e8ce792b5b3d` | Tumalo Creek Transportation → `TUMALOC` | 0304867 | 1,750.00 |
| 5 | `2287ec61-11d6-4ff3-9351-03dc5735860a` | Mexus, Inc. → `MEXUS` | 86431 | 180.00 |

- Clean-set doc count: **5**
- Clean-set total: **$5,714.50**

This list is informational — the runner resolves the post set
at `post` time from `(candidate pool − exclude list)`. The
amendment does not pre-commit to the 5-doc clean-set composition
if the pool shifts between this amendment and Phase B; the
§5 evidence requirements below handle that.

## 4. Phase A status under the amended list

- G0 backend-not-throttled: **PASS** (log-tail 0 lines,
  `/api/health` 200 in 16 ms, Mongo RTT 19 ms on 5,779 docs).
- G1 preflight: **PASS** (all 6 sub-checks green; write→Sandbox,
  `block_prod=True`, `pilot_mode=True`, `read_only=True`,
  catalog fresh at 19.7 h).
- G2 dry-run: **PASS** (exit 0, 9 candidates, clean summary).
- Sweep: at_risk=2, safe=7; the 2 sweep-at_risk IDs are both
  in the amended list.
- §4.6 pinned-in-pool: **PASS** — all 4 amended-list IDs are
  present in the authoritative G2 candidate pool
  (`dryrun.txt` entries `[7]`, `[8]`, `[3]`, `[9]`).
- Exclude-list integrity (§3.8 as amended): **PASS** — the
  4-ID CSV in §2 is the canonical pinned list.

**Phase A is declared CLEAR under this amendment, and only
under this amendment.**

## 5. Fresh evidence requirement before §6 clearance

This amendment does **not** indefinitely extend Phase A
clearance. Before the §6 clearance line is issued and Phase B
runs, the operator must confirm in the same SSH session:

1. G0 re-probed and still PASS (log-tail clean, `/api/health`
   < 2 s, Mongo RTT < 1 s).
2. G1 preflight re-run and still PASS.
3. G2 dry-run re-run and still shows:
   - all 4 amended-list IDs present in the candidate pool, and
   - no new risk-annotated doc outside the amended list.
4. Fresh sweep still reports `at_risk` ⊆ amended list.

If any of (1)–(4) fails, Phase B does not run; this amendment
is re-evaluated. The operator is not required to paste a new
§5 bundle unless an abnormality surfaces — a one-line operator
note confirming (1)–(4) is sufficient to carry the §6 clearance.

Same-session rule: the §6 clearance line and the subsequent
`post --confirm` invocation must occur in the same SSH session
as the confirmations above. If the session drops, restart the
runbook from Step 0.

## 6. Explicit Phase B clearance line (amended)

Phase B may only begin after the operator delivers the
following clearance line **verbatim** in a subsequent message,
after confirming §5:

> `Phase B clear — proceed with --exclude-ids "6c3f98e8-122b-4761-a20f-d603d500a568,6d29133c-3730-4fab-a808-5504184504e0,3ee0b684-cfee-4559-a49c-275b6b1a58e2,3fcfa433-de88-40ba-baaa-226a46d62391"`

Any deviation from that line — different IDs, fewer IDs, extra
IDs, reworded clearance, missing `--exclude-ids` argument — is
**not cleared**. Phase B does not begin.

The clearance line is scoped to a single `post --confirm`
attempt. A second attempt requires a fresh §5 confirmation and
a fresh clearance line.

## 7. Post-batch verification (unchanged reference)

After Phase B, the operator runs the runbook's Step 9 read-only
verification probe (`BATCH_3_POST_verification.json`) and pastes
back Step 8 stdout + Step 9 output. Agent records the per-doc
bucket breakdown (P/E/S) and updates
`prod_reports/TIER1_BATCH_RESULTS.md` under a separate
post-batch reporting declaration — not under this amendment.

## 8. Recorded gaps (not fixed here)

This amendment explicitly records, but does **not** fix, the
following gaps for later signed tracks:

- **Sweep heuristic gap.** The sweep's narrow at_risk flag did
  not surface CITICARGO (`3ee0b684-…`) nor the Tumalo
  header-only (`3fcfa433-…`). The dry-run caught both. A
  separate signed track can tighten the sweep to match the
  dry-run's risk annotations when prioritized.
- **G3 snapshot query gap.** The runbook's G3 Mongo query is
  narrower than the runner's `phase_select`. Two candidates
  (`FIFTHSTR`, `CARGOMO`) appeared in the G3 snapshot but were
  not in the G2 dry-run, and one pinned ID (`6c3f98e8-…`)
  appeared in the G2 dry-run but not in an earlier G3
  snapshot. The runner's `phase_select` is authoritative. A
  separate signed track can align the G3 snapshot with
  `phase_select` when prioritized.
- **`doc_prestamp_or_fallback → CREAT` resolver class.** Two
  NEW-CLASS docs are parked pending a resolver investigation
  under its own separate signed declaration when prioritized.
- **Header-only PI policy.** Still in backlog. The header-only
  Tumalo doc is excluded here; the policy itself remains
  unreopened.
- **CITICARGO vendor-mapping investigation.** Still parked.
  The doc is excluded here; the investigation remains
  unreopened.

Engineering does not fix any of these inline. All require their
own signed scopes.

## 9. Sign request

To proceed to the fresh §5 confirmation and the §6 clearance:

- **"Sign as-is"** → the amended 4-ID pinned list in §2 is the
  canonical Batch-3 exclude list. The next operator action is
  the fresh §5 same-session confirmation, followed by the
  verbatim §6 clearance line. No code, no script edits, no doc
  mutations, no posting occur on the back of this amendment
  alone.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → Phase B stays blocked; Lane 1 idles; separate
  tracks handle CITICARGO / header-only / CREAT fallback on
  their own timelines.

## 10. What this amendment deliberately does NOT do

- Does not authorize any BC post (sandbox or prod).
- Does not grant Phase B. §6 clearance is a separate message.
- Does not modify `tier1_batch_runner.py`, the sweep, self-heal,
  or any other script.
- Does not heal, promote, demote, or otherwise mutate the 4
  excluded docs. They stay in whatever status they currently
  hold; the amendment only keeps them out of this batch.
- Does not reopen the investigations behind the 4 excluded
  classes.
- Does not pre-commit the clean-set composition if the pool
  shifts; §5 handles shifts.
- Does not extend Phase A clearance beyond the same-session
  §5 confirmation window.
- Does not expand or shrink the amended list without another
  signed amendment.
- Does not relax any §0 fence of the re-entry declaration.
