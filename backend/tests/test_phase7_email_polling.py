"""
Phase 7 C1: Email Polling Observation Infrastructure Tests

Tests for:
- GET /api/email-polling/status - Returns config and last_24h stats
- POST /api/email-polling/trigger - Returns error when EMAIL_POLLING_ENABLED is false
- GET /api/email-polling/logs - Returns mail intake logs
- GET /api/settings/shadow-mode - Includes email_polling section
- Feature flag EMAIL_POLLING_ENABLED defaults to false
- All Phase 6 endpoints still work
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEmailPollingStatus:
    """Test GET /api/email-polling/status endpoint"""
    
    def test_email_polling_status_returns_200(self):
        """GET /api/email-polling/status should return 200"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_email_polling_status_has_config_section(self):
        """Status should include config section with all settings"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert "config" in data, "Response should have 'config' section"
        config = data["config"]
        
        # Verify all config fields are present
        assert "enabled" in config, "Config should have 'enabled' field"
        assert "interval_minutes" in config, "Config should have 'interval_minutes' field"
        assert "user" in config, "Config should have 'user' field"
        assert "lookback_minutes" in config, "Config should have 'lookback_minutes' field"
        assert "max_messages_per_run" in config, "Config should have 'max_messages_per_run' field"
        assert "max_attachment_mb" in config, "Config should have 'max_attachment_mb' field"
    
    def test_email_polling_status_enabled_is_false_by_default(self):
        """EMAIL_POLLING_ENABLED should default to false"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        # Feature flag should be false by default
        assert data["config"]["enabled"] == False, "EMAIL_POLLING_ENABLED should be false by default"
    
    def test_email_polling_status_has_last_24h_stats(self):
        """Status should include last_24h aggregated stats"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert "last_24h" in data, "Response should have 'last_24h' section"
        last_24h = data["last_24h"]
        
        # Verify all stats fields are present
        assert "runs_count" in last_24h, "last_24h should have 'runs_count'"
        assert "messages_scanned" in last_24h, "last_24h should have 'messages_scanned'"
        assert "attachments_processed" in last_24h, "last_24h should have 'attachments_processed'"
        assert "attachments_skipped_duplicate" in last_24h, "last_24h should have 'attachments_skipped_duplicate'"
        assert "attachments_skipped_inline" in last_24h, "last_24h should have 'attachments_skipped_inline'"
        assert "attachments_failed" in last_24h, "last_24h should have 'attachments_failed'"
    
    def test_email_polling_status_has_recent_runs(self):
        """Status should include recent_runs array"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert "recent_runs" in data, "Response should have 'recent_runs' section"
        assert isinstance(data["recent_runs"], list), "recent_runs should be a list"
    
    def test_email_polling_status_has_health_indicator(self):
        """Status should include health indicator"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert "health" in data, "Response should have 'health' field"
        assert data["health"] in ["healthy", "degraded", "unhealthy"], f"Health should be one of healthy/degraded/unhealthy, got {data['health']}"
    
    def test_email_polling_interval_is_5_minutes(self):
        """Default polling interval should be 5 minutes"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["interval_minutes"] == 5, "Default interval should be 5 minutes"


class TestEmailPollingTrigger:
    """Test POST /api/email-polling/trigger endpoint"""
    
    def test_trigger_returns_error_when_disabled(self):
        """POST /api/email-polling/trigger should return error when EMAIL_POLLING_ENABLED is false"""
        response = requests.post(f"{BASE_URL}/api/email-polling/trigger")
        
        # Should return 200 with error message (not 4xx/5xx)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "error" in data, "Response should have 'error' field when polling is disabled"
        assert "EMAIL_POLLING_ENABLED" in data["error"], "Error should mention EMAIL_POLLING_ENABLED flag"
        assert "false" in data["error"].lower(), "Error should indicate the flag is false"
    
    def test_trigger_error_message_is_helpful(self):
        """Error message should guide user to enable the feature"""
        response = requests.post(f"{BASE_URL}/api/email-polling/trigger")
        data = response.json()
        
        # Error message should be actionable
        assert "error" in data
        error_msg = data["error"]
        assert "true" in error_msg.lower() or "enable" in error_msg.lower(), \
            "Error message should guide user to enable the feature"


class TestEmailPollingLogs:
    """Test GET /api/email-polling/logs endpoint"""
    
    def test_logs_returns_200(self):
        """GET /api/email-polling/logs should return 200"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_logs_returns_logs_array(self):
        """Logs endpoint should return logs array"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs")
        data = response.json()
        
        assert "logs" in data, "Response should have 'logs' field"
        assert isinstance(data["logs"], list), "logs should be a list"
    
    def test_logs_returns_count(self):
        """Logs endpoint should return count"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs")
        data = response.json()
        
        assert "count" in data, "Response should have 'count' field"
        assert isinstance(data["count"], int), "count should be an integer"
    
    def test_logs_accepts_days_parameter(self):
        """Logs endpoint should accept days query parameter"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs", params={"days": 7})
        assert response.status_code == 200, f"Expected 200 with days param, got {response.status_code}"
    
    def test_logs_accepts_status_parameter(self):
        """Logs endpoint should accept status query parameter"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs", params={"status": "Processed"})
        assert response.status_code == 200, f"Expected 200 with status param, got {response.status_code}"
    
    def test_logs_accepts_limit_parameter(self):
        """Logs endpoint should accept limit query parameter"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs", params={"limit": 10})
        assert response.status_code == 200, f"Expected 200 with limit param, got {response.status_code}"
        
        data = response.json()
        assert len(data["logs"]) <= 10, "Should respect limit parameter"


