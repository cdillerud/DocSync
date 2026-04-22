# GPI Hub — Lane A/B/C Pre-Coding Declaration (SIGNED)

**Status:** Signed by Chad Dillerud, Product Owner, 2026-04-22.
**Source:** Pre-coding declaration of 2026-04-22 + Chad's amendment memo of the same date.
**Amendments incorporated:** §2.1, §3.1, §4a.1, §4a.2, §5.1, §6.1, plus §4b docstring clarification.
**Execution directive:** Proceed through Lane A without further checkpoints until Lane A is complete.

---

## §1. Lane A — Integrity scope (ACCEPTED AS WRITTEN)

Four items. A1 first (gives A2 a place to write). A2 and A4 parallel. A3 gates Lane B.

| # | Item | Canonical path | Done criteria |
|---|---|---|---|
| A1 | **Historical posting-attempts array** | `hub_documents.bc_posting_attempts[]` replaces the overwrite-on-failure `bc_posting_error` string | Schema migration; append-only; frontend accordion (see A1 UX spec below); pytest covers first / retry / success-after-retry / partial-post-mid-retry |
| A2 | **Retry/backoff on BC 429/503** | Single HTTP wrapper in `services/business_central_service.py` | 3 retries, base 1s/2s/4s + jitter, circuit-break at 3 consecutive; 4xx-non-429 passes through; every attempt appends to `bc_posting_attempts` |
| A3 | **Phase 4 Path B removal PR** | Delete six `_deprecate()` registrations + three orphan `server.py` functions | `phase_4_gate.gate_met=true` for 7 consecutive UTC days AND full regression green. **See §1 clock semantics below.** |
| A4 | **Pre-claim `workflow_engine.advance_workflow`** | `POST /api/ap-review/documents/{id}/post-to-bc` drives engine BEFORE `bc_post_claim.claim_for_bc_post` | `ON_BC_POSTING_STARTED` pre-claim; `ON_BC_POSTED` / `ON_BC_PARTIAL_POSTED` / `ON_BC_POST_FAILED` post-result; release_claim reverses engine state on failure |

### §1 clock semantics (per Chad's explicit note)
**A3's "7 consecutive UTC days" is a clock measurement, not a deploy gate.** If `phase_4_gate.gate_met=true` for N days (N<7) and then a Path B hit arrives on day N+1, the counter resets to zero and A3 does not ship. The regression hit is itself logged as an exception of type `archived_doc_collision` (see §6 revised taxonomy) pointed at the offending route so the caller is surfaced to ops.

Implementation: the regression-detection writes happen inside the existing `_deprecate()` wrapper — a Path B hit writes both the `deprecation_hits` counter row (already built) AND an exception document with `archetype="legacy_path_b"`, `source_gate_id="phase_4_gate.drain_regression"`, `evidence={last_client_host, last_user_agent, day_bucket, route_template}`. Ships as part of A3's PR, not A1.

### A1 UX spec (per Chad's answer to question 1)
- Accordion; collapsed by default; open on page load if `bc_posting_status ∈ {"failed", "partial", "pending_retry"}`.
- Entries ordered most-recent first.
- Each entry renders: `timestamp` (local + UTC tooltip), `status`, `actor` (`engine:retry` vs `user:<email>`), truncated `error` with expand-for-full, and `gate_id` when the attempt was blocked pre-submission.

---

## §2. Lane B — Module tree (ACCEPTED WITH AMENDMENT §2.1)

Pure mechanical move. Zero behavior change. One PR. Ships only after A3 lands.

### §2.1 (Chad's amendment): add `workflows/document_capture/` placeholder

```
backend/workflows/
├── __init__.py                                # domain index, no logic
├── core/
│   ├── engine.py                              # ← services/workflow_engine.py (MOVED)
│   ├── events.py
│   ├── state.py
│   ├── gate_framework.py                      # NEW — see §5
│   └── learning_core/                         # ← services/learning_core/ (MOVED)
├── ap_invoice/
│   ├── module.py
│   ├── scenarios/                             # SCAFFOLD ONLY
│   │   ├── receive_and_invoice.py
│   │   ├── invoice_only.py
│   │   ├── freight_only.py
│   │   ├── correction.py
│   │   ├── warehouse_inbound.py
│   │   └── assembly_repack.py
│   └── rules/
│       ├── bc_preflight.py                    # ← services/* (MOVED)
│       ├── line_reconciliation.py             # ← services/line_reconciliation.py (MOVED)
│       └── vendor_profile.py                  # ← services/vendor_profile_* (MOVED)
├── sales/
│   ├── module.py
│   └── subtypes/
│       ├── README.md
│       ├── drop_ship/                         # empty — so_rules_engine stays in services/ until step 6
│       ├── warehouse_order/                   # empty
│       ├── produce_and_hold/                  # empty
│       ├── assembly_order/                    # empty
│       ├── consignment/                       # empty
│       ├── customer_storage/                  # empty
│       ├── customer_owned_ware/               # empty
│       ├── reselling_cow/                     # empty
│       └── reroute/                           # empty
├── freight/
│   ├── module.py
│   ├── shipment_methods/
│   │   ├── registry.py                        # NEW — see §4a
│   │   └── rules.py                           # NEW
│   └── item_charges.py                        # ← services/freight_business_rules.py (MOVED)
├── inventory/
│   ├── module.py
│   ├── ledger/                                # ← services/inventory_ledger_service.py (MOVED)
│   ├── ownership.py                           # NEW scaffold
│   ├── lineage.py                             # NEW scaffold
│   └── planning/
│       └── staging.py                         # ← services/inventory_xls_staging_service.py (MOVED)
├── document_capture/                          # §2.1 AMENDMENT — NEW placeholder
│   └── README.md                              # Square 9 + ZetaDocs scope note, no module yet
├── payments/
│   └── README.md                              # DEFERRED
└── batch/
    ├── module.py
    ├── eod_controller.py                      # SCAFFOLD — implemented Lane C step 3
    └── exception_queues.py                    # SCAFFOLD — implemented Lane C step 3
```

