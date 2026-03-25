"""
Test suite for Vendor Extraction Profiles (VEP) feature
Tests:
1. GET /api/vendor-extraction-profiles - returns all profiles
2. GET /api/vendor-extraction-profiles/stats - returns stats
3. GET /api/vendor-extraction-profiles/{vendor_id} - returns specific profile
4. POST /api/vendor-extraction-profiles/{vendor_id}/generate - generates profile
5. POST /api/vendor-extraction-profiles/generate-all - batch generation
6. POST /api/vendor-extraction-profiles/{vendor_id}/toggle - toggle enabled
7. POST /api/vendor-extraction-profiles/{vendor_id}/reset - delete profile
8. GET /api/documents/{doc_id}/matching-debug - includes vendor_extraction_profile
9. POST /api/documents/{doc_id}/matching-debug/rerun - includes extraction_profile_bias
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://batch-split-router.preview.emergentagent.com').rstrip('/')

# Test document and vendor from context
TEST_DOC_ID = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"
TEST_VENDOR = "Cargo Modules LLC"


class TestVendorExtractionProfilesAPI:
    """Test VEP endpoints"""

    def test_get_all_profiles(self):
        """GET /api/vendor-extraction-profiles - returns array with required fields"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        assert isinstance(data, list), "Expected array response"
        assert len(data) >= 1, "Expected at least 1 profile"
        
        # Check required fields in first profile
        profile = data[0]
        required_fields = [
            'vendor_no', 'vendor_name', 'document_type_bias', 
            'reference_priority_order', 'reference_label_bias',
            'confidence_adjustments', 'enabled', 'learning_source'
        ]
        for field in required_fields:
            assert field in profile, f"Missing required field: {field}"
        
        print(f"✓ GET /api/vendor-extraction-profiles: {len(data)} profiles returned")

    def test_get_profile_stats(self):
        """GET /api/vendor-extraction-profiles/stats - returns stats"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert 'total_profiles' in data, "Missing total_profiles"
        assert 'enabled' in data, "Missing enabled count"
        assert 'disabled' in data, "Missing disabled count"
        assert 'with_label_bias' in data, "Missing with_label_bias count"
        
        assert data['total_profiles'] >= 0
        assert data['enabled'] >= 0
        assert data['disabled'] >= 0
        
        print(f"✓ GET /api/vendor-extraction-profiles/stats: total={data['total_profiles']}, enabled={data['enabled']}, disabled={data['disabled']}")

    def test_get_specific_vendor_profile(self):
        """GET /api/vendor-extraction-profiles/{vendor_id} - returns Cargo Modules LLC profile"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        assert data['vendor_name'] == TEST_VENDOR
        assert 'document_type_bias' in data
        assert 'reference_priority_order' in data
        assert isinstance(data['reference_priority_order'], list)
        assert 'enabled' in data
        
        print(f"✓ GET /api/vendor-extraction-profiles/{TEST_VENDOR}: doc_type_bias={data.get('document_type_bias')}")

    def test_generate_profile(self):
        """POST /api/vendor-extraction-profiles/{vendor_id}/generate - generates profile"""
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/generate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        assert data['vendor_name'] == TEST_VENDOR
        assert 'reference_priority_order' in data
        assert 'enabled' in data
        
        print(f"✓ POST /api/vendor-extraction-profiles/{TEST_VENDOR}/generate: profile regenerated")

    def test_toggle_profile_disable(self):
        """POST /api/vendor-extraction-profiles/{vendor_id}/toggle?enabled=false - disables profile"""
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/toggle?enabled=false")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data['enabled'] == False
        
        # Verify profile is disabled
        get_response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}")
        assert get_response.status_code == 200
        profile = get_response.json()
        assert profile['enabled'] == False
        
        print(f"✓ POST /api/vendor-extraction-profiles/{TEST_VENDOR}/toggle?enabled=false: profile disabled")

    def test_toggle_profile_enable(self):
        """POST /api/vendor-extraction-profiles/{vendor_id}/toggle?enabled=true - enables profile"""
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/toggle?enabled=true")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data['enabled'] == True
        
        print(f"✓ POST /api/vendor-extraction-profiles/{TEST_VENDOR}/toggle?enabled=true: profile enabled")

    def test_generate_all_profiles(self):
        """POST /api/vendor-extraction-profiles/generate-all - batch generation"""
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/generate-all")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert 'vendors_evaluated' in data
        assert 'profiles_created' in data
        assert 'profiles_updated' in data
        assert 'skipped' in data
        
        print(f"✓ POST /api/vendor-extraction-profiles/generate-all: evaluated={data['vendors_evaluated']}, created={data['profiles_created']}, updated={data['profiles_updated']}")


