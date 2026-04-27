# P0.3 — Feature Flag Inventory (Read-Only Phase 0 Scan)

**Status:** READ-ONLY inventory. Per `a7k3qm` directive, the central feature-flag registry (P1.B) is **deferred to Phase 2** — this doc exists so Phase 2 starts with a verified inventory rather than rediscovering it.

**Scope:** all `os.environ.get(...).lower() == 'true'` and equivalent boolean-flag patterns in `/app/backend/`. Excludes credential/URL env vars (they are config, not flags). 156 unique env-var references found total; the boolean-flag subset is enumerated below.

## Boolean feature flags (currently env-driven)

| Flag | Default | Used in | Posture |
|---|---|---|---|
| `DEMO_MODE` | `true` | `server.py:183`, `bc_draft_service.py:24`, `bc_link_service.py:20`, `bc_sandbox_service.py:63` | Universal demo gate. **Replicated in 4 files** — Phase 2 consolidation candidate. |
| `AI_CLASSIFICATION_ENABLED` | `true` | `server.py:188` | Core feature gate |
| `AUTO_CREATE_SALES_ORDER_ENABLED` | (per env) | `services/auto_post_service.py:477` (canonical), exported via `server.py:248` | 4d.7/4d.8 reverse-arrow target — already canonical |
| `AUTO_POST_ENABLED` | (per env) | `services/auto_post_service.py` | Canonical |
| `BC_WRITE_ENABLED` | `false` | `server.py:5617`, `services/ap_auto_post_service.py:219` | **Replicated in 2 files** — consolidation candidate |
| `BC_BLOCK_PRODUCTION_WRITES` | `true` | `services/bc_sandbox_service.py:1295` | Safety gate |
| `BC_MOCK_MODE` | (per env) | `services/business_central_service.py` | Mock toggle |
| `BC_WRITEBACK_LINK_ENABLED` | (per env) | various | BC link feature |
| `EMAIL_POLLING_ENABLED` | `false` | `server.py:191` | Polling on/off |
| `SALES_EMAIL_POLLING_ENABLED` | `false` | `server.py:198` | SO polling on/off |
| `ENABLE_CREATE_DRAFT_HEADER` | `false` | `server.py:186` | Feature gate |
| `EOD_ENABLED` | (per env) | `workflows/batch/eod_controller.py` | EOD job gate |
| `INSIDE_SALES_PILOT_ENABLED` | (per env) | `services/inside_sales_pilot_service.py` | Pilot scope |
| `PILOT_MODE_ENABLED` | (per env) | various | Pilot gate |
| `DRIFT_WATCHLIST_ENABLED` | (per env) | `workflows/core/learning_core/drift_watchlist_service.py` | Watchlist gate |
| `SPIRO_INTEGRATION_ENABLED` | (per env) | spiro stack | Integration gate |
| `SPIRO_CONTEXT_ENABLED` | (per env) | spiro stack | Sub-feature |

## Phase 2 consolidation watchlist

- `DEMO_MODE` defined in 4 distinct modules → must consolidate to a single source via P1.B (Phase 2).
- `BC_WRITE_ENABLED` defined in 2 modules → consolidate.
- All others appear single-source and are good migration candidates.

**No Phase 1 code touches any of these flags.** Phase 1 only adds two new flag-shaped controls:
- `RBAC_ENFORCEMENT_ENABLED` — **NOT introduced** in Phase 1 (per `RBAC_AUDIT.md` decision: RBAC is always-on, no flag).
- `ENTRA_AUTH_ENABLED` — **NOT introduced** in Phase 1; the Entra dependency is wired unconditionally.
