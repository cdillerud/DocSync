# GPI Document Hub — Architectural Review & Redesign
## Senior Systems Architecture Assessment
## v2.1.0 | 2026-04-16

---

## Executive Summary

GPI Document Hub is a 131,000-line Python/React system (8,718 in `server.py`, 80,527 across 157 services, 42,086 across 65 routers) that processes ~1,750 documents/month through email ingestion, AI extraction, entity resolution, validation, and BC posting. It works. The auto-rate is 97.2%, vendor resolve is 92%, AI confidence is 96.1%.

The problem is not that it fails. The problem is that it grew feature-by-feature without a unifying orchestration model. The result: **the same logical operation is implemented independently in 5-9 places**, the monolithic `server.py` contains 27 doc_type branches across 111 async functions, and adding a new document type requires touching ~15 files.

**Recommendation**: Refactor into **one orchestration pipeline with pluggable policy modules**. Not multiple pipelines sharing utilities, not a hybrid. One pipeline. The reason is simple — the runtime already works this way. Every document enters through `_internal_intake_document()`, gets classified, extracted, and normalized by the same code path. The branching happens at one point (the doc_type switch). The architecture should reflect what the code already does, and the duplicated resolution/readiness logic should be consolidated into shared services called by thin policy modules.

---

## 1. Current-State Architectural Issues

### 1.1 The Monolith Problem
`server.py` is 8,718 lines containing:
- Document intake orchestration
- AP invoice workflow (vendor resolution → validation → posting)
- Sales order workflow (customer resolution → pilot hold)
- Warehouse workflow (BOL matching → auto-clear)
- Default/other workflow
- 7+ background schedulers (PO retry, ready-to-post, auto-clear, email polling, pilot polling)
- Ad-hoc utility functions
- Configuration and initialization

This is not a file. This is the entire backend masquerading as one file.

### 1.2 Customer Resolution: 9 Independent Implementations
The following files each contain their own customer resolution chain (extract customer_name → check vendor_canonical → check BC validation → check Spiro external_id → check batch parent → Gamer gate):

| # | File | Context |
|---|---|---|
| 1 | `routers/sales_dashboard.py` | Queue list assessment |
| 2 | `routers/gpi_integration.py` | Preflight / SO creation |
| 3 | `routers/explain.py` | Advisory panel |
| 4 | `services/inside_sales_pilot_service.py` | Pilot extraction |
| 5 | `services/bc_prod_validator.py` | BC validation |
| 6 | `services/pilot_readiness_review_service.py` | Readiness review |
| 7 | `services/so_rules_engine.py` | Rules evaluation |
| 8 | `routers/readiness.py` | Readiness scoring |
| 9 | `server.py` | Intake workflow |

Each copy has slightly different field priority, different fallback chains, and different Gamer-detection logic because they were written at different times. This session alone required patching 7 of these 9 copies to fix customer resolution. Every future change requires the same.

### 1.3 Vendor Resolution: 70+ Files Reference It
70 files reference `vendor_canonical` or vendor matching logic. The core resolution algorithm (`alias → BC exact → BC search → fuzzy → sender domain`) lives in `server.py` and `services/unified_vendor_matcher.py`, but at least 12 other files re-derive vendor state from document fields rather than calling a shared service.

### 1.4 Readiness Assessment: 5 Implementations
`_assess_readiness()` in `sales_dashboard.py`, readiness scoring in `routers/readiness.py`, `services/document_readiness_service.py`, `services/so_rules_engine.py`, and `routers/admin.py` all compute "is this document ready?" using overlapping but inconsistent logic.

### 1.5 No Formal Orchestration Model
The intake function is a 1,500-line `if/elif/elif` chain. There is no pipeline abstraction. Each doc type branch re-implements field extraction, status updates, event emission, and error handling inline. The "pipeline" is implicit in the control flow of one function, not explicit in a composable architecture.

---

## 2. Target-State Architecture

### Design Principle
**One pipeline. Shared stages. Policy modules for divergence. Services for capabilities.**

```
Document In
    │
    ▼
┌─────────────────────────────────────────────┐
│         ORCHESTRATOR (pipeline.py)           │
│                                             │
│  For each document:                         │
│    1. intake_service.ingest(doc)            │
│    2. ai_service.classify_extract(doc)      │
│    3. resolution_service.resolve(doc)       │
│    4. validation_service.validate(doc)      │
│    5. policy = get_policy(doc.doc_type)     │
│    6. policy.evaluate(doc)                  │
│    7. action_service.execute(doc, policy)   │
│    8. governance_service.learn(doc)         │
│                                             │
└─────────────────────────────────────────────┘
```

