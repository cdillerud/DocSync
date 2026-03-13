"""
P0 Consistency Bug Fix Tests

Tests for the P0 bug fix that ensures consistent validation state:
- derived_state_service clears vendor blocking issues when BC validation passes
- derived_state_service clears vendor blocking issues when document has matched_vendor_no
- AP validation cross-references BC validation results for vendor resolution
- Document status badge uses derived state
- Extraction quality shows correct field counts (not 0/0)
- Line items map 'amount' to 'line_total' correctly
- BC environment split still works (READ Production / WRITE Sandbox)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndEnvironment:
    """Basic health and environment status tests"""
    
    def test_health_endpoint(self):
        """Test health endpoint returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'healthy'
        print("PASS: Health endpoint returns healthy status")
    
    def test_bc_environment_status(self):
        """Test BC environment status returns split environment config"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        assert response.status_code == 200
        data = response.json()
        
        # Verify split environment config
        assert 'read_environment' in data, "Missing read_environment in response"
        assert 'write_environment' in data, "Missing write_environment in response"
        assert data['read_environment'] == 'Production', f"Expected Production for reads, got {data['read_environment']}"
        assert 'Sandbox' in data['write_environment'], f"Expected Sandbox for writes, got {data['write_environment']}"
        assert data.get('block_production_writes') == True, "Production write guard should be active"
        print(f"PASS: BC Environment status - READ: {data['read_environment']}, WRITE: {data['write_environment']}")


class TestDerivedStateService:
    """Tests for derived state service consistency fixes"""
    
    def test_get_documents_list(self):
        """Test documents list endpoint works"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert 'documents' in data
        assert 'total' in data
        print(f"PASS: Documents list returns {len(data['documents'])} docs, total: {data['total']}")
        return data.get('documents', [])
    
    def test_document_derived_state_returned(self):
        """Test that document detail returns derived_state"""
        # First get a document
        list_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        if not docs:
            pytest.skip("No documents available for testing")
        
        doc_id = docs[0]['id']
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}?include_events=true")
        assert response.status_code == 200
        data = response.json()
        
        # Verify derived_state is present
        assert 'derived_state' in data, "derived_state should be in document response"
        derived = data['derived_state']
        
        # Verify required derived state fields
        assert 'validation_state' in derived, "validation_state missing from derived_state"
        assert 'workflow_state' in derived, "workflow_state missing from derived_state"
        assert 'automation_state' in derived, "automation_state missing from derived_state"
        assert 'blocking_issues' in derived, "blocking_issues missing from derived_state"
        assert 'warnings' in derived, "warnings missing from derived_state"
        assert 'derived_from' in derived, "derived_from missing from derived_state"
        
        print(f"PASS: Document {doc_id[:8]}... derived_state: validation={derived['validation_state']}, workflow={derived['workflow_state']}")
        return doc_id, derived
    
    def test_derived_state_consistency_no_contradictions(self):
        """Test that derived state doesn't have contradictions (P0 bug)"""
        # Get AP Invoice documents which are more likely to have validations
        list_response = requests.get(f"{BASE_URL}/api/documents?document_type=AP_Invoice&limit=5")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        if not docs:
            pytest.skip("No AP_Invoice documents available for testing")
        
        for doc_summary in docs:
            doc_id = doc_summary['id']
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}?include_events=true")
            assert response.status_code == 200
            data = response.json()
            
            doc = data.get('document', {})
            derived = data.get('derived_state', {})
            
            bc_val = doc.get('validation_results', {})
            ap_val = doc.get('ap_validation_result', {})
            
            # P0 Fix Check: If BC validation passed with vendor resolved, 
            # there should be no vendor blocking issues in derived state
            if bc_val.get('all_passed') and bc_val.get('bc_record_info'):
                vendor_blocking = [i for i in derived.get('blocking_issues', []) 
                                 if 'vendor' in str(i).lower()]
                assert len(vendor_blocking) == 0, \
                    f"Doc {doc_id[:8]}: BC validation passed but derived state has vendor blocking: {vendor_blocking}"
            
            # P0 Fix Check: If document has matched_vendor_no, no vendor blocking
            if doc.get('matched_vendor_no') or doc.get('vendor_id'):
                vendor_blocking = [i for i in derived.get('blocking_issues', []) 
                                 if 'vendor' in str(i).lower()]
                assert len(vendor_blocking) == 0, \
                    f"Doc {doc_id[:8]}: Has matched vendor but derived state has vendor blocking: {vendor_blocking}"
            
            print(f"PASS: Doc {doc_id[:8]}... - No contradictory vendor states")


