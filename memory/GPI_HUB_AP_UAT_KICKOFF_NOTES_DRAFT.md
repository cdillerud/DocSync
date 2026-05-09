# GPI Hub — AP UAT Kickoff Notes (INTERNAL DRAFT)

> **Status:** Internal draft for IT / Engineering review.
> **NOT for distribution to Accounting.**
> Accounting has not been engaged. These notes are the stub of what
> we will eventually hand to AP testers as a ~1-page kickoff sheet on
> Day 0 of the pilot. The tone here will be re-edited for an
> AP-facing audience before any external send.
> **Companion docs (also internal drafts):**
> - `GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md`
> - `GPI_HUB_AP_TEST_FEEDBACK_TEMPLATE.csv`

---

## What this pilot is

A short, time-boxed walk-through of the GPI Hub by a small group of
AP testers. The goal is to confirm — with real eyes on real
invoices — that the Hub captures, classifies, and exposes AP
documents at least as well as Square9 does today, and that AP can
correct anything that's wrong without having to call IT every time.

Square9 stays live throughout. Nothing changes about how AP gets
paid, how invoices flow, or how vendors are managed. The pilot is a
parallel exercise.

---

## What we are asking AP to validate

For every document AP looks at during the pilot week:

1. **Is it the right document?** (Same invoice you'd expect to see in
   Square9; legible preview; no missing pages.)
2. **Are the auto-extracted fields right?** (Vendor, invoice number,
   invoice date, amount, PO number — the five that matter.)
3. **If a field is wrong, can you correct it cleanly?** (Edit in the
   AP Review panel, click Save, see the change persist.)
4. **Are there documents that should be in the Hub but aren't?**
   (Things AP can find in Square9 but not in the Hub.)
5. **Are there documents that shouldn't be in the AP queue but are?**
   (Tracking spreadsheets, statements, freight slips, etc.)
6. **Are there duplicates?** (Same invoice arriving twice; the Hub
   should flag those.)

The full step-by-step walk is in the test plan
(`GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md`). This kickoff is
just the orientation.

---

## What AP is NOT responsible for

- Posting anything to Business Central from the Hub during the
  testing window. Posting is real and writes to BC; we will explicitly
  invite AP into a posting test in a later phase.
- Fixing or maintaining vendor profiles, classification rules, or
  routing rules.
- Reconciling the Hub against Square9 record-by-record. There is an
  internal IT script that does that; AP doesn't run it.
- Deleting anything.
- Triaging documents that don't belong to AP (sales orders, planning
  spreadsheets, etc.). Note them, move on.
- Solving engineering problems. If something looks wrong, log it and
  let IT chase it.

---

## How much time

- **Pilot length:** 5 business days.
- **Per tester per day:** 30–45 minutes, on top of normal AP work.
- **End of week:** one 30-minute debrief call.

If the time commitment is creeping over an hour per day, stop and
tell IT. We sized this small on purpose.

---

## Where to send feedback

- **Primary channel:** the daily feedback CSV
  (`GPI_HUB_AP_TEST_FEEDBACK_TEMPLATE.csv`). One row per observation,
  one CSV per tester per day.
- **CSV file naming:** `<tester-initials>-<YYYY-MM-DD>.csv`.
- **Screenshot folder naming:** `screenshots-<YYYY-MM-DD>/` next to
  the CSV. The CSV's `Screenshot Attached` column is yes/no; IT will
  open the folder.
- **Drop location:** TBD by IT before kickoff (likely a shared Teams
  / SharePoint folder restricted to the AP UAT group).
- **Email path for blockers and Critical-severity issues:** the AP
  UAT IT mailbox (TBD by IT before kickoff). Phone the AP supervisor
  first if a real payment is at risk.

---

## Who reviews feedback

- **Daily triage:** IT / Engineering reads new CSV rows each morning
  during the pilot week. Severity-Blocker and Critical rows get
  same-day attention. High rows get a remediation owner assigned
  within 24 hours. Medium / Low rows are batched.
- **Weekly debrief:** 30-minute call with AP testers + AP supervisor
  + IT / Eng. We walk the open list, agree on what blocks cutover and
  what doesn't, and confirm the next steps.
- **No daily standup is required of AP.** AP's only daily action is
  to log the rows.

---

## How retesting works

When AP corrects a field on a document during the pilot (e.g. fixes a
wrong vendor or fills in a missing invoice date), they don't need to
do anything special — just save the change and continue. IT runs the
internal reconciliation rerun afterward and confirms the Hub now sees
the document the way AP corrected it.

If a tester hits the same problem twice on the same document after a
correction, that itself is a feedback row (severity Critical or High,
depending on what failed to persist). Those are exactly the kinds of
issues the pilot is meant to catch.

For documents AP **didn't** touch, no action is required from the
tester — IT compares the Hub against Square9 separately.

---

## Out of scope (do not include in feedback)

- Anything related to Square9's own UI or data.
- Anything in the Hub's Settings, Config, Admin, or Intelligence
  pages.
- Sales / inventory / planning workflows. AP UAT is AP-only.
- Cutover timing, Square9 retirement, or "when will we stop using
  Square9." That's a separate decision out of the testers' hands.
- Performance / speed (unless the page is unusable; then it's a
  Blocker).

---

## Internal-only notes (NOT for the AP-facing version)

- This kickoff doc and the test plan must be re-edited before being
  shared with Accounting. Strip the "INTERNAL DRAFT" banners, soften
  the engineering language, drop the references to internal scripts
  / probes / IT memos, and reformat for a 1-page handout.
- The feedback CSV template currently has two example rows
  (one Pass, one Fail) so IT can see the intended fill pattern. The
  AP-facing version of the CSV must have the example rows removed —
  testers should start from a clean header-only file.
- The body-reconciliation probe, the
  `INTERNAL_AP_REVIEW_METADATA_VALIDATION.md` memo, and the rerun
  CSVs in `prod_reports/` must not be referenced or shared
  externally.
- Hub doc links shown in feedback rows should be reviewed before
  any external archival; some Hub documents include vendor / BC
  data that shouldn't leave the AP UAT group.
- AP UAT environment URL, IT mailbox, and feedback drop location are
  marked TBD here. Resolve before printing the AP-facing version.
