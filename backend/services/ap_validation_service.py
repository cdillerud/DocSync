"""
GPI Document Hub - AP Invoice Validation Service

This service implements the updated validation rules for AP invoices:

Validation = "Document contains minimum required accounting information to proceed"

Required fields (FAIL if missing):
1. Vendor must resolve to a BC vendor
2. Invoice number must exist
3. Invoice date must exist
4. Total amount must exist
5. Invoice must not be a duplicate for that vendor

Warnings (DO NOT fail validation):
- PO reference extracted but not found in BC
- Freight direction cannot be determined
- Currency mismatch
- Missing line items
- Missing tax amount

Result:
- validation_state = pass | warning | fail
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class APValidationState(str, Enum):
    """AP Invoice validation state."""
    PENDING = "pending"
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class APValidationResult:
    """
    Result of AP invoice validation.
    
    Separates required field validation (blocking) from warnings (non-blocking).
    """
    
    def __init__(self):
        self.validation_state = APValidationState.PENDING.value
        self.required_checks = []
        self.warnings = []
        self.blocking_issues = []
        
        # Required field status
        self.vendor_resolved = False
        self.invoice_number_present = False
        self.invoice_date_present = False
        self.total_amount_present = False
        self.is_duplicate = False
        
        # Resolved values
        self.matched_vendor_no = None
        self.matched_vendor_name = None
        self.match_method = None
        self.match_score = 0.0
        
        # Reference resolution
        self.reference_resolution = None
        
        # BOL extraction
        self.bol_number = None
        
        # Metadata
        self.validated_at = None
    
    def add_required_check(self, name: str, passed: bool, details: str, **kwargs):
        """Add a required check result."""
        check = {
            "check_name": name,
            "passed": passed,
            "details": details,
            "required": True,
            **kwargs
        }
        self.required_checks.append(check)
        if not passed:
            self.blocking_issues.append(details)
    
    def add_warning(self, name: str, details: str, **kwargs):
        """Add a warning (non-blocking)."""
        warning = {
            "check_name": name,
            "details": details,
            "required": False,
            **kwargs
        }
        self.warnings.append(warning)
    
    def compute_final_state(self):
        """
        Compute final validation state based on checks and warnings.
        
        Logic:
        - FAIL: Any required check failed
        - WARNING: All required checks passed but warnings present
        - PASS: All required checks passed, no warnings
        """
        all_required_passed = all(c["passed"] for c in self.required_checks)
        
        if not all_required_passed:
            self.validation_state = APValidationState.FAIL.value
        elif self.warnings:
            self.validation_state = APValidationState.WARNING.value
        else:
            self.validation_state = APValidationState.PASS.value
        
        self.validated_at = datetime.now(timezone.utc).isoformat()
        return self.validation_state
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "validation_state": self.validation_state,
            "all_passed": self.validation_state in (APValidationState.PASS.value, APValidationState.WARNING.value),
            "checks": self.required_checks,
            "warnings": self.warnings,
            "blocking_issues": self.blocking_issues,
            
            # Required field status
            "vendor_resolved": self.vendor_resolved,
            "invoice_number_present": self.invoice_number_present,
            "invoice_date_present": self.invoice_date_present,
            "total_amount_present": self.total_amount_present,
            "is_duplicate": self.is_duplicate,
            
            # Resolved values
            "matched_vendor_no": self.matched_vendor_no,
            "matched_vendor_name": self.matched_vendor_name,
            "match_method": self.match_method,
            "match_score": self.match_score,
            
            # Reference resolution
            "reference_resolution": self.reference_resolution,
            
            # BOL
            "bol_number": self.bol_number,
            
            "validated_at": self.validated_at
        }


class APValidationService:
    """
    AP Invoice Validation Service.
    
    Validates AP invoices against the required accounting information rules.
    """
    
    def __init__(self, db, bc_service=None, event_service=None):
        self.db = db
        self.bc_service = bc_service
        self.event_service = event_service
    
    async def validate_ap_invoice(
        self,
        document: Dict[str, Any],
        extracted_fields: Dict[str, Any],
        vendor_match_result: Optional[Dict] = None,
        correlation_id: Optional[str] = None
    ) -> APValidationResult:
        """
        Validate an AP invoice document.
        
        Args:
            document: The document record
            extracted_fields: Extracted fields from AI
            vendor_match_result: Optional pre-computed vendor match
            correlation_id: For event correlation
            
        Returns:
            APValidationResult with validation state and details
        """
        result = APValidationResult()
        doc_id = document.get("id", "unknown")
        
        logger.info("[AP Validation] Starting validation for doc %s", doc_id[:8])
        
        # ============================================================
        # CHECK 1: Vendor Resolution (REQUIRED)
        # ============================================================
        vendor_name = extracted_fields.get("vendor") or document.get("vendor_raw", "")
        
        if vendor_match_result:
            # Use pre-computed match
            if vendor_match_result.get("matched"):
                result.vendor_resolved = True
                result.matched_vendor_no = vendor_match_result.get("bc_vendor_number") or \
                    vendor_match_result.get("best_match", {}).get("vendor_number")
                result.matched_vendor_name = vendor_match_result.get("best_match", {}).get("name")
                result.match_method = vendor_match_result.get("source") or "unknown"
                result.match_score = vendor_match_result.get("score", 0.0)
                
                result.add_required_check(
                    "vendor_resolution",
                    True,
                    f"Vendor resolved: {result.matched_vendor_name} ({result.matched_vendor_no}) via {result.match_method}",
                    vendor_no=result.matched_vendor_no,
                    vendor_name=result.matched_vendor_name,
                    match_method=result.match_method,
                    match_score=result.match_score
                )
            else:
                result.add_required_check(
                    "vendor_resolution",
                    False,
                    f"Vendor not resolved: '{vendor_name}' not found in BC"
                )
        else:
            # No vendor match provided - check if we have a vendor name at all
            if not vendor_name:
                result.add_required_check(
                    "vendor_resolution",
                    False,
                    "Vendor not extracted from document"
                )
            else:
                # We have a vendor name but no match result - treat as unresolved
                result.add_required_check(
                    "vendor_resolution",
                    False,
                    f"Vendor '{vendor_name}' not resolved to BC vendor"
                )
        
        # ============================================================
        # CHECK 2: Invoice Number (REQUIRED)
        # ============================================================
        invoice_number = extracted_fields.get("invoice_number") or document.get("invoice_number_clean")
        
        if invoice_number and str(invoice_number).strip():
            result.invoice_number_present = True
            result.add_required_check(
                "invoice_number",
                True,
                f"Invoice number present: {invoice_number}",
                invoice_number=invoice_number
            )
        else:
            result.add_required_check(
                "invoice_number",
                False,
                "Invoice number not extracted from document"
            )
        
        # ============================================================
        # CHECK 3: Invoice Date (REQUIRED)
        # ============================================================
        invoice_date = extracted_fields.get("invoice_date") or document.get("invoice_date")
        
        if invoice_date and str(invoice_date).strip():
            result.invoice_date_present = True
            result.add_required_check(
                "invoice_date",
                True,
                f"Invoice date present: {invoice_date}",
                invoice_date=invoice_date
            )
        else:
            result.add_required_check(
                "invoice_date",
                False,
                "Invoice date not extracted from document"
            )
        
        # ============================================================
        # CHECK 4: Total Amount (REQUIRED)
        # ============================================================
        total_amount = extracted_fields.get("amount") or document.get("amount_float")
        
        # Handle string amounts
        if isinstance(total_amount, str):
            try:
                total_amount = float(total_amount.replace(",", "").replace("$", ""))
            except (ValueError, AttributeError):
                total_amount = None
        
        if total_amount is not None:
            result.total_amount_present = True
            result.add_required_check(
                "total_amount",
                True,
                f"Total amount present: ${total_amount:,.2f}" if isinstance(total_amount, (int, float)) else f"Total amount present: {total_amount}",
                amount=total_amount
            )
        else:
            result.add_required_check(
                "total_amount",
                False,
                "Total amount not extracted from document"
            )
        
        # ============================================================
        # CHECK 5: Duplicate Invoice (REQUIRED - if vendor resolved)
        # ============================================================
        if result.vendor_resolved and result.invoice_number_present:
            is_duplicate = await self._check_duplicate_invoice(
                result.matched_vendor_no,
                invoice_number
            )
            
            if is_duplicate:
                result.is_duplicate = True
                result.add_required_check(
                    "duplicate_check",
                    False,
                    f"Duplicate invoice: {invoice_number} already exists for vendor {result.matched_vendor_no}",
                    existing_invoice=invoice_number
                )
            else:
                result.add_required_check(
                    "duplicate_check",
                    True,
                    f"No duplicate invoice found for {invoice_number}"
                )
        else:
            # Can't check duplicates without vendor and invoice number
            if not result.vendor_resolved:
                result.add_warning(
                    "duplicate_check_skipped",
                    "Duplicate check skipped: vendor not resolved"
                )
        
        # ============================================================
        # WARNINGS (Non-blocking)
        # ============================================================
        
        # Warning: PO reference not found
        po_number = extracted_fields.get("po_number") or document.get("po_number_clean")

        # ============================================================
        # CHECK 6: PO Amount Validation (10% tolerance)
        # ============================================================
        if po_number and total_amount is not None:
            await self._validate_po_amount(result, po_number, total_amount)
        elif po_number:
            result.add_warning(
                "po_amount_skip_no_invoice_amount",
                f"PO '{po_number}' found but invoice amount missing — cannot validate",
            )

        if po_number:
            # PO was extracted - check if it exists in BC (this is informational, not blocking)
            # Store for reference resolution
            result.add_warning(
                "po_reference",
                f"PO reference extracted: {po_number} (will be validated separately)",
                po_number=po_number
            )
        
        # Warning: Currency mismatch
        currency = extracted_fields.get("currency") or document.get("currency", "USD")
        if currency and currency.upper() not in ("USD", "CAD"):
            result.add_warning(
                "currency_mismatch",
                f"Non-standard currency: {currency}"
            )
        
        # Warning: Missing line items
        line_items = extracted_fields.get("line_items") or document.get("line_items", [])
        if not line_items:
            result.add_warning(
                "missing_line_items",
                "No line items extracted from document"
            )
        
        # Warning: Missing tax amount
        tax_amount = extracted_fields.get("tax_amount") or document.get("tax_amount")
        if tax_amount is None:
            result.add_warning(
                "missing_tax_amount",
                "Tax amount not extracted (will default to 0)"
            )
        
        # ============================================================
        # COMPUTE FINAL STATE
        # ============================================================
        result.compute_final_state()
        
        logger.info(
            "[AP Validation] Doc %s: state=%s, vendor=%s, blocking_issues=%d, warnings=%d",
            doc_id[:8], result.validation_state, 
            "resolved" if result.vendor_resolved else "not resolved",
            len(result.blocking_issues), len(result.warnings)
        )
        
        return result
    
    async def _check_duplicate_invoice(
        self,
        vendor_no: str,
        invoice_number: str
    ) -> bool:
        """
        Check if an invoice already exists for the vendor in BC.
        
        Returns True if duplicate found.
        """
        if not self.bc_service:
            logger.warning("[AP Validation] BC service not available - skipping duplicate check")
            return False
        
        try:
            existing = await self.bc_service.check_duplicate_purchase_invoice(vendor_no, invoice_number)
            return existing is not None
        except Exception as e:
            logger.error("[AP Validation] Duplicate check failed: %s", str(e))
            return False  # Assume not duplicate on error

    async def _validate_po_amount(
        self,
        result: APValidationResult,
        po_number: str,
        invoice_amount,
    ):
        """
        Check 6: PO Amount Validation (10% tolerance).
        Looks up PO in BC and compares total against invoice amount.
        """
        if not self.bc_service or not po_number:
            return

        try:
            po_data = await self.bc_service.find_purchase_order_by_number(po_number)
            if not po_data:
                result.add_warning(
                    "po_not_found",
                    f"PO '{po_number}' not found in Business Central — cannot validate amount",
                    po_number=po_number,
                )
                return

            po_amount = po_data.get("totalAmountIncludingTax") or po_data.get("totalAmountExcludingTax")
            if not po_amount:
                result.add_warning(
                    "po_no_amount",
                    f"PO '{po_number}' found but has no amount — cannot validate",
                    po_number=po_number,
                )
                return

            if not invoice_amount:
                return  # Already flagged in check 4

            diff_pct = abs(float(invoice_amount) - float(po_amount)) / float(po_amount) if float(po_amount) else 0
            TOLERANCE = 0.10  # 10%

            if diff_pct > TOLERANCE:
                result.add_required_check(
                    "po_amount_validation",
                    False,
                    f"Amount mismatch: invoice ${float(invoice_amount):,.2f} vs PO ${float(po_amount):,.2f} "
                    f"({diff_pct*100:.1f}% diff, tolerance={TOLERANCE*100:.0f}%)",
                    invoice_amount=float(invoice_amount),
                    po_amount=float(po_amount),
                    diff_pct=round(diff_pct * 100, 1),
                )
            else:
                result.add_required_check(
                    "po_amount_validation",
                    True,
                    f"Amount within tolerance: invoice ${float(invoice_amount):,.2f} vs PO ${float(po_amount):,.2f} "
                    f"({diff_pct*100:.1f}% diff)",
                    invoice_amount=float(invoice_amount),
                    po_amount=float(po_amount),
                    diff_pct=round(diff_pct * 100, 1),
                )
        except Exception as e:
            logger.warning("[AP Validation] PO amount check failed for %s: %s", po_number, e)
            result.add_warning(
                "po_amount_check_failed",
                f"PO amount validation failed: {e}",
            )


def validate_ap_invoice_sync(
    document: Dict[str, Any],
    extracted_fields: Dict[str, Any],
    vendor_match_result: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Synchronous validation for AP invoices (for use in existing code).
    
    This implements the validation logic without async BC calls.
    Use APValidationService for full async validation with BC lookups.
    """
    result = APValidationResult()
    
    # Check 1: Vendor Resolution
    if vendor_match_result and vendor_match_result.get("matched"):
        result.vendor_resolved = True
        result.matched_vendor_no = vendor_match_result.get("bc_vendor_number") or \
            vendor_match_result.get("best_match", {}).get("vendor_number")
        result.matched_vendor_name = vendor_match_result.get("best_match", {}).get("name")
        result.match_method = vendor_match_result.get("source")
        result.match_score = vendor_match_result.get("score", 0.0)
        result.add_required_check("vendor_resolution", True, f"Vendor resolved: {result.matched_vendor_name}")
    else:
        vendor_name = extracted_fields.get("vendor") or document.get("vendor_raw", "")
        result.add_required_check("vendor_resolution", False, f"Vendor not resolved: '{vendor_name}'")
    
    # Check 2: Invoice Number
    invoice_number = extracted_fields.get("invoice_number") or document.get("invoice_number_clean")
    if invoice_number and str(invoice_number).strip():
        result.invoice_number_present = True
        result.add_required_check("invoice_number", True, f"Invoice number: {invoice_number}")
    else:
        result.add_required_check("invoice_number", False, "Invoice number missing")
    
    # Check 3: Invoice Date
    invoice_date = extracted_fields.get("invoice_date") or document.get("invoice_date")
    if invoice_date and str(invoice_date).strip():
        result.invoice_date_present = True
        result.add_required_check("invoice_date", True, f"Invoice date: {invoice_date}")
    else:
        result.add_required_check("invoice_date", False, "Invoice date missing")
    
    # Check 4: Total Amount
    total_amount = extracted_fields.get("amount") or document.get("amount_float")
    if isinstance(total_amount, str):
        try:
            total_amount = float(total_amount.replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            total_amount = None
    
    if total_amount is not None:
        result.total_amount_present = True
        result.add_required_check("total_amount", True, f"Amount: {total_amount}")
    else:
        result.add_required_check("total_amount", False, "Total amount missing")
    
    # Compute final state
    result.compute_final_state()
    
    return result.to_dict()
