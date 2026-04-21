# Dual AP Path — Consolidation Decision

**Date:** 2026-04-21
**Status:** DECIDED — consolidation work itemized below
**Author:** E1 (following Finding #8 of the 2026-04 engineering review)

---

## Problem

The codebase carries two parallel AP invoice workflows:

| Path | Router file | Frontend caller | Uses `workflow_engine.py`? |
|---|---|---|---|
| **A.** `/api/ap-review/*` | `routers/ap_review.py` | `APReviewPanel.js` (Document Detail page — **active, user-facing**) | **No** — bypasses it |
| **B.** `/api/workflows/ap_invoice/*` | `routers/workflows.py` + `routers/pilot.py` | `APWorkflowsPage.js` (**removed from nav** per CHANGELOG) | **Yes** — proper state machine |

The `workflow_engine.py` module is the best-engineered part of the backend (per the review's own words). It sits behind Path B — which is operationally dead. Path A, which is operationally live, never touches it.

`server.py` even has guard handlers at lines 6612 / 6670 / 6728 that raise HTTP errors *directing callers to Path B* — a dead letter.

Meanwhile, every improvement shipped in this codebase over the past 24 hours (v2.5.20 reconciliation, v2.5.21–22 vendor profile learning, v2.5.23 atomic claim, today's per-line BC routing + partial-post detection) landed on **Path A**.

## Decision

**Path A (`/api/ap-review/*`) is the canonical AP workflow going forward.**

Justification — pragmatic, not aesthetic:

1. **User reality.** `APReviewPanel.js` is the only AP surface a user can reach today. The `APWorkflowsPage` was intentionally removed from navigation. There is zero operational benefit to preserving Path B.
2. **Recent investment.** Five consecutive releases (v2.5.20 → v2.5.24) hardened Path A end-to-end: line-math reconciliation, preflight sanity gates, vendor profile fallbacks, atomic claim, per-line BC routing, partial-post detection. Path B has none of these.
3. **Alignment with `REFACTOR_PLAN.md`.** The plan says: *"APWorkflowsPage → merge into QueuePage"*. The page dies; its backend routes die with it.
4. **The workflow engine is not lost.** `workflow_engine.py` is a module, not a router. Path A can (and should) adopt its state machine without keeping Path B's routes alive.

## Consolidation Plan (bounded, ~3 days)

### Phase 1 — Make the decision non-regressive (this PR, done today) ✅
- [x] Documented in this memo
- [x] CHANGELOG entry calling Path A canonical
- [x] Path A's `post-to-bc` flow is race-safe + amount-safe + classification-safe (v2.5.20–24)

### Phase 2 — Port the useful Path-B logic into Path A (1–2 days) ✅ 2026-04-21
- [x] Audit each `/workflows/ap_invoice/*` endpoint. The six mutation endpoints
      (`set-vendor`, `update-fields`, `override-bc-validation`, `start-approval`,
      `approve`, `reject`) were re-exposed on Path A as thin delegators that
      reuse the authoritative handlers in `services/workflow_handlers.py`.
      The query endpoints (status-counts, *-pending queues, metrics) stay on
      Path B — they are read-only and carry no state-machine drift risk.
- [x] Specific endpoints audited:
  - `set-vendor` → Path A: `POST /api/ap-review/documents/{id}/set-vendor`
  - `update-fields` → Path A: `POST /api/ap-review/documents/{id}/update-fields`
  - `override-bc-validation` → Path A: `POST /api/ap-review/documents/{id}/override-bc-validation`
  - `start-approval` → Path A: `POST /api/ap-review/documents/{id}/start-approval`
  - `approve` → Path A: `POST /api/ap-review/documents/{id}/approve`
  - `reject` → Path A: `POST /api/ap-review/documents/{id}/reject`
- [x] All Path A mutation routes are gated by `Depends(get_current_user)` JWT.
- [x] Frontend `lib/api.js` helpers (`setVendor`, `updateFields`,
      `overrideBcValidation`, `startApproval`, `approveDocument`,
      `rejectDocument`) repointed to Path A with correct body shapes for
      `SetVendorRequest` / `UpdateFieldsRequest` / `BCValidationOverrideRequest` /
      `ApprovalActionRequest`.
- [x] Regression suite: `tests/test_ap_path_consolidation.py` (36 cases)
      covers route registration, deprecation flags, JWT enforcement on Path A,
      and X-Deprecated header survival on Path B error responses.

### Phase 3 — Deprecate Path B (half day) ✅ 2026-04-21
- [x] Every `/workflows/ap_invoice/{id}/{action}` mutation handler is
      registered with `deprecated=True` (shows in OpenAPI) AND wrapped in
      `routers/workflows.py::_deprecate(...)` so every response — including
      handler-raised HTTPException paths — carries:
        - `X-Deprecated: true`
        - `X-Deprecated-Sunset: next-release`
        - `X-Deprecated-Use: /api/ap-review/documents/{doc_id}/{action}`
- [x] Routes remain live for one release window so any outside caller (BC
      extension, test scripts) has time to migrate.

### Phase 4 — Delete Path B (half day, next release)
- [ ] Remove `routers/workflows.py` (AP portion — leave the shell if it routes other doc types)
- [ ] Remove the redirect handlers in `server.py`
- [ ] Delete `APWorkflowsPage.js`, `WorkflowQueue.js`
- [ ] Remove the now-orphaned `workflow_engine` callsites that only Path B used
- [ ] Run the full pytest + manual regression over `APReviewPanel.js`

### Phase 5 — Adopt workflow_engine from Path A (part of `REFACTOR_PLAN` Phase 3)
- [ ] `POST /ap-review/documents/{id}/post-to-bc` should drive `workflow_engine.advance_workflow(doc, target=POSTED)` before calling `claim_for_bc_post`
- [ ] Status transitions emitted by the engine produce `WorkflowHistoryEntry` audit rows (they do not today on Path A)
- [ ] This closes the reviewer's finding *"bypasses the workflow engine"* structurally, not just by delete-and-hope

## What the user-facing experience looks like

No change today. This is pure backend hygiene. The demo path (XPOLOGI / TUMALOC → Post to BC) is already on Path A and is already green.

## Rollback plan

If Phase 2 porting uncovers a Path-B behavior that can't be reproduced on Path A in reasonable time, we halt before Phase 3. Path B remains live as an escape hatch. No data loss risk — both paths write to the same `hub_documents` collection; the only drift is audit/state-machine invariants.
