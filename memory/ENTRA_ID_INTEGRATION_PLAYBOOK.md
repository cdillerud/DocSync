# Microsoft Entra ID Integration Playbook — GPI Hub (P0.7 deliverable)

**Status:** signed-off integration plan from `integration_playbook_expert_v2`. Hard gate for P1.H / P1.K / P1.C / P1.J auth implementation. **No code begins until the user has provided the credentials enumerated in §7 and this document is reviewed.**

**Architecture:** OAuth 2.0 Authorization Code Flow with PKCE on the SPA, asymmetric JWT validation on the backend with JWKS caching, role-based access control via Entra app-role claims. Single-tenant, no client secret on the SPA.

---

## 1. Library and version pins (Feb 2026 baseline)

**Backend (Python):**
- `PyJWT==2.12.1` — JWT decode/verify with RS256 + JWKS; replaces deprecated `python-jose`.
- `cryptography>=41.0.0` — RSA primitives.
- `requests` (already present) for JWKS fetch.

**Frontend (React CRA):**
- `@azure/msal-browser@^4.4.0` — core MSAL.
- `@azure/msal-react@^3.1.0` — React bindings (`MsalProvider`, hooks). **Amended 2026-04-23 from v2.0.0 to v3.1.0+ for React 19 compatibility (P1.H signed correction).**

Install via `pip install … && pip freeze` and `yarn add` per Emergent platform protocol.

## 2. JWKS handling
- Fetch from `{issuer}/.well-known/openid-configuration` → `jwks_uri`.
- Cache TTL: **10–15 minutes**. In-process for single-instance; shared (Redis) for multi-instance.
- Match incoming token's header `kid` against cached keys; refresh on miss after TTL.
- During key rotation Entra publishes new + old keys simultaneously — search-by-`kid` handles transition automatically.

## 3. Entra app-registration steps (user action required)

| Step | Where | Action |
|---|---|---|
| 1 | Entra portal → App registrations → New registration | Create "GPI Hub API". Single-tenant. Copy **Tenant ID** + **Client ID**. |
| 2 | App → Expose an API | Set Application ID URI = `api://{client-id}`. Add scope `access_as_user` (admins+users consent). Record full URI: `api://{client-id}/access_as_user`. |
| 3 | App → Manifest | Populate `appRoles[]` with role definitions. Each role needs unique GUID `id`. Recommended initial set: `admin`, `approver`, `reviewer`, `viewer`. |
| 4 | App → Authentication → Add platform → SPA | Add redirect URIs: `http://localhost:3000`, deployed frontend URL. **Do NOT** add backend URL. |
| 5 | App → API permissions | Add permission → My APIs → select self → check `access_as_user` → Grant admin consent. |
| 6 | Enterprise applications → GPI Hub API → Users and groups | Assign roles to test user(s). |

## 4. Token claim shape backend will rely on
- `oid` — stable user GUID (primary key for actor identity).
- `preferred_username` — display only; not unique.
- `roles` — array of strings (role `value` from manifest, e.g. `["admin"]`).
- `aud` — must equal `ENTRA_API_AUDIENCE` (full `api://…` URI).
- `iss` — must equal `https://login.microsoftonline.com/{tenant-id}/v2.0`.
- `exp`, `iat` — standard.
- `tid` — must equal `ENTRA_TENANT_ID`.
- v2.0 endpoint only.

## 5. Backend validation contract
- FastAPI dependency `validate_token(credentials)` extracts Bearer, looks up signing key by `kid`, verifies signature with RS256 + audience + issuer + expiry. Use `leeway=30` for clock skew.
- Returns `Actor` dataclass: `oid`, `preferred_username`, `roles`, `tenant_id`, `correlation_id`.
- `require_role(*roles)` factory builds a dependency that checks `roles` claim ⊇ required-set; 403 on mismatch.

## 6. Frontend wiring contract
- `MsalProvider` at app root. Cache: `sessionStorage` (security over UX continuity per playbook recommendation; persistent sessions across tabs requires architectural change).
- `loginPopup` (preferred for SPA UX) with `scopes: [REACT_APP_ENTRA_API_SCOPE]`.
- Silent acquisition first, interactive fallback on `InteractionRequiredAuthError`.
- Axios interceptor or fetch wrapper attaches `Authorization: Bearer …` to every request to `REACT_APP_BACKEND_URL`.
- Route guard `<RequireAuth>` redirects unauthenticated users.

## 7. **Required credentials to be provided by user before P1.H code starts**

| Credential | Where obtained in Entra portal | Goes into |
|---|---|---|
| **Tenant ID** | App registration Overview → Directory (Tenant) ID | `ENTRA_TENANT_ID` (backend) + `REACT_APP_ENTRA_TENANT_ID` (frontend) |
| **Client (Application) ID** | App registration Overview → Application (Client) ID | `ENTRA_CLIENT_ID` (backend) + `REACT_APP_ENTRA_CLIENT_ID` (frontend) |
| **API Scope URI** | Expose an API page → full scope URI | `ENTRA_API_AUDIENCE` (backend) + `REACT_APP_ENTRA_API_SCOPE` (frontend) |
| (No client secret) | — | PKCE-only on SPA per playbook |

**The user must complete §3 steps 1–6 in the Entra portal and provide these three identifiers before P1.H implementation begins.**

## 8. Common pitfalls (countermeasures encoded in P1.H tests)
1. Audience-string mismatch (`api://…` vs raw GUID) — P1.H probe pins exact string match.
2. Clock skew — 30s leeway in decoder.
3. JWKS cache stale during rotation — TTL ≤ 15 min; probe simulates rotation.
4. Bearer header malformed — interceptor enforces format; backend `HTTPBearer` rejects malformed.
5. `localStorage` token leakage — `sessionStorage` mandated.
6. Issuer validation skipped — explicit `issuer=` in decode call.
7. Roles claim missing — manifest populated; test inspects token at jwt.io.
8. CORS on backend (not Entra) — existing FastAPI CORS unchanged; verify no regression.
9. Nonce on access tokens — do NOT validate nonce on access tokens (ID-token-only concept).

## 9. Test recipe
- **R1:** Service-principal client-credentials flow to mint a test token in staging tenant (via `msal.ConfidentialClientApplication`); curl backend with token; assert 200/403.
- **R2:** Interactive end-to-end with React frontend running locally against staging tenant; inspect network tab for Authorization header.
- **R3:** Decode token at jwt.io to verify all claim shapes.
- **R4:** Local mock-token unit tests with self-signed RSA keypair (no network) for backend validation logic.

## 10. Out-of-scope explicit fences
- MS Graph / SharePoint / mail-poller integrations — separate app-only credentials, untouched by P1.H.
- Multi-tenant federation.
- App-managed user accounts; sign-up flows; password reset.
- Mobile-app flows.
- Tracing / OpenTelemetry context propagation (Phase 2).
- Refresh-token rotation customization beyond MSAL defaults.
