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
| `sales_dashboard.py` | 9 | **reviewer** | SO dashboard mutations |
| `intake_learning.py` | 8 | **admin** | Learning config |
| `inventory_xls.py` | 8 | **reviewer** | XLS uploads |
| `automation_intelligence.py` | TBD | **admin** | Automation config |
| `automation_rules.py` | TBD | **admin** | Rules config |
| `auth.py` | TBD | **public** (login/logout) + `admin` (user management) | Two-tier within file |
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
| `dashboard.py` | TBD | (mostly read; mutations: `reviewer`) | |
| `dedup.py` | TBD | **reviewer** | |
| `dev_tools.py` | TBD | **admin** | Dev-only |
| `email_polling.py` | TBD | **admin** | Polling control |
| `events.py` | TBD | **admin** | Event mutations |
| `explain.py` | TBD | (read-only? confirm) | |
| `feedback_health.py` | TBD | **reviewer** | |
| `file_import.py` | TBD | **reviewer** | |
| `file_integrity.py` | TBD | **admin** | |
| `freight_routing.py` | TBD | **reviewer** | |
| `governance.py` | TBD | mixed: read=`viewer`, mutations=`admin` | |
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
