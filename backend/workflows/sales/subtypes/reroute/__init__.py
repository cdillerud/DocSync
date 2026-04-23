"""Reroute archetype package (Lane C Step 7).

Unwired-foundation gate scaffolding at the sales-archetype layer for
the Reroute flow (warehouse order rerouted to drop-ship, indicated by
``location_code == "001"``).

CRITICAL BOUNDARY: The freight-side reroute logic is MATURE and
AUTHORITATIVE for freight behavior, and is EXPLICITLY untouched by
this package:
  - ``workflows/freight/item_charges.LOCATION_REROUTED``
  - ``services/freight_gl_routing_service`` (rerouted SO handling)
  - ``services/bc_reference_cache_service.find_so_for_rerouted_po``

This package only adds a sales-archetype diagnostic/gate surface. It
does NOT:
  - route anything
  - resolve SO references
  - write to freight GL classification
  - touch location-code infra
  - become a second freight-routing authority
"""

from .rules import (
    ARCHETYPE,
    RerouteLocationWithoutOriginalSoGate,
    RerouteRequiresDropShipLinkageGate,
    register_reroute_gates,
)

__all__ = [
    "ARCHETYPE",
    "RerouteLocationWithoutOriginalSoGate",
    "RerouteRequiresDropShipLinkageGate",
    "register_reroute_gates",
]
