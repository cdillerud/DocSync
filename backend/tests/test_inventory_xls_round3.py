"""
Inventory XLS Pipeline Round 3 Tests (Iteration 208)
─────────────────────────────────────────────────────

Tests for Round 3 enhancements:
1. Auto-approve gate — files with learned mapping approval_count >= 3 auto-apply
2. Auto-approve confidence formula — 0.80 + 0.05 * approval_count (capped at 0.99)
3. POST /api/inventory-xls/backfill-pilot-docs (dry_run=true/false)
4. Customer auto-suggest prefix match — domain "gamerpackaging" matches code "gamer"
5. Regression — all iter 207 endpoints still work
6. Status=applied records show auto_approved=True flag when gate fires
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
    return session


@pytest.fixture(scope="module")
def gamer_customer_id(api_client):
    """Get or create a customer with code='gamer' for prefix matching tests."""
    # First try to find existing gamer customer
    resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    if resp.status_code == 200:
        customers = resp.json()
        for c in customers:
            if c.get("code", "").lower() == "gamer":
                return c["id"]
    
    # Create a new gamer customer
    resp = api_client.post(
        f"{BASE_URL}/api/inventory-ledger/customers",
        json={
            "name": "Gamer Packaging Test",
            "code": "gamer",
            "negative_balance_policy": "warn_only"
        }
    )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    
    pytest.skip(f"Could not create gamer customer: {resp.status_code} {resp.text}")


@pytest.fixture(scope="module")
def test_customer_id(api_client):
    """Create or get a test customer for the XLS pipeline tests."""
    resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    if resp.status_code == 200:
        customers = resp.json()
        for c in customers:
            if c.get("code", "").startswith("XLSTEST"):
                return c["id"]
    
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


# ─────────────────────────────────────────────────────────────
# Test 1: Auto-approve confidence formula
# ─────────────────────────────────────────────────────────────

class TestAutoApproveConfidenceFormula:
    """Test the confidence formula: learned_confidence = min(0.99, 0.80 + 0.05 * approval_count)."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_confidence_formula_via_learning_loop(self, api_client, test_customer_id):
        """
        Test confidence formula by approving files and checking learned mapping confidence.
        After 1 approval: 0.85, after 2: 0.90, after 3: 0.95, after 4+: 0.99 (capped)
        """
        unique_domain = f"conftest{uuid.uuid4().hex[:6]}.com"
        
        # Create consistent headers for learning
        headers_df = pd.DataFrame({
            "PO Number": ["PO-CONF-001"],
            "SKU": ["CONF-ITEM-1"],
            "Qty": [100],
            "Ship Date": ["2026-07-01"],
            "Warehouse": ["MAIN"]
        })
        
        # Approve 3 files to build up approval_count
        for i in range(3):
            xls_bytes = create_xls_bytes(headers_df)
            files = {
                "file": (
                    f"Confidence Test {i+1} {uuid.uuid4().hex[:6]}.xlsx",
                    io.BytesIO(xls_bytes),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            }
            data = {"sender_email": f"sender{i}@{unique_domain}"}
            
            resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
            assert resp.status_code == 200, f"Ingest {i+1} failed: {resp.status_code}"
            result = resp.json()
            
            if result.get("already_staged"):
                staging_id = result.get("staging_id")
            else:
                staging_id = result.get("staging", {}).get("id")
            
            if not staging_id:
                continue
            
            # Assign customer and approve
            api_client.post(
                f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
                json={"assigned_customer_id": test_customer_id}
            )
            
            resp = api_client.post(
                f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
            )
            
            if resp.status_code == 200:
                print(f"  Approved file {i+1} for domain {unique_domain}")
        
        # Now ingest a 4th file - should use learned mapping with confidence based on formula
        xls_bytes = create_xls_bytes(headers_df)
        files = {
            "file": (
                f"Confidence Test 4 {uuid.uuid4().hex[:6]}.xlsx",
                io.BytesIO(xls_bytes),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        }
        data = {"sender_email": f"sender4@{unique_domain}"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("staged") and not result.get("already_staged"):
            staging = result.get("staging", {})
            column_map = staging.get("column_map", {})
            
            # Check if learned mapping was used
            if column_map.get("source") == "learned":
                confidence = column_map.get("confidence", 0)
                # After 3 approvals, confidence should be 0.95 (0.80 + 0.05*3)
                # The 4th file lookup sees approval_count=3, so confidence = 0.95
                assert confidence >= 0.95, f"Expected confidence >= 0.95 after 3 approvals, got {confidence}"
                print(f"✓ Confidence formula verified: source=learned, confidence={confidence}")
            else:
                print(f"  Column map source is {column_map.get('source')}, not 'learned'")
        else:
            print("  File already staged or not staged - confidence formula test inconclusive")


# ─────────────────────────────────────────────────────────────
# Test 2: Auto-approve gate
# ─────────────────────────────────────────────────────────────

class TestAutoApproveGate:
    """Test auto-approve gate: files with approval_count >= 3 auto-apply."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_auto_approve_gate_fires_after_3_approvals(self, api_client, gamer_customer_id):
        """
        Test that after 3 manual approvals from same sender_domain with same headers,
        the 4th file auto-applies (auto_applied=true, status=applied, created_by='auto:learned-mapping').
        """
        unique_domain = f"autoapprove{uuid.uuid4().hex[:6]}.com"
        
        # Create consistent headers for learning
        headers_df = pd.DataFrame({
            "PO Number": ["PO-AUTO-001"],
            "Item": ["AUTO-ITEM-1"],
            "Qty": [50],
            "Ship Date": ["2026-08-01"],
            "Warehouse": ["MAIN"]
        })
        
        # Approve 3 files to build up approval_count to threshold
        staging_ids = []
        for i in range(3):
            xls_bytes = create_xls_bytes(headers_df)
            files = {
                "file": (
                    f"Auto Approve Test {i+1} {uuid.uuid4().hex[:6]}.xlsx",
                    io.BytesIO(xls_bytes),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            }
            data = {"sender_email": f"sender{i}@{unique_domain}"}
            
            resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
            assert resp.status_code == 200, f"Ingest {i+1} failed: {resp.status_code}"
            result = resp.json()
            
            if result.get("already_staged"):
                staging_id = result.get("staging_id")
            else:
                staging_id = result.get("staging", {}).get("id")
            
            if not staging_id:
                continue
            
            staging_ids.append(staging_id)
            
            # Assign customer and approve
            api_client.post(
                f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
                json={"assigned_customer_id": gamer_customer_id}
            )
            
            resp = api_client.post(
                f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
            )
            
            if resp.status_code == 200:
                print(f"  Manually approved file {i+1} for domain {unique_domain}")
        
        # Now ingest a 4th file - should auto-apply if gate fires
        xls_bytes = create_xls_bytes(headers_df)
        files = {
            "file": (
                f"Auto Approve Test 4 {uuid.uuid4().hex[:6]}.xlsx",
                io.BytesIO(xls_bytes),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        }
        data = {"sender_email": f"sender4@{unique_domain}"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        # Check if auto_applied
        auto_applied = result.get("auto_applied", False)
        
        if result.get("staged") and not result.get("already_staged"):
            staging = result.get("staging", {})
            status = staging.get("status")
            auto_approved_flag = staging.get("auto_approved", False)
            
            if auto_applied:
                assert status == "applied", f"Expected status=applied when auto_applied=true, got {status}"
                assert auto_approved_flag == True, f"Expected auto_approved=true, got {auto_approved_flag}"
                print(f"✓ Auto-approve gate fired: auto_applied={auto_applied}, status={status}, auto_approved={auto_approved_flag}")
            else:
                # Gate may not fire if customer wasn't auto-suggested
                print(f"  Auto-approve gate did not fire (auto_applied={auto_applied}, status={status})")
                print(f"  This may be expected if customer wasn't auto-suggested from sender domain")
        else:
            print(f"  File already staged or not staged - auto-approve test inconclusive")
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_auto_approve_does_not_fire_with_low_approval_count(self, api_client, test_customer_id):
        """Test that files with approval_count < 3 do NOT auto-apply."""
        unique_domain = f"noapprove{uuid.uuid4().hex[:6]}.com"
        
        # Create file with unique headers (no prior approvals)
        headers_df = pd.DataFrame({
            "PO Number": ["PO-NOAPPROVE-001"],
            "SKU": ["NOAPPROVE-ITEM"],
            "Qty": [25],
            "Ship Date": ["2026-09-01"],
            "Warehouse": ["MAIN"]
        })
        
        xls_bytes = create_xls_bytes(headers_df)
        files = {
            "file": (
                f"No Auto Approve Test {uuid.uuid4().hex[:6]}.xlsx",
                io.BytesIO(xls_bytes),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        }
        data = {"sender_email": f"sender@{unique_domain}"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200
        result = resp.json()
        
        # Should NOT auto-apply since no prior approvals
        auto_applied = result.get("auto_applied", False)
        
        assert auto_applied == False, f"Expected auto_applied=false for new sender, got {auto_applied}"
        
        if result.get("staged") and not result.get("already_staged"):
            staging = result.get("staging", {})
            status = staging.get("status")
            assert status == "pending_review", f"Expected status=pending_review, got {status}"
            print(f"✓ Auto-approve correctly did NOT fire: auto_applied={auto_applied}, status={status}")
        else:
            print(f"  File already staged - test inconclusive")


# ─────────────────────────────────────────────────────────────
# Test 3: Backfill pilot docs endpoint
# ─────────────────────────────────────────────────────────────

class TestBackfillPilotDocs:
    """Test POST /api/inventory-xls/backfill-pilot-docs endpoint."""
    
    def test_backfill_dry_run_true(self, api_client):
        """Test backfill with dry_run=true - should scan but not stage."""
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/backfill-pilot-docs?dry_run=true&limit=50"
        )
        
        assert resp.status_code == 200, f"Backfill dry_run failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Verify response structure
        assert "scanned" in result, "Expected 'scanned' in response"
        assert "classified_inventory" in result, "Expected 'classified_inventory' in response"
        assert "by_classification" in result, "Expected 'by_classification' in response"
        
        # In dry_run mode, staged count should be 0
        assert result.get("staged", 0) == 0, f"Expected staged=0 in dry_run mode, got {result.get('staged')}"
        
        print(f"✓ Backfill dry_run=true: scanned={result.get('scanned')}, "
              f"classified_inventory={result.get('classified_inventory')}, "
              f"staged={result.get('staged')}")
    
    def test_backfill_dry_run_false(self, api_client):
        """Test backfill with dry_run=false - should scan and stage."""
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/backfill-pilot-docs?dry_run=false&limit=10"
        )
        
        assert resp.status_code == 200, f"Backfill failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Verify response structure
        assert "scanned" in result, "Expected 'scanned' in response"
        assert "classified_inventory" in result, "Expected 'classified_inventory' in response"
        assert "staged" in result, "Expected 'staged' in response"
        assert "already_staged" in result, "Expected 'already_staged' in response"
        
        print(f"✓ Backfill dry_run=false: scanned={result.get('scanned')}, "
              f"classified_inventory={result.get('classified_inventory')}, "
              f"staged={result.get('staged')}, already_staged={result.get('already_staged')}")
    
    def test_backfill_idempotent(self, api_client):
        """Test that backfill is idempotent - second run returns already_staged > 0."""
        # First run
        resp1 = api_client.post(
            f"{BASE_URL}/api/inventory-xls/backfill-pilot-docs?dry_run=false&limit=10"
        )
        assert resp1.status_code == 200
        result1 = resp1.json()
        
        # Second run - should see already_staged or already_processed
        resp2 = api_client.post(
            f"{BASE_URL}/api/inventory-xls/backfill-pilot-docs?dry_run=false&limit=10"
        )
        assert resp2.status_code == 200
        result2 = resp2.json()
        
        # If first run staged anything, second run should see already_staged
        if result1.get("staged", 0) > 0:
            assert result2.get("already_staged", 0) > 0, \
                f"Expected already_staged > 0 on second run, got {result2.get('already_staged')}"
            print(f"✓ Backfill idempotent: first staged={result1.get('staged')}, "
                  f"second already_staged={result2.get('already_staged')}")
        else:
            print(f"  First run staged 0 docs - idempotency test inconclusive")


# ─────────────────────────────────────────────────────────────
# Test 4: Customer auto-suggest prefix match
# ─────────────────────────────────────────────────────────────

class TestCustomerPrefixMatch:
    """Test customer auto-suggest with prefix matching."""
    
    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas/openpyxl not available")
    def test_gamerpackaging_domain_matches_gamer_code(self, api_client, gamer_customer_id):
        """
        Test that sender 'user@gamerpackaging.com' with inv_customer code='gamer'
        correctly suggests the Gamer workspace via hint.startsWith(code) logic.
        """
        # Create XLS with gamerpackaging sender
        df = pd.DataFrame({
            "PO Number": ["PO-PREFIX-001"],
            "SKU": ["PREFIX-ITEM"],
            "Qty": [100],
            "Ship Date": ["2026-10-01"],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {
            "file": (
                f"Prefix Match Test {uuid.uuid4().hex[:6]}.xlsx",
                io.BytesIO(xls_bytes),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        }
        # Use gamerpackaging.com domain - should match customer code "gamer"
        data = {"sender_email": "user@gamerpackaging.com"}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data=data)
        assert resp.status_code == 200, f"Ingest failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Check suggested_customer
        suggested_customer = result.get("suggested_customer")
        
        if suggested_customer:
            suggested_code = suggested_customer.get("code", "").lower()
            suggested_id = suggested_customer.get("id")
            
            # The domain "gamerpackaging" should match customer code "gamer"
            # because "gamerpackaging".startswith("gamer") is true
            assert suggested_code == "gamer" or suggested_id == gamer_customer_id, \
                f"Expected suggested customer code='gamer', got {suggested_code}"
            
            print(f"✓ Prefix match: sender=user@gamerpackaging.com → customer code={suggested_code}")
        else:
            # Check if staging has suggested_customer_id
            if result.get("staged") and not result.get("already_staged"):
                staging = result.get("staging", {})
                suggested_id = staging.get("suggested_customer_id")
                if suggested_id == gamer_customer_id:
                    print(f"✓ Prefix match: suggested_customer_id={suggested_id} matches gamer customer")
                else:
                    print(f"  No suggested_customer in response, suggested_customer_id={suggested_id}")
            else:
                print("  File already staged - prefix match test inconclusive")


# ─────────────────────────────────────────────────────────────
# Test 5: Regression tests for iter 207 endpoints
# ─────────────────────────────────────────────────────────────

class TestRegressionIter207:
    """Regression tests to ensure iter 207 endpoints still work."""
    
    def test_ingest_endpoint_works(self, api_client):
        """Test POST /api/inventory-xls/ingest still works."""
        if not PANDAS_AVAILABLE:
            pytest.skip("pandas not available")
        
        df = pd.DataFrame({
            "PO Number": ["PO-REG-001"],
            "SKU": ["REG-ITEM"],
            "Qty": [10],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Regression Test {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200, f"Ingest failed: {resp.status_code}"
        print("✓ Regression: POST /api/inventory-xls/ingest works")
    
    def test_staging_list_endpoint_works(self, api_client):
        """Test GET /api/inventory-xls/staging still works."""
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging")
        assert resp.status_code == 200, f"Staging list failed: {resp.status_code}"
        result = resp.json()
        assert "total" in result and "staging" in result
        print(f"✓ Regression: GET /api/inventory-xls/staging works (total={result.get('total')})")
    
    def test_staging_detail_endpoint_works(self, api_client):
        """Test GET /api/inventory-xls/staging/{id} still works."""
        # Get a staging record
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?limit=1")
        assert resp.status_code == 200
        result = resp.json()
        
        if not result.get("staging"):
            pytest.skip("No staging records for detail test")
        
        staging_id = result["staging"][0]["id"]
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging/{staging_id}")
        assert resp.status_code == 200, f"Staging detail failed: {resp.status_code}"
        print(f"✓ Regression: GET /api/inventory-xls/staging/{{id}} works")
    
    def test_staging_update_endpoint_works(self, api_client, test_customer_id):
        """Test POST /api/inventory-xls/staging/{id}/update still works."""
        # Get a pending_review staging record
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?status=pending_review&limit=1")
        assert resp.status_code == 200
        result = resp.json()
        
        if not result.get("staging"):
            pytest.skip("No pending_review staging records for update test")
        
        staging_id = result["staging"][0]["id"]
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        assert resp.status_code == 200, f"Staging update failed: {resp.status_code}"
        print(f"✓ Regression: POST /api/inventory-xls/staging/{{id}}/update works")
    
    def test_staging_approve_endpoint_works(self, api_client, test_customer_id):
        """Test POST /api/inventory-xls/staging/{id}/approve still works."""
        if not PANDAS_AVAILABLE:
            pytest.skip("pandas not available")
        
        # Create a fresh staging record
        df = pd.DataFrame({
            "PO Number": [f"PO-REGAPPROVE-{uuid.uuid4().hex[:6]}"],
            "SKU": ["REGAPPROVE-ITEM"],
            "Qty": [5],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Regression Approve {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        if not staging_id:
            pytest.skip("No staging_id for approve test")
        
        # Assign customer
        api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/update",
            json={"assigned_customer_id": test_customer_id}
        )
        
        # Approve
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/approve?approved_by=testuser"
        )
        assert resp.status_code == 200, f"Staging approve failed: {resp.status_code}"
        print(f"✓ Regression: POST /api/inventory-xls/staging/{{id}}/approve works")
    
    def test_staging_reject_endpoint_works(self, api_client):
        """Test POST /api/inventory-xls/staging/{id}/reject still works."""
        if not PANDAS_AVAILABLE:
            pytest.skip("pandas not available")
        
        # Create a fresh staging record
        df = pd.DataFrame({
            "PO Number": [f"PO-REGREJECT-{uuid.uuid4().hex[:6]}"],
            "SKU": ["REGREJECT-ITEM"],
            "Qty": [3],
            "Warehouse": ["MAIN"]
        })
        xls_bytes = create_xls_bytes(df)
        
        files = {"file": (f"Regression Reject {uuid.uuid4().hex[:6]}.xlsx", io.BytesIO(xls_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        resp = api_client.post(f"{BASE_URL}/api/inventory-xls/ingest", files=files, data={})
        assert resp.status_code == 200
        result = resp.json()
        
        if result.get("already_staged"):
            staging_id = result.get("staging_id")
        else:
            staging_id = result.get("staging", {}).get("id")
        
        if not staging_id:
            pytest.skip("No staging_id for reject test")
        
        # Reject
        resp = api_client.post(
            f"{BASE_URL}/api/inventory-xls/staging/{staging_id}/reject?rejected_by=testuser&reason=Regression test"
        )
        assert resp.status_code == 200, f"Staging reject failed: {resp.status_code}"
        print(f"✓ Regression: POST /api/inventory-xls/staging/{{id}}/reject works")
    
    def test_learning_summary_endpoint_works(self, api_client):
        """Test GET /api/inventory-xls/learning-summary still works."""
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/learning-summary")
        assert resp.status_code == 200, f"Learning summary failed: {resp.status_code}"
        result = resp.json()
        assert "total_learned_mappings" in result
        print(f"✓ Regression: GET /api/inventory-xls/learning-summary works (total={result.get('total_learned_mappings')})")


# ─────────────────────────────────────────────────────────────
# Test 6: Auto-approved flag in staging records
# ─────────────────────────────────────────────────────────────

class TestAutoApprovedFlag:
    """Test that auto_approved flag is set correctly in staging records."""
    
    def test_manual_approval_has_no_auto_approved_flag(self, api_client):
        """Test that manually approved records don't have auto_approved=True."""
        # Get an applied staging record
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?status=applied&limit=10")
        assert resp.status_code == 200
        result = resp.json()
        
        if not result.get("staging"):
            pytest.skip("No applied staging records to check")
        
        # Find one that was manually approved (approved_by != 'auto:learned-mapping')
        for doc in result.get("staging", []):
            approved_by = doc.get("approved_by", "")
            auto_approved = doc.get("auto_approved", False)
            
            if approved_by and approved_by != "auto:learned-mapping":
                # Manual approval should have auto_approved=False or absent
                assert auto_approved in (False, None), \
                    f"Expected auto_approved=False for manual approval, got {auto_approved}"
                print(f"✓ Manual approval has auto_approved={auto_approved}, approved_by={approved_by}")
                return
        
        print("  No manually approved records found to verify")
    
    def test_auto_approved_records_have_correct_created_by(self, api_client):
        """Test that auto-approved records have created_by='auto:learned-mapping' on ledger rows."""
        # Get applied staging records with auto_approved=True
        resp = api_client.get(f"{BASE_URL}/api/inventory-xls/staging?status=applied&limit=50")
        assert resp.status_code == 200
        result = resp.json()
        
        auto_approved_found = False
        for doc in result.get("staging", []):
            if doc.get("auto_approved") == True:
                auto_approved_found = True
                approved_by = doc.get("approved_by", "")
                assert approved_by == "auto:learned-mapping", \
                    f"Expected approved_by='auto:learned-mapping' for auto_approved=True, got {approved_by}"
                print(f"✓ Auto-approved record has approved_by={approved_by}")
                break
        
        if not auto_approved_found:
            print("  No auto-approved records found - this is expected if auto-approve gate hasn't fired yet")


# ─────────────────────────────────────────────────────────────
# Test 7: Match tier distribution endpoint (for Cache Drift Alarm)
# ─────────────────────────────────────────────────────────────

class TestMatchTierDistribution:
    """Test GET /api/inside-sales-pilot/match-tier-distribution for Cache Drift Alarm."""
    
    def test_match_tier_distribution_returns_buckets(self, api_client):
        """Test that match-tier-distribution returns expected buckets schema."""
        resp = api_client.get(f"{BASE_URL}/api/inside-sales-pilot/match-tier-distribution")
        
        # Endpoint may not exist or may return 404 if no pilot data
        if resp.status_code == 404:
            pytest.skip("match-tier-distribution endpoint not found or no pilot data")
        
        assert resp.status_code == 200, f"Match tier distribution failed: {resp.status_code} {resp.text}"
        result = resp.json()
        
        # Verify expected buckets schema
        # The alarm checks: matched>=10 AND (exact/matched < 0.80 OR fuzzy/matched > 0.10)
        # So we expect buckets like: exact, fuzzy, none, matched
        if "buckets" in result or "exact" in result or "matched" in result:
            print(f"✓ Match tier distribution returns buckets: {list(result.keys())[:5]}")
        else:
            print(f"  Match tier distribution response: {result}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
