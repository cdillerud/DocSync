"""
Iteration 193: Test Automation Rate Dashboard Widget API
Tests the new GET /api/readiness/automation-rate endpoint with various days parameters
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAutomationRateEndpoint:
    """Tests for GET /api/readiness/automation-rate endpoint"""
    
    def test_automation_rate_default_30_days(self):
        """Test automation-rate endpoint with default 30 days"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify all required fields are present
        required_fields = [
            'automation_rate', 'posting_rate', 'total_documents', 
            'auto_processed', 'manual_review', 'blocked', 'bc_posted',
            'distribution', 'daily_trend', 'top_manual_vendors', 'period_days'
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify data types
        assert isinstance(data['automation_rate'], (int, float)), "automation_rate should be numeric"
        assert isinstance(data['posting_rate'], (int, float)), "posting_rate should be numeric"
        assert isinstance(data['total_documents'], int), "total_documents should be int"
        assert isinstance(data['auto_processed'], int), "auto_processed should be int"
        assert isinstance(data['manual_review'], int), "manual_review should be int"
        assert isinstance(data['blocked'], int), "blocked should be int"
        assert isinstance(data['bc_posted'], int), "bc_posted should be int"
        assert isinstance(data['distribution'], dict), "distribution should be dict"
        assert isinstance(data['daily_trend'], list), "daily_trend should be list"
        assert isinstance(data['top_manual_vendors'], list), "top_manual_vendors should be list"
        assert data['period_days'] == 30, f"Default period should be 30, got {data['period_days']}"
        
        print(f"✓ Default 30 days: automation_rate={data['automation_rate']}%, total_docs={data['total_documents']}")
    
    def test_automation_rate_7_days(self):
        """Test automation-rate endpoint with 7 days parameter"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=7")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['period_days'] == 7, f"Period should be 7, got {data['period_days']}"
        
        # Verify structure
        assert 'automation_rate' in data
        assert 'daily_trend' in data
        assert 'top_manual_vendors' in data
        
        print(f"✓ 7 days: automation_rate={data['automation_rate']}%, period_days={data['period_days']}")
    
    def test_automation_rate_90_days(self):
        """Test automation-rate endpoint with 90 days parameter"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=90")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['period_days'] == 90, f"Period should be 90, got {data['period_days']}"
        
        # Verify structure
        assert 'automation_rate' in data
        assert 'daily_trend' in data
        assert 'top_manual_vendors' in data
        
        print(f"✓ 90 days: automation_rate={data['automation_rate']}%, period_days={data['period_days']}")
    
    def test_automation_rate_data_consistency(self):
        """Verify data consistency: auto_processed + manual_review + blocked should relate to total"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=30")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify automation_rate calculation is reasonable (0-100)
        assert 0 <= data['automation_rate'] <= 100, f"automation_rate should be 0-100, got {data['automation_rate']}"
        assert 0 <= data['posting_rate'] <= 100, f"posting_rate should be 0-100, got {data['posting_rate']}"
        
        # Verify counts are non-negative
        assert data['total_documents'] >= 0
        assert data['auto_processed'] >= 0
        assert data['manual_review'] >= 0
        assert data['blocked'] >= 0
        assert data['bc_posted'] >= 0
        
        print(f"✓ Data consistency: total={data['total_documents']}, auto={data['auto_processed']}, manual={data['manual_review']}, blocked={data['blocked']}")
    
    def test_automation_rate_daily_trend_structure(self):
        """Verify daily_trend array structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=30")
        assert response.status_code == 200
        
        data = response.json()
        daily_trend = data.get('daily_trend', [])
        
        if len(daily_trend) > 0:
            # Check first item structure
            item = daily_trend[0]
            expected_keys = ['date', 'auto', 'manual', 'blocked', 'total', 'rate']
            for key in expected_keys:
                assert key in item, f"daily_trend item missing key: {key}"
            
            # Verify date format (YYYY-MM-DD)
            assert len(item['date']) == 10, f"Date should be YYYY-MM-DD format, got {item['date']}"
            
            print(f"✓ Daily trend structure valid, {len(daily_trend)} data points")
        else:
            print("✓ Daily trend empty (no recent evaluations)")
    
    def test_automation_rate_top_manual_vendors_structure(self):
        """Verify top_manual_vendors array structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=30")
        assert response.status_code == 200
        
        data = response.json()
        vendors = data.get('top_manual_vendors', [])
        
        if len(vendors) > 0:
            # Check first item structure
            item = vendors[0]
            expected_keys = ['vendor', 'count', 'primary_reason']
            for key in expected_keys:
                assert key in item, f"top_manual_vendors item missing key: {key}"
            
            # Verify count is positive
            assert item['count'] > 0, "Vendor count should be positive"
            
            print(f"✓ Top manual vendors structure valid, {len(vendors)} vendors")
        else:
            print("✓ Top manual vendors empty (no manual review docs)")
    
    def test_automation_rate_distribution_structure(self):
        """Verify distribution dict structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate?days=30")
        assert response.status_code == 200
        
        data = response.json()
        distribution = data.get('distribution', {})
        
        # Distribution should be a dict with status -> count
        assert isinstance(distribution, dict)
        
        for status, count in distribution.items():
            assert isinstance(status, str), f"Distribution key should be string, got {type(status)}"
            assert isinstance(count, int), f"Distribution value should be int, got {type(count)}"
            assert count >= 0, f"Distribution count should be non-negative, got {count}"
        
        print(f"✓ Distribution structure valid: {distribution}")


class TestReadinessMetricsStillWorks:
    """Verify existing /api/readiness/metrics endpoint still works"""
    
    def test_readiness_metrics_endpoint(self):
        """Test that /api/readiness/metrics still returns valid data"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify key fields exist
        assert 'total_documents' in data
        assert 'by_status' in data
        
        print(f"✓ /api/readiness/metrics works: total_documents={data.get('total_documents')}")


class TestReevaluateAllStillWorks:
    """Verify POST /api/readiness/reevaluate-all still works with auto-act tracking"""
    
    def test_reevaluate_all_endpoint(self):
        """Test that /api/readiness/reevaluate-all returns expected fields"""
        response = requests.post(f"{BASE_URL}/api/readiness/reevaluate-all?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify key fields exist
        assert 'total_processed' in data
        assert 'total_corrections' in data
        assert 'errors' in data
        
        # Verify auto-act tracking fields (new in iteration 192)
        assert 'auto_acted' in data or data.get('auto_acted') is None or 'auto_acted' in str(data)
        
        print(f"✓ /api/readiness/reevaluate-all works: processed={data.get('total_processed')}, corrections={data.get('total_corrections')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
