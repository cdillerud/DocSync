"""
GPI Document Hub - BC Sandbox Service Test Suite

Comprehensive tests for the BC Sandbox read-only integration.
Minimum 20 tests covering:
- All 8 read-only lookup functions
- Pilot guards (write operations blocked)
- Mock BC API responses
- Integration with workflow engine
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

# Import the service under test
import sys
sys.path.insert(0, '/app/backend')

from services.bc_sandbox_service import (
    # Read-only functions
    get_vendor,
    search_vendors_by_name,
    validate_vendor_exists,
    get_customer,
    get_purchase_order,
    get_purchase_invoice,
    get_sales_invoice,
    validate_invoice_exists,
    # Validation functions
    validate_ap_invoice_in_bc,
    validate_sales_invoice_in_bc,
    validate_purchase_order_in_bc,
    # Status
    get_bc_sandbox_status,
    # Blocked write functions
    create_vendor,
    update_vendor,
    delete_vendor,
    create_purchase_invoice,
    post_purchase_invoice,
    update_purchase_invoice,
    create_sales_invoice,
    post_sales_invoice,
    # Exceptions
    PilotModeWriteBlockedError,
    BCSandboxError,
    BCAuthenticationError,
    BCNotFoundError,
    # Result types
    BCLookupStatus,
    BCLookupResult,
    # Mock data
    MOCK_VENDORS,
    MOCK_CUSTOMERS,
    MOCK_PURCHASE_ORDERS,
    MOCK_PURCHASE_INVOICES,
    MOCK_SALES_INVOICES,
)

from services.workflow_engine import (
    WorkflowEvent,
    BCValidationHistoryEntry,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# TEST 1-8: READ-ONLY LOOKUP FUNCTIONS (DEMO MODE)
# =============================================================================

class TestVendorLookups:
    """Tests for vendor lookup functions."""
    
    @pytest.mark.asyncio
    async def test_get_vendor_success(self):
        """Test 1: Get existing vendor by number."""
        result = await get_vendor("V10000")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data is not None
        assert result.data["number"] == "V10000"
        assert result.data["displayName"] == "Acme Supplies Inc"
        assert result.timing_ms >= 0
        assert result.endpoint is not None
    
    @pytest.mark.asyncio
    async def test_get_vendor_not_found(self):
        """Test 2: Get non-existent vendor returns NOT_FOUND."""
        result = await get_vendor("V99999")
        
        assert result.status == BCLookupStatus.NOT_FOUND
        assert result.error is not None
        assert "not found" in result.error.lower()
        assert result.data == {}
    
    @pytest.mark.asyncio
    async def test_search_vendors_by_name(self):
        """Test 3: Search vendors by name fragment."""
        result = await search_vendors_by_name("Supplies")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert "vendors" in result.data
        assert result.data["count"] >= 1
        # Should find "Acme Supplies Inc"
        vendor_names = [v["displayName"] for v in result.data["vendors"]]
        assert any("Supplies" in name for name in vendor_names)
    
    @pytest.mark.asyncio
    async def test_search_vendors_empty_result(self):
        """Test 4: Search vendors with no matches."""
        result = await search_vendors_by_name("ZZZZNONEXISTENT")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data["count"] == 0
        assert result.data["vendors"] == []
    
    @pytest.mark.asyncio
    async def test_validate_vendor_exists_true(self):
        """Test 5: Validate vendor exists returns True for existing vendor."""
        exists, result = await validate_vendor_exists("V10001")
        
        assert exists is True
        assert result.is_found is True
        assert result.data["number"] == "V10001"
    
    @pytest.mark.asyncio
    async def test_validate_vendor_exists_false(self):
        """Test 6: Validate vendor exists returns False for missing vendor."""
        exists, result = await validate_vendor_exists("V00000")
        
        assert exists is False
        assert result.is_found is False


class TestCustomerLookups:
    """Tests for customer lookup functions."""
    
    @pytest.mark.asyncio
    async def test_get_customer_success(self):
        """Test 7: Get existing customer by number."""
        result = await get_customer("C20000")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data["number"] == "C20000"
        assert result.data["displayName"] == "Acme Corp"
    
    @pytest.mark.asyncio
    async def test_get_customer_not_found(self):
        """Test 8: Get non-existent customer returns NOT_FOUND."""
        result = await get_customer("C99999")
        
        assert result.status == BCLookupStatus.NOT_FOUND
        assert result.error is not None


# =============================================================================
# TEST 9-12: DOCUMENT LOOKUPS (PO AND INVOICES)
# =============================================================================

class TestDocumentLookups:
    """Tests for PO and invoice lookup functions."""
    
    @pytest.mark.asyncio
    async def test_get_purchase_order_success(self):
        """Test 9: Get existing PO by number."""
        result = await get_purchase_order("PO-001")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data["number"] == "PO-001"
        assert result.data["vendorNumber"] == "V10000"
        assert "totalAmount" in result.data
    
    @pytest.mark.asyncio
    async def test_get_purchase_invoice_success(self):
        """Test 10: Get existing purchase invoice by number."""
        result = await get_purchase_invoice("PI-1001")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data["number"] == "PI-1001"
        assert result.data["vendorInvoiceNumber"] == "INV-2026-001"
    
    @pytest.mark.asyncio
    async def test_get_sales_invoice_success(self):
        """Test 11: Get existing sales invoice by number."""
        result = await get_sales_invoice("SI-5001")
        
        assert result.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE]
        assert result.data["number"] == "SI-5001"
        assert result.data["customerNumber"] == "C20000"
    
    @pytest.mark.asyncio
    async def test_validate_invoice_exists(self):
        """Test 12: Validate invoice existence."""
        # Purchase invoice
        exists_pi, result_pi = await validate_invoice_exists("PI-1002", "purchase")
        assert exists_pi is True
        
        # Sales invoice
        exists_si, result_si = await validate_invoice_exists("SI-5002", "sales")
        assert exists_si is True
        
        # Non-existent
        exists_none, result_none = await validate_invoice_exists("XX-9999", "purchase")
        assert exists_none is False


# =============================================================================
# TEST 13-17: PILOT GUARDS (WRITE OPERATIONS BLOCKED)
# =============================================================================

class TestPilotGuards:
    """Tests for pilot mode write operation guards."""
    
    @pytest.mark.asyncio
    async def test_create_vendor_blocked(self):
        """Test 13: Creating vendor raises PilotModeWriteBlockedError."""
        with pytest.raises(PilotModeWriteBlockedError) as exc_info:
            await create_vendor({"name": "Test Vendor"})
        
        assert exc_info.value.operation == "create_vendor"
        assert "READ-ONLY" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_update_vendor_blocked(self):
        """Test 14: Updating vendor raises PilotModeWriteBlockedError."""
        with pytest.raises(PilotModeWriteBlockedError) as exc_info:
            await update_vendor("V10000", {"name": "Updated"})
        
        assert exc_info.value.operation == "update_vendor"
    
    @pytest.mark.asyncio
    async def test_delete_vendor_blocked(self):
        """Test 15: Deleting vendor raises PilotModeWriteBlockedError."""
        with pytest.raises(PilotModeWriteBlockedError) as exc_info:
            await delete_vendor("V10000")
        
        assert exc_info.value.operation == "delete_vendor"
    
    @pytest.mark.asyncio
    async def test_create_purchase_invoice_blocked(self):
        """Test 16: Creating purchase invoice raises PilotModeWriteBlockedError."""
        with pytest.raises(PilotModeWriteBlockedError) as exc_info:
            await create_purchase_invoice({"vendor": "V10000"})
        
        assert exc_info.value.operation == "create_purchase_invoice"
    
    @pytest.mark.asyncio
    async def test_post_purchase_invoice_blocked(self):
        """Test 17: Posting purchase invoice raises PilotModeWriteBlockedError."""
        with pytest.raises(PilotModeWriteBlockedError) as exc_info:
            await post_purchase_invoice("PI-1001")
        
        assert exc_info.value.operation == "post_purchase_invoice"


# =============================================================================
# TEST 18-22: VALIDATION FUNCTIONS
# =============================================================================

class TestValidationFunctions:
    """Tests for BC validation functions."""
    
    @pytest.mark.asyncio
    async def test_validate_ap_invoice_success(self):
        """Test 18: Validate AP invoice with existing vendor."""
        result = await validate_ap_invoice_in_bc(
            vendor_number="V10000",
            invoice_number="INV-2026-001",
            po_number="PO-001"
        )
        
        assert result["observation_only"] is True
        assert result["pilot_mode"] is True
        assert "checks" in result
        assert len(result["checks"]) >= 1
        
        # Vendor check should pass
        vendor_check = next(c for c in result["checks"] if c["check_name"] == "vendor_exists")
        assert vendor_check["passed"] is True
    
    @pytest.mark.asyncio
    async def test_validate_ap_invoice_vendor_not_found(self):
        """Test 19: Validate AP invoice with missing vendor generates warning."""
        result = await validate_ap_invoice_in_bc(
            vendor_number="V99999"
        )
        
        assert len(result["warnings"]) > 0
        assert "not found" in result["warnings"][0].lower()
        # Still valid in observation mode
        assert result["overall_valid"] is True
    
    @pytest.mark.asyncio
    async def test_validate_sales_invoice(self):
        """Test 20: Validate sales invoice with customer lookup."""
        result = await validate_sales_invoice_in_bc(
            customer_number="C20000",
            invoice_number="SI-5001"
        )
        
        assert result["observation_only"] is True
        assert "checks" in result
        
        customer_check = next(c for c in result["checks"] if c["check_name"] == "customer_exists")
        assert customer_check["passed"] is True
    
    @pytest.mark.asyncio
    async def test_validate_purchase_order(self):
        """Test 21: Validate purchase order lookup."""
        result = await validate_purchase_order_in_bc("PO-002")
        
        assert result["observation_only"] is True
        
        po_check = next(c for c in result["checks"] if c["check_name"] == "po_exists")
        assert po_check["passed"] is True
        
        # Should have BC data
        assert "bc_po_data" in result
        assert result["bc_po_data"]["vendor_number"] == "V10001"
    
    @pytest.mark.asyncio
    async def test_validate_purchase_order_not_found(self):
        """Test 22: Validate non-existent PO generates warning."""
        result = await validate_purchase_order_in_bc("PO-99999")
        
        assert len(result["warnings"]) > 0
        assert "not found" in result["warnings"][0].lower()


# =============================================================================
# TEST 23-25: WORKFLOW INTEGRATION
# =============================================================================

class TestWorkflowIntegration:
    """Tests for workflow engine integration."""
    
    def test_bc_lookup_workflow_events_exist(self):
        """Test 23: BC lookup workflow events are defined."""
        assert hasattr(WorkflowEvent, 'ON_BC_LOOKUP_SUCCESS')
        assert hasattr(WorkflowEvent, 'ON_BC_LOOKUP_FAILED')
        assert hasattr(WorkflowEvent, 'ON_BC_LOOKUP_NOT_FOUND')
        assert hasattr(WorkflowEvent, 'ON_BC_VENDOR_VALIDATED')
        assert hasattr(WorkflowEvent, 'ON_BC_CUSTOMER_VALIDATED')
        assert hasattr(WorkflowEvent, 'ON_BC_PO_VALIDATED')
        assert hasattr(WorkflowEvent, 'ON_BC_INVOICE_VALIDATED')
    
    @pytest.mark.asyncio
    async def test_bc_validation_history_entry_lookup(self):
        """Test 24: BCValidationHistoryEntry creates correct lookup entry."""
        # Create a mock BC lookup result
        bc_result = {
            "status": "success",
            "data": {"number": "V10000", "displayName": "Acme Supplies Inc"},
            "timing_ms": 150,
            "endpoint": "vendors?$filter=number eq 'V10000'",
            "response_size": 256,
            "error": None
        }
        
        entry = BCValidationHistoryEntry.create_bc_lookup_entry(
            event=WorkflowEvent.ON_BC_VENDOR_VALIDATED.value,
            lookup_type="vendor",
            lookup_key="V10000",
            bc_result=bc_result
        )
        
        assert entry["event"] == "on_bc_vendor_validated"
        assert entry["actor"] == "bc_sandbox_service"
        assert entry["bc_validation"]["lookup_type"] == "vendor"
        assert entry["bc_validation"]["lookup_key"] == "V10000"
        assert entry["bc_validation"]["found"] is True
        assert entry["bc_validation"]["timing_ms"] == 150
        assert entry["observation_only"] is True
    
    @pytest.mark.asyncio
    async def test_bc_validation_history_entry_full(self):
        """Test 25: BCValidationHistoryEntry creates correct validation entry."""
        validation_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pilot_mode": True,
            "observation_only": True,
            "overall_valid": True,
            "total_timing_ms": 350,
            "warnings": [],
            "errors": [],
            "checks": [
                {"check_name": "vendor_exists", "passed": True, "bc_lookup": {"timing_ms": 150}},
                {"check_name": "po_exists", "passed": True, "bc_lookup": {"timing_ms": 200}}
            ]
        }
        
        entry = BCValidationHistoryEntry.create_bc_validation_entry(
            validation_type="ap_invoice",
            validation_result=validation_result
        )
        
        assert entry["event"] == "on_bc_lookup_success"
        assert entry["bc_validation"]["validation_type"] == "ap_invoice"
        assert entry["bc_validation"]["overall_valid"] is True
        assert entry["bc_validation"]["checks_passed"] == 2
        assert entry["bc_validation"]["checks_total"] == 2
        assert entry["pilot_mode"] is True


# =============================================================================
# TEST 26-28: SERVICE STATUS AND CONFIGURATION
# =============================================================================

class TestServiceStatus:
    """Tests for service status and configuration."""
    
    def test_service_status_returns_correct_structure(self):
        """Test 26: Service status returns expected structure."""
        status = get_bc_sandbox_status()
        
        assert status["service"] == "bc_sandbox_service"
        assert status["read_only"] is True
        assert status["write_operations_blocked"] is True
        assert "config" in status
        assert "available_operations" in status
        assert "blocked_operations" in status
    
    def test_service_status_lists_all_operations(self):
        """Test 27: Service status lists all available operations."""
        status = get_bc_sandbox_status()
        
        expected_operations = [
            "get_vendor",
            "search_vendors_by_name",
            "validate_vendor_exists",
            "get_customer",
            "get_purchase_order",
            "get_purchase_invoice",
            "get_sales_invoice",
            "validate_invoice_exists"
        ]
        
        for op in expected_operations:
            assert op in status["available_operations"]
    
    def test_service_status_lists_blocked_operations(self):
        """Test 28: Service status lists all blocked write operations."""
        status = get_bc_sandbox_status()
        
        expected_blocked = [
            "create_vendor",
            "update_vendor",
            "delete_vendor",
            "create_purchase_invoice",
            "post_purchase_invoice"
        ]
        
        for op in expected_blocked:
            assert op in status["blocked_operations"]


# =============================================================================
# TEST 29-31: BCLOOKUPRESULT CLASS
# =============================================================================

class TestBCLookupResult:
    """Tests for BCLookupResult class."""
    
    def test_lookup_result_to_dict(self):
        """Test 29: BCLookupResult.to_dict() returns correct structure."""
        result = BCLookupResult(
            status=BCLookupStatus.SUCCESS,
            data={"number": "V10000", "displayName": "Test"},
            timing_ms=100,
            endpoint="vendors",
            response_size=50
        )
        
        d = result.to_dict()
        
        assert d["status"] == "success"
        assert d["data"]["number"] == "V10000"
        assert d["timing_ms"] == 100
        assert d["endpoint"] == "vendors"
        assert d["response_size"] == 50
        assert "timestamp" in d
    
    def test_lookup_result_is_success(self):
        """Test 30: BCLookupResult.is_success property works correctly."""
        success_result = BCLookupResult(status=BCLookupStatus.SUCCESS, data={"test": 1})
        demo_result = BCLookupResult(status=BCLookupStatus.DEMO_MODE, data={"test": 1})
        not_found_result = BCLookupResult(status=BCLookupStatus.NOT_FOUND)
        error_result = BCLookupResult(status=BCLookupStatus.ERROR, error="test error")
        
        assert success_result.is_success is True
        assert demo_result.is_success is False  # DEMO_MODE is not SUCCESS
        assert not_found_result.is_success is False
        assert error_result.is_success is False
    
    def test_lookup_result_is_found(self):
        """Test 31: BCLookupResult.is_found property works correctly."""
        found_result = BCLookupResult(status=BCLookupStatus.SUCCESS, data={"number": "V10000"})
        demo_found = BCLookupResult(status=BCLookupStatus.DEMO_MODE, data={"number": "V10000"})
        not_found = BCLookupResult(status=BCLookupStatus.NOT_FOUND, data={})
        empty_data = BCLookupResult(status=BCLookupStatus.SUCCESS, data={})
        
        assert found_result.is_found is True
        assert demo_found.is_found is True
        assert not_found.is_found is False
        assert empty_data.is_found is False


# =============================================================================
# TEST 32: MOCK DATA CONSISTENCY
# =============================================================================

class TestMockData:
    """Tests for mock data consistency."""
    
    def test_mock_vendors_have_required_fields(self):
        """Test 32: Mock vendors have all required fields."""
        required_fields = ["number", "displayName", "id", "email"]
        
        for vendor in MOCK_VENDORS:
            for field in required_fields:
                assert field in vendor, f"Vendor {vendor.get('number')} missing field: {field}"
    
    def test_mock_customers_have_required_fields(self):
        """Test 33: Mock customers have all required fields."""
        required_fields = ["number", "displayName", "id"]
        
        for customer in MOCK_CUSTOMERS:
            for field in required_fields:
                assert field in customer, f"Customer {customer.get('number')} missing field: {field}"
    
    def test_mock_purchase_orders_have_required_fields(self):
        """Test 34: Mock purchase orders have all required fields."""
        required_fields = ["number", "id", "vendorNumber", "status"]
        
        for po in MOCK_PURCHASE_ORDERS:
            for field in required_fields:
                assert field in po, f"PO {po.get('number')} missing field: {field}"


# =============================================================================
# TEST 35: EXCEPTION CLASSES
# =============================================================================

class TestExceptions:
    """Tests for exception classes."""
    
    def test_pilot_mode_write_blocked_error(self):
        """Test 35: PilotModeWriteBlockedError contains operation info."""
        error = PilotModeWriteBlockedError("create_vendor", "Custom message")
        
        assert error.operation == "create_vendor"
        assert error.message == "Custom message"
        # The str() of the error is the message
        assert "Custom message" in str(error)
    
    def test_bc_sandbox_error(self):
        """Test 36: BCSandboxError contains status and details."""
        error = BCSandboxError("Test error", status_code=404, details={"key": "value"})
        
        assert error.message == "Test error"
        assert error.status_code == 404
        assert error.details["key"] == "value"


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
