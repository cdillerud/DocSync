# P0.6 — Phase 1 Acceptance Criteria

**Status:** Authoritative checklist. Approved during P0 review. Phase 1 is "done" iff every item below is green.

## Hard gates (block deploy)

### Auth & Identity (P1.H + P1.K)
- [ ] `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_API_AUDIENCE` set on backend `.env`; `REACT_APP_ENTRA_TENANT_ID`, `REACT_APP_ENTRA_CLIENT_ID`, `REACT_APP_ENTRA_API_SCOPE` set on frontend `.env`.
- [ ] Backend `services/entra_auth_service.py::validate_token` validates a real Entra-issued access token end-to-end (test recipe R1 from Entra playbook).
- [ ] JWKS cache hits ≥ 95% of validations under steady-state (verify via SLO-1 measurement).
- [ ] Backend rejects: expired tokens, wrong-tenant tokens, wrong-audience tokens, malformed tokens, tokens signed with unknown `kid`.
- [ ] Frontend `<MsalProvider>` wired; login (popup) works against staging tenant; silent token acquisition with interactive fallback works.
- [ ] Every API call from frontend carries `Authorization: Bearer …` header (verify by browser network tab smoke).
- [ ] Protected routes redirect unauthenticated users; render content only when authenticated.
- [ ] **18+ Phase 1 auth test probes pass.**

### Authorization (P1.C)
- [ ] All 407 mutating endpoints have `Depends(require_role(...))` per finalized `RBAC_MATRIX.md`.
- [ ] `tests/test_phase1_rbac_enforcement.py` generates one probe per endpoint; all pass.
- [ ] Anonymous → 401, wrong-role → 403, correct-role → 200 verified per endpoint.
- [ ] No mutating endpoint returns 200 to anonymous caller.

### Actor Context (P1.J)
- [ ] `current_actor: ContextVar` set per request; cleared on response.
- [ ] 100 concurrent requests with distinct actors → 0 contextvar leakage (probe).
- [ ] Audit log rows (P1.A) carry `actor.oid`, `actor.preferred_username`, `actor.roles[]`.
- [ ] Async-task propagation verified.

### Audit Log (P1.A)
- [ ] `governance_audit_log` collection created with indexes on `(correlation_id, ts)`, `(actor_oid, ts)`, `(event_type, ts)`.
- [ ] Mutating endpoint hit → 1 audit row with all required fields populated.
- [ ] Append-only enforced: negative test attempts `update_one` → raises.
- [ ] Replay query by correlation_id returns full causal chain for any 24-hour window.
- [ ] No-PII assertion: audit payload never carries customer SSN/credit-card/etc. (probe scans payload schema).

### Preflight & Deploy (P1.F)
- [ ] `scripts/preflight.sh` runs 277+ Phase 3 parity probes + Phase 1 acceptance suite; exits 0 only when all pass.
- [ ] `scripts/postdeploy_smoke.sh` hits `/api/health` + `/openapi.json` + audit script + 1 authenticated round-trip; exits 0 only against healthy deploy.
- [ ] `DEPLOY_P1_PHASE1.md` runbook references both scripts as required steps.

## Soft gates (non-blocking but tracked)

- [ ] `routers/governance.py` audit-log read endpoint (deferred to P1.G in Phase 2 — placeholder doc only).
- [ ] OpenAPI path count delta = +N (where N = exact count of new endpoints introduced by P1.A audit-log read + P1.C RBAC). Document the band in deploy runbook.
- [ ] Phase 3 parity surface still **277/277 PASS** post-Phase-1.
- [ ] No regression in 4d.8 reverse-arrow-cleanup probes.
- [ ] Sandbox full-regression baseline shifts only by the count of new Phase 1 tests (e.g. `4847 P + N` vs. prior `4847 P`).

## Frozen, never-touched-in-Phase-1

- [ ] `_attempt_llm_vendor_ranking` body unchanged.
- [ ] `_build_vendor_resolution` body unchanged.
- [ ] `services/document_handlers.py` lazy `from server import (...)` tuple = exactly 2 entries (`_attempt_llm_vendor_ranking`, `_build_vendor_resolution`).
- [ ] `workflows/document_capture/rules/workflow_status.py` zero `from server` imports — milestone preserved.

## Phase 1 → Phase 2 gate

All hard gates checked. Soft gates documented as tracked debt. Frozen items verified untouched. Then and only then is Phase 2 unblocked.