class TestShadowModeIncludesEmailPolling:
    """Test that GET /api/settings/shadow-mode includes email_polling section"""
    
    def test_shadow_mode_returns_200(self):
        """GET /api/settings/shadow-mode should return 200"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_shadow_mode_has_email_polling_section(self):
        """Shadow mode status should include email_polling section"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "email_polling" in data, "Shadow mode status should have 'email_polling' section"
    
    def test_shadow_mode_email_polling_has_enabled_field(self):
        """email_polling section should have enabled field"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        email_polling = data["email_polling"]
        assert "enabled" in email_polling, "email_polling should have 'enabled' field"
        assert isinstance(email_polling["enabled"], bool), "enabled should be boolean"
    
    def test_shadow_mode_email_polling_has_user_field(self):
        """email_polling section should have user field"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        email_polling = data["email_polling"]
        assert "user" in email_polling, "email_polling should have 'user' field"
    
    def test_shadow_mode_email_polling_has_interval_field(self):
        """email_polling section should have interval_minutes field"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        email_polling = data["email_polling"]
        assert "interval_minutes" in email_polling, "email_polling should have 'interval_minutes' field"
        assert email_polling["interval_minutes"] == 5, "Default interval should be 5 minutes"


class TestPhase6EndpointsStillWork:
    """Verify all Phase 6 endpoints still work after Phase 7 C1 changes"""
    
    def test_match_score_distribution_still_works(self):
        """GET /api/metrics/match-score-distribution should still work"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "buckets" in data, "Should have buckets"
        assert "summary" in data, "Should have summary"
    
    def test_alias_exceptions_still_works(self):
        """GET /api/metrics/alias-exceptions should still work"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "alias_totals" in data, "Should have alias_totals"
    
    def test_vendor_stability_still_works(self):
        """GET /api/metrics/vendor-stability should still work"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "categories" in data, "Should have categories"
    
    def test_shadow_mode_performance_report_still_works(self):
        """GET /api/reports/shadow-mode-performance should still work"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "executive_summary" in data, "Should have executive_summary"
    
    def test_shadow_mode_post_still_works(self):
        """POST /api/settings/shadow-mode should still work"""
        response = requests.post(
            f"{BASE_URL}/api/settings/shadow-mode",
            json={"notes": "Phase 7 C1 test"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"


class TestPhase4And5EndpointsStillWork:
    """Verify Phase 4-5 functionality still works"""
    
    def test_draft_creation_feature_status(self):
        """GET /api/settings/features/create-draft-header should work"""
        response = requests.get(f"{BASE_URL}/api/settings/features/create-draft-header")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "enabled" in data, "Should have enabled field"
        assert "safety_thresholds" in data, "Should have safety_thresholds"
    
    def test_automation_metrics(self):
        """GET /api/metrics/automation should work"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "total_documents" in data or "automation_rate" in data, "Should have automation metrics"
    
    def test_alias_impact_metrics(self):
        """GET /api/metrics/alias-impact should work"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_vendor_friction_metrics(self):
        """GET /api/metrics/vendors should work"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_settings_status(self):
        """GET /api/settings/status should work"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "demo_mode" in data, "Should have demo_mode"
        assert "features" in data, "Should have features"


class TestIdempotencyStructure:
    """Test that idempotency collections exist and are queryable"""
    
    def test_mail_intake_log_collection_queryable(self):
        """mail_intake_log collection should be queryable via logs endpoint"""
        response = requests.get(f"{BASE_URL}/api/email-polling/logs")
        assert response.status_code == 200, "Should be able to query mail_intake_log"
    
    def test_mail_poll_runs_collection_queryable(self):
        """mail_poll_runs collection should be queryable via status endpoint"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        assert response.status_code == 200, "Should be able to query mail_poll_runs"
        
        data = response.json()
        # recent_runs comes from mail_poll_runs collection
        assert "recent_runs" in data, "Should have recent_runs from mail_poll_runs collection"


class TestFeatureFlagConfiguration:
    """Test feature flag configuration"""
    
    def test_email_polling_enabled_defaults_false(self):
        """EMAIL_POLLING_ENABLED should default to false"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["enabled"] == False, "EMAIL_POLLING_ENABLED should default to false"
    
    def test_email_polling_interval_defaults_5(self):
        """EMAIL_POLLING_INTERVAL_MINUTES should default to 5"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["interval_minutes"] == 5, "Interval should default to 5 minutes"
    
    def test_email_polling_lookback_defaults_60(self):
        """EMAIL_POLLING_LOOKBACK_MINUTES should default to 60"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["lookback_minutes"] == 60, "Lookback should default to 60 minutes"
    
    def test_email_polling_max_messages_defaults_25(self):
        """EMAIL_POLLING_MAX_MESSAGES should default to 25"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["max_messages_per_run"] == 25, "Max messages should default to 25"
    
    def test_email_polling_max_attachment_mb_defaults_25(self):
        """EMAIL_POLLING_MAX_ATTACHMENT_MB should default to 25"""
        response = requests.get(f"{BASE_URL}/api/email-polling/status")
        data = response.json()
        
        assert data["config"]["max_attachment_mb"] == 25, "Max attachment MB should default to 25"


class TestCoreEndpointsStillWork:
    """Verify core document hub endpoints still work"""
    
    def test_dashboard_stats(self):
        """GET /api/dashboard/stats should work"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_documents_list(self):
        """GET /api/documents should work"""
        response = requests.get(f"{BASE_URL}/api/documents")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_workflows_list(self):
        """GET /api/workflows should work"""
        response = requests.get(f"{BASE_URL}/api/workflows")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_bc_companies(self):
        """GET /api/bc/companies should work"""
        response = requests.get(f"{BASE_URL}/api/bc/companies")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_auth_login(self):
        """POST /api/auth/login should work"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "token" in data, "Should return token"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
