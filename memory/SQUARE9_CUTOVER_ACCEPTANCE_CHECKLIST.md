# Square9 Cutover — Acceptance Checklist

- Owner: Operations + Engineering, presented to CFO for sign-off.
- Generated: 2026-05-02 (UTC).
- Purpose: Define the non-negotiable proof standard that must be
  met before Square9 is turned off. Anything below this bar
  means the cutover does not happen on Friday.
- Companion artifacts:
  - `SQUARE9_USER_TEST_SCRIPTS.md` — real-world task scripts.
  - `SQUARE9_FALLBACK_LOG_TEMPLATE.md` — evidence log of any
    fallback to Square9 during the shadow window.
  - `SQUARE9_READY_FOR_CUTOVER.md` — engineering-side readiness.
  - `SQUARE9_CUTOVER_PLAN.md` — operational runbook.

---

## 1. Critical user groups

These are the populations whose normal day must remain unchanged
the morning Square9 is off. If any one of these groups cannot
complete their daily work without Square9 during the shadow
window, cutover is blocked.

| Group | Representative roles | Daily volume signal |
|---|---|---|
| Accounting / AP | AP clerk, AP lead, controller | AP invoices in/posted, vendor lookups, statement reconciliation |
| Warehouse / Shipping | Warehouse clerk, shipping lead | POs received, packing slips, BOLs, freight docs |
| Sales / Customer Service | Sales coordinator, CS rep, sales manager | Sales orders, order confirmations, customer-PO lookups |
| Management / Audit | Controller, CFO, auditors (occasional) | Search-by-customer, search-by-date, document retrieval for audit |

Out-of-scope for this checklist (do not block cutover on these):
- DocuSign / contract intelligence users.
- Engineering / dev-tool flows.

---

## 2. Critical workflows (must pass on Hub without Square9)

Each row is a workflow that, today, a user could plausibly do in
Square9. Each must be demonstrably doable in Hub during the
shadow window. The associated test script lives in
`SQUARE9_USER_TEST_SCRIPTS.md`.

### Accounting / AP

- A1. Find a specific AP invoice by vendor name.
- A2. Find a specific AP invoice by invoice number.
- A3. Find all AP invoices for a vendor in a date range.
- A4. Open an AP invoice and see line items + extracted fields.
- A5. Open the SharePoint copy of an AP invoice from Hub.
- A6. Reconcile a vendor statement: list invoices for vendor X
      between two dates and confirm presence/absence.
- A7. View posting status / BC document number on an AP invoice.

### Warehouse / Shipping

- W1. Find a Purchase Order by PO number.
- W2. Find a packing slip / BOL by reference number.
- W3. Browse "today's shipping documents" or recent warehouse
      docs without typing a query.
- W4. Open a warehouse / shipping document and see classification
      and routed SharePoint folder.
- W5. Open the SharePoint copy from Hub.

### Sales / Customer Service

- S1. Find a sales order by SO number.
- S2. Find a sales order by customer PO number.
- S3. Find all documents tied to a customer in the last 30 days.
- S4. Open an order confirmation and verify it routed correctly.
- S5. Open the SharePoint copy from Hub.
- S6. Sales-mailbox-originated docs (G2 path) appear in Hub
      within the agreed SLA after delivery to the sales mailbox.

### Cross-cutting

- X1. Free-text search returns the right document for a query a
      user would type into Square9 today (e.g. partial vendor
      name, partial customer name, BC number, dollar amount).
- X2. Quick-filter chips (AP Invoices, Purchase Orders, Sales,
      Warehouse / Shipping, Unclassified, Needs Review,
      Exceptions) return the populations a user expects.
- X3. URL deep-link to a search result is shareable and reopens
      the same view for another user.
- X4. Document detail page renders and the SharePoint link works.

---

## 3. Pass / fail criteria

A workflow is **PASS** only if all four are true:
1. The tester completed the task entirely in Hub.
2. The tester did **not** need to open Square9 to finish or
   verify the task.
3. The result matched what they would have gotten from Square9
   (same document, same metadata material to the task).
4. The tester rated it as "same speed or faster, not confusing"
   compared to Square9. Marginal slower-but-acceptable is still
   PASS; "confusing or measurably worse" is FAIL.

A workflow is **FAIL** if any of the following:
- Tester had to fall back to Square9 to finish the task.
- The correct document was not retrievable in Hub.
- The Hub result was wrong (different document, missing metadata
  the user relies on).
- Tester rated UX as "confusing or materially worse" — this is a
  FAIL even if the document was technically findable, because the
  CFO bar is invisibility, not technical sufficiency.

Test attempts that produced **zero** correct documents because
none exist (e.g., querying for a vendor that has no docs in the
window) do not count for or against — discard and re-pick a real
example.

---

## 4. What counts as a BLOCKER (cutover does not happen)

Any one of the following blocks Friday cutover:

- B1. ≥ 1 FAIL in workflows A1, A2, A4, A6, A7 (core AP daily
      work).
