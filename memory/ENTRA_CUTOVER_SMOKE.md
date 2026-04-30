# Entra ID Cutover Smoke Runbook (P1.K post-merge validation)

**Status:** authoritative VM smoke checklist. **No new implementation work** is allowed before this runbook completes successfully.

**Audience:** the VM operator running `cd /opt/gpi-hub && ...` on the production Azure VM.

**Scope fence:** validates the already-landed P1.H + P1.K implementation only. No code is touched. No P1.C / P1.J / P1.A / P1.F / scope-typo cleanup / `/api/auth/whoami` work happens during this window.

**Migration posture during smoke:** Entra is enabled for the smoke test, **legacy auth stays enabled** as a safety net. If Entra fails for any reason, every existing user can still log in via the legacy email/password form on the same page.

---

## 0. Pre-flight (one-time, before first cutover attempt)

### 0a. Entra app registration sanity
In the Entra admin portal, on app registration `6ac62e44-8968-4ad9-b781-434507a5c83a`:

| Section | Required setting | Why |
|---|---|---|
| Authentication → Single-page application → Redirect URIs | Add the **exact** VM frontend origin (e.g. `https://hub.gamerpackaging.com`, plus any other origins you serve). Do **not** append a path. | MSAL v5 redirects back to `window.location.origin`; mismatch → `AADSTS50011`. |
| Expose an API → Application ID URI | `api://6ac62e44-8968-4ad9-b781-434507a5c83a` | Backend audience must match exactly. |
| Expose an API → Scopes | `access_as_users` exists, "Admins and users" consent | Frontend requests this scope; backend validates `aud=api://<id>/access_as_users`. |
| App roles | `admin`, `approver`, `reviewer`, `viewer`, `service` defined | Consumed by P1.C; not yet enforced, but should be present so claims surface in tokens. |
| Enterprise applications → Users and groups | At least 1 test user assigned to `admin` role | Needed to exercise the `roles` claim during smoke. |

### 0b. Capture the legacy fallback creds
You already have these from the migration window. Confirm `hub-admin@gamerpackaging.com` + the rotated password still works **before** flipping the Entra flag — that's your rollback parachute.

### 0c. Save current VM env values
Take a snapshot of the VM's current `.env` (or compose env) — `ENTRA_AUTH_ENABLED`, `REACT_APP_ENTRA_AUTH_ENABLED`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_API_AUDIENCE`, `LEGACY_AUTH_ENABLED`. You'll need the snapshot for rollback in §4.

---

## 1. Pull, set flags, rebuild, bring up

On the VM:

```bash
cd /opt/gpi-hub
git pull
```

Edit the VM's environment (compose env or wherever it lives) so the **runtime** values are:

```
# Backend
ENTRA_TENANT_ID=contract-intel-9
ENTRA_CLIENT_ID=contract-intel-9
ENTRA_API_AUDIENCE=api://6ac62e44-8968-4ad9-b781-434507a5c83a/access_as_users
ENTRA_AUTHORITY=https://login.microsoftonline.com/c7b2de14-71d9-4c49-a0b9-2bec103a6fdc/v2.0
ENTRA_JWKS_URL=https://login.microsoftonline.com/c7b2de14-71d9-4c49-a0b9-2bec103a6fdc/discovery/v2.0/keys
ENTRA_AUTH_ENABLED=true        # <-- flipped ON for smoke
LEGACY_AUTH_ENABLED=true       # <-- kept ON as the safety net

# Frontend (must be present BEFORE `docker compose build` because CRA bakes them at build time)
REACT_APP_ENTRA_AUTH_ENABLED=true
REACT_APP_ENTRA_TENANT_ID=contract-intel-9
REACT_APP_ENTRA_CLIENT_ID=contract-intel-9
REACT_APP_ENTRA_API_SCOPE=api://6ac62e44-8968-4ad9-b781-434507a5c83a/access_as_users
```

Then:

```bash
docker compose build --no-cache
docker compose up -d
docker compose logs -f --tail=100 backend frontend
```