### Lane B mechanical rules (unchanged)
- Move files; do not split. Updates are import paths only.
- No route URLs change. No Pydantic models change. No DB collections change.
- `services/so_rules_engine.py` stays put until Lane C step 6.
- `workflows/payments/` and `workflows/document_capture/` are `README.md` only — no `__init__.py`, nothing importable.
- PR is atomic. Supervisor restart clean. `/openapi.json` byte-identical.

---

## §3. Lane C sub-sequence (ACCEPTED WITH AMENDMENT §3.1)

9 canonical steps + step 2.5 (shipment-method registry foundation) + step 2.75 (master-data-completeness gate scaffold, warn-severity).

| # | Step | Deliverables |
|---|---|---|
| 1 | Customer-Owned Ware | CP-item registry; ownership module; CP-on-PO block; DS adjustment-journal allowance; COW archetype gates |
| 2 | Consignment | Reuse ownership.py; consignment ownership-state transitions; archetype gates |
| **2.5** | **Shipment-method registry foundation** | 13-code seed; rule engine keyed on code; unit tests; unwired |
| **2.75** | **§3.1 AMENDMENT: master-data-completeness gate scaffold** | Global gate registered at `archetype=None`; **`warn` severity** initially (not block); validates the gate framework plumbing end-to-end with a live gate before archetype gates ship in volume. Upgrades to `block` severity at step 9 once every archetype's required master data set is known. |
| 3 | EOD controller + unified exception queues | 5-step close-day; 10-type exception taxonomy; idempotent per step; §6.1 amendment |
| 4 | Produce-and-Hold + Assembly Order pair | Inventory lineage (`workflows/inventory/lineage.py`); inventory-transformation primitives |
| 5 | Warehouse Order | Standard inbound/outbound; consumes shipment-method registry |
| 6 | Drop Ship formalization | Lift `so_rules_engine.py` into `workflows/sales/subtypes/drop_ship/`; mechanical |
| 7 | Customer Storage + Reselling COW + Reroute | Lower complexity; batched single release |
| 8 | Planning/import (Coloplast-style) | `workflows/inventory/planning/calculator.py`; staging → calc → exception review → downstream; cycle-completion gate |
| 9 | Master-data-completeness gate **upgrade to `block`** | Flip the step-2.75 gate severity from `warn` to `block` now that every archetype's required master data set is final |

---

## §4. Registry schemas (ACCEPTED WITH AMENDMENTS §4a.1, §4a.2, §4b docstring)

### §4a. Shipment-method registry (`db.shipment_method_registry`)

```python
{
  "code": "PPDADD",                                    # unique uppercase
  "display_name": "Prepaid Add",
  "region": "domestic" | "international",
  "fob_side": "origin" | "destination",
  "date_field_driving_order": "pickup_date" | "delivery_date",
  "freight_line_expected_on": "SO" | "PO" | "neither",
  "sell_price_source": "customer_billed" | "not_billed" | "wrapped_in_item_cost",
  "arranged_by": "gamer" | "supplier" | "customer" | "third_party",
  "customs_responsibility": "gamer" | "supplier" | "n/a",
  "freight_variance_threshold_usd": null,              # §4a.1 — default fallback = FREIGHT_VARIANCE_DEFAULT=100.0;
                                                       #   carrier-level override deferred to carrier_registry;
                                                       #   TODO in seed file to document XPO/R&L $50 threshold
  "post_bol_update": {                                 # §4a.2 — reviewer-choice model
      "new_code_options": ["THIRD_PARTY", "COLLECT"],
      "when": "bol_received",
      "requires_reviewer_choice": true,                # false iff deterministic mapping exists (none today)
      "applies_to_archetypes": ["drop_ship", "warehouse_order"]
  } | null,
  "allowed_archetypes": [...],
  "notes": "",
  "active": true,
  "created_utc": "...",
  "updated_utc": "..."
}
```

