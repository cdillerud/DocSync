# Square9 Cutover Plan — PLAN-ONLY (NO CODE, NO DATA CHANGES, NO CUTOVER)

- Author/agent: Emergent fork agent
- Generated: 2026-05-01 (UTC)
- Status: DRAFT — awaiting user signature.
- Document class: week-long execution plan with explicit gates.
- Locked input: `/app/memory/SQUARE9_CUTOVER_GAP_AUDIT.md`
  (signed 2026-05-01) — the audit's classifications are
  treated as fixed baseline.
- Parallel artifacts in force:
  - `FAST_TRACK_EXECUTION_PLAN.md` (3-lane posture active)
  - `BATCH_3_POST_REPORT_DECLARATION.md` (Batch-3 closed,
    clearance consumed)
  - `ACCOUNTING_UAT_PLAN.md`, `SALES_UAT_PLAN.md` (signed,
    awaiting cohort + capture location)

## 0. Out-of-scope fence (NON-NEGOTIABLE)

This plan does **not**:

- Authorize the Square9 cutover. The cutover requires its own
  separate verbatim §10 clearance line (analogous to Batch-3
  §6).
- Modify any backend or frontend code by being signed. Code
  for G1 / G2 / conditional gates only happens after this plan
  signs and only inside the gate boundaries below; each gate
  has its own ship/no-ship criterion.
- Mutate any document, vendor, alias, or profile.
- Re-open any parked AP class
  (CARGOMO FREIGHT-WH, CITICARGO mapping, header-only PI,
  `doc_prestamp_or_fallback → CREAT`, SMC, SC-YANDELL,
  Smurfit, GROUPWA-SEAQUIS).
- Touch `tier1_batch_runner.py`, `vendor_mismatch_sweep.py`,
  self-heal, or orphan unstick scripts.
- Reactivate the consumed Batch-3 §6 clearance.
- Author any production BC write (sandbox-only writes through
  the existing AP path remain permitted under their own signed
  declarations; no new BC writes are introduced by this plan).
- Open Phase 4C(b) DocuSign live-path work. (Parked.)
- Perform HTTPS migration. (Parked.)
- Engineer around backend capacity. (Out of scope.)
- Expand scope beyond the audit's classifications. Anything
  outside `BUILD-THIS-WEEK` or a Day-1-flipped conditional gate
  requires a separate signed amendment.
- Modify the Square9 cutover endpoints
  (`archive-stage-data`, `restore-stage-data`,
  `migration-status`). They are used as-is.

## 1. Goal

Stand up enough end-user surface inside the hub by Thursday
EOD that on Friday a single authorized
`POST /api/square9/archive-stage-data` call can fire **without
a user-visible regression in document routing, classification,
or routine retrieval**, with `restore-stage-data` ready as the
rollback path.

## 2. Locked classifications (from the audit)

Treated as fixed input. Not re-debated.

| Bucket | Items |
|---|---|
| `BUILD-THIS-WEEK` | **G1** retrieval-oriented frontend page over `GET /api/documents/search`. **G2** sales mailbox (`hub-sales-intake@`) polling diagnosis + enablement. |
| `VALIDATE DAY-1` | **C1** historical Square9 archive reachability. **C2** warehouse/shipping mailbox path. **C3** non-AP drawer/folder browse coverage. **C4** manual page-range split UX usage. **C5** scanner/MFP inflow. |
| `ALREADY-COVERED` | AP intake/classification/extraction/vendor matching/BC validation/SharePoint upload, backend search, splitting backend, vendor drill-down, Square9 stage tracking, cutover toggle + restore. |
| `DEFER-NOT-USER-VISIBLE` | Retry counter auto-delete, location code validation, Easy Lookup, International12h flag, custom indexing fields, `OTHER` auto-routing. |

## 3. Day-by-day sequence (Mon–Fri)

### Mon — Day-1 evidence + G2 root-cause

Read-only morning, scoped code work in the afternoon if and
only if Day-1 evidence supports it.

