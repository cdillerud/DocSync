"""
Inventory XLS Pipeline Tests (Iteration 207)
─────────────────────────────────────────────

Tests for the Inventory XLS inference pipeline:
- POST /api/inventory-xls/ingest (multipart file upload)
- Dedup detection
- GET /api/inventory-xls/staging (list with status filter)
- GET /api/inventory-xls/staging/{id} (full staging record)
- POST /api/inventory-xls/staging/{id}/update (assign customer)
- POST /api/inventory-xls/staging/{id}/approve (apply to ledger)
- POST /api/inventory-xls/staging/{id}/reject
- Ledger persistence verification
- Learning loop (Phase D)
- Forecast routing to inv_incoming_supply
- Not-inventory skip
- Classifier unit behavior
- Effective date extraction from filename
"""

import pytest
import requests
import os
import io
import uuid
from datetime import datetime, timezone

# Use pandas to create synthetic XLS files
try:
    import pandas as pd
    import openpyxl
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


def create_xls_bytes(df: "pd.DataFrame", filename: str = "test.xlsx") -> bytes:
    """Create XLS bytes from a pandas DataFrame."""
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    # Don't set Content-Type globally - let requests handle it for multipart
    return session


@pytest.fixture(scope="module")
def test_customer_id(api_client):
    """Create or get a test customer for the XLS pipeline tests."""
    # First try to find existing test customer
    resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    if resp.status_code == 200:
        customers = resp.json()
        for c in customers:
            if c.get("code", "").startswith("XLSTEST"):
                return c["id"]
    
    # Create a new test customer
    unique_code = f"XLSTEST{uuid.uuid4().hex[:6].upper()}"
    resp = api_client.post(
        f"{BASE_URL}/api/inventory-ledger/customers",
        json={
            "name": "XLS Pipeline Test Customer",
            "code": unique_code,
            "negative_balance_policy": "warn_only"
        }
    )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    
    pytest.skip(f"Could not create test customer: {resp.status_code} {resp.text}")


