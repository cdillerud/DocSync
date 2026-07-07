# Branch Guide — read this before assuming `main` is current

**TL;DR: `main` is NOT the production branch. `production-current` is.**

This repo's branch names don't reflect reality, and it cost a full session
to untangle (2026-07-07). Writing this down so the next person doesn't
have to redo that work.

## The actual lineage

`production-current` (tracking `origin/conflict_150326_1947` as of this
writing) is the real, continuously-developed codebase — **2,510 commits**,
forked from `main` back on 2026-02-12 and developed continuously through
2026-05-13. It has the mature `backend/routers/` + `backend/policies/` +
`backend/models/` structure, live LLM-based document classification,
knowledge seeding, PO resolution, gap-closing logic, and is what's
actually deployed and running on the production VM (`/opt/gpi-hub`).

`main` has **1,069 commits** and is a much smaller, comparatively stale
side-branch. Several `feature/*` branches were built on top of `main`
(not on top of `production-current`) and are very likely redundant with
work that already exists, independently, on `production-current` — e.g.
`feature/sales-order-intake-preflight` built its own sales-order-review
page and services, but `production-current` already has a
`SalesOrderReviewPage.js` and `sales_order_reviewer_feedback_service.py`
of its own, built separately. Don't assume a `feature/*` branch is ahead
of `production-current` just because it's ahead of `main` — check actual
file contents, not just commit-graph position relative to `main`.

## How this happened (best guess)

The four `conflict_DDMMYY_HHMM` branches (`conflict_020326_1424`,
`conflict_120326_1320`, `conflict_130326_1349`, `conflict_150326_1947`)
all share the exact same fork point from `main` (2026-02-12) and have
strictly increasing commit counts (1148 → 1163 → 1310 → 2510) and dates
(Mar 11 → Mar 13 → Mar 15 → May 13). That's not four separate branches —
it's one continuous lineage that got a new branch name each time an
automated tool (commit authorship is `emergent-agent-e1` /
`github@emergent.sh`, consistent with the Emergent AI-assisted dev
platform) hit an internal merge conflict and had to fork a fresh branch
to keep going, without ever renaming anything back to something sane or
merging back into `main`.

## What's still open

- `production-current`'s trail in git goes cold at 2026-05-13. It's
  2026-07-07 now. Either work continued somewhere that never got pushed
  to GitHub, or it's been sitting still for ~2 months. Worth finding out
  which.
- There's an unresolved, CFO/AP-Director-level decision from
  `memory/SQUARE9_CUTOVER_SLIP_DECISION.md` (2026-05-08): the Square9
  cutover was slipped due to a 45.45% audited AP match rate against an
  85% gate. As of 2026-07-07, Square9 is still the system of record. A
  fully-scoped, dry-run-validated remediation plan for the two biggest
  known gaps (Bucket A: 46 misclassified docs; Bucket C: 3 vendor email
  aliases + 2 manual follow-ups) exists under `prod_reports/` but was
  never applied.
- `main` and its `feature/*` descendants should probably be either
  archived/deleted or explicitly reconciled against `production-current`
  once someone with full context signs off - right now they're just a
  trap for the next person who assumes `main` means "current."

## If you're about to build something here

Branch from `production-current`, not `main`, unless you've specifically
verified otherwise.
