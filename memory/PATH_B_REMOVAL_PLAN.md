# Path B — Phase 4 Removal Plan (AP Mutation Routes)

**Target release:** Next release cycle after v2.5.25 (AP Path Consolidation Phases 2+3) has been in production for at least one full drain window.
**Owner:** Main agent (E1), reviewed by user before merge.
**Principle (user directive, 2026-04-22):** Temporary deprecation bridges must not become permanent drift. Unless a specific blocker is documented, Path B AP mutation routes MUST be removed next cycle.

---

## 1. What gets deleted

### 1a. Backend route registrations (`/app/backend/routers/workflows.py`)
Remove the six `app.add_api_route(...)` calls inside `register_server_routes(app)` that bind the `_deprecate(...)`-wrapped AP mutation handlers:

| Deprecated URL (to delete)                                   | Canonical replacement                                                   |
|--------------------------------------------------------------|--------------------------------------------------------------------------|
| `POST /api/workflows/ap_invoice/{doc_id}/set-vendor`            | `POST /api/ap-review/documents/{doc_id}/set-vendor`            |
| `POST /api/workflows/ap_invoice/{doc_id}/update-fields`         | `POST /api/ap-review/documents/{doc_id}/update-fields`         |
| `POST /api/workflows/ap_invoice/{doc_id}/override-bc-validation`| `POST /api/ap-review/documents/{doc_id}/override-bc-validation`|
| `POST /api/workflows/ap_invoice/{doc_id}/start-approval`        | `POST /api/ap-review/documents/{doc_id}/start-approval`        |
| `POST /api/workflows/ap_invoice/{doc_id}/approve`               | `POST /api/ap-review/documents/{doc_id}/approve`               |
| `POST /api/workflows/ap_invoice/{doc_id}/reject`                | `POST /api/ap-review/documents/{doc_id}/reject`                |

Keep the rest of `register_server_routes(app)` intact — generic mutation routes (`/api/workflows/{doc_id}/mark-ready-for-review`, `.../approve`, etc.) are NOT part of this removal.

### 1b. Backend wrapper + observability (only if zero hits persist)
Once the six deprecated routes are gone AND the global `deprecation_hits` collection has been empty for the AP mutation templates for the drain window:
- Remove `_deprecate(...)`, `_record_deprecation_hit(...)`, and their imports (`functools.wraps`, `inspect`) from `routers/workflows.py` — but ONLY if no other router is using them. (None are today.)
- Leave the `deprecation_hits` collection itself in place — cheap, useful for future deprecations.
- Leave `GET /api/admin/deprecation-metrics` in place — generic, reusable.

### 1c. Backend dead orphans in `server.py`
Delete the three orphan functions left behind when mutation handlers were extracted to `services/workflow_handlers.py`:

| File / location (as of 2026-04-22)            | Function                          |
|-----------------------------------------------|-----------------------------------|
| `server.py` L6590–6644 (55 lines)             | `async def start_approval_generic(...)` |
| `server.py` L6648–6702 (55 lines)             | `async def approve_generic(...)`        |
| `server.py` L6706–6760 (55 lines)             | `async def reject_generic(...)`         |

Verification that these are safe to delete:
- No `@app.*` decorator on any of them (confirmed 2026-04-22).
- No import / reference anywhere else in the repo (confirmed via `grep -rn "start_approval_generic\|approve_generic\|reject_generic" /app/backend /app/frontend`).
- The live versions are in `services/workflow_handlers.py` and registered via `routers/workflows.py::register_server_routes`.

### 1d. Frontend dead helpers (`/app/frontend/src/lib/api.js`)
Audit: if none of `getWorkflowStatusCounts / getVendorPendingQueue / getBcValidationPendingQueue / getBcValidationFailedQueue / getDataCorrectionPendingQueue / getReadyForApprovalQueue / getWorkflowMetrics / exportDocument / getStatusCountsByType / getMetricsByType` has gained a consumer by then, delete the unused exports. Otherwise leave them.

