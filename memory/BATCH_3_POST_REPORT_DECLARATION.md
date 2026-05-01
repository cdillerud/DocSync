# Batch-3 Post-Report — Closeout Declaration (PLAN-ONLY)

- Author/agent: Emergent fork agent
- Generated: 2026-05-01 (UTC)
- Status: DRAFT — awaiting user signature.
- Document class: **formal closeout record** for an executed
  Batch-3 AP sandbox posting cycle. Suitable for internal audit
  and executive reference.
- No code changes. No data changes. No posting. No reopening
  of parked classes. No Batch-4 opened.

## 1. Goal

Formally close out Batch-3 as a completed AP sandbox posting
cycle, capture its business and operational significance, pin
the exact audit trail used to authorize it, and restore the
full fence posture so no authority carries forward.

## 2. Scope

This declaration includes, and only includes:

- The 5 documents posted to BC sandbox under Batch-3.
- The 4 documents excluded under the amended pinned list.
- The exact clearance/audit chain that authorized the single
  `post --confirm` attempt.
- The cumulative AP proof points established as of Batch-3.
- The explicit closeout posture and re-armed fences.

It does not include:

- Any new batch authorization.
- Any investigation of the excluded classes.
- Any script, schema, or workflow change.
- Any production BC posting.
- Any reopening of previously-parked tracks.
- Any UAT lane sign-off (Lanes 2/3 proceed under their own
  signed plans).

## 3. Batch-3 summary

| Field | Value |
|---|---|
| Phase | Phase 1 — AP Hardening and Controlled Rollout |
| Environment | BC sandbox (`Sandbox_11_3_2025`, `block_prod=True`, `pilot_mode=True`, `read_only=True`) |
| Attempt window (UTC) | `2026-05-01T16:06:12Z` (§5 re-confirm) → `2026-05-01T16:27:33Z` (Phase 5 summary) |
| Candidate pool (pre-exclusion) | 9 docs |
| Exclude list size | 4 docs |
| Post set | 5 docs |
| Posted total value | **$5,714.50** |
| Bucket breakdown | P1: 5 · P2: 0 · POLICY: 0 · E: 0 · S: 0 · F-BUG: 0 |
| PASS criterion | ≥ 4/5 in (P1+P2+POLICY) with zero F-BUG |
| Result | **PASS — Tier 1 Viable** |
| Attempt count under clearance | 1 of 1 (single-attempt limit) |
| Clearance status | **Consumed** |
| Exit code | 0 |

## 4. Per-doc posted results

| # | doc_id | Vendor (extracted → resolved) | Invoice # | Amount | Bucket | HTTP | BC Record # | Latency |
|---|---|---|---|---|---|---|---|---|
| 1 | `2afa5aeb-dd57-4a9a-9741-3730022b8364` | PROGRESSIVE LOGISTICS → Progressive Logistics | 130461 | $13.00 | P1 | 200 | **73882** | 6,639 ms |
| 2 | `4a282510-4306-4f25-bdf6-9e7565519706` | PROGRESSIVE LOGISTICS → Progressive Logistics | 00130390 | $321.50 | P1 | 200 | **73883** | 1,314 ms |
| 3 | `0813830a-b564-4a72-8b92-c119363fa4fa` | Tumalo Creek Transportation → `TUMALOC` | 0304874 | $3,450.00 | P1 | 200 | **73884** | 1,853 ms |
| 4 | `83a5bbbf-6c6a-41b1-8f1c-e8ce792b5b3d` | Tumalo Creek Transportation → `TUMALOC` | 0304867 | $1,750.00 | P1 | 200 | **73885** | 1,023 ms |
| 5 | `2287ec61-11d6-4ff3-9351-03dc5735860a` | Mexus, Inc. → `MEXUS` | 86431 | $180.00 | P1 | 200 | **73886** | 2,733 ms |

