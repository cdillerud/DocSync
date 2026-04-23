# GPI Document Hub — Product Requirements Document

## Original Problem Statement
Build and continuously refine the Sales/AP Modules and Document Inbox with AI autonomy and continuous learning. Goal: aggressively shrink the Inbox "Needs Review" queue by closing validation gaps (PO, Customer, Vendor, SO, Duplicate) so docs are auto-routed.

## Core Product Requirements
1. Per-Document Intelligence Engine
2. Advanced Intelligence Engines (Gap Closers) for POs, Customers, Vendors, SOs, Duplicates
3. Accurate validation gap reporting across monitoring dashboards
4. Auto-resolution of high-confidence vendor aliases
5. Executive Monitoring Dashboard (`/monitor`)
6. Vendor Profile Consolidation
7. Exception and Retry mechanisms
8. Inbox Metrics Panel — Detailed breakdown of docs IN the inbox by Status, Type, Age, Vendor, Blocker
9. Captured Doc Auto-Retry — Docs stuck in "captured" get 4 retries then escalate to Exception Queue

## Architecture
- **Frontend**: React (Vite) with Shadcn UI, dark theme
- **Backend**: FastAPI with MongoDB
- **Deployment**: Docker on Azure VM (git pull → docker compose up)
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph

## Key File References
- `/app/backend/routers/dashboard.py` — inbox-stats, inbox-metrics, insights endpoints
- `/app/backend/routers/readiness.py` — Force cleanup, Exception retry, PO park/retry, Captured retry
- `/app/backend/routers/documents.py` — Queue endpoints, TERMINAL_STATUSES, is_duplicate filter
- `/app/backend/routers/aliases.py` — Vendor matching & alias suggestions
- `/app/backend/routers/workflow_fix.py` — Batch-fix stuck "captured" docs
- `/app/backend/routers/intake_learning.py` — Hub-wide BC+Spiro learning endpoints (2026-04-18)
- `/app/backend/services/sales_intake_learning_service.py` — Giovanni-pattern orchestrator (2026-04-18)
- `/app/backend/services/order_line_patterns.py` — Core pattern learning engine (Giovanni C-10250)
- `/app/backend/services/unified_validation_service.py` — Validation facade + intake_learning stage
- `/app/backend/server.py` — Main server, background schedulers (PO retry, Captured retry), intake pipeline
- `/app/frontend/src/pages/UnifiedQueuePage.js` — Inbox with metrics panel, retry-stuck button, tabs
- `/app/frontend/src/pages/IntakeLearningPage.js` — Intake-learning dashboard (2026-04-18)
- `/app/frontend/src/components/IntakeLearningPanel.jsx` — Drop-in insights panel (2026-04-18)

### 2026-04-18 — Intake Learning v2.5.1 (Giovanni + Feedback + Cold-Start + Unified Core)
- **v2.2.0**: Generalized Giovanni/Nikki blanket-PO BC learning (C-10250) to every ingested doc + XLS spreadsheet
- **v2.2.1**: IntakeLearningPanel on every Document Detail page; de-pilotized UI labels
- **v2.3.0**: Learning feedback loop — thumbs-up/down buttons, pattern trust/retire, hygiene scheduler, Pattern Health dashboard
- **v2.4.0**: Cold-start peer matching — pure-python TF-IDF fingerprints + inherited suggestions + promote-to-own
- **v2.4.1**: Learning Core U1 — unified `learning_events_v2` collection + dual-write from intake, cold-start, and AP draft feedback
- **v2.5.0**: Proactive Drift Alerts — 5 drift rules scan unified log nightly (trusted-pattern drift, reject spike, bounds drift, AP template drift, catalog explosion), inline Ack/Resolve UI
- **v2.5.1**: Learning Core U2 — shared TF-IDF fingerprint service for both customer (intake) and vendor (AP); unified `scope_fingerprints` collection
- Read-only wrt BC. 42/42 pytest + testing agent iter 210/211/212/213/214 all 100% green. Giovanni data kept pristine.

### 2026-04-21 — AP Path Consolidation v2.5.25 (Phases 2 + 3)
- Single canonical AP mutation surface: **`POST /api/ap-review/documents/{doc_id}/{action}`** for `set-vendor`, `update-fields`, `override-bc-validation`, `start-approval`, `approve`, `reject`.
- All Path A mutation routes JWT-gated via `Depends(get_current_user)`; all delegate to `services/workflow_handlers.py` so every transition drives through `WorkflowEngine.advance_workflow`.
- Legacy `/api/workflows/ap_invoice/{doc_id}/{action}` kept live for one release with `deprecated=True` in OpenAPI and `X-Deprecated` headers attached to every response (including HTTPException paths).
- Frontend `lib/api.js` helpers (`setVendor`, `updateFields`, `overrideBcValidation`, `startApproval`, `approveDocument`, `rejectDocument`) repointed to Path A with bodies normalized to canonical Pydantic shapes.
- New regression suite `tests/test_ap_path_consolidation.py` — 36/36 passing. Phase 4 (deletion of Path B) scheduled for next release.



### 2026-04-22 — Deprecation observability + Partial-post integrity v2.5.26
- **Server-side observability of Path B hits:** every `/api/workflows/ap_invoice/{id}/{action}` call emits a `WARNING` log and increments a template-keyed counter in `db.deprecation_hits`. New admin endpoint `GET /api/admin/deprecation-metrics?days=N` aggregates hit counts — used as the hard gate before Phase 4 route removal.
- **Partial-post integrity (auto-post path):** `routers/gpi_integration.py::create_purchase_invoice_from_document` now mirrors `business_central_service` partial-post detection. Header-accepted + lines-rejected flips `success=False`, attempts orphan-draft deletion, and blocks `ap_auto_post_service` from writing `bc_posting_status="posted"`. Financial-integrity leak closed; 4/4 integration tests green.
- **Phase 4 removal plan:** `/app/memory/PATH_B_REMOVAL_PLAN.md` locks the symbols to delete, the hard metric gate (zero hits for 7 days), the rollback path, and the sequence.


- `/app/frontend/src/pages/MonitoringDashboard.js` — Vendor mapping UI

## Critical Data Rule

### 2026-04-22 — Phase 4 gate projection + 422 disclosure v2.5.27
- **Phase 4 one-curl gate check:** `GET /api/admin/deprecation-metrics` response now includes a `phase_4_gate` object with `gate_met` boolean, `offending_callers[]` (caller IP + UA), `hits_by_template`, and `action_if_gate_not_met`. The 7-day window is hard-coded so `?days=N` cannot narrow the gate accidentally.
- **422 blind-spot disclosed in three places:** `_deprecate()` docstring, admin endpoint docstring, `phase_4_gate.observability_limitations[]` field in the payload, plus a dedicated §2c in `PATH_B_REMOVAL_PLAN.md` with a covered-vs-uncovered scenario table. We explicitly say `deprecation_hits` captures valid Path B requests that reach the wrapper — not every malformed attempt.
- **Backlog reorder:** retry/backoff + posting-attempt history sit ahead of server.py decomposition per workflow-integrity priority.
- 7 new tests (`test_deprecation_metrics.py`), full regression 122/125 (3 concurrency skips by design).

- `is_duplicate: {"$ne": True}` must be included in ALL inbox-related queries (documents list, inbox-stats, inbox-metrics) to match the actual inbox view. The documents endpoint enforces this at line 180.


### 2026-04-23 — Phase 3 Step 2R: AP compute-wrapper cleanup
- **Audit correction before signing**: original Phase 3 audit claimed ~220L of AP compute business logic in `server.py:1478-1700`. Reality: 5 one-line compatibility shims totaling ~45L; the real logic was already extracted into `services/ap_computation.py` and `services/document_intel_helpers.py` by a prior step. Scope revised to wrapper-cleanup only.
- **Micro-amendment before coding**: `_build_vendor_resolution` discovered to contain a real try/except fallback (not a pure shim) — intentionally excluded to preserve behavior. Deletion scope narrowed to 5 pure `compute_*` wrappers.
- **Deletions from `server.py`** (5 wrapper functions): `compute_ap_normalized_fields`, `compute_ap_validation`, `compute_ap_status`, `compute_canonical_fields` (legacy alias, zero callers), `compute_draft_candidate_flag`.
- **Direct-import block added** at `server.py` near line 1699: clearly labeled `DIRECT CANONICAL IMPORTS: AP compute functions`. Names preserved, so all 6 call sites (3078, 3150, 3889, 3916, 4760, 5506) resolve to the authoritative service symbols with zero call-site rename.
- **`policies/ap_invoice.py` docstring** corrected (factual, minimal): stale "migration from server.py:3333-3634" sentence replaced with a statement naming `services.ap_computation`, `services.document_intel_helpers`, and `services.vendor_resolution_service` as the authoritative compute-lane sources.
- **`_build_vendor_resolution` preserved** per signed narrowing — future step can migrate the fallback into the service or formalize it otherwise.
- **Parity probe**: new `tests/test_ap_wrapper_cleanup_parity.py` — 8/8 passed. Three classes: byte-identical output probe, source-inspection confirming deletions, guardrail asserting `_build_vendor_resolution` and its fallback are preserved.
- **`server.py`: 7,889 → 7,854 lines (−35 net)**. Phase 3 cumulative reduction: 8,903 → 7,854 = −1,049 lines (−11.8%) across Steps 1 + 2R.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). Path A auth-gated routes unaffected. Canonical service logic untouched.
- **Targeted regression**: 409 passed. Known unrelated baseline failures (`TestRouteCountStable::test_count` stale magic number; `test_reprocess_uses_direct_import` asserts on a file 2R did not touch) unchanged.



### 2026-04-23 — Phase 3 Step 1: Shadow-handler deletion from `server.py`
- **Deleted Block A** (4 Pydantic model shadows): `SetVendorRequest`, `UpdateFieldsRequest`, `BCValidationOverrideRequest`, `ApprovalActionRequest` — canonical copies remain in `services/workflow_handlers.py:34–58`.
- **Deleted Block B** (15 handler function shadows + 3 section headers + stale "Moved to" comment): `set_vendor_for_document`, `update_document_fields`, `override_bc_validation`, `start_approval`, `approve_document`, `reject_document`, `mark_ready_for_review`, `mark_reviewed`, `start_approval_generic`, `approve_generic`, `reject_generic`, `complete_triage`, `link_credit_to_invoice`, `tag_quality_doc`, `export_document` — canonical copies remain in `services/workflow_handlers.py`.
- **Single file touched**: `server.py`. Zero edits to `services/workflow_handlers.py`, routers, frontend, or DB schema.
- **`server.py`: 8,903 → 7,889 lines (−1,014, −11.4%)**.
- **Runtime behavior**: zero change. OpenAPI path count = 858 (unchanged); Path A `/api/ap-review/documents/{doc_id}/*` all functional; generic workflow mutation routes (`/api/workflows/{doc_id}/*`) all functional; Path B (`/api/workflows/ap_invoice/{doc_id}/*`) still 404 from Phase 4 removal.
- **Regression**: Lane C + workflow-extraction aggregate **379/379 passed**. Only remaining failure is the pre-existing stale `TestRouteCountStable::test_count` (expects 427, actual 901 — same as Phase 4 baseline, not introduced by this work).
- **Phase 3 sequence established**: Step 1 (shadow deletion, ✅ done) → Step 2 (AP compute-function extraction into `policies/ap_invoice.py`, next signed step).



### 2026-04-23 — Phase 4 Path B Removal (Lane A completion)
- **Production gate met**: prod VM returned `gate_met: true`, `total_hits_in_window: 0` across all six AP mutation Path B templates, empty `offending_callers[]`, zero hits in the full 14-day lookback.
- **Removed**: six deprecated `/api/workflows/ap_invoice/{doc_id}/{action}` routes (set-vendor, update-fields, override-bc-validation, start-approval, approve, reject) from `routers/workflows.py`. Path A under `/api/ap-review/documents/{doc_id}/{action}` becomes the sole authority.
- **Removed orphan functions**: `_record_deprecation_hit`, `_deprecate` (the wrapper factory) in `routers/workflows.py`, plus the `from functools import wraps` import and the 6 unused handler imports from `services.workflow_handlers`.
- **Deleted tests**: 6 Path B negative tests in `tests/test_workflow_handler_extraction.py::TestAPInvoiceRouteAvailability`.
- **Repointed error text** (correctness fix, signed in declaration):
  - `server.py` lines 6612 / 6670 / 6728 — `"use /api/workflows/ap_invoice/{doc_id}/..."` → `"use /api/ap-review/documents/{doc_id}/..."` (×3)
  - `services/workflow_handlers.py` lines 690 / 749 / 808 — same (×3)
- **Explicitly NOT touched** (per signed scope fence):
  - `routers/admin.py` `phase_4_gate` projection + `AP_MUTATION_TEMPLATES` list — stays in place, will report `gate_met=true, hits=0` forever (harmless).
  - `frontend/src/lib/api.js` comment.
  - Path A handler logic in `services/workflow_handlers.py` (beyond 3 error-text strings).
- **Verification**:
  - `/openapi.json` path count: **864 → 858** (exactly -6).
  - `POST /api/workflows/ap_invoice/bogus/approve` → **HTTP 404** (route gone).
  - `POST /api/workflows/ap_invoice/bogus/set-vendor` → **HTTP 404** (route gone).
  - `POST /api/ap-review/documents/bogus/approve` → **HTTP 401** (route auth-gated, still works).
  - Full Lane C regression: **379/379 passed** (only remaining failure `TestRouteCountStable::test_count` is a pre-existing stale-magic-number baseline test, unchanged by this work).
  - Ruff clean on all touched files.
  - Backend + frontend supervisor RUNNING.
- **Lane A (AP Path Consolidation) is now complete**: canonical AP mutation surface lives exclusively at Path A.



### 2026-04-23 — Lane C Step 8: Planning / Import (Coloplast, Option A foundation)
- **New top-level package** `workflows/planning/` — parser + validator + typed row model. No persistence. No routes. No scheduler. No wire-in. No LLM.
  - `__init__.py` (42 lines) — re-exports.
  - `module.py` (10 lines) — scope doc.
  - `types.py` (90 lines) — frozen dataclasses: `PlanningRow`, `PlanningRowError`, `PlanningSheet`, `PlanningParseResult`; `PlanningRowSeverity` literal.
  - `coloplast.py` (297 lines) — `parse_coloplast_sheet(sheet)` deterministic parser. Recognizes canonical column aliases (Item/SKU/Part No; UOM/UM/Unit; Description), weekly period headers (`W15`, `Week 15`, `2026-W15`) via ISO calendar, numeric/named monthly headers (`2026-04`, `04/2026`, `Apr 2026`, `April 2026`). Emits structured `PlanningRowError` on ambiguity — never invents intent. Skips blank rows and footer totals (`total`, `grand total`, `sum`, `totals`).
  - `validate.py` (135 lines) — `validate_planning_rows(rows, customer_no=None, today=None, horizon_weeks=26, backlog_weeks=1)`. Row-level policy: item_no non-empty, customer_no present & matching expected, qty finite & non-negative, period within ±26-week horizon. Warn-level for horizon violations; error-level for integrity violations. Pure — never mutates rows.