Query helpers calling `/workflows/ap_invoice/*` stay — they are read-only, not drift-prone, and `WorkflowQueue.js` may add consumers.

### 1e. Consolidation memo + PRD cleanup
- Mark `/app/memory/AP_PATH_CONSOLIDATION.md` Phase 4 `✅ done`, date it.
- PRD entry for v2.5.25 gets a trailing "Path B removed in vN.N" stanza.

---

## 2. Gating criterion (hard, measured)

Removal is **only** safe when BOTH are true:

### 2a. Zero Path B hits for 7 consecutive days

**One-curl gate check** (v2.5.27+ returns the verdict directly in the response):
```bash
# From /opt/gpi-hub on the remote VM
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<admin>","password":"<pw>"}' | jq -r .token)

curl -s "http://localhost:8080/api/admin/deprecation-metrics" \
  -H "Authorization: Bearer $TOKEN" | jq '.phase_4_gate'
```

Expected when safe to ship Phase 4:
```json
{
  "gate_met": true,
  "total_hits_in_window": 0,
  "offending_callers": [],
  "hits_by_template": {
    "/api/workflows/ap_invoice/{doc_id}/set-vendor": 0,
    "/api/workflows/ap_invoice/{doc_id}/update-fields": 0,
    ...
  }
}
```

If `gate_met: false`, inspect `phase_4_gate.offending_callers[]` — each entry carries `last_client_host` and `last_user_agent` so the offender can be pinpointed. Migrate them to Path A, then restart the 7-day drain clock.

**Detailed route-level view** (optional, for audit / trend analysis):
```bash
curl -s "http://localhost:8080/api/admin/deprecation-metrics?days=7" \
  -H "Authorization: Bearer $TOKEN" | jq '.route_totals[] |
    select(.deprecated_path | startswith("/api/workflows/ap_invoice/"))'
```

Expected: **empty** (no AP mutation Path B row whose `total_hits > 0` in the window).

### 2b. Regression suite green
Re-run:
- `tests/test_ap_path_consolidation.py` — currently 36 cases; after Phase 4, expect:
  - `TestCanonicalPathARegistered` → still 6/6 (Path A unchanged)
  - `TestDeprecatedPathBFlagged::test_path_b_still_present` → FLIPS to `test_path_b_removed` asserting the routes are absent from `/openapi.json`
  - `TestDeprecatedPathBFlagged::test_path_b_marked_deprecated` → REMOVED
  - `TestPathAAuthEnforcement` → still 12/12
  - `TestPathBDeprecationHeaders` → REMOVED
- `tests/test_partial_post_detection.py` — 4/4 must still pass
- `tests/test_deprecation_metrics.py` — gate_met projection tests must still pass
- `tests/test_auth_enforcement.py`, `test_bc_post_claim.py`, `test_bc_line_routing.py`, `test_pi_preflight_reconcile.py`, `test_vendor_profile_fallbacks.py` — 75/75 must still pass

New smoke:
- `curl -sI -X POST http://localhost:8080/api/workflows/ap_invoice/any/set-vendor` → HTTP 404 (route gone, not 405)

### 2c. Observability limitation — disclosed truthfully

Per user directive (2026-04-22): **`deprecation_hits` only captures Path B requests that reach the `_deprecate()` wrapper.** Specifically:

| Scenario                                         | Recorded in deprecation_hits? | Shows in phase_4_gate? |
|--------------------------------------------------|-------------------------------|------------------------|
| Valid body, valid auth, valid doc_id             | **Yes** (status 200 or 201)   | Yes                    |
| Valid body, valid auth, bad doc_id               | **Yes** (status 404)          | Yes                    |
| Valid body, missing/invalid JWT                  | **Yes** (status 401)          | Yes                    |
| **Malformed body (Pydantic 422)**                | **NO — pre-wrapper failure**  | **NO**                 |
| Wrong HTTP method (POST-only route hit with GET) | **NO — pre-wrapper failure**  | **NO**                 |

