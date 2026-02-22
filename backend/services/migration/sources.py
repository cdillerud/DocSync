"""
GPI Document Hub - Legacy Document Sources

This module defines the abstraction for legacy document sources and provides
concrete implementations for testing and development.

The LegacyDocumentSource abstraction allows the migration job to work with
any source of legacy data without being tied to specific external systems.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, Iterator, List
from enum import Enum

logger = logging.getLogger(__name__)


class LegacySystem(str, Enum):
    """Legacy system identifiers."""
    SQUARE9 = "SQUARE9"
    ZETADOCS = "ZETADOCS"


@dataclass
class LegacyDocumentMetadata:
    """
    Metadata for a legacy document.
    
    This represents the information available from Square9 or Zetadocs exports.
    Not all fields will be populated for every document.
    """
    # Source identification
    legacy_system: str  # "SQUARE9" or "ZETADOCS"
    legacy_id: str      # Original primary key from the legacy system
    
    # System-specific identifiers
    legacy_workflow_name: Optional[str] = None      # Square9 workflow name
    legacy_zetadocs_set_code: Optional[str] = None  # Zetadocs set code (ZD00015, etc.)
    legacy_bc_doc_no: Optional[str] = None          # BC document number if linked
    
    # Business fields (may vary by document type)
    vendor_name: Optional[str] = None
    vendor_no: Optional[str] = None
    customer_name: Optional[str] = None
    customer_no: Optional[str] = None
    invoice_number: Optional[str] = None
    document_number: Optional[str] = None
    po_number: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    posting_date: Optional[str] = None
    
    # Quality doc specific
    quality_tags: Optional[List[str]] = None
    quality_category: Optional[str] = None
    
    # Status flags from legacy system
    is_paid: bool = False
    is_posted: bool = False
    is_exported: bool = False
    is_approved: bool = False
    is_canceled: bool = False
    is_voided: bool = False
    is_closed: bool = False
    is_reviewed: bool = False
    
    # Additional metadata
    created_date: Optional[str] = None
    modified_date: Optional[str] = None
    created_by: Optional[str] = None
    
    # Extra fields for flexibility
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values and empty extras."""
        result = {
            "legacy_system": self.legacy_system,
            "legacy_id": self.legacy_id,
        }
        
        # Add optional fields if present
        optional_fields = [
            "legacy_workflow_name", "legacy_zetadocs_set_code", "legacy_bc_doc_no",
            "vendor_name", "vendor_no", "customer_name", "customer_no",
            "invoice_number", "document_number", "po_number",
            "amount", "currency", "invoice_date", "due_date", "posting_date",
            "quality_tags", "quality_category",
            "created_date", "modified_date", "created_by"
        ]
        
        for field_name in optional_fields:
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        
        # Add boolean flags only if True
        boolean_flags = [
            "is_paid", "is_posted", "is_exported", "is_approved",
            "is_canceled", "is_voided", "is_closed", "is_reviewed"
        ]
        
        for flag in boolean_flags:
            if getattr(self, flag):
                result[flag] = True
        
        # Add extra fields
        if self.extra:
            result["extra"] = self.extra
        
        return result


@dataclass
class LegacyDocument:
    """
    A legacy document ready for migration.
    
    Contains the metadata and a reference to the binary content.
    """
    metadata: LegacyDocumentMetadata
    binary_reference: Optional[str] = None  # File path, URL, or storage key
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "metadata": self.metadata.to_dict(),
        }
        if self.binary_reference:
            result["binary_reference"] = self.binary_reference
        return result


