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
- `/app/backend/server.py` — Main server, background schedulers (PO retry, Captured retry), intake pipeline
- `/app/frontend/src/pages/UnifiedQueuePage.js` — Inbox with metrics panel, retry-stuck button, tabs
- `/app/frontend/src/pages/MonitoringDashboard.js` — Vendor mapping UI

## Critical Data Rule
- `is_duplicate: {"$ne": True}` must be included in ALL inbox-related queries (documents list, inbox-stats, inbox-metrics) to match the actual inbox view. The documents endpoint enforces this at line 180.

## Completed Features
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

## Upcoming Tasks
- P0: Ollama Provider Abstraction Layer (base_provider.py, ollama_provider.py, llm_router.py)
- P1: Rep Overrides Management UI
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future/Backlog
- P2: Low-volume vendor review routing (<5 docs skip auto-file)
- P2: Activate correction replay engine
- P2: Email sender → vendor mapping
- P3: `server.py` extraction/refactoring (8,200+ lines)