Each numbered step is a **service call**, not inline code. The orchestrator is ~100 lines. It replaces 1,500 lines of `server.py` branching.

### 2.1 Shared Core Services

These are stateless services with a single responsibility. Every document type calls them.

| Service | Responsibility | Current Location | Target |
|---|---|---|---|
| `intake_service` | Mailbox poll, relevance filter, dedup, doc creation | `server.py` lines 2824-3100 + `email_polling_service.py` | `services/intake_service.py` |
| `ai_service` | Classification, LLM extraction, normalization, batch split | `server.py` lines 3100-3700 | `services/ai_processing_service.py` |
| `entity_resolution_service` | **Single** resolve_customer() + resolve_vendor() | 9 files (see §1.2) | `services/entity_resolution_service.py` |
| `validation_service` | Field completeness, entity existence, PO match, amount range, duplicate risk | `server.py` + 5 readiness files | `services/validation_service.py` |
| `event_service` | Workflow audit trail | `services/event_service.py` | Keep as-is |

### 2.2 Supporting Enrichment Services

These provide data to the resolution and validation layers. They are not orchestration steps — they are called by core services.

| Service | Called By | Function |
|---|---|---|
| `bc_reference_cache` | entity_resolution, validation | Customer/vendor/order lookup in BC |
| `spiro_service` | entity_resolution (Sales) | CRM matching, external_id, ISR, opportunities |
| `spiro_bc_cross_ref` | Dashboard (read-only) | Name reconciliation visualization |
| `customer_posting_profiles` | validation, policy (Sales) | Historical ordering patterns |
| `vendor_invoice_profiles` | validation, policy (AP) | Learned vendor extraction templates |
| `unified_vendor_matcher` | entity_resolution | Alias, fuzzy, BC search matching |

### 2.3 Policy Modules

Each policy module implements a `PolicyModule` interface:

```python
class PolicyModule:
    async def evaluate(self, doc, resolution, validation) -> PolicyResult:
        """Apply doc-type-specific business rules. Return actions + status."""
        ...

    async def get_actions(self, doc, evaluation) -> List[Action]:
        """Return available actions for this document in its current state."""
        ...
```

| Policy Module | Target File | What It Does | What It Does NOT Do |
|---|---|---|---|
| `ap_invoice_policy` | `policies/ap_invoice.py` | Vendor match enforcement, AP validation rules, retry/escalation, draft PI preview, line distribution, auto-post eligibility | Does NOT do extraction, normalization, or vendor resolution |
| `sales_order_policy` | `policies/sales_order.py` | Smart reclassifier, Spiro vendor gate, SO Rules Engine, readiness review, profile comparison, pilot safety hold | Does NOT do classification, customer resolution, or BC lookup |
| `warehouse_policy` | `policies/warehouse.py` | BOL matching, PO matching, auto-clear, ship date validation | Does NOT do extraction or entity resolution |
| `archive_policy` | `policies/archive.py` | Route to SharePoint, mark as no-processing | Minimal — just routing |

### 2.4 Action Layer

Actions are the side effects a policy module requests. The action layer executes them.

| Action | Handler | Used By |
|---|---|---|
| `post_to_bc` | `services/ap_auto_post_service.py` | AP policy |
| `create_sales_order` | `routers/gpi_integration.py` | Sales policy (blocked in pilot) |
| `route_to_review` | `services/document_routing_service.py` | All policies |
| `route_to_exception` | `services/document_routing_service.py` | All policies |
| `archive` | `services/sharepoint_routing_service.py` | Archive policy |
| `auto_clear` | `services/auto_clear_service.py` | Warehouse policy |

### 2.5 Governance & Learning Layer

Post-action services that update system intelligence. Shared infrastructure, doc-type-specific learners.

| Service | Scope | Function |
|---|---|---|
| `confidence_calibration` | Shared | Adjust AI confidence based on outcomes |
| `feedback_loop` | Shared | Human agree/disagree → model correction |
| `vendor_profile_learning` | AP | Update vendor templates from BC postings |
| `customer_profile_learning` | Sales | Update customer patterns from SO history |
| `posting_pattern_learning` | AP | Template value injection, usage_rate |
| `drift_detection` | Shared | Advisory alerts on changing patterns |