**13-code seed** (code-checked-in in `workflows/freight/shipment_methods/registry.py`):
- Domestic: `PPDADD`, `PPD`, `CPU`, `DELIVERED`, `COLLECT`, `GAMER_ARRANGED`, `THIRD_PARTY`
- International: `EX_WORK`, `FOB_PORT`, `DDP`, `DDU`, `CFR`, `DAT`

Index: `{code: 1}` unique.

### §4b. CP-item registry (`db.cp_item_registry`) — ACCEPTED AS WRITTEN + docstring clarification

Schema as previously specified. **Registry module docstring** (not a schema change) captures:

> CP items are never retired programmatically. When a customer fully consumes their CP inventory, the registry row stays `status=active` because the customer could buy more ware under the same CP item number later. Only `items@gamerpackaging.com` can set `status=retired` — a manual admin action. `linked_invoice_ids` is append-only.

Indexes: `{item_no: 1}` unique; `{customer_no: 1, status: 1}`.

Guard rule scope:
- **Block (severity=block)** on `document_type=PO` line with `item_no` matching either (a) registry `status=active` OR (b) fallback pattern `.*-CP[A-Z0-9]+$` not in registry with `status=retired`. Exception type: `COW_ITEM_ON_PO`.
- **Allow** on inventory adjustment journal (positive qty into `canonical_location`).
- **Separate gate `COW_SO_USES_BASE_ITEM`** enforces the SO side billing on the base item, not the CP item.

---

## §5. Gate framework (ACCEPTED WITH AMENDMENT §5.1)

`workflows/core/gate_framework.py` — single module. Archetype modules self-register. Global-then-archetype evaluation order.

### §5.1 AMENDMENT: `gate_version` on both protocol and result

```python
@dataclass(frozen=True)
class GateResult:
    gate_id: str                       # stable identifier
    gate_version: str                  # §5.1 — default: sha256(evaluate source)[:12]; override with manual semver when tightening thresholds
    passed: bool
    severity: Literal["block", "warn", "info"]
    detail: str
    evidence: dict
    resolution_hint: str | None

class Gate(Protocol):
    id: str
    version: str                       # §5.1 — matches GateResult.gate_version at evaluation time
    archetype: str | None              # None = global
    applies_to_states: set[str]
    severity: str
    async def evaluate(self, ctx) -> GateResult: ...
```

**Rationale (Chad):** when a gate's threshold tightens (e.g., GP margin 5% → 6% for default archetypes), exceptions opened under the old version must be distinguishable from new. Without versioning, historical exception reports lie.

**Default version:** content-hash of the `evaluate()` source (`hashlib.sha256(inspect.getsource(evaluate))[:12]`). Override with manual semver (`"1.2.0"`) when a threshold change is significant enough to warrant a human-readable bump.

Gate registration, evaluation API, and global-then-archetype order unchanged from original declaration.

---

## §6. EOD controller + exception queues (ACCEPTED WITH AMENDMENT §6.1)

Endpoint shape and taxonomy as previously specified, **except**:

### §6.1 AMENDMENT: 10-type exception taxonomy (Chad chose option (a))

Round-number promise broken in favor of honest semantics. The canonical list is now:

1. `missing_master_data`
2. `duplicate_invoice_risk`
3. `low_inventory`
4. `missing_freight_docs`
5. `receipt_invoice_mismatch`
6. `cost_mismatch`
7. `location_division_mismatch`
8. `partial_post`
9. `archived_doc_collision`         — means "the doc is already archived somewhere else"; no overloading
10. **`intentional_send_skip`** (`severity=info`) — the EOD `send_posted_docs` zero-amount skip writes here; reviewers can audit without it appearing as a failure

All 10 enumerated in `workflows/batch/exception_queues.py` as a `Literal` type; no string-literal sprawl.

EOD endpoint behavior unchanged from original declaration. `send_posted_docs` step now routes zero-amount skips to `intentional_send_skip(severity=info)`, not to `archived_doc_collision`.

---

## §7. Execution order this session

| Phase | Item | Gated on |
|---|---|---|
| 1 | Write this signed scope memo | — |
| 2 | **A1** — posting-attempts history (schema migration + write-path + frontend accordion + tests) | — |
| 3 | **A2** — retry/backoff wrapper on BC HTTP (3 retries, jitter, circuit-break; appends to A1 history) | A1 |
| 4 | **A4** — pre-claim `workflow_engine.advance_workflow` on Phase 5 endpoint | — (parallel-safe with A2) |
| 5 | Full regression + `testing_agent_v3_fork` for Lane A | A1 + A2 + A4 |
| 6 | **A3** — Phase 4 Path B removal PR | **Externally gated** on 7-UTC-day `phase_4_gate.gate_met=true`. Not deliverable in this session. A3 branch will be prepared and documented; merge awaits the drain clock. |

**A3 out-of-band status:** I will prepare the A3 changeset (route deletions + orphan-function deletions + test file flip) as a ready-to-merge PR at the end of this session, clearly documented as "DO NOT MERGE until 7-UTC-day gate met per §1 clock semantics". Chad will merge it when the drain clock matures.

---

## Signed scope: locked. Lane A A1 begins immediately on this memo's commit.
