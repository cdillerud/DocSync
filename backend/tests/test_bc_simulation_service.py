"""
GPI Document Hub - BC Simulation Service Test Suite

Phase 2 Shadow Pilot: Tests for simulated BC write operations.
Minimum 20 tests covering:
- All 5 simulation functions
- Deterministic ID generation
- Validation checks
- Workflow history entries
- Summary calculations
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, '/app/backend')

from services.bc_simulation_service import (
    # Simulation functions
    simulate_export_ap_invoice,
    simulate_create_purchase_invoice,
    simulate_attach_pdf,
    simulate_sales_invoice_export,
    simulate_po_linkage,
    run_full_export_simulation,
    # Validation helpers
    validate_document_for_export,
    validate_ap_invoice_for_bc,
    validate_sales_invoice_for_export,
    validate_po_for_linkage,
    # ID generation
    generate_simulated_bc_id,
    generate_simulated_bc_number,
    # Summary
    calculate_simulation_summary,
    # Status
    get_simulation_service_status,
    # Types
    SimulationResult,
    SimulationType,
    SimulationStatus,
    # Constants
    SIMULATION_VERSION,
    SIMULATED_BC_COMPANY_NAME,
)

from services.workflow_engine import (
    WorkflowEvent,
    SimulationHistoryEntry,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def sample_ap_invoice():
    """Sample AP invoice document."""
    return {
        "document_id": "test-ap-001",
        "doc_type": "AP_INVOICE",
        "workflow_status": "approved",
        "vendor_canonical": "V10000",
        "vendor_name": "Acme Supplies Inc",
        "invoice_number": "INV-2026-001",
        "amount": 5000.00,
        "invoice_date": "2026-02-15",
        "po_number": "PO-001",
        "sharepoint_url": "https://sharepoint.com/docs/test.pdf",
        "original_filename": "invoice.pdf"
    }


@pytest.fixture
def sample_sales_invoice():
    """Sample sales invoice document."""
    return {
        "document_id": "test-si-001",
        "doc_type": "SALES_INVOICE",
        "workflow_status": "approved",
        "customer_number": "C20000",
        "customer_name": "Acme Corp",
        "invoice_number": "SI-5001",
        "amount": 12500.00,
        "invoice_date": "2026-02-10",
        "sharepoint_url": "https://sharepoint.com/docs/sales.pdf"
    }


@pytest.fixture
def sample_purchase_order():
    """Sample purchase order document."""
    return {
        "document_id": "test-po-001",
        "doc_type": "PURCHASE_ORDER",
        "workflow_status": "approved",
        "po_number": "PO-002",
        "vendor_canonical": "V10001",
        "vendor_name": "Global Packaging Co",
        "sharepoint_url": "https://sharepoint.com/docs/po.pdf"
    }


@pytest.fixture
def incomplete_ap_invoice():
    """AP invoice missing required fields."""
    return {
        "document_id": "test-ap-incomplete",
        "doc_type": "AP_INVOICE",
        "workflow_status": "data_correction_pending",
        # Missing vendor, invoice_number, amount
    }


# =============================================================================
# TEST 1-5: SIMULATION FUNCTIONS
# =============================================================================

class TestAPInvoiceSimulation:
    """Tests for AP invoice simulation."""
    
    def test_simulate_export_ap_invoice_success(self, sample_ap_invoice):
        """Test 1: Simulate AP invoice export with valid document."""
        result = simulate_export_ap_invoice(sample_ap_invoice)
        
        assert result.status == SimulationStatus.SUCCESS
        assert result.simulation_type == SimulationType.EXPORT_AP_INVOICE
        assert result.would_succeed_in_production is True
        assert result.failure_reason is None
        assert result.document_id == "test-ap-001"
        
        # Check simulated BC response
        assert result.simulated_bc_response["vendorNumber"] == "V10000"
        assert result.simulated_bc_response["status"] == "Draft"
        assert result.simulated_bc_response["_simulated"] is True
    
    def test_simulate_export_ap_invoice_failure(self, incomplete_ap_invoice):
        """Test 2: Simulate AP invoice export with missing fields."""
        result = simulate_export_ap_invoice(incomplete_ap_invoice)
        
        assert result.status == SimulationStatus.WOULD_FAIL
        assert result.would_succeed_in_production is False
        assert result.failure_reason is not None
        assert "Missing" in result.failure_reason
    
    def test_simulate_create_purchase_invoice(self, sample_ap_invoice):
        """Test 3: Simulate purchase invoice creation."""
        result = simulate_create_purchase_invoice(sample_ap_invoice)
        
        assert result.status == SimulationStatus.SUCCESS
        assert result.simulation_type == SimulationType.CREATE_PURCHASE_INVOICE
        assert result.would_succeed_in_production is True
        
        # Check payload
        assert result.simulated_bc_payload["vendorNumber"] == "V10000"
        assert result.simulated_bc_payload["vendorInvoiceNumber"] == "INV-2026-001"


class TestSalesInvoiceSimulation:
    """Tests for sales invoice simulation."""
    
    def test_simulate_sales_invoice_export_success(self, sample_sales_invoice):
        """Test 4: Simulate sales invoice export with valid document."""
        result = simulate_sales_invoice_export(sample_sales_invoice)
        
        assert result.status == SimulationStatus.SUCCESS
        assert result.simulation_type == SimulationType.EXPORT_SALES_INVOICE
        assert result.would_succeed_in_production is True
        
        # Check response
        assert result.simulated_bc_response["customerNumber"] == "C20000"
        assert result.simulated_bc_response["status"] == "Draft"
    
    def test_simulate_sales_invoice_missing_customer(self):
        """Test 5: Simulate sales invoice export with missing customer."""
        doc = {
            "document_id": "test-si-incomplete",
            "doc_type": "SALES_INVOICE",
            # Missing customer_number
        }
        result = simulate_sales_invoice_export(doc)
        
        assert result.status == SimulationStatus.WOULD_FAIL
        assert result.would_succeed_in_production is False
        assert "customer" in result.failure_reason.lower()


# =============================================================================
# TEST 6-8: PO AND ATTACHMENT SIMULATION
# =============================================================================

class TestPOAndAttachmentSimulation:
    """Tests for PO linkage and attachment simulation."""
    
    def test_simulate_po_linkage_success(self, sample_purchase_order):
        """Test 6: Simulate PO linkage with valid document."""
        result = simulate_po_linkage(sample_purchase_order)
        
        assert result.status == SimulationStatus.SUCCESS
        assert result.simulation_type == SimulationType.PO_LINKAGE
        assert result.would_succeed_in_production is True
        
        # Check response
        assert result.simulated_bc_response["purchaseOrderNumber"] == "PO-002"
        assert result.simulated_bc_response["linkStatus"] == "Linked"
    
    def test_simulate_po_linkage_missing_po(self):
        """Test 7: Simulate PO linkage with missing PO number."""
        doc = {
            "document_id": "test-po-missing",
            "doc_type": "PURCHASE_ORDER",
            # Missing po_number
        }
        result = simulate_po_linkage(doc)
        
        assert result.status == SimulationStatus.WOULD_FAIL
        assert "PO" in result.failure_reason or "Missing" in result.failure_reason
    
    def test_simulate_attach_pdf_success(self, sample_ap_invoice):
        """Test 8: Simulate PDF attachment with valid document."""
        result = simulate_attach_pdf(sample_ap_invoice)
        
        assert result.status == SimulationStatus.SUCCESS
        assert result.simulation_type == SimulationType.ATTACH_PDF
        assert result.would_succeed_in_production is True
        
        # Check response has attachment info
        assert "fileName" in result.simulated_bc_response
        assert result.simulated_bc_response["_simulated"] is True


# =============================================================================
# TEST 9-11: FULL EXPORT SIMULATION
# =============================================================================

class TestFullExportSimulation:
    """Tests for batch export simulation."""
    
    def test_run_full_export_simulation_ap_invoice(self, sample_ap_invoice):
        """Test 9: Run full simulation for AP invoice."""
        results = run_full_export_simulation(sample_ap_invoice)
        
        # Should include multiple simulations
        assert "export_ap_invoice" in results
        assert "create_purchase_invoice" in results
        assert "attach_pdf" in results
        assert "po_linkage" in results  # Because sample has PO number
        
        # All should succeed
        assert all(r.would_succeed_in_production for r in results.values())
    
    def test_run_full_export_simulation_sales_invoice(self, sample_sales_invoice):
        """Test 10: Run full simulation for sales invoice."""
        results = run_full_export_simulation(sample_sales_invoice)
        
        assert "export_sales_invoice" in results
        assert "attach_pdf" in results
        
        # Should not include AP-specific simulations
        assert "export_ap_invoice" not in results
        assert "create_purchase_invoice" not in results
    
    def test_run_full_export_simulation_po(self, sample_purchase_order):
        """Test 11: Run full simulation for purchase order."""
        results = run_full_export_simulation(sample_purchase_order)
        
        assert "po_linkage" in results
        assert "attach_pdf" in results


# =============================================================================
# TEST 12-14: DETERMINISTIC ID GENERATION
# =============================================================================

class TestDeterministicIdGeneration:
    """Tests for deterministic BC ID generation."""
    
    def test_generate_simulated_bc_id_deterministic(self):
        """Test 12: Same inputs produce same BC ID."""
        id1 = generate_simulated_bc_id("doc-123", "export")
        id2 = generate_simulated_bc_id("doc-123", "export")
        
        assert id1 == id2
        assert id1.startswith("sim-")
    
    def test_generate_simulated_bc_id_different_inputs(self):
        """Test 13: Different inputs produce different IDs."""
        id1 = generate_simulated_bc_id("doc-123", "export")
        id2 = generate_simulated_bc_id("doc-456", "export")
        id3 = generate_simulated_bc_id("doc-123", "create")
        
        assert id1 != id2
        assert id1 != id3
    
    def test_generate_simulated_bc_number_format(self):
        """Test 14: BC number has correct format."""
        number = generate_simulated_bc_number("PI", "doc-123")
        
        assert number.startswith("PI-SIM-")
        assert len(number.split("-")) == 3
        
        # Should be deterministic
        number2 = generate_simulated_bc_number("PI", "doc-123")
        assert number == number2


# =============================================================================
# TEST 15-17: VALIDATION HELPERS
# =============================================================================

class TestValidationHelpers:
    """Tests for validation helper functions."""
    
    def test_validate_ap_invoice_for_bc_valid(self, sample_ap_invoice):
        """Test 15: Validate complete AP invoice."""
        is_valid, checks, failure_reason = validate_ap_invoice_for_bc(sample_ap_invoice)
        
        assert is_valid is True
        assert failure_reason is None
        assert len(checks) >= 3
        assert all(c["passed"] for c in checks if c["check"] in ["has_vendor", "has_invoice_number", "has_amount"])
    
    def test_validate_ap_invoice_for_bc_invalid(self, incomplete_ap_invoice):
        """Test 16: Validate incomplete AP invoice."""
        is_valid, checks, failure_reason = validate_ap_invoice_for_bc(incomplete_ap_invoice)
        
        assert is_valid is False
        assert failure_reason is not None
        assert "Missing" in failure_reason
    
    def test_validate_sales_invoice_for_export(self, sample_sales_invoice):
        """Test 17: Validate sales invoice for export."""
        is_valid, checks, failure_reason = validate_sales_invoice_for_export(sample_sales_invoice)
        
        assert is_valid is True
        assert failure_reason is None


# =============================================================================
# TEST 18-20: SIMULATION RESULT CLASS
# =============================================================================

class TestSimulationResultClass:
    """Tests for SimulationResult class."""
    
    def test_simulation_result_to_dict(self, sample_ap_invoice):
        """Test 18: SimulationResult.to_dict() returns correct structure."""
        result = simulate_export_ap_invoice(sample_ap_invoice)
        d = result.to_dict()
        
        assert d["simulation_id"] is not None
        assert d["simulation_type"] == "export_ap_invoice"
        assert d["status"] == "success"
        assert d["document_id"] == "test-ap-001"
        assert d["simulated_bc_response"] is not None
        assert d["simulated_bc_payload"] is not None
        assert d["pilot_phase"] is not None
        assert d["simulation_version"] == SIMULATION_VERSION
    
    def test_simulation_result_to_workflow_entry(self, sample_ap_invoice):
        """Test 19: SimulationResult.to_workflow_entry() creates valid entry."""
        result = simulate_export_ap_invoice(sample_ap_invoice)
        entry = result.to_workflow_entry()
        
        assert "timestamp" in entry
        assert entry["event"].startswith("simulated_")
        assert entry["actor"] == "bc_simulation_service"
        assert entry["observation_only"] is True
        assert entry["pilot_mode"] is True
        assert "simulation" in entry
    
    def test_simulation_result_timing(self, sample_ap_invoice):
        """Test 20: SimulationResult tracks timing."""
        result = simulate_export_ap_invoice(sample_ap_invoice)
        
        assert result.timing_ms >= 0
        assert result.timestamp is not None


# =============================================================================
# TEST 21-23: WORKFLOW INTEGRATION
# =============================================================================

class TestWorkflowIntegration:
    """Tests for workflow engine integration."""
    
    def test_simulation_workflow_events_exist(self):
        """Test 21: Simulation workflow events are defined."""
        assert hasattr(WorkflowEvent, 'ON_EXPORT_SIMULATED')
        assert hasattr(WorkflowEvent, 'ON_BC_CREATE_INVOICE_SIMULATED')
        assert hasattr(WorkflowEvent, 'ON_BC_ATTACHMENT_SIMULATED')
        assert hasattr(WorkflowEvent, 'ON_BC_LINKAGE_SIMULATED')
        assert hasattr(WorkflowEvent, 'ON_SIMULATION_SUCCESS')
        assert hasattr(WorkflowEvent, 'ON_SIMULATION_WOULD_FAIL')
    
    def test_simulation_history_entry_single(self, sample_ap_invoice):
        """Test 22: SimulationHistoryEntry creates correct single entry."""
        result = simulate_export_ap_invoice(sample_ap_invoice)
        result_dict = result.to_dict()
        
        entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
        
        assert entry["event"] == "on_export_simulated"
        assert entry["simulation"]["simulation_type"] == "export_ap_invoice"
        assert entry["simulation"]["would_succeed_in_production"] is True
        assert entry["observation_only"] is True
    
    def test_simulation_history_entry_batch(self, sample_ap_invoice):
        """Test 23: SimulationHistoryEntry creates correct batch entry."""
        results = run_full_export_simulation(sample_ap_invoice)
        results_dict = {k: v.to_dict() for k, v in results.items()}
        
        entry = SimulationHistoryEntry.create_batch_simulation_entry(
            document_id="test-ap-001",
            simulation_results=results_dict
        )
        
        assert entry["event"] == "on_simulation_success"
        assert entry["batch_simulation"]["total_simulations"] == len(results)
        assert entry["batch_simulation"]["would_succeed_count"] == len(results)


# =============================================================================
# TEST 24-26: SUMMARY CALCULATIONS
# =============================================================================

class TestSummaryCalculations:
    """Tests for summary calculation functions."""
    
    def test_calculate_simulation_summary_empty(self):
        """Test 24: Summary calculation with empty list."""
        summary = calculate_simulation_summary([])
        
        assert summary["total"] == 0
        assert summary["would_succeed_rate"] == 0.0
    
    def test_calculate_simulation_summary_all_success(self, sample_ap_invoice, sample_sales_invoice):
        """Test 25: Summary calculation with all successes."""
        r1 = simulate_export_ap_invoice(sample_ap_invoice)
        r2 = simulate_sales_invoice_export(sample_sales_invoice)
        
        results = [r1.to_dict(), r2.to_dict()]
        summary = calculate_simulation_summary(results)
        
        assert summary["total"] == 2
        assert summary["would_succeed_count"] == 2
        assert summary["would_succeed_rate"] == 100.0
        assert summary["by_type"]["export_ap_invoice"] == 1
        assert summary["by_type"]["export_sales_invoice"] == 1
    
    def test_calculate_simulation_summary_mixed(self, sample_ap_invoice, incomplete_ap_invoice):
        """Test 26: Summary calculation with mixed results."""
        r1 = simulate_export_ap_invoice(sample_ap_invoice)
        r2 = simulate_export_ap_invoice(incomplete_ap_invoice)
        
        results = [r1.to_dict(), r2.to_dict()]
        summary = calculate_simulation_summary(results)
        
        assert summary["total"] == 2
        assert summary["would_succeed_count"] == 1
        assert summary["would_fail_count"] == 1
        assert summary["would_succeed_rate"] == 50.0
        assert len(summary["failure_reasons"]) > 0


# =============================================================================
# TEST 27-28: SERVICE STATUS
# =============================================================================

class TestServiceStatus:
    """Tests for service status."""
    
    def test_service_status_returns_correct_structure(self):
        """Test 27: Service status returns expected structure."""
        status = get_simulation_service_status()
        
        assert status["service"] == "bc_simulation_service"
        assert status["simulation_version"] == SIMULATION_VERSION
        assert status["real_bc_writes"] is False
        assert status["observation_only"] is True
        assert "available_simulations" in status
    
    def test_service_status_lists_all_simulations(self):
        """Test 28: Service status lists all available simulations."""
        status = get_simulation_service_status()
        
        expected = [
            "simulate_export_ap_invoice",
            "simulate_create_purchase_invoice",
            "simulate_attach_pdf",
            "simulate_sales_invoice_export",
            "simulate_po_linkage"
        ]
        
        for sim in expected:
            assert sim in status["available_simulations"]


# =============================================================================
# TEST 29-30: SIMULATION TYPES AND STATUS
# =============================================================================

class TestSimulationEnums:
    """Tests for simulation enums."""
    
    def test_simulation_types_defined(self):
        """Test 29: All simulation types are defined."""
        assert SimulationType.EXPORT_AP_INVOICE.value == "export_ap_invoice"
        assert SimulationType.CREATE_PURCHASE_INVOICE.value == "create_purchase_invoice"
        assert SimulationType.ATTACH_PDF.value == "attach_pdf"
        assert SimulationType.EXPORT_SALES_INVOICE.value == "export_sales_invoice"
        assert SimulationType.PO_LINKAGE.value == "po_linkage"
    
    def test_simulation_status_defined(self):
        """Test 30: All simulation statuses are defined."""
        assert SimulationStatus.SUCCESS.value == "success"
        assert SimulationStatus.WOULD_FAIL.value == "would_fail"
        assert SimulationStatus.SKIPPED.value == "skipped"
        assert SimulationStatus.BLOCKED.value == "blocked"
        assert SimulationStatus.ERROR.value == "error"


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