class LegacyDocumentSource(ABC):
    """
    Abstract base class for legacy document sources.
    
    Implementations can connect to real legacy systems (Square9 API, Zetadocs export files)
    or provide test data for development and testing.
    """
    
    @abstractmethod
    def iter_documents(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Iterator[LegacyDocument]:
        """
        Iterate over legacy documents matching the filters.
        
        Args:
            source_filter: Filter by legacy system ("SQUARE9", "ZETADOCS")
            doc_type_filter: Filter by document type hint (e.g., "AP_INVOICE")
            limit: Maximum number of documents to yield
            
        Yields:
            LegacyDocument objects ready for migration
        """
        pass
    
    @abstractmethod
    def get_document_count(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None
    ) -> int:
        """
        Get the count of documents matching the filters.
        
        Useful for progress reporting and planning.
        """
        pass
    
    @abstractmethod
    def get_source_name(self) -> str:
        """Return a descriptive name for this source."""
        pass


class InMemorySource(LegacyDocumentSource):
    """
    In-memory document source for testing.
    
    Documents can be added programmatically.
    """
    
    def __init__(self, name: str = "in_memory"):
        self._name = name
        self._documents: List[LegacyDocument] = []
    
    def add_document(self, doc: LegacyDocument) -> None:
        """Add a document to the source."""
        self._documents.append(doc)
    
    def add_documents(self, docs: List[LegacyDocument]) -> None:
        """Add multiple documents to the source."""
        self._documents.extend(docs)
    
    def clear(self) -> None:
        """Remove all documents."""
        self._documents.clear()
    
    def iter_documents(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Iterator[LegacyDocument]:
        count = 0
        for doc in self._documents:
            # Apply source filter
            if source_filter and doc.metadata.legacy_system != source_filter:
                continue
            
            # Apply doc_type filter (based on workflow/set hints)
            if doc_type_filter:
                doc_type_hint = self._get_doc_type_hint(doc.metadata)
                if doc_type_hint and doc_type_hint != doc_type_filter:
                    continue
            
            # Apply limit
            if limit and count >= limit:
                break
            
            yield doc
            count += 1
    
    def get_document_count(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None
    ) -> int:
        return sum(1 for _ in self.iter_documents(source_filter, doc_type_filter))
    
    def get_source_name(self) -> str:
        return self._name
    
    def _get_doc_type_hint(self, metadata: LegacyDocumentMetadata) -> Optional[str]:
        """Get doc_type hint from metadata."""
        # Check Zetadocs set code
        zetadocs_mapping = {
            "ZD00015": "AP_INVOICE",
            "ZD00007": "SALES_INVOICE",
            "ZD00002": "PURCHASE_ORDER",
            "ZD00009": "SALES_CREDIT_MEMO",
        }
        if metadata.legacy_zetadocs_set_code:
            return zetadocs_mapping.get(metadata.legacy_zetadocs_set_code)
        
        # Check Square9 workflow
        square9_mapping = {
            "AP_Invoice": "AP_INVOICE",
            "AP Invoice": "AP_INVOICE",
            "Sales Invoice": "SALES_INVOICE",
            "Purchase Order": "PURCHASE_ORDER",
            "Statement": "STATEMENT",
        }
        if metadata.legacy_workflow_name:
            return square9_mapping.get(metadata.legacy_workflow_name)
        
        return None


class JsonFileSource(LegacyDocumentSource):
    """
    JSON file-based document source for testing and batch imports.
    
    Reads legacy documents from a JSON file with the following structure:
    {
        "source_name": "Legacy Export 2024-01",
        "exported_at": "2024-01-15T10:00:00Z",
        "documents": [
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-12345",
                    "legacy_workflow_name": "AP_Invoice",
                    "vendor_name": "Acme Corp",
                    ...
                },
                "binary_reference": "/exports/2024/12345.pdf"
            },
            ...
        ]
    }
    """
    
    def __init__(self, file_path: str):
        self._file_path = Path(file_path)
        self._data: Optional[Dict] = None
        self._documents: Optional[List[LegacyDocument]] = None
    
    def _load(self) -> None:
        """Load and parse the JSON file."""
        if self._data is not None:
            return
        
        if not self._file_path.exists():
            raise FileNotFoundError(f"Migration source file not found: {self._file_path}")
        
        with open(self._file_path, 'r', encoding='utf-8') as f:
            self._data = json.load(f)
        
        self._documents = []
        for doc_data in self._data.get("documents", []):
            metadata_dict = doc_data.get("metadata", {})
            
            # Handle quality_tags as list
            quality_tags = metadata_dict.get("quality_tags")
            if quality_tags and isinstance(quality_tags, str):
                quality_tags = [t.strip() for t in quality_tags.split(",")]
            
            metadata = LegacyDocumentMetadata(
                legacy_system=metadata_dict.get("legacy_system", "UNKNOWN"),
                legacy_id=metadata_dict.get("legacy_id", ""),
                legacy_workflow_name=metadata_dict.get("legacy_workflow_name"),
                legacy_zetadocs_set_code=metadata_dict.get("legacy_zetadocs_set_code"),
                legacy_bc_doc_no=metadata_dict.get("legacy_bc_doc_no"),
                vendor_name=metadata_dict.get("vendor_name"),
                vendor_no=metadata_dict.get("vendor_no"),
                customer_name=metadata_dict.get("customer_name"),
                customer_no=metadata_dict.get("customer_no"),
                invoice_number=metadata_dict.get("invoice_number"),
                document_number=metadata_dict.get("document_number"),
                po_number=metadata_dict.get("po_number"),
                amount=metadata_dict.get("amount"),
                currency=metadata_dict.get("currency"),
                invoice_date=metadata_dict.get("invoice_date"),
                due_date=metadata_dict.get("due_date"),
                posting_date=metadata_dict.get("posting_date"),
                quality_tags=quality_tags,
                quality_category=metadata_dict.get("quality_category"),
                is_paid=metadata_dict.get("is_paid", False),
                is_posted=metadata_dict.get("is_posted", False),
                is_exported=metadata_dict.get("is_exported", False),
                is_approved=metadata_dict.get("is_approved", False),
                is_canceled=metadata_dict.get("is_canceled", False),
                is_voided=metadata_dict.get("is_voided", False),
                is_closed=metadata_dict.get("is_closed", False),
                is_reviewed=metadata_dict.get("is_reviewed", False),
                created_date=metadata_dict.get("created_date"),
                modified_date=metadata_dict.get("modified_date"),
                created_by=metadata_dict.get("created_by"),
                extra=metadata_dict.get("extra", {}),
            )
            
            doc = LegacyDocument(
                metadata=metadata,
                binary_reference=doc_data.get("binary_reference")
            )
            self._documents.append(doc)
        
        logger.info(f"Loaded {len(self._documents)} documents from {self._file_path}")
    
    def iter_documents(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Iterator[LegacyDocument]:
        self._load()
        
        count = 0
        for doc in self._documents:
            # Apply source filter
            if source_filter and doc.metadata.legacy_system != source_filter:
                continue
            
            # Apply doc_type filter
            if doc_type_filter:
                doc_type_hint = self._get_doc_type_hint(doc.metadata)
                if doc_type_hint and doc_type_hint != doc_type_filter:
                    continue
            
            # Apply limit
            if limit and count >= limit:
                break
            
            yield doc
            count += 1
    
    def get_document_count(
        self,
        source_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None
    ) -> int:
        self._load()
        return sum(1 for _ in self.iter_documents(source_filter, doc_type_filter))
    
    def get_source_name(self) -> str:
        self._load()
        return self._data.get("source_name", self._file_path.stem)
    
    def _get_doc_type_hint(self, metadata: LegacyDocumentMetadata) -> Optional[str]:
        """Get doc_type hint from metadata using the same logic as InMemorySource."""
        zetadocs_mapping = {
            "ZD00015": "AP_INVOICE",
            "ZD00007": "SALES_INVOICE", 
            "ZD00002": "PURCHASE_ORDER",
            "ZD00009": "SALES_CREDIT_MEMO",
        }
        if metadata.legacy_zetadocs_set_code:
            return zetadocs_mapping.get(metadata.legacy_zetadocs_set_code)
        
        square9_mapping = {
            "AP_Invoice": "AP_INVOICE",
            "AP Invoice": "AP_INVOICE",
            "Sales Invoice": "SALES_INVOICE",
            "Purchase Order": "PURCHASE_ORDER",
            "Statement": "STATEMENT",
            "Quality": "QUALITY_DOC",
        }
        if metadata.legacy_workflow_name:
            return square9_mapping.get(metadata.legacy_workflow_name)
        
        return None


def create_sample_migration_file(output_path: str) -> None:
    """
    Create a sample migration JSON file for testing.
    
    This generates a variety of document types with realistic metadata.
    """
    sample_data = {
        "source_name": "Sample Legacy Export",
        "exported_at": "2026-02-22T12:00:00Z",
        "documents": [
            # AP Invoices from Square9
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-AP-001",
                    "legacy_workflow_name": "AP_Invoice",
                    "vendor_name": "Acme Supplies Inc",
                    "vendor_no": "V10001",
                    "invoice_number": "INV-2024-0001",
                    "amount": 5250.00,
                    "currency": "USD",
                    "invoice_date": "2024-01-15",
                    "due_date": "2024-02-15",
                    "po_number": "PO-2024-0050",
                    "is_posted": True,
                    "is_paid": True,
                    "created_date": "2024-01-15T09:30:00Z"
                },
                "binary_reference": "/legacy/square9/ap/2024/INV-2024-0001.pdf"
            },
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-AP-002",
                    "legacy_workflow_name": "AP_Invoice",
                    "vendor_name": "Office Pro Ltd",
                    "vendor_no": "V10002",
                    "invoice_number": "INV-2024-0002",
                    "amount": 1200.50,
                    "currency": "USD",
                    "invoice_date": "2024-01-20",
                    "due_date": "2024-02-20",
                    "is_approved": True,
                    "is_posted": False,
                    "created_date": "2024-01-20T14:00:00Z"
                },
                "binary_reference": "/legacy/square9/ap/2024/INV-2024-0002.pdf"
            },
            # AP Invoice from Zetadocs
            {
                "metadata": {
                    "legacy_system": "ZETADOCS",
                    "legacy_id": "ZD-15-00123",
                    "legacy_zetadocs_set_code": "ZD00015",
                    "legacy_bc_doc_no": "PI-00123",
                    "vendor_name": "Global Parts Co",
                    "vendor_no": "V20001",
                    "invoice_number": "GP-2024-500",
                    "amount": 8750.00,
                    "currency": "EUR",
                    "invoice_date": "2024-02-01",
                    "due_date": "2024-03-01",
                    "is_exported": True,
                    "created_date": "2024-02-01T11:00:00Z"
                },
                "binary_reference": "/legacy/zetadocs/ZD00015/2024/GP-2024-500.pdf"
            },
            # Sales Invoice from Zetadocs
            {
                "metadata": {
                    "legacy_system": "ZETADOCS",
                    "legacy_id": "ZD-07-00456",
                    "legacy_zetadocs_set_code": "ZD00007",
                    "legacy_bc_doc_no": "SI-00456",
                    "customer_name": "Big Customer Inc",
                    "customer_no": "C30001",
                    "invoice_number": "SI-2024-0456",
                    "amount": 15000.00,
                    "currency": "USD",
                    "invoice_date": "2024-01-25",
                    "due_date": "2024-02-25",
                    "is_posted": True,
                    "is_exported": True,
                    "created_date": "2024-01-25T16:00:00Z"
                },
                "binary_reference": "/legacy/zetadocs/ZD00007/2024/SI-2024-0456.pdf"
            },
            # Purchase Order from Zetadocs
            {
                "metadata": {
                    "legacy_system": "ZETADOCS",
                    "legacy_id": "ZD-02-00789",
                    "legacy_zetadocs_set_code": "ZD00002",
                    "legacy_bc_doc_no": "PO-00789",
                    "vendor_name": "Equipment World",
                    "vendor_no": "V10005",
                    "document_number": "PO-2024-0789",
                    "amount": 25000.00,
                    "currency": "USD",
                    "is_closed": True,
                    "created_date": "2024-01-10T08:00:00Z"
                },
                "binary_reference": "/legacy/zetadocs/ZD00002/2024/PO-2024-0789.pdf"
            },
            {
                "metadata": {
                    "legacy_system": "ZETADOCS",
                    "legacy_id": "ZD-02-00790",
                    "legacy_zetadocs_set_code": "ZD00002",
                    "vendor_name": "Tech Supplies",
                    "vendor_no": "V10006",
                    "document_number": "PO-2024-0790",
                    "amount": 5500.00,
                    "currency": "USD",
                    "is_closed": False,
                    "is_approved": True,
                    "created_date": "2024-02-15T10:30:00Z"
                },
                "binary_reference": "/legacy/zetadocs/ZD00002/2024/PO-2024-0790.pdf"
            },
            # Statement from Square9
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-ST-001",
                    "legacy_workflow_name": "Statement",
                    "vendor_name": "Bank of Commerce",
                    "document_number": "STMT-2024-JAN",
                    "invoice_date": "2024-01-31",
                    "is_reviewed": True,
                    "created_date": "2024-02-01T09:00:00Z"
                },
                "binary_reference": "/legacy/square9/statements/2024/STMT-2024-JAN.pdf"
            },
            # Quality Doc from Square9
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-QD-001",
                    "legacy_workflow_name": "Quality",
                    "document_number": "QC-2024-0001",
                    "quality_tags": ["inspection", "passed"],
                    "quality_category": "Incoming Inspection",
                    "vendor_name": "Parts Supplier Co",
                    "is_reviewed": True,
                    "is_closed": True,
                    "created_date": "2024-01-18T14:30:00Z"
                },
                "binary_reference": "/legacy/square9/quality/2024/QC-2024-0001.pdf"
            },
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-QD-002",
                    "legacy_workflow_name": "Quality",
                    "document_number": "QC-2024-0002",
                    "quality_tags": ["inspection", "pending"],
                    "quality_category": "Final QC",
                    "is_reviewed": False,
                    "created_date": "2024-02-10T11:00:00Z"
                },
                "binary_reference": "/legacy/square9/quality/2024/QC-2024-0002.pdf"
            },
            # Unclassified document
            {
                "metadata": {
                    "legacy_system": "SQUARE9",
                    "legacy_id": "S9-MISC-001",
                    "document_number": "MISC-2024-001",
                    "created_date": "2024-02-20T09:00:00Z",
                    "extra": {"notes": "Unclassified correspondence"}
                },
                "binary_reference": "/legacy/square9/misc/2024/MISC-2024-001.pdf"
            }
        ]
    }
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(sample_data, f, indent=2)
    
    logger.info(f"Created sample migration file at {output_path}")
