"""Warehouse Order archetype package (Lane C Step 5).

First real consumer of the Step 2.5 shipment-method registry. Gates
defined here delegate shipment-method rule resolution to
``workflows.freight.shipment_methods.resolve_rules`` — no local copies
of shipment-method logic live in this package.

WH subtype classification remains the live responsibility of
``services.document_intel_helpers._classify_so_subtype``; gates read
``doc.so_subtype`` directly.

Opt-in registration via ``register_warehouse_order_gates``; not
auto-registered.
"""

from .rules import (
    ARCHETYPE,
    WarehouseOrderFreightExpectationMismatchGate,
    WarehouseOrderShipmentMethodArchetypeMismatchGate,
    WarehouseOrderShipmentMethodUnknownGate,
    register_warehouse_order_gates,
)

__all__ = [
    "ARCHETYPE",
    "WarehouseOrderShipmentMethodUnknownGate",
    "WarehouseOrderShipmentMethodArchetypeMismatchGate",
    "WarehouseOrderFreightExpectationMismatchGate",
    "register_warehouse_order_gates",
]
