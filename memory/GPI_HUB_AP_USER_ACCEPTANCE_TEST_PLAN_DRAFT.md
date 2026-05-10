# GPI Hub — AP User Acceptance Test Plan (INTERNAL DRAFT — Controlled Pilot)

> **Status:** Internal draft for IT / Engineering review.
> **NOT for distribution to Accounting** until final approval.
> Accounting has not been engaged. This document is a working draft
> of what we will eventually hand to AP testers, captured now while
> the context is fresh. Language and tone will be re-edited for an
> AP-facing audience before any external send.
> **Source context:** `prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md`,
> `prod_reports/AP_UAT_READINESS_STATUS_2026-05-08.md`,
> `prod_reports/AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md` (2026-05-10).

---

## 0. Readiness baseline (2026-05-10)

The Hub is technically clean enough to begin a **controlled AP pilot**.
This is not cutover, not Square9 replacement, not posting-to-BC
testing — it is a guided review with a small set of testers.

**Production VM smoke baseline (P0 + P1 set, 16 documents):**

| Check | Result |
| --- | --- |
| Documents loaded under authenticated session | 16 / 16 |
| AP Review panel rendered above the PDF preview | 16 / 16 |
| All five AP fields visible (Vendor, Invoice #, Date, Amount, PO) | 16 / 16 |
| Document Status card present | 16 / 16 |
| Raw JSON warnings leaked to UI | 0 / 16 |
| Raw snake_case blocker codes leaked to UI | 0 / 16 |
| Save / Mark Ready / Post / Re-process actions triggered | **none** |
| Automated DOM smoke checker exit code | **0 (pass)** |

**What changed since the 2026-05-08 status:**
1. `entity_resolution_blocking_items` rendering bug fixed — items like
   `vendor_unmatched: 'MRP Solutions'` now render as
   *"Vendor not matched to a Business Central record yet — 'MRP
   Solutions'"* via the new `humanizeBlockingItem()` helper in
   `DocumentIntelligencePanel.js`. Caught by the automated DOM smoke
   checker, fixed, redeployed, re-validated.
2. `po_not_found` blocker code now mapped to plain English
   ("PO extracted but not found in Business Central"). No more
   "Po Not Found" title-case fallback.
3. Smoke checker calibration: Document Status substring match made
   case-insensitive (Hub renders `DOCUMENT STATUS`).

**Explicit non-claims (DO NOT promise to AP):**
- Square9 is **not** being replaced or retired.
- Hub is **not** the system of record yet.
- Posting to BC from Hub is **not** part of this pilot.
- 16/16 smoke ≠ 100% accuracy guarantee — extraction errors are
  exactly what the pilot is meant to surface on real documents.

---

## 1. Purpose of testing

We need a small group of AP users to confirm that GPI Hub correctly
captures, classifies, and exposes the same invoices that Accounts
Payable would otherwise see in Square9, and that AP can confidently
correct any document where the Hub's auto-extraction got something
wrong. The end state is that AP can run their day out of the Hub
instead of out of Square9, with no missing invoices, no silently-wrong
vendor / invoice number / amount, and no surprise duplicates.

In one sentence: **prove the Hub is at least as trustworthy as
Square9 for the daily AP work, and surface anywhere it isn't.**

---

## 2. Plain-English overview of the AP workflow in GPI Hub

The Hub is a web application, similar to a shared inbox, that AP
opens in a browser. Invoices arrive by email, by SharePoint folder,
or by file upload. The Hub:

1. **Receives** the invoice (PDF, image, sometimes a spreadsheet).
2. **Reads** the document and pulls out the vendor, the invoice
   number, the date, the amount, and the PO number, if it can find
   them.
3. **Classifies** what kind of document it is (AP invoice, freight
   bill, statement, sales order, etc.).
4. **Routes** the invoice to the right "queue" inside the Hub
   depending on what it is and how confident the Hub feels about it.
5. **Asks AP for help** when something is missing, ambiguous, or
   doesn't match Business Central (BC).
6. **Posts to BC** — once an invoice has all the right fields and AP
   marks it ready, it can be posted to Business Central directly from
   the Hub.

Most invoices flow through automatically. The job of an AP tester is
to walk through the queue, spot-check that each invoice looks right,
and correct anything that doesn't.

---

## 3. What is different from Square9

| Square9 today | GPI Hub |
| --- | --- |
| Mostly a digital filing cabinet — you find PDFs and read them. | Active processing — the Hub reads each invoice and pre-fills vendor / invoice number / amount / PO so you don't have to retype. |
| AP types data into Business Central separately. | AP can post directly to BC from inside the Hub, using the fields the Hub already extracted (after AP confirms them). |
| No automatic duplicate detection. | The Hub flags likely duplicates so AP doesn't pay the same invoice twice. |
| No automatic vendor matching. | The Hub auto-matches the vendor to the BC vendor list and tells AP its confidence. |
| No queues — everything's just "in there." | Documents land in named queues: "Needs Review," "Ready to Post," "Captured," "Exception," etc. AP walks the queues. |
| Search is filename / folder based. | Search by vendor, invoice number, PO, amount, date — across the whole Hub. |
| No feedback loop. | When AP corrects a vendor or an invoice number, the Hub remembers and gets better at that vendor next time. |

**What stays the same:** every invoice still ends up filed in
SharePoint at the end. The Hub is the cockpit; SharePoint is still
the file room.

---

## 4. What AP should and should not do during testing

### Should

- Open documents from their normal day's work.
- Click around. Try the Inbox, the search, the document detail page.
- Correct any field that's wrong (vendor, invoice number, date,
  amount, PO) using the AP Review panel.
