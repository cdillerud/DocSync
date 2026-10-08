"""GPI Square9 Parity Engine shadow components.

V77 is deliberately unwired from live Hub decisioning.
"""

from services.parity_engine.contracts import (
    CANONICAL_DOCUMENT_TYPES,
    canonical_classification_schema,
    fail_closed_result,
)
from services.parity_engine.function_gateway_provider import (
    FunctionGatewayProvider,
)
from services.parity_engine.shadow_classifier import (
    ShadowClassifier,
)

__all__ = [
    "CANONICAL_DOCUMENT_TYPES",
    "FunctionGatewayProvider",
    "ShadowClassifier",
    "canonical_classification_schema",
    "fail_closed_result",
]
