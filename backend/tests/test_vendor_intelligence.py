"""
Vendor Intelligence Service API Tests

Tests for:
- GET /api/vendor-intelligence/stats (aggregate stats)
- GET /api/vendor-intelligence/profiles (list with pagination)
- GET /api/vendor-intelligence/profiles/{vendor_id} (single profile)
- POST /api/vendor-intelligence/rebuild (trigger rebuild)
- GET /api/vendor-intelligence/resolver-hints/{vendor_name} (resolver hints)
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestVendorIntelligenceStats:
    """Test GET /api/vendor-intelligence/stats endpoint"""
    
    def test_stats_returns_200(self):
        """Stats endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_stats_has_required_fields(self):
        """Stats should contain all required aggregate fields"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        assert response.status_code == 200
        data = response.json()
        
        # Check all required fields exist
        required_fields = ['total_vendors', 'stable_vendors', 'avg_automation_rate', 'domain_distribution']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify field types
        assert isinstance(data['total_vendors'], int), "total_vendors should be int"
        assert isinstance(data['stable_vendors'], int), "stable_vendors should be int"
        assert isinstance(data['avg_automation_rate'], (int, float)), "avg_automation_rate should be numeric"
        assert isinstance(data['domain_distribution'], dict), "domain_distribution should be dict"
    
    def test_stats_domain_distribution_structure(self):
        """Domain distribution should have purchase/sales/shipping keys"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        assert response.status_code == 200
        data = response.json()
        
        domain_dist = data.get('domain_distribution', {})
        expected_domains = ['purchase', 'sales', 'shipping']
        for domain in expected_domains:
            assert domain in domain_dist, f"Missing domain: {domain}"
            assert isinstance(domain_dist[domain], int), f"{domain} count should be int"


class TestVendorIntelligenceProfiles:
    """Test GET /api/vendor-intelligence/profiles endpoint"""
    
    def test_profiles_list_returns_200(self):
        """Profiles list endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles")
        assert response.status_code == 200
    
    def test_profiles_list_has_profiles_and_total(self):
        """Response should have profiles array and total count"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles")
        assert response.status_code == 200
        data = response.json()
        
        assert 'profiles' in data, "Missing 'profiles' field"
        assert 'total' in data, "Missing 'total' field"
        assert isinstance(data['profiles'], list), "profiles should be a list"
        assert isinstance(data['total'], int), "total should be int"
    
    def test_profiles_pagination(self):
        """Profiles should support skip/limit pagination"""
        # First page
        response1 = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?skip=0&limit=5")
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second page
        response2 = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?skip=5&limit=5")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Verify pagination works
        assert len(data1['profiles']) <= 5, "First page should have at most 5 profiles"
        
        # If there are enough profiles, second page should be different
        if data1['total'] > 5 and len(data2['profiles']) > 0:
            first_page_ids = [p.get('vendor_no') for p in data1['profiles']]
            second_page_ids = [p.get('vendor_no') for p in data2['profiles']]
            # Check no overlap
            assert not any(vid in first_page_ids for vid in second_page_ids), "Pages should not overlap"
    
    def test_profile_has_required_fields(self):
        """Each profile should have all required behavioral metrics"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        assert response.status_code == 200
        data = response.json()
        
        if len(data['profiles']) > 0:
            profile = data['profiles'][0]
            required_fields = [
                'vendor_no', 'vendor_name', 'invoice_count',
                'po_reference_frequency', 'bol_presence_rate', 'shipment_reference_frequency',
                'typical_reference_domain', 'stable_vendor_flag', 'automation_success_rate',
                'typical_bc_match_types'
            ]
            for field in required_fields:
                assert field in profile, f"Missing required field in profile: {field}"
    
    def test_profiles_sort_by_invoice_count(self):
        """Profiles should be sortable by invoice_count"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?sort_by=invoice_count&limit=10")
        assert response.status_code == 200
        data = response.json()
        
        profiles = data['profiles']
        if len(profiles) > 1:
            # Verify descending sort
            counts = [p.get('invoice_count', 0) for p in profiles]
            assert counts == sorted(counts, reverse=True), "Profiles should be sorted by invoice_count descending"


