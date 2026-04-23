"""Canonical shipment-method registry + rule engine (Lane C Step 2.5).

Unwired by design. See registry.py module docstring for convergence plan.
"""

from .registry import (
    PostBolUpdate,
    ShipmentMethodRecord,
    exists,
    get,
    list_all,
    list_by_region,
    list_codes,
    list_for_archetype,
)
from .rules import FREIGHT_VARIANCE_DEFAULT, ResolvedRules, resolve_rules

__all__ = [
    "PostBolUpdate",
    "ShipmentMethodRecord",
    "ResolvedRules",
    "FREIGHT_VARIANCE_DEFAULT",
    "exists",
    "get",
    "list_all",
    "list_by_region",
    "list_codes",
    "list_for_archetype",
    "resolve_rules",
]
