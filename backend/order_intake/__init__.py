"""GPI customer order intake package.

Phase 0 keeps parsing/mapping evidence separate from Business Central mutation.
"""

from .customer_pdf_mapping import apply_profiled_customer_pdf_mapping
from .models import (
    DocumentType,
    NormalizedInboundOrder,
    NormalizedRelease,
    OrderCustomer,
    OrderDocument,
    OrderSource,
    OrderValidation,
    ProposedAction,
)

__all__ = [
    "DocumentType",
    "NormalizedInboundOrder",
    "NormalizedRelease",
    "OrderCustomer",
    "OrderDocument",
    "OrderSource",
    "OrderValidation",
    "ProposedAction",
    "apply_profiled_customer_pdf_mapping",
]