class TestVendorProfileDetail:
    """Test GET /api/vendor-intelligence/profiles/{vendor_id} endpoint"""
    
    def test_get_profile_by_vendor_no(self):
        """Should get profile by vendor_no"""
        # First get a valid vendor_no
        list_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        assert list_resp.status_code == 200
        profiles = list_resp.json().get('profiles', [])
        
        if len(profiles) > 0:
            vendor_no = profiles[0].get('vendor_no')
            response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles/{vendor_no}")
            assert response.status_code == 200
            
            data = response.json()
            assert data.get('vendor_no') == vendor_no, "Returned vendor_no should match"
    
    def test_get_profile_not_found(self):
        """Should return 404 for non-existent vendor"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles/NONEXISTENT_VENDOR_999")
        assert response.status_code == 404
    
    def test_profile_detail_has_all_metrics(self):
        """Profile detail should include all behavioral metrics"""
        list_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        profiles = list_resp.json().get('profiles', [])
        
        if len(profiles) > 0:
            vendor_no = profiles[0].get('vendor_no')
            response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles/{vendor_no}")
            assert response.status_code == 200
            
            profile = response.json()
            
            # Check all behavioral metrics
            assert 'po_reference_frequency' in profile
            assert 'bol_presence_rate' in profile
            assert 'shipment_reference_frequency' in profile
            assert 'automation_success_rate' in profile
            assert 'reference_resolution_success_rate' in profile
            assert 'typical_bc_match_types' in profile
            assert 'stable_vendor_flag' in profile
            
            # Check numeric values are valid rates (0-1)
            assert 0 <= profile.get('po_reference_frequency', 0) <= 1
            assert 0 <= profile.get('automation_success_rate', 0) <= 1


class TestVendorIntelligenceRebuild:
    """Test POST /api/vendor-intelligence/rebuild endpoint"""
    
    def test_rebuild_returns_200(self):
        """Rebuild endpoint should accept POST and return status"""
        response = requests.post(f"{BASE_URL}/api/vendor-intelligence/rebuild")
        assert response.status_code == 200
    
    def test_rebuild_returns_status_message(self):
        """Rebuild should return status and message"""
        response = requests.post(f"{BASE_URL}/api/vendor-intelligence/rebuild")
        assert response.status_code == 200
        
        data = response.json()
        assert 'status' in data, "Missing 'status' field"
        assert data['status'] == 'rebuild_started', "Status should be 'rebuild_started'"


class TestVendorResolverHints:
    """Test GET /api/vendor-intelligence/resolver-hints/{vendor_name} endpoint"""
    
    def test_resolver_hints_for_known_vendor(self):
        """Should return hints for a vendor with enough documents"""
        # Get a vendor with documents
        list_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=5")
        profiles = list_resp.json().get('profiles', [])
        
        # Find vendor with at least 3 documents (threshold for hints)
        vendor_with_docs = None
        for p in profiles:
            if p.get('invoice_count', 0) >= 3:
                vendor_with_docs = p.get('vendor_name')
                break
        
        if vendor_with_docs:
            response = requests.get(f"{BASE_URL}/api/vendor-intelligence/resolver-hints/{vendor_with_docs}")
            assert response.status_code == 200
            
            data = response.json()
            assert 'has_hints' in data
            if data.get('has_hints'):
                assert 'preferred_domain' in data
                assert 'vendor_name' in data
    
    def test_resolver_hints_for_new_vendor(self):
        """Should return no hints for vendor with few documents"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/resolver-hints/BRAND_NEW_VENDOR_NEVER_SEEN")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get('has_hints') == False, "New vendor should have no hints"
    
    def test_resolver_hints_structure(self):
        """Hints should have proper structure when available"""
        # Use TUMALO CREEK as test vendor (has 6 documents)
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/resolver-hints/TUMALO CREEK Transportation")
        assert response.status_code == 200
        
        data = response.json()
        if data.get('has_hints'):
            # Check hint structure
            expected_fields = ['vendor_name', 'preferred_domain', 'behavior_score_boost']
            for field in expected_fields:
                assert field in data, f"Missing hint field: {field}"
            
            # Check optional boost fields when present
            if 'search_order_boost' in data:
                assert isinstance(data['search_order_boost'], list), "search_order_boost should be list"


class TestVendorIntelligenceIntegration:
    """Integration tests for vendor intelligence flow"""
    
    def test_stats_match_profile_counts(self):
        """Stats total_vendors should match profiles total"""
        stats_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        profiles_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        
        assert stats_resp.status_code == 200
        assert profiles_resp.status_code == 200
        
        stats = stats_resp.json()
        profiles_data = profiles_resp.json()
        
        assert stats['total_vendors'] == profiles_data['total'], \
            f"Stats total_vendors ({stats['total_vendors']}) should match profiles total ({profiles_data['total']})"
    
    def test_vendor_profile_data_consistency(self):
        """Profile from list should match profile from detail endpoint"""
        list_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?limit=1")
        profiles = list_resp.json().get('profiles', [])
        
        if len(profiles) > 0:
            list_profile = profiles[0]
            vendor_no = list_profile.get('vendor_no')
            
            detail_resp = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles/{vendor_no}")
            assert detail_resp.status_code == 200
            detail_profile = detail_resp.json()
            
            # Key fields should match
            assert list_profile['vendor_name'] == detail_profile['vendor_name']
            assert list_profile['invoice_count'] == detail_profile['invoice_count']
            assert list_profile['automation_success_rate'] == detail_profile['automation_success_rate']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