- Save changes after correcting.
- Tell us anything that's confusing, slow, missing, or surprising.
- Use the feedback CSV (or the kickoff form, when available) to log
  one row per observation.
- Flag any document they think is genuinely missing, duplicated, or
  misclassified.

### Should NOT

- Post anything to Business Central during the testing window
  unless explicitly asked. Posting is real and writes to BC.
- Delete documents.
- Change settings, vendor profiles, classification rules, or anything
  in the Settings or Config pages.
- Try to "fix" Square9 from inside the Hub. The two systems are not
  yet synced; corrections live in the Hub only for now.
- Treat anything in the testing window as the system of record. AP's
  normal Square9 process continues in parallel until cutover.
- Share screenshots of vendor or invoice data outside the AP +
  IT / Eng team.

---

## 5. Tester prerequisites

| # | Requirement | How to confirm |
| --- | --- | --- |
| 1 | A GPI Hub login (email + password). | IT will create accounts before kickoff. |
| 2 | A modern browser (Chrome, Edge, or Firefox, current version). | "About → Version" in the browser. |
| 3 | The Hub URL. | Provided in the kickoff email. |
| 4 | A few real invoices in front of the tester (paper or PDF). | Pick a normal day's stack. |
| 5 | Read the kickoff notes (`GPI_HUB_AP_UAT_KICKOFF_NOTES_DRAFT.md`). | 5-minute read. |
| 6 | Know the BC vendor lookup is the source of truth for vendor names. | The Hub's vendor field talks to BC. |

Testers do **not** need:

- Any setup on their machine.
- Any Square9 access changes.
- Any BC permissions changes.
- Any technical / engineering knowledge.

---

## 6. Glossary