---

## 3. Where AP and Sales Should Truly Diverge

### Must Diverge (Real Business Differences)
| Concern | AP | Sales | Why |
|---|---|---|---|
| Primary entity | Vendor (who sent the invoice) | Customer (who sent the PO) | Opposite direction of trade |
| BC target object | Purchase Invoice | Sales Order | Different BC APIs |
| Auto-action | Auto-post PI to BC | BLOCKED (pilot mode) | Safety constraint |
| Compliance rules | AP validation (tax, freight, amount vs PO) | SO Rules Engine (11 rules per flowchart) | Different business rule sets |
| CRM enrichment | Not used | Spiro CRM matching | Sales-specific data source |
| Template learning | Vendor posting patterns, line distribution | Customer ordering patterns | Different profile shapes |
| Reclassification | Not needed (AP docs are already typed) | Smart reclassifier (vendor confirmations, noise) | Sales inbox is noisier |

### Must NOT Diverge (Currently Duplicated Without Reason)
| Concern | Current State | Target State |
|---|---|---|
| Entity resolution algorithm | 9 copies with different fallback chains | One `resolve_entity(doc, entity_type)` service |
| Readiness assessment | 5 implementations | One `assess_readiness(doc)` service |
| Field completeness check | Inline in multiple files | Part of `validation_service` |
| BC reference cache lookup | Inline in 12+ files | Method on `bc_cache_service` |
| Gamer-is-entity detection | Copied in 7 files | Part of `entity_resolution_service` |
| Batch parent inheritance | Copied in 3 files | Part of `entity_resolution_service` |
| Status normalization | `so_rules_engine.py` only | Shared utility |
| Extraction quality scoring | `inside_sales_pilot_service.py` only | Part of `validation_service` |

---

## 4. Canonical Processing Sequence

Every document, regardless of type:

```
1. INGEST        → intake_service.ingest(source, file, metadata)
                   Output: doc record in hub_documents

2. CLASSIFY      → ai_service.classify(doc)
                   Output: doc_type, confidence, batch_info

3. EXTRACT       → ai_service.extract(doc)
                   Output: extracted_fields, line_items

4. NORMALIZE     → ai_service.normalize(doc)
                   Output: normalized_fields

5. RESOLVE       → entity_resolution_service.resolve(doc)
                   Calls: vendor_matcher, bc_cache, spiro (if sales),
                          parent_inheritance, gamer_gate
                   Output: vendor_canonical OR customer_resolved,
                           entity_no, match_method, confidence

6. VALIDATE      → validation_service.validate(doc)
                   Calls: field_completeness, entity_exists,
                          po_match, amount_range, duplicate_risk,
                          extraction_quality
                   Output: validation_results, readiness_score

7. POLICY        → policy_registry.get(doc.doc_type).evaluate(doc)
                   AP: vendor enforcement, draft PI, auto-post eligibility
                   Sales: reclassifier, SO rules, profile comparison, pilot hold
                   Warehouse: BOL match, auto-clear
                   Archive: route to SharePoint
                   Output: policy_result {stage, compliance, actions, warnings}

8. ACTION        → action_service.execute(doc, policy_result)
                   AP: post to BC / route to review / exception
                   Sales: update dashboard / hold for pilot / flag
                   Warehouse: auto-clear / exception
                   Output: action_result, final status

9. LEARN         → governance_service.learn(doc, action_result)
                   Update profiles, calibrate confidence,
                   record feedback, detect drift
                   Output: learning_events
```

Steps 1-6 are **identical for every document**. Step 7 is the **only** point of divergence. Steps 8-9 are shared infrastructure executing doc-type-specific actions.

---

## 5. Recommended Refactors

### Priority 1: Entity Resolution Service (High Value, Medium Effort)
**Create `services/entity_resolution_service.py`** with:
```python
async def resolve_entity(doc: dict) -> EntityResolution:
    """Single resolution chain for both vendor and customer."""
    # Returns: {entity_type, entity_name, entity_no, match_method, confidence, source}
```
- Consolidates 9 copies into 1
- Called by: validation_service, all policy modules, all dashboards
- Includes: Gamer gate, batch parent inheritance, Spiro bridge, BC cache lookup
- Estimated: ~200 lines replacing ~1,500 lines of duplicated code

