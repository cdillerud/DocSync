# Square9 User Test Scripts — Shadow / UAT Window

- Owner: Operations. Distribute to testers in each group.
- Generated: 2026-05-02 (UTC).
- Window: 1–2 business days, in parallel with normal work.
- Pairs with: `SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md` (pass /
  fail bar) and `SQUARE9_FALLBACK_LOG_TEMPLATE.md` (log every
  time you have to go back to Square9).

---

## How to use these scripts

1. Pick **your real work** for that day. Do not invent fake
   scenarios. The point is to test what you actually do.
2. Try each task **in Hub first.** Only open Square9 if you
   genuinely cannot finish in Hub or you cannot trust the
   answer Hub gives you.
3. For each row, fill in the four columns:
   - **completed in hub?** yes / no
   - **needed Square9?** yes / no
   - **confusing/slower than Square9?** yes / no
   - **notes** — short. The document number you used, the
     vendor / customer, what felt off, anything you'd want
     leadership to know.
4. If you had to go back to Square9 for any reason, also create
   one row in `SQUARE9_FALLBACK_LOG_TEMPLATE.md` for that event.
5. Hand the completed script to the operator at end of day.
   An empty fallback log is a good outcome, not a missing one.

There are no trick questions. Honest "no, I had to go back to
Square9" answers are the most valuable data we can collect.

---

## Group A — Accounting / AP

Tester: ____________________   Date: ____________   Mailbox / role: ____________________

| # | Task | Completed in Hub? | Needed Square9? | Confusing/slower than Square9? | Notes |
|---|---|---|---|---|---|
| A1 | Pull up the most recent AP invoice from a vendor you process every week. Use vendor name only. |   |   |   |   |
| A2 | Pull up a specific AP invoice by its invoice number — pick one from a paper or email reference today. |   |   |   |   |
| A3 | List all AP invoices from one vendor between two specific dates (e.g., last month). |   |   |   |   |
| A4 | Open one AP invoice and verify the line items and amount are correct vs the source PDF. |   |   |   |   |
| A5 | Open the SharePoint copy of that AP invoice from Hub (one click from the document). |   |   |   |   |
| A6 | Reconcile a vendor statement: take a real statement on your desk, find each invoice listed in Hub, and confirm what is present and what is missing. |   |   |   |   |
| A7 | On a posted AP invoice, confirm the BC document number / posting status is visible in Hub. |   |   |   |   |
| A8 | Find an AP invoice you remember by approximate dollar amount only (no vendor, no invoice #). |   |   |   |   |
| A9 | Use the "Exceptions" or "Needs Review" quick filter — does the population match what you'd expect to triage today? |   |   |   |   |
| A10 | Share a Hub search result with a coworker via copy/paste of the URL — do they see the same view? |   |   |   |   |
| A11 | Pick one AP invoice you processed today. Open its SharePoint copy from Hub and confirm the file path lands under: `/sites/GamerAccounting/Shared Documents/General/Accounting/Accounts Payable/Temp Folder`. Note any AP doc that lands somewhere else. |   |   |   |   |

End-of-day narrative (1–3 sentences). Did your AP day feel
normal? Did you actively miss Square9, ignore it, or want it?

---

## Group B — Warehouse / Shipping

Tester: ____________________   Date: ____________   Mailbox / role: ____________________

| # | Task | Completed in Hub? | Needed Square9? | Confusing/slower than Square9? | Notes |
|---|---|---|---|---|---|
| W1 | Find a Purchase Order by PO number — pick one a driver or vendor referenced today. |   |   |   |   |
| W2 | Find a packing slip or BOL by reference number from a real shipment. |   |   |   |   |
| W3 | Use the "Warehouse / Shipping" quick filter to browse today's recent shipping documents — without typing a query. |   |   |   |   |
| W4 | Open a warehouse / shipping document and verify it routed to the correct SharePoint folder (assembly, GT's, ball orders, UPS orders, international, etc., as applicable). |   |   |   |   |
| W5 | Open the SharePoint copy of that document from Hub. |   |   |   |   |
| W6 | Find a freight / international shipping document if your day involved one. |   |   |   |   |
| W7 | Find a return / RMA-related document if your day involved one. |   |   |   |   |
| W8 | Use free-text search to find a doc by carrier name or container/tracking-style reference, the way you'd type it into Square9 today. |   |   |   |   |
| W9 | Take one document Square9 would normally surface "by browsing" and see if a quick filter chip + a single tweak gets you the same view. |   |   |   |   |

End-of-day narrative. Did your warehouse / shipping day feel
normal? Did you actively miss Square9, ignore it, or want it?

---

## Group C — Sales / Customer Service

Tester: ____________________   Date: ____________   Mailbox / role: ____________________

| # | Task | Completed in Hub? | Needed Square9? | Confusing/slower than Square9? | Notes |
|---|---|---|---|---|---|
| S1 | Find a sales order by SO number from a real customer call or email today. |   |   |   |   |
| S2 | Find a sales order by customer PO number (not your SO number). |   |   |   |   |
| S3 | List all documents tied to one customer in the last 30 days — does the population look right? |   |   |   |   |
| S4 | Open an order confirmation and verify it routed correctly + extracted fields look right. |   |   |   |   |
| S5 | Open the SharePoint copy of a sales doc from Hub. |   |   |   |   |
| S6 | Email a sales-related document to the sales mailbox (or have a customer do it). Wait the agreed SLA. Confirm it shows up in Hub via the "Sales" quick filter. |   |   |   |   |
| S7 | Find a sales document by approximate ship date only. |   |   |   |   |
| S8 | Free-text search by customer name fragment the way you'd type it into Square9 today. |   |   |   |   |
| S9 | Share a Hub search result URL with another sales coworker — do they see the same view? |   |   |   |   |

End-of-day narrative. Did your sales / CS day feel normal? Did
you actively miss Square9, ignore it, or want it?

---

## Optional — Group D — Management / Audit spot checks

Use only if a manager or auditor is on the floor during the
shadow window.

Tester: ____________________   Date: ____________   Role: ____________________

| # | Task | Completed in Hub? | Needed Square9? | Confusing/slower than Square9? | Notes |
|---|---|---|---|---|---|
| D1 | Pull all documents tied to a specific customer or vendor for an audit-style date range. |   |   |   |   |
| D2 | Retrieve one specific document by BC document number. |   |   |   |   |
| D3 | Confirm a posted AP invoice in Hub matches BC for the same number. |   |   |   |   |
| D4 | Open one document of each type (AP invoice, PO, sales order, warehouse / shipping doc) and confirm the SharePoint link works. |   |   |   |   |

---

## Submission

End of each shadow day:

- Hand the completed script to the operator (or drop in the
  agreed shared folder).
- Submit your fallback log for the day, even if it has zero
  rows.
- One line at the bottom of your script: would *you*
  personally be comfortable if Square9 were turned off
  tomorrow morning? **yes / no / not sure** — and one short
  reason.

That last line is the most important one on the page.
