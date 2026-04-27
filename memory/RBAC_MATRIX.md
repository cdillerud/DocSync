# P0.1 — Proposed RBAC Matrix (assumption-to-validate during review)

**Status:** STARTER PROPOSAL pending user refinement against the literal governance brief. Anchored on the 4-role taxonomy declared in `ENTRA_ID_INTEGRATION_PLAYBOOK.md` §3 step 3.

**Methodology:** classify the 407 mutating endpoints by router-family (router-file) into role buckets. Per-endpoint refinement happens during P0.1 review. Acceptance criterion: each of the 407 endpoints has a final role assigned before P1.C implementation begins.

## Role taxonomy (initial)

| Role | Intent | Example surfaces |
|---|---|---|
| **`admin`** | Full system control: settings, deprecation, feature flags, credentials, user assignment | `admin.py`, `admin_eod.py`, `dev_tools.py`, `migration_routes.py`, `mailbox_sources.py`, `posting_patterns.py` (curation), `bakeoff.py` |
| **`approver`** | Mutate workflow state: approve/reject documents, override gates, post to BC | `auto_approve.py`, `auto_clear.py`, `auto_clear_reprocess.py`, `ap_review.py` (approve), `ar_release.py` (override), `bc_integration.py`, `governance.py` (mutate) |
| **`reviewer`** | Mutate document content: corrections, label fixes, alias edits, reclassification | `documents.py`, `aliases.py`, `label_corrections.py`, `dedup.py`, `reprocess_comparison.py`, `intake_learning.py`, `cp_item_registry.py`, `consigned_item_registry.py`, `inventory_items.py`, `inventory_xls.py`, `freight_routing.py` |
| **`viewer`** | No mutating access. Read-only consumer of dashboards. | (Not on any mutating route — all 473 GET routes default to `viewer`.) |

## Proposed router-family → role mapping (407 mutating endpoints)

| Router | Mutating count | Proposed role | Rationale |
|---|---|---|---|
| `inventory_ledger.py` | 42 | **reviewer** + selected `admin` | Ledger mutations; sensitive but reviewer-domain |
| `posting_patterns.py` | 27 | **admin** | Pattern curation = system tuning |
| `admin.py` | 22 | **admin** | Self-evident |
| `gpi_integration.py` | 21 | **admin** | BC integration tuning |
| `bakeoff.py` | 18 | **admin** | A/B test config |
| `document_intelligence.py` | 17 | **reviewer** | Doc intel corrections |
| `documents.py` | 16 | **reviewer** | Document mutations |
| `pilot.py` | 16 | **admin** | Pilot config |
| `inside_sales_pilot.py` | 14 | **reviewer** + selected `approver` | Pilot data + approval gates |
| `sharepoint_routing.py` | 14 | **admin** | Routing config |
| `ap_review.py` | 12 | **approver** | AP approval surface |
| `readiness.py` | 11 | **approver** | Readiness gate overrides |
| `sales_dashboard.py` | 9 | **resolved P0.1 ↓** | See per-endpoint table below |
| `intake_learning.py` | 8 | **admin** | Learning config |
| `inventory_xls.py` | 8 | **reviewer** | XLS uploads |
| `automation_intelligence.py` | TBD | **admin** | Automation config |
| `automation_rules.py` | TBD | **admin** | Rules config |
| `auth.py` | TBD | **resolved P0.1 ↓** | See per-endpoint table below |
| `auto_approve.py` | TBD | **approver** | Self-evident |
| `auto_clear.py` | TBD | **approver** | Self-evident |
| `auto_clear_reprocess.py` | TBD | **approver** | Self-evident |
| `ap_advisory.py` | TBD | **reviewer** | Advisory mutations |
| `ap_validation.py` | TBD | **approver** | AP validation overrides |
| `aliases.py` | TBD | **reviewer** | Alias edits |
| `alerts.py` | TBD | **admin** | Alert config |
| `ar_release.py` | TBD | **approver** | AR release decisions |
| `bc_integration.py` | TBD | **approver** | BC posting |
| `bc_sandbox.py` | TBD | **admin** | Sandbox config |
| `cache.py` | TBD | **admin** | Cache invalidation |
| `cp_item_registry.py` | TBD | **reviewer** | Registry mutations |
| `consigned_item_registry.py` | TBD | **reviewer** | Registry mutations |
| `dashboard.py` | TBD | **resolved P0.1 ↓** | See per-endpoint table below |
| `dedup.py` | TBD | **reviewer** | |
| `dev_tools.py` | TBD | **admin** | Dev-only |
| `email_polling.py` | TBD | **admin** | Polling control |
| `events.py` | TBD | **admin** | Event mutations |
| `explain.py` | TBD | (read-only? confirm) | |
| `feedback_health.py` | TBD | **reviewer** | |
| `file_import.py` | TBD | **reviewer** | |
| `file_integrity.py` | TBD | **admin** | |
| `freight_routing.py` | TBD | **reviewer** | |
| `governance.py` | TBD | **resolved P0.1 ↓** | See per-endpoint table below |
| `inventory_items.py` | TBD | **reviewer** | |
| `knowledge_seed.py` | TBD | **admin** | |
| `label_corrections.py` | TBD | **reviewer** | |
| `layout_fingerprints.py` | TBD | **reviewer** | |
| `learning_core.py` | TBD | **admin** | |
| `mailbox_sources.py` | TBD | **admin** | |
| `metrics.py` | TBD | (read-only? confirm) | |
| `migration_routes.py` | TBD | **admin** | |
| `po_resolution.py` | TBD | **reviewer** | |
| `queue_constants.py` | TBD | **admin** | |
| `reference_intelligence.py` | TBD | **reviewer** | |
| `reprocess_comparison.py` | TBD | **reviewer** | |
| `salesperson_dashboard.py` | TBD | **reviewer** | |
| `sales_pipeline_demo.py` | TBD | **admin** (demo-only) | |
| `settings.py` | TBD | **admin** | |
| `sharepoint_routing.py` | (already counted above) | **admin** | |

