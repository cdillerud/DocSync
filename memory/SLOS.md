# P0.5 — Service Level Objectives (Phase 1 Floor)

**Status:** STARTER PROPOSAL — 5 SLOs. Acceptance during P0 review = blocking input for Phase 2 alerting wiring (G-GOV-5).

**Phase 1 scope:** measurement methodology landed. **Alerting wiring is Phase 2.**

## SLO catalog

### SLO-1: Auth dependency latency (introduced by Phase 1)
- **Service surface:** every mutating endpoint + every authenticated GET endpoint (essentially every `/api/*` route post-P1.C).
- **Indicator:** p95 of `Depends(get_current_actor)` execution time, measured from `Authorization` header receipt to `Actor` object availability.
- **Target:** **p95 ≤ 50ms** under steady-state JWKS cache hit. **p99 ≤ 200ms** allowing for occasional cache-miss/JWKS-fetch.
- **Measurement:** new ASGI middleware records `(route, method, actor_resolution_ms, cache_hit)` to `governance_audit_log` collection (P1.A).
- **Failure budget:** ≤ 0.1% of requests > 500ms over a 7-day window.

### SLO-2: BC SO creation success rate
- **Service surface:** `services.auto_post_service.attempt_auto_create_sales_order` calls.
- **Indicator:** ratio (200/201/202 BC responses) ÷ (all BC SO POST attempts).
- **Target:** **≥ 99.0%** rolling 24-hour success rate when `AUTO_CREATE_SALES_ORDER_ENABLED=true` AND `BC_WRITE_ENABLED=true`.
- **Failure budget:** 1% — 1 in 100 attempts may fail without breaching SLO.
- **Measurement:** existing audit on auto_post_service + new fields surfaced via P1.A audit log.

### SLO-3: Intake-to-classification latency
- **Service surface:** `services.document_handlers.intake_document_from_bytes`.
- **Indicator:** time from byte receipt to `workflow_status='classified'`.
- **Target:** **p95 ≤ 12 seconds** for documents ≤ 5MB; **p95 ≤ 30 seconds** for documents 5–25MB.
- **Failure budget:** ≤ 5% of submissions exceeding p95 over a 7-day window.
- **Measurement:** existing event timestamps in `learning_events_v2` + audit log correlation_id chain.

### SLO-4: Gate-decision latency
- **Service surface:** every `Gate.evaluate()` call across the 4 production gates (COWItemOnPO, COWSalesOrder, Consignment, MasterDataCompleteness).
- **Indicator:** p95 of `evaluate()` wall-clock time per gate per doc.
- **Target:** **p95 ≤ 100ms per gate**, p99 ≤ 500ms per gate.
- **Failure budget:** ≤ 1% of gate evaluations > 1s over 7-day window.
- **Measurement:** new `governance_audit_log` rows per gate decision (P1.A).

### SLO-5: Audit log write durability
- **Service surface:** `services.governance_audit_log.emit_audit`.
- **Indicator:** `emit_audit` call resulting in a durable row reflected by `find_one({_id: ...})` within 1s.
- **Target:** **100.00%** — no audit-log losses tolerated.
- **Failure budget:** **zero**. Any loss triggers immediate runbook escalation.
- **Measurement:** P1.A test probes assert durability.

## Phase 1 deliverables for SLOs

- P1.A audit-log middleware records the (route, method, actor_resolution_ms, cache_hit) fields needed for SLO-1 and SLO-4.
- P1.F slim preflight asserts SLO-related test probes pass before deploy.
- Nothing wired to alerting yet — alerting is G-GOV-5 in Phase 2.

## Phase 2+ deliverables

- G-GOV-5: Wire SLO-1..5 to existing `drift_watchlist_service` channel.
- Define burn-rate-based alerting (1h, 6h, 24h windows).
- Runbook for each alert.
