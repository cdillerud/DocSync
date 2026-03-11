"""
GPI Document Hub — Document Processor Base Class

All document family processors must inherit from this base.
Processors are stateless, pure-extraction, and safe (no BC writes, no validation bypass).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any


class DocumentProcessor(ABC):
    """
    Base class for document family processors.

    Lifecycle:
        1. detect()  — called by registry to check if this processor handles the doc
        2. extract() — pull structured fields from the document text
        3. suggest_vendor()     — optional vendor inference
        4. suggest_references() — return reference candidates for the resolver
    """

    # Human-readable name shown in diagnostics
    name: str = "BaseProcessor"
    # Priority (lower = checked first). Default processors use 100–199.
    priority: int = 100

    @abstractmethod
    def detect(self, document_text: str, layout_fingerprint: Optional[Dict] = None,
               ai_classification: Optional[Dict] = None) -> bool:
        """Return True if this processor should handle the document."""
        ...

    @abstractmethod
    def extract(self, document_text: str, layout_fingerprint: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Return structured fields extracted from the document.
        Keys should be snake_case field names. Values are raw strings or lists.
        """
        ...

    def suggest_vendor(self, extracted_fields: Dict[str, Any]) -> Optional[str]:
        """
        Optional: infer a vendor name from extracted fields.
        Return None to skip vendor suggestion.
        """
        return None

    def suggest_references(self, extracted_fields: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Return reference candidates for the resolver.
        Each entry: {"label": "PO Number", "value": "111428", "source": "processor"}
        """
        return []

    def get_diagnostics(self, extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
        """Return diagnostics info for the matching debug panel."""
        return {
            "processor_name": self.name,
            "fields_extracted": list(extracted_fields.keys()),
            "field_count": len(extracted_fields),
        }