| Slot | Track | Action | Output |
|---|---|---|---|
| AM | C1 | Inventory the Square9 historical archive vs `hub_documents` and SharePoint. | `prod_reports/SQ9_DAY1_C1_archive_reach.md` |
| AM | C2 | `mail_intake_log` last-7d aggregation by mailbox + classified `doc_type`; cross with `mailbox_sources`. | `prod_reports/SQ9_DAY1_C2_mailboxes.md` |
| AM | C3 | Operator-side UI walkthrough of `DocTypeDashboardPage`, `UnifiedQueuePage`, `DocumentsHubPage` for non-AP types. | `prod_reports/SQ9_DAY1_C3_browse_coverage.md` |
| AM | C4 | `db.workflow_events.find({event_type: /split/i, ts: last 30d}).count()` and operator confirmation. | `prod_reports/SQ9_DAY1_C4_split_usage.md` |
| AM | C5 | Operator confirmation + `mail_intake_log` sender-pattern scan for scanner devices. | `prod_reports/SQ9_DAY1_C5_scanner.md` |
| AM | G2 root-cause | `mailbox_sources` query for `hub-sales-intake@`; `mail_intake_log` count for that mailbox; backend log scan for sales-poller errors. Identify whether the cause is creds, scheduler, mailbox empty, or disabled. | `prod_reports/SQ9_DAY1_G2_rootcause.md` |
| PM | Gate G2 fix | If root cause is config (creds / scheduler / disabled flag): apply minimal config fix only. **No new poller code.** Re-run for one cycle, confirm `mail_intake_log` rows appear. | Updated config + 1 cycle evidence in same report. |
| PM | Gate G1 scaffold | If `SearchPage.js` does not exist: create it as a thin wrapper over `GET /api/documents/search`. Skeleton only Mon; routing wire-up. | `frontend/src/pages/SearchPage.js` (skeleton); route entry. |

Day-1 stop conditions (any → halt and report):
- C1 reveals a meaningful unmirrored Square9 archive that users
  actively retrieve from. Reclassify C1 as `BUILD-THIS-WEEK` or
  `DEFER-WITH-FALLBACK` under a separate amendment.
- C5 reveals an active scanner/MFP inflow. Halt the cutover
  scope and re-evaluate.
- G2 root cause is something other than config (e.g., a
  fundamental Graph permission change or missing service
  identity). Treat as a separate signed track; do not extend
  this plan inline.

### Tue — G1 build, G2 stabilize, conditional gates if any flipped

| Slot | Track | Action | Acceptance |
|---|---|---|---|
| AM | G1 | Search filters wired (doc_type, vendor_canonical, customer, created_utc range, free-text). Each result row links to `DocumentDetailPage` and to `sharepoint_web_url` if present. | Filter combinations return correct subset; no console errors; `data-testid` set on all controls. |
| AM | G2 | Run a full sales-mailbox poll cycle. Confirm at least one `mail_intake_log` row from `hub-sales-intake@`. If zero, halt and amend. | ≥ 1 ingested doc OR confirmed-empty mailbox with sender-side test. |
| AM/PM | Conditional | For each C1–C5 that Day-1 flipped to `BUILD-THIS-WEEK`, scope the smallest UI/config change. No new domain logic. | Per-gate acceptance written into `prod_reports/SQ9_DAY2_<gate>.md`. |
| PM | Tests | Backend smoke: curl `GET /api/documents/search?q=...` for ≥ 5 known doc shapes. Frontend smoke: render SearchPage; verify result mapping. | Smoke pass. |

### Wed — Hardening + parallel shadow start

| Slot | Track | Action | Acceptance |
|---|---|---|---|
| AM | G1 | Edge cases: empty query, 0 results, very large result sets, sort by `created_utc` desc default, deep-link to a result. | Manual sweep + smoke. |
| AM | G2 | Repeat poll cycles every standard interval; confirm zero error spikes. | Stable across 3+ cycles. |
| PM | **Parallel shadow start** | Square9 stays **active** (no toggle). Hub serves all user surfaces in parallel. Day-end snapshot of any user-reported gaps. | Snapshot artifact: `prod_reports/SQ9_SHADOW_DAY1.md`. |
| PM | Lane 2 / Lane 3 | If cohort + capture location have been provided, cohort begins the same lightweight test scripts (see UAT plans), explicitly attempting the cutover-relevant flows: search historical, route new email, browse non-AP. Lane 2 cohort is the natural canary for "no user notices." | Findings filed under existing UAT triage buckets. |

### Thu — Shadow continues + cutover readiness review

