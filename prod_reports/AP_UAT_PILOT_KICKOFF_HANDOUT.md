# GPI Hub — AP Pilot Kickoff Handout

Welcome, and thank you for helping with this pilot. This sheet is
your Day 1 cheat-sheet — keep it next to you while you test.

---

## What this is

A short, guided pilot of the GPI Document Hub. We want to know
whether the documents you'd normally see in Square9 read clearly
inside the Hub: vendor, invoice number, invoice date, total amount,
PO number.

That's it. We're not asking you to learn a new system. We're asking
you to look at the screen and tell us whether it makes sense.

## What this is **not**

- This is **not** a replacement for Square9. Square9 stays your
  working system of record throughout this pilot.
- This is **not** a "go live." The Hub is not posting anything to
  Business Central from your hands.
- This is **not** a long commitment. One short session today, plus
  a quick debrief.

---

## Five rules to keep the pilot safe

1. **Do not click "Post to BC."** If you see the button, leave it
   alone. Posting writes real entries to Business Central; it is
   not part of this pilot.
2. **Do not click "Mark Ready" or "Save"** unless IT says so on a
   specific document.
3. **Test only the documents on your assigned list.** Don't go
   exploring random invoices yet — random clicks make it harder for
   us to tell what's working and what isn't.
4. **Report everything in the feedback CSV.** Even small things.
   One row per observation. Don't worry about formatting; just
   write what you saw.
5. **If a real payment depends on something you see in the Hub,
   call your AP supervisor first**, not IT. Fall back to Square9
   and flag it. Hub bugs do not block real payments.

---

## How today goes

| Time | What happens |
| --- | --- |
| 0:00 – 0:30 | We read this handout together. We confirm your login works. We open one document together so you see what to expect. |
| 0:30 – 1:30 | You walk **10–15 assigned documents** at your own pace. One feedback row per document. IT is in the room — ask anything. |
| 1:30 – 1:45 | Quick debrief. We read your rows together, ask follow-ups, and answer questions. Then you're done. |

Total: about 90 minutes, including breaks.

---

## How to log in

1. Open your browser to: **`[HUB_URL_TBD]`**
2. Sign in with your normal company credentials. (Same SSO you use
   for everything else; if MFA prompts, complete it as usual.)
3. You should land on the Hub home page. If you see a list of
   documents, you're in.

If login doesn't work, tell IT in the room — don't keep retrying.

---

## How to open a document from your assigned list

Your assigned list will be handed to you on a single sheet of
paper. Each entry has:

- A **document link** (a URL).
- A **vendor name** and an **invoice number** (so you know what to
  expect).

Click the link. The document detail page opens.

---

## What you'll see on the document page (top to bottom)

1. **Filename** at the top — should match the invoice you expected.
2. **Document Status** card — tells you what the Hub thinks about
   this document right now (e.g., "Needs review," "Ready for
   posting").
3. **AP Review panel** — this is the panel you care about most.
   It's just under the header. It should show:
   - Vendor
   - Invoice #
   - Invoice Date
   - Total Amount
   - PO Number
4. **Document Preview** — the actual PDF, rendered in the browser.
   Scroll inside the preview if you need to.
5. **Other panels** below — Evidence, Risks, etc. You don't need
   to test those today.

---

## What to check on each document

For each document, ask yourself five questions and log one row:

1. Does the **PDF preview** load? (Yes / No)
2. Does the **Vendor** in the AP Review panel match the vendor on
   the PDF?
3. Does the **Invoice #** match?
4. Does the **Invoice Date** match?
5. Does the **Total Amount** match?

(PO Number is bonus — many invoices don't have one. If it's there
on the PDF and the Hub got it right, great. If the Hub got it
wrong, flag it.)

You're done with that document. One row in the CSV. Move on.

---

## How to tell if something is wrong

Some examples of "wrong" worth flagging:

- A field is **blank** but the PDF clearly shows it.
- A field is **filled in** but it doesn't match the PDF.
- The **Status / Blocking Issues** text is hard to read or doesn't
  make sense in plain English.
- The **PDF preview doesn't load** at all.
- The page shows a **duplicate warning** ("possible duplicate") —
  worth flagging even if you can't tell whether it's right.
- A **non-invoice attachment** (statement, packing list, freight
  note) shows up where you expected an invoice — flag it as
  "wrong document type" and move on.

You **don't** need to fix any of these. Just describe what you saw.

---

## What to ignore today

- The **other tabs / pages** in the Hub (Settings, Admin,
  Intelligence, etc.). Stay on document detail pages.
- **Performance / speed.** Unless the page is unusable, don't log
  speed observations today.
- **Documents you weren't assigned.** Even if they look interesting.
- **Suggestions about how to redesign the UI.** Useful, but later.

---

## How to submit feedback

You'll be given a copy of `AP_UAT_PILOT_FEEDBACK_TEMPLATE.csv`. For
each document, fill in **one row**:

| Column | What to put |
| --- | --- |
| Tester | Your initials |
| Date | Today |
| Document / Vendor | Vendor name |
| Invoice Number | The invoice # from the PDF (or what the Hub showed) |
| Hub Link | The link from your assigned list |
| What looked right | One short sentence |
| What looked wrong | One short sentence (leave empty if everything was fine) |
| What did you expect? | One short sentence (only if something was wrong) |
| Severity | Pass / Low / Medium / High / Blocker |
| Screenshot attached? | Yes / No |
| Notes | Anything else |
| IT follow-up needed? | Yes / No |

If you took a screenshot, save it next to the CSV with a name
that includes the invoice number (e.g.
`screenshot-BILL-2026-04-84480.png`).

When you're done, save the CSV to:

> **`[FEEDBACK_DROP_LOCATION_TBD]`**

IT will read every row.

---

## Severity guide (so we triage right)

- **Pass** — everything matched the PDF. Common.
- **Low** — small label / wording issue, no impact on the data.
- **Medium** — a field is wrong or missing, but you can see what
  it should be from the PDF.
- **High** — multiple fields wrong, or a confusing UI moment that
  would slow you down day-to-day.
- **Blocker** — the page won't load, the wrong vendor/invoice
  appears, or anything that looks like a data leak.

When in doubt, log it one severity higher than you think — IT will
re-rank it.

---

## Who to call

- **In the room with you:** IT engineer **`[IT_ATTENDEE_TBD]`**.
- **Login issues / Hub down:** IT mailbox
  **`[IT_MAILBOX_TBD]`**.
- **A real payment is at risk because of something you see:** your
  AP supervisor first, then IT.

---

## After today

- IT reads every feedback row.
- Critical / Blocker items get same-day attention.
- Medium / High items get owners and target dates within a week.
- We'll come back to you with a short note on what was fixed and
  what's still open.

You won't be asked to keep testing daily unless we decide together
that a longer pilot is useful.

---

## One more time, the rules

- Do not click Post.
- Do not click Mark Ready or Save.
- Square9 is still the system of record.
- Test only your assigned documents.
- Log everything in the CSV.

Thanks again — your eyes on this pilot are the part we can't
automate.
