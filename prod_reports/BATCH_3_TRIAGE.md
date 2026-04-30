# Batch-3 Blocker Triage Report

- Generated: 2026-04-30T18:22:52Z (UTC)
- Parent: Batch-3 Sandbox Post Declaration (signed 2026-04-30),
  Phase A blocked.
- Governing declaration: `memory/BATCH_3_BLOCKER_TRIAGE_DECLARATION.md`
  (signed as-is 2026-04-30).
- Posture: read-only. No posting, no dry-run, no script edits,
  no doc mutations, no reopen of SMC / SC-YANDELL / CITICARGO /
  Smurfit / GROUPWA-SEAQUIS tracks.

## A. Mismatch sweep summary (verbatim)

- at_risk: 2
- safe: 7
- source artifact: `prod_reports/BATCH_3_TRIAGE_sweep.md`
  (pulled from `backend:/app/memory/VENDOR_MISMATCH_SWEEP.md`)
- sweep heuristic surface: `vendor_match_method` /
  `bc_match_status` fields on the live Tier-1 candidate pool
  (status=ReadyForPost, workflow_status=ready_for_post,
  bc_purchase_invoice unset).

## B. At-risk docs

### Doc 1

- id: `6c3f98e8-122b-4761-a20f-d603d500a568`
- vendor_canonical: `T.D. LINES, INC.`
- bc_vendor_number: `CREAT`
- vendor_match_method: `doc_prestamp_or_fallback`
- bc_match_status: `at_risk`
- invoice_number: as recorded in sweep artifact (preserved
  verbatim; not re-probed to preserve read-only posture)
- total: as recorded in sweep artifact
- mismatch signature (verbatim from sweep):
  `vendor_canonical="T.D. LINES, INC." → bc_vendor_number="CREAT"
   via vendor_match_method="doc_prestamp_or_fallback"`
- class: **NEW-CLASS**
- disposition: **EXCLUDE-NEW-CLASS**
- rationale: The resolver collapsed the vendor identity onto the
  placeholder/fallback BC vendor number `CREAT` through the
  `doc_prestamp_or_fallback` code path. This pattern does not fit
  any of the already-parked classes (SMC structural rejection,
  SC-Warehouses/YANDELL mixed record, CITICARGO, Smurfit
  WROCKCP↔WESTROCK, GROUPWA-SEAQUIS cosmetic). It is a
  previously-undocumented resolver class — the fallback branch
  is emitting a non-canonical match instead of refusing to resolve.
  Per the triage declaration, NEW-CLASS docs are parked via
  EXCLUDE-NEW-CLASS; no inline heal, no resolver change here.
  A separate signed investigation declaration is required before
  touching the `doc_prestamp_or_fallback` code path.

### Doc 2

- id: `6d29133c-3730-4fab-a808-5504184504e0`
- vendor_canonical: `Parkway Plastics Inc.`
- bc_vendor_number: `CREAT`
- vendor_match_method: `doc_prestamp_or_fallback`
- bc_match_status: `at_risk`
- invoice_number: as recorded in sweep artifact
- total: as recorded in sweep artifact
- mismatch signature (verbatim from sweep):
  `vendor_canonical="Parkway Plastics Inc." → bc_vendor_number="CREAT"
   via vendor_match_method="doc_prestamp_or_fallback"`
- class: **NEW-CLASS**
- disposition: **EXCLUDE-NEW-CLASS**
- rationale: Same resolver collapse as Doc 1 — distinct vendor
  canonical, identical fallback signature terminating at the
  `CREAT` placeholder. Two independent vendors converging on the
  same non-canonical BC number via the same match method is a
  strong signal that `doc_prestamp_or_fallback` is the shared
  contamination surface, not the vendor records themselves. The
  appropriate triage action is still to park both IDs and defer
  the resolver-path investigation to its own signed track.

## C. Preflight-failure triage

- miss signature (from logs): `/api/health` preflight did not
  clear within the runner's timeout window during the Phase A
  attempt. Post-miss log tail shows no sustained
  `RESOURCE_EXHAUSTED`, no 503 cluster, no Gemini throttle
  burst, and no Mongo connection reset during the miss window.
- approximate miss wall-clock (UTC): within the Phase A attempt
  window immediately preceding this triage; single occurrence.
- current `/api/health`: HTTP 200, `t_total ≈ 15 ms` (re-probe
  after the miss).
- current Mongo round-trip: 5,682 documents counted in 17 ms via
  `-T` heredoc probe (well under the 1 s threshold).
- verdict: **TRANSIENT-BLIP**
- rationale: The miss did not reproduce on re-probe. Health and
  Mongo are both an order of magnitude under the stability
  thresholds defined in the triage declaration (§3.5:
  `/api/health` < 2 s, Mongo round-trip < 1 s). Logs show no
  sustained degradation pattern around the miss. This matches
  the declaration's TRANSIENT-BLIP definition. The recommended
  response is operational — wait for a fresh session and re-run
  Phase A once a re-entry declaration is signed. No
  capacity-posture track is opened by this triage.

## D. Recommended re-entry posture

- exclude list for any future Batch-N re-entry:
  - `6c3f98e8-122b-4761-a20f-d603d500a568`  (NEW-CLASS,
    `doc_prestamp_or_fallback → CREAT`, vendor: T.D. LINES, INC.)
  - `6d29133c-3730-4fab-a808-5504184504e0`  (NEW-CLASS,
    `doc_prestamp_or_fallback → CREAT`, vendor: Parkway Plastics Inc.)
- fresh stability check required before Phase A re-entry (all
  must pass in the re-entry session, per §5 of the triage
  declaration):
  - full G0 pass — backend log-tail clean, `/api/health` 200
    in < 2 s, Mongo round-trip < 1 s (with `-T` heredoc on the
    Mongo probe).
  - G1 preflight clean in the same session.
  - fresh `vendor_mismatch_sweep` run showing `at_risk == 0`
    **after subtracting** the exclude list above. If a new
    at_risk candidate appears that is not on this list, re-entry
    aborts and a fresh triage round is required.
- no batch re-entry before a separate signed
  `BATCH_3_RE_ENTRY_DECLARATION.md` that (a) cites this report
  by path, (b) pins the exclude list above verbatim, and
  (c) re-acknowledges the §0 out-of-scope fence of the triage
  declaration.
- deferred tracks (explicitly NOT opened by this report):
  - `doc_prestamp_or_fallback → CREAT` resolver investigation
    (its own signed declaration when prioritized).
  - any capacity-posture / backend-throttling track (not opened;
    verdict is TRANSIENT-BLIP).
  - all previously parked classes (SMC, SC-YANDELL, CITICARGO,
    Smurfit, GROUPWA-SEAQUIS) remain parked.

---

**One-line verdict:**
Batch-3 blocked; 2 at_risk classified as NEW-CLASS / NEW-CLASS
(`doc_prestamp_or_fallback → CREAT`, IDs
`6c3f98e8-122b-4761-a20f-d603d500a568`,
`6d29133c-3730-4fab-a808-5504184504e0`); preflight verdict
TRANSIENT-BLIP; re-entry blocked until
`BATCH_3_RE_ENTRY_DECLARATION.md` is signed.
