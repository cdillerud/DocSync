# GPI Hub — AP Pilot Test Plan

> A controlled pilot for AP testers. Pair this with the kickoff
> handout. Read the kickoff first; come back here for the detailed
> step-by-step.

---

## 1. What we're asking you to do

Walk through 10–15 assigned documents in the GPI Document Hub and
tell us, for each one, whether the Hub correctly read the invoice
data. That's the entire job.

You are **not** approving anything. You are **not** posting
anything. You are **not** replacing Square9.

---

## 2. Before you start (5 minutes)

You'll be given:

- **Your assigned document list** — printed sheet, one row per
  document with vendor + invoice # + a clickable Hub link.
- **A blank feedback CSV** — `AP_UAT_PILOT_FEEDBACK_TEMPLATE.csv`,
  same columns as below.
- **A note with the Hub URL and feedback drop location.**
- **The on-call IT engineer's name** — they'll be in the room.

Open the Hub URL in your browser and confirm you can sign in.

---

## 3. How to log in

1. Browser → `[HUB_URL_TBD]`
2. Sign in with your normal company credentials (same SSO you use
   for everything else; complete MFA if it prompts).
3. You should see the Hub home page with a list of recent
   documents.

If sign-in doesn't work after one try, ask IT in the room.
Don't keep guessing passwords.

---

## 4. How to open a document

1. On your assigned list, click the **Hub Link** for the document
   you want to test.
2. The document detail page opens.
3. Wait for the page to fully load (you'll see the PDF preview
   appear; usually under 3 seconds).

If the page never loads, that's a Blocker — log it and move on to
the next document.

---

## 5. The five things to look at, in order

Top to bottom on the document detail page:

### 5.1 Filename header

At the top, you'll see the document's filename. Confirm it matches
the invoice you expected.

> ✅ Pass: filename matches your assigned list.
> ❌ Fail: filename doesn't match — log it and move on.

### 5.2 Document Status card

A small card that tells you what the Hub thinks of this document.
You'll see one of:

- "Needs review"
- "Ready for posting"
- "Blocked — see issues"
- (or similar)

You don't need to act on this. Just **read it**. If the wording
is unclear or has weird code-looking words (e.g. things like
`vendor_unmatched`), that's a Low-severity feedback row.

### 5.3 AP Review panel — the main event

This is the panel just under the page header. It shows the five
core fields the Hub extracted from the invoice:

| Field | What to check |
| --- | --- |
| **Vendor** | Matches the vendor name on the PDF? |
| **Invoice #** | Matches the invoice number on the PDF? |
| **Invoice Date** | Matches the invoice date on the PDF? |
| **Total Amount** | Matches the total amount on the PDF? |
| **PO Number** | If the PDF has a PO, does it match? |

Compare each field side-by-side with the PDF preview. That's it.

### 5.4 Document Preview

The PDF should render right next to / below the AP Review panel.

> ✅ Pass: PDF loads and is readable.
> ❌ Fail: PDF doesn't load, or the wrong PDF appears (different
> invoice than the AP Review panel says) — Blocker, log it, move
> on.

### 5.5 Status / Blocking Issues

If the document has any blocking issues, they'll appear in the
Document Status card or just below the AP Review panel. They
should read in **plain English**, like:

- "Vendor not matched to a Business Central record yet."
- "Invoice date missing."
- "PO extracted but not found in Business Central."

If you see anything that reads like raw code (e.g. `po_validation`
or `{"check_name": ...`), that's a Medium-severity row.

---

## 6. The 12 scenarios (one per assigned document)

You're not running a 12-step process per document — these are the
**checks** you're doing. One feedback CSV row per document covers
them all.

| # | Check | What you do |
| --- | --- | --- |
| 1 | Open the document | Click the link, wait for the page |
| 2 | Confirm preview loads | PDF appears, is readable |
| 3 | Review Vendor field | Matches the PDF? |
| 4 | Review Invoice # | Matches the PDF? |
| 5 | Review Invoice Date | Matches the PDF? |
| 6 | Review Total Amount | Matches the PDF? |
| 7 | Review PO Number | Matches the PDF (if PO exists)? |
| 8 | Review Status / blocking issue text | Reads in plain English? |
| 9 | Spot duplicate warning | If the page shows "possible duplicate," log it |
| 10 | Spot non-invoice attachments | If the assigned doc isn't an invoice, log "wrong document type" |
| 11 | Report missing or wrong data | Log severity per the guide below |
| 12 | **Save nothing** | Don't click Save / Mark Ready / Post unless IT says |

---

## 7. Feedback CSV — what each column means

Columns in `AP_UAT_PILOT_FEEDBACK_TEMPLATE.csv`:

| Column | Example |
| --- | --- |
| Tester | `JD` |
| Date | `2026-05-12` |
| Document / Vendor | `Hawkemedia` |
| Invoice Number | `BILL-2026-04-84480` |
| Hub Link | (paste from assigned list) |
| What looked right | "Vendor and invoice # matched the PDF." |
| What looked wrong | "Total Amount field was blank." |
| What did you expect? | "Total $5,250.00 from line at the bottom of the PDF." |
| Severity | `Medium` |
| Screenshot attached? | `Yes` or `No` |
| Notes | Anything extra (optional) |
| IT follow-up needed? | `Yes` or `No` |

If everything matched, just put one short sentence in "What looked
right" and leave the rest empty (Severity = `Pass`).

---

## 8. Severity quick guide

- **Pass** — everything matched the PDF.
- **Low** — small wording / label issue, no data impact.
- **Medium** — one field wrong or missing, but you can read the
  correct value from the PDF.
- **High** — multiple fields wrong, OR something confusing that
  would slow you down at the rate you'd actually do this work.
- **Blocker** — page doesn't load, wrong vendor/invoice appears,
  or anything that looks like data from another customer / vendor.

When in doubt, bump it up one. IT will re-rank.

---

## 9. What you do **not** do

- Do **not** click "Post to BC."
- Do **not** click "Mark Ready."
- Do **not** click "Save" unless the on-call IT engineer points to
  a specific document and says, "Try saving this one for me."
- Do **not** test documents that aren't on your assigned list.
- Do **not** change vendor master data, classifications, or
  routing rules.
- Do **not** retry repeatedly if something errors. Log it once and
  move on.

---

## 10. What to do if a real payment depends on what you see

Stop testing for that document. Call your AP supervisor. Fall
back to Square9 and process the payment from there. Then come
back and log the Hub observation as a Blocker.

Real payments do not run through the Hub during this pilot.

---

## 11. After you finish

1. Save the feedback CSV with the name **`<your-initials>-<date>.csv`**
   (e.g. `JD-2026-05-12.csv`).
2. Drop it at: **`[FEEDBACK_DROP_LOCATION_TBD]`**.
3. If you took screenshots, drop them in a folder named
   `screenshots-<date>/` next to the CSV.
4. Tell the on-call IT engineer you're done.
5. Stay for the 15-minute debrief.

---

## 12. What happens next

- IT reads every row that day.
- Critical and Blocker items: addressed same day.
- High items: owner + target date assigned within 24 hours.
- Medium and Low: batched for the next round.
- We come back to you with a short summary of what was fixed and
  what's still open.

You will not be asked to do daily testing unless we mutually decide
that a longer pilot is useful.

---

## 13. Reminder of the pilot rules

- Square9 remains your system of record.
- Do not click Post / Mark Ready / Save without IT direction.
- Test only your assigned documents.
- Report every observation through the CSV.
- IT is in the room (or one phone call away) the entire time.

That's the whole plan. Thank you.
