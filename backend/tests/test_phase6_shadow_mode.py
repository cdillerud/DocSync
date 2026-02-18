"""
Phase 6: Shadow Mode + Data Validation Tests

Tests for:
1. GET /api/metrics/match-score-distribution - histogram buckets
2. GET /api/metrics/alias-exceptions - vendor-level metrics and daily trend
3. GET /api/metrics/vendor-stability - categorized vendors
4. GET /api/settings/shadow-mode - feature flags, readiness assessment
5. POST /api/settings/shadow-mode - update shadow mode settings
6. GET /api/reports/shadow-mode-performance - comprehensive report with readiness_score
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestMatchScoreDistribution:
    """Tests for GET /api/metrics/match-score-distribution"""
    
    def test_match_score_distribution_returns_200(self):
        """Verify endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        assert response.status_code == 200
    
    def test_match_score_distribution_has_buckets(self):
        """Verify response contains all 4 histogram buckets"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        data = response.json()
        
        assert "buckets" in data
        buckets = data["buckets"]
        
        # Verify all 4 buckets exist
        assert "0.95_1.00" in buckets, "Missing bucket 0.95-1.00"
        assert "0.92_0.95" in buckets, "Missing bucket 0.92-0.95"
        assert "0.88_0.92" in buckets, "Missing bucket 0.88-0.92"
        assert "lt_0.88" in buckets, "Missing bucket <0.88"
    
    def test_match_score_distribution_bucket_structure(self):
        """Verify each bucket has count, by_method, linked, needs_review"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        data = response.json()
        
        for bucket_key, bucket_data in data["buckets"].items():
            assert "count" in bucket_data, f"Bucket {bucket_key} missing 'count'"
            assert "by_method" in bucket_data, f"Bucket {bucket_key} missing 'by_method'"
            assert "linked" in bucket_data, f"Bucket {bucket_key} missing 'linked'"
            assert "needs_review" in bucket_data, f"Bucket {bucket_key} missing 'needs_review'"
    
    def test_match_score_distribution_has_summary(self):
        """Verify response contains summary with high_confidence_pct and interpretation"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        data = response.json()
        
        assert "summary" in data
        summary = data["summary"]
        
        assert "high_confidence_eligible" in summary
        assert "high_confidence_pct" in summary
        assert "interpretation" in summary
        assert "near_threshold" in summary
        assert "below_threshold" in summary
    
    def test_match_score_distribution_has_threshold_analysis(self):
        """Verify response contains threshold_analysis"""
        response = requests.get(f"{BASE_URL}/api/metrics/match-score-distribution")
        data = response.json()
        
        assert "threshold_analysis" in data
        analysis = data["threshold_analysis"]
        
        assert "current_threshold" in analysis
        assert analysis["current_threshold"] == 0.92
        assert "above_threshold_count" in analysis
        assert "above_threshold_pct" in analysis
    
    def test_match_score_distribution_with_date_params(self):
        """Verify endpoint accepts from_date and to_date parameters"""
        response = requests.get(
            f"{BASE_URL}/api/metrics/match-score-distribution",
            params={"from_date": "2026-01-01", "to_date": "2026-02-18"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "period" in data
        assert data["period"]["from_date"] == "2026-01-01"
        assert data["period"]["to_date"] == "2026-02-18"


class TestAliasExceptions:
    """Tests for GET /api/metrics/alias-exceptions"""
    
    def test_alias_exceptions_returns_200(self):
        """Verify endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        assert response.status_code == 200
    
    def test_alias_exceptions_has_alias_totals(self):
        """Verify response contains alias_totals with required fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        data = response.json()
        
        assert "alias_totals" in data
        totals = data["alias_totals"]
        
        assert "alias_matches_total" in totals
        assert "alias_matches_success" in totals
        assert "alias_matches_needs_review" in totals
        assert "alias_exception_rate" in totals
    
    def test_alias_exceptions_has_daily_trend(self):
        """Verify response contains daily_trend array"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        data = response.json()
        
        assert "daily_trend" in data
        assert isinstance(data["daily_trend"], list)
        
        # Should have 7 days of data
        assert len(data["daily_trend"]) == 7
        
        # Each day should have required fields
        for day in data["daily_trend"]:
            assert "date" in day
            assert "total" in day
            assert "success" in day
            assert "exceptions" in day
            assert "exception_rate" in day
    
    def test_alias_exceptions_has_top_exception_vendors(self):
        """Verify response contains top_exception_vendors array"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        data = response.json()
        
        assert "top_exception_vendors" in data
        assert isinstance(data["top_exception_vendors"], list)
    
    def test_alias_exceptions_has_high_alias_contribution_vendors(self):
        """Verify response contains high_alias_contribution_vendors array"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        data = response.json()
        
        assert "high_alias_contribution_vendors" in data
        assert isinstance(data["high_alias_contribution_vendors"], list)
    
    def test_alias_exceptions_has_interpretation(self):
        """Verify response contains interpretation with status and message"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-exceptions")
        data = response.json()
        
        assert "interpretation" in data
        interp = data["interpretation"]
        
        assert "status" in interp
        assert interp["status"] in ["healthy", "watch", "attention"]
        assert "message" in interp
    
    def test_alias_exceptions_with_days_param(self):
        """Verify endpoint accepts days parameter"""
        response = requests.get(
            f"{BASE_URL}/api/metrics/alias-exceptions",
            params={"days": 30}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["period_days"] == 30


class TestVendorStability:
    """Tests for GET /api/metrics/vendor-stability"""
    
    def test_vendor_stability_returns_200(self):
        """Verify endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        assert response.status_code == 200
    
    def test_vendor_stability_has_categories(self):
        """Verify response contains all 3 vendor categories"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        data = response.json()
        
        assert "categories" in data
        categories = data["categories"]
        
        # Verify all 3 categories exist
        assert "low_automation" in categories
        assert "high_score_high_exception" in categories
        assert "consistently_high_confidence" in categories
    
    def test_vendor_stability_category_structure(self):
        """Verify each category has description, count, and vendors array"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        data = response.json()
        
        for cat_key, cat_data in data["categories"].items():
            assert "description" in cat_data, f"Category {cat_key} missing 'description'"
            assert "count" in cat_data, f"Category {cat_key} missing 'count'"
            assert "vendors" in cat_data, f"Category {cat_key} missing 'vendors'"
            assert isinstance(cat_data["vendors"], list)
    
    def test_vendor_stability_has_threshold_override_candidates(self):
        """Verify response contains threshold_override_candidates"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        data = response.json()
        
        assert "threshold_override_candidates" in data
        assert isinstance(data["threshold_override_candidates"], list)
    
    def test_vendor_stability_has_total_vendors_analyzed(self):
        """Verify response contains total_vendors_analyzed"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendor-stability")
        data = response.json()
        
        assert "total_vendors_analyzed" in data
        assert isinstance(data["total_vendors_analyzed"], int)
    
    def test_vendor_stability_with_days_param(self):
        """Verify endpoint accepts days parameter"""
        response = requests.get(
            f"{BASE_URL}/api/metrics/vendor-stability",
            params={"days": 30}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["period_days"] == 30


class TestShadowModeSettings:
    """Tests for GET/POST /api/settings/shadow-mode"""
    
    def test_shadow_mode_get_returns_200(self):
        """Verify GET endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        assert response.status_code == 200
    
    def test_shadow_mode_has_feature_flags(self):
        """Verify response contains feature_flags with CREATE_DRAFT_HEADER and DEMO_MODE"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "feature_flags" in data
        flags = data["feature_flags"]
        
        assert "CREATE_DRAFT_HEADER" in flags
        assert "DEMO_MODE" in flags
        assert isinstance(flags["CREATE_DRAFT_HEADER"], bool)
        assert isinstance(flags["DEMO_MODE"], bool)
    
    def test_shadow_mode_has_shadow_mode_status(self):
        """Verify response contains shadow_mode status object"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "shadow_mode" in data
        sm = data["shadow_mode"]
        
        assert "started_at" in sm
        assert "days_running" in sm
        assert "notes" in sm
        assert "is_active" in sm
    
    def test_shadow_mode_has_health_indicators_7d(self):
        """Verify response contains health_indicators_7d"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "health_indicators_7d" in data
        health = data["health_indicators_7d"]
        
        assert "high_confidence_docs_pct" in health
        assert "alias_exception_rate" in health
        assert "total_docs_processed" in health
    
    def test_shadow_mode_has_readiness_assessment(self):
        """Verify response contains readiness_assessment"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "readiness_assessment" in data
        readiness = data["readiness_assessment"]
        
        assert "high_confidence_ok" in readiness
        assert "alias_exception_ok" in readiness
        assert "sufficient_data" in readiness
        assert "recommended_action" in readiness
    
    def test_shadow_mode_has_draft_creation_thresholds(self):
        """Verify response contains draft_creation_thresholds"""
        response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        data = response.json()
        
        assert "draft_creation_thresholds" in data
        thresholds = data["draft_creation_thresholds"]
        
        assert "eligible_match_methods" in thresholds
        assert "min_match_score_for_draft" in thresholds
        assert "min_confidence_for_draft" in thresholds
    
    def test_shadow_mode_post_updates_settings(self):
        """Verify POST endpoint updates shadow_mode_started_at and notes"""
        # First, set shadow mode
        test_date = "2026-02-15T10:00:00Z"
        test_notes = "Test shadow mode update via pytest"
        
        response = requests.post(
            f"{BASE_URL}/api/settings/shadow-mode",
            json={
                "shadow_mode_started_at": test_date,
                "shadow_mode_notes": test_notes
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify the update was applied
        assert data["shadow_mode"]["started_at"] == test_date
        assert data["shadow_mode"]["notes"] == test_notes
        assert data["shadow_mode"]["days_running"] >= 0
        
        # Verify GET returns the same data
        get_response = requests.get(f"{BASE_URL}/api/settings/shadow-mode")
        get_data = get_response.json()
        
        assert get_data["shadow_mode"]["started_at"] == test_date
        assert get_data["shadow_mode"]["notes"] == test_notes


class TestShadowModePerformanceReport:
    """Tests for GET /api/reports/shadow-mode-performance"""
    
    def test_shadow_mode_report_returns_200(self):
        """Verify endpoint returns 200 status"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        assert response.status_code == 200
    
    def test_shadow_mode_report_has_executive_summary(self):
        """Verify response contains executive_summary with readiness_score"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "executive_summary" in data
        summary = data["executive_summary"]
        
        assert "readiness_score" in summary
        assert "readiness_max" in summary
        assert summary["readiness_max"] == 100
        assert "recommendation" in summary
        assert "recommendation_detail" in summary
        assert "shadow_mode_days" in summary
        assert "total_documents_processed" in summary
        assert "automation_rate" in summary
        assert "high_confidence_pct" in summary
    
    def test_shadow_mode_report_has_readiness_factors(self):
        """Verify response contains readiness_factors array with 4 factors"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "readiness_factors" in data
        factors = data["readiness_factors"]
        
        assert len(factors) == 4
        
        # Verify each factor has required fields
        for factor in factors:
            assert "factor" in factor
            assert "value" in factor
            assert "target" in factor
            assert "score" in factor
            assert "max_score" in factor
        
        # Verify factor names
        factor_names = [f["factor"] for f in factors]
        assert "High Confidence Documents" in factor_names
        assert "Alias Exception Rate" in factor_names
        assert "Overall Automation Rate" in factor_names
        assert "Data Volume" in factor_names
    
    def test_shadow_mode_report_has_match_score_analysis(self):
        """Verify response contains match_score_analysis"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "match_score_analysis" in data
        analysis = data["match_score_analysis"]
        
        assert "buckets" in analysis
        assert "summary" in analysis
        assert "threshold_analysis" in analysis
    
    def test_shadow_mode_report_has_alias_engine_performance(self):
        """Verify response contains alias_engine_performance"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "alias_engine_performance" in data
        alias = data["alias_engine_performance"]
        
        assert "totals" in alias
        assert "interpretation" in alias
        assert "daily_trend" in alias
        assert "top_exception_vendors" in alias
        assert "high_contribution_vendors" in alias
    
    def test_shadow_mode_report_has_vendor_friction_analysis(self):
        """Verify response contains vendor_friction_analysis"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "vendor_friction_analysis" in data
        friction = data["vendor_friction_analysis"]
        
        assert "total_vendors" in friction
        assert "low_automation_count" in friction
        assert "process_issue_count" in friction
        assert "threshold_override_candidates" in friction
    
    def test_shadow_mode_report_has_feature_flags(self):
        """Verify response contains feature_flags"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "feature_flags" in data
        assert "CREATE_DRAFT_HEADER" in data["feature_flags"]
        assert "DEMO_MODE" in data["feature_flags"]
    
    def test_shadow_mode_report_has_next_steps(self):
        """Verify response contains next_steps array"""
        response = requests.get(f"{BASE_URL}/api/reports/shadow-mode-performance")
        data = response.json()
        
        assert "next_steps" in data
        assert isinstance(data["next_steps"], list)
        assert len(data["next_steps"]) > 0
    
    def test_shadow_mode_report_with_days_param(self):
        """Verify endpoint accepts days parameter"""
        response = requests.get(
            f"{BASE_URL}/api/reports/shadow-mode-performance",
            params={"days": 30}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["report_period_days"] == 30


class TestExistingEndpointsStillWork:
    """Verify existing ROI dashboard endpoints still work after Phase 6 changes"""
    
    def test_automation_metrics_still_works(self):
        """Verify /api/metrics/automation still returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/automation")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_documents" in data
        assert "automation_rate" in data
        assert "review_rate" in data
        assert "status_distribution" in data
    
    def test_vendor_metrics_still_works(self):
        """Verify /api/metrics/vendors still returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/vendors")
        assert response.status_code == 200
        data = response.json()
        
        assert "vendors" in data
    
    def test_alias_impact_still_works(self):
        """Verify /api/metrics/alias-impact still returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/alias-impact")
        assert response.status_code == 200
        data = response.json()
        
        assert "total_aliases" in data
        assert "alias_contribution" in data
    
    def test_daily_metrics_still_works(self):
        """Verify /api/metrics/daily still returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/metrics/daily")
        assert response.status_code == 200
        data = response.json()
        
        assert "daily_metrics" in data
    
    def test_settings_status_still_works(self):
        """Verify /api/settings/status still returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        data = response.json()
        
        assert "demo_mode" in data
        assert "connections" in data
        assert "features" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