> "TBD" = endpoint count not yet enumerated in P0.1 starter. Resolved during P0.1 review.

## Open questions for review

1. **Two-tier files** (`auth.py`, `dashboard.py`, `governance.py`, `sales_dashboard.py`): some endpoints are public/viewer, some are admin/reviewer. Per-endpoint matrix needed.
2. **`documents.py:16` mutating** likely splits across reviewer-grade edits and approver-grade (e.g. force-clear, force-route) actions.
3. **Sensitive `admin` actions** (`POST /api/admin/deprecation-metrics/clear`, `migration_routes.py`, `dev_tools.py`) should additionally require `MFA-elevated` — flag for Phase 2 if brief mandates it.
4. **Service-account role** (for Teams webhook in P1.E once unfrozen, email-poller, BC-poll): naming + scope to be decided during P0.1 review.

## Deliverable closure for P0.1

When this matrix is finalized:
- Every one of the 407 mutating routes has a final role assignment.
- Every one of the 473 GET routes is confirmed-or-explicitly-overridden as `viewer`.
- `RBAC_AUDIT.md` (P0.2) flips from "0/407 enforced" to "0/407 enforced; gap target list = all 407 → 0 gap, blocker for P1.C".

---

# P0.1 Refinement Pass — 4 Two-Tier Router Files (signed 2026-04-23)

**Scope fence:** This pass refines per-endpoint role assignment for exactly four router files identified during P0.1 review as having mixed/two-tier semantics. No other router files are touched in this pass. No code is modified — this section is the documentation deliverable that closes P0.1 for these four files. P1.C will enforce these assignments at the dependency layer.

**Approved taxonomy in effect:**
- `admin` — full system control (settings, deprecation, feature flags, credentials, user assignment, destructive ops, automation control)
- `approver` — mutate workflow state (approve/reject documents, override gates, post to BC)
- `reviewer` — mutate document content (corrections, label fixes, alias edits, reclassification, manual triage)
- `viewer` — read-only consumer of dashboards and queue listings
- `service` — non-interactive background actor (email-poller, BC poller, scheduler, webhook receivers). **Scope: system-internal callers only.** Never broadened to UI-facing permissions. Authenticated via service-principal token (Entra app-only, not user-delegated). MFA-elevated tier deferred to Phase 2.

**Special pseudo-bucket:**
- `public` — unauthenticated. Used only for the auth bootstrap surface (login). Never granted to any other route.
- `authenticated` — token validity required, but role does not gate access. Used for self-introspection (`/auth/me`, `/auth/logout`). Resolves to "any of {admin, approver, reviewer, viewer, service}".

---

## File 1 — `routers/auth.py`

**Summary.** Authentication bootstrap surface. Three endpoints split across three buckets: one `public` (login — must be reachable without a token), two `authenticated` (logout + self-introspection — token required but no role gate). No `admin`/`approver`/`reviewer` actions live here in the current implementation. User-management endpoints (create user, assign role, rotate password) are **not in this file today** — when added during Phase 1, they land here with `admin` enforcement and will require their own signed declaration.

