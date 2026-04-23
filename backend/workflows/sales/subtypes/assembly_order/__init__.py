"""Assembly Order archetype package (Lane C Step 4b).

UNWIRED foundation, sibling to Produce & Hold. Classifier orthogonal to
the live DS/WH classifier. Gates defined but NOT auto-registered;
opt-in via ``register_assembly_order_gates``.
"""

from .classification import (
    ASSEMBLY_BOM_COMPLETENESS_STRICT,
    ASSEMBLY_CONFIDENCE_THRESHOLD,
    AssemblyClassification,
    KNOWN_ASSEMBLY_CUSTOMERS,
    classify_assembly_order,
)
from .rules import (
    ARCHETYPE,
    AssemblyOrderBomCompletenessGate,
    AssemblyOrderProducedOverdrawGate,
    register_assembly_order_gates,
)

__all__ = [
    "ARCHETYPE",
    "AssemblyClassification",
    "ASSEMBLY_CONFIDENCE_THRESHOLD",
    "ASSEMBLY_BOM_COMPLETENESS_STRICT",
    "KNOWN_ASSEMBLY_CUSTOMERS",
    "classify_assembly_order",
    "AssemblyOrderProducedOverdrawGate",
    "AssemblyOrderBomCompletenessGate",
    "register_assembly_order_gates",
]
