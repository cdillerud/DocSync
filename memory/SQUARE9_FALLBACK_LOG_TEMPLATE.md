# Square9 Fallback Log — Template

- Owner: Operations. One log per tester per shadow day.
- Generated: 2026-05-02 (UTC).
- Pairs with: `SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md` and
  `SQUARE9_USER_TEST_SCRIPTS.md`.

## What this is

Every time, during the shadow window, that you have to open
Square9 to finish a task or to verify that Hub is right, log it
here. **One row per fallback event.** No event is too small.

An empty log is the strongest possible evidence — it means you
did a full day of normal work without ever needing Square9.
Submit the log even if it has zero rows.

## Severity definitions (use exactly these)

- **blocker** — I could not complete the task without Square9
  and there was no acceptable workaround in Hub. The document
  was missing, wrong, or unfindable.
- **important** — I completed the task with Square9, but the
  Hub experience was bad enough that other users would also fall
  back. Examples: confusing UI, results I did not trust, search
  consistently missing the obvious doc.
- **minor** — I peeked at Square9 out of habit, for reassurance,
  or to compare. Hub had the answer, I just wanted to double-check.

## How to fill in a row

Be terse. One line per field is fine. The point is that the
operator can read 30 of these in 5 minutes and see the pattern.

| Field | What to put |
|---|---|
| tester name | Your name. |
| date / time (local) | When the fallback happened. Approx is fine. |
| group | accounting / warehouse / sales / management |
| task attempted | What you were trying to do, in your words. Tie it to a script row (e.g., "A6 — vendor statement reconciliation") if applicable. |
| document reference | Any identifier that helps trace it: invoice #, PO #, SO #, vendor name, customer name, BC document #, dollar amount + date. PII-safe is fine. |
| why hub failed or felt insufficient | The actual reason. "couldn't find by partial vendor name", "wrong document type filter count", "SharePoint link broken", "search returned 0 hits", "I didn't trust the answer", etc. |
| blocker / important / minor | Pick exactly one (definitions above). |
| temporary workaround used | What you actually did. "Opened Square9 and searched by vendor", "asked a coworker", "checked SharePoint directly", "skipped the task", etc. |

---

## Daily log

Tester name: ____________________

Group: accounting / warehouse / sales / management   (circle one)

Shadow day: ____________   Shift: ____________

| # | date / time (local) | task attempted | document reference | why hub failed or felt insufficient | severity (blocker / important / minor) | temporary workaround used |
|---|---|---|---|---|---|---|
| 1 |   |   |   |   |   |   |
| 2 |   |   |   |   |   |   |
| 3 |   |   |   |   |   |   |
| 4 |   |   |   |   |   |   |
| 5 |   |   |   |   |   |   |
| 6 |   |   |   |   |   |   |
| 7 |   |   |   |   |   |   |
| 8 |   |   |   |   |   |   |
| 9 |   |   |   |   |   |   |
| 10 |   |   |   |   |   |   |

Add additional rows as needed.

---

## End-of-day summary (fill in even if log is empty)

- Total fallback events today: ____
- Of those, blockers: ____   important: ____   minor: ____
- Did you complete your normal day's work? **yes / no**
- If Square9 disappeared tomorrow morning, would your day have
  been impacted? **yes / no / not sure** — one-line reason:

---

## Submission

- Hand to operator at end of shift, or drop in the agreed
  shared folder named `square9_shadow_<YYYY-MM-DD>/`.
- Filename suggestion: `fallback_<lastname>_<YYYY-MM-DD>.md`.
- The operator aggregates all daily logs into the CFO sign-off
  packet alongside the completed test scripts.