| Term | Plain-English definition |
| --- | --- |
| **Hub** | The new GPI document system being tested. |
| **Square9** | The current digital filing cabinet AP uses. |
| **BC** | Microsoft Dynamics 365 Business Central — the accounting system invoices get posted into. |
| **AP Inbox / Queue** | The list of AP-related documents waiting on something. |
| **Document Detail page** | The single-document view, where preview + extracted fields + actions live. |
| **AP Review panel** | The form on the document detail page where AP confirms or corrects vendor / invoice number / date / amount / PO. |
| **Extracted fields** | What the Hub *thinks* the invoice says, before AP confirms. |
| **Vendor canonical** | The official BC vendor record the Hub matched to. |
| **Workflow status** | Where this document is in its life cycle — e.g. "Vendor Pending," "Data Correction Pending," "Ready for Posting," "Posted." |
| **Reconciliation probe** | An IT-only check that compares what's in the Hub vs. what's in Square9. AP doesn't run this. |
| **Cutover** | The future date Square9 stops being the source of truth for AP. Not happening during testing. |
| **Duplicate** | A document the Hub thinks it has already seen (same vendor + invoice number, usually). |

---

## 7. Test schedule / daily cadence

- **Length of pilot:** 5 business days (1 working week).
- **Daily commitment per tester:** 30–45 minutes, on top of normal AP
  work. Testers are not asked to abandon Square9.
- **Daily structure:**
  - 0:00–0:05 — open Hub, scan the AP Inbox.
  - 0:05–0:30 — walk one of the day's scenario blocks (see § 8).
  - 0:30–0:40 — log feedback rows in the CSV.
  - 0:40–0:45 — note anything blocking and email IT.
- **End-of-week:** 30-minute debrief call with IT / Eng. AP doesn't
  prepare a deck; we walk the feedback CSV together.

| Day | Scenario block (high-level) |
| --- | --- |
| Day 1 | Login + Inbox + open-a-document (T-01 → T-04). |
| Day 2 | Field validation walk (T-05 → T-09). |
| Day 3 | Status, exceptions, and search (T-10 → T-13). |
| Day 4 | Edge cases — missing, misclassified, duplicate, non-invoice (T-14 → T-17). |
| Day 5 | Correct + retest cycle (T-18 → T-19) and freeform exploration. |

---

## 8. Step-by-step test scenarios

> **Format note:** every scenario uses the same structure. "Pass" means
> the Expected Result happened, with no surprises. "Fail" means it did
> not, OR something happened that the tester wasn't expecting (even if
> the system technically did its job). When in doubt, log it and let
> IT decide.
>
> **Severity guide:** see § 10.

### T-01 — Log in to the Hub

- **Purpose:** Confirm the tester can reach the Hub and authenticate.
- **Steps:**
  1. Open browser.
  2. Go to the Hub URL from the kickoff email.
  3. Enter email + password. Click Sign In.
- **Expected result:** Tester lands on the Hub home / Documents page.
  No error banner.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — even if pass.
- **Screenshot required:** No (yes if fail).
- **Severity if failed:** Blocker.

### T-02 — Find the AP inbox

- **Purpose:** Confirm AP can locate the inbox without help.
- **Steps:**
  1. From the Hub home, find the navigation menu.
  2. Click into the page that holds the AP queue / inbox.
- **Expected result:** A list of AP documents appears, with vendor,
  invoice number, amount, status, age.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — note how many clicks it took.
- **Screenshot required:** No.
- **Severity if failed:** High.

### T-03 — Open a document

- **Purpose:** Confirm AP can open one document and see the detail
  page.
- **Steps:**
  1. From the inbox, click any one document row.
- **Expected result:** Document Detail page opens. Preview, extracted
  fields, AP Review panel, status, and history are visible.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes.
- **Screenshot required:** Yes.
- **Severity if failed:** Blocker.

### T-04 — Review the document preview

- **Purpose:** Confirm the on-screen PDF preview is readable and
  matches the document the tester would expect.
- **Steps:**
  1. On the Detail page, scroll to the PDF preview.
  2. Compare what's on screen against the original invoice (paper or
     email).
- **Expected result:** Preview matches the source. Pages are legible,
  no missing pages.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if anything is off.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** High.

### T-05 — Validate vendor

- **Purpose:** Confirm the Hub-extracted vendor matches the actual
  vendor on the invoice.
- **Steps:**
  1. In the AP Review panel, look at the Vendor field.
  2. Compare against the printed "From" / "Bill From" / "Remit To"
     on the invoice.