| method | path | required role | rationale |
|---|---|---|---|
| POST | `/api/auth/login` | **public** | Token bootstrap. Cannot require a token to acquire one. Rate-limit + brute-force protection is a separate Phase 1 concern, not RBAC. |
| POST | `/api/auth/logout` | **authenticated** | Clears the `access_token` cookie. Requires a valid token (per the `Depends(get_current_user)` already in the handler). No role gate — every authenticated principal can log itself out, including `service`. |
| GET  | `/api/auth/me` | **authenticated** | Self-introspection. Returns the caller's own claims. Requires a valid token. No role gate — every authenticated principal can read its own identity. |

**Service-role applicability.** `service` principals **may** call `/auth/me` (useful for token-validity probes) but **never** `/auth/login` (they authenticate via app-only client-credentials flow against Entra, not via this endpoint). This file's `public` bucket is the **only** unauthenticated surface in the entire backend; any future addition to this bucket requires a signed declaration.

---

## File 2 — `routers/dashboard.py`

**Summary.** Read-only dashboard surface. **All 11 endpoints are GET.** Every endpoint is a viewer-grade dashboard query (counts, time-series, trends, metrics). No mutations live in this file. The previous matrix entry that listed `dashboard.py` as "mostly read; mutations: reviewer" is corrected here — there are zero mutating routes in this file as of 2026-04-23.

| method | path | required role | rationale |
|---|---|---|---|
| GET | `/api/dashboard/daily-ingestion` | **viewer** | Time-series ingestion counts. |
| GET | `/api/dashboard/stats` | **viewer** | Aggregate document stats. |
| GET | `/api/dashboard/workflow-intelligence` | **viewer** | Workflow-level intelligence summary. |
| GET | `/api/dashboard/document-types` | **viewer** | Doc-type distribution. |
| GET | `/api/dashboard/document-types/export` | **viewer** | CSV export of doc-type distribution. Read-only export of already-viewable data. |
| GET | `/api/dashboard/routing-summary` | **viewer** | Routing summary. |
| GET | `/api/dashboard/email-stats` | **viewer** | Email-source stats. |
| GET | `/api/dashboard/inbox-stats` | **viewer** | Inbox stats strip data. |
| GET | `/api/dashboard/inbox-metrics` | **viewer** | Inbox metrics breakdown panel. |
| GET | `/api/dashboard/insights-trends` | **viewer** | Insights/trends chart data. |
| GET | `/api/dashboard/ap-metrics` | **viewer** | AP-pipeline metrics. |

**Service-role applicability.** Background actors do **not** call dashboard endpoints — they consume the underlying collections directly. `service` is **not** granted access to this file's routes; if a future scheduler needs aggregate data it queries Mongo directly.

---

## File 3 — `routers/governance.py`

**Summary.** Single read-only consolidated governance dashboard endpoint. Module docstring is explicit: *"READ-ONLY: Never changes profiles, thresholds, or workflow."* No mutations live in this file. The previous matrix entry "mixed: read=viewer, mutations=admin" is corrected — there are zero mutations in this file as of 2026-04-23. Mutating governance operations (suggestion approve/reject, profile edits) live in **other** routers (e.g. `routers/governance_audit.py` once introduced in P1.A, plus the `so_learning_*` and `ap_learning_*` mutation surfaces under their own routers) and will be classified separately.

| method | path | required role | rationale |
|---|---|---|---|
| GET | `/api/governance/dashboard` | **viewer** | Cross-pipeline metrics dashboard (SO + AP suggestions, drift, hotspots, system health). Read-only by contract. |

**Service-role applicability.** `service` is **not** granted access. Schedulers that compute drift/hotspots write directly into the underlying audit collections and never round-trip through this endpoint.

**Forward note for P1.A.** When the append-only `governance_audit_log` collection ships, its read endpoint will land in this router as a second `GET /api/governance/audit-log` route, also `viewer`. Append operations are server-side only (driven by RBAC-gated mutations elsewhere) and will not expose a public POST.

---

## File 4 — `routers/sales_dashboard.py`

**Summary.** Mixed read + mutation router for the Sales Order review surface. 14 endpoints split four ways: 6 read-only listings (`viewer`), 1 destructive bulk operation (`admin`), 1 workflow-state approval (`approver`), 4 reviewer-grade triage actions (`reviewer`), and 4 system-configuration operations (`admin`). The previous matrix entry "mutations=reviewer (9)" is refined here per-endpoint.