- **Tests**: `tests/test_planning_coloplast_parser.py` — **33/33 passed** (canonical shape, 12 column-alias parametrizations, structural errors, row skipping, determinism, separation-from-inventory-staging, separation-from-sales-workflow, unwired + LLM-free guardrails). `tests/test_planning_validator.py` — **16/16 passed** (happy path, required fields, qty discipline incl. NaN/inf, horizon bounds, error structure, row-non-mutation).
- **Separation proof**:
  - Static scan asserts `workflows/planning/` contains no references to `STAGING_COLL`, `inv_import_staging`, `inv_xls_learned_mappings`, or `workflows.inventory.planning.staging`.
  - Static scan asserts no references to `so_rules_engine`, `document_readiness_service`, `hub_documents`, `workflow_engine`, `business_central_service`, or `evaluate_and_persist`.
  - Static scan asserts no LLM references (`emergentintegrations`, `LlmChat`, `openai`, `anthropic`, `gemini`, `EMERGENT_LLM_KEY`).
- **Runtime**: zero. `/openapi.json` = 864 paths (unchanged). `workflows/inventory/planning/staging.py` (26,499 bytes) and `services/sales_intake_learning_service.py` (38,117 bytes) untouched.
- **Aggregate Lane C suite**: **361/361 passed** in 1.30s.
- **Deferred for later signed steps**: staging collection (`planning_import_staging`), router, SO-generation consumer (forecast → SO drafts / blanket-PO drawdowns), scheduler, BC writes, non-Coloplast customer formats.



### 2026-04-23 — Lane C Step 7b: Reselling COW — Evidence enrichment (Option 1)
- **Chose Option 1** after semantic re-declaration: Reselling COW is a **cross-cutting ownership refinement**, not a new sales archetype. No `reselling_cow/` package was created. Single COW truth surface (`cp_item_registry` + `classify_item_ownership` + `get_cp_item`) preserved.
- **Single file touched**: `workflows/inventory/ownership.py` — additive ~35 lines:
  - `_RESALE_SIGNAL_KEYS` tuple locks the three-field surface: `resale_authorization_id`, `resale_authorized_by`, `resale_authorization_date`.
  - `_extract_resale_context(doc)` reads those three signals exclusively from `doc.extracted_fields`; returns `None` when all absent/empty; trims string values.
  - `check_cow_so_uses_base_item` extended to attach `resale_context` **only** on `cow_so_wrong_customer` evidence rows and **only** when `_extract_resale_context` returns non-empty.
- **Enforcement unchanged**: `BLOCKER_CODE_SO_WRONG_CUSTOMER` still appends to `readiness.blocking_reasons`; no severity downgrade. Authorization presence is documentary only.
- **Scope strictly**: no new package, no new collection, no new HTTP route, no new ownership accessor, no frontend touches, no readiness-pipeline changes.
- **Tests**: `tests/test_cow_reselling_evidence.py` — **12/12 passed**.
  - Attachment: full-signal / partial-signal / empty-string rejection / whitespace-trimming.
  - Scoping: resale_context attaches ONLY to wrong-customer rows (not same-customer base-item code, not unknown_cp_pattern code, not when no signals present).
  - Enforcement invariants: block code still appended; authorization presence never downgrades the block.
  - Single-truth-surface: static source-inspection asserts `_extract_resale_context` reads only `extracted_fields` and never touches `cp_item_registry`/`classify_item_ownership`/`get_cp_item`; module carries no drift symbols (`classify_resale_ownership`, `get_resale_item`, `resale_item_registry`).
- **Regression**: Step-1 COW 28/28 unchanged, Step-2 consignment 27/27 unchanged, full Lane C aggregate **312/312 passed** in 1.22s. `/openapi.json` paths = 864 (unchanged).
- **Future step (unsigned)**: if the business later decides authorizations should downgrade the block to warn, that layer builds on this evidence foundation rather than requiring a rework.



### 2026-04-23 — Lane C Step 7 (narrowed): Customer Storage + Reroute
- **Scope split** — Reselling COW **deferred** out of Step 7 and will be re-declared separately; this step lands only Customer Storage and Reroute as signal-driven, unwired-foundation gate surfaces.
- **New package** `workflows/sales/subtypes/customer_storage/` — two gates, signal-driven (no classifier, no registry, no writes):
  - `customer_storage_without_storage_agreement` → **warn**
  - `customer_storage_ship_out_missing_release` → **block**
  - Signals read: `extracted_fields.is_customer_storage`, `extracted_fields.storage_agreement_id`, `extracted_fields.storage_release_id`, line-level `from_customer_storage=true` + `quantity>0` for ship-out detection.
- **New package** `workflows/sales/subtypes/reroute/` — two gates, `location_code=="001"`-driven (no classifier):
  - `reroute_location_without_original_so` → **warn** (mirrors freight-side `rerouted_missing_so` warning at sales-archetype layer)
  - `reroute_requires_drop_ship_linkage` → **warn** (non-duplicative with live SO-008 — orthogonal trigger axes: keyword-detection vs location_code)
  - Freight-side authority (`workflows/freight/item_charges.LOCATION_REROUTED`, `services/freight_gl_routing_service`, `services/bc_reference_cache_service.find_so_for_rerouted_po`) **untouched**.
- **Runtime behavior**: zero. Opt-in `register_*_gates` only; no auto-registration; `/openapi.json` paths = 864 (unchanged); `services/so_rules_engine.py` / `workflows/freight/item_charges.py` / `workflows/inventory/ownership.py` bytes on disk unchanged.
- **Tests**: `tests/test_customer_storage.py` 15/15 + `tests/test_reroute.py` 19/19 = 34/34 green. Prior-step regression (Steps 1–6 + EOD + shipment-method + taxonomy + Lane C registries) 266/266 green. Aggregate Lane-C suite: **300/300** passed in 1.18s.
- **Non-duplication proof for Reroute**: pytest `TestNonDuplicationWithLiveSo008` asserts the live `so_rules_engine._check_drop_ship_rules` uses keyword detection while the new reroute gates use location-code detection; both can flag the same doc without conflict.
- **Deferred**: Reselling COW (separate declaration), Step 9 warn→block upgrade, DS env-flag shadow mode.



### 2026-04-23 — Lane C Step 6: Drop Ship formalization (extraction seam)
- **New package** `workflows/sales/subtypes/drop_ship/` with three gate classes as authoritative-equivalent scaffolding for the Drop Ship archetype. Adapter-driven over the canonical gate framework. No classifier (defers to live `services.document_intel_helpers._classify_so_subtype`). Trigger axis is `doc.so_subtype == "DS_Sales_Order"`.
- **Severity ledger (parity with live `so_rules_engine._check_drop_ship_rules`):**
  - `drop_ship_po_missing` → **block** (SO-008 parity)
  - `drop_ship_po_cost_unverified` → **warn** (SO-009 parity)
  - `drop_ship_inventory_line_not_marked` → **warn** (ancillary parity)
- **Convergence mechanic**: extraction seam — chosen over move/wrap to keep live consumers (`server.py:2776`, `routers/inside_sales_pilot.py:785`) undisturbed. `services/so_rules_engine.py` bytes unchanged. No auto-registration; callers opt in via `register_drop_ship_gates(registry)`.
- **Runtime behavior**: zero change. No new routes (`/openapi.json` paths = 864, unchanged). No readiness pipeline, router, frontend, or DB schema touches.
- **Tests**: `tests/test_drop_ship_order.py` 24/24 green (SO-008/009/ancillary parity, opt-in registration, archetype-scoped, idempotent double-register, unwired guardrail asserting no external imports of the package and `so_rules_engine._check_drop_ship_rules` still owns live DS logic). Full prior-step regression 242/242 unchanged.


## Completed Features

### 2026-04-23 — Phase 3 Step 4a: `_internal_intake_document` caller rewire (seam-only)
- **Scope split upfront (Step 4 → 4a + 4b)**: audit found `_internal_intake_document` (760-line function at `server.py:2861–3621`) references 8 `server.py`-module-scope helpers (`_attempt_llm_vendor_ranking`, `_build_vendor_resolution`, `_derive_workflow_status`, `_emit_intake_events`, `_update_ap_workflow_status`, `_update_standard_workflow_status`, `_update_vendor_profile_incremental`, `make_automation_decision`) plus module globals. Moving the body alongside 6 caller rewires is a real blast-radius step. User signed the split — Step 4a rewires callers to a thin seam; Step 4b later does the body move.
- **Canonical destination**: new public thin-seam wrapper `services.document_handlers.intake_document_from_bytes(**kwargs)`. Byte-identical signature to `server._internal_intake_document`. Pure forwarder — lazy-imports the target and dispatches kwargs verbatim. NO preprocessing, NO normalization, NO logging, NO metrics, NO branching (signed guardrail).
- **Caller inventory — all 6 rewired**:
  1. `routers/sales_pipeline_demo.py:287–297` (demo ingestion, `source="demo_pipeline"`).
  2. `routers/pilot.py:918` (pilot mailbox, `source="email"`). Note: this caller previously had a **latent NameError** — no import statement existed for `_internal_intake_document`; the rewire adds an explicit `from services.document_handlers import …` so the call path is now correctly bound.
  3. `services/email_polling_service.py:501–502` (AP email polling, `source="email_poll"`).
  4. `services/email_polling_service.py:867–868` (Sales email polling, `source="email"`).
  5. `services/inside_sales_pilot_service.py:387–389` (`source="inside_sales_pilot"`).
  6. `services/batch_po_splitter.py:162+232` (child ingestion, propagates parent `source`).
- **Explicitly untouched** (in-file self-reference, Step 4b scope): `server.py::intake_document` (HTTP route at line ~3670) still calls `_internal_intake_document` in-file.
- **Parity probe**: new `tests/test_intake_caller_rewire_parity.py` — **22/22 passed**. 5 classes:
  - **Class A — Wrapper identity**: parameter list + defaults byte-identical to `_internal_intake_document`; kwargs forward unchanged across explicit and default-using invocations.
  - **Class B — Per-caller source-code verification**: each of the 6 caller files imports the new seam, no longer contains `from server import _internal_intake_document`, and the `await intake_document_from_bytes(` call count matches per-file expectation.
  - **Class C — Per-ingest-mode kwarg preservation**: 6 parametrized modes (`demo_pipeline`, `pilot_email`, `ap_email_poll`, `sales_email_poll`, `inside_sales_pilot`, `batch_po_splitter_child`) — each caller's kwarg bundle arrives at the underlying function byte-identical.
  - **Class D — Live OpenAPI surface**: path count remains **858** on `localhost:8001`; `/api/documents/intake` still registered.
  - **Class E — Guardrails**: `_internal_intake_document` signature byte-stable; `server.py` does NOT import the wrapper (would create circular risk); wrapper source contains no forbidden content (no logger calls, no DB ops, no metrics, no source-branching); wrapper body ≤ 25 code lines.
- **`server.py`: 7,402 lines (unchanged — pure topology change)**. Phase 3 cumulative: still **8,903 → 7,402 = −1,501 lines (−16.9%)** through Steps 1 + 2R + 2B + 3 + 4a. The value of Step 4a is decoupling the 6 external callers from `from server import …` so Step 4b can move the body without coordinating caller updates.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged). All 6 ingestion paths continue to dispatch to the identical function via the wrapper.
- **Targeted regression**: **278 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — identical pre-vs-post stash; same failure as after Step 3). Zero regressions introduced.


### 2026-04-23 — Phase 3 Step 3: AP auto-post branch extraction
- **Scope split upfront**: original user direction named "Step 3/4 — AP auto-post orchestration and intake-branch migration". Blast-radius audit showed meaningful asymmetry: intake branch is ~30 lines with 2 in-file call sites, while `_internal_intake_document` external-caller migration touches 6+ callers across 4 external modules. User signed the split — this declaration covered Step 3 only; Step 4 deferred to a separate declaration.
- **Canonical destination**: new helper `services.ap_auto_post_service.finalize_ap_decision` (co-located with `attempt_ap_auto_post` — single module owning the full AP auto-post lifecycle). Explicitly NOT `policies/ap_invoice.py` — that module is a `PolicyModule` evaluator pattern, not a home for effectful DB-writing orchestration.
- **Helper signature** (narrowly behavior-preserving per signed guardrail — no retry, no metrics, no shadow-mode, no policy semantics added):
  ```python
  async def finalize_ap_decision(
      doc_id, db, *, source,
      emit_reprocess_events=False,
      on_exception_fallback_status=None,
  ) -> {"status", "posted", "reason", "bc_record_no", "events_emitted"}
  ```
- **Server.py rewires** (2 call sites — total):
  1. `server.py::_internal_intake_document` lines 3346–3373 (~28 lines) → `finalize_ap_decision(doc_id, db, source="auto")`. Outer `try/except` preserved for intake-parity "swallow" semantics.
  2. `server.py::_reprocess_document_inner` lines 4698–4722 (~25 lines) → `finalize_ap_decision(doc_id, db, source="reprocess", emit_reprocess_events=True, on_exception_fallback_status="NeedsReview")`. Plus removed the previously-inlined 35-line reprocess-events-emission + derived-state-refresh block at lines 4732–4758 (now absorbed by helper when `emit_reprocess_events=True`).
- **Preserved inline by declared scope**: `bc_vendor_number` pre-update in reprocess branch (depends on `validation_results` not passed through helper), the "[REPROCESS] Auto-clear SKIPPED" log line (belongs to auto-clear skip semantics, not finalize semantics).
- **Parity probe**: new `tests/test_ap_finalize_decision_parity.py` — **20/20 passed**. 4 classes:
  - **Class A — Pure-result parity**: recreates the inline intake decision tree, asserts helper return values match across 5 canonical `attempt_ap_auto_post` response shapes + 2 exception paths (intake swallow / reprocess fallback-to-NeedsReview).
  - **Class B — DB-mutation golden-file parity**: in-memory `_DbDouble` captures the exact sequence of `update_one` / `insert_one` calls the helper makes across 6 scenarios (intake × {posted,ready,needs_review} + reprocess × {posted,ready,needs_review}); asserts against golden fixture `tests/fixtures/ap_finalize_golden.json` (scope-filtered to the 3 direct mutations the helper is responsible for — status flip + 2 workflow_events; derived-state side-effects filtered out as DerivedStateService's own contract).
  - **Class C — Source-inspection guardrail**: `server.py` has exactly 2 `finalize_ap_decision` call sites and 0 remaining `attempt_ap_auto_post(` calls; `services/ap_auto_post_service.py` defines exactly 1 `finalize_ap_decision`; helper signature exactly matches the declared contract.
  - **Class D — Live-surface smoke**: `/api/documents/intake` + `/api/documents/{id}/reprocess` routes still registered on live `localhost:8001` backend; OpenAPI path count remains **858** (unchanged).
- **`server.py`: 7,437 → 7,402 lines (−35 net, −0.5%)**. Phase 3 cumulative: **8,903 → 7,402 = −1,501 lines (−16.9%)** across Steps 1 + 2R + 2B + 3. `services/ap_auto_post_service.py`: 807 → 939 lines (+132, helper + docstrings).
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged — no route surface touched). Intake and reprocess pipelines continue to produce identical status flips, identical workflow_events emission, identical derived-state refresh.
- **Existing test update**: `tests/test_ap_auto_post_service.py::TestCodePathVerification::test_server_imports_ap_auto_post_service` updated to assert the new post-Step-3 import pattern (`finalize_ap_decision`) instead of the removed direct `attempt_ap_auto_post` import. The authoritative module is still exercised — the helper calls `attempt_ap_auto_post` internally.
- **Targeted regression**: **256 passed, 1 pre-existing failure** (`test_post_to_bc_returns_404_for_missing_doc` — fails identically pre-stash and post-stash, unrelated auth/live-backend issue). Lane C aggregate 174/174 green.