- **Expected result:** Vendor name matches. If the vendor was
  auto-matched to a BC vendor, the BC vendor name is shown.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if any mismatch.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** High.

### T-06 — Validate invoice number

- **Purpose:** Confirm the extracted invoice number matches the
  invoice's printed invoice number.
- **Steps:**
  1. Read the Invoice Number field in the AP Review panel.
  2. Compare against the invoice itself.
- **Expected result:** Exact string match (case-insensitive ok).
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if any mismatch.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** High.

### T-07 — Validate invoice date

- **Purpose:** Confirm the invoice date matches the document.
- **Steps:**
  1. Read the Invoice Date field.
  2. Compare to the invoice header.
- **Expected result:** Same date. Date format may differ (`2026-04-15`
  vs `04/15/2026`); same calendar date is what matters.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if any mismatch.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** Medium.

### T-08 — Validate amount

- **Purpose:** Confirm the Total Amount field matches the invoice's
  total / amount due.
- **Steps:**
  1. Read the Total Amount field.
  2. Compare to the invoice's "Total" / "Amount Due" / "Balance Due."
- **Expected result:** Same dollar value, to the cent.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if any mismatch.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** High.

### T-09 — Validate PO number

- **Purpose:** Confirm the PO field matches the printed PO. PO is
  optional — many invoices don't have one.
- **Steps:**
  1. Read the PO Number field.
  2. Compare to "PO," "Purchase Order," or "P.O." on the invoice.
  3. If the invoice has no PO, the field should be blank.
- **Expected result:** PO matches OR field is blank when invoice has
  no PO.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if Hub shows a PO that isn't on the
  invoice (false positive) or vice versa (false negative).
- **Screenshot required:** Yes if fail.
- **Severity if failed:** Medium.

### T-10 — Understand document status

- **Purpose:** Confirm tester can read the status badge and tell
  what's expected of them next.
- **Steps:**
  1. Look at the Status / Workflow Status field on the Detail page.
  2. Read the kickoff notes' status cheat sheet.
  3. Tell us in plain English what the Hub is waiting on for this
     document.
- **Expected result:** Tester correctly says, e.g., "vendor not yet
  matched, AP needs to pick one" or "ready to post."
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — copy the status name and the tester's
  interpretation.
- **Screenshot required:** No.
- **Severity if failed:** Medium (UX — likely renaming of statuses
  needed before cutover).

### T-11 — Understand review / exception cases

- **Purpose:** Confirm the tester can identify a document that's in
  an exception state and knows it's not their normal happy-path.
- **Steps:**
  1. Find a document in the Exception or Needs Review queue (the
     kickoff notes will name the exact menu).
  2. Open it.
  3. Read the reason / blocker the Hub gives.
- **Expected result:** Tester can articulate why the document is held
  up (e.g. "duplicate," "vendor unknown," "amount missing").
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — copy the blocker text.
- **Screenshot required:** Yes.
- **Severity if failed:** Medium.

### T-12 — Search by vendor

- **Purpose:** Confirm AP can find all documents from a single
  vendor.
- **Steps:**
  1. Go to the Search page.
  2. Type a vendor name the tester knows.
  3. Submit.
- **Expected result:** A list of that vendor's documents — recent
  first if the search supports it. Counts and amounts look plausible.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if results are missing or inflated.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** Medium.

### T-13 — Search by invoice number

- **Purpose:** Confirm AP can locate a specific invoice.
- **Steps:**
  1. From Search, enter an invoice number you have on a real invoice.
  2. Submit.
- **Expected result:** Exactly one document opens (or comes up at the
  top of the result list). Vendor and amount match the printed
  invoice.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes if not found, or if multiple results
  surface for one invoice number.
- **Screenshot required:** Yes if fail.
- **Severity if failed:** High.

### T-14 — Identify a missing document

- **Purpose:** Spot an invoice the tester knows exists in Square9 but
  cannot find in the Hub.
