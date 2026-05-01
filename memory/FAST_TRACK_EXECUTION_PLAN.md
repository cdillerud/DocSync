# Fast-Track Execution Plan — Parallel Pilot Posture (PLAN-ONLY)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature.
- Phase posture: Phase 1 — AP Hardening and Controlled Rollout
  remains the governing phase. This plan does **not** promote
  anything to production and does **not** move Phase 1 to Phase 2.
- Parent chain:
  - `BATCH_3_SANDBOX_POST_DECLARATION.md` (signed 2026-04-30)
  - `BATCH_3_BLOCKER_TRIAGE_DECLARATION.md` (signed 2026-04-30)
  - `prod_reports/BATCH_3_TRIAGE.md` (committed 2026-04-30)
  - `BATCH_3_RE_ENTRY_DECLARATION.md` (signed 2026-04-30;
    most recent Phase A attempt aborted — pinned doc out of
    pool + G1/G2 no-evidence)

## 0. Out-of-scope fence (NON-NEGOTIABLE)

This plan is operational posture only. It does **not**:

- Authorize production BC writes of any kind.
- Relax any existing signed declaration. Batch-3 posting still
  requires the §6 Phase B clearance line from the re-entry
  declaration.
- Modify `tier1_batch_runner.py`, `vendor_mismatch_sweep.py`,
  self-heal, orphan unstick, or any other AP script.
- Mutate any hub document, vendor master, alias, or profile.
- Heal, promote, or demote any document.
- Reopen SMC, SC Warehouses / YANDELL, CITICARGO, Smurfit,
  GROUPWA / SEAQUIS, or the `doc_prestamp_or_fallback → CREAT`
  resolver investigation. All remain parked.
- Pretend sales posting is production-ready. Sales UAT is
  explicitly non-posting.
- Open a backend-capacity engineering track. Throttle signals
  remain recorded-only per prior declarations.
- Introduce new backend routes, new models, or new workflow
  states. The plan only rearranges who touches existing
  read/observe surfaces and on what cadence.
- Give UAT participants any write capability in Lane 2 or
  Lane 3. All UAT is read/observe + findings capture.

## 1. Why the posture change

The current bottleneck is **process friction**, not code:

- Repeated bespoke evidence capture per attempt.
- Pool churn between checks (pinned-doc drift observed in the
  last attempt).
- Single-thread proof work blocks user feedback on 90% of the
  system that is already usable read-only.

The fix is not to add features or touch code. The fix is to
**run three lanes in parallel** under a shared set of fences.

## 2. The three lanes

### Lane 1 — Safe AP sandbox execution (engineering only)

- **Owner:** AP engineering + signing operator.
- **Allowed:** evidence capture, preflight, dry-run, sandbox
  `post --confirm --exclude-ids "..."` **only after** a verbatim
  §6 Phase B clearance line under a signed re-entry declaration.
- **Forbidden:** production writes. Script edits. Doc mutations
  outside the runner's own authorized writes. Reopening parked
  classes. Relaxing the pinned exclude list without a signed
  amendment.
- **Cadence:** runbook-driven; one attempt per signed clearance.
  See `BATCH_3_OPERATOR_RUNBOOK.md`.

### Lane 2 — Accounting UAT (observe + report)

- **Owner:** accounting user cohort (named below, ≤ 3 users
  in the first round).
- **Allowed:** read the document queue, extracted-field panels,
  exception lists, posting-candidate views, and sandbox posting
  results landed by Lane 1. File findings via the issue
  template in `ACCOUNTING_UAT_PLAN.md`.
- **Forbidden:** no “Post to BC” button usage. No vendor-master
  edits. No alias/profile edits. No self-heal invocations. No
  runner invocations. No reopening parked classes. No sending
  payloads to prod BC.
- **Cadence:** lightweight test script runs twice per week for
  the first 2 weeks.

### Lane 3 — Sales non-posting workflow UAT (observe + report)

- **Owner:** sales user cohort (named below, ≤ 3 users in the
  first round).
- **Allowed:** read intake, classification, customer-PO
  interpretation, order-readiness review, exception review,
  and general usability of the non-posting sales workflow.
  File findings via the issue template in `SALES_UAT_PLAN.md`.