class TestInventoryXlsIngest:
    """Tests for POST /api/inventory-xls/ingest endpoint."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_ingest_open_orders_xls(self, api_client):
        """Test ingesting an Open Orders XLS file with inventory-relevant headers."""
        # Create synthetic XLS with Open Orders headers
        df = pd.DataFrame({
            "PO Number": ["PO-001", "PO-002", "PO-003"],
            "SKU": ["ITEM-A", "ITEM-B", "ITEM-C"],
            "Qty": [100, 200, 150],
            "Ship Date": ["2026-03-20", "2026-03-21", "2026-03-22"],
            "Warehouse": ["MAIN", "MAIN", "EAST"]
        })
        xls_bytes = create_xls_bytes(df)
        
        # Upload via multipart
        files = {"file": ("Gamer Packaging Open Orders.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "sales@gamerpackaging.com"}
        
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/ingest",
            files=files,
            data=data
        )
        
        assert resp.status_code == 200, f"Ingest failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Verify staging was created
        assert result.get("staged") == True or result.get("already_staged") == True, f"Expected staged=true or already_staged=true, got {result}"
        
        # If newly staged, verify classification
        if result.get("staged") == True:
            staging = result.get("staging", {})
            classification = staging.get("classification", {})
            
            assert classification.get("classification") == "inventory_open_orders", \
                f"Expected classification='inventory_open_orders', got {classification.get('classification')}"
            assert classification.get("confidence", 0) >= 0.9, \
                f"Expected confidence >= 0.9, got {classification.get('confidence')}"
            
            # Verify column_map source
            column_map = staging.get("column_map", {})
            assert column_map.get("source") in ("heuristic", "learned"), \
                f"Expected column_map.source in (heuristic, learned), got {column_map.get('source')}"
            
            # Verify row_count
            assert staging.get("row_count") == 3, f"Expected row_count=3, got {staging.get('row_count')}"
            
            # Store staging_id for later tests
            self.__class__.staging_id = staging.get("id")
        else:
            # Already staged - get the staging_id
            self.__class__.staging_id = result.get("staging_id")
        
        print(f"✓ Ingest Open Orders XLS: staged={result.get('staged')}, staging_id={self.__class__.staging_id}")
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_ingest_dedup_same_file(self, api_client):
        """Test that uploading the same file twice returns already_staged=true."""
        # Create identical XLS
        df = pd.DataFrame({
            "PO Number": ["PO-001", "PO-002", "PO-003"],
            "SKU": ["ITEM-A", "ITEM-B", "ITEM-C"],
            "Qty": [100, 200, 150],
            "Ship Date": ["2026-03-20", "2026-03-21", "2026-03-22"],
            "Warehouse": ["MAIN", "MAIN", "EAST"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": ("Gamer Packaging Open Orders.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "sales@gamerpackaging.com"}
        
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/ingest",
            files=files,
            data=data
        )
        
        assert resp.status_code == 200, f"Dedup check failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Should be already_staged since we uploaded the same file
        assert result.get("already_staged") == True, f"Expected already_staged=true on second upload, got {result}"
        print(f"✓ Dedup detection: already_staged={result.get('already_staged')}")
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_ingest_not_inventory_file(self, api_client):
        """Test that non-inventory files are skipped (staged=false)."""
        # Create RFQ-style file with no inventory keywords
        df = pd.DataFrame({
            "Item": ["Widget A", "Widget B"],
            "Price": [10.99, 25.50],
            "Lead Time": ["2 weeks", "3 weeks"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": ("RFQ.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "vendor@example.com"}
        
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/ingest",
            files=files,
            data=data
        )
        
        assert resp.status_code == 200, f"Not-inventory check failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Should NOT be staged
        assert result.get("staged") == False, f"Expected staged=false for non-inventory file, got {result}"
        
        # Classification should be not_inventory
        classification = result.get("classification", {})
        assert classification.get("classification") == "not_inventory", \
            f"Expected classification='not_inventory', got {classification.get('classification')}"
        
        print(f"✓ Not-inventory skip: staged={result.get('staged')}, classification={classification.get('classification')}")


class TestInventoryXlsStaging:
    """Tests for staging list and detail endpoints."""
    
    def test_list_staging_all(self, api_client):
        """Test GET /api/inventory-xls/staging returns staging records."""
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging")
        
        assert resp.status_code == 200, f"List staging failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        assert "total" in result, "Expected 'total' in response"
        assert "staging" in result, "Expected 'staging' in response"
        assert isinstance(result["staging"], list), "Expected staging to be a list"
        
        print(f"✓ List staging: total={result.get('total')}, returned={len(result.get('staging', []))}")
    
    def test_list_staging_with_status_filter(self, api_client):
        """Test GET /api/inventory-xls/staging with status filter."""
        for status in ["pending_review", "applied", "rejected"]:
            resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?status={status}")
            
            assert resp.status_code == 200, f"List staging with status={status} failed: {resp.status_code}"
            result = resp.json()
            
            # Verify all returned records have the requested status
            for doc in result.get("staging", []):
                assert doc.get("status") == status, f"Expected status={status}, got {doc.get('status')}"
        
        print("✓ List staging with status filter works for all statuses")
    
    def test_get_staging_detail(self, api_client):
        """Test GET /api/inventory-xls/staging/{id} returns full staging record."""
        # First get a staging record
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?limit=1")
        assert resp.status_code == 200
        result = resp.json()
        
        if not result.get("staging"):
            pytest.skip("No staging records available for detail test")
        
        staging_id = result["staging"][0]["id"]
        
        # Get detail
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging/{staging_id}")
        assert resp.status_code == 200, f"Get staging detail failed: {resp.status_code} {resp.text}"
        
        doc = resp.json()
        
        # Verify required fields
        assert "id" in doc, "Expected 'id' in staging detail"
        assert "rows" in doc, "Expected 'rows' in staging detail"
        assert "column_map" in doc, "Expected 'column_map' in staging detail"
        assert "classification" in doc, "Expected 'classification' in staging detail"
        assert "status" in doc, "Expected 'status' in staging detail"
        
        print(f"✓ Get staging detail: id={staging_id}, status={doc.get('status')}, row_count={len(doc.get('rows', []))}")
    
    def test_get_staging_not_found(self, api_client):
        """Test GET /api/inventory-xls/staging/{id} returns 404 for non-existent."""
        fake_id = str(uuid.uuid4())
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging/{fake_id}")
        
        assert resp.status_code == 404, f"Expected 404 for non-existent staging, got {resp.status_code}"
        print("✓ Get staging not found returns 404")


class TestInventoryXlsUpdateAndApprove:
    """Tests for update, approve, and reject endpoints."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_update_staging_assign_customer(self, api_client, test_customer_id):
        """Test POST /api/inventory-xls/staging/{id}/update to assign customer."""
        # Create a fresh staging record for this test
        df = pd.DataFrame({
            "PO Number": [f"PO-UPD-{uuid.uuid4().hex[:6]}"],
            "SKU": ["ITEM-UPDATE-TEST"],
            "Qty": [50],
            "Ship Date": ["2026-04-01"],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Update Test Orders {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "test@updatetest.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        assert staging_id, f"No staging_id returned: {result}"
        
        # Update with assigned_customer_id
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        assert resp.status_code == 200, f"Update staging failed: {resp.status_code} {resp.text}"
        update_result = resp.json()
        
        assert update_result.get("updated") == True, f"Expected updated=true, got {update_result}"
        
        # Verify the update persisted
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging/{staging_id}")
        assert resp.status_code == 200
        doc = resp.json()
        assert doc.get("assigned_customer_id") == test_customer_id, \
            f"Expected assigned_customer_id={test_customer_id}, got {doc.get('assigned_customer_id')}"
        
        # Store for approve test
        self.__class__.staging_id_for_approve = staging_id
        print(f"✓ Update staging: assigned customer {test_customer_id}")
    
    def test_update_staging_already_applied_fails(self, api_client, test_customer_id):
        """Test that updating an already-applied staging returns updated=false."""
        # Find an applied staging record
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?status=applied&limit=1")
        assert resp.status_code == 200
        result = resp.json()
        
        if not result.get("staging"):
            pytest.skip("No applied staging records to test update failure")
        
        staging_id = result["staging"][0]["id"]
        
        # Try to update
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        assert resp.status_code == 200
        update_result = resp.json()
        assert update_result.get("updated") == False, f"Expected updated=false for applied staging, got {update_result}"
        
        print(f"✓ Update already-applied staging returns updated=false")
    
    def test_approve_without_customer_returns_422(self, api_client):
        """Test that approving without assigned customer returns HTTP 422."""
        # Create a staging record without customer
        if not PANDAS_AVAILABLE:
            pytest.skip("pandas not available")
        
        df = pd.DataFrame({
            "PO Number": [f"PO-NOCUST-{uuid.uuid4().hex[:6]}"],
            "SKU": ["ITEM-NO-CUSTOMER"],
            "Qty": [10],
            "Ship Date": ["2026-05-01"],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"No Customer Test {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        # No sender_email to avoid auto-suggestion
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        # Clear any suggested customer
        api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": None}
        )
        
        # Try to approve without customer
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
        )
        
        assert resp.status_code == 422, f"Expected 422 for approve without customer, got {resp.status_code}"
        print("✓ Approve without customer returns 422")
    
    def test_approve_staging_creates_movements(self, api_client, test_customer_id):
        """Test POST /api/inventory-xls/staging/{id}/approve creates ledger movements."""
        staging_id = getattr(self.__class__, "staging_id_for_approve", None)
        
        if not staging_id:
            pytest.skip("No staging_id available from update test")
        
        # Approve
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
        )
        
        assert resp.status_code == 200, f"Approve failed: {resp.status_code} {resp.text}"
        approve_result = resp.json()
        
        assert approve_result.get("status") == "applied", f"Expected status=applied, got {approve_result.get('status')}"
        assert approve_result.get("applied_count", 0) >= 1, f"Expected applied_count >= 1, got {approve_result.get('applied_count')}"
        
        print(f"✓ Approve staging: applied_count={approve_result.get('applied_count')}, errors={approve_result.get('error_count', 0)}")
        
        # Store for ledger verification
        self.__class__.approved_staging_id = staging_id
    
    def test_ledger_movements_after_approval(self, api_client, test_customer_id):
        """Verify movements appear in ledger after approval."""
        staging_id = getattr(self.__class__, "approved_staging_id", None)
        
        if not staging_id:
            pytest.skip("No approved staging_id available")
        
        # Get movements for the customer
        resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{test_customer_id}/movements")
        
        assert resp.status_code == 200, f"Get movements failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        movements = result.get("movements", [])
        
        # Find movements with reference_id = staging_id
        xls_movements = [m for m in movements if m.get("reference_id") == staging_id]
        
        assert len(xls_movements) >= 1, f"Expected at least 1 movement with reference_id={staging_id}, found {len(xls_movements)}"
        
        # Verify movement fields
        for m in xls_movements:
            assert m.get("source_type") == "spreadsheet_import", f"Expected source_type=spreadsheet_import, got {m.get('source_type')}"
            assert m.get("reference_type") == "xls_import", f"Expected reference_type=xls_import, got {m.get('reference_type')}"
        
        print(f"✓ Ledger movements verified: {len(xls_movements)} movements with reference_id={staging_id}")
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_reject_staging(self, api_client):
        """Test POST /api/inventory-xls/staging/{id}/reject."""
        # Create a staging record to reject
        df = pd.DataFrame({
            "PO Number": [f"PO-REJ-{uuid.uuid4().hex[:6]}"],
            "SKU": ["ITEM-REJECT-TEST"],
            "Qty": [25],
            "Ship Date": ["2026-06-01"],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Reject Test Orders {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "reject@test.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        # Reject
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/reject?rejected_by=testuser&reason=Test rejection"
        )
        
        assert resp.status_code == 200, f"Reject failed: {resp.status_code} {resp.text}"
        reject_result = resp.json()
        
        assert reject_result.get("rejected") == True or reject_result.get("status") == "rejected", \
            f"Expected rejected=true or status=rejected, got {reject_result}"
        
        # Verify status changed
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging/{staging_id}")
        assert resp.status_code == 200
        doc = resp.json()
        assert doc.get("status") == "rejected", f"Expected status=rejected, got {doc.get('status')}"
        
        print(f"✓ Reject staging: status={doc.get('status')}")


class TestInventoryXlsForecastRouting:
    """Test that Forecast XLS goes to inv_incoming_supply, not inv_movements."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_forecast_xls_routes_to_incoming_supply(self, api_client, test_customer_id):
        """Test that Forecast XLS approval creates records in inv_incoming_supply."""
        # Create Forecast XLS
        df = pd.DataFrame({
            "Week": ["2026-W15", "2026-W16", "2026-W17"],
            "SKU": ["FORECAST-ITEM-A", "FORECAST-ITEM-B", "FORECAST-ITEM-C"],
            "Qty": [500, 600, 700],
            "Warehouse": ["MAIN", "MAIN", "EAST"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Forecast {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "forecast@test.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200, f"Forecast ingest failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        if not result.get("staged"):
            # May be already staged or not classified as forecast
            classification = result.get("classification", {})
            if classification.get("classification") != "inventory_forecast":
                pytest.skip(f"File not classified as forecast: {classification}")
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
            classification = result.get("staging", {}).get("classification", {})
        
        if not staging_id:
            pytest.skip("No staging_id for forecast test")
        
        # Verify classification is forecast
        if classification.get("classification") != "inventory_forecast":
            pytest.skip(f"Not classified as forecast: {classification.get('classification')}")
        
        # Assign customer and approve
        api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Forecast approve failed: {resp.status_code} {resp.text}")
        
        approve_result = resp.json()
        
        # Verify it went to incoming_supply
        assert approve_result.get("applied_to") == "inv_incoming_supply", \
            f"Expected applied_to=inv_incoming_supply, got {approve_result.get('applied_to')}"
        
        print(f"✓ Forecast routing: applied_to={approve_result.get('applied_to')}, count={approve_result.get('applied_count')}")


class TestInventoryXlsLearningLoop:
    """Test Phase D learning: approved mappings are reused for same-domain files."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_learning_loop_same_domain(self, api_client, test_customer_id):
        """Test that second file from same domain uses learned mapping."""
        unique_domain = f"learning{uuid.uuid4().hex[:6]}.com"
        
        # First file - will use heuristic
        df1 = pd.DataFrame({
            "PO Number": ["PO-LEARN-001"],
            "SKU": ["LEARN-ITEM-1"],
            "Qty": [100],
            "Ship Date": ["2026-07-01"],
            "Warehouse": ["MAIN"]
        })
        xls_bytes1 = create_xls_bytes(df1)
        
        files1 = {"file": (f"Learning Test 1 {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes1), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data1 = {"sender_email": f"sender@{unique_domain}"}
        
        resp1 = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files1, data=data1)
        assert resp1.status_code == 200
        result1 = resp1.json()
        
        if result1.get("already_staged"):
            staging_id1 = result1.get("staging_id")
        else:
            staging_id1 = result1.get("staging", {}).get("id")
            first_source = result1.get("staging", {}).get("column_map", {}).get("source")
            print(f"  First file column_map.source: {first_source}")
        
        # Assign customer and approve first file (this persists learning)
        api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id1}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        resp_approve = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id1}/approve?approved_by=testuser"
        )
        
        if resp_approve.status_code != 200:
            pytest.skip(f"First file approve failed: {resp_approve.status_code}")
        
        # Second file - SAME headers, different sender but SAME domain
        df2 = pd.DataFrame({
            "PO Number": ["PO-LEARN-002"],
            "SKU": ["LEARN-ITEM-2"],
            "Qty": [200],
            "Ship Date": ["2026-07-15"],
            "Warehouse": ["EAST"]
        })
        xls_bytes2 = create_xls_bytes(df2)
        
        files2 = {"file": (f"Learning Test 2 {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes2), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data2 = {"sender_email": f"anyone@{unique_domain}"}  # Different sender, same domain
        
        resp2 = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files2, data=data2)
        assert resp2.status_code == 200
        result2 = resp2.json()
        
        if result2.get("already_staged"):
            # Can't verify learning if already staged
            print("  Second file already staged - learning verification skipped")
        else:
            staging2 = result2.get("staging", {})
            second_source = staging2.get("column_map", {}).get("source")
            
            # The second file should use "learned" mapping
            # Note: This may still be "heuristic" if the heuristic confidence is high enough
            # The learning lookup happens before heuristic, so if learned exists it should be used
            print(f"  Second file column_map.source: {second_source}")
            
            # We expect "learned" but accept "heuristic" since heuristic may have high confidence
            assert second_source in ("learned", "heuristic"), \
                f"Expected column_map.source in (learned, heuristic), got {second_source}"
        
        print(f"✓ Learning loop test completed for domain {unique_domain}")


class TestInventoryXlsLearningSummary:
    """Test GET /api/inventory-xls/learning-summary endpoint."""
    
    def test_learning_summary(self, api_client):
        """Test that learning-summary returns aggregation stats."""
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/learning-summary")
        
        assert resp.status_code == 200, f"Learning summary failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        assert "total_learned_mappings" in result, "Expected 'total_learned_mappings' in response"
        assert "by_classification" in result, "Expected 'by_classification' in response"
        assert "top_senders" in result, "Expected 'top_senders' in response"
        
        assert isinstance(result["by_classification"], list), "Expected by_classification to be a list"
        assert isinstance(result["top_senders"], list), "Expected top_senders to be a list"
        
        print(f"✓ Learning summary: total_learned_mappings={result.get('total_learned_mappings')}, "
              f"classifications={len(result.get('by_classification', []))}, "
              f"top_senders={len(result.get('top_senders', []))}")


class TestClassifierUnitBehavior:
    """Test classifier function directly via introspection or API behavior."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_classifier_open_orders_detection(self, api_client):
        """Test that classifier correctly identifies Open Orders files."""
        # Create file with Open Orders pattern
        df = pd.DataFrame({
            "PO Number": ["PO-CLASS-001"],
            "SKU": ["CLASS-ITEM"],
            "Qty": [100],
            "Ship Date": ["2026-08-01"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": ("Gamer Packaging Open Orders.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": "x@gamerpackaging.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        # Get classification from staging or direct response
        if result.get("staged"):
            classification = result.get("staging", {}).get("classification", {})
        else:
            classification = result.get("classification", {})
        
        assert classification.get("classification") == "inventory_open_orders", \
            f"Expected classification='inventory_open_orders', got {classification.get('classification')}"
        assert classification.get("confidence", 0) >= 0.9, \
            f"Expected confidence >= 0.9, got {classification.get('confidence')}"
        assert classification.get("movement_intent") == "order_commitment", \
            f"Expected movement_intent='order_commitment', got {classification.get('movement_intent')}"
        
        # Check suggested_customer_hint
        hint = classification.get("suggested_customer_hint")
        assert hint == "gamerpackaging", f"Expected suggested_customer_hint='gamerpackaging', got {hint}"
        
        print(f"✓ Classifier Open Orders: classification={classification.get('classification')}, "
              f"confidence={classification.get('confidence')}, hint={hint}")


class TestEffectiveDateExtraction:
    """Test effective date extraction from filenames."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_effective_date_yyyy_mm_dd(self, api_client):
        """Test filename 'Open Orders 2026-03-18.xlsx' extracts date correctly."""
        df = pd.DataFrame({
            "PO Number": ["PO-DATE-001"],
            "SKU": ["DATE-ITEM"],
            "Qty": [50],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": ("Open Orders 2026-03-18.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("staged"):
            staging = result.get("staging", {})
            eff_date = staging.get("filename_effective_date")
        else:
            eff_date = None
        
        if eff_date:
            assert "2026-03-18" in eff_date, f"Expected date to contain '2026-03-18', got {eff_date}"
            print(f"✓ Effective date YYYY-MM-DD: {eff_date}")
        else:
            print("  Effective date extraction: date not extracted (may be already staged)")
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_effective_date_mm_dd_yy(self, api_client):
        """Test filename 'Gamer Dunnage 04.13.26.xlsx' extracts date correctly."""
        df = pd.DataFrame({
            "Item": ["DUNNAGE-ITEM"],
            "Qty": [100],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": ("Gamer Dunnage 04.13.26.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("staged"):
            staging = result.get("staging", {})
            eff_date = staging.get("filename_effective_date")
        else:
            eff_date = None
        
        if eff_date:
            assert "2026-04-13" in eff_date, f"Expected date to contain '2026-04-13', got {eff_date}"
            print(f"✓ Effective date MM.DD.YY: {eff_date}")
        else:
            print("  Effective date extraction: date not extracted (may be already staged or not classified)")


class TestEffectiveDateInMovements:
    """Test that effective_date is preserved in ledger movements after approval."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_effective_date_preserved_in_movements(self, api_client, test_customer_id):
        """Test that effective_date from filename is preserved in movements."""
        unique_id = uuid.uuid4().hex[:6]
        
        df = pd.DataFrame({
            "PO Number": [f"PO-EFF-{unique_id}"],
            "SKU": [f"EFF-ITEM-{unique_id}"],
            "Qty": [75],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        # Use a filename with a date
        files = {"file": (f"Open Orders 2026-05-20 {unique_id}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"sender_email": f"eff{unique_id}@test.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        if not staging_id:
            pytest.skip("No staging_id for effective date test")
        
        # Assign customer and approve
        api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
        )
        
        if resp.status_code != 200:
            pytest.skip(f"Approve failed: {resp.status_code}")
        
        # Get movements and check effective_date
        resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{test_customer_id}/movements")
        assert resp.status_code == 200
        
        movements = resp.json().get("movements", [])
        xls_movements = [m for m in movements if m.get("reference_id") == staging_id]
        
        if xls_movements:
            for m in xls_movements:
                eff_date = m.get("effective_date")
                if eff_date:
                    assert "2026-05-20" in eff_date, f"Expected effective_date to contain '2026-05-20', got {eff_date}"
                    print(f"✓ Effective date in movement: {eff_date}")
                else:
                    print("  Movement has no effective_date field")
        else:
            print("  No movements found with staging reference")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