- Duplicate scan: **clean** on all 5.
- Risk annotations at dry-run: **none** on all 5.
- BC sandbox record numbers issued sequentially (73882 → 73886).
- All posts completed within a 23-second wall-clock window
  under Phase 4 sequential sandbox post mode (cap 10, timeout
  60 s/doc).

## 5. Excluded docs (amended 4-ID pinned list)

| # | doc_id | Vendor → BC resolution | Class | Reason |
|---|---|---|---|---|
| 1 | `6c3f98e8-122b-4761-a20f-d603d500a568` | T.D. LINES, INC. → `CREAT` | NEW-CLASS | `doc_prestamp_or_fallback → CREAT` resolver collapse. Parked per triage report §B Doc 1. |
| 2 | `6d29133c-3730-4fab-a808-5504184504e0` | Parkway Plastics Inc. → `CREAT` | NEW-CLASS | Same `doc_prestamp_or_fallback → CREAT` resolver collapse. Parked per triage report §B Doc 2. |
| 3 | `3ee0b684-cfee-4559-a49c-275b6b1a58e2` | CITICARGO & STORAGE → `112522` | KNOWN-CLASS | Dry-run confirms `VENDOR MISMATCH`. CITICARGO vendor-mapping investigation remains parked. |
| 4 | `3fcfa433-de88-40ba-baaa-226a46d62391` | Tumalo Creek Transportation → `TUMALOC` | KNOWN-CLASS | Dry-run confirms `zero line items extracted — endpoint may post a header-only PI`. Header-only PI policy remains parked in backlog. |

Exclusion enforcement verified in the runner log:

    ⊖ excluding doc 3ee0b684-cfee-4559-a49c-275b6b1a58e2 (matched --exclude-ids)
    ⊖ excluding doc 6c3f98e8-122b-4761-a20f-d603d500a568 (matched --exclude-ids)
    ⊖ excluding doc 6d29133c-3730-4fab-a808-5504184504e0 (matched --exclude-ids)
    ⊖ excluding doc 3fcfa433-de88-40ba-baaa-226a46d62391 (matched --exclude-ids)
    After --exclude-ids: 5 candidate(s) remain.

None of the 4 excluded IDs appear in the posted set. Integrity
of the amended list (§3.8 of the re-entry declaration as
amended) is confirmed.

## 6. Clearance and declaration lineage

The single `post --confirm` attempt that produced BC records
73882–73886 was authorized by the following chain. Each step
is an artifact of record.

| # | Step | Artifact | Date (UTC) |
|---|---|---|---|
| 1 | Phase-1 sandbox post scope | `/app/memory/BATCH_3_SANDBOX_POST_DECLARATION.md` | 2026-04-30 |
| 2 | Blocker triage (plan-only) | `/app/memory/BATCH_3_BLOCKER_TRIAGE_DECLARATION.md` | 2026-04-30 |
| 3 | Triage report | `/app/prod_reports/BATCH_3_TRIAGE.md` | 2026-04-30 |
| 4 | Re-entry declaration | `/app/memory/BATCH_3_RE_ENTRY_DECLARATION.md` | 2026-04-30 |
| 5 | Parallel posture (umbrella) | `/app/memory/FAST_TRACK_EXECUTION_PLAN.md` | 2026-04-30 |
| 6 | Operator runbook | `/app/memory/BATCH_3_OPERATOR_RUNBOOK.md` | 2026-04-30 |
| 7 | Exclude-list amendment | `/app/memory/BATCH_3_EXCLUDE_LIST_AMENDMENT.md` | 2026-05-01 |
| 8 | Phase A §5 re-confirmation | same SSH session (see §7 below) | 2026-05-01T16:06–16:07Z |
| 9 | §6 verbatim clearance line | delivered by operator in chat | 2026-05-01 |
| 10 | Phase B single `post --confirm` | `prod_reports/BATCH_3_POST_stdout.txt` | 2026-05-01T16:27Z |
| 11 | Post-batch verification probe | `prod_reports/BATCH_3_POST_verification.json` | 2026-05-01T16:27Z |