- B2. ≥ 1 FAIL in workflows W1, W2, W4 (core warehouse daily
      work).
- B3. ≥ 1 FAIL in workflows S1, S2, S4 (core sales daily work).
- B4. ≥ 1 FAIL in any cross-cutting workflow (X1–X4).
- B5. Any fallback-log entry tagged **blocker** by the tester
      that operations cannot mitigate before Friday.
- B6. G2 sales mailbox polling stops ingesting during the shadow
      window (any non-zero error rate over a sustained interval).
- B7. SharePoint links from Hub are broken for any tested
      document type.
- B8. AP posting path shows any regression vs Batch-3 baseline
      during the shadow window.

If a blocker is hit, cutover is postponed. Engineering remediates
or scopes a workaround; a fresh shadow window is run.

---

## 5. What counts as MINOR / non-blocking

Document and ship; do not block on:

- M1. Cosmetic UX preference (font size, spacing, label wording)
      provided the document is retrievable and the task completes.
- M2. Slower-than-Square9 by an acceptable margin (≤ ~2× the
      Square9 time on the same task) when the task still
      completes correctly without fallback.
- M3. Doc-type filter shows a count off by a small number due to
      reclassification lag; the tester can still find the doc by
      free-text or another filter.
- M4. Empty-state messaging or error copy is unfriendly but does
      not block completion.
- M5. Non-tested doc types (e.g., legacy Square9-only archive
      categories with zero current daily usage) — these stay in
      Square9 archive read-only mode if needed and are out of
      scope for cutover.

Minor items are still logged in the fallback log with severity
**minor** and are queued as backlog.

---

## 6. Required shadow-period evidence

To meet the CFO bar, the shadow/UAT window (1–2 business days)
must produce all of the following artifacts:

- E1. **One fallback log per tester per day**, even if empty,
      using `SQUARE9_FALLBACK_LOG_TEMPLATE.md`. An empty log is
      itself evidence: it shows a tester worked a full day
      without needing Square9.
- E2. **Completed test-script sheets** — every script row in
      `SQUARE9_USER_TEST_SCRIPTS.md` filled in by at least one
      tester per applicable group (AP, warehouse, sales).
- E3. **Aggregate scoreboard** with: total tasks attempted,
      PASS count, FAIL count, fallback count by severity
      (blocker / important / minor).
- E4. **G2 polling health snapshot** for the shadow window:
      number of poll cycles run, messages detected, error count
      (must be zero or operationally explained).
- E5. **AP posting baseline check**: confirmation that the
      Batch-3 5/5 P1 posting result is unchanged during the
      shadow window — no AP posting regressions.
- E6. **Operator narrative**: 1-paragraph summary per tester
      ("how the day felt"), capturing whether Square9 was
      missed, ignored, or actively wanted.
- E7. **Square9 access metric (optional but valuable)**: count
      of distinct testers who opened Square9 during the shadow
      window for any reason. Zero is the strongest possible
      signal; a small number with logged reasons is acceptable
      if all reasons are minor or archive-only.

All evidence is collected into a single packet and attached to
the CFO sign-off.

---

## 7. Decision matrix

| Result | Meaning | Action |
|---|---|---|
| 0 blockers, 0 important fallbacks, all critical workflows PASS | Square9 is invisible to users. | Cutover Friday. |
| 0 blockers, ≤ small number of *minor* fallbacks, all critical workflows PASS | Square9 is effectively invisible. | Cutover Friday; backlog the minors. |
| 0 blockers, ≥ 1 *important* fallback that operations can mitigate before Friday | Recoverable. | Mitigate, re-test the affected workflow, then cutover. |
| ≥ 1 *blocker* (per §4) | Not invisible. | Postpone cutover; remediate; re-run shadow window. |

---

## 8. Final readiness statement (for CFO review)

Use exactly this template once the shadow window closes. Anyone
who pastes a different summary line should be ignored.

> Square9 cutover readiness — CFO signoff package
>
> Shadow window: <start> → <end> (UTC).
> Testers: <names + groups>.
> Tasks attempted: <N>. PASS: <N>. FAIL: <N>.
> Fallback events: blocker=<N>, important=<N>, minor=<N>.
> G2 polling: <cycles> cycles, <errors> errors.
> AP posting baseline: <unchanged | regressed>.
> Critical workflows: <PASS-on-all | FAIL-on: list>.
>
> Decision: <Cutover authorized for Friday | Cutover postponed,
> re-shadow scheduled for <date>>.
>
> Authorizing signature: <Operator name, role, timestamp UTC>.
> CFO acknowledgment: <Name, timestamp UTC>.

If, and only if, the decision line reads "Cutover authorized for
Friday" and the operator pastes the verbatim Friday clearance
line specified in `SQUARE9_CUTOVER_PLAN.md` §6, engineering
fires `POST /api/square9/archive-stage-data`. Anything else =
no cutover.
