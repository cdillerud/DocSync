# Accounting UAT Plan — Lane 2 (PLAN-ONLY)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature.
- Scope: define what accounting staff can safely test **right
  now**, during Phase 1 — AP Hardening and Controlled Rollout,
  in parallel with Lane 1 (safe AP sandbox execution) and
  Lane 3 (sales non-posting UAT).
- Parent: `FAST_TRACK_EXECUTION_PLAN.md`.
- This is a **read-only UAT lane**. No production writes, no
  sandbox posts initiated by accounting users, no data
  mutations by accounting users.

## 0. Out-of-scope fence

Accounting UAT users do **not**:

- Click any “Post to BC” action. Posting remains Lane 1 only,
  behind the signed Phase B clearance line.
- Edit vendor master, aliases, or extraction profiles.
- Invoke any script (self-heal, orphan unstick, sweep, runner).
- Manually change document status / workflow_status.
- Re-run extraction on a document.
- Change the exclude list.
- Touch any Lane 3 (sales) surface.
- Open a parked-class investigation
  (SMC / SC-YANDELL / CITICARGO / Smurfit / GROUPWA-SEAQUIS /
  `CREAT` fallback). Matches to those are filed as
  `KNOWN-CLASS` findings and closed.

## 1. Goal

Get accounting eyes on the existing AP surfaces early, in a
controlled way, so we learn:

- Whether the **extracted fields** look right to an accountant
  on real documents.
- Whether the **exception / validation** surfaces are clear.
- Whether the **posting candidate** view matches accounting
  intuition before sandbox posting happens.
- Whether **sandbox posting results** (landed by Lane 1) look
  correct to accounting.

Findings feed into engineering through the issue template in
§7. Engineering does not act on findings inline; fixes go
through the existing signed-declaration discipline.

## 2. Cohort + access

- **Size:** ≤ 3 accounting users in round 1.
- **Named participants:** TBD at sign time (no silent
  expansion).
- **Access:** existing accountant-role hub login. No new
  permissions are granted by this plan.
- **Environment:** sandbox-connected environment only. Users
  must never be pointed at a prod-BC-connected environment for
  UAT.

## 3. What accounting can look at

All read-only, observation-only:

1. **Document intake queue.** The list of recently arrived AP
   documents with sender, received time, classification, and
   current status.
2. **Extracted-field panel.** Per document: vendor canonical,
   vendor number, invoice number, total, line items if
   surfaced, currency, invoice date, due date.
3. **Vendor / invoice / amount sanity.** Does the resolved BC
   vendor match the document? Does the invoice number match
   the PDF? Does the total match?
4. **Exception / validation panel.** Reasons a document is not
   eligible for posting (missing fields, ambiguous vendor,
   mismatch, blocked class, etc.).
5. **Posting-candidate view.** The set of documents currently
   eligible for Tier-1 posting (equivalent to the Lane 1
   candidate pool snapshot, surfaced in the UI).
6. **Sandbox posting results.** For batches Lane 1 has already
   run: which docs landed (P-bucket), which were excluded, which
   errored. Cross-check against accounting’s own expectation.

## 4. What accounting should NOT do

- Not click any post / submit / send-to-BC control.
- Not edit extracted values even if they look wrong. Filing a
  finding is the correct action.
- Not escalate a single finding into a vendor-master or profile
  fix. That is engineering work behind a signed declaration.
- Not assume a parked-class finding (SMC / SC-YANDELL /
  CITICARGO / Smurfit / GROUPWA-SEAQUIS / `CREAT` fallback)
  is a new bug. Refer to §7 triage bucket `KNOWN-CLASS`.
- Not share sandbox URLs, test data, or document contents
  outside the UAT cohort.

## 5. Lightweight test script (per session)

Each session is ≤ 45 minutes. Run twice per week. Each user
follows the same script; findings are per-session, per-doc.

### Session steps

1. **Open the AP document intake queue.** Note the top 10
   docs by received time.