### Priority 2: Extract Policy Modules from server.py (High Value, High Effort)
**Create `policies/` directory**:
- `policies/ap_invoice.py` (~300 lines from server.py lines 3333-3634)
- `policies/sales_order.py` (~200 lines from server.py lines 2231-2363)
- `policies/warehouse.py` (~200 lines from server.py lines 2065-2228)
- `policies/archive.py` (~50 lines from server.py lines 2365-2438)
- `pipeline.py` (~100 lines — the orchestrator)

This turns `server.py` from 8,718 lines into ~6,000 lines (background schedulers, utilities, initialization remain).

### Priority 3: Validation Service Consolidation (Medium Value, Low Effort)
**Create `services/validation_service.py`** with:
```python
async def validate_document(doc: dict, resolution: EntityResolution) -> ValidationResult:
    """Shared validation: completeness, entity exists, PO match, amount, duplicate."""
```
- Consolidates 5 readiness implementations into 1
- Policy modules add type-specific validations on top

### Priority 4: Pipeline Orchestrator (Medium Value, Medium Effort)
**Create `pipeline.py`** — the canonical 9-step sequence:
```python
async def process_document(doc_id: str):
    doc = await intake_service.get(doc_id)
    doc = await ai_service.classify_extract_normalize(doc)
    resolution = await entity_resolution_service.resolve(doc)
    validation = await validation_service.validate(doc, resolution)
    policy = policy_registry.get(doc.doc_type)
    evaluation = await policy.evaluate(doc, resolution, validation)
    result = await action_service.execute(doc, evaluation)
    await governance_service.learn(doc, result)
```
This replaces the 1,500-line `if/elif` chain with 8 function calls.

### Priority 5: Background Scheduler Extraction (Low Value, Low Effort)
Move 7 background loops from `server.py` to `services/schedulers/`:
- `po_retry_scheduler.py`
- `ready_to_post_scheduler.py`
- `auto_clear_scheduler.py`
- `pilot_polling_scheduler.py`
- `email_polling_scheduler.py`
- `continuous_learning_scheduler.py`
- `startup_cleanup.py`

---

## 6. Architectural Recommendation

**Model: One orchestration pipeline with pluggable policy modules.**

Not multiple pipelines sharing utilities — that's what exists today and it led to 9 copies of customer resolution.

Not a hybrid — that adds complexity without solving the duplication.

One pipeline because:
1. **The runtime already works this way.** Every document enters `_internal_intake_document()`, goes through the same classification → extraction → normalization path, then branches on doc_type. The architecture should match the runtime.
2. **The duplication is in the shared stages, not the specialized ones.** AP and Sales diverge in ~300 lines of policy logic each. They share ~1,200 lines of intake, extraction, resolution, and validation that are currently implemented independently.
3. **New document types become trivial.** Adding "Credit Memo" or "Remittance" processing means writing a 50-line policy module, not forking 1,500 lines of pipeline code.
4. **The entity resolution problem is solved once.** One service, one fallback chain, one place to add Spiro enrichment or batch parent inheritance. Every consumer gets it for free.
5. **Testing becomes meaningful.** You can test the pipeline, test resolution, test AP policy, and test Sales policy independently. Today you can only test `server.py`.

The 4 policy modules (AP, Sales, Warehouse, Archive) are small (~50-300 lines each) because they only contain genuine business-rule differences. Everything else is shared infrastructure.

---

## 7. Effort Estimate

| Refactor | Lines Affected | Risk | Business Impact |
|---|---|---|---|
| Entity Resolution Service | ~1,500 lines consolidated → 200 | Low (pure extraction) | Eliminates recurring customer resolution bugs |
| Policy Module Extraction | ~1,000 lines from server.py | Medium (behavioral) | Makes doc-type logic testable and extensible |
| Validation Consolidation | ~500 lines consolidated → 150 | Low | Consistent readiness scoring everywhere |
| Pipeline Orchestrator | ~100 new lines, ~1,500 removed | Medium | Replaces monolithic branching with composable steps |
| Scheduler Extraction | ~400 lines moved | Negligible | Reduces server.py by 400 lines |
| **Total** | **~3,500 lines touched** | **Medium overall** | **Platform becomes maintainable and extensible** |

The system processes 1,750 docs/month at 97.2% auto-rate. It doesn't need to be rewritten. It needs to be reorganized so the next 10 features don't each require patching 9 files.