### 2026-04-23 — Phase 3 Step 2B: AP queue/count shadow-def deletion
- **Audit correction before signing**: original user directive named Step 2B as "AP queue/count helpers **migration** into `policies/ap_invoice.py`". Reality was 10 already-undecorated, zero-caller dead shadow `async def`s in `server.py` — same shape as Step 1 shadows, not a migration candidate. Live canonical copies already run from `routers/workflows.py` (Domain 8). `policies/ap_invoice.py` is a `PolicyModule` class pattern, not a routes/queries container. User signed revised scope as **pure shadow deletion**.
- **Deletions from `server.py`** (10 shadow `async def`s + 2 bracketing `# Moved to routers/workflows.py (Domain 8)` comments + 1 orphaned `# ==================== GENERIC WORKFLOW QUEUE API ====================` header + 1 orphaned `# ==================== WORKFLOW METRICS ====================` header + trailing-blank runs):
  1. `get_ap_workflow_status_counts`
  2. `get_vendor_pending_queue`
  3. `get_bc_validation_pending_queue`
  4. `get_bc_validation_failed_queue`
  5. `get_data_correction_pending_queue`
  6. `get_ready_for_approval_queue`
  7. `get_workflow_queue`
  8. `get_status_counts_by_doc_type`
  9. `get_workflow_metrics_by_doc_type`
  10. `get_ap_workflow_metrics`
- **`policies/ap_invoice.py`** minimal factual docstring amendment: names `routers/workflows.py` as the live queue/count surface; left policy class contract untouched.
- **Out of scope per signed fence** (preserved): `routers/workflows.py` (live routes), `routers/pilot.py::get_ap_workflow_metrics` (separate live route under `/pilot` prefix), 3 unrelated `list_workflows`/`get_workflow`/`retry_workflow` shadows at `server.py:1197-1225` (their own removal needs a separate signed declaration), auto-post orchestration, intake branches, `_build_vendor_resolution`, frontend, DB schema.
- **Parity probe**: new `tests/test_ap_queue_shadow_deletion_parity.py` — **36/36 passed**. 3 classes: OpenAPI route-registration presence (all 10 live routes still registered + path-count floor sanity), source-inspection confirming 10 symbols absent from `server.py`, guardrails asserting live copies in `routers/workflows.py`, unrelated pilot route preserved, `APInvoicePolicy` class contract byte-stable.
- **`server.py`: 7,854 → 7,437 lines (−417 net, −5.3%)**. Phase 3 cumulative: **8,903 → 7,437 = −1,466 lines (−16.5%)** across Steps 1 + 2R + 2B.
- **Runtime behavior**: zero change. `/openapi.json` = 858 paths (unchanged — shadows had no decorators). Live smoke: `GET /api/workflows/ap_invoice/status-counts`, `/vendor-pending`, `/generic/queue`, `/ap_invoice/metrics` all return HTTP 200.
- **Targeted regression**: zero delta — exact same 20 pre-existing failures before/after (`TestPathBDeprecationHeaders` stale after Phase 4 Path B removal, `TestAuthEndpoints` using rejected `admin/admin` creds, `TestRouteCountStable::test_count` stale magic number, `test_reprocess_uses_direct_import` pre-existing). Lane C aggregate **174/174 passed** unchanged.


### 2026-04-22 — Blocker-Code Rendering Tidy v2.5.34
- **New shared util** `frontend/src/lib/blockerLabels.js` — `BLOCKER_LABELS` map + `labelForBlocker(code)` function. Covers all 8 Lane C COW/consignment codes + 6 common pre-Lane-C codes. Unknown codes gracefully fall through to the existing snake→Title Case behavior — zero risk of "???".
- **6 call sites swapped** across 3 files: `DashboardPage.js` (failure-reasons chart label + top-blockers + top-warnings), `DocumentDetailPage.js` (plain blocking_reasons + warning_reasons lists below the ownership evidence panel), `AutomationMetricsCard.js` (blocking + warning lines).
- **Wording tweak per signoff:** `consigned_item_post_lifecycle_on_so` → "Consigned item on Sales after lifecycle closed".
- **Zero backend changes, zero new endpoints, zero data mutations.** Raw blocker codes remain unchanged in `readiness.blocking_reasons[]` / `top_blocking_reasons[]` payloads — display-layer only.
- **Verification** — 0 lint issues across 4 touched files; Lane B regression unchanged at 317P/35F/14E; COW+consignment 55/55 unchanged; OpenAPI path set byte-identical at 862; screenshot smoke confirmed all mapped codes render with human labels, unmapped code falls through correctly.
- **Deferred**: `BCResolutionWidget.js` line 178 renders BC resolution miss-reasons from a *different* taxonomy (`missReasons`, not readiness blockers) — not in scope; flagged for a future BC-telemetry pass.