- **Steps:**
  1. Pick a recent invoice from Square9 that the tester remembers.
  2. Search the Hub by vendor + invoice number.
  3. If the invoice is not in the Hub, log it.
- **Expected result:** Most invoices should be findable in both. Any
  that are NOT findable in the Hub are logged for IT.
- **Pass / Fail:** ☐ Pass ☐ Fail (Pass = found in Hub or confirmed
  absent and logged.)
- **Feedback required:** Yes — vendor, invoice number, date.
- **Screenshot required:** Yes (the Square9 hit) if missing in Hub.
- **Severity if failed:** Critical (missing invoices are the worst
  failure mode for AP).

### T-15 — Identify wrong classification

- **Purpose:** Spot an AP invoice that the Hub classified as
  something else (or vice versa).
- **Steps:**
  1. While walking the inbox, find a document whose document type
     looks wrong (e.g. an AP invoice classified as "Misc" or "Sales
     Order").
- **Expected result:** Tester logs the mismatch with the document
  link.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — vendor, document name, what the Hub
  classified it as, what it should be.
- **Screenshot required:** Yes.
- **Severity if failed:** High (drives the misrouted-to-AP queue
  count down).

### T-16 — Identify duplicate / non-duplicate

- **Purpose:** Spot a document the Hub flagged as a duplicate that is
  actually a duplicate, OR one it flagged that is NOT a duplicate
  (false positive).
- **Steps:**
  1. Look for the duplicate badge / status.
  2. Confirm by reading the original invoice.
- **Expected result:** Hub-flagged duplicates are real duplicates.
  False positives are logged.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — both directions matter.
- **Screenshot required:** Yes.
- **Severity if failed:** High (a missed duplicate could mean a
  double-payment risk; a false positive blocks a legitimate invoice).

### T-17 — Identify a non-invoice attachment

- **Purpose:** Spot tracking spreadsheets, signed delivery slips, or
  other attachments that landed in the AP queue but aren't invoices.
- **Steps:**
  1. While walking the inbox, find anything that's not actually an
     invoice (XLS tracking sheet, DOC, image of a packing slip, etc.).
- **Expected result:** Tester logs it. We will route these out of
  the AP cohort upstream over time.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — file name + parent path.
- **Screenshot required:** Yes.
- **Severity if failed:** Low (clutter, not financial risk).

### T-18 — Save a metadata correction

- **Purpose:** Confirm AP can change a wrong field and persist it.
- **Steps:**
  1. Open a document where one of vendor / invoice number / date /
     amount / PO is wrong.
  2. In the AP Review panel, edit the wrong field.
  3. Click Save Changes.
- **Expected result:** Toast / banner says "Changes saved." Reload
  the page; the corrected value persists.
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes — what was changed and why.
- **Screenshot required:** Yes (before + after).
- **Severity if failed:** Critical (this is the core remediation
  workflow).

### T-19 — Retest after correction

- **Purpose:** Confirm that, after a correction, the document looks
  right going forward.
- **Steps:**
  1. After T-18, walk back to the inbox.
  2. Find the same document via search by invoice number.
  3. Open it again.
- **Expected result:** Field still shows the corrected value. Status
  may have advanced (e.g. from "Vendor Pending" to "BC Validation
  Pending" or similar).
- **Pass / Fail:** ☐ Pass ☐ Fail
- **Feedback required:** Yes.
- **Screenshot required:** No (yes if fail).
- **Severity if failed:** Critical.

---

## 9. Feedback instructions

- One **row per observation** in `GPI_HUB_AP_TEST_FEEDBACK_TEMPLATE.csv`.
- Fill in every column that applies. Leave blanks if not applicable.
- Attach screenshots in a folder next to the CSV named with the same
  date (e.g. `screenshots-2026-XX-XX/`). The CSV's
  `Screenshot Attached` column is just yes/no — IT will go look.
- For copy/paste of the Hub document link, use the browser URL bar
  on the document detail page (it will look like
  `…/documents/<long-id>`).
- One CSV per tester per day, named
  `<tester-initials>-<YYYY-MM-DD>.csv`.

---

## 10. Severity guide

| Severity | Meaning | Examples |
| --- | --- | --- |
| **Blocker** | Tester cannot continue testing. | Login fails. Document Detail page won't load. Save throws an error. |
| **Critical** | A real invoice is mis-handled in a way that risks money. | Duplicate not flagged. Wrong vendor matched. Save doesn't persist. |
| **High** | Important field is wrong, but tester can work around it manually. | Wrong amount extracted. Misclassified document type. Search misses a document. |
| **Medium** | Annoying, but not financial risk. | Wrong date. PO mismatch. Status name confusing. |
| **Low** | Cosmetic / nice-to-have. | Non-invoice attachment in AP queue. Slow page load. Layout glitch. |

---

## 11. Known limitations

These are already known to IT and **do not need to be re-reported**.
Anything else, please log.

- Some scanned image PDFs (estimated single-digit count) cannot be
  read by the Hub's text extractor today; they need OCR. They will
  show empty extracted fields. IT is tracking the OCR pipeline as a
  P1.
- Some documents have been classified to a non-AP type but are
  actually AP invoices (e.g. routed to "Misc" or "Freight Issues").
  These are part of T-15. The remediation rules are still being
  tuned.
- A small number of vendors have inconsistent name strings between
  the email "From" and the invoice header. Vendor matching may show
  lower confidence on those. AP can still set vendor manually via
  the BC lookup.
- The body-reconciliation probe and any IT-only scripts referenced
  internally are not part of AP UAT. Ignore any mention of them.
- Cutover from Square9 has not happened. Both systems will be live
  during the testing window.

---

## 12. Escalation path

| Situation | Who | How |
| --- | --- | --- |
| Cannot log in. | IT (Hub admin) | Email; copy the AP UAT lead. |
| A document is missing money / vendor info AND a real payment depends on it. | AP supervisor first, then IT. | Phone the AP supervisor; do not block a real payment on a Hub bug. |
| Save / mark-ready / post button shows an error. | IT | Log in CSV at `Blocker`; email the screenshot. |
| Hub is down. | IT | Email + Teams; no need to log individual rows. |
| Anything else (non-blocking observations). | IT | Log in CSV at the right severity. Daily review will catch it. |
| Anything that looks like a data leak / wrong customer's invoice / wrong vendor's bank info on a doc. | AP supervisor + IT | Same-day. Severity = Critical. |

---

## 13. Exit criteria

The pilot exits **successfully** when, on the last day of the test
window:

- Every Blocker test (T-01, T-03, T-18, T-19) passes for every
  tester.
- No open Critical-severity feedback rows.
- ≤ 5 open High-severity feedback rows, each with an IT-assigned
  remediation owner and target date.
- AP testers, in the debrief, report they could imagine running a
  full AP day in the Hub, even if a few rough edges remain.

The pilot exits **as not-ready** if any of:

- Blockers remain on the last day.
- Critical issues are still open.
- More than 5 High issues without remediation owners.
- AP testers report they would not be willing to use the Hub as
  primary even with the rough edges fixed.

In the not-ready case, IT triages the open list, fixes top items,
and a second short pilot is scheduled. We do not declare cutover
until exit criteria are met.

---

## 14. Day-one pilot plan (controlled-pilot mode)

Before opening the pilot to a full week, run a **single short
session** with 1–2 AP testers to confirm the on-the-ground
experience. This day-one pass is the gate for everything that
follows in this plan.

| Time | Step | Owner |
| --- | --- | --- |
| 0:00 – 0:30 | **Kickoff** — read `GPI_HUB_AP_UAT_KICKOFF_NOTES_DRAFT.md` aloud, confirm logins work, confirm everyone knows where to log feedback, walk one example doc together. | IT |
| 0:30 – 1:30 | **Guided review** — testers walk **10–15** assigned documents from the P0+P1 smoke set (already validated 16/16). One observation row per doc in the feedback CSV. **No clicking Post to BC. No Mark Ready. No Save unless explicitly directed by IT for a single test row.** | AP testers (with IT in the room) |
| 1:30 – 1:45 | **Feedback review** — IT reads the new CSV rows on the spot, flags anything Critical/Blocker, confirms tester's understanding before they leave. | IT + AP testers |
| 1:45 onward | **IT triage** — engineering decides whether to fix-then-expand or expand-now. | IT |

If the day-one session surfaces a Critical or Blocker, **stop the
pilot here**. Do not proceed to the 5-day window in section 7 until
the issue is fixed and re-smoked.

---

## 15. Pilot guardrails (must remain explicit to AP)

Carry these forward verbatim into any AP-facing send. These are not
suggestions; they are the conditions under which the pilot is safe.

- **AP must NOT click "Post to BC".** Posting writes to Business
  Central and is out of scope for this pilot. If the button is
  visible, leave it alone.
- **AP must NOT treat the Hub as system-of-record.** Square9 remains
  the source of truth for AP throughout the pilot.
- **AP must report all issues via the feedback template** — no
  hallway / Slack / email-only reports. Every observation gets a
  CSV row so triage stays auditable.
- **AP must test only assigned documents.** Random invoices are not
  part of the pilot set; testing them muddies the regression signal.
- **AP must not change classification, routing rules, or vendor
  master data.** Those are admin actions; the pilot is read-and-edit
  on individual documents only.
- **AP must call the AP supervisor (not IT) if a real payment is at
  risk.** Hub bugs do not block real payments; if a real payment is
  on the line, fall back to Square9 and flag it.

---

## 16. Known limitations heading into the pilot

These are real and expected. Note them in the AP-facing kickoff;
they should not become Blocker rows during testing.

- **Document Intelligence empty-state 404s** are engineering-console
  noise only. AP will not see them in the UI. (Tracked as
  engineering hygiene; no AP impact.)
- **OCR examples are not part of the first pilot.** Documents that
  require OCR show empty extracted fields by design today; they are
  excluded from the smoke-set walk.
- **Non-invoice attachment handling is still being refined.**
  Tracking spreadsheets, statements, freight issues — these may
  appear in the AP queue and should just be noted-and-skipped, not
  fixed.
- **Square9 remains available throughout the pilot.** Nothing about
  AP's day changes. The pilot is parallel.
- **No production BC posting from the Hub during the pilot** unless
  IT explicitly approves and supervises a specific test row. Default
  posture is "do not post."
- **Some vendors with inconsistent header names** show lower
  vendor-match confidence. AP can correct via the BC lookup; that's
  expected behaviour for the pilot.

---

## 17. Final pre-send checklist (IT must complete before AP send)

Do not send any AP-facing version of this plan until every box
below is ticked.

- [ ] Pilot testers identified and confirmed (1–2 names).
- [ ] AP supervisor named and looped in.
- [ ] Hub URL confirmed reachable from each tester's workstation.
- [ ] Login / SSO / MFA confirmed for each tester.
- [ ] Feedback drop location resolved (Teams / SharePoint / shared
      folder), permissions scoped to the AP UAT group.
- [ ] AP UAT IT mailbox confirmed and monitored.
- [ ] "Do not click Post to BC" instruction repeated **in the
      kickoff**, the **test plan**, and the **feedback CSV header
      banner**. (Three places, on purpose.)
- [ ] On-call IT engineer named and present for the day-one session.
- [ ] Latest smoke-checker run is green within the last 48 hours.
- [ ] CSV example rows stripped from the AP-facing template (the
      INTERNAL DRAFT keeps them for IT's reference).
- [ ] INTERNAL DRAFT banners and engineering-language references
      removed from the AP-facing version.
- [ ] All `TBD` markers in this plan and in the kickoff doc are
      resolved.
- [ ] AP supervisor has read this plan and signed off in writing.

---

_End of internal draft._
