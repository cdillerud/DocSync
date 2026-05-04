# Square9 Cutover — CFO Summary

One page. Fill in after the shadow window. The CFO reads this
and decides. The full packet sits behind it.

---

**Objective.** Determine whether Square9 can be turned off
without disrupting users' daily work, based on a live shadow /
UAT window run in parallel with normal operations.

**Shadow window.** Start: ____________________   End: ____________________   (UTC).

**Tester groups involved.**
- Accounting / AP: ______________________________________________
- Warehouse / Shipping: ________________________________________
- Sales / Customer Service: ____________________________________
- Management / Audit (optional): _______________________________

**Overall result** (circle one):
- READY — Square9 can be turned off Friday.
- READY WITH MINOR EXCEPTIONS — turn off Friday; backlog items logged.
- NOT READY — postpone cutover; remediate; re-run shadow window.

---

**Critical workflows tested** (one line each, per acceptance checklist §2):
- AP daily work (find by vendor, find by invoice #, statement reconciliation, posting status visible): _________________________
- Warehouse / shipping daily work (find by PO, packing slip / BOL, browse today's docs, SharePoint open): _____________________
- Sales / CS daily work (find by SO #, by customer PO, customer 30-day list, sales-mailbox ingestion): _______________________
- Cross-cutting (free-text search, quick filters, shareable URL, SharePoint links): __________________________________________

**Pass / fail summary.**
- Total tasks attempted: ______
- PASS: ______   FAIL: ______
- Critical workflows with any FAIL: ______ (list, if any: ____________________________________________)

**Fallbacks to Square9 during the window.**
- Total fallback events: ______
- Distinct testers who opened Square9 at least once: ______ of ______
- Severity breakdown: blocker ______   important ______   minor ______

**Top 3 issues** (if any — leave blank if none):
1. ____________________________________________________________________________
2. ____________________________________________________________________________
3. ____________________________________________________________________________

---

**What was proven.**
- Hub serves search, browse, filter, retrieval, and document
  detail for all business-critical doc types: ______ (yes / no).
- Sales-mailbox ingestion (G2) ran cleanly through the window:
  ______ (yes / no — cycles: ____, errors: ____).
- AP posting baseline unchanged vs Batch-3: ______ (yes / no).
- SharePoint links from Hub work for tested doc types: ______ (yes / no).

**What remains open** (items deferred but not blocking):
- ______________________________________________________________________________
- ______________________________________________________________________________

---

**CFO decision** (check exactly one):

[  ] Approve Friday cutover. Operator may issue the verbatim
     Friday clearance line per `SQUARE9_CUTOVER_PLAN.md` §6 and
     fire `POST /api/square9/archive-stage-data`. Rollback path
     remains in place.

[  ] Delay cutover pending fixes. Engineering remediates the
     listed top issues. A fresh shadow window must run before
     the next decision.

---

**Sign-off.**

Operator (name, role, timestamp UTC):
______________________________________________________________

CFO (name, timestamp UTC):
______________________________________________________________

---

*Evidence sources behind this summary:*
`SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md` (proof bar) ·
`SQUARE9_USER_TEST_SCRIPTS.md` (completed tester scripts) ·
`SQUARE9_FALLBACK_LOG_TEMPLATE.md` (per-tester per-day fallback logs).