### 2026-04-22 — Reviewer UI Polish: Ownership Evidence Panel v2.5.33
- **New component** `frontend/src/components/OwnershipEvidencePanel.jsx` — structured renderer for `readiness.cow_items[]`, `readiness.cow_so_items[]`, and `readiness.consigned_items[]`. Three guarded sections, each shown only when its array is non-empty. Zero visual impact on docs without ownership evidence.
- **Integration** — inserted into `pages/DocumentDetailPage.js` inside the existing Readiness card, after Warnings. Reads the payload that `GET /api/documents/{doc_id}` already returns — **zero backend changes, zero new fetches, zero new endpoints**.
- **Per-row actions** — "Update registry" deep-links to `/config?tab={cp-items|consigned-items}&filter_item=<item_no>`; "Correct line" scrolls+highlights the extracted-data card via anchor `#doc-line-items` (guarded, no-ops cleanly when the card doesn't render).
- **Deep-link behavior in admin tabs** — `CpItemRegistryPanel.jsx` and `ConsignedItemRegistryPanel.jsx` now read `filter_item` from `useSearchParams`, pre-fill a new `item_no` text filter input, set the status filter to `all` on deep-link, and highlight the matched row with a primary ring. **Does NOT auto-open the create modal per signed amendment** — navigation only.
- **Verification** — 0 lint issues across 4 touched frontend files; backend Lane B regression 317P/35F/14E unchanged; COW+consignment 55/55 unchanged; OpenAPI path set byte-identical (862); screenshot smoke confirmed panel renders, deep-link navigation works with prefilled filter + highlighted row.

### 2026-04-22 — Lane C Step 2: Vendor Consignment v2.5.32
- **`consigned_item_registry` collection** — separate from `cp_item_registry`. Schema: `item_no` (unique), `vendor_no`, `physical_location`, `state ∈ {consigned_in, consumed, returned}`, `linked_receipt_ids[]`, `linked_consumption_ids[]`, `linked_return_ids[]` (all append-only), audit fields. Vendor-only consignor per signed Q2.
- **State machine** — exactly two legal transitions: `consigned_in → consumed` and `consigned_in → returned`. Terminal states; no reopen path. Transition requires `CONSIGNMENT_STATE_ACTOR_EMAIL` (env, default `items@gamerpackaging.com`) + mandatory `evidence_id` appended to the relevant link array.
- **5 hard-block rules** (all append to `readiness.blocking_reasons`, evidence in new `readiness.consigned_items[]`):
  - `consigned_item_on_ap_invoice` — AP invoice / PO with a `consigned_in` item
  - `consigned_item_wrong_state_on_ap` — AP invoice on a `consumed`/`returned` item
  - `consigned_item_on_sales_doc` — **any** sales doc with a `consigned_in` item (R3 widened per signoff)
  - `consigned_item_post_lifecycle_on_so` — sales doc on a `consumed`/`returned` item (R4 upgraded from warn per signoff)
  - `consigned_item_wrong_location_on_adj` — adjustment journal with non-matching `physical_location`
- **Wire-in** — single `try` block in `services/document_readiness_service.py::evaluate_and_persist`, immediately after the two existing COW blocks. Symmetric structure with idempotent clear on explicit re-eval.
- **Admin HTTP surface** — new `routers/consigned_item_registry.py` with 4 JWT-gated operations across 3 paths (`GET /api/consigned-items`, `GET /api/consigned-items/{item_no}`, `POST /api/consigned-items`, `POST /api/consigned-items/{item_no}/transition`).
- **Admin UI** — new `Consigned Items` tab in `SettingsHubPage.js`, component `ConsignedItemRegistryPanel.jsx`. List + vendor/state filters + create modal + per-row Consume/Return buttons (visible only in `consigned_in`). Evidence doc ID required on every transition; terminal-state policy explained in footer.
- **Tests**: `tests/test_cow_step2_consignment.py` — **27/27 green** (K1–K22 + helpers). Combined Step 1 + Step 2 ownership suite: **55/55**.
- **Regression**: Lane B-adjacent suite unchanged at 317P / 35F / 14E (normalized diff empty). OpenAPI: exactly +3 paths (862 total), 0 removed.

### 2026-04-22 — Lane C Step 1 Follow-up: COW SO-side gate + admin UI v2.5.31
- **SO-side hard block** — new `check_cow_so_uses_base_item` in `workflows/inventory/ownership.py`; fires for `SALES_INVOICE`, `SALES_ORDER`, `SO_CONFIRMATION`, `DS_SALES_ORDER`, `WH_SALES_ORDER`. Wired into `services/document_readiness_service.py::evaluate_and_persist` alongside the Step 1 PO block. Same canonical path, same explicit-reeval semantics, no new schedulers.
- **Two distinct blocker codes (per amendment):**
  - `cow_so_uses_base_item` — active registered CP or unknown CP-pattern item billed on a sales doc; evidence carries `recommended_base_item_no` for the base-item correction.
  - `cow_so_wrong_customer` — CP registered to customer A but billed on a doc for customer B; evidence carries `registered_customer_no` + `doc_customer_no`.
- **SO-side evidence lives in `readiness.cow_so_items[]`** (additive field, distinct from PO-side `readiness.cow_items[]`). Retired CP items still allow sales docs (registry retirement = customer consent to re-use as regular SKU).
- **Admin UI** — new tab `CP Items` in `SettingsHubPage.js`, component `components/CpItemRegistryPanel.jsx`. List + customer_no filter + status filter + refresh + create/upsert modal + per-row retire button with actor-email prompt. All elements have `data-testid` attributes. No charts, no bulk tools, no CSV — intentionally restrained per Amendment 3.
- **Zero new HTTP endpoints** — the 4 Step 1 endpoints cover the UI entirely.
- **Tests**: `tests/test_cow_step1.py` grew to **28/28 green** (+11 SO-side scenarios S1–S9 plus 2 apply-helper tests). Full Lane B-adjacent regression stays at 317P/35F/14E — diff empty. OpenAPI stays at 859 paths.

### 2026-04-22 — Lane C Step 1: Customer-Owned Ware v2.5.30
- **CP-item registry** — new MongoDB collection `cp_item_registry` with unique `item_no` index + `{customer_no, status}` compound index. Signed §4b schema: item_no, customer_no, base_item_no, canonical_location, linked_invoice_ids[] (append-only), status (active|retired), audit fields. Never programmatically retired — only `items@gamerpackaging.com` (env-configurable via `COW_RETIREMENT_ACTOR_EMAIL`) can flip status.
- **Ownership module** (`workflows/inventory/ownership.py`) — single source of truth for item ownership classification (`classify_item_ownership` returns `gamer | customer_owned_active | customer_owned_retired | unknown_cp_pattern`), CRUD helpers, CP-pattern regex `.*-CP[A-Z0-9]+$`, and the hard-block check `check_cow_item_on_po(doc)`.
- **Hard-block enforcement** — wired into the canonical readiness path (`services/document_readiness_service.py::evaluate_and_persist`). Block logic: active-registered CP item on PO → block; unknown-CP-pattern on PO → block; retired CP on PO → allow; inventory adjustment journal into `canonical_location` with positive qty → allow (signed §4b carve-out); adjustment journal into any other location → block. Writes `"cow_item_on_po"` to `readiness.blocking_reasons`, detail to `readiness.explanations`, structured evidence to `readiness.cow_items[]` (additive field).
- **Admin HTTP surface** — `routers/cp_item_registry.py` (3 paths / 4 operations): `GET /api/cp-items`, `GET /api/cp-items/{item_no}`, `POST /api/cp-items` (upsert), `POST /api/cp-items/{item_no}/retire`. All JWT-gated; retire also guards on actor email.
- **Test matrix** — `tests/test_cow_step1.py` 17/17 green (T1–T14 per signed pre-change declaration + 3 supplementary). T13/T14 use explicit canonical re-evaluation (not any background propagation, per amendment).
- **What is NOT included** — no gate_framework coupling (deferred to Step 2.75), no SO-side `COW_SO_USES_BASE_ITEM` gate, no frontend admin UI, no BC read/write of registry, no background re-evaluator.
- **OpenAPI diff**: +3 paths, 0 removals (additive). Regression: 317P/35F/14E on Lane B-adjacent suite unchanged; +17 new passes from COW suite.

### 2026-04-22 — Lane B Structural Carve-out v2.5.29
- **New `backend/workflows/` tree** per signed §2.1: 7 real files moved (workflow_engine → workflows.core.engine; learning_core dir; line_reconciliation; vendor_profile_helpers → rules/vendor_profile; freight_business_rules → freight/item_charges; inventory_ledger_service → inventory/ledger/service; inventory_xls_staging_service → inventory/planning/staging). 32 inert scaffold modules + 3 READMEs.
- **Real-file rule honored**: `vendor_profile_helpers.py` used in place of signed `vendor_profile_service.py` (file not present on disk); `bc_preflight` omitted (no source file existed).
- **163 import rewrites** across 54 files. Removed dead re-export from `services/__init__.py` (no shim layer per Amendment 2).
- **Verification**: `/openapi.json` byte-identical (856 paths, sha256 match). pytest diff empty vs baseline (317P/35F/14E). Supervisor clean.

### 2026-04-22 — Hygiene patch (post-Lane-A)
- JWT auth added to `GET /api/ap-review/documents/{id}/bc-status` (was unauthenticated).
- Frontend `limit=0` callers fixed for endpoints with `ge=1` constraint: `UnifiedQueuePage.js` (readiness exception-queue + po-pending), `SalesInventoryHubPage.js` (triage-queue). `/documents?limit=0` left untouched (backend accepts it).

### 2026-04-22 — Lane A Integrity v2.5.28
- **A1 Historical posting-attempts array** — `hub_documents.bc_posting_attempts[]` append-only audit log replaces overwrite-on-failure `bc_posting_error`. Frontend accordion on the AP review panel (collapsed by default, auto-expands on failed/partial/pending_retry). Legacy migration on startup.
- **A2 Retry/backoff on BC 429/503** — `bc_http_with_retry()` wraps the header POST and per-line POST inside `create_purchase_invoice`. 3 retries, 1s/2s/4s + jitter, circuit-break on exhaustion. Non-retriable 4xx passes through immediately.
- **A4 Pre-claim `workflow_engine.advance_workflow`** — BC post lifecycle is now a first-class engine concern via new events `ON_BC_POSTING_STARTED/ON_BC_POSTED/ON_BC_PARTIAL_POSTED/ON_BC_POST_FAILED` and states `BC_POSTING_IN_PROGRESS/BC_POSTED/BC_POST_PARTIAL`. Engine refuses ON_BC_POSTING_STARTED from invalid states → 409 before BC is called. On claim race, engine state reverts.
- **A3 gated** — Phase 4 Path B route deletion PR ready; merges when `phase_4_gate.gate_met=true` for 7 consecutive UTC days.
- Regression: 153/156 (3 concurrency skips by design) across 11 suites.

- Expanded TERMINAL_STATUSES (Validated, ReadyForPost, etc.)
- 20-Rule Force Cleanup Engine (`POST /api/readiness/sync-status`)
- Auto-Post Revert Bug Fix (non-AP docs no longer revert)
- Exception Queue + Retry System (4x retry → escalate)
- Vendor Matching Gap Closer (variants, manual BC search, dismiss)
- PO Auto-Retry Queue (park, 4h retry, 3d escalation, UI tab)
- Inbox Metrics Panel — `GET /api/dashboard/inbox-metrics` (2026-04-09)
- Captured Doc Auto-Retry — Background scheduler + manual endpoint + UI button (2026-04-09)
- **Bugfix: is_duplicate filter** — Added to inbox-metrics and inbox-stats pending_review so numbers match inbox table (2026-04-09)
- **ReadyForPost Auto-Post Scheduler** — Background loop (5min interval, 5 retries) posts ReadyForPost docs to BC when BC_WRITE_ENABLED=true. Manual trigger: `POST /api/readiness/retry-ready-to-post`. UI "Post Ready" button added. (2026-04-10)
- **Transient BC error resilience** — Failed BC posts now keep docs at ReadyForPost (not NeedsReview) so the scheduler retries. Permanent errors (404/422) still revert to NeedsReview. (2026-04-10)
- **Draft Auto-Approve in scheduler** — `auto_approve_drafts` now runs automatically every 2h cycle alongside draft feedback sync + continuous learning. High-confidence vendors auto-approved. (2026-04-10)
- **Cross-document dedup guard** — Gate 2b in `check_auto_draft_eligibility` prevents duplicate PI creation when another doc for same vendor+invoice already has a PI. (2026-04-10)
- **Posted to BC stats widget** — Inbox stats strip now shows `posted_to_bc_7d` and `ready_for_post` counts in real-time. (2026-04-10)
- **Vendor maturity fix** — Fixed maturity level labels to match frontend (mastered/proficient/developing/learning/novice), lowered thresholds (75/60/40/20), field_coverage defaults to 50 when no extraction patterns exist. (2026-04-10)
- **Bulk Classify endpoint + UI** — `POST /api/documents/bulk-classify` assigns doc_type to multiple docs with AI learning feedback. Dropdown + button in Inbox selection bar. (2026-04-10)
- **Vendor learning backfill** — Background scheduler backfills amount/line data from approved drafts' BC records for vendors showing $0. (2026-04-10)
- **Auto gap closer** — Gap closer now runs automatically in intelligence maintenance scheduler (2h cycle), re-evaluating docs with blocking validation gaps. (2026-04-10)
- **Freight Business Rules Engine** — Codified controller's (Meghan) freight processing rules into `freight_business_rules.py`. Includes: order number pattern detection (W/WR=inbound, 6-digit=outbound), location code routing (00=dropship, 001=rerouted), international vendor detection (CARGOMO/USCUSTO), shipment method codes (PPDADD/PPD/Delivered), freight item code validation, $100 variance threshold, multi-order invoice detection, LTL carrier duplicate risk (XPO/R&L), invoice naming convention parser. (2026-04-10)
- **Enhanced Freight GL Routing** — Controller rules now feed into freight GL classification as high-weight signals. Results include `controller_rules` with review flags persisted to document. (2026-04-10)
- **Freight-Specific Readiness Checks** — High freight variance blocks readiness. Multi-order invoices and LTL duplicate risk generate warnings. (2026-04-10)
- **Enhanced Duplicate Detection** — LTL carriers flagged with duplicate risk warning. In-hub duplicate check now includes order reference. (2026-04-10)
- **Noise Learning Events Cleanup** — Readiness self-corrections no longer pollute `posting_learning_events`. Dashboard queries filter out noise. Startup cleanup removes existing bad data. (2026-04-10)

## Key API Endpoints
- `POST /api/readiness/fix-validation-gaps` — Targeted PO learning + vendor resolution + re-evaluation
- `POST /api/posting-patterns/system/run-full-cycle` — 8-step intelligence orchestration
- `POST /api/readiness/sync-status` — Force cleanup engine
- `POST /api/readiness/retry-failed` — Batch retry extraction-failed docs
- `POST /api/readiness/retry-captured` — Retry stuck captured docs (4 max → exception)
- `POST /api/readiness/retry-ready-to-post` — Post ReadyForPost docs to BC
- `POST /api/documents/bulk-classify` — Bulk assign document type with AI learning
- `POST /api/readiness/po-pending/park` / `POST /api/readiness/po-pending/retry`
- `GET /api/dashboard/inbox-stats` / `GET /api/dashboard/inbox-metrics`
- `GET /api/aliases/vendors/unmatched-gaps` / `GET /api/aliases/vendors/search`

## Bugfix: "Needs Review" Status-Readiness Mismatch (2026-04-10)
**Root cause**: Three bugs caused ~270 documents to be stuck in "Needs Review" despite readiness being "ready_auto_draft"/"ready_auto_link":
1. **Bug 1 (server.py:7770, 7983)**: Gap closer scheduler and PO retry scheduler passed full document dicts instead of `doc["id"]` strings to `evaluate_and_persist()`, causing ALL background re-evaluations to silently fail.
2. **Bug 2 (readiness.py)**: `sync_readiness_to_status` excluded `auto_cleared=True` docs. If a doc was previously cleared but had its status reverted (e.g., by AP auto-post failure), it became invisible to the sync.
3. **Bug 3 (server.py)**: `sync_readiness_to_status` only ran once at startup — no periodic scheduler to catch docs that fall through cracks.
**Fixes applied**:
- Fixed `evaluate_and_persist(doc_id)` calls in gap closer (line 7770) and PO retry (line 7983) — now correctly pass `doc["id"]`
- Added Rule 21 (reverted auto_cleared docs) and Rule 22 (readiness-status mismatch) to `sync_readiness_to_status`
- Added periodic sync scheduler (every 30 minutes) alongside the existing startup-only sync

## Bugfix: AI Learning Dashboard Issues (2026-04-10)
1. **Vendor Maturity showing `/100` with no score**: `get_deep_learning_summary()` returned raw DB documents with `composite_score` field, but frontend expected `score`. Fixed by mapping field in summary response.
2. **$0/blank learning events**: Added composite filter to exclude events with no amount AND no line_count AND no items_used. Extended startup cleanup to delete ghost events from DB.
3. **Stuck "Needs Review" docs (server.py)**: Fixed `evaluate_and_persist()` call bugs in gap closer (line 7770) and PO retry (line 7983) schedulers — were passing full dict instead of `doc["id"]`. Added Rule 21/22 to `sync_readiness_to_status` and periodic 30-min sync scheduler.

## UX Simplification: One Button to Rule Them All (2026-04-10)
**Problem**: Too many manual buttons (Run All Learning, Re-evaluate All, Auto-Approve, Force Cleanup, Retry Failed, Backfill All 7, Self-Correct, Score Vendors, Recalibrate, Backfill History) — user didn't know which to press or when.
**Fix**:
- Created unified `POST /api/posting-patterns/system/run-full-cycle` endpoint running 7 steps in correct order: cleanup → intelligence backfill → readiness re-eval → auto-approve → recalibrate → learning pulse → deep learning
- Monitor page: single "Run Full Cycle" button with step-by-step result display
- AI Learning page: all individual buttons hidden behind `<details>` "Advanced Operations" toggles
- Background schedulers handle everything automatically; button is only for "I want it NOW"

## Bugfix: "0 Posted to BC" Field Name Mismatch (2026-04-10)
Posting code wrote `bc_purchase_invoice.bc_record_no` and `bc_record_no`, but dashboard counted `bc_purchase_invoice_no` (never written). Fixed all 3 write paths + added startup backfill migration.

## Bugfix: Automation Health 49% → 67%+ (2026-04-10)
Vendor maturity level names (`mastered/proficient`) didn't match what monitor expected (`stable/autonomous`). Fixed mapping in MonitoringDashboard.js. Also softened validation gaps formula (threshold 50 instead of 20).

## Freight Gaps Closed — Meghan Alignment (2026-04-10)
Three gaps from Meghan's controller rules now implemented:

**Gap 1: PO Notes → SO for Rerouted (001) Orders**
- `extract_so_from_document_text()` scans extracted fields, notes, remarks, `_po_all_candidates` for 6-digit SO refs
- `find_so_for_rerouted_po()` in BC cache service provides fallback via base-number matching
- If no SO found → flags `rerouted_missing_so` for manual review

**Gap 2: Inbound Freight Cost Box Comparison**
- `lookup_po_freight_details()` queries BC PO lines for freight item codes (FREIGHT, DETENTION, DRAYAGE, CUSTOMS, TARIFF, WHSEFRT)
- `compare_freight_to_bc_reference()` compares invoice vs PO freight total with $100 threshold
- Persisted as `freight_comparison` in freight GL classification

**Gap 3: Additional Charges via SO**
- `lookup_so_freight_lines()` queries BC SO lines for freight codes
- When invoice exceeds PO freight, checks if SO freight covers the gap (approved additional charges)
- If SO covers → severity=low, reason explains additional charges approved
- Also validates PI freight codes match SO codes (Meghan: "The codes should match the Sales Order")

Files modified: `freight_business_rules.py`, `freight_gl_routing_service.py`, `bc_reference_cache_service.py`

## Validation Gap Auto-Fixer (2026-04-11)
**Problem**: 45 documents stuck with blocking validation gaps (23 PO validation, 18 vendor match) preventing auto-filing. Specifically:
- TUMALOC vendor sends non-standard PO formats (`001307`, `19326`, `SI-02-26-31777`) that consistently fail BC PO validation
- "SC Warehouses, LLC" and similar vendors have no alias mapping to their BC counterpart

**Fix — 3 New Gap Closers**:

**GAP CLOSER 8: PO Validation Learning**
- `learn_vendor_po_validation_rate()` in `gap_closer_service.py` analyzes per-vendor PO resolution history
- If >70% failure rate with >=3 docs, auto-sets `vendor_invoice_profiles.po_expected = false`
- Integrated into `evaluate_and_persist()` — when PO is unresolved, checks/learns vendor's PO pattern
- Once learned, `compute_signals()` sets `po_not_required_by_vendor = True`, skipping BC PO check

**GAP CLOSER 9: Vendor Auto-Resolution**
- `auto_resolve_unmatched_vendor()` in `gap_closer_service.py` uses 4 strategies:
  1. Exact normalized alias match
  2. Fuzzy match against `vendor_invoice_profiles` (name + variants + BC card)
  3. Word-level + abbreviation matching (e.g., "Warehouses" → "WAREHOU")
  4. Auto-creates vendor alias for future matching
- Integrated into `evaluate_and_persist()` — for docs with `vendor_unresolved` blocker

**Batch Orchestrator: `fix_all_validation_gaps()`**
- Step 1: PO Learning — finds vendors with chronic PO failures, auto-learns profiles
- Step 2: Vendor Resolution — fuzzy-matches all unresolved vendor docs
- Step 3: Re-evaluates all gap-blocked docs to clear them through the pipeline
- Exposed as `POST /api/readiness/fix-validation-gaps`
- Also integrated as Step 2.5 in Run Full Cycle

## Comprehensive Inbox Cleanup (2026-04-11)
**Problem**: 267 documents stuck in "Needs Review" across multiple categories:
- ~120+ TUMALOC AP Invoices with non-standard PO formats
- ~30+ CARGOMO Shipping/AP docs
- ~12 ROTONDO Shipping/Warehouse docs
- ~10 XPOLOGI Account Statement splits
- Various junk, statement, remittance, and unmatched vendor docs

**Fixes Applied**:

1. **Run Full Cycle upgraded to 9 steps** (was 7→8→9):
   - Step 8: Final Cleanup — runs force_cleanup AFTER readiness re-evaluation to sync all newly-ready docs

2. **Force Cleanup Rules 23-25** added to `readiness.py`:
   - Rule 23: PO-relaxed vendor — auto-clears docs from vendors whose `po_expected=false` was learned
   - Rule 24: Shipping supporting docs — catches packing lists, commercial invoices, entry summaries, BOLs misclassified as AP
   - Rule 25: Broadest catchall — NeedsReview docs with NO blocking reasons + vendor resolved → auto-clear

3. **Enhanced PO Learning** (`gap_closer_service.py`):
   - Now counts ALL docs for a vendor (not just those with po_resolution attempted)
   - Also detects docs where PO was never extracted (skipped/no_po_extracted)
   - More aggressive vendor discovery: searches both po_resolution failures AND readiness.warning_reasons=po_missing

Files modified: `gap_closer_service.py`, `readiness.py`, `posting_patterns.py`
Test reports: `test_reports/iteration_203.json` (25/25), `test_reports/iteration_204.json` (24/24)

## Decision Explainer Service (2026-04-12)
- `GET /api/documents/{document_id}/explain` — plain-English explanation of document workflow state
- Service: `services/decision_explainer_service.py` — uses LLM router abstraction with `gemini-2.0-flash` default
- Route: `routers/explain.py` — JWT-protected, read-only, returns ExplainerResult JSON
- Returns: explanation, blocking_reason, next_action, model_used, generated_at, error (if any)
- Graceful error handling: missing LLM key, parse failures, import errors all return HTTP 200 with error in payload

## LLM Provider Abstraction Layer (2026-04-12)
- `services/providers/base_provider.py` — `BaseLLMProvider` ABC with `complete()` method + `LLMProviderError`
- `services/providers/emergent_provider.py` — `EmergentProvider` wrapping existing `emergentintegrations` LlmChat
- `services/providers/ollama_provider.py` — `OllamaProvider` using httpx to call Ollama `/api/chat`
- `services/llm_router.py` — `get_provider(task)` routes to correct provider per env var
- Env vars: `LLM_CLASSIFICATION_PROVIDER`, `LLM_EXTRACTION_PROVIDER`, `LLM_EXPLANATION_PROVIDER` (all default: `emergent`), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`
- `decision_explainer_service.py` migrated to use `get_provider("explanation")` — existing behavior unchanged
- ai_classifier.py and invoice_extractor.py NOT yet migrated (future task)

## Side-by-Side Extraction Comparison Endpoint (2026-04-12)
- `POST /api/dev/compare-extraction` — runs invoice extraction against baseline (emergent/gemini-2.0-flash) and candidate provider in parallel
- Route: `routers/dev_tools.py` — JWT-protected, read-only, never writes to DB
- Uses vision-based extraction (FileContentWithMimeType) for Emergent providers, text fallback for Ollama
- Returns structured diff: fields_agreed, fields_disagreed, fields_missing_in_candidate/baseline, confidence_delta
- Diff compares: invoice_number, invoice_date, due_date, vendor_name, po_number, total_amount, tax_amount, currency

## Vendor Resolution Ranking Assist (2026-04-12)
- Service: `services/vendor_resolution_assist_service.py` — LLM-assisted vendor candidate ranking when fuzzy matching is uncertain
- `rank_vendor_candidates(vendor_raw, candidates, document_context)` → `VendorRankingResult`
- Uses `get_provider("classification")` slot for disambiguation
- Safety: rejects model selection not in candidate list, caps at 10 candidates, skips LLM for trivial single-candidate case
- Test endpoint: `POST /api/dev/test-vendor-ranking` in `routers/dev_tools.py`
- NOT wired into live ingestion pipeline yet

## LLM Vendor Ranking — Live Pipeline Integration (2026-04-12)
- Wired `rank_vendor_candidates()` into both ingestion paths in `server.py` (`_internal_intake_document` + `intake_document`)
- Feature flag: `ENABLE_LLM_VENDOR_RANKING=false` (default OFF — must be explicitly enabled)
- Threshold: `VENDOR_RANKING_CONFIDENCE_THRESHOLD=0.80` (env-configurable)
- Decision gate: skips LLM for high-confidence methods (alias, exact_name, bc_search); activates only for uncertain/no-match cases
- On success: updates vendor_canonical/vendor_match_method, appends `llm_vendor_ranking_applied` to workflow_events
- On failure/low-confidence: logs, preserves original resolution unchanged
- Full audit: `llm_vendor_ranking` dict always persisted on document when ranking attempted
- Also created `vendor_resolution_service.py` (renamed from `vendor_resolution_assist_service.py` per user note)

## Daily Random Trace System (2026-04-12)
- Background scheduler runs 15 random invoice traces every 24 hours (also runs 2 min after startup)
- Picks random vendors from `vendor_invoice_profiles` (604 vendors), fetches real invoices from BC Production
- Compares human-posted lines vs AI template lines, stores results in `daily_trace_results` collection
- Endpoints: `POST /api/posting-patterns/daily-trace/run` (manual trigger), `GET /api/posting-patterns/daily-trace/latest`, `GET /api/posting-patterns/daily-trace/results`
- Frontend: "Daily Trace Feed" card on Invoice Trace page with summary stats, clickable vendor rows, "Run Now" button
- Configurable: `DAILY_TRACE_COUNT=15` (env var)

## Daily Trace Trend Tracking (2026-04-12)
- `GET /api/posting-patterns/daily-trace/trend?days=30` — returns historical avg match rates + vendor leaderboard
- Frontend: SVG sparkline chart showing match rate trend over time, vendor performance leaderboard (collapsible)
- Trend auto-populates as daily runs accumulate; sparkline appears after 2+ data points

## Daily Trace — PROD PI Comparison (2026-04-12)
- Rewrote `_run_daily_traces` to fetch recent PIs from BC Production (last 3 months via `invoiceDate ge` filter)
- Scans up to 500 PROD PIs across all vendors, filters to those with vendor profiles, randomly samples 10-20
- Each trace compares PROD human-posted lines vs AI template simulation
- Results include `has_template` flag, `prod_invoices_scanned`, `cutoff_date`, `status` per invoice
- Frontend shows "PROD vs AI Template (last 3 months)" label and template indicator badge per row

## Template Value Injection Service (2026-04-12)
- Service: `services/template_value_injector.py` — merges template structure with live extracted values
- `inject_extracted_values(template_lines, extraction_result, vendor_id, document_context)` → `InjectionResult`
- Injection rules: amounts from extraction (multi-line preserves template ratios), descriptions via ref injection (LLM or extracted PO/BOL), GL/tax/UOM/line_type always from template
- Full audit_trail per line per field showing source ("extracted" or "template")
- Test endpoint: `POST /api/dev/test-template-injection` in dev_tools.py
- NOT wired into live draft creation yet

## Template Injection — Live Pipeline Integration (2026-04-12)
- Wired `inject_extracted_values()` into `_build_pi_lines_with_mapping` in `gpi_integration.py`
- Feature flag: `ENABLE_TEMPLATE_INJECTION=false` (default OFF)
- Threshold: `TEMPLATE_INJECTION_CONFIDENCE_THRESHOLD=0.70` (env-configurable, lower than vendor ranking)
- Injection runs after template line selection, before BC API call
- On success: replaces bc_lines with injected lines, stores full audit trail as `template_injection`, appends `template_injection_applied` to workflow_events
- On failure/low-confidence: logs, uses original lines, still stores audit trail
- Both auto-draft and manual PI creation paths covered (single injection point in `_build_pi_lines_with_mapping`)

## Sales Order Learning Foundation (2026-04-13)
- Service: `services/sales_order_learning_service.py` — reads BC sales orders, builds customer posting profiles
- Collection: `customer_posting_profiles` (one doc per customer_no) + `sales_posting_learning_events` + `sales_learning_jobs`
- Functions: `build_all_customer_posting_profiles()` (bulk BC backfill), `analyze_customer_ordering_patterns()` (per-customer), `learn_from_sales_order_posting()` (incremental), `detect_posted_sales_drafts()` (feedback loop)
- Wired into `run_all_learning_engines()` in continuous_learning_service.py
- Admin endpoints: `POST /api/admin/sales-learning/backfill-bc-orders`, `GET /api/admin/sales-learning/customer-profiles`, `POST /api/admin/sales-learning/detect-posted-drafts`
- Profile includes: common_items, common_uoms, po_number_pattern, typical_order_value, amount_range, typical_ship_to, days_to_ship_p50, line_count_distribution
- NOT wired into SO draft creation yet

## Sales Order Readiness Reviewer (2026-04-13)
- Service: `services/sales_order_readiness_reviewer.py` — LLM-assisted advisory layer for SO readiness
- Uses `get_provider("classification")` from LLM router — no hardcoded provider logic
- Returns structured JSON: readiness_status (ready/needs_review/suspicious/incomplete), confidence, summary, blocking_issues, warnings, unusual_patterns, profile_matches, recommended_next_step
- Evaluates: item familiarity, UOM consistency, order value range, PO format, ship-to, line count vs customer history
- Full observability: model_used, latency_ms, schema_valid, retry_count, customer_profile_id/version
- Integration: runs advisory-only in sales workflow (server.py line ~2279), stores result as `so_readiness_review` on document
- Test endpoint: `POST /api/dev/test-so-readiness` in dev_tools.py
- NEVER changes posting decisions — recommendation mode only

## Sales Order Readiness Evaluator (2026-04-13)
- Service: `services/sales_order_readiness_evaluator.py` — batch evaluation harness for readiness reviewer
- `run_batch_evaluation(db, limit)` — loads historical sales docs, runs reviewer, compares against known outcomes, stores results
- Collections: `so_readiness_evaluations` (run summaries), `so_readiness_eval_details` (per-doc results)
- Per-doc detail: doc_id, customer, readiness_status, confidence, profile/blocking/warning/pattern counts, model_used, latency_ms, schema_valid, known_outcomes
- Summary metrics: status distribution, avg confidence, avg latency, no-profile %, posted-cleanly %, top recurring warnings, top unusual patterns
- Admin endpoints: `POST /api/admin/sales-learning/evaluate-readiness` (sync or background), `GET /api/admin/sales-learning/readiness-evaluations`, `GET /api/admin/sales-learning/readiness-evaluations/{run_id}`
- Evaluation only — never changes workflow or posting decisions

## Sales Order Decision Explainer (2026-04-13)
- Service: `services/sales_order_decision_explainer.py` — plain-English explanation layer for SO readiness
- Endpoint: `GET /api/documents/{document_id}/sales-order-explainer` (JWT-protected, on existing explain router)
- Prefers explaining existing `so_readiness_review` data (`review_reused: true`) — no unnecessary LLM calls
- Falls back to deterministic signals from validation_results and document state when no review exists
- Output: headline, plain_english_summary, why_it_was_flagged, what_looks_normal, what_needs_attention, recommended_next_steps, reviewer_confidence, readiness_status
- Logging: doc_id, review_reused, latency_ms, readiness_status, confidence
- Explanation only — never alters posting decisions or routing

## Sales Order Reviewer Feedback (2026-04-13)
- Service: `services/sales_order_reviewer_feedback_service.py` — captures human feedback on advisory reviews
- Collection: `so_reviewer_feedback` (structured, queryable by customer/assessment/model/reviewer)
- Endpoints: `POST /api/documents/{id}/sales-order-review-feedback`, `GET /api/documents/{id}/sales-order-review-feedback`
- Payload: reviewer_assessment (5 values), final_human_decision, disagreed_fields, notes, auto-captured reviewer_user_id from JWT
- Snapshots linked_review (readiness_status, confidence, model, profile_id/version) at feedback time
- Also stores `so_review_feedback_latest` summary on document for quick display
- Frontend: `SOReviewFeedbackPanel` component added to DocumentDetailPage — expandable panel with explainer + feedback form (assessment buttons, decision override, disagreed fields, notes)
- Feedback capture only — never changes posting, routing, or validation

## Sales Order Feedback Analytics (2026-04-13)
- Service: `services/sales_order_feedback_analytics_service.py` — MongoDB aggregation pipelines for reviewer feedback analysis
- Admin endpoints:
  - `GET /api/admin/sales-learning/reviewer-feedback-summary` — rates, distributions, confidence by assessment, by model/customer/reviewer, top disagreed fields + combos
  - `GET /api/admin/sales-learning/reviewer-feedback-details` — paginated individual records
  - `GET /api/admin/sales-learning/reviewer-feedback-by-customer` — per-customer breakdown
- Full filter support: date_from/to, customer_no, reviewer, model, readiness_status, assessment, decision
- Analytics only — never changes workflow or decisions

## Unified SO Advisory Panel (2026-04-13)
- Consolidated backend endpoint: `GET /api/documents/{id}/sales-order-advisory` — single call returns explainer + review + customer profile + feedback
- Frontend: Rewrote `SOReviewFeedbackPanel` as unified panel — compact, collapsible, shows full advisory story:
  - Status badge + confidence in header (collapsed view: headline only)
  - Expanded: summary, 4-stat row (blocking/warnings/unusual/matches), detail sections with icons, customer profile context, next steps
  - Feedback section: shows existing feedback or inline form (assessment, decision, disagreed fields, notes)
  - Loading/empty/no-review/no-profile states all handled
- Reuses all existing services — no changes to underlying logic

## Sales Order Disagreement Diagnostics (2026-04-13)
- Service: `services/sales_order_disagreement_diagnostics_service.py` — root-cause classification of reviewer disagreements
- Classifies disagreements into 10 root-cause categories: no_customer_profile, profile_too_sparse, order_value_range_too_strict, ship_to_sensitivity_too_high, item_uom_sensitivity_too_high, upstream_extraction_weakness, confidence_overestimation, prompt_wording_issue, new_customer_low_history, other_unknown
- Outputs: root-cause distribution, per-customer/per-model hotspots, disagreement rate by advisory confidence band, disagreed_field-to-cause mapping, example documents per cause
- Admin endpoints: `GET /api/admin/sales-learning/disagreement-diagnostics` (full filters), `GET .../examples?root_cause=X`
- Diagnostics only — never changes workflow or advisory logic

## Sales Order Confidence Calibration (2026-04-13)
- Service: `services/sales_order_confidence_calibration_service.py` — heuristic calibration layer
- Penalties: no_profile (-20%), weak_profile (-10%), per_warning (-5%), per_unusual (-7%), per_blocker (-15%), new_customer (-15%), overconfidence_history (-12%)
- Preserves raw_confidence, adds calibrated_confidence + confidence_band + calibration_reasons + penalties_applied
- Integrated into `sales-order-advisory` consolidated endpoint (on-demand calibration)
- Admin endpoints: `POST /calibrate-confidence` (batch), `GET /calibration-comparison` (raw vs calibrated bands), `POST /calibrate-document/{id}` (single)
- Frontend: unified panel shows calibrated confidence with "cal" indicator, expanded view shows raw→calibrated with reasons
- Advisory/display only — never changes routing or posting decisions

## Low-History Profile Handling Improvements (2026-04-13)
- Reviewer: profile-state-aware prompts (none/weak/medium/strong) — reduces over-assertive anomaly language
  - No profile: caps confidence at 0.60, avoids speculative anomalies, uses "limited comparison basis" phrasing
  - Weak profile: caps confidence at 0.70, phrases deviations as "differs from limited sample"
  - Medium: flags deviations as "worth verifying"
  - Strong: full comparison (existing behavior)
- Added `profile_state` field to ReadinessReviewResult and advisory endpoint response
- Explainer: adjusted headlines ("Limited customer history — manual review recommended"), attention items, and next steps for low-history cases
- Frontend: "No History" / "Limited History" badge in advisory panel header for low-history documents
- All existing schemas backward-compatible (profile_state is additive)

## Ship-To Sensitivity Tuning (2026-04-13)
- New service: `services/ship_to_analysis_service.py` — normalization + context-aware comparison
- Match types: exact | normalized_match | known_alternate | plausible_new | unknown_new
- Severity levels: none | low | medium | high — determined by profile strength + other signal context
- Normalization handles: casing, whitespace, punctuation, abbreviations (st/ave/blvd/whse/dist/etc.)
- Integrated pre-LLM: analysis runs before prompt, injected as structured context with explicit instructions to LLM
- Results stored on review as `ship_to_analysis` (match_type, severity, context_notes, known_locations)
- Frontend advisory endpoint includes ship_to_analysis in response

## Item/UOM Sensitivity Tuning (2026-04-13)
- New service: `services/item_uom_analysis_service.py` — pre-LLM item and UOM normalization + comparison
- Item match types: exact | normalized | known_alternate | new_plausible | unknown
- UOM match: exact | alias_match | known_alternate | unknown — with 14 canonical UOM groups (ea/cs/pk/bx/pl/ct/lb/kg etc.)
- Severity: context-aware (profile strength × other signals × count of unknown lines)
- Normalization: casing, punctuation, spacing, UOM alias resolution (case=cs, each=ea, pallet=pl, etc.)
- Integrated pre-LLM with explicit instructions: "Do NOT flag items as unusual" when severity=none
- Results stored on review as `item_uom_analysis` and included in advisory endpoint

## Explanation Wording Refinement (2026-04-13)
- Rewrote `sales_order_decision_explainer.py` with evidence-calibrated tone system
- 6 tone categories: direct (blockers), confident (ready), cautious (low-history), concerned (strong anomaly), attentive (moderate deviation), neutral (default)
- Headline, summary, flagged items, attention items, and steps now consistent per tone — no mixed signals
- Uses structured pre-analysis (ship_to severity, item_uom severity, profile state, calibrated confidence) to determine wording strength
- Low-evidence patterns qualified with "minor:" prefix; no-profile cases get "limited comparison basis" language
- Added `explanation_tone` field to SOExplanation output for observability

## Post-Tuning Calibration & Impact Review (2026-04-13)
- Service: `services/sales_order_post_tuning_review_service.py` — comprehensive post-tuning impact analysis
- Outputs: agreement rates, disagreement root-cause distribution, raw vs calibrated confidence band agreement, profile-state outcomes, ship-to/item-UOM disagreement counts, explanation-tone distribution, tuning impact signals, calibration weight assessment
- Calibration assessment: checks monotonicity of agreement across confidence bands, recommends penalty adjustments if warranted
- Tuning impact signals: per-area assessment (ship_to, item_uom, no_profile, wording) with positive/needs_monitoring verdict
- Detail endpoint: individual records enriched with profile_state, ship_to_severity, item_uom_severity, calibrated_confidence
- Admin endpoints: `GET /post-tuning-review`, `GET /post-tuning-review/details` — full filter support
- Analysis only — never changes workflow, weights, or prompts

## Strong-Profile Behavior Tuning (2026-04-13)
- Ship-to: strong profile with 3+ known locations + normal signals → severity downgraded from medium to low ("likely normal expansion")
- Ship-to: strong profile where everything else matches → severity downgraded from medium to low ("all other signals match")
- Ship-to: only escalates to medium when combined with other atypical signals
- Item/UOM: considers profile item diversity (6+ items = diverse); unknown item with diverse profile + normal signals → low not medium
- Item/UOM: majority rules — if >75% of lines are clean, caps overall severity one level lower
- Item/UOM: unknown item with all-normal signals → low ("not previously seen — other signals match established pattern")
- Reviewer LLM prompt: strong-profile instruction explicitly states "mature customers naturally evolve" and "one new item/destination is routine expansion"
- All structured outputs backward-compatible

## Strong-Profile Validation Review (2026-04-13)
- Service: `services/sales_order_strong_profile_review_service.py` — pre vs post tuning comparison for strong-profile cases
- Compares: agreement rate, disagreement drivers, ship-to/item-UOM frequency, confidence behavior, status distribution
- Customer-level breakdown: per-customer agreement + disagreement drivers
- Examples: improved cases (agreement rose) + still-problematic cases (with severity context)
- Verdict engine: positive/marginally_positive/neutral/needs_investigation with specific recommendations
- Admin endpoints: `GET /strong-profile-review`, `GET /strong-profile-review/details` — full filter support
- Analysis only — never changes workflow, weights, or prompts

## Bug Fix: Auto-Split Unknown Children Silently Exported (2026-04-19 — P0)
- **Root cause**: `auto_clear_service.evaluate_auto_clear()` had `confidence_threshold=0.0` with no `require_minimum_extraction` for `Unknown` / `Other` / `DEFAULT` doc_types. Auto-split child PDFs (e.g., `..._p11.pdf`) that the AI re-classified as `Unknown` with 0.00 confidence and zero extracted fields trivially satisfied the one confidence check (0.0 ≥ 0.0) → "All 1 checks passed" → exported/completed, bypassing manual review.
- **Fixes**:
  1. `services/auto_clear_service.py` — early guard rejects `Unknown`/`Unknown_Document`/`Unknown_Sales`/`Other`/empty/`DEFAULT` doc_types when `confidence < 0.70` OR meaningful fields < 2. Returns `NEEDS_REVIEW` with `unclassified_guard_triggered=True`.
  2. `services/batch_po_splitter.py` — new `_inherit_parent_and_reevaluate` helper: when a split child returns Unknown/low-confidence, inherits parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical` onto the child, preserves original AI values under `*_from_split_ai` for audit, and forces `status=NeedsReview`.
  3. `routers/auto_clear.py` — repaired missing import block (`evaluate_auto_clear`, `get_auto_clear_config`, `update_threshold`, etc.) that had been causing 500 on `/api/auto-clear/evaluate/{id}`, `/config`, `/config/threshold`. Discovered by testing agent iter_224.
- **KPI Fix (same iteration)**: `routers/dashboard.py` — `posted_to_bc_7d` query was too strict (required literal `status == "Posted"` AND `posted_to_bc_at` timestamp). Now matches any of `bc_purchase_invoice_no`/`bc_record_no`/`bc_document_no`/`bc_record_id` present WITH any of `posted_to_bc_at`/`bc_posted_at`/`posted_at`/`updated_utc` within 7 days. `ready_for_post` query's self-contradictory filter (`status=="ReadyForPost"` AND `status $nin ["Posted","Completed","Archived"]`) simplified.
- **CI Gate**: `.github/workflows/phase-b-gate.yml` drafted — enforces Phase B observer + unknown-guard tests and blocks new external callers of `_update_standard_workflow_status` ahead of Phase B extraction.
- **Tests**: `tests/test_auto_clear_unknown_guard.py` (8/8 pass), `tests/test_iter224_unknown_guard_http.py` (10/10 HTTP regression, added by testing agent), full suite 50/50 green (iteration_224.json).

## Pattern Health Implicit-Trust + Confidence Calibration Tightening (2026-04-19 — v2.5.3)
- **Observed on prod dashboard**: `Pattern Health — AP` showed `Trusted=3 / Drifting=216` despite 97.5% auto-rate + zero recent negative feedback for the majority of those 216 vendors. Also: `Confidence Calibration` 85–95% band at 91% accuracy vs 70–85% at 98% and 95–100% at 99% — the AI was over-confident specifically in the 85–95% window.
- **Fix A — Implicit Trust (`services/learning_core/pattern_health_service.py`)**: `_ap_health()` now uses implicit-success signals. New `_fetch_ap_negative_events_by_vendor()` aggregates `learning_events_v2` (domain=ap_posting, types in `{draft_bc_feedback, draft_rejected, pattern_rejected, suggestion_rejected, correction_applied, drift_flagged}`) once per call. Classification order: retired → explicit_high_tier → drift_signal → implicit_success (`samples >= AP_IMPLICIT_TRUST_MIN_SAMPLES=10` AND zero negative events in last 30 days) → medium_tier_still_maturing → unscored. Every `per_scope` row now carries `trust_reason` + `negative_events_30d` for transparency.
- **Fix B — Calibration Curve (`services/per_document_learning_service.py`)**: `compute_effective_confidence()` curve tightened. Old curve: scale=1.0 at completeness>=0.50 (no penalty). New piecewise curve: full pass at >=0.75, mild penalty (scale~0.88) at 0.50, moderate (scale~0.67) at 0.25, heavy (scale~0.35) at 0.00. A 90%-confident doc with only 2 of 4 core fields now calibrates to ~79% and shifts from the 85–95% band into the 70–85% band where manual review catches it. Monotonicity preserved (test_curve_is_monotonic).
- **Tests**: `tests/test_pattern_health_implicit_trust.py` (8/8) + `tests/test_confidence_calibration_curve.py` (10/10) + `tests/test_pattern_health_core.py` updated to assert new semantics. Full 32/32 unit tests + 6/6 HTTP endpoints green (iteration_225.json).

## Drift Watchlist Weekly Notification (2026-04-19 — v2.5.4)
- **Purpose**: Turn the passive Pattern Health dashboard into an actionable weekly alert. Aggregates vendors with corrective events in the last 30 days (`learning_events_v2` negative event types) OR open rows in `learning_drift_alerts`, ranks by score (`2 × open_alerts + negative_events_30d`), and dispatches.
- **Service** (`services/learning_core/drift_watchlist_service.py`): `build_watchlist` (one aggregation + one find + one enrichment query — no N+1), `format_teams_card` (Adaptive Card with 15-vendor cap + "+N more" footer), `format_email_html` (HTML table with clickable vendor deep-links via `APP_PUBLIC_URL`), `send_watchlist` (per-channel dispatcher with failure isolation — one failing channel never kills siblings).
- **Channels** (via `DRIFT_WATCHLIST_CHANNELS` comma-separated env — any combination):
  - `teams_webhook` → `TEAMS_DRIFT_WEBHOOK_URL`
  - `graph_channel` → MS Graph `/teams/{id}/channels/{id}/messages` using existing `GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` (requires `ChannelMessage.Send`)
  - `email` → MS Graph `/users/{from}/sendMail`
- **Scheduler** (`server.py`): fires weekly, gated by `DRIFT_WATCHLIST_ENABLED=true`, `DRIFT_WATCHLIST_CRON_DOW` (0=Mon), `DRIFT_WATCHLIST_CRON_HOUR` (default 7). Hourly-poll design that sends at most once per target day.
- **Router endpoints** (`routers/learning_core.py`):
  - `GET /api/learning/drift-watchlist/preview` — dry-run, returns `{watchlist, teams_card, email_html}` without sending
  - `POST /api/learning/drift-watchlist/send-now?channels=` — manual dispatch with optional channel override
  - `GET /api/learning/drift-watchlist/runs` — audit history of past dispatches (persisted in `drift_watchlist_runs`)
- **Safety**: empty-watchlist short-circuit (no noise), per-run audit even on skip, `{_id: 0}` projection everywhere.
- **Tests**: `tests/test_drift_watchlist.py` (16/16). Full iteration_226 report: 16 unit + 6 HTTP + 26 regression tests green.

## Unknown-Doc Reclaim Sweep (2026-04-19 — v2.5.5)
- **Purpose**: Counterpart to the v2.5.3 `unclassified_guard`. Sweeps docs that were auto-cleared to Completed/Exported BEFORE the guard existed and kicks them back to NeedsReview so humans can resolve them.
- **Service** (`services/admin/unknown_doc_reclaim_service.py`): `preview` + `run` + `recent_runs`. Filter requires ALL three type fields (`doc_type`, `document_type`, `suggested_job_type`) to be in the unknown set (`$and` — fixed an initial `$or` bug where missing-field defaulted to None/Unknown and caused false positives on real AP_Invoice docs).
- **Safety**: hard guard against any BC-write evidence (`bc_purchase_invoice_no`, `bc_record_no`, `bc_document_no`, `bc_record_id`). Idempotent via `reclaim_to_needs_review_at` timestamp. Dry-run default.
- **Audit**: preserves `auto_cleared=True` / `auto_cleared_at` history, appends workflow_history event, persists per-run summary to `unknown_doc_reclaim_runs`.
- **Endpoints** (`routers/admin.py`):
  - `GET /api/admin/unknown-doc-reclaim/preview?limit=` — counts + sample + breakdown (how many from batch-split, by doc_type)
  - `POST /api/admin/unknown-doc-reclaim/run?execute=false&limit=&actor=` — dry-run by default; `execute=true` required to mutate; optional `limit` for staged rollout
  - `GET /api/admin/unknown-doc-reclaim/runs?limit=` — audit history
- **Tests**: `tests/test_unknown_doc_reclaim.py` (9/9 via mongomock-motor). Full iteration_227: 48/48 green. Live preview DB verified end-to-end (1 real candidate found and reclaimed).
- **Deps**: added `mongomock-motor==0.0.36` to test stack.

## Unknown-Doc Reclaim — Smart + Skip-Noise Modes (2026-04-19 — v2.5.6)
- **Purpose**: Dramatically reduce the review-queue load before the user runs the full 372-doc sweep. Sampling showed 62% batch-split children (whose parents ARE classified) and 40%+ `OTHER` doc-type garbage, plus a cluster of email-sprite noise (`linkedin_*.png`, `cmn_*.png`, `image.png`).
- **New flags** (opt-in, both default False for backward compat):
  - `smart=true` — batch-split children whose parent is classified inherit parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical` before routing to NeedsReview. Original child `doc_type` preserved under `doc_type_from_reclaim_ai`. `parent_inheritance_applied=true` flag set. Reviewer sees enriched context instead of bare "Unknown".
  - `skip_noise=true` — filenames matching 15 regex patterns (email sprites, signatures, tracking pixels, `image*.png`, `logo.svg`) get marked `noise_filtered=true`, `queue_visible=false`, and KEPT OUT of NeedsReview entirely. `reclaim_to_needs_review_at` is still stamped for idempotency.
- **Precedence**: noise wins over smart (an email sprite with a classified parent is still noise).
- **Shape changes**: response now has `reclaimed_plain_count` / `reclaimed_inherited_count` / `filtered_noise_count` / `total_mutated`. Legacy `reclaimed_count = plain + inherited` (noise separate) for back-compat.
- **Preview extension**: `smart_inheritable` + `filtered_as_noise` counters in `sample_breakdown` (returns null when flag is off — distinguishes "feature disabled" from "zero").
- **Endpoints** (`routers/admin.py`) now accept `smart` + `skip_noise` query params on both `/preview` and `/run`.
- **Tests**: `tests/test_unknown_doc_reclaim_smart.py` (11) + `tests/test_unknown_doc_reclaim.py` (9) = 20/20 unit. Full iteration_228: 38/38 (20 unit + 18 HTTP). Verified NOISE_FILENAME_PATTERNS do NOT match real doc filenames (W117505.pdf, MARCH 2026 ACTIVITY.pdf, 0303382.pdf etc).

## Retroactive Post-Process Sweep (2026-04-19 — v2.5.7)
- **Purpose**: Fix the prod situation where operator ran v2.5.5 plain reclaim on 372 docs BEFORE v2.5.6 (smart + skip_noise) shipped. Those docs went to NeedsReview without parent-inheritance enrichment and with email-sprite noise still in the queue. This sweep retroactively applies the two modes.
- **Service** (`services/admin/unknown_doc_reclaim_service.py`): `_build_post_process_filter` + `post_process` + `recent_post_process_runs`. Filter scopes to docs with `reclaim_to_needs_review_at` set AND `post_process_applied_at` unset AND still queue-visible AND no BC evidence.
- **Three paths per doc** (evaluated in order):
  1. `skip_noise` + filename matches noise → revert OUT of NeedsReview (`status=Completed`, `queue_visible=false`, `noise_filtered=true`)
  2. `smart` + batch_parent_id + classified parent + no prior inheritance → inherit parent's `doc_type` + `vendor_canonical` + `vendor_id` + `customer_canonical`; stays in NeedsReview but enriched
  3. Otherwise → stamp-only (`post_process_applied_at` set; prevents re-picks)
- **Audit**: `unknown_doc_reclaim_post_process_runs` collection + `workflow_history` events (`post_process_noise_filtered`, `post_process_parent_inheritance`).
- **Endpoints** (`routers/admin.py`):
  - `POST /api/admin/unknown-doc-reclaim/post-process?execute=&smart=&skip_noise=&limit=&actor=`
  - `GET  /api/admin/unknown-doc-reclaim/post-process/runs`
- **Tests**: `tests/test_unknown_doc_reclaim_post_process.py` (11 tests). iteration_229: 43/43 (30 unit + 13 HTTP), zero bugs.

## Filename Heuristics Classifier (2026-04-19 — v2.5.8)
- **Purpose**: Pattern-based fallback classifier targeting the ~335 "stamp-only" docs left in NeedsReview after the v2.5.7 post-process sweep — docs the standalone page-level AI couldn't type but whose filename + vendor clearly signals the type.
- **Service** (`services/admin/filename_heuristics_service.py`): 12 rules derived from real prod samples (TUMALOC freight, CARGOMO invoices, Valley Distributing receiving reports, Brown monthly statements, Progressive Logistics rebills, Crown/Apex outbound, GROUPWA W-prefix, GAMMIN AR, Lone Star numeric, SMC Scan-WA, etc.). Every rule carries an `evidence note` so reviewers see *why* the AI reclassified each doc.
- **Safety**: 
  - Filter requires ALL three type fields in UNKNOWN_DOC_TYPES (never touches known-typed docs)
  - Never touches docs with BC evidence
  - Idempotent via `filename_heuristic_applied_at` sentinel
  - `keep_in_review=True` default — status stays at current (NeedsReview) pending human signoff; heuristic NEVER auto-clears
  - `doc_type_before_heuristic` audit field preserves the original (garbage) doc_type
  - `min_confidence=0.70` default gate (each rule has its own confidence, tunable per call)
- **Endpoints** (`routers/admin.py`):
  - `GET  /api/admin/filename-heuristics/rules`
  - `GET  /api/admin/filename-heuristics/preview`
  - `POST /api/admin/filename-heuristics/apply?execute=&smart=&min_confidence=&limit=&actor=`
  - `GET  /api/admin/filename-heuristics/runs`
- **Tests**: `tests/test_filename_heuristics.py` (34: 15 real-prod-filename matches + 8 false-positive checks + 11 behavioral). Iteration_230: 78/78 (64 unit + 14 HTTP), zero bugs. 15 real prod filenames from the user's iteration_227/229 sample all classified correctly.

## Triage Tools: Unmatched-Sample + Duplicate Scan/Resolve (2026-04-19 — v2.5.9)
- **Context**: v2.5.8 heuristics matched 56 of 417 candidates on prod (13%), leaving 361 unmatched. Also surfaced 12x duplicate ingestion of `GAMMIN_AR_20260316.xls` in a single day — proof of email-poller dedup miss.
- **Service** (`services/admin/triage_tools_service.py`): `filename_shape` (single-pass tokenizer using `#+` for digits + `A+` for letters — fixed an initial bug where `\\d+` replacement got letter-consumed by a second pass), `unmatched_sample`, `duplicate_scan`, `duplicate_resolve`, `recent_duplicate_runs`.
- **Endpoints** (`routers/admin.py`):
  - `GET /api/admin/filename-heuristics/unmatched-sample?limit=&top_n=&min_group_size=` — groups unmatched filenames by (vendor, shape). Includes defensive rescan — docs that `classify_filename` WOULD match are excluded from rule_candidates.
  - `GET /api/admin/duplicate-docs/scan?same_day=&limit=&min_count=` — groups docs by (file_name + vendor_canonical [+ YYYY-MM-DD]) where count ≥ 2. Skips `duplicate_resolved_at`-set docs (idempotent).
  - `POST /api/admin/duplicate-docs/resolve?execute=&keep=oldest|newest&same_day=&actor=` — keeps one per group (oldest or newest), marks rest `duplicate_of=<keeper>`, `status=Completed`, `queue_visible=false`, appends `duplicate_resolved` workflow_history event, persists audit row.
  - `GET /api/admin/duplicate-docs/runs`
- **Safety**: dry-run defaults, idempotent via `duplicate_resolved_at`, keeper never mutated, router guards invalid `keep` values.
- **Tests**: `tests/test_triage_tools.py` (18 tests incl. GAMMIN-12x scenario). Iteration_231: 101/101 (82 regression + 19 HTTP), zero bugs. filename_shape collisions verified symmetric (e.g., ROT12345_p1.pdf ≡ FED99887_p12.pdf).

## Upcoming Tasks
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future/Backlog
- P2: Evergreen multi-PO container allocation spreadsheet integration
- P2: BOL / Tracking No field storage in BC
- P2: Low-volume vendor review routing (<5 docs skip auto-file)
- P2: Activate correction replay engine
- P2: Email sender → vendor mapping
- P3: `server.py` extraction/refactoring (8,500+ lines)

## Inside Sales Pilot — Controlled Ingestion (2026-04-14)
- **Purpose**: Controlled ingest-only pilot for Inside Sales mailboxes — learn from real sales documents without creating operational risk
- **Pilot mailboxes**: `mkoch@gamerpackaging.com`, `nhannover@gamerpackaging.com`, `ASaumweber@gamerpackaging.com`
- **Feature flag**: `INSIDE_SALES_PILOT_ENABLED` (default: `false` — must be explicitly enabled in `.env`)
- **Service**: `services/inside_sales_pilot_service.py` — dedicated polling, relevance filtering, structured extraction, logging
- **Router**: `routers/inside_sales_pilot.py` — full endpoint suite:
  - Core: `GET /status`, `POST /poll-now`, `GET /documents`, `GET /runs`, `GET /logs`, `GET /extraction-review`
  - BC Validation: `POST /validate/{id}`, `POST /validate-all`, `GET /validation-results`
  - Corpus: `POST /validate-sales-corpus`, `GET /corpus-validation-summary`
  - Maintenance: `POST /re-extract-all`, `POST /smart-reclassify`
  - Spiro: `POST /spiro-match/{id}`, `POST /spiro-match-all`, `GET /spiro-results`, `GET /spiro-search`
- **Safety guards (6 layers)**:
  1. `source="inside_sales_pilot"` check in server.py SO auto-create path
  2. `inside_sales_pilot` flag check in `auto_post_service.check_sales_order_eligibility()`
  3. `inside_sales_pilot` flag check in `auto_post_service.check_auto_post_eligibility()`
  4. `auto_create_so_blocked=True` persisted on document
  5. `bc_write_blocked=True` persisted on document
  6. Sales workflow guard — pilot docs stop at `pilot_review` status, never progress to exported/posted
- **Relevance filtering**: keyword + filename matching, noise rejection (certificates, dunnage, signatures, info sheets)
- **Smart PO extraction**: validates AI-extracted POs, rejects garbage (rate, intment, number.), catches real patterns (W117579, WR112624)
- **Smart reclassifier**: auto-tags non-sales docs (certificates→Certificate, dunnage→BOL, reports→Report, etc.)
- **BC Production cross-validation**: read-only customer match, order lookup, item validation, amount range check
- **Sales corpus validation**: batch validation of existing 1000+ sales docs with side-by-side comparison
- **Spiro CRM integration**: company lookup, opportunity/quote matching, PO-to-quote matching
- **Frontend**: Inside Sales Pilot tab on Sales page + Build Roadmap page
- **Config vars**: `INSIDE_SALES_PILOT_ENABLED`, `INSIDE_SALES_PILOT_MAILBOXES`, `INSIDE_SALES_PILOT_INTERVAL_MINUTES`, `INSIDE_SALES_PILOT_LOOKBACK_MINUTES`, `INSIDE_SALES_PILOT_MAX_MESSAGES`
- **Spiro config**: `SPIRO_CLIENT_ID`, `SPIRO_CLIENT_SECRET`, `SPIRO_REFRESH_TOKEN`, `SPIRO_API_BASE`, `SPIRO_OAUTH_URL`
- **Version**: v2.1.0
- **NO BC writes, NO auto-create sales orders, NO downstream automation**

## Sales Order Draft Context Service (2026-04-13)
- Service: `services/sales_order_draft_context_service.py` — profile-based draft assistance
- Endpoint: `GET /api/documents/sales-orders/draft-context/{customer_id}` — JWT-protected
- Returns: ship_to_suggestions (primary + alternates), item_suggestions (core/regular/occasional with per-item UOM alternates), value_context (typical/min/max), common_uoms, po_pattern, guidance messages, profile richness/variability indicators
- No-profile: graceful degradation with "No customer history — draft will use extracted data only"
- Assistive only — never forces values or overrides user data

## Feedback-to-Learning Pipeline (2026-04-13)
- Service: `services/sales_order_feedback_learning_service.py` — converts reviewer feedback into candidate profile-learning suggestions
- Collection: `so_learning_suggestions` — one doc per suggestion with full audit (suggestion_id, type, customer, evidence, confidence, proposed_change, status, fingerprint)
- Suggestion types: add_alternate_ship_to, add_occasional_valid_item, add_alternate_uom_for_item, widen_order_value_tolerance, revise_po_pattern, increase_variability_tolerance
- Status lifecycle: pending → (approved / rejected / applied) — never auto-applied
- Deduplication via fingerprint (customer + type + change key)
- Confidence: evidence-weighted (0.3 base + 0.15 per supporting feedback, capped)
- Insufficient evidence: single-occurrence suggestions stored as "insufficient_evidence"
- Admin endpoints: `POST /generate-learning-suggestions?sync=true`, `GET /learning-suggestions`, `GET /learning-suggestions/{id}`
- Full filter support: customer, type, status, min_confidence, date range
- Suggestion generation only — never mutates profiles

## Learning Suggestion Approval/Apply Workflow (2026-04-13)
- Service: `services/sales_order_learning_suggestion_apply_service.py` — governed approval + apply workflow
- State machine: pending → approved → applied (terminal), pending → rejected, rejected → pending (un-reject)
- Mutation logic per type: add ship-to, add item, add UOM-for-item, widen amount range (±15-20%), relax PO pattern, increase variability (+0.15)
- Duplicate detection: no-op if value already present in profile
- Guard: cannot apply rejected/pending — must be approved first
- Full audit: `so_learning_apply_audit` collection with pre/post snapshots, applier, change summary
- Admin endpoints: `/approve`, `/reject`, `/apply` per suggestion_id
- Never auto-applies — explicit human approval required

## Learning Suggestions Admin UI (2026-04-13)
- Component: `components/LearningSuggestionsPanel.js` — admin governance UI for learning suggestions
- Placed at top of AI Learning Intelligence page (LearningDashboard.js)
- Features: filterable list (status + type), expandable detail rows, approve/reject/apply action buttons
- Detail view: evidence summary, supporting docs count, proposed change, profile snapshot, audit info
- Action guards: only shows valid actions per status (approve/reject for pending, apply/reject for approved, no actions for applied/rejected)
- Loading/empty/error states handled
- Uses existing admin endpoints — no new backend needed

## Learning Apply-Impact Review (2026-04-13)
- Service: `services/sales_order_learning_impact_review_service.py` — pre/post apply outcome comparison
- Compares: agreement rate, disagreement field frequency, root-cause changes per customer and suggestion type
- Outputs: improved/no_change/regressed counts, per-type and per-customer deltas, examples, actionable recommendations
- Recommendation engine: suggests lowering thresholds for high-impact types, flags regressions, notes insufficient data
- Admin endpoints: `GET /learning-impact-review`, `GET /learning-impact-review/details` — full filter support
- Analysis only — never changes thresholds or behavior

## Profile Drift & Change History Controls (2026-04-13)
- Service: `services/sales_order_profile_drift_service.py` — drift detection and change history
- Risk indicators: change cadence (>8/30d), ship-to growth (>8), occasional item growth (>15), variability (>0.90), richness jumps (>25pts)
- Risk classification: low/medium/high based on weighted signal count
- Outputs: per-customer risk assessment, risk distribution, change type breakdown, timeline, current profile metrics
- Admin endpoints: `GET /profile-drift`, `GET /profile-drift/{customer_id}`, `GET /profile-change-history/{customer_id}`
- Full filter support: date range, customer, drift_risk, suggestion_type, applied_by
- Governance/visibility only — never reverts or blocks changes

## Evidence Threshold Tuning (2026-04-13)
- Per-type configurable thresholds via env vars: `LEARN_THRESH_SHIP_TO=1`, `LEARN_THRESH_ITEM=1`
- Only low-risk types relaxable: add_alternate_ship_to, add_occasional_valid_item
- Higher-risk types unchanged: increase_variability, widen_amount, revise_po (default threshold=2-3)
- Drift-aware: high-drift customers automatically use default (conservative) thresholds even for relaxable types
- Suggestions record: threshold_used, relaxed_threshold (bool), drift_risk_at_generation
- All governance preserved: suggestions still require explicit approve + apply

## Rep Overrides Management UI (2026-04-13)
- Component: `components/RepOverridesPanel.js` — full admin CRUD for rep overrides
- Placed in Settings Hub as "Rep Overrides" tab
- Features: list/search/filter overrides, expandable detail, create/edit/disable, type badges
- Override types: rep_assignment, ship_to_exception, item_uom_exception, draft_preference, business_note
- Backend extended: added override_type, reason, notes, expires_at, updated_by fields + filter support
- Overrides remain separate from learned profiles — no silent merging
- Audit: created_utc, updated_utc, updated_by on every change

## Customer Hotspot Review (2026-04-13)
- Service: `services/sales_order_customer_hotspot_review_service.py` — cross-signal friction analysis
- Combines: feedback, disagreement fields, overrides, applied suggestions, audit count, profile richness/confidence
- Hotspot score: weighted (incorrect×3, ship_to×2, item_uom×2, overrides×2, drift audit, low richness bonus)
- Root causes: low_profile_richness, override_dependence, extraction_quality, threshold_tuning_needed, ship_to_friction, item_uom_friction, profile_drift_risk, high_volume_low_learning, monitor_only
- Fix paths: profile_improvement, override_management, extraction_improvement, threshold_tuning, monitor_only
- Detail endpoint: recent feedback + pending suggestions
- Admin endpoints: `GET /customer-hotspots`, `GET /customer-hotspots/{customer_id}` — full filter support
- Analysis only — never changes profiles, overrides, or thresholds

## Maturity Checkpoint & Reusability Review (2026-04-13)
- Service: `services/sales_order_maturity_checkpoint_service.py` — system-wide maturity assessment
- 7 dimensions scored: feedback_volume, agreement_quality, profile_coverage, learning_loop, governance_controls, drift_health, override_governance
- Maturity bands: mature (≥75) / operational (≥50) / developing (<50) → ready_to_reuse / mostly_ready / not_ready
- Component inventory: 13 generic framework components (72.2% reuse ratio), 5 domain-specific
- Next workflow recommendation: AP Invoice Vendor Advisory (fit=0.90, 12 reusable components, effort=low)
- Admin endpoints: `GET /maturity-checkpoint`, `GET /maturity-checkpoint/reusability`
- Assessment only — never triggers expansion

## AP Invoice Vendor Advisory — Phase 1 (2026-04-13)
- Framework reuse from Sales Order advisory pattern (72% component reuse)
- New AP-specific services:
  - `services/ap_invoice_advisory_reviewer.py` — vendor-profile-aware LLM advisory with profile-state prompts
  - `services/ap_invoice_decision_explainer.py` — evidence-calibrated tone system (direct/confident/cautious/concerned/neutral)
  - `services/ap_invoice_feedback_service.py` — feedback capture + basic analytics (reuses generic pattern)
- New router: `routers/ap_advisory.py` — 7 endpoints:
  - `POST /api/ap-advisory/review/{id}` — run advisory
  - `GET /api/ap-advisory/explain/{id}` — explainer
  - `GET /api/ap-advisory/advisory/{id}` — consolidated view
  - `POST /api/ap-advisory/feedback/{id}` — submit feedback
  - `GET /api/ap-advisory/feedback/{id}` — get feedback
  - `GET /api/ap-advisory/feedback-summary` — analytics
- Collections: `ap_reviewer_feedback` (feedback), `ap_advisory_review` (stored on doc)
- Phase 2 (not yet built): disagreement diagnostics, calibration, learning suggestions, approval/apply

## AP Invoice Vendor Advisory — Phase 2 (2026-04-13)
- Disagreement diagnostics: `ap_invoice_disagreement_diagnostics_service.py` — AP-specific root causes (vendor_match_ambiguity, extraction_ambiguity, po_reference_mismatch, amount_tolerance_sensitivity, duplicate_sensitivity, confidence_overestimation, explanation_wording)
- Confidence calibration: `ap_invoice_confidence_calibration_service.py` — penalty-based calibration preserving raw values (no_profile -20%, weak -10%, per_warning -5%, per_unusual -7%, per_blocker -15%)
- Learning suggestions: `ap_invoice_feedback_learning_service.py` — governed suggestion generation (add_vendor_alias, add_accepted_reference_pattern, widen_amount_tolerance, add_accepted_po_behavior, increase_vendor_variability)
- Collection: `ap_learning_suggestions` — same lifecycle as SO suggestions (pending → approved → applied)
- Endpoints on ap_advisory router: GET /diagnostics, POST /calibrate/{id}, POST /generate-suggestions, GET /suggestions

## AP Invoice Vendor Advisory — Phase 3 (2026-04-14)
- Suggestion approval workflow: `ap_invoice_learning_suggestion_apply_service.py` — governed approve/reject/apply lifecycle
  - State machine: pending → approved → applied (terminal), pending → rejected, rejected → pending (un-reject)
  - Mutation logic per type: add vendor alias, add accepted reference pattern, widen amount tolerance, relax PO requirement, increase vendor variability
  - Duplicate detection: no-op if value already present in profile
  - Full audit: `ap_learning_apply_audit` collection with pre/post snapshots
  - Endpoints: POST `/suggestions/{id}/approve`, `/reject`, `/apply`
- Learning impact review: `ap_invoice_learning_impact_review_service.py` — pre/post apply outcome comparison per vendor/type
  - Outputs: improved/no_change/regressed counts, per-type and per-vendor deltas, actionable recommendations
  - Endpoints: GET `/learning-impact-review`, GET `/learning-impact-review/details`
- Profile drift controls: `ap_invoice_profile_drift_service.py` — vendor profile evolution monitoring
  - Risk indicators: change cadence (>8/30d), alias growth (>10), variability (>0.90), amount range swing (>50%)
  - Endpoints: GET `/profile-drift`, GET `/profile-drift/{vendor_no}`, GET `/profile-change-history/{vendor_no}`
- Vendor hotspot review: `ap_invoice_vendor_hotspot_review_service.py` — cross-signal friction analysis
  - Root causes: low_profile_maturity, vendor_match_ambiguity, extraction_quality, amount_sensitivity, po_reference_friction, duplicate_sensitivity, profile_drift_risk, high_volume_low_learning
  - Endpoints: GET `/vendor-hotspots`, GET `/vendor-hotspots/{vendor_no}`
- All 14 new endpoints added to `routers/ap_advisory.py`
- Integration tests: `tests/test_ap_phase3.py` (12/12 passing)
- AP Invoice Advisory is now at feature parity with Sales Order governed learning pipeline

## Unified Governance Dashboard (2026-04-14)
- Backend: `routers/governance.py` — single consolidated endpoint aggregating SO + AP + system health
- Endpoint: `GET /api/governance/dashboard` — returns cross-pipeline metrics
- Sections: sales_orders (suggestions, feedback, drift_30d, hotspots), ap_invoices (same), system_health (7 metrics), combined_drift
- Frontend: `pages/GovernanceDashboard.js` — new standalone page at `/governance`
- System health strip: 7 stat cards (Total Docs, Pending, Completed, Posted 7D, Ready, Vendor Profiles, Auto Rate)
- Combined drift risk distribution: stacked bar chart (low/medium/high) — front and center
- Pipeline cards: SO + AP side-by-side with suggestion counts, agreement rates, drift mini-bars, expandable hotspot lists
- Actionable alert: shows when suggestions need attention
- Sidebar: "Governance" nav item with Shield icon
- Tested: 18/18 backend + 7/7 frontend tests passing (iteration_205.json)

## Bug Fix: Draft PI Preview Showing Identical Amounts (2026-04-14)
- **Root cause**: `posting_patterns.py` line 1348 — `preview_draft_pi()` assigned the FULL extracted total to EVERY template line instead of distributing it
- **Impact**: A $3,300 invoice with 3 template lines showed $3,300 × 3 = $9,900, or a $1,100 invoice showed $1,100 on all 3 lines
- **Fix**: Uses template `usage_rate` to distribute amounts proportionally. Falls back to even split when usage_rates are zero. Includes rounding correction to ensure line total matches document total exactly
- **Note**: The actual `create-draft` path (which posts to BC) was NOT affected — it uses the `template_value_injector.py` service which already handled ratios correctly. Only the preview modal was wrong

## Bug Fix: Readiness Completed with 0% Extraction (2026-04-13)
- **Root cause:** `evaluate_readiness()` would mark docs as `ready_auto_draft` when vendor was resolved via email sender BUT zero fields were extracted (e.g., .xls files the AI couldn't read)
- **Fix:** Added extraction quality gate — requires ≥2 meaningful extracted fields AND (invoice_number OR amount) before allowing auto-clear
- **Also tightened:** terminal short-circuit threshold from 1 to 2 meaningful fields, excluding boolean flags
- **Tested:** GAMMIN doc (0 fields) now correctly goes to `needs_review`; normal TUMALOC doc still auto-clears

## Status Model Cleanup (2026-04-13)
- **Bug 1 (Critical):** `derived_state_service.py` line 234 — when BC validation returned `all_passed=false` without `validation_status` field, the system defaulted to PASS instead of FAIL. Fixed: now correctly sets FAIL.
- **Bug 2:** AP validation "pass" event was overriding prior WARNING/FAIL states. Fixed: only upgrades validation_state if no prior failure/warning exists.
- **Bug 3:** `ReadyForPost` automation decision was silently overriding FAIL validation state. Fixed: only upgrades to PASS when validation hasn't already failed.
- **Bug 4 (Loop):** Reprocess loop — docs already decided as ReadyForPost were re-evaluated every full cycle (20+ times). Fixed: skip re-evaluation if `auto_post_attempted=true` and status already `ReadyForPost`.
- **Frontend:** Top badge now distinguishes "Ready to Post" (workflow=ready + validation=pass) from "Validated" (validation=pass), "Warnings", "Failed", and "Posted".
- Hierarchy enforced: Failed > Warnings > Validated > Ready to Post > Posted


## Bug Fix: Vendor Confirmations Falsely Triggering SO Rules (2026-04-15)
- **Root cause**: `pilot_smart_reclassifier.py` had no rules for order confirmations, order acknowledgments, or proforma invoices. Docs from vendors like Herdez, Aptar, O-I with filenames like "Order Confirmation", "OrderAck_W117579", "_ack.pdf" were classified as SALES_INVOICE and fed into the SO Rules Engine, triggering false SO-005 (missing cost) failures.
- **Fix 1 (Reclassifier)**: Added 6 new rules to Section 3 of `_RULES`: `order_confirmation`, `order_acknowledgment`, `vendor_confirmation`, `acknowledgment_file`, `ack_suffix`, `proforma_invoice`. All reclassify to `Vendor_Document`. Certificate negative lookahead prevents false positives. Already-reclassified docs are now skipped (checks `reclassified_from`).
- **Fix 2 (SO Rules Engine)**: `evaluate_all_pilot_sales_orders()` now excludes docs with `reclassified_from` in its query. `_check_cost_rules()` and `_check_customer_po()` expanded with additional vendor indicators (`_ack.`, `_ack_`, `acknowledg`, `proforma`) and `doc_type` check for `Vendor_Document`/`Purchase_Order`.
- **Tests**: 17/17 passing (`tests/test_p0_fixes.py`)

## Bug Fix: Incorrect Customer Extraction on Inbound Customer POs (2026-04-15)
- **Root cause**: `inside_sales_pilot_service.py` and `so_rules_engine.py` both used `vendor_canonical` as the primary customer source. When a customer (e.g., Giovanni) sends a PO to Gamer, the main pipeline sometimes resolves "Gamer" as `vendor_canonical` because Gamer appears in the Ship-To address on the PO.
- **Fix (Pilot Service)**: When `vendor_canonical` resolves to "Gamer", skip it and fall back to: extracted_fields customer/bill_to, then email sender domain-derived name (e.g., `orders@giovannis.com` → "Giovannis"). Gamer-related customer_no values (GAMER, GAMERPA, GAMER1) are cleared.
- **Fix (SO Rules Engine)**: Same Gamer-aware resolution in `_build_order_context()`. When `vendor_canonical` is Gamer, falls back to extracted fields and pilot extraction.

## Bug Fix: Total Amount Field Hit Rate at 0% (2026-04-15)
- **Root cause**: `inside_sales_pilot_service.py` checked `doc.get("total_amount")` first, but the main pipeline stores amount as `amount_float` at the top level (line 3229 of `server.py`). The field `total_amount` was never set by the main pipeline for most docs.
- **Fix**: Changed primary lookup to `doc.get("amount_float")` in both `inside_sales_pilot_service.py` and `so_rules_engine.py`. Extended fallback chain to also check `ef.get("amount")`, `ef.get("grand_total")`, `ef.get("invoice_total")`, `ef.get("net_amount")`.


## Spiro ↔ BC Name Reconciliation (2026-04-15)
- **Problem**: Companies like "Ortho Molecular Products" appeared in both "Spiro Only" and "BC Only" because no single document had both a Spiro match AND a BC match simultaneously. The cross-reference only linked companies when a single doc had both.
- **Fix**: Added `_reconcile_by_name()` to `spiro_bc_cross_ref_service.py`. After building spiro_only and bc_only lists, performs a normalized name comparison (stripping suffixes like Inc/LLC/Ltd/NA, normalizing punctuation/case). Moves matched pairs from both "only" lists into the "both" list.
- **Also fixed**: `bc_prod_validator.py` had same `doc.get("total_amount")` bug → fixed to `doc.get("amount_float")`. Added Gamer customer guard (clears Gamer-resolved customer_no, falls back to email sender domain).

## SO Rules Engine — Flowchart Alignment (2026-04-15)
- **Problem**: All 37 pilot sales docs evaluated as "Exception / Needs Review" with 32 Non-Compliant. The rules engine was treating early-stage docs (Draft/Open) the same as Released docs, pushing any missing field into a hard blocker.
- **Root cause**: Per the user's canonical Sales Order flowchart, Draft/Open docs are at the BEGINNING of the workflow — missing cost, confirmation, picks are expected. Those are action items for later stages, not blockers.
- **Fixes applied**:
  1. **SO-001 (Customer PO)**: Inbound customer PO documents (filename contains "PO", "Purchase Order", etc.) now have PO control marked as "inherently satisfied" — the document itself IS the PO.
  2. **SO-005 (Cost)**: Only blocks at Released+ stage. At Draft/Open, cost absence is informational ("will need cost entry before release").
  3. **SO-011 (Customer resolution)**: Only blocks at Released/Posted. At Draft/Open, it's an action item ("must resolve in BC before release").
  4. **Stage determination**: Draft/Open docs stay as "Draft / Open" with guidance. Only hard blockers (e.g., Gamer-is-customer, reclassification needed) push to Exception.
  5. **Compliance**: Draft/Open docs with PO + customer identified → "Conditionally Compliant" (can proceed to SO creation).
- **Expected impact**: Most pilot docs should now show "Draft / Open" + "Conditionally Compliant" with clear next-action guidance, instead of being dumped into exceptions.


## Pilot BC Prod Profile Comparison (2026-04-15)
- **Service**: `services/pilot_readiness_review_service.py` — bridges pilot docs with SO Readiness Reviewer + customer posting profiles
- **Endpoints**: `POST /api/inside-sales-pilot/readiness-review/{doc_id}`, `POST /readiness-review-all`, `GET /readiness-review-results`
- **Resolution chain**: customer_no from extraction → BC validation → Spiro external_id → vendor_canonical → fuzzy name → bc_reference_cache bridge
- **Validation gate**: Rejects false profile matches by verifying customer name overlap (first-word comparison)
- **Results**: 10/37 docs with accurate BC Prod profiles (Giovanni→GIOVANN, Herdez→HERDEZ, Ortho→ORTHO)
- **Intelligence**: "Order value within typical range", "New ship-to address detected", "Item matches customer history"
- Advisory only — never writes to BC

## Spiro Vendor Gate (2026-04-15)
- **Problem**: Docs from Spiro-designated Vendor companies (Owens, Phoenix, Ball Corp, Aptar, etc.) were entering the sales pipeline as customer POs. These companies are suppliers TO Gamer, not customers ordering FROM Gamer.
- **Fix**: Added Spiro `relationship_type` check to three services:
  1. **Reclassifier**: Vendor-company docs with SALES_INVOICE type → reclassified to Vendor_Document
  2. **SO Rules Engine**: Vendor docs → "Not a Sales Order" stage with routing guidance
  3. **Readiness Review**: Vendor docs → "not_applicable" with vendor context
- **Impact**: 3 vendor docs reclassified, pipeline reduced from 37 → 36 genuine sales docs
- **ISR context**: Jon Hawkes handles all vendor relationships (0 opportunities, 43% in BC) — vendor docs are supply-side communications

## Status Normalization Fix (2026-04-15)
- **Root cause**: `_normalize_status()` in `so_rules_engine.py` returned raw status strings for unrecognized values (e.g., "captured", "extracted"). These fell through all stage checks to the final "Exception / Needs Review" return.
- **Fix**: Added 10+ hub internal statuses to the mapping (captured, extracted, classified, ingested, processing, queued, new, pending → Draft/Open; exception, failed, error → Exception). Unrecognized statuses now default to "Draft / Open" instead of raw passthrough.
- **Impact**: All 37 docs moved from "Exception / Needs Review" to "Draft / Open"


## v2.5.10 — Email Dedup + Auto-Proposed Filename Rules (2026-04-19)
- **Fixed**: Email-poller ingesting same attachment 10–12×/day (GAMMIN_AR, W9.pdf). Root cause: static + dynamic pollers used incompatible dedup schemas in shared `mail_intake_log`, dynamic poller had 1h hardcoded lookback replayed every 60 s, and no DB-layer uniqueness. Fix: unified hash-first dedup across both pollers, per-mailbox watermarks, UNIQUE partial index on `(internet_message_id, attachment_hash)`, and `ensure_mail_intake_indexes()` at startup.
- **Added**: Auto-Proposed Filename Heuristic Rules — mines each vendor's own classified-doc history in `hub_documents` to derive new rules without manual input. Persisted in `filename_heuristic_custom_rules` collection and consulted by `classify_filename_async` (60 s cache). Built-in rules always win; custom rules serve as fallback. 5 new admin endpoints under `/api/admin/filename-heuristics/{auto-propose, auto-apply, custom-rules, custom-rules/{id}/toggle}`.
- **Tests**: 8 dedup + 13 auto-propose pytests + testing-agent iter_232 HTTP suite — 107/107 PASS.
- **Known follow-ups** (all P2 — see ROADMAP.md):
  - Frontend tooltip on Document Detail showing `filename_heuristic_rule` + `filename_heuristic_note`.
  - Surface the custom-rules list in an admin UI panel (currently API-only).
  - Phase B/C orchestration extraction from `server.py`.