- **Forbidden:** no sales order creation against BC (sandbox
  or prod). No writes to hub docs. No customer-master edits.
  No workflow state transitions that the system does not
  already expose to their role. No implication that sales
  posting is live.
- **Cadence:** lightweight test script runs twice per week for
  the first 2 weeks.

### What is still blocked across all three lanes

- Any production BC write.
- Any AP script code change.
- Any schema change to hub_documents, vendors, aliases,
  profiles, or the contracts collections.
- Any investigation of the parked classes
  (SMC, SC/YANDELL, CITICARGO, Smurfit, GROUPWA/SEAQUIS,
  `doc_prestamp_or_fallback → CREAT`).
- Any broad refactor, directory restructure, or server.py
  breakdown.
- HTTPS migration / frontend origin change.
- DocuSign live-path (Phase 4C(b)) — remains parked on creds.

## 3. Participants

| Lane | Role | Named participants | Access |
|---|---|---|---|
| 1 | Signing operator | (operator of record) | Runner execution under signed clearance only. |
| 1 | AP engineering | (you + agent) | Plan + evidence review. No direct script edits without a separate signed declaration. |
| 2 | Accounting UAT | TBD (≤ 3 users) | Read-only app access to AP queue, extraction, exceptions, posting-candidate and sandbox-result views. |
| 3 | Sales UAT | TBD (≤ 3 users) | Read-only app access to sales intake, classification, PO interpretation, readiness and exception views. |

Cohort names are filled in at sign time. New participants
require an appended amendment; no silent cohort expansion.

## 4. How findings flow back into engineering

Both Lane 2 and Lane 3 use the same issue-capture template
(replicated inside each plan file):

1. User files a finding against a single doc id (AP) or a
   single intake/order id (Sales) using the template.
2. Findings are triaged into one of four buckets:
   - `EXPECTED` — matches known behaviour; close with a
     reference to the relevant parked class or declaration.
   - `KNOWN-CLASS` — matches SMC / SC-YANDELL / CITICARGO /
     Smurfit / GROUPWA-SEAQUIS / `CREAT` fallback. Attach to
     the existing parked track; no inline fix.
   - `NEW-CLASS` — does not match any known class. Filed as
     a candidate for its own signed investigation declaration.
     No inline fix.
   - `UX-ONLY` — visual / copy / navigation issue with no
     data-integrity impact. Queued for a UX-only declaration.
3. Engineering does not act on findings inline. All fixes go
   through the existing signed-declaration discipline.

## 5. Success criteria over the next 2 weeks

This is success, not perfection. Targets are intentionally
modest so we ship the posture rather than argue about it.

- **Lane 1:** at least one successful Batch-3 Phase A → Phase B
  sandbox post cycle under the re-entry declaration (with the
  pinned exclude list — amended in writing if T.D. LINES has
  drifted), with clean §5 evidence bundle.
- **Lane 2:** at least two accounting users complete the
  lightweight test script twice each, producing ≥ 6 findings
  triaged by bucket.
- **Lane 3:** at least two sales users complete the lightweight
  test script twice each, producing ≥ 6 findings triaged by
  bucket.
- **No regressions** in any previously-signed guardrail.
- **No production writes.**
- **No code merged** into `tier1_batch_runner.py`, the sweep,
  self-heal, orphan unstick, or contract scripts during the
  2-week window without its own signed declaration.
- **Parked classes stay parked.** Any UAT finding that fits a
  parked class is filed under `KNOWN-CLASS` and closed.

## 6. What this plan is NOT

- Not a promotion to Phase 2.
- Not a Phase B clearance.
- Not permission to touch production BC.
- Not a silent widening of the Batch-3 exclude list. Any
  change to the pinned exclude list requires a written
  amendment to the re-entry declaration or its successor.
- Not a commitment that sales or accounting features are
  production-ready. UAT is controlled pilot, not GA.
- Not a green light to remove the §0 fences of any existing
  signed declaration.

## 7. Sign request

To proceed:

- **"Sign as-is"** → agent does nothing further until the
  runbook and the two UAT plans are reviewed under their own
  sign requests; Lane 1 execution continues to be gated on the
  existing re-entry declaration's §6 clearance.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

Nothing in this plan grants Phase B or production authority.
Signing it only authorizes the parallel operating posture and
the existence of the three companion artifacts.
