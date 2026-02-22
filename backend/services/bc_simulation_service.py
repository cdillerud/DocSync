"""
GPI Document Hub - Business Central Simulation Service

Phase 2 of Shadow Pilot: Simulated BC Write Operations

This module simulates all BC write operations internally without calling real BC APIs.
All simulations are:
- Deterministic (same input = same output)
- Logged to workflow history
- Stored in MongoDB for analysis
- Only active when pilot_mode is true

NO REAL BC WRITE CALLS. SIMULATION ONLY.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
import uuid

from services.pilot_config import (
    PILOT_MODE_ENABLED, CURRENT_PILOT_PHASE,
    is_external_write_blocked
)

logger = logging.getLogger(__name__)


# =============================================================================
# SIMULATION CONFIGURATION
# =============================================================================

# Simulated BC company/environment
SIMULATED_BC_COMPANY_ID = "sim-company-001"
SIMULATED_BC_COMPANY_NAME = "GPI Packaging Ltd (Simulated)"
SIMULATED_BC_ENVIRONMENT = "Sandbox-Simulation"

# Simulation version for tracking
SIMULATION_VERSION = "1.0.0"


# =============================================================================
# SIMULATION STATUS TYPES
# =============================================================================

class SimulationStatus(str, Enum):
    """Status of a simulation operation."""
    SUCCESS = "success"
    WOULD_FAIL = "would_fail"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    ERROR = "error"


class SimulationType(str, Enum):
    """Types of simulated operations."""
    EXPORT_AP_INVOICE = "export_ap_invoice"
    CREATE_PURCHASE_INVOICE = "create_purchase_invoice"
    ATTACH_PDF = "attach_pdf"
    EXPORT_SALES_INVOICE = "export_sales_invoice"
    PO_LINKAGE = "po_linkage"


# =============================================================================
# SIMULATION RESULT CLASS
# =============================================================================

class SimulationResult:
    """Result of a simulated BC operation."""
    
    def __init__(
        self,
        simulation_type: SimulationType,
        status: SimulationStatus,
        document_id: str,
        simulated_bc_response: Dict[str, Any],
        simulated_bc_payload: Dict[str, Any],
        validation_checks: List[Dict[str, Any]] = None,
        would_succeed_in_production: bool = True,
        failure_reason: str = None,
        timing_ms: int = 0
    ):
        self.simulation_id = str(uuid.uuid4())
        self.simulation_type = simulation_type
        self.status = status
        self.document_id = document_id
        self.simulated_bc_response = simulated_bc_response
        self.simulated_bc_payload = simulated_bc_payload
        self.validation_checks = validation_checks or []
        self.would_succeed_in_production = would_succeed_in_production
        self.failure_reason = failure_reason
        self.timing_ms = timing_ms
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.pilot_phase = CURRENT_PILOT_PHASE
        self.simulation_version = SIMULATION_VERSION
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "simulation_id": self.simulation_id,
            "simulation_type": self.simulation_type.value,
            "status": self.status.value,
            "document_id": self.document_id,
            "simulated_bc_response": self.simulated_bc_response,
            "simulated_bc_payload": self.simulated_bc_payload,
            "validation_checks": self.validation_checks,
            "would_succeed_in_production": self.would_succeed_in_production,
            "failure_reason": self.failure_reason,
            "timing_ms": self.timing_ms,
            "timestamp": self.timestamp,
            "pilot_phase": self.pilot_phase,
            "simulation_version": self.simulation_version
        }
    
    def to_workflow_entry(self, actor: str = "bc_simulation_service") -> Dict[str, Any]:
        """Create workflow history entry for this simulation."""
        return {
            "timestamp": self.timestamp,
            "event": f"simulated_{self.simulation_type.value}",
            "actor": actor,
            "simulation": {
                "simulation_id": self.simulation_id,
                "type": self.simulation_type.value,
                "status": self.status.value,
                "would_succeed": self.would_succeed_in_production,
                "failure_reason": self.failure_reason,
                "bc_response_summary": _summarize_bc_response(self.simulated_bc_response),
            },
            "observation_only": True,
            "pilot_mode": True,
            "pilot_phase": self.pilot_phase
        }


def _summarize_bc_response(response: Dict) -> Dict:
    """Create a summary of the BC response for workflow history."""
    if not response:
        return {}
    return {
        "id": response.get("id"),
        "number": response.get("number"),
        "status": response.get("status"),
    }


# =============================================================================
# DETERMINISTIC ID GENERATION
# =============================================================================

def generate_simulated_bc_id(document_id: str, operation: str) -> str:
    """
    Generate a deterministic BC ID for simulation.
    Same inputs always produce same output.
    """
    seed = f"{document_id}:{operation}:{SIMULATION_VERSION}"
    hash_bytes = hashlib.sha256(seed.encode()).hexdigest()[:32]
    return f"sim-{hash_bytes}"


def generate_simulated_bc_number(prefix: str, document_id: str) -> str:
    """Generate a deterministic BC document number."""
    seed = f"{document_id}:{prefix}"
    hash_num = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) % 100000
    return f"{prefix}-SIM-{hash_num:05d}"


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_document_for_export(document: Dict) -> Tuple[bool, List[Dict]]:
    """
    Validate a document is ready for export simulation.
    Returns (is_valid, validation_checks).
    """
    checks = []
    
    # Check 1: Document has required fields
    has_doc_type = bool(document.get("doc_type"))
    checks.append({
        "check": "has_doc_type",
        "passed": has_doc_type,
        "value": document.get("doc_type")
    })
    
    # Check 2: Document has workflow status
    has_status = bool(document.get("workflow_status"))
    checks.append({
        "check": "has_workflow_status",
        "passed": has_status,
        "value": document.get("workflow_status")
    })
    
    # Check 3: Document is approved (for export)
    workflow_status = document.get("workflow_status", "")
    is_approved = workflow_status in ["approved", "ready_for_approval", "exported", "ready_for_export"]
    checks.append({
        "check": "is_approved_or_ready",
        "passed": is_approved,
        "value": workflow_status
    })
    
    is_valid = all(c["passed"] for c in checks)
    return is_valid, checks


def validate_ap_invoice_for_bc(document: Dict) -> Tuple[bool, List[Dict], str]:
    """
    Validate an AP invoice document has all required fields for BC creation.
    Returns (is_valid, validation_checks, failure_reason).
    """
    checks = []
    failure_reasons = []
    
    # Check 1: Has vendor
    vendor = document.get("vendor_canonical") or document.get("vendor_raw") or document.get("extracted_data", {}).get("vendor_number")
    has_vendor = bool(vendor)
    checks.append({
        "check": "has_vendor",
        "passed": has_vendor,
        "value": vendor
    })
    if not has_vendor:
        failure_reasons.append("Missing vendor number")
    
    # Check 2: Has invoice number
    invoice_num = document.get("invoice_number") or document.get("extracted_data", {}).get("invoice_number")
    has_invoice_num = bool(invoice_num)
    checks.append({
        "check": "has_invoice_number",
        "passed": has_invoice_num,
        "value": invoice_num
    })
    if not has_invoice_num:
        failure_reasons.append("Missing invoice number")
    
    # Check 3: Has amount
    amount = document.get("amount") or document.get("extracted_data", {}).get("total_amount")
    has_amount = amount is not None
    checks.append({
        "check": "has_amount",
        "passed": has_amount,
        "value": amount
    })
    if not has_amount:
        failure_reasons.append("Missing amount")
    
    # Check 4: Has posting date or invoice date
    date = document.get("invoice_date") or document.get("extracted_data", {}).get("invoice_date")
    has_date = bool(date)
    checks.append({
        "check": "has_date",
        "passed": has_date,
        "value": date
    })
    
    is_valid = has_vendor and has_invoice_num and has_amount
    failure_reason = "; ".join(failure_reasons) if failure_reasons else None
    
    return is_valid, checks, failure_reason


def validate_sales_invoice_for_export(document: Dict) -> Tuple[bool, List[Dict], str]:
    """Validate a sales invoice for export simulation."""
    checks = []
    failure_reasons = []
    
    # Check 1: Has customer
    customer = document.get("customer_number") or document.get("extracted_data", {}).get("customer_number")
    has_customer = bool(customer)
    checks.append({
        "check": "has_customer",
        "passed": has_customer,
        "value": customer
    })
    if not has_customer:
        failure_reasons.append("Missing customer number")
    
    # Check 2: Has invoice number
    invoice_num = document.get("invoice_number") or document.get("extracted_data", {}).get("invoice_number")
    has_invoice_num = bool(invoice_num)
    checks.append({
        "check": "has_invoice_number",
        "passed": has_invoice_num,
        "value": invoice_num
    })
    
    is_valid = has_customer
    failure_reason = "; ".join(failure_reasons) if failure_reasons else None
    
    return is_valid, checks, failure_reason


def validate_po_for_linkage(document: Dict) -> Tuple[bool, List[Dict], str]:
    """Validate a PO document for linkage simulation."""
    checks = []
    failure_reasons = []
    
    # Check 1: Has PO number
    po_number = document.get("po_number") or document.get("extracted_data", {}).get("po_number")
    has_po = bool(po_number)
    checks.append({
        "check": "has_po_number",
        "passed": has_po,
        "value": po_number
    })
    if not has_po:
        failure_reasons.append("Missing PO number")
    
    # Check 2: Has vendor
    vendor = document.get("vendor_canonical") or document.get("vendor_raw")
    has_vendor = bool(vendor)
    checks.append({
        "check": "has_vendor",
        "passed": has_vendor,
        "value": vendor
    })
    
    is_valid = has_po
    failure_reason = "; ".join(failure_reasons) if failure_reasons else None
    
    return is_valid, checks, failure_reason


# =============================================================================
# SIMULATION FUNCTIONS
# =============================================================================

def simulate_export_ap_invoice(document: Dict) -> SimulationResult:
    """
    Simulate exporting an AP invoice to BC.
    
    This generates what WOULD be sent to BC without actually calling the API.
    
    Args:
        document: The document dict from hub_documents
        
    Returns:
        SimulationResult with simulated BC response
    """
    import time
    start_time = time.time()
    
    document_id = document.get("document_id", "unknown")
    
    logger.info("BC Simulation: simulate_export_ap_invoice called, doc_id=%s", document_id)
    
    # Validate document
    is_valid, checks, failure_reason = validate_ap_invoice_for_bc(document)
    
    # Build simulated BC payload
    vendor = document.get("vendor_canonical") or document.get("vendor_raw") or document.get("extracted_data", {}).get("vendor_number")
    invoice_num = document.get("invoice_number") or document.get("extracted_data", {}).get("invoice_number")
    amount = document.get("amount") or document.get("extracted_data", {}).get("total_amount") or 0
    invoice_date = document.get("invoice_date") or document.get("extracted_data", {}).get("invoice_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    po_number = document.get("po_number") or document.get("extracted_data", {}).get("po_number")
    
    simulated_payload = {
        "vendorNumber": vendor,
        "vendorInvoiceNumber": invoice_num,
        "invoiceDate": invoice_date,
        "postingDate": invoice_date,
        "totalAmountIncludingTax": float(amount) if amount else 0.0,
        "purchaseOrderNumber": po_number,
        "currencyCode": "USD",
        "payToVendorNumber": vendor,
        # Metadata
        "_gpi_hub_document_id": document_id,
        "_gpi_hub_simulation": True,
        "_gpi_hub_pilot_phase": CURRENT_PILOT_PHASE
    }
    
    # Generate deterministic BC response
    simulated_bc_id = generate_simulated_bc_id(document_id, "export_ap_invoice")
    simulated_bc_number = generate_simulated_bc_number("PI", document_id)
    
    simulated_response = {
        "id": simulated_bc_id,
        "number": simulated_bc_number,
        "vendorNumber": vendor,
        "vendorName": document.get("vendor_name", f"Vendor {vendor}"),
        "vendorInvoiceNumber": invoice_num,
        "postingDate": invoice_date,
        "status": "Draft" if is_valid else "Error",
        "totalAmountIncludingTax": float(amount) if amount else 0.0,
        "lastModifiedDateTime": datetime.now(timezone.utc).isoformat(),
        "_simulated": True,
        "_simulation_timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    status = SimulationStatus.SUCCESS if is_valid else SimulationStatus.WOULD_FAIL
    
    result = SimulationResult(
        simulation_type=SimulationType.EXPORT_AP_INVOICE,
        status=status,
        document_id=document_id,
        simulated_bc_response=simulated_response,
        simulated_bc_payload=simulated_payload,
        validation_checks=checks,
        would_succeed_in_production=is_valid,
        failure_reason=failure_reason,
        timing_ms=elapsed_ms
    )
    
    logger.info(
        "BC Simulation: simulate_export_ap_invoice complete, doc_id=%s, would_succeed=%s, timing=%dms",
        document_id, is_valid, elapsed_ms
    )
    
    return result


def simulate_create_purchase_invoice(document: Dict) -> SimulationResult:
    """
    Simulate creating a purchase invoice in BC (draft creation).
    
    Args:
        document: The document dict
        
    Returns:
        SimulationResult with simulated BC response
    """
    import time
    start_time = time.time()
    
    document_id = document.get("document_id", "unknown")
    
    logger.info("BC Simulation: simulate_create_purchase_invoice called, doc_id=%s", document_id)
    
    # Validate
    is_valid, checks, failure_reason = validate_ap_invoice_for_bc(document)
    
    # Extract fields
    vendor = document.get("vendor_canonical") or document.get("vendor_raw") or ""
    invoice_num = document.get("invoice_number") or document.get("extracted_data", {}).get("invoice_number") or ""
    amount = document.get("amount") or document.get("extracted_data", {}).get("total_amount") or 0
    invoice_date = document.get("invoice_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Build payload for BC purchaseInvoices endpoint
    simulated_payload = {
        "vendorNumber": vendor,
        "vendorInvoiceNumber": invoice_num,
        "invoiceDate": invoice_date,
        "postingDate": invoice_date,
        "currencyCode": "USD",
        "pricesIncludeTax": False,
        "_gpi_hub_document_id": document_id,
        "_gpi_hub_simulation": True
    }
    
    # Generate deterministic response
    simulated_bc_id = generate_simulated_bc_id(document_id, "create_purchase_invoice")
    simulated_bc_number = generate_simulated_bc_number("PI", document_id)
    
    simulated_response = {
        "id": simulated_bc_id,
        "number": simulated_bc_number,
        "vendorNumber": vendor,
        "vendorInvoiceNumber": invoice_num,
        "invoiceDate": invoice_date,
        "postingDate": invoice_date,
        "status": "Draft",
        "totalAmountIncludingTax": float(amount) if amount else 0.0,
        "totalAmountExcludingTax": float(amount) * 0.9 if amount else 0.0,
        "discountAmount": 0.0,
        "currencyCode": "USD",
        "paymentTermsId": "00000000-0000-0000-0000-000000000000",
        "shipmentMethodId": "00000000-0000-0000-0000-000000000000",
        "lastModifiedDateTime": datetime.now(timezone.utc).isoformat(),
        "_simulated": True
    }
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    status = SimulationStatus.SUCCESS if is_valid else SimulationStatus.WOULD_FAIL
    
    result = SimulationResult(
        simulation_type=SimulationType.CREATE_PURCHASE_INVOICE,
        status=status,
        document_id=document_id,
        simulated_bc_response=simulated_response,
        simulated_bc_payload=simulated_payload,
        validation_checks=checks,
        would_succeed_in_production=is_valid,
        failure_reason=failure_reason,
        timing_ms=elapsed_ms
    )
    
    logger.info(
        "BC Simulation: simulate_create_purchase_invoice complete, doc_id=%s, would_succeed=%s",
        document_id, is_valid
    )
    
    return result


def simulate_attach_pdf(document: Dict, pdf_filename: str = None) -> SimulationResult:
    """
    Simulate attaching a PDF to a BC record.
    
    Args:
        document: The document dict
        pdf_filename: Optional filename for the attachment
        
    Returns:
        SimulationResult with simulated attachment response
    """
    import time
    start_time = time.time()
    
    document_id = document.get("document_id", "unknown")
    filename = pdf_filename or document.get("original_filename", f"{document_id}.pdf")
    
    logger.info("BC Simulation: simulate_attach_pdf called, doc_id=%s, filename=%s", document_id, filename)
    
    # Check if document has SharePoint URL (file exists)
    sharepoint_url = document.get("sharepoint_url") or document.get("file_url")
    has_file = bool(sharepoint_url)
    
    checks = [
        {"check": "has_file_url", "passed": has_file, "value": sharepoint_url},
        {"check": "has_document_id", "passed": bool(document_id), "value": document_id}
    ]
    
    is_valid = has_file
    failure_reason = "No file URL available for attachment" if not has_file else None
    
    # Generate deterministic attachment response
    attachment_id = generate_simulated_bc_id(document_id, "attach_pdf")
    parent_id = generate_simulated_bc_id(document_id, "parent_record")
    
    simulated_payload = {
        "parentId": parent_id,
        "fileName": filename,
        "contentType": "application/pdf",
        "_gpi_hub_document_id": document_id,
        "_gpi_hub_source_url": sharepoint_url
    }
    
    simulated_response = {
        "id": attachment_id,
        "parentId": parent_id,
        "fileName": filename,
        "byteSize": document.get("file_size", 102400),  # Default 100KB
        "attachmentContent@odata.mediaReadLink": f"https://api.businesscentral.dynamics.com/.../attachments({attachment_id})/attachmentContent",
        "lastModifiedDateTime": datetime.now(timezone.utc).isoformat(),
        "_simulated": True
    }
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    status = SimulationStatus.SUCCESS if is_valid else SimulationStatus.WOULD_FAIL
    
    result = SimulationResult(
        simulation_type=SimulationType.ATTACH_PDF,
        status=status,
        document_id=document_id,
        simulated_bc_response=simulated_response,
        simulated_bc_payload=simulated_payload,
        validation_checks=checks,
        would_succeed_in_production=is_valid,
        failure_reason=failure_reason,
        timing_ms=elapsed_ms
    )
    
    logger.info(
        "BC Simulation: simulate_attach_pdf complete, doc_id=%s, would_succeed=%s",
        document_id, is_valid
    )
    
    return result


def simulate_sales_invoice_export(document: Dict) -> SimulationResult:
    """
    Simulate exporting a sales invoice to BC.
    
    Args:
        document: The document dict
        
    Returns:
        SimulationResult with simulated export response
    """
    import time
    start_time = time.time()
    
    document_id = document.get("document_id", "unknown")
    
    logger.info("BC Simulation: simulate_sales_invoice_export called, doc_id=%s", document_id)
    
    # Validate
    is_valid, checks, failure_reason = validate_sales_invoice_for_export(document)
    
    # Extract fields
    customer = document.get("customer_number") or document.get("extracted_data", {}).get("customer_number") or ""
    invoice_num = document.get("invoice_number") or document.get("extracted_data", {}).get("invoice_number") or ""
    amount = document.get("amount") or document.get("extracted_data", {}).get("total_amount") or 0
    invoice_date = document.get("invoice_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Build payload
    simulated_payload = {
        "customerNumber": customer,
        "invoiceDate": invoice_date,
        "externalDocumentNumber": invoice_num,
        "currencyCode": "USD",
        "_gpi_hub_document_id": document_id,
        "_gpi_hub_simulation": True
    }
    
    # Generate deterministic response
    simulated_bc_id = generate_simulated_bc_id(document_id, "export_sales_invoice")
    simulated_bc_number = generate_simulated_bc_number("SI", document_id)
    
    simulated_response = {
        "id": simulated_bc_id,
        "number": simulated_bc_number,
        "customerNumber": customer,
        "customerName": document.get("customer_name", f"Customer {customer}"),
        "invoiceDate": invoice_date,
        "status": "Draft" if is_valid else "Error",
        "totalAmountIncludingTax": float(amount) if amount else 0.0,
        "lastModifiedDateTime": datetime.now(timezone.utc).isoformat(),
        "_simulated": True
    }
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    status = SimulationStatus.SUCCESS if is_valid else SimulationStatus.WOULD_FAIL
    
    result = SimulationResult(
        simulation_type=SimulationType.EXPORT_SALES_INVOICE,
        status=status,
        document_id=document_id,
        simulated_bc_response=simulated_response,
        simulated_bc_payload=simulated_payload,
        validation_checks=checks,
        would_succeed_in_production=is_valid,
        failure_reason=failure_reason,
        timing_ms=elapsed_ms
    )
    
    logger.info(
        "BC Simulation: simulate_sales_invoice_export complete, doc_id=%s, would_succeed=%s",
        document_id, is_valid
    )
    
    return result


def simulate_po_linkage(document: Dict) -> SimulationResult:
    """
    Simulate linking a document to a Purchase Order in BC.
    
    Args:
        document: The document dict
        
    Returns:
        SimulationResult with simulated linkage response
    """
    import time
    start_time = time.time()
    
    document_id = document.get("document_id", "unknown")
    
    logger.info("BC Simulation: simulate_po_linkage called, doc_id=%s", document_id)
    
    # Validate
    is_valid, checks, failure_reason = validate_po_for_linkage(document)
    
    # Extract fields
    po_number = document.get("po_number") or document.get("extracted_data", {}).get("po_number") or ""
    vendor = document.get("vendor_canonical") or document.get("vendor_raw") or ""
    
    # Build payload
    simulated_payload = {
        "purchaseOrderNumber": po_number,
        "vendorNumber": vendor,
        "linkedDocumentId": document_id,
        "_gpi_hub_document_id": document_id,
        "_gpi_hub_simulation": True
    }
    
    # Generate deterministic response
    simulated_bc_id = generate_simulated_bc_id(document_id, "po_linkage")
    simulated_po_id = generate_simulated_bc_id(po_number, "po_record")
    
    simulated_response = {
        "id": simulated_bc_id,
        "purchaseOrderId": simulated_po_id,
        "purchaseOrderNumber": po_number,
        "vendorNumber": vendor,
        "linkStatus": "Linked" if is_valid else "Failed",
        "linkedDocumentId": document_id,
        "lastModifiedDateTime": datetime.now(timezone.utc).isoformat(),
        "_simulated": True
    }
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    status = SimulationStatus.SUCCESS if is_valid else SimulationStatus.WOULD_FAIL
    
    result = SimulationResult(
        simulation_type=SimulationType.PO_LINKAGE,
        status=status,
        document_id=document_id,
        simulated_bc_response=simulated_response,
        simulated_bc_payload=simulated_payload,
        validation_checks=checks,
        would_succeed_in_production=is_valid,
        failure_reason=failure_reason,
        timing_ms=elapsed_ms
    )
    
    logger.info(
        "BC Simulation: simulate_po_linkage complete, doc_id=%s, would_succeed=%s",
        document_id, is_valid
    )
    
    return result


# =============================================================================
# BATCH SIMULATION
# =============================================================================

def run_full_export_simulation(document: Dict) -> Dict[str, SimulationResult]:
    """
    Run a full export simulation for a document based on its type.
    
    This runs all applicable simulations for a document.
    
    Args:
        document: The document dict
        
    Returns:
        Dict mapping simulation type to result
    """
    doc_type = document.get("doc_type", "OTHER")
    results = {}
    
    if doc_type == "AP_INVOICE":
        # AP Invoice: create invoice + attach PDF
        results["export_ap_invoice"] = simulate_export_ap_invoice(document)
        results["create_purchase_invoice"] = simulate_create_purchase_invoice(document)
        results["attach_pdf"] = simulate_attach_pdf(document)
        
        # If has PO reference, simulate linkage
        if document.get("po_number") or document.get("extracted_data", {}).get("po_number"):
            results["po_linkage"] = simulate_po_linkage(document)
            
    elif doc_type == "SALES_INVOICE":
        results["export_sales_invoice"] = simulate_sales_invoice_export(document)
        results["attach_pdf"] = simulate_attach_pdf(document)
        
    elif doc_type == "PURCHASE_ORDER":
        results["po_linkage"] = simulate_po_linkage(document)
        results["attach_pdf"] = simulate_attach_pdf(document)
        
    else:
        # For other types, just simulate attachment
        results["attach_pdf"] = simulate_attach_pdf(document)
    
    return results


# =============================================================================
# SUMMARY HELPERS
# =============================================================================

def calculate_simulation_summary(results: List[Dict]) -> Dict[str, Any]:
    """
    Calculate summary statistics from a list of simulation results.
    
    Args:
        results: List of simulation result dicts
        
    Returns:
        Summary statistics dict
    """
    if not results:
        return {
            "total": 0,
            "by_status": {},
            "by_type": {},
            "would_succeed_rate": 0.0,
            "avg_timing_ms": 0
        }
    
    total = len(results)
    
    # Count by status
    by_status = {}
    for r in results:
        status = r.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    
    # Count by type
    by_type = {}
    for r in results:
        sim_type = r.get("simulation_type", "unknown")
        by_type[sim_type] = by_type.get(sim_type, 0) + 1
    
    # Would succeed rate
    would_succeed = sum(1 for r in results if r.get("would_succeed_in_production"))
    would_succeed_rate = round(would_succeed / total * 100, 1) if total > 0 else 0.0
    
    # Average timing
    total_timing = sum(r.get("timing_ms", 0) for r in results)
    avg_timing = round(total_timing / total, 1) if total > 0 else 0
    
    # Failure reasons breakdown
    failure_reasons = {}
    for r in results:
        reason = r.get("failure_reason")
        if reason:
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    
    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "would_succeed_count": would_succeed,
        "would_fail_count": total - would_succeed,
        "would_succeed_rate": would_succeed_rate,
        "avg_timing_ms": avg_timing,
        "failure_reasons": failure_reasons
    }


# =============================================================================
# SERVICE STATUS
# =============================================================================

def get_simulation_service_status() -> Dict[str, Any]:
    """Get simulation service status."""
    return {
        "service": "bc_simulation_service",
        "pilot_mode_enabled": PILOT_MODE_ENABLED,
        "simulation_version": SIMULATION_VERSION,
        "simulated_bc_environment": SIMULATED_BC_ENVIRONMENT,
        "simulated_bc_company": SIMULATED_BC_COMPANY_NAME,
        "available_simulations": [
            "simulate_export_ap_invoice",
            "simulate_create_purchase_invoice",
            "simulate_attach_pdf",
            "simulate_sales_invoice_export",
            "simulate_po_linkage",
            "run_full_export_simulation"
        ],
        "real_bc_writes": False,
        "observation_only": True
    }
