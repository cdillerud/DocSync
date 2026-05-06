# Square9 Cutover Readiness — Proof Pack Summary

_Decision_: **NO-GO**

- Proof dir: `prod_reports/cutover_proof_2026-05-06T19-40-53Z`
- Started UTC: 2026-05-06T19:40:53Z
- Finished UTC: 2026-05-06T19:40:53Z
- match_rate_pct: **unknown**  (min required: 85.00%)
- Steps: total=9 ok=0 ok_signal=9 fail=0

## Blockers
- match_rate_pct unavailable (parity JSON missing or unparseable)

## Steps

| # | id | label | rc | status | duration_sec |
| - | -- | ----- | -- | ------ | ------------ |
| 1 | ap_cutover_readiness_report | AP cutover readiness report | 2 | ok_signal | 0 |
| 2 | billing_intake_routing_probe | Billing intake routing probe | 2 | ok_signal | 0 |
| 3 | square9_hub_ap_parity_report | Square9 Hub-AP parity report | 2 | ok_signal | 0 |
| 4 | square9_only_triage_resolver | Square9-only triage resolver | 2 | ok_signal | 0 |
| 5 | bucket_A_root_cause_report | Bucket A root-cause report | 2 | ok_signal | 0 |
| 6 | bucket_C_intake_gap_report | Bucket C intake-gap report | 2 | ok_signal | 0 |
| 7 | bucket_A_misrouting_remediation_plan | Bucket A misrouting remediation plan | 2 | ok_signal | 0 |
| 8 | bucket_C_intake_remediation_plan | Bucket C intake remediation plan | 2 | ok_signal | 0 |
| 9 | email_poll_watermark_probe | mail_poll_runs health summary | 2 | ok_signal | 0 |

> READ-ONLY proof pack. No Mongo writes, no Exchange changes, no Square9 cutover triggers.