| Slot | Track | Action | Acceptance |
|---|---|---|---|
| AM | Parallel shadow | 24h since shadow start. Capture user-side discrepancy log (anything users had to do in Square9 that they couldn't do in the hub). | `prod_reports/SQ9_SHADOW_DAY2.md`. |
| PM | Cutover readiness review | Walk the audit's risk register row by row against shadow evidence. Each risk → `mitigated` / `unmitigated` / `accepted`. Any `unmitigated` blocks Friday. | `prod_reports/SQ9_READINESS_REVIEW.md`. |
| PM | Restore drill | Read-only verification that `POST /api/square9/restore-stage-data` is reachable, that the cutover endpoints return expected shapes, and that `migration-status` reports `cutover_readiness=ready`. **Do not invoke** archive-stage-data. | One-line operator note confirming probes returned 200. |

### Fri — Cutover gate + execution + monitoring window

Cutover only proceeds if all of the following hold by Friday
AM (operator confirms each as a one-liner, no fresh evidence
bundle required unless an item failed):

1. G1 ship gate: SearchPage live in production hub; smoke pass.
2. G2 ship gate: sales mailbox poller confirmed ingesting in
   the last 24h.
3. All Day-1 conditional gates resolved
   (`BUILD-THIS-WEEK` items shipped; `DEFER-NOT-USER-VISIBLE`
   items signed off as accepted).
4. Shadow drill (Wed PM → Fri AM, ≥ 36h) shows zero
   `unmitigated` user-visible gaps in the Thu readiness review.
5. Lane 1 (AP) posture is unchanged: Batch-3 clearance still
   consumed; no new at_risk class surfaced; `block_prod=True`,
   `pilot_mode=True`, `read_only=True`.
6. Restore drill (Thu PM) returned green.
7. Operator (signing operator of record) is available for the
   30-minute post-cutover monitoring window.

If any of (1)–(7) fails, **cutover does not run.** A separate
amendment defers the firing day.

If all hold, the operator delivers the §10 verbatim clearance
line and the cutover executes per §11.

Friday afternoon: 30-minute live monitoring window; users
attempt routine flows in the hub; any regression triggers the
§12 rollback path.

## 4. Gate G1 — retrieval-oriented frontend page

| Item | Detail |
|---|---|
| Backend | `GET /api/documents/search` (already shipped). No new backend code. |
| Frontend | New `frontend/src/pages/SearchPage.js`. Single page, no new components beyond what `/components/ui/` already provides. Filters: free-text `q`, `doc_type` multi-select, `vendor_canonical` autocomplete (existing endpoint), `customer` autocomplete, `created_utc` date range, optional `bc_document_no`. Results table with `data-testid` per row + per filter. Click-through to `DocumentDetailPage` and to `sharepoint_web_url`. |
| Routing | Add a route entry for `/search`. Surface a top-nav link visible to all roles. |
| Acceptance | (a) Free-text query returns same results as direct API call. (b) Filters compose correctly. (c) Empty state and 0-result UX shown explicitly. (d) Clicking a result opens `DocumentDetailPage`. (e) SharePoint link opens in new tab when present. (f) Lighthouse accessibility ≥ 90. |
| Out of scope (G1) | No new search filters server-side. No reindexing. No fuzzy logic beyond what the endpoint already does. No multi-tenant scoping changes. |
| Test plan | Self-test (curl + screenshot) for routine flows. If regressions visible, escalate to `testing_agent_v3_fork` for a frontend-only run. |

## 5. Gate G2 — sales mailbox polling enablement

| Item | Detail |
|---|---|
| Root cause options | (a) creds missing for `hub-sales-intake@`. (b) `mailbox_sources` row disabled. (c) scheduler not iterating that mailbox. (d) Graph permissions changed. (e) mailbox legitimately empty. |
| Day-1 disposition | Identify which of (a)–(e) is true via Mon-AM read-only probes. |
| Allowed fix | Config-only: enable a `mailbox_sources` row, add a missing cred to `.env` (preserving the `<PROTECTED_VARIABLES>` rule for frontend `REACT_APP_BACKEND_URL` and backend `MONGO_URL` / `DB_NAME`), or wire the existing poller to include the mailbox. **No new poller code.** |
| Acceptance | (a) ≥ 1 doc lands in `mail_intake_log` from `hub-sales-intake@` after the fix. (b) The doc classifies cleanly through the existing AI classifier. (c) The doc routes per existing `folder_routing_service.py` logic. |
| Edge case | If the mailbox is legitimately empty (no inbound POs), G2 acceptance is met by a sender-side test PO from a known address with hub-side ingest evidence. |
| Out of scope (G2) | No new sales-side workflow. No new sales pipeline plumbing. The audit explicitly placed those in Lane-3 / future-batch territory. |

## 6. Conditional gates C1–C5 — handling

Each conditional gate has three possible Day-1 outcomes:

- **`BUILD-THIS-WEEK`** → minimal scoped change inside this
  plan. Same fence: config / UI wiring / no new domain logic.
  Acceptance written into the gate's Day-2 report.
- **`DEFER-NOT-USER-VISIBLE`** → recorded in the Day-1 report
  with operator sign-off; no further action this week.
- **`DEFER-WITH-FALLBACK`** → user-visible but cannot ship
  inside the week; document the fallback path (e.g., Square9
  stays alive as a backend archive read-only and is surfaced
  from the hub UI as a clearly-labeled link). Requires its own
  amendment.

Concrete C-gate-specific outcome rules:

- **C1 (archive reach):** if Square9 holds documents not in
  hub or SharePoint that users retrieve normally, default is
  `DEFER-WITH-FALLBACK` for this week.
- **C2 (warehouse/shipping mailbox):** if a separate mailbox
  exists and isn't polling, default is `BUILD-THIS-WEEK`
  (mirrors G2 semantics — config-only fix).
- **C3 (drawer/folder browse):** if non-AP browse is
  inadequate, default is `BUILD-THIS-WEEK` only if the gap is
  trivially fillable from existing components; otherwise
  `DEFER-WITH-FALLBACK` (tell users to use SearchPage from G1
  instead).
- **C4 (split UX):** if used in last 30 days, default is
  `BUILD-THIS-WEEK`. If unused, `DEFER-NOT-USER-VISIBLE`.
- **C5 (scanner):** if used, default is **halt the cutover
  for that one inflow path** and amend the plan. If unused,
  `DEFER-NOT-USER-VISIBLE`.

## 7. Parallel-shadow phase (Wed PM → Fri AM)

- **Posture:** Square9 stays active; the hub also serves the
  full user surfaces. Both available to users in parallel.
- **Length:** at least **36 hours**, target 48 hours.
- **Evidence:** `prod_reports/SQ9_SHADOW_DAY1.md` (Wed),
  `SQ9_SHADOW_DAY2.md` (Thu).
- **Discrepancy ledger:** any flow a user had to perform in
  Square9 that they could not perform in the hub. Each row
  classified as `mitigated_by_<gate>` / `unmitigated`.
- **Cohort participation:** Lane 2 (accounting) cohort, once
  named, is the natural primary canary. Lane 3 (sales) joins if
  named. Cohorts are not required for shadow validity, but
  their presence raises confidence.
- **Stop condition:** any `unmitigated` row blocks Friday
  cutover.

## 8. Friday cutover readiness review

The Thu PM review walks the audit's risk register row by row.
Output is `prod_reports/SQ9_READINESS_REVIEW.md` with one row
per risk:

| Risk | Mitigation | Evidence | Verdict |
|---|---|---|---|
| Search UX missing | G1 shipped | screenshot + curl | mitigated |
| Sales inflow theoretical | G2 enabled | mail_intake_log row | mitigated |
| Warehouse/shipping path | C2 outcome | day-1 evidence | mitigated / accepted |
| Historical retrieval | C1 outcome | day-1 evidence | mitigated / fallback / unmitigated |
| Manual split | C4 outcome | day-1 evidence | mitigated / accepted |
| Scanner inflow | C5 outcome | day-1 evidence | mitigated / accepted / **blocking** |
| Cutover regression | restore drill | thu PM probe | mitigated |

Any `unmitigated` or `blocking` row → cutover does not run.

## 9. Lane 1 / Lane 2 / Lane 3 interaction

- **Lane 1 (AP execution):** **fully unchanged.** Batch-3 is
  closed and the consumed §6 clearance does not return. Any
  future AP batch follows its own full declaration cycle and
  is independent of the Square9 cutover.
- **Lane 2 (Accounting UAT):** can shadow-test cutover-relevant
  flows once cohort + capture location are provided. Findings
  filed in the UAT plan's existing triage buckets.
- **Lane 3 (Sales UAT):** same posture as Lane 2 for
  sales-side flows. Sales posting remains not live.

This plan does **not** consume Lane 2 or Lane 3 sign authority;
both lanes proceed under their already-signed UAT plans.

## 10. Explicit Friday cutover clearance line

Cutover may only run after the operator delivers the
following clearance line **verbatim** in a subsequent Friday
message, after the §3 Friday gate (1)–(7) is satisfied:

> `Square9 cutover clear — proceed with POST /api/square9/archive-stage-data {"confirm": true}`

Any deviation from that line — different verb, missing
confirm flag, different endpoint, reworded clearance — is
**not cleared**. Cutover does not run.

The clearance is **single-attempt**. A second attempt requires
fresh §3 Friday-gate confirmation and a fresh clearance line.

## 11. Cutover execution (Friday only, after §10)

Bare-line operator commands. No markdown fences in the
operator copy. The execution itself is a single API call
plus a verification probe.

Step 11.A — readiness probe (read-only):

    curl -s -o /tmp/sq9_pre.out -w "HTTP %{http_code}\n" http://localhost:8001/api/square9/migration-status

    cat /tmp/sq9_pre.out

Expected: HTTP 200, `cutover_readiness: "ready"`,
`square9_active: true`. Any other shape blocks cutover.

Step 11.B — single cutover invocation:

    curl -s -o prod_reports/SQ9_CUTOVER_response.json -w "HTTP %{http_code}\n" -X POST http://localhost:8001/api/square9/archive-stage-data -H "Content-Type: application/json" -d "{\"confirm\": true}"

    cat prod_reports/SQ9_CUTOVER_response.json

Expected: HTTP 200, `status: "decommissioned"`,
`archived_count` ≥ 0, `archived_at` populated.

Step 11.C — post-cutover probe (read-only):

    curl -s http://localhost:8001/api/square9/migration-status

    docker compose exec -T backend python -u -c "import asyncio,os,json; from motor.motor_asyncio import AsyncIOMotorClient; exec('async def m():\n db=AsyncIOMotorClient(os.environ[\"MONGO_URL\"])[os.environ[\"DB_NAME\"]]\n cfg=await db.hub_config.find_one({\"key\":\"square9_cutover\"},{\"_id\":0})\n print(json.dumps(cfg,default=str,indent=2))'); asyncio.run(m())"

Expected: `square9_active: false`, `archived_at` populated.

Step 11.D — 30-minute live monitoring window:

- Operator (or named cohort, if Lane 2/3 are involved)
  attempts the routine flows from the discrepancy ledger.
- Any regression triggers §12 rollback.

## 12. Rollback / restore posture

If a regression is observed during Step 11.D or in the
72-hour post-cutover window:

Step 12.A — restore (single command):

    curl -s -o prod_reports/SQ9_RESTORE_response.json -w "HTTP %{http_code}\n" -X POST http://localhost:8001/api/square9/restore-stage-data -H "Content-Type: application/json" -d "{\"confirm\": true}"

    cat prod_reports/SQ9_RESTORE_response.json

Expected: HTTP 200, `status: "restored"`, `restored_count`
matches the pre-cutover archive count, `restored_at` populated.

Step 12.B — re-probe `migration-status`. Expect
`square9_active: true`.

Step 12.C — file a restore-incident report under
`prod_reports/SQ9_RESTORE_INCIDENT_<timestamp>.md` with the
specific user-visible regression that triggered rollback.
Plan is then re-evaluated in a separate amendment.

The restore path does **not** require a new clearance line —
rollback is always permitted as a safety action. Re-firing the
cutover after a restore **does** require a fresh full §3 + §10
cycle.

## 13. Reporting requirements

By end of the week, regardless of cutover outcome, the
following reports exist:

- `prod_reports/SQ9_DAY1_C1_archive_reach.md`
- `prod_reports/SQ9_DAY1_C2_mailboxes.md`
- `prod_reports/SQ9_DAY1_C3_browse_coverage.md`
- `prod_reports/SQ9_DAY1_C4_split_usage.md`
- `prod_reports/SQ9_DAY1_C5_scanner.md`
- `prod_reports/SQ9_DAY1_G2_rootcause.md`
- `prod_reports/SQ9_SHADOW_DAY1.md`, `SQ9_SHADOW_DAY2.md`
- `prod_reports/SQ9_READINESS_REVIEW.md`
- `prod_reports/SQ9_CUTOVER_response.json` (Friday only, if
  fired)
- `prod_reports/SQ9_RESTORE_response.json` (only if rollback
  fires)

A separate signed `SQ9_CUTOVER_REPORT_DECLARATION.md` (modeled
on `BATCH_3_POST_REPORT_DECLARATION.md`) is the formal
closeout artifact. Drafted only after the live monitoring
window and only if the user explicitly asks.

## 14. Sign request

- **"Sign as-is"** → plan goes live; Day-1 starts Monday.
  Cutover is **not** authorized by this sign; Friday requires
  the verbatim §10 clearance line.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction; Square9 stays active.

## 15. What this plan deliberately does NOT do

- Does not authorize the Square9 cutover.
- Does not pre-commit any code change. G1 / G2 / conditional
  gate code begins under their own per-gate acceptance criteria
  and is rolled back if any acceptance fails.
- Does not change AP posting posture. Lane 1 stays exactly as
  Batch-3 left it.
- Does not reopen any parked AP class.
- Does not modify the Square9 cutover endpoints themselves.
- Does not touch `tier1_batch_runner.py`, the sweep, self-heal,
  or orphan unstick scripts.
- Does not extend or reissue the consumed Batch-3 §6 clearance.
- Does not commit to any production BC write.
- Does not commit to any HTTPS, DocuSign live-path, capacity,
  or refactor work.
- Does not silently expand the audit's classifications.
