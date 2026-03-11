"""
Test suite for Automated Threshold Alerts feature (alert_pattern_service)

Tests the following endpoints:
- GET /api/alerts/summary — returns total_active, critical, warning, info counts
- GET /api/alerts/active — returns array of alert objects
- GET /api/alerts/all — returns all alerts
- GET /api/alerts/all?include_resolved=true — includes resolved/dismissed alerts
- GET /api/alerts/active?severity=info — filters by severity
- GET /api/alerts/active?vendor=Cargo%20Modules — filters by vendor
- POST /api/alerts/evaluate — manually triggers evaluation
- POST /api/alerts/{pattern_key}/dismiss — dismisses alert
- POST /api/alerts/{pattern_key}/resolve — resolves alert

Pattern key format: 'PO→posted_sales_shipment' (uses Unicode arrow U+2192)
"""

import pytest
import requests
import os
import urllib.parse

# Use production URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAlertPatternServiceEndpoints:
    """Test all alert pattern service endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        if not BASE_URL:
            pytest.skip("REACT_APP_BACKEND_URL not set")
    
    # =========================================================================
    # Module 1: GET /api/alerts/summary
    # =========================================================================
    
    def test_alerts_summary_endpoint_returns_200(self):
        """GET /api/alerts/summary should return 200"""
        response = requests.get(f"{BASE_URL}/api/alerts/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_alerts_summary_response_structure(self):
        """GET /api/alerts/summary should return total_active, critical, warning, info"""
        response = requests.get(f"{BASE_URL}/api/alerts/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Validate required fields
        required_fields = ['total_active', 'critical', 'warning', 'info']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate types
        assert isinstance(data['total_active'], int), f"total_active should be int, got {type(data['total_active'])}"
        assert isinstance(data['critical'], int), f"critical should be int, got {type(data['critical'])}"
        assert isinstance(data['warning'], int), f"warning should be int, got {type(data['warning'])}"
        assert isinstance(data['info'], int), f"info should be int, got {type(data['info'])}"
        
        # Validate counts are non-negative
        assert data['total_active'] >= 0
        assert data['critical'] >= 0
        assert data['warning'] >= 0
        assert data['info'] >= 0
        
        # Validate total = sum of severities
        expected_total = data['critical'] + data['warning'] + data['info']
        assert data['total_active'] == expected_total, f"total_active ({data['total_active']}) != sum ({expected_total})"
    
    # =========================================================================
    # Module 2: GET /api/alerts/active
    # =========================================================================
    
    def test_alerts_active_endpoint_returns_200(self):
        """GET /api/alerts/active should return 200"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_alerts_active_returns_array(self):
        """GET /api/alerts/active should return an array"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
    
    def test_alerts_active_alert_structure(self):
        """Active alerts should have required fields"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            alert = data[0]
            required_fields = [
                'pattern_key', 'predicted_label', 'actual_entity_type',
                'severity_level', 'occurrence_count_7d', 'occurrence_count_30d',
                'trend', 'affected_vendors', 'suggested_action', 'status'
            ]
            for field in required_fields:
                assert field in alert, f"Missing required field: {field} in alert"
            
            # Validate severity_level is one of expected values
            assert alert['severity_level'] in ['info', 'warning', 'critical'], \
                f"Invalid severity_level: {alert['severity_level']}"
            
            # Validate trend is one of expected values
            assert alert['trend'] in ['new', 'stable', 'increasing', 'decreasing'], \
                f"Invalid trend: {alert['trend']}"
            
            # Validate status
            assert alert['status'] == 'active', f"Expected status 'active', got {alert['status']}"
            
            # Validate affected_vendors is a list
            assert isinstance(alert['affected_vendors'], list), "affected_vendors should be list"
    
    # =========================================================================
    # Module 3: GET /api/alerts/all
    # =========================================================================
    
    def test_alerts_all_endpoint_returns_200(self):
        """GET /api/alerts/all should return 200"""
        response = requests.get(f"{BASE_URL}/api/alerts/all")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_alerts_all_returns_array(self):
        """GET /api/alerts/all should return an array"""
        response = requests.get(f"{BASE_URL}/api/alerts/all")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
    
    def test_alerts_all_with_include_resolved(self):
        """GET /api/alerts/all?include_resolved=true should include resolved/dismissed alerts"""
        response = requests.get(f"{BASE_URL}/api/alerts/all?include_resolved=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
    
    # =========================================================================
    # Module 4: GET /api/alerts/active with filters
    # =========================================================================
    
    def test_alerts_filter_by_severity_info(self):
        """GET /api/alerts/active?severity=info should filter by severity"""
        response = requests.get(f"{BASE_URL}/api/alerts/active?severity=info")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Verify all returned alerts have severity=info
        for alert in data:
            assert alert['severity_level'] == 'info', \
                f"Expected severity_level 'info', got {alert['severity_level']}"
    
    def test_alerts_filter_by_severity_warning(self):
        """GET /api/alerts/active?severity=warning should filter by severity"""
        response = requests.get(f"{BASE_URL}/api/alerts/active?severity=warning")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Verify all returned alerts have severity=warning
        for alert in data:
            assert alert['severity_level'] == 'warning', \
                f"Expected severity_level 'warning', got {alert['severity_level']}"
    
    def test_alerts_filter_by_severity_critical(self):
        """GET /api/alerts/active?severity=critical should filter by severity"""
        response = requests.get(f"{BASE_URL}/api/alerts/active?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Verify all returned alerts have severity=critical
        for alert in data:
            assert alert['severity_level'] == 'critical', \
                f"Expected severity_level 'critical', got {alert['severity_level']}"
    
    def test_alerts_filter_by_vendor(self):
        """GET /api/alerts/active?vendor=<vendor> should filter by vendor"""
        # First get active alerts to find a vendor to filter by
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        alerts = response.json()
        
        if len(alerts) > 0 and len(alerts[0].get('affected_vendors', [])) > 0:
            vendor = alerts[0]['affected_vendors'][0]
            encoded_vendor = urllib.parse.quote(vendor)
            
            filter_response = requests.get(f"{BASE_URL}/api/alerts/active?vendor={encoded_vendor}")
            assert filter_response.status_code == 200
            filtered = filter_response.json()
            
            # Verify all returned alerts contain the vendor
            for alert in filtered:
                vendors = alert.get('affected_vendors', [])
                vendor_scope = alert.get('vendor_scope', 'global')
                assert vendor in vendors or vendor_scope == vendor, \
                    f"Expected vendor '{vendor}' in alert, got vendors={vendors}, scope={vendor_scope}"
    
    # =========================================================================
    # Module 5: POST /api/alerts/evaluate
    # =========================================================================
    
    def test_alerts_evaluate_endpoint_returns_200(self):
        """POST /api/alerts/evaluate should return 200"""
        response = requests.post(f"{BASE_URL}/api/alerts/evaluate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_alerts_evaluate_response_structure(self):
        """POST /api/alerts/evaluate should return alerts_created, alerts_updated, alerts_resolved"""
        response = requests.post(f"{BASE_URL}/api/alerts/evaluate")
        assert response.status_code == 200
        data = response.json()
        
        # Validate required fields
        required_fields = ['alerts_created', 'alerts_updated', 'alerts_resolved']
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate types
        assert isinstance(data['alerts_created'], int)
        assert isinstance(data['alerts_updated'], int)
        assert isinstance(data['alerts_resolved'], int)
        
        # Validate non-negative
        assert data['alerts_created'] >= 0
        assert data['alerts_updated'] >= 0
        assert data['alerts_resolved'] >= 0
    
    # =========================================================================
    # Module 6: POST /api/alerts/{pattern_key}/dismiss
    # =========================================================================
    
    def test_alerts_dismiss_nonexistent_returns_404(self):
        """POST /api/alerts/{pattern_key}/dismiss for non-existent alert should return 404"""
        fake_key = "FAKE→nonexistent"
        encoded_key = urllib.parse.quote(fake_key)
        response = requests.post(f"{BASE_URL}/api/alerts/{encoded_key}/dismiss")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
    
    # =========================================================================
    # Module 7: POST /api/alerts/{pattern_key}/resolve
    # =========================================================================
    
    def test_alerts_resolve_nonexistent_returns_404(self):
        """POST /api/alerts/{pattern_key}/resolve for non-existent alert should return 404"""
        fake_key = "FAKE→nonexistent"
        encoded_key = urllib.parse.quote(fake_key)
        response = requests.post(f"{BASE_URL}/api/alerts/{encoded_key}/resolve")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


class TestAlertDismissResolveFlow:
    """Test dismiss and resolve flow for existing alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        if not BASE_URL:
            pytest.skip("REACT_APP_BACKEND_URL not set")
    
    def test_dismiss_existing_alert_flow(self):
        """Test dismissing an existing alert - dismiss should remove from active list"""
        # 1. Get active alerts
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        alerts = response.json()
        
        if len(alerts) == 0:
            # Trigger evaluation to create alerts
            eval_resp = requests.post(f"{BASE_URL}/api/alerts/evaluate")
            assert eval_resp.status_code == 200
            
            # Re-fetch alerts
            response = requests.get(f"{BASE_URL}/api/alerts/active")
            alerts = response.json()
        
        if len(alerts) == 0:
            pytest.skip("No active alerts to test dismiss flow")
        
        # 2. Get first alert's pattern_key
        alert = alerts[0]
        pattern_key = alert['pattern_key']
        encoded_key = urllib.parse.quote(pattern_key)
        
        # 3. Dismiss the alert
        dismiss_resp = requests.post(f"{BASE_URL}/api/alerts/{encoded_key}/dismiss")
        assert dismiss_resp.status_code == 200, f"Dismiss failed: {dismiss_resp.text}"
        dismiss_data = dismiss_resp.json()
        
        # 4. Verify response structure
        assert dismiss_data.get('status') == 'dismissed', f"Expected status 'dismissed', got {dismiss_data}"
        
        # 5. Verify alert is no longer in active list
        active_resp = requests.get(f"{BASE_URL}/api/alerts/active")
        active_alerts = active_resp.json()
        active_keys = [a['pattern_key'] for a in active_alerts]
        assert pattern_key not in active_keys, f"Dismissed alert still in active list"
        
        # 6. Verify alert appears in all with include_resolved
        all_resp = requests.get(f"{BASE_URL}/api/alerts/all?include_resolved=true")
        all_alerts = all_resp.json()
        dismissed_alert = next((a for a in all_alerts if a['pattern_key'] == pattern_key), None)
        assert dismissed_alert is not None, f"Dismissed alert not found in all alerts"
        assert dismissed_alert.get('status') == 'dismissed', \
            f"Expected status 'dismissed', got {dismissed_alert.get('status')}"
        
        # 7. Cleanup: Re-trigger evaluation to potentially reactivate alert
        requests.post(f"{BASE_URL}/api/alerts/evaluate")


class TestAlertTrendAndSeverity:
    """Test alert trend and severity fields"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        if not BASE_URL:
            pytest.skip("REACT_APP_BACKEND_URL not set")
    
    def test_alert_trend_pct_field(self):
        """Alerts should include trend_pct field"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        alerts = response.json()
        
        if len(alerts) > 0:
            alert = alerts[0]
            assert 'trend_pct' in alert, "Missing trend_pct field"
            # trend_pct can be positive, negative, or 0
            assert isinstance(alert['trend_pct'], (int, float)), f"trend_pct should be numeric"
    
    def test_alert_occurrence_counts(self):
        """Alerts should include occurrence_count_7d and occurrence_count_30d"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        alerts = response.json()
        
        if len(alerts) > 0:
            alert = alerts[0]
            assert alert['occurrence_count_7d'] >= 0
            assert alert['occurrence_count_30d'] >= 0
            # 30d count should be >= 7d count
            assert alert['occurrence_count_30d'] >= alert['occurrence_count_7d'], \
                f"30d count ({alert['occurrence_count_30d']}) < 7d count ({alert['occurrence_count_7d']})"
    
    def test_alert_suggested_action(self):
        """Alerts should have non-empty suggested_action"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200
        alerts = response.json()
        
        if len(alerts) > 0:
            for alert in alerts:
                action = alert.get('suggested_action', '')
                assert len(action) > 0, f"Alert {alert['pattern_key']} has empty suggested_action"


class TestAlertsSummaryCounts:
    """Test that summary counts match actual alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        if not BASE_URL:
            pytest.skip("REACT_APP_BACKEND_URL not set")
    
    def test_summary_counts_match_active_alerts(self):
        """Summary counts should match count of active alerts by severity"""
        # Get summary
        summary_resp = requests.get(f"{BASE_URL}/api/alerts/summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        
        # Get active alerts
        active_resp = requests.get(f"{BASE_URL}/api/alerts/active")
        assert active_resp.status_code == 200
        alerts = active_resp.json()
        
        # Count by severity
        actual_critical = len([a for a in alerts if a['severity_level'] == 'critical'])
        actual_warning = len([a for a in alerts if a['severity_level'] == 'warning'])
        actual_info = len([a for a in alerts if a['severity_level'] == 'info'])
        
        assert summary['critical'] == actual_critical, \
            f"Summary critical ({summary['critical']}) != actual ({actual_critical})"
        assert summary['warning'] == actual_warning, \
            f"Summary warning ({summary['warning']}) != actual ({actual_warning})"
        assert summary['info'] == actual_info, \
            f"Summary info ({summary['info']}) != actual ({actual_info})"
        assert summary['total_active'] == len(alerts), \
            f"Summary total ({summary['total_active']}) != actual count ({len(alerts)})"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