Wait for both services to report ready. Backend should print no warnings about Entra config; frontend should compile cleanly.

---

## 2. Smoke checklist (run in order; abort on first FAIL)

| # | Step | Command / action | PASS criterion | On FAIL |
|---|---|---|---|---|
| 1 | Backend health | `curl -s http://localhost:8080/api/dashboard/inbox-stats -o /dev/null -w "%{http_code}\n"` | `401` (auth required, dep is wired) — **not** 500/502 | §4 rollback |
| 2 | JWKS reachable from VM | `curl -sI "$ENTRA_JWKS_URL" \| head -1` | `HTTP/2 200` | check VM egress / corporate proxy |
| 3 | OpenAPI path count | `curl -s http://localhost:8080/openapi.json \| python3 -c "import sys,json;print(len(json.load(sys.stdin)['paths']))"` | `858` (unchanged from pre-cutover) | check container build picked up latest code |
| 4 | Frontend serves `/login` | `curl -sI https://<vm-host>/login \| head -1` | `200` | check frontend container logs |
| 5 | Login page renders both surfaces (browser, hard refresh, **incognito**) | Visit `/login` | "Sign in with Microsoft" button visible **above** the legacy email/password form. Divider says "or use legacy credentials". | check `REACT_APP_ENTRA_AUTH_ENABLED=true` was set **before** the build |
| 6 | Microsoft sign-in succeeds | Click "Sign in with Microsoft" → consent if prompted → land on `/` | Redirected to dashboard. Top-right shows your user. No console errors. | inspect popup error code (typically `AADSTS50011` redirect mismatch → fix §0a) |
| 7 | Token actually attached on API calls | DevTools → Network → reload `/` → click a request to `/api/dashboard/...` | Request header `Authorization: Bearer eyJ…` is present **and** the JWT decodes (jwt.io) to: `iss=https://login.microsoftonline.com/c7b2de14-…/v2.0`, `aud=api://6ac62e44-…/access_as_users`, `tid=c7b2de14-…`, `roles=["admin"]` (for the test user) | if `Bearer` is the legacy `gpi_token`-shaped opaque value, the Entra silent acquisition silently fell back — check console for MSAL error |
| 8 | Protected-route round-trip | While signed in, navigate to `/governance` → expect dashboard data | 200 response, dashboard renders | check backend logs for the actual claim that failed validation |
| 9 | Backend role claim surfaces | `curl -sH "Authorization: Bearer $TOKEN_FROM_DEVTOOLS" http://localhost:8080/api/auth/me` | 200 with `{"role":"admin","email":"<test-user>",...}` (hybrid facade returns Entra path) | if 401, decode token at jwt.io and compare each claim against §5 below |
| 10 | Logout clears MSAL **and** legacy state | Click logout → return to `/login` → DevTools Application → Storage | `sessionStorage` MSAL keys gone. `localStorage.gpi_token` and `localStorage.gpi_user` gone. | known low-severity; non-blocking |
| 11 | Legacy fallback still works during the smoke window | On `/login`, fill the legacy email/password form (do **not** click Microsoft) → Sign In | Lands on dashboard. Network: `/api/auth/me` returns `{"auth_source":"legacy"}` (or absent — backend tolerates both) | confirms `LEGACY_AUTH_ENABLED=true` is honored; no need to escalate |
| 12 | Rollback dry-run (do this with no users active) | Flip `ENTRA_AUTH_ENABLED=false` and `REACT_APP_ENTRA_AUTH_ENABLED=false`, rebuild frontend, restart backend (no rebuild needed) | Login page reverts to legacy-only form. Existing legacy sessions continue to work. No 500s. | if anything 500s, do not declare cutover ready |

If steps 1–11 all PASS, mark **cutover smoke complete** and re-flip flags to whatever rollout posture you want for the actual rollout (gradual or full).

---

## 3. What "PASS for the whole runbook" means

- All 12 steps PASS in a single contiguous run.
- No backend 500s observed in `docker compose logs backend` during the smoke window.
- The legacy login form remained clickable throughout (step 11 proves it).
- Step 12 dry-run proves rollback is one env flip + one rebuild.

