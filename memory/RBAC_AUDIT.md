# P0.2 — RBAC Audit Gap List

**Status:** Authoritative audit run against the post-4d.8 working tree (Feb 2026).

## Single-line headline

**0 of 407 mutating endpoints currently enforce RBAC.** Every mutating endpoint is reachable by any authenticated caller (and in many environments, by anonymous callers given the current `routers/auth.py` posture). This is the 100% gap list that P1.C closes.

## Methodology

- Inventoried all routers with `@router.{post,put,patch,delete}` decorators (see `MUTATING_ROUTE_INVENTORY.md`).
- Searched all router files for any of: `Depends(require_role`, `Depends(require_admin`, `Depends(require_user`, `Depends(verify_role`, `Depends(role_required`, or any role-checking dependency pattern.
- Verified `routers/auth.py` exposes session/token decode but **does not** publish any role-enforcing FastAPI dependency for downstream routers to consume.

## Findings

| Surface | Count | Status |
|---|---|---|
| Mutating endpoints | 407 | All currently unguarded by RBAC |
| GET endpoints | 473 | None require RBAC; default `viewer` posture acceptable |
| Routers calling `Depends(require_role(...))` | **0** | Confirmed via grep |
| Routers calling `Depends(require_admin)` | **0** | Confirmed via grep |
| Existing role-enforcing dependency in `auth.py` | **None** | `auth.py` has session/token decode but no role-check dependency |

## What this means for P1.C

P1.C is the **complete** RBAC enforcement work for the system. There is no partial pre-existing RBAC layer to integrate with. P1.C will:

1. Land `backend/auth/rbac.py` exposing `require_role(*roles)` factory.
2. Add `Depends(require_role(...))` to all 407 mutating endpoints per the finalized `RBAC_MATRIX.md`.
3. Generate `tests/test_phase1_rbac_enforcement.py` programmatically — one probe per endpoint asserting anon→401, wrong-role→403, correct-role→200.

## Risk surfacing

- **Scale:** 407 endpoint touches in P1.C. Mechanical edit (single-line `Depends` insertion) but high count means strict change-management discipline (parity probes, git diff review).
- **Ordering:** P1.H must land first (provides the validated `Actor` object that `require_role` consumes). P1.C cannot start until then.
- **Rollback:** if P1.C breaks any endpoint, the system returns to "0 RBAC" — explicit feature flag (`RBAC_ENFORCEMENT_ENABLED`, default off in dev, on in staging→prod) deferred to P1.B in Phase 2; **for Phase 1 we land RBAC as always-on** because feature-flag plumbing is itself deferred.