Why: FastAPI/Pydantic runs body validation and method matching BEFORE the wrapper executes. That's a framework-level ordering we accept, not a bug.

Practical impact: narrow. Any real caller (BC extension, AL script, internal frontend, curl-based cron) sends well-formed bodies and matching methods. A 422 on a deprecated URL typically indicates a human ad-hoc test, not production traffic.

If a caller turns out to be emitting 422s repeatedly against Path B (we'd see them in NGINX / ingress logs but not in `deprecation_hits`), escalate before Phase 4 removal and migrate them manually. The gate is still meaningful; it is not a complete census.

Future hardening (not in scope for v2.5.27): move recording into a starlette middleware keyed on the matched route template, BEFORE body parsing. That would catch 422s. Gate is being kept strict for now — per user directive "finish drain + Phase 4 first, then decide".

---

## 3. Documented blockers (exit conditions)

If any of these is true, **do not** remove; document the blocker in this file and defer one more release:

1. An external BC extension or integration script is still calling Path B (spotted via non-empty `phase_4_gate.offending_callers` OR via NGINX/ingress 422 logs — see §2c). Action: notify owner, migrate them to Path A, restart 7-day clock.
2. A scheduled batch job inside the repo calls Path B from a code path that isn't exercised by routine traffic. Action: `grep -rn "/api/workflows/ap_invoice/" /app/backend /app/frontend` — should return only the registration file; if it returns a caller, migrate it first.
3. A test file (other than `test_ap_path_consolidation.py`) hits Path B URLs directly. Action: rewrite it against Path A.

---

## 4. Rollback

The change is a pure subtraction from `register_server_routes(app)`. To roll back:
1. Re-add the six `_deprecate(...)` `add_api_route` calls from git history (one commit).
2. Restart backend via supervisor on preview OR `docker compose up -d` on the VM.

Data impact: none. Both paths write the same `hub_documents` / `vendor_invoice_profiles` shape. The `deprecation_hits` counter would resume; no migration needed.

---

## 5. Sequencing

```
T+0 days    v2.5.25 ships — Path A canonical + Path B deprecated
            v2.5.26 ships — observability + partial-post integrity
            v2.5.27 ships — phase_4_gate projection + 422 disclosure
T+1..7 days drain window — GET /api/admin/deprecation-metrics | jq .phase_4_gate
T+7 days    checkpoint: gate_met == true?
            YES → proceed to Phase 4 branch
            NO  → investigate offending_callers, migrate, reset clock
T+8 days    Phase 4 PR:
              - Delete the 6 _deprecate() registrations
              - Delete start_approval_generic / approve_generic / reject_generic orphans
              - Flip TestDeprecatedPathBFlagged to TestPathBRemoved
              - Update AP_PATH_CONSOLIDATION.md Phase 4 status
T+8..9 days Ship Phase 4, verify no 404 spike (no new caller broken)
T+14 days   If clean, delete the _deprecate/_record_deprecation_hit helpers
            (leave db.deprecation_hits collection + admin endpoint in place —
            generic, reusable for any future deprecation)
```

---

## 6. Open questions for the user (before Phase 4 merge)

- Any external system (Power Automate flow, BC AL extension, custom script) that still calls `/api/workflows/ap_invoice/*`? If so, give us its `User-Agent` / host so we can cross-check against `phase_4_gate.offending_callers[].last_user_agent`.
- OK with permanent keep of `/api/admin/deprecation-metrics` and the `deprecation_hits` collection? (Recommended: yes — generic, cheap, reusable.)
- Want NGINX/ingress 422 log sampling added before Phase 4 to close the disclosed blind spot in §2c? (Recommended: no, per your directive "finish drain + Phase 4 first, then decide".)

