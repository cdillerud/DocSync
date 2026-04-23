"""Customer Storage archetype package (Lane C Step 7).

Signal-driven, unwired-foundation gate scaffolding for the Customer
Storage archetype. No classifier. No registry. No writes.

Signals read from the document:
  - extracted_fields.storage_agreement_id
  - extracted_fields.storage_release_id
  - extracted_fields.is_customer_storage (boolean)
  - line_items[*].from_customer_storage (boolean)
  - line_items[*].quantity (for ship-out detection)

Out of scope:
  - AP S&H invoice classification (lives in folder_routing_service +
    freight_gl_routing_service.STORAGE_HANDLING_KEYWORDS — untouched)
  - Any customer-storage registry / collection
  - Any readiness-pipeline wire-in
"""

from .rules import (
    ARCHETYPE,
    CustomerStorageShipOutMissingReleaseGate,
    CustomerStorageWithoutStorageAgreementGate,
    register_customer_storage_gates,
)

__all__ = [
    "ARCHETYPE",
    "CustomerStorageWithoutStorageAgreementGate",
    "CustomerStorageShipOutMissingReleaseGate",
    "register_customer_storage_gates",
]
