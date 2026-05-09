# AP Smoke Test — Quick Start

**For:** Chad or Alani.
**Time:** ~30 minutes.
**Goal:** Click around the Hub on a few real documents and tell us if anything looks broken or confusing.
**Not:** A real test plan. Not for Accounting. Don't save anything.

---

## What you're doing

Open ~6 documents in the Hub. For each one, answer five quick questions:

1. Did the document open?
2. Did the preview load?
3. Did the AP Review panel appear (when it should)?
4. Are the vendor / invoice number / amount / PO fields visible?
5. Does the status / routing text make sense in plain English?

If yes to all five → mark Pass and move on.
If no to any → write one sentence in the notes column.

---

## Step 1 — Open this file

`prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv`

It has 18 test documents. You only need to walk a handful.

---

## Step 2 — Open the Hub

Open the GPI Hub URL in a browser and sign in.

---

## Step 3 — Walk the P0 rows first

In the smoke CSV, sort by `priority`. Start with `P0`. There are **2 rows** at P0 — they're the metadata-cleanup examples (Hawkemedia, XPO).

For each P0 row:
1. Copy `hub_document_url`. Paste it into the browser. (If it starts with `/documents/...`, paste it after the Hub origin.)
2. Walk the five questions below.
3. Log one row in the findings CSV.

**If anything major is broken on a P0 row, stop here and tell Emergent.** Don't push on.

If P0 looks fine, continue with the `P1` rows (12 of them). You can stop after ~4 P1s if you've seen enough.

---

## Step 4 — The five questions (per document)

| # | Question | Look at |
| --- | --- | --- |
| 1 | Did the document open? | The Document Detail page loaded; no white screen. |
| 2 | Did the preview load? | PDF preview shows the actual document. |
| 3 | Did the AP Review panel appear? | Yes if it's an AP Invoice. The panel has Vendor + Invoice Number + Date + Amount + PO fields. |
| 4 | Are the fields visible? | The five fields above are present in the panel (some may be empty — that's fine, just check they're rendering). |
| 5 | Is the status text understandable? | The status badge / workflow status reads in plain English ("Vendor Pending," "Ready," etc.) — not engineering jargon. |

---

## Step 5 — What NOT to do

- **Don't click Save Changes.** Don't fix anything. This is observation only.
- **Don't click Mark Ready or Post to BC.** Those are real actions.
- **Don't email Accounting.** They are not in the loop yet.
- **Don't worry about cutover, Square9, or what the matcher score is.** Not your problem here.

---

## Step 6 — Log problems

Open `prod_reports/AP_INTERNAL_SMOKE_TEST_MINIMAL_FINDINGS.csv`.

One row per document you walked, even when everything works. Six yes/no columns and one notes column. That's it.

Severity is just:
- **Blocker** — couldn't open the document or the page is broken.
- **High** — opened, but something key is missing or wrong (no panel on an AP invoice, no fields, etc.).
- **Low** — works but feels confusing.
- (Leave blank if everything was fine.)

---

## Step 7 — When you're done

Save the findings CSV next to the others in `prod_reports/`. Tell Emergent it's there. We'll take it from there.

If you saw nothing scary, that's a great answer too.

---

_That's it. ~30 minutes. No code, no Accounting, no saves._
