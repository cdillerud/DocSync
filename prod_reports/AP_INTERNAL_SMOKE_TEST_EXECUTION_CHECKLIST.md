# AP Internal Smoke-Test Execution Checklist

> **INTERNAL — IT / Engineering only.**
> Accounting has not been engaged. Do not send this to AP.
> Do not post to BC. Do not modify Square9. This is not cutover testing.
>
> **Companion artifacts:**
> - `prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv` (18 rows)
> - `prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.md`
> - `prod_reports/AP_INTERNAL_SMOKE_TEST_FINDINGS_TEMPLATE.csv`
> - `prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md`

---

## 1. Purpose of the internal smoke test

Walk the curated 18-row smoke set inside the GPI Hub UI and confirm
that the core AP workflow behaves correctly *before* any AP user is
invited to test. The goal is to surface UI bugs, broken panels,
mis-rendered fields, or confusing status text while the audience is
still IT/Eng — not while Accounting is watching.

This is a **read-only walk**. No corrections are saved, no documents
are posted, no Mongo writes. The pinned `metadata_cleanup_example`
rows (Hawkemedia, XPO) are reviewed as observation cases only — IT
does not edit them in this pass.

---

## 2. Preconditions

| # | Precondition | How to confirm |
| --- | --- | --- |
| 1 | Backend container is running. | `docker compose ps` — `gpi-backend` is `Up`. |
| 2 | Frontend is reachable in a browser. | Hub URL loads to the login page without error. |
| 3 | Smoke set CSV is present and recent. | `ls -lh prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv` shows today's date. |
| 4 | Tester has a working Hub login. | Sign in succeeds; lands on Documents Hub. |
| 5 | Tester has read the companion MD. | One pass through `prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.md`. |
| 6 | Tester has the findings CSV template open. | `prod_reports/AP_INTERNAL_SMOKE_TEST_FINDINGS_TEMPLATE.csv` copied to a tester-named copy for the day. |

If any precondition fails, stop and resolve before walking the rows.

---

## 3. What not to do

- **Do not contact AP.** Findings stay inside IT/Eng.
- **Do not post to BC.** Click neither "Mark Ready" nor "Post to BC"
  on any document during the smoke walk.
- **Do not modify Square9.** Square9 is untouched by this walk.
- **Do not save metadata corrections** on the pinned cleanup rows.
  This pass observes only.
- **Do not treat this as cutover testing.** Cutover gating runs out
  of the cutover proof pack, not this smoke set.
- **Do not screenshot rows marked `internal_only=Y`** for any
  audience outside IT/Eng.

---

## 4. How to use the smoke-set CSV

1. Open `prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv` in a
   spreadsheet (or `column -s, -t` it on the command line).
2. Sort or filter by `priority` — walk **P0 → P1 → P2**.
3. For each row, read three columns: `why_this_doc_is_in_the_test_set`,
   `what_tester_should_check`, and `expected_result`.
4. Open `hub_document_url` in a new browser tab. (If the column shows
   a relative `/documents/{id}` path, paste it behind the Hub origin.)
5. Walk the row through the matching block in §5.
6. Record a row in the findings CSV (one row per smoke row, even
   when Pass).

Do not skip rows. If a row's document does not exist in the live Hub
(possible for the pinned cleanup rows under drift), still record the
finding — that itself is a useful signal.

---

## 5. Step-by-step checklist

> Each block applies to the relevant smoke-set category. Tick the
> checkbox in the findings CSV's `Pass/Fail` column. If anything is
> off, set `Severity` per the guide below and write a one-line
> `Notes`.

### 5.1 Open each document

- ☐ The Document Detail page loads within a few seconds.
- ☐ The page does not white-screen, throw a console error, or render
  a partial layout.
- ☐ The browser URL ends with `/documents/{hub_doc_id}`.

**Severity if fail:** Blocker. Stop the walk, log it, escalate to
Eng before proceeding.

### 5.2 Confirm the document preview loads

- ☐ The PDF preview pane renders.
- ☐ Pages are legible (text or scanned image is visible).
- ☐ For multi-page docs, page navigation works.
- ☐ No "preview unavailable" error unless the row is in
  `sharepoint_permission_edge` (currently 0 rows; not exercised this
  run).

