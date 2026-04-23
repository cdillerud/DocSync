"""Drop Ship archetype package (Lane C Step 6).

Authoritative-equivalent gate scaffolding for the Drop Ship archetype.
Parity with the live ``services.so_rules_engine._check_drop_ship_rules``
SO-008/SO-009 rules, implemented here as adapter-driven gates over the
canonical gate framework.

DS subtype classification remains the live responsibility of
``services.document_intel_helpers._classify_so_subtype``; gates read
``doc.so_subtype`` directly to avoid duplicating DS-detection logic.

Runtime unchanged in Step 6: gates are opt-in via
``register_drop_ship_gates``; the live evaluation path in
``services/so_rules_engine.py`` is not modified, wrapped, or deleted.
Wire-in is deferred to a later signed step after parity is proven.
"""

from .rules import (
    ARCHETYPE,
    DropShipInventoryLineNotMarkedGate,
    DropShipPoCostUnverifiedGate,
    DropShipPoMissingGate,
    register_drop_ship_gates,
)

__all__ = [
    "ARCHETYPE",
    "DropShipPoMissingGate",
    "DropShipPoCostUnverifiedGate",
    "DropShipInventoryLineNotMarkedGate",
    "register_drop_ship_gates",
]
