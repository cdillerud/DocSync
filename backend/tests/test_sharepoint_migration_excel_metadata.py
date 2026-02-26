"""
Tests for SharePoint Migration API - Excel Metadata Structure Feature
Verifies the new Excel metadata fields (acct_type, acct_name, document_type, 
document_sub_type, document_status) are properly supported.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')
if BASE_URL:
    BASE_URL = BASE_URL.rstrip('/')


class TestSharePointMigrationSummary:
    """Test GET /api/migration/sharepoint/summary endpoint for Excel metadata breakdowns"""
    
    def test_summary_returns_new_excel_metadata_breakdowns(self):
        """Summary should include by_document_type, by_acct_type, by_document_status"""
        response = requests.get(f"{BASE_URL}/api/migration/sharepoint/summary")
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Data assertions for new Excel metadata breakdowns
        data = response.json()
        assert "by_document_type" in data, "Missing by_document_type in summary"
        assert "by_acct_type" in data, "Missing by_acct_type in summary"
        assert "by_document_status" in data, "Missing by_document_status in summary"
        
        # Verify these are dictionaries
        assert isinstance(data["by_document_type"], dict), "by_document_type should be a dict"
        assert isinstance(data["by_acct_type"], dict), "by_acct_type should be a dict"
        assert isinstance(data["by_document_status"], dict), "by_document_status should be a dict"
        
        # Verify existing fields still present
        assert "total_candidates" in data
        assert "by_status" in data
        assert "by_confidence" in data
        
        print(f"Summary returned: total_candidates={data['total_candidates']}")
        print(f"  by_document_type: {data['by_document_type']}")
        print(f"  by_acct_type: {data['by_acct_type']}")
        print(f"  by_document_status: {data['by_document_status']}")


class TestSharePointMigrationCandidates:
    """Test GET /api/migration/sharepoint/candidates endpoint for Excel metadata fields"""
    
    def test_candidates_include_new_excel_metadata_fields(self):
        """Candidates should include acct_type, acct_name, document_type, etc."""
        response = requests.get(f"{BASE_URL}/api/migration/sharepoint/candidates?limit=10")
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Data assertions
        data = response.json()
        assert "candidates" in data, "Response should have candidates array"
        assert "count" in data, "Response should have count"
        
        candidates = data["candidates"]
        assert len(candidates) > 0, "Should have at least one candidate"
        
        # Check that candidates have the new Excel metadata field keys (may be null)
        candidate = candidates[0]
        excel_metadata_fields = [
            "acct_type", "acct_name", "document_type", 
            "document_sub_type", "document_status"
        ]
        
        for field in excel_metadata_fields:
            # Field should exist in response (can be null/None)
            assert field in candidate or candidate.get(field, "MISSING") != "MISSING", \
                f"Field '{field}' should be present in candidate response"
        
        print(f"First candidate: {candidate.get('file_name')}")
        print(f"  acct_type: {candidate.get('acct_type')}")
        print(f"  document_type: {candidate.get('document_type')}")
        print(f"  document_status: {candidate.get('document_status')}")
    
    def test_candidate_with_populated_excel_metadata(self):
        """At least one candidate should have populated Excel metadata fields"""
        # The test candidate ID that was manually updated
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        response = requests.get(f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "candidate" in data, "Response should have candidate object"
        
        candidate = data["candidate"]
        
        # This specific candidate should have Excel metadata populated
        assert candidate.get("acct_type") is not None, "acct_type should be populated"
        assert candidate.get("document_type") is not None, "document_type should be populated"
        assert candidate.get("document_status") is not None, "document_status should be populated"
        
        print(f"Test candidate Excel metadata:")
        print(f"  acct_type: {candidate.get('acct_type')}")
        print(f"  acct_name: {candidate.get('acct_name')}")
        print(f"  document_type: {candidate.get('document_type')}")
        print(f"  document_sub_type: {candidate.get('document_sub_type')}")
        print(f"  document_status: {candidate.get('document_status')}")


class TestSharePointMigrationCandidateUpdate:
    """Test PATCH /api/migration/sharepoint/candidates/{id} for Excel metadata updates"""
    
    def test_patch_accepts_excel_metadata_fields(self):
        """PATCH should accept and save new Excel metadata fields"""
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        # Update with Excel metadata
        update_data = {
            "acct_type": "Manufacturers / Vendors",
            "acct_name": "Test Vendor Corp",
            "document_type": "Supplier Documents",
            "document_sub_type": "Vendor Agreement",
            "document_status": "Pending"
        }
        
        response = requests.patch(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
            json=update_data,
            headers={"Content-Type": "application/json"}
        )
        
        # Status code assertion
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Data assertions
        data = response.json()
        assert data.get("success") == True, "Update should be successful"
        assert "candidate" in data, "Response should include updated candidate"
        
        updated = data["candidate"]
        
        # Verify all Excel metadata fields were updated
        assert updated.get("acct_type") == "Manufacturers / Vendors", \
            f"acct_type not updated: {updated.get('acct_type')}"
        assert updated.get("acct_name") == "Test Vendor Corp", \
            f"acct_name not updated: {updated.get('acct_name')}"
        assert updated.get("document_type") == "Supplier Documents", \
            f"document_type not updated: {updated.get('document_type')}"
        assert updated.get("document_sub_type") == "Vendor Agreement", \
            f"document_sub_type not updated: {updated.get('document_sub_type')}"
        assert updated.get("document_status") == "Pending", \
            f"document_status not updated: {updated.get('document_status')}"
        
        print("PATCH successfully updated Excel metadata fields")
    
    def test_patch_persists_excel_metadata(self):
        """Verify PATCH changes are persisted to database via GET"""
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        # First update
        update_data = {
            "acct_type": "Customer Accounts",
            "acct_name": "Persisted Customer",
            "document_type": "Customer Documents",
            "document_sub_type": "Test Sub Type",
            "document_status": "Active"
        }
        
        patch_response = requests.patch(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
            json=update_data,
            headers={"Content-Type": "application/json"}
        )
        assert patch_response.status_code == 200
        
        # GET to verify persistence
        get_response = requests.get(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}"
        )
        assert get_response.status_code == 200
        
        candidate = get_response.json()["candidate"]
        
        # Verify data persisted
        assert candidate.get("acct_type") == "Customer Accounts", "acct_type not persisted"
        assert candidate.get("acct_name") == "Persisted Customer", "acct_name not persisted"
        assert candidate.get("document_type") == "Customer Documents", "document_type not persisted"
        assert candidate.get("document_sub_type") == "Test Sub Type", "document_sub_type not persisted"
        assert candidate.get("document_status") == "Active", "document_status not persisted"
        
        print("Excel metadata changes verified as persisted")


class TestSharePointMigrationValidDocTypes:
    """Test that valid document types from Excel structure are accepted"""
    
    @pytest.mark.parametrize("doc_type", [
        "Product Specification Sheet",
        "Product Drawings",
        "Product Pack-Out Specs",
        "Graphical Die Line",
        "Supplier Documents",
        "Marketing Literature",
        "Customer Documents",
        "SOPs / Resources",
        "Agreement Resources",
        "Quality Documents",
        "Other"
    ])
    def test_valid_document_types_accepted(self, doc_type):
        """Various Excel document types should be accepted"""
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        response = requests.patch(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
            json={"document_type": doc_type},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200, f"Document type '{doc_type}' should be accepted"
        
        # Verify it was saved
        data = response.json()
        assert data["candidate"].get("document_type") == doc_type
    
    @pytest.mark.parametrize("acct_type", [
        "Customer Accounts",
        "Manufacturers / Vendors",
        "Corporate Internal",
        "System Resources"
    ])
    def test_valid_acct_types_accepted(self, acct_type):
        """All Excel AcctType values should be accepted"""
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        response = requests.patch(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
            json={"acct_type": acct_type},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200, f"AcctType '{acct_type}' should be accepted"
        assert response.json()["candidate"].get("acct_type") == acct_type
    
    @pytest.mark.parametrize("doc_status", ["Active", "Archived", "Pending"])
    def test_valid_document_status_accepted(self, doc_status):
        """All Excel DocumentStatus values should be accepted"""
        test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
        
        response = requests.patch(
            f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
            json={"document_status": doc_status},
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 200, f"DocumentStatus '{doc_status}' should be accepted"
        assert response.json()["candidate"].get("document_status") == doc_status


# Cleanup fixture to reset test candidate after tests
@pytest.fixture(scope="module", autouse=True)
def reset_test_candidate():
    """Reset test candidate to original state after all tests"""
    yield
    # Restore original values
    test_candidate_id = "2e509aa3-ce81-486a-8349-ceadbf31d12a"
    requests.patch(
        f"{BASE_URL}/api/migration/sharepoint/candidates/{test_candidate_id}",
        json={
            "acct_type": "Customer Accounts",
            "acct_name": "Prospecting Lead",
            "document_type": "Customer Documents",
            "document_sub_type": "Inquiry Form",
            "document_status": "Active"
        },
        headers={"Content-Type": "application/json"}
    )