**Severity if fail:** High.

### 5.3 Confirm the AP Review panel appears where expected

- ☐ For rows in `clean_ap_invoice`, `ap_invoice_*_populated`,
  `needs_review_or_exception`, `metadata_cleanup_example`,
  `duplicate_or_possible_duplicate`, `misclassified_or_corrected`:
  the AP Review panel is present on the page.
- ☐ For any row whose `doc_type` / `suggested_job_type` is **not**
  `AP_Invoice`, the panel is **absent** (this is by design — see
  `frontend/src/pages/DocumentDetailPage.js:1137`).
- ☐ When present, the panel renders all five core fields: Vendor,
  Invoice Number, Invoice Date, Total Amount, PO Number.
- ☐ The Save Changes button is visible. (Do **not** click it.)

**Severity if fail:** Critical (missing panel on an AP_Invoice row)
or High (missing fields inside the panel).

### 5.4 Confirm vendor / invoice / date / amount / PO are visible

- ☐ For rows in the `ap_invoice_vendor_populated` block, the Vendor
  field is non-empty AND matches the file name's vendor cue.
- ☐ For `ap_invoice_invoice_number_populated`, the Invoice Number
  field is non-empty AND matches the body of the doc.
- ☐ For `ap_invoice_amount_populated`, the Total Amount is non-empty
  AND > 0.
- ☐ For `ap_invoice_po_populated`, the PO Number is non-empty.
- ☐ For `clean_ap_invoice`, all five core fields are non-empty AND
  internally consistent.

**Severity if fail:** High. Note exactly which field disagrees.

### 5.5 Confirm status / routing fields are understandable

- ☐ The Workflow Status badge or label is readable in plain English.
- ☐ The status name does not require engineering knowledge to
  interpret.
- ☐ The routing reason (when present) clearly says why the doc went
  where it did.

**Severity if fail:** Medium (UX — likely renaming work needed
before AP UAT, not before cutover).

### 5.6 Confirm duplicate examples behave as expected

- ☐ For each `duplicate_or_possible_duplicate` row, a duplicate
  badge / status / banner is visible somewhere on the Detail page.
- ☐ Clicking through to the "duplicate of" original (if the UI links
  it) opens a real second document.
- ☐ The duplicate verdict is plausible — same vendor + invoice
  number on both, OR a clear false positive worth logging.

**Severity if fail:** High (false positive blocks a legitimate
invoice; missed duplicate is a payment-risk Critical).

### 5.7 Confirm metadata cleanup examples show missing fields

- ☐ For each `metadata_cleanup_example` row (Hawkemedia, XPO):
  - The AP Review panel renders.
  - At least one of `vendor_canonical`, `invoice_date`, `amount_float`,
    `po_number_clean` is visibly empty in the panel.
  - The notes column of the smoke CSV lists `expected_missing=[…]`
    matching what the panel actually shows.
  - **Do not save any correction in this pass.**

**Severity if fail:** Critical (the AP UAT remediation lane depends
on these rows behaving exactly as documented).

### 5.8 Confirm exception / review examples are understandable

- ☐ For each `needs_review_or_exception` row, the page surfaces
  *why* the doc is held up — `validation_errors`, blocker text, or
  workflow status name.
- ☐ The reason is intelligible to a non-engineer reading it cold.
- ☐ The next-action implied by the page is clear (e.g. "set vendor,"
  "correct amount").

**Severity if fail:** Medium.

### 5.9 Confirm misclassified / corrected examples carry history

- ☐ For each `misclassified_or_corrected` row, the document type is
  the corrected type (typically `AP_Invoice`).
- ☐ The classification override audit subdoc is visible somewhere on
  the page (event timeline / history / metadata block).
- ☐ The override entry shows the original type, corrected type, and
  a corrected_at timestamp.

**Severity if fail:** High.

---

## 6. Pass / fail log template

Use `prod_reports/AP_INTERNAL_SMOKE_TEST_FINDINGS_TEMPLATE.csv`.
One findings row **per smoke-set row walked**, even when Pass.

Required columns (matching the CSV header):