If all of the above hold → **cutover smoke complete; system is ready for P1.C**.

---

## 4. Rollback posture (memorize this BEFORE flipping the flag)

If anything in §2 fails and you cannot resolve it inside ~15 minutes:

```bash
# 1) Flip both flags back to the dormant default
sed -i 's/^ENTRA_AUTH_ENABLED=true/ENTRA_AUTH_ENABLED=false/' <env-file>
sed -i 's/^REACT_APP_ENTRA_AUTH_ENABLED=true/REACT_APP_ENTRA_AUTH_ENABLED=false/' <env-file>

# 2) Rebuild frontend (CRA bakes envs at build time)
docker compose build frontend
docker compose up -d

# 3) Verify
curl -s http://localhost:8080/openapi.json | python3 -c "import sys,json;print(len(json.load(sys.stdin)['paths']))"  # must still print 858
```

After rollback, the system is byte-identical to pre-cutover. Existing user sessions on legacy bcrypt JWTs continue to work because `LEGACY_AUTH_ENABLED=true` was never flipped.

**Do not** delete the `services/entra_auth.py` module or the frontend MSAL files on rollback — leave them dormant. The next cutover attempt should not require a code change, only an env flip + rebuild.

---

## 5. Token-shape reference (for §2 step 7 / step 9 debugging)

Decode the captured Bearer token at jwt.io. The header must be:

```json
{"alg": "RS256", "typ": "JWT", "kid": "<some-guid>", ...}
```

The payload must satisfy **all** of:

| Claim | Required value |
|---|---|
| `iss` | `https://login.microsoftonline.com/c7b2de14-71d9-4c49-a0b9-2bec103a6fdc/v2.0` |
| `aud` | `api://6ac62e44-8968-4ad9-b781-434507a5c83a/access_as_users` |
| `tid` | `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc` |
| `oid` | a stable GUID (your test user's object ID) |
| `roles` | `["admin"]` (for the assigned test user) |
| `scp` | `access_as_users` (present on user-delegated tokens; absent on app-only) |
| `exp` | future-dated; default lifetime ~1 hour |

If any of these are wrong, that is the failing claim and `services/entra_auth.py::validate_entra_token` will reject the token at exactly that step.

---

## 6. Reporting back template

When the smoke completes (pass or fail), report:

```
Cutover smoke result: PASS / PARTIAL / FAIL

Flags / env posture used:
- ENTRA_AUTH_ENABLED=...
- LEGACY_AUTH_ENABLED=...
- REACT_APP_ENTRA_AUTH_ENABLED=...

Step results:
1. Backend health                  : PASS / FAIL — <note>
2. JWKS reachable from VM          : PASS / FAIL — <note>
3. OpenAPI path count              : PASS / FAIL — <note>
4. Frontend /login serves          : PASS / FAIL — <note>
5. Both surfaces render            : PASS / FAIL — <note>
6. Microsoft sign-in succeeds      : PASS / FAIL — <note>
7. Bearer token shape correct      : PASS / FAIL — <note>
8. Protected-route round-trip      : PASS / FAIL — <note>
9. /api/auth/me with Entra token   : PASS / FAIL — <note>
10. Logout clears both stores      : PASS / FAIL — <note>
11. Legacy fallback still works    : PASS / FAIL — <note>
12. Rollback dry-run               : PASS / FAIL — <note>

Overall: ready to proceed to P1.C? YES / NO
Blockers / follow-ups: <list>
```

---

## 7. Recommended next step on PASS

If the runbook completes PASS, the recommended next implementation step is:

- **P1.C — RBAC enforcement on the 30 already-classified endpoints** (the four routers closed in P0.1).

After P1.C lands and is itself smoked, then in this order:

- **P1.J** — Actor context propagation
- **P1.A** — `governance_audit_log` collection + read endpoint
- **P1.F** — Slim preflight + post-deploy smoke probe

Until the runbook above PASSes, **no new implementation work begins**.