2. For each of the top 10:
   a. Open the document.
   b. Compare extracted **vendor canonical** and
      **bc_vendor_number** against what the PDF/email suggests.
   c. Compare extracted **invoice number** and **total**
      against the PDF.
   d. Read the exception / validation panel.
   e. If the doc is in the posting-candidate view, note
      whether you would approve it as an accountant based on
      the panel alone.
3. **Open the posting-candidate view.** Note how many docs are
   listed and whether any surprise you (vendor you don’t
   recognize, total you would question, vendor you would
   refuse to pay).
4. **Open the latest Lane-1 sandbox result** (if one was run
   since your last session). For each posted doc:
   a. Does the vendor look correct?
   b. Does the amount look correct?
   c. Does the invoice number look correct?
5. **File findings** per §7 template. One finding per doc,
   not one combined entry.

### What to pay extra attention to

- Unknown vendor canonicals mapping to `CREAT` or other
  non-descriptive BC numbers.
- Totals that are orders-of-magnitude wrong (currency unit
  confusion, comma vs period).
- Invoice numbers that look like dates or PO numbers instead
  of invoice numbers.
- Documents stuck in an exception state for reasons you can’t
  read in plain English.
- Sandbox posts that landed but for a vendor or amount you
  think is wrong.

## 6. Triage buckets (filled in by engineering, not the user)

Every accounting finding is triaged into exactly one:

- `EXPECTED` — matches known behaviour; close.
- `KNOWN-CLASS` — matches an already-parked class. Attach to
  that track; no inline fix.
- `NEW-CLASS` — no known class fits; candidate for a new signed
  investigation declaration. No inline fix.
- `UX-ONLY` — UI/copy/nav issue only; queued for a UX-only
  declaration.

## 7. Issue template

Each finding filed as:

```
Finding ID: (auto)
Submitter: <username>
Session date (UTC): <YYYY-MM-DD>
Doc id (AP): <uuid if available, otherwise best identifier>
Surface: intake | extraction | exception | candidate | sandbox-result
Vendor (extracted): <value>
BC vendor number (extracted): <value>
Invoice number (extracted): <value>
Total (extracted): <value>
What I observed:
  <one paragraph, plain English>
What I would have expected:
  <one paragraph, plain English>
Severity (submitter estimate):
  blocker | major | minor | cosmetic
Attachments:
  <screenshot or copied panel text if possible>

--- (engineering-only below) ---
Triage bucket: EXPECTED | KNOWN-CLASS | NEW-CLASS | UX-ONLY
Parked-class reference (if KNOWN-CLASS):
  SMC | SC-YANDELL | CITICARGO | SMURFIT | GROUPWA-SEAQUIS |
  CREAT-FALLBACK
Engineering action: none-inline (standard)
Follow-up declaration: <name or “n/a”>
```

Findings are gathered in a shared location (Airtable / Sheets /
issue tracker of choice — decided at sign time). This plan
does not create new engineering infrastructure.

## 8. Cadence + success

- Twice per week, ≤ 45 minutes per session.
- Target over 2 weeks: ≥ 2 users × 2 sessions × 3 findings =
  ≥ 12 findings triaged by bucket.
- Success = accounting has filed findings, each finding is in
  a triage bucket, no finding has been silently acted on by
  engineering outside the signed-declaration discipline.

## 9. Escalation

- A `blocker` severity finding that is also `NEW-CLASS` is
  escalated to engineering within 24h for a decision on whether
  to draft a new signed investigation declaration. No inline
  fix.
- A finding that touches the pinned Batch-3 exclude list
  (`6c3f98e8-...`, `6d29133c-...`) is escalated to the signing
  operator, not patched.
- Any finding that would require a production BC write is
  **rejected at triage**. Accounting UAT is sandbox-only.

## 10. Sign request

- **"Sign as-is"** → plan goes live with ≤ 3 named users.
  Engineering wires the shared finding-capture location and
  shares access with the cohort.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

Signing this plan does **not** grant any posting authority to
accounting users. Lane 1 continues to be gated on the Batch-3
re-entry declaration and the §6 Phase B clearance line.