| Column | Notes |
| --- | --- |
| `Date` | YYYY-MM-DD. |
| `Tester` | Initials. |
| `Smoke Row Category` | Copy from `test_doc_category` of the smoke CSV. |
| `Hub Doc ID` | Copy from `hub_doc_id` of the smoke CSV. |
| `File Name` | Copy from `file_name`. |
| `Expected Result` | Copy from `expected_result`. |
| `Actual Result` | One sentence in tester's own words. |
| `Pass/Fail` | Pass or Fail. |
| `Severity` | Blocker / Critical / High / Medium / Low. Blank if Pass. |
| `Notes` | Anything that didn't fit. |
| `Follow-Up Owner` | Eng owner if Fail; blank if Pass. |

**Severity legend** (same as AP UAT plan):

- **Blocker** — tester cannot continue (page won't load, panel won't
  render, document won't open).
- **Critical** — risks money in production (duplicate missed, save
  silently dropped, wrong vendor matched, classification override
  lost).
- **High** — important field is wrong or missing but tester can
  reason around it (wrong amount, wrong invoice number, broken
  search hit).
- **Medium** — annoying but not financial risk (wrong date format,
  confusing status name, slow page load).
- **Low** — cosmetic (layout glitch, copy nit).

---

## 7. Known gaps in this smoke set

The 18-row smoke set is missing real examples for three P2
categories. These are coverage holes, **not** smoke-test blockers.
Listed here so testers don't waste time hunting for them and don't
log "missing" against them.

| Category | Why empty | Action |
| --- | --- | --- |
| `non_invoice_attachment` | Probe rows for these have no `best_hub_doc_id` (the body classifier short-circuits before signal scoring). | IT to manually backfill before promoting to the AP UAT list. |
| `ocr_required` | Same — empty signals → no Hub anchor → no row. | Same. |
| `sharepoint_permission_edge` | Body fetch returns 403/404 → no Hub anchor. | Same. |

---

## 8. Smoke-test exit criteria

This smoke pass exits **successfully** when:

- ☐ All P0 rows (`metadata_cleanup_example`, 2 rows) walked, every
  smoke checklist block §5.1–§5.7 ticked Pass.
- ☐ All P1 rows (14 rows across `clean_ap_invoice`,
  `ap_invoice_*_populated`, `needs_review_or_exception`,
  `duplicate_or_possible_duplicate`,
  `misclassified_or_corrected`) walked, no Blocker findings, no
  Critical findings.
- ☐ ≤ 5 open High-severity findings, each with an Eng follow-up
  owner assigned in the CSV's `Follow-Up Owner` column.
- ☐ All findings logged in
  `prod_reports/AP_INTERNAL_SMOKE_TEST_FINDINGS_TEMPLATE.csv`
  (renamed `<tester-initials>-<YYYY-MM-DD>.csv`).

This smoke pass exits **as not-ready** if any of:

- Any Blocker remains open.
- Any Critical remains open without a same-day fix.
- More than 5 open High findings.
- The pinned `metadata_cleanup_example` rows do not behave as
  documented in
  `prod_reports/INTERNAL_AP_REVIEW_METADATA_VALIDATION.md`.

In the not-ready case, IT triages, fixes the top items, and reruns
the smoke walk before any further AP UAT scoping.

---

## 9. Next step after the smoke test

This is sequenced; do not skip steps.

1. IT walks all 18 rows, logs findings.
2. Eng triages findings within 24 hours.
3. Top High findings get a remediation owner + target date.
4. Update the AP UAT draft (`memory/GPI_HUB_AP_USER_ACCEPTANCE_TEST_PLAN_DRAFT.md`,
   `memory/GPI_HUB_AP_TEST_FEEDBACK_TEMPLATE.csv`,
   `memory/GPI_HUB_AP_UAT_KICKOFF_NOTES_DRAFT.md`) with anything the
   smoke walk surfaced — terminology fixes, missing scenarios,
   tightened status copy, sharper screenshots.
5. Backfill the three missing smoke categories
   (`non_invoice_attachment`, `ocr_required`,
   `sharepoint_permission_edge`) by hand or by extending the
   generator.
6. **Only then** consider involving Accounting.

---

_End of internal execution checklist._
