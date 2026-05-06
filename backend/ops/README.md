# Square9 Cutover Readiness — Proof Pack

This directory contains the read-only production verification harness for
the GPI Hub → Square9 cutover. It runs the full cutover-readiness probe
chain in dependency order, captures every artifact under one timestamped
folder, and renders a final **GO / NO-GO** decision based on per-step
exit codes plus the parity report's `match_rate_pct`.

## What it does (and what it does NOT do)

The proof pack is **strictly read-only**. It will:

- run all 9 read-only probes in dependency order
- write every stdout / stderr stream to a per-step log
- snapshot the parity JSON into the proof directory
- emit a manifest (`manifest.json`), a structured summary
  (`summary.json`), and a human-readable summary (`summary.md`)
- print a final **GO / NO-GO** banner and exit `0` (GO) or `1` (NO-GO)

It will **never**:

- write to MongoDB
- change Exchange / mailbox sources / transport rules
- toggle the Square9 cutover
- call `archive-stage-data`
- reclassify documents
- mutate any production state of any kind

## Running it on the prod VM

After `git pull` on the VM:

    docker compose exec backend bash ops/prod_verify_square9_cutover_readiness.sh

That's the entire command. Outputs land under
`prod_reports/cutover_proof_<UTC-timestamp>/`. The host sees them
directly because `prod_reports/` is bind-mounted in
`docker-compose.yml`.

Optional overrides:

    docker compose exec \
        -e MIN_MATCH_RATE=85 \
        -e PROOF_SINCE_HOURS=168 \
        backend bash ops/prod_verify_square9_cutover_readiness.sh

Defaults: `MIN_MATCH_RATE=85.0`, `PROOF_SINCE_HOURS=168` (1 week).
The 168h default is chosen so the parity / triage / bucket stages
have data to operate on; a 24h window typically yields zero
Square9-only triage rows and cascades into FileNotFoundErrors
through the downstream bucket stages.

## Output layout

    prod_reports/cutover_proof_2026-05-06T18-00-00Z/
    ├── manifest.json                 # one entry per step (rc, log path, duration)
    ├── summary.json                  # decision + blockers + per-step status
    ├── summary.md                    # human-readable rendering
    ├── square9_hub_ap_parity.json    # snapshot of the parity report
    └── logs/
        ├── ap_cutover_readiness_report.log
        ├── billing_intake_routing_probe.log
        ├── square9_hub_ap_parity_report.log
        ├── square9_only_triage_resolver.log
        ├── bucket_A_root_cause_report.log
        ├── bucket_C_intake_gap_report.log
        ├── bucket_A_misrouting_remediation_plan.log
        ├── bucket_C_intake_remediation_plan.log
        └── email_poll_watermark_probe.log

## Decision rules

| Condition | Effect on decision |
|---|---|
| Any stage exits with rc ≥ 3 | NO-GO + blocker for that stage |
| Parity JSON missing or unparseable | NO-GO + "match_rate_pct unavailable" blocker |
| `match_rate_pct < MIN_MATCH_RATE` | NO-GO + threshold blocker |
| Otherwise | GO |

Per-step exit codes 0/1/2 are treated as **workflow signals**
(`ok` / `ok_signal`), not failures. This matches the existing repo
convention (e.g. the remediation plan scripts use rc=2 to mean "rows
emitted").

## Stages

| # | id | script |
|---|---|---|
| 1 | `ap_cutover_readiness_report` | `scripts/ap_cutover_readiness_report.py --json` |
| 2 | `billing_intake_routing_probe` | `scripts/billing_intake_routing_probe.py --json` |
| 3 | `square9_hub_ap_parity_report` | `scripts/square9_hub_ap_parity_report.py --json` |
| 4 | `square9_only_triage_resolver` | `scripts/square9_only_triage_resolver.py --triage-csv prod_reports/square9_only_triage.csv` |
| 5 | `bucket_A_root_cause_report` | `scripts/bucket_A_root_cause_report.py` |
| 6 | `bucket_C_intake_gap_report` | `scripts/bucket_C_intake_gap_report.py` |
| 7 | `bucket_A_misrouting_remediation_plan` | `scripts/bucket_A_misrouting_remediation_plan.py` |
| 8 | `bucket_C_intake_remediation_plan` | `scripts/bucket_C_intake_remediation_plan.py` |
| 9 | `email_poll_watermark_probe` | `scripts/email_poll_watermark_probe.py` |

## Tests

Decision-engine logic is covered by
`backend/tests/test_cutover_proof_summary.py` (24 tests, synthetic
fixtures, no Mongo, no network). Run in preview or in the container:

    python -m pytest tests/test_cutover_proof_summary.py -v

## Files

- `backend/ops/prod_verify_square9_cutover_readiness.sh` — bash orchestrator
- `backend/ops/cutover_proof_summary.py` — Python summarizer + decision engine
- `backend/ops/README.md` — this file

(Inside the container these resolve to `/app/ops/...` because the
backend image's `WORKDIR` is `/app` and the Dockerfile copies the
`backend/` tree there.)
