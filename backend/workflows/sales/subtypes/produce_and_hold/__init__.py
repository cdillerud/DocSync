"""Produce & Hold archetype package (Lane C Step 4).

UNWIRED foundation. Classifier is orthogonal to the live DS/WH
classifier in services/document_intel_helpers.py. Gates are defined
but NOT auto-registered; opt-in via ``register_produce_and_hold_gates``.
"""

from .classification import (
    KNOWN_PH_CUSTOMERS,
    PH_AGING_THRESHOLD_DAYS,
    PH_BLANKET_DIVERGENCE_FRACTION,
    PH_CONFIDENCE_THRESHOLD,
    PHClassification,
    classify_produce_and_hold,
)
from .rules import (
    ARCHETYPE,
    ProduceAndHoldAgingGate,
    ProduceAndHoldBlanketMatchGate,
    ProduceAndHoldReleaseOverdrawGate,
    register_produce_and_hold_gates,
)

__all__ = [
    "ARCHETYPE",
    "PHClassification",
    "PH_CONFIDENCE_THRESHOLD",
    "PH_BLANKET_DIVERGENCE_FRACTION",
    "PH_AGING_THRESHOLD_DAYS",
    "KNOWN_PH_CUSTOMERS",
    "classify_produce_and_hold",
    "ProduceAndHoldReleaseOverdrawGate",
    "ProduceAndHoldBlanketMatchGate",
    "ProduceAndHoldAgingGate",
    "register_produce_and_hold_gates",
]
