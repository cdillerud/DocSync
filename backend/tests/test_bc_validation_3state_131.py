"""
BC Validation 3-State Status Tests (iteration 131)

Tests for the BC Validation badge fix:
- PASSED (all checks pass)
- WARNINGS (optional checks fail)
- FAILED (required checks fail)

The validation_status field is computed in bc_validation_service.py:
- "pass" = every check passed
- "warn" = some optional checks failed, all required passed
- "fail" = at least one required check failed
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBCValidation3State:
    """Tests for BC Validation 3-state status computation"""
    
    def test_document_has_validation_status_fail(self):
        """Test that document a959d504 has validation_status=fail (bc_connection required check failed)"""
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        doc = data.get('document', {})
        vr = doc.get('validation_results', {})
        
        # Verify validation_status field exists and is 'fail'
        validation_status = vr.get('validation_status')
        assert validation_status == 'fail', f"Expected validation_status='fail', got '{validation_status}'"
        
        # Verify all_passed is False
        all_passed = vr.get('all_passed')
        assert all_passed == False, f"Expected all_passed=False, got {all_passed}"
        
        # Verify there is at least one failed required check
        checks = vr.get('checks', [])
        required_failures = [c for c in checks if c.get('required') and not c.get('passed')]
        assert len(required_failures) > 0, "Expected at least one required failed check"
        
        # Verify bc_connection check is the failing required check
        bc_connection_check = next((c for c in checks if c.get('check_name') == 'bc_connection'), None)
        assert bc_connection_check is not None, "Expected bc_connection check to exist"
        assert bc_connection_check.get('passed') == False, "Expected bc_connection check to be failed"
        assert bc_connection_check.get('required') == True, "Expected bc_connection check to be required"
        
        print(f"SUCCESS: Document has validation_status='fail' with bc_connection required check failed")
    
    def test_document_has_pipeline_stages(self):
        """Test that document a959d504 has pipeline_stages data for Pipeline Visualization"""
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/document-intelligence/{doc_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        pipeline_stages = data.get('pipeline_stages', {})
        
        # Verify pipeline_stages exists and has data
        assert pipeline_stages, "Expected pipeline_stages to have data"
        
        # Verify all 5 stages are present
        expected_stages = ['parse', 'classify', 'extract', 'validate', 'route']
        for stage in expected_stages:
            assert stage in pipeline_stages, f"Expected stage '{stage}' in pipeline_stages"
            stage_data = pipeline_stages[stage]
            assert 'status' in stage_data, f"Expected 'status' field in stage '{stage}'"
            assert 'ms' in stage_data, f"Expected 'ms' field in stage '{stage}'"
        
        # Verify validate stage is failed (bc validation failed)
        validate_status = pipeline_stages.get('validate', {}).get('status')
        assert validate_status == 'failed', f"Expected validate stage status='failed', got '{validate_status}'"
        
        print(f"SUCCESS: Document has pipeline_stages data with all 5 stages")
    
    def test_frontend_computes_validation_status_from_checks(self):
        """Test that frontend can compute validation_status from checks array (backward compatibility)"""
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        doc = data.get('document', {})
        vr = doc.get('validation_results', {})
        
        # Simulate frontend logic from DocumentDetailPage.js lines 603-608
        checks = vr.get('checks', [])
        failed_checks = [c for c in checks if not c.get('passed', True)]
        required_failures = [c for c in failed_checks if c.get('required', False)]
        
        # Frontend computes: validation_status || computed status
        backend_status = vr.get('validation_status')
        if required_failures:
            computed_status = 'fail'
        elif failed_checks:
            computed_status = 'warn'
        else:
            computed_status = 'pass'
        
        # Either backend provides it or frontend can compute it
        final_status = backend_status or computed_status
        
        assert final_status == 'fail', f"Expected final status='fail', got '{final_status}'"
        print(f"SUCCESS: Frontend can compute validation_status from checks array")
    
    def test_validation_status_values(self):
        """Test that validation_status can be 'pass', 'warn', or 'fail'"""
        # This test verifies the expected possible values
        valid_statuses = ['pass', 'warn', 'fail']
        
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        doc = data.get('document', {})
        vr = doc.get('validation_results', {})
        
        validation_status = vr.get('validation_status')
        assert validation_status in valid_statuses, f"Expected validation_status in {valid_statuses}, got '{validation_status}'"
        print(f"SUCCESS: validation_status='{validation_status}' is a valid value")


class TestItemMappingsAPI:
    """Tests for Item Mappings API (regression tests from iteration 130)"""
    
    def test_get_item_mappings(self):
        """Test GET /api/gpi-integration/item-mappings returns mappings"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert 'mappings' in data, "Expected 'mappings' key in response"
        assert 'total' in data, "Expected 'total' key in response"
        
        # Verify mappings is a list
        mappings = data.get('mappings', [])
        assert isinstance(mappings, list), "Expected mappings to be a list"
        
        # Previous test showed 20 rules exist
        assert len(mappings) > 0, "Expected at least one mapping rule"
        
        print(f"SUCCESS: GET /api/gpi-integration/item-mappings returned {len(mappings)} mappings")


class TestDocumentDetailAPI:
    """Tests for Document Detail API"""
    
    def test_document_detail_returns_required_fields(self):
        """Test that document detail returns all required fields for BC Validation card"""
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify top-level structure
        assert 'document' in data, "Expected 'document' key in response"
        assert 'workflows' in data, "Expected 'workflows' key in response"
        assert 'event_timeline' in data, "Expected 'event_timeline' key in response"
        assert 'derived_state' in data, "Expected 'derived_state' key in response"
        
        doc = data.get('document', {})
        
        # Verify validation_results exists
        vr = doc.get('validation_results', {})
        assert vr, "Expected validation_results to have data"
        
        # Verify required fields for BC Validation card
        assert 'checks' in vr, "Expected 'checks' in validation_results"
        assert 'extraction_quality' in vr, "Expected 'extraction_quality' in validation_results"
        
        # Verify extraction_quality has required fields
        eq = vr.get('extraction_quality', {})
        assert 'completeness_score' in eq, "Expected 'completeness_score' in extraction_quality"
        assert 'total_extracted' in eq, "Expected 'total_extracted' in extraction_quality"
        assert 'total_defined' in eq, "Expected 'total_defined' in extraction_quality"
        
        print(f"SUCCESS: Document detail returns all required fields for BC Validation card")
    
    def test_derived_state_validation_state(self):
        """Test that derived_state shows validation_state correctly"""
        doc_id = "a959d504-fc69-420f-a0c1-2ae318211d76"
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        derived_state = data.get('derived_state', {})
        
        # Verify validation_state in derived_state
        validation_state = derived_state.get('validation_state')
        assert validation_state == 'fail', f"Expected validation_state='fail', got '{validation_state}'"
        
        # Verify blocking_issues contains bc_connection
        blocking_issues = derived_state.get('blocking_issues', [])
        assert 'bc_connection' in blocking_issues, "Expected 'bc_connection' in blocking_issues"
        
        print(f"SUCCESS: derived_state shows validation_state='fail' with bc_connection blocking")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