### Verbatim §6 clearance line (for audit)

    Phase B clear — proceed with --exclude-ids "6c3f98e8-122b-4761-a20f-d603d500a568,6d29133c-3730-4fab-a808-5504184504e0,3ee0b684-cfee-4559-a49c-275b6b1a58e2,3fcfa433-de88-40ba-baaa-226a46d62391"

### Clearance lifecycle

- Scope of the clearance: **one** `post --confirm` attempt in
  one SSH session.
- Status as of this declaration: **consumed**.
- Any subsequent batch, even a retry, requires a fresh full
  cycle (sandbox scope declaration → triage if blockers →
  re-entry declaration → any needed amendment → §5 → §6). No
  steps carry forward.

## 7. Phase A §5 re-confirmation evidence (same-session)

| Check | Evidence |
|---|---|
| Terminal sanity | `echo HELLO` printed `HELLO`; session good. |
| Session window | `2026-05-01T16:06:12Z` → `2026-05-01T16:27:33Z` (single continuous SSH session) |
| G0.a log-tail | 0 lines matching throttle / 5xx / timeout |
| G0.b /api/health | HTTP 200 in 12 ms |
| G0.c Mongo RTT | 5,781 docs in 17 ms |
| G1 preflight | exit 0; all 6 sub-checks green; `write_env=Sandbox_11_3_2025`, `block_prod=True`, `pilot_mode=True`, `read_only=True`; BC catalog fresh at 20.25 h |
| G2 dry-run composition | 9 candidates; identical to amendment evidence |
| G2 risk annotations outside amended list | none |
| Sweep totals | `scanned=1891 matches=1712 mismatches=58 pairs=30`; Batch-2 candidates `total=9 at_risk=2 safe=7`; at_risk ⊆ amended list |

All §3 hard requirements satisfied under the amended list. No
new at_risk class, no new throttle signature, no pinned-doc
drift from the candidate pool.

## 8. What Batch-3 proved

- **AP posting path is operationally viable.** The full
  intake → extraction → candidate selection → exclusion →
  sandbox post → BC-record-number → verification pipeline runs
  end-to-end under controlled authorization and produces
  correct outcomes.
- **The declaration discipline works in practice.** A blocker
  triage, a re-entry declaration, an explicit amendment, a
  same-session §5 re-confirmation, and a verbatim §6 clearance
  line together produced a clean 5/5 P1 result with zero
  F-BUG. No step was skipped; no scope drifted.
- **Exclude lists are effective containment.** Four documents
  in parked or new-class states were cleanly excluded at post
  time, preventing four known-bad postings while five
  acceptable documents landed.
- **Cumulative AP proof points now on record:**
  - Earlier: Progressive Logistics sandbox PI — successful
    (documented in prior batches).
  - Earlier: Mid America sandbox PI — successful, P-bucket
    observed in Batch-2.
  - Batch-3: 5 / 5 P1, 0 F-BUG, $5,714.50 posted to BC
    sandbox across 5 PIs (73882–73886).
- **Operational implication.** The AP hardening phase now has
  three independent positive posting outcomes under progressively
  tighter controls. That is sufficient basis for the parallel
  UAT lanes (accounting read-only review, sales non-posting
  workflow review) to begin in their signed scopes.

## 9. What Batch-3 did NOT solve

Batch-3 is a proof of the **posting pipeline**, not a fix of
the **content gaps** that led to the amended exclude list. The
following remain unsolved and parked:

- **`doc_prestamp_or_fallback → CREAT` resolver class.** Two
  vendors (T.D. LINES, INC. and Parkway Plastics Inc.) still
  collapse to the `CREAT` placeholder through the fallback
  branch. No inline fix. Requires a dedicated signed
  investigation.
