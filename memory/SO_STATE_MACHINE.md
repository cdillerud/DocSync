# P0.4 — SO State Machine (Canonical, Phase-1-Aware)

**Status:** STARTER PROPOSAL. Anchored on the Lucid SO flow inlined in directive `e2r7qm`. Approved during P0 review = blocking input for any future Phase 2 SO work.

**Phase 1 scope flag:** This document is *informational* for Phase 1. **Phase 1 does not implement any new SO state transitions** — that is Phase 2 (P1.D `Pending Prepayment` first-class state, G-SO-3 archetype gate registration, G-SO-4 drop-ship dependency state machine).

**G-SO-6 watchpoint:** if Phase 1 auth/RBAC work surfaces a hard dependency on `_check_drop_ship_rules` vs. `workflows/sales/subtypes/drop_ship/rules.py` (the dual surface), promote G-SO-6 to Phase 1 scope. **Active monitoring during P1.C** rollout.

## Canonical states (post-P1.D, when implemented)

```
                        ┌─────────────────────┐
   intake ───────────►  │ INTAKE_RECEIVED     │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ CLASSIFIED          │ (sales-order subtype: WH/DS/AOR/CST/PNH/RR)
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ READINESS_REVIEW    │ (sales_order_readiness_evaluator)
                        └──────┬───────┬──────┘
                               │       │
                fail ──────────┘       └──────── pass
                  │                              │
                  ▼                              ▼
       ┌───────────────────┐          ┌──────────────────────┐
       │ DATA_CORRECTION   │          │ AR_RELEASE_GATE      │ (5-check service)
       │ (reviewer-owned)  │          └──────┬─────────┬─────┘
       └───────────────────┘                 │         │
                                             │         │
                              held ──────────┘         └──── released
                                │                            │
                                ▼                            ▼
                  ┌─────────────────────────┐    ┌────────────────────┐
                  │ HELD                    │    │ READY_FOR_BC_CREATE│
                  │  (split per hold-cause):│    └────────┬───────────┘
                  │  • PENDING_APPROVAL ◄───┼──◄ approval-required
                  │  • PENDING_PREPAYMENT◄──┼──◄ prepay-only hold
                  │  • PENDING_CREDIT       │
                  │  • PENDING_TERMS        │             ▼
                  │  • PENDING_SHIPTO       │   (bc_sales_order_service)
                  └──────────┬──────────────┘
                             │
                  approver decision
                             │
                             ▼
                       (re-enters AR_RELEASE_GATE or aborts to ABORTED)

           ┌─────────────────────────┐
           │ BC_SO_CREATED           │ (auto_post_service.attempt_auto_create_sales_order)
           └────────┬────────────────┘
                    │
                    ▼
           ┌─────────────────────────┐
           │ SUBTYPE_RESOLUTION      │ (gate framework selects: WH/DS/AOR/CST/PNH/RR)
           └────────┬────────────────┘
                    │
            ┌───────┴───────┬──────────────┬────────────┐
            ▼               ▼              ▼            ▼
    ┌─────────────┐  ┌──────────────┐ ┌─────────┐ ┌──────────┐
    │ WH_PENDING  │  │ DS_PENDING_  │ │ ASSEMBLY│ │ STORAGE/ │
    │             │  │ VENDOR_PO    │ │ /PnH    │ │ REROUTE  │
    └──────┬──────┘  │ ↓            │ └────┬────┘ └────┬─────┘
           │         │ DS_VENDOR_PO_│      │           │
           │         │ CONFIRMED    │      │           │
           │         │ ↓            │      │           │
           │         │ DS_VENDOR_   │      │           │
           │         │ SHIPPED      │      │           │
           │         └──────┬───────┘      │           │
           │                │              │           │
           └────────────────┼──────────────┴───────────┘
                            ▼
                  ┌─────────────────────┐
                  │ FREIGHT_REQUIRED?   │ (freight_routing decision)
                  └────────┬───────┬────┘
                           │       │
                          yes      no
                           │       │
                           ▼       │
                ┌──────────────┐   │
                │ FREIGHT_     │   │
                │ COORDINATING│   │
                └──────┬───────┘   │
                       └─────┬─────┘
                             ▼
                  ┌─────────────────────┐
                  │ SHIPPED             │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ READY_TO_INVOICE    │ (G-SO-5 gate; Phase 2)
                  │ _GATE               │
                  └──────┬────────┬─────┘
                         │        │
                       held     ready
                         │        │
                         │        ▼
                         │  ┌──────────────────┐
                         │  │ INVOICE_POSTED   │ (bc_post_claim)
                         │  └────────┬─────────┘
                         │           │
                         │           ▼
                         │  ┌──────────────────┐
                         │  │ COMPLETE         │ (terminal)
                         │  └──────────────────┘
                         └────────► (back to HELD path)
```

## Phase 1 implications

- **No new state transitions land in Phase 1.** Existing implicit state lives in `workflow_status` field and `ar_release_gate.outcome`.
- The audit log (P1.A) captures every existing-state transition that occurs once `actor` context is present.
- G-SO-6 watchpoint: if drop-ship resolution path collides with auth changes, raise immediately and pause P1.C until resolved.

## Phase 2+ deliverables this state machine implies

- P1.D: Promote `PENDING_PREPAYMENT` to first-class.
- G-SO-3: Register the 6 SO archetype gates live (currently scaffolded with parity).
- G-SO-4: Implement DS_PENDING_VENDOR_PO → DS_VENDOR_PO_CONFIRMED → DS_VENDOR_SHIPPED transitions.
- G-SO-5: New `services/ready_to_invoice_gate_service.py`.
- G-SO-6: Drain-window deprecation of legacy `_check_drop_ship_rules`.
