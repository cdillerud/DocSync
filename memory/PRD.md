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

## Upcoming Tasks
- P0: Ollama Provider Abstraction Layer (base_provider.py, ollama_provider.py, llm_router.py)
- P1: Rep Overrides Management UI
- P1: Teams Adaptive Card integration (webhook → BC Sales Order)

## Future/Backlog
- P2: Low-volume vendor review routing (<5 docs skip auto-file)
- P2: Activate correction replay engine
- P2: Email sender → vendor mapping
- P3: `server.py` extraction/refactoring (8,200+ lines)

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
- Phase 3 (not yet): impact review, drift controls, hotspot review for AP