- **CITICARGO vendor mapping.** `CITICARGO & STORAGE` still
  resolves to `112522`, which is incorrect. No inline fix.
  Remains parked.
- **Header-only PI policy.** Documents with zero extracted
  line items (e.g., `3fcfa433-…`) are still eligible for the
  candidate pool and must be excluded at post time. The policy
  decision (refuse at runner level vs. accept with a header-only
  bucket) remains in backlog.
- **Mismatch-sweep heuristic gap.** The sweep's at_risk flag
  did not surface the CITICARGO mismatch or the header-only
  Tumalo doc; only the dry-run caught them. Sweep heuristic
  tightening is deferred to its own signed track.
- **G3 Mongo snapshot filter skew.** The runbook's G3 snapshot
  query is narrower than the runner's `phase_select`. Not a
  Batch-3 blocker (G2 is authoritative), but needs alignment
  under a separate track.
- **CARGOMO FREIGHT-WH item-charge 404s.** Visible in historical
  verification probe output (pre-Batch-3). Known issue; not
  touched here.
- **Backend capacity / LLM throttling posture.** Not observed
  as a Batch-3 issue but remains the standing P1 track.

None of the above were introduced by Batch-3. None were fixed
by Batch-3. The proof point is scoped strictly to the five
posted docs and the discipline that authorized them.

## 10. Closeout posture

As of the signing of this declaration:

- **Batch-3 is complete.** BC sandbox records 73882, 73883,
  73884, 73885, 73886 are the canonical artifacts of the
  posting. The `bc_purchase_invoice` fields on the five posted
  hub documents are authoritative for their BC linkage.
- **Batch-3 clearance is exhausted.** The single-attempt §6
  clearance line has been consumed. No further posts are
  authorized under it.
- **No authority carries forward into Batch-4 or any later
  batch.** Future batches require an independent full declaration
  cycle.
- **The amended 4-ID exclude list remains pinned** as a
  reference for any future batch that includes the same
  docs — but the list does not constitute standing
  authorization; each batch re-pins its own exclude set under
  its own declaration chain.
- **All prior fences return to full force.** The operating
  posture is `FAST_TRACK_EXECUTION_PLAN.md` in active state;
  Lane 1 is idle; Lane 2 / Lane 3 await cohort sign-off.

## 11. Out-of-scope fence (restated; remain parked)

- CARGOMO FREIGHT-WH item-charge mapping
- CITICARGO vendor mapping
- Header-only PI policy
- `doc_prestamp_or_fallback → CREAT` resolver
- SMC structural rejection class
- SC Warehouses / YANDELL cleanup
- Smurfit `WROCKCP` / `WESTROCK` ambiguity
- GROUPWA / SEAQUIS cosmetic normalization
- DocuSign live-path (Phase 4C(b)) — parked on credentials
- HTTPS migration
- Backend capacity engineering
- Any production BC posting
- Any broad refactor (including `server.py` breakdown)
- Any script edit to `tier1_batch_runner.py`,
  `vendor_mismatch_sweep.py`, self-heal, or orphan unstick

Each deferred item retains its existing track and will be
addressed under its own signed declaration when prioritized.

## 12. Sign request

- **"Sign as-is"** → this document is the canonical closeout
  artifact for Batch-3. No operator action follows; the
  declaration only fixes the record.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

## 13. What this declaration deliberately does NOT do

- Does not authorize any BC post.
- Does not authorize Batch-4 or any other future batch.
- Does not modify any script or schema.
- Does not heal, promote, demote, or otherwise mutate any
  document.
- Does not reopen any parked class.
- Does not extend or reissue the consumed §6 clearance.
- Does not grant posting authority to accounting or sales UAT
  lanes.
- Does not constitute a capacity-engineering commitment or a
  production-readiness statement.
- Does not pre-commit any exclude list beyond the 4 IDs
  recorded here as the Batch-3 reference.