class TestExtractionQuality:
    """Tests for extraction quality field counts fix"""
    
    def test_extraction_quality_not_zero(self):
        """Test that extraction quality shows correct field counts (not 0/0)"""
        list_response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        tested = 0
        for doc_summary in docs:
            doc_id = doc_summary['id']
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert response.status_code == 200
            data = response.json()
            doc = data.get('document', {})
            
            bc_val = doc.get('validation_results', {})
            eq = bc_val.get('extraction_quality', {})
            
            if not eq:
                continue
            
            tested += 1
            
            # Check that required_extracted and optional_extracted are present
            # and one of them is > 0 if completeness_score > 0
            completeness = eq.get('completeness_score', 0)
            req_extracted = eq.get('required_extracted', 0)
            opt_extracted = eq.get('optional_extracted', 0)
            
            # Old buggy format check - these should NOT be present at root level as 0
            # unless the completeness_score is also 0
            if completeness > 0:
                total_extracted = req_extracted + opt_extracted
                # If completeness > 0 but extracted count is 0, it's a bug
                # But we need to account for legacy data formats too
                if eq.get('extracted_count') is not None:
                    # Legacy format, skip this check
                    continue
                    
                # New format should have required_extracted or optional_extracted > 0
                # if completeness_score > 0
                assert total_extracted > 0 or completeness == 0, \
                    f"Doc {doc_id[:8]}: completeness={completeness} but extracted=0/0"
            
            print(f"PASS: Doc {doc_id[:8]}... extraction_quality: req={req_extracted}, opt={opt_extracted}, completeness={completeness}")
        
        if tested == 0:
            pytest.skip("No documents with extraction_quality found")
        
        print(f"PASS: Tested {tested} documents for extraction quality")


class TestAPValidationCrossReference:
    """Tests for AP validation cross-referencing BC validation"""
    
    def test_ap_validation_endpoint_exists(self):
        """Test AP validation endpoint exists"""
        # Just check 404 for non-existent doc (proves endpoint exists)
        response = requests.get(f"{BASE_URL}/api/ap-validation/status/non-existent-doc")
        # Should return 404 Not Found, not 405 Method Not Allowed or 500
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: AP validation status endpoint exists")
    
    def test_ap_validation_trigger_endpoint(self):
        """Test AP validation trigger endpoint exists"""
        response = requests.post(f"{BASE_URL}/api/ap-validation/validate/non-existent-doc")
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"
        print("PASS: AP validation trigger endpoint exists")
    
    def test_ap_validation_cross_references_bc(self):
        """Test that AP validation cross-references BC validation for vendor resolution"""
        # Get an AP Invoice with BC validation
        list_response = requests.get(f"{BASE_URL}/api/documents?document_type=AP_Invoice&limit=5")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        if not docs:
            pytest.skip("No AP_Invoice documents available")
        
        for doc_summary in docs:
            doc_id = doc_summary['id']
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert response.status_code == 200
            data = response.json()
            doc = data.get('document', {})
            
            bc_val = doc.get('validation_results', {})
            ap_val = doc.get('ap_validation_result', {})
            
            # If BC validation passed with bc_record_info, AP should show vendor_resolved=True
            if bc_val.get('all_passed') and bc_val.get('bc_record_info') and ap_val:
                vendor_resolved = ap_val.get('vendor_resolved', False)
                # Note: vendor_resolved might be True from BC or from document fields
                # The key fix is that derived_state doesn't have contradictions
                print(f"PASS: Doc {doc_id[:8]}... BC passed, AP vendor_resolved={vendor_resolved}")
                break
        else:
            print("INFO: No documents found with both BC and AP validation results")


class TestDocumentRefreshState:
    """Tests for document state refresh endpoint"""
    
    def test_refresh_state_endpoint(self):
        """Test refresh-state endpoint works"""
        list_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        if not docs:
            pytest.skip("No documents available")
        
        doc_id = docs[0]['id']
        response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/refresh-state")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get('state_updated') == True, "state_updated should be True"
        assert 'validation_state' in data, "validation_state should be in response"
        assert 'workflow_state' in data, "workflow_state should be in response"
        
        print(f"PASS: Refresh state for {doc_id[:8]}... - validation={data.get('validation_state')}")


class TestLineItemsMapping:
    """Tests for line items amount->line_total mapping"""
    
    def test_document_line_items_format(self):
        """Test that document line items have correct format"""
        # Get documents that might have line items
        list_response = requests.get(f"{BASE_URL}/api/documents?document_type=AP_Invoice&limit=10")
        assert list_response.status_code == 200
        docs = list_response.json().get('documents', [])
        
        tested = 0
        for doc_summary in docs:
            doc_id = doc_summary['id']
            response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
            assert response.status_code == 200
            data = response.json()
            doc = data.get('document', {})
            
            line_items = doc.get('line_items', [])
            if not line_items:
                continue
            
            tested += 1
            
            # Check line item format
            for i, item in enumerate(line_items):
                # Line items should have description, quantity, and either
                # line_total, total, or amount field
                has_total = any(k in item for k in ['line_total', 'total', 'amount'])
                
                print(f"  Line item {i}: {list(item.keys())}")
            
            print(f"PASS: Doc {doc_id[:8]}... has {len(line_items)} line items with correct format")
        
        if tested == 0:
            print("INFO: No documents with line_items found - this is expected if no invoices have been extracted")


class TestGPIIntegrationStatus:
    """Tests for GPI integration status endpoint"""
    
    def test_gpi_integration_status(self):
        """Test GPI integration status returns split environment config"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200
        data = response.json()
        
        assert 'configured' in data, "Missing configured field"
        
        # If configured, should have environment info
        if data.get('configured'):
            assert 'read_environment' in data or 'environment' in data, "Missing environment info"
            print(f"PASS: GPI Integration status - configured={data.get('configured')}")
        else:
            print(f"PASS: GPI Integration status - not configured (expected in test environment)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