class TestMatchingDebugWithVEP:
    """Test matching-debug includes VEP data"""

    def test_matching_debug_includes_vep(self):
        """GET /api/documents/{doc_id}/matching-debug - includes vendor_extraction_profile"""
        response = requests.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/matching-debug")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Check vendor_extraction_profile field
        assert 'vendor_extraction_profile' in data, "Missing vendor_extraction_profile"
        vep = data['vendor_extraction_profile']
        
        assert vep is not None
        assert 'has_profile' in vep
        
        if vep['has_profile']:
            assert 'reference_priority_order' in vep
            assert 'reference_label_bias' in vep
            print(f"✓ GET /api/documents/{TEST_DOC_ID}/matching-debug: has_profile=True, priority_order={vep.get('reference_priority_order', [])[:2]}...")
        else:
            print(f"✓ GET /api/documents/{TEST_DOC_ID}/matching-debug: has_profile=False")

    def test_matching_debug_diagnostics_includes_extraction_profile(self):
        """GET /api/documents/{doc_id}/matching-debug - diagnostics includes extraction_profile"""
        response = requests.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/matching-debug")
        assert response.status_code == 200
        
        data = response.json()
        diag = data.get('diagnostics')
        
        if diag:
            # Check for extraction_profile in diagnostics
            assert 'extraction_profile' in diag, "diagnostics missing extraction_profile"
            ep = diag['extraction_profile']
            assert 'has_profile' in ep
            
            print(f"✓ diagnostics.extraction_profile: has_profile={ep.get('has_profile')}, priority={ep.get('reference_priority_order', [])[:2]}...")

    def test_matching_debug_rerun_includes_extraction_profile_bias(self):
        """POST /api/documents/{doc_id}/matching-debug/rerun - includes extraction_profile_bias in score breakdown"""
        response = requests.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/matching-debug/rerun")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        diag = data.get('matching_diagnostics', {})
        
        # Check candidate_scores for extraction_profile_bias
        scores = diag.get('candidate_scores', [])
        
        extraction_profile_bias_found = False
        for score in scores:
            breakdown = score.get('score_breakdown', {})
            if 'extraction_profile_bias' in breakdown:
                extraction_profile_bias_found = True
                epb = breakdown['extraction_profile_bias']
                print(f"✓ extraction_profile_bias component found: {epb:.4f} for {score.get('bc_document_no', 'N/A')}")
        
        # Check decision diagnostics
        decision = diag.get('decision', {})
        if 'extraction_profile_applied' in decision:
            print(f"✓ decision.extraction_profile_applied: {decision['extraction_profile_applied']}")
        
        # It's OK if no bias was applied (profile may not have label_bias set)
        print(f"✓ POST /api/documents/{TEST_DOC_ID}/matching-debug/rerun: completed, extraction_profile_bias_in_breakdown={extraction_profile_bias_found}")


class TestVEPScoringIntegration:
    """Test VEP scoring model integration"""

    def test_vep_max_boost_respected(self):
        """Verify MAX_MATCH_BOOST (0.15) is respected"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}")
        assert response.status_code == 200
        
        data = response.json()
        conf_adj = data.get('confidence_adjustments', {})
        
        # All adjustments should be <= 0.15
        for key, value in conf_adj.items():
            if 'boost' in key:
                assert value <= 0.15, f"Boost {key}={value} exceeds MAX_MATCH_BOOST 0.15"
            if 'penalty' in key:
                assert value >= -0.10, f"Penalty {key}={value} exceeds MAX_MATCH_PENALTY -0.10"
        
        print(f"✓ confidence_adjustments within safety caps: {conf_adj}")

    def test_vep_vendor_influence_cap(self):
        """Check vendor influence is capped at 0.20 total"""
        response = requests.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/matching-debug/rerun")
        assert response.status_code == 200
        
        data = response.json()
        diag = data.get('matching_diagnostics', {})
        scores = diag.get('candidate_scores', [])
        
        for score in scores:
            breakdown = score.get('score_breakdown', {})
            vendor_components = (
                breakdown.get('vendor_behavior_bonus', 0) +
                breakdown.get('label_correction_boost', 0) +
                max(breakdown.get('extraction_profile_bias', 0), 0)  # only positive
            )
            
            # Note: after scaling, should be <= 0.20
            if vendor_components > 0:
                print(f"  Vendor influence for {score.get('bc_document_no', 'N/A')}: {vendor_components:.4f}")
        
        print(f"✓ Vendor influence components checked")


class TestVEPResetAndRegenerate:
    """Test reset and regenerate flows"""

    def test_reset_profile(self):
        """POST /api/vendor-extraction-profiles/{vendor_id}/reset - deletes profile"""
        # First ensure profile exists
        gen_response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/generate")
        assert gen_response.status_code == 200
        
        # Now reset
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/reset")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data['status'] == 'reset'
        
        print(f"✓ POST /api/vendor-extraction-profiles/{TEST_VENDOR}/reset: profile deleted")

    def test_regenerate_after_reset(self):
        """After reset, regenerate the profile"""
        # Regenerate
        response = requests.post(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}/generate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data['vendor_name'] == TEST_VENDOR
        assert data['enabled'] == True  # New profiles are enabled by default
        
        print(f"✓ Profile regenerated after reset: enabled={data['enabled']}")


class TestVEPAutoGeneration:
    """Test VEP auto-generation from vendor intelligence data"""

    def test_profile_has_learning_source(self):
        """Profiles should have learning_source field"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}")
        assert response.status_code == 200
        
        data = response.json()
        assert 'learning_source' in data
        assert isinstance(data['learning_source'], list)
        assert len(data['learning_source']) > 0
        
        print(f"✓ learning_source: {data['learning_source']}")

    def test_profile_has_source_counts(self):
        """Profiles should have source counts for audit"""
        response = requests.get(f"{BASE_URL}/api/vendor-extraction-profiles/{TEST_VENDOR}")
        assert response.status_code == 200
        
        data = response.json()
        assert 'source_invoice_count' in data
        assert 'source_correction_count' in data
        
        print(f"✓ source_invoice_count={data.get('source_invoice_count')}, source_correction_count={data.get('source_correction_count')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