| method | path | required role | rationale |
|---|---|---|---|
| GET    | `/api/sales-dashboard/queue` | **viewer** | List sales review queue. |
| GET    | `/api/sales-dashboard/summary` | **viewer** | Queue summary counts. |
| DELETE | `/api/sales-dashboard/queue/clear` | **admin** | Destructive bulk clear of the entire queue. Reserved to admin; reviewers cannot wipe queue state. |
| GET    | `/api/sales-dashboard/reps` | **viewer** | List sales reps. |
| GET    | `/api/sales-dashboard/my-queue` | **viewer** | Per-rep queue view (caller-scoped). |
| GET    | `/api/sales-dashboard/triage-queue` | **viewer** | Triage queue listing. |
| POST   | `/api/sales-dashboard/queue/{doc_id}/approve` | **approver** | Approve a sales review document → flips workflow state to "approved" and gates BC SO creation. Workflow-state mutation = approver-grade. |
| POST   | `/api/sales-dashboard/queue/{doc_id}/flag` | **reviewer** | Flag a doc for attention with notes. Reviewer-grade triage; does not flip the document into a terminal state. |
| POST   | `/api/sales-dashboard/queue/{doc_id}/assign` | **reviewer** | Manually assign a rep to a document (triage action). Reviewer-grade routing; does not approve or finalize. |
| POST   | `/api/sales-dashboard/review/{doc_id}` | **approver** | Unified review action endpoint accepting `action ∈ {approve, flag}`. **Required role = approver**, the higher of the two underlying actions, because the endpoint accepts the approval branch. P1.C may further split this into two sub-actions if a tighter gate is desired; for now, single-role = approver to avoid privilege underflow on the approve path. |
| POST   | `/api/sales-dashboard/seed-review-data` | **admin** | Seed/test-data utility. Reserved to admin; never exposed to reviewer/approver. |
| POST   | `/api/sales-dashboard/run-auto-assign` | **admin** | Triggers the auto-assignment automation across the queue. System automation control = admin. |
| GET    | `/api/sales-dashboard/rep-overrides` | **viewer** | Read rep-override config. |
| POST   | `/api/sales-dashboard/rep-overrides` | **admin** | Create/update a customer→rep override. Configuration mutation = admin. |
| DELETE | `/api/sales-dashboard/rep-overrides/{customer_no}` | **admin** | Delete a rep override. Configuration mutation = admin. |

**Service-role applicability.** Background `service` callers do **not** invoke the per-doc approve/flag/assign endpoints (those are user actions). The `run-auto-assign` endpoint is admin-triggered today; if a scheduler is later granted permission to invoke it on a cadence, that scheduler authenticates as `service` and the route becomes **admin OR service**. Until that signed step lands, `service` is **not** granted any route in this file.

---

## P0.1 Refinement Pass — Closure Statement

**Files closed by this pass:** `routers/auth.py` (3 endpoints), `routers/dashboard.py` (11 endpoints), `routers/governance.py` (1 endpoint), `routers/sales_dashboard.py` (15 endpoints). **30 endpoints total.**

**Endpoint count by required role (this pass):**
- `public`: 1
- `authenticated`: 2
- `viewer`: 18
- `reviewer`: 3
- `approver`: 2
- `admin`: 4
- `service`: 0 (no routes in these 4 files require service-role access today)

**Out of scope for this pass (deferred to subsequent P0.1 sub-passes):** all other TBD router families remain as-is in the file-level table above. Two prior matrix entries were corrected by this pass:
- `dashboard.py` "mutations: reviewer" → corrected to **zero mutations** in current code.
- `governance.py` "mutations=admin" → corrected to **zero mutations** in current code (mutating governance work lives in other routers).

**Definition of done for P0.1 globally:** the per-file table at the top of this document still has TBDs across the remaining router families; those will close in their own signed sub-passes prior to P1.C implementation.

**Phase 1 prerequisite — BLOCKED on user-supplied Entra ID credentials before P1.H can begin:**
1. Entra Tenant ID (GUID)
2. Entra API app-registration Client ID (GUID)
3. API Scope URI (e.g. `api://<api-client-id>/access_as_user`)
4. Optional: SPA app-registration Client ID (if separate from the API app)

Until these four values are supplied, P1.H (backend JWT validation) and P1.K (MSAL.js frontend) remain not-started.
