"""
Test Vendor Intelligence + Deep Learning Integration (Iteration 185)

Tests:
1. GET /api/posting-patterns/advanced-learning/summary - all 7 engines return data
2. GET /api/posting-patterns/advanced-learning/volume-prediction - returns prediction
3. GET /api/posting-patterns/deep-learning/vendor-maturity/ANCH - returns maturity score
4. GET /api/posting-patterns/learning-pulse/vendor/ANCH - returns vendor learning profile
5. GET /api/vendor-intelligence/profiles - returns profiles with vendor_no for maturity lookup
6. GET /api/vendor-intelligence/stats - returns stats
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAdvancedLearningSummary:
    """Test GET /api/posting-patterns/advanced-learning/summary"""
    
    def test_summary_returns_all_7_engines(self):
        """Summary endpoint returns data for all 7 advanced learning engines"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify all 7 engines are present
        assert "line_item_intelligence" in data, "Missing line_item_intelligence"
        assert "document_flow" in data, "Missing document_flow"
        assert "amount_patterns" in data, "Missing amount_patterns"
        assert "correction_replay" in data, "Missing correction_replay"
        assert "field_correlations" in data, "Missing field_correlations"
        assert "temporal_intelligence" in data, "Missing temporal_intelligence"
        assert "error_patterns" in data, "Missing error_patterns"
        
        # Verify structure of each engine
        assert "vendors_tracked" in data["line_item_intelligence"]
        assert "vendors_with_sequences" in data["document_flow"]
        assert "vendors_tracked" in data["amount_patterns"]
        assert "total_replays" in data["correction_replay"]
        assert "total_correlations" in data["field_correlations"]
        assert "by_day_of_week" in data["temporal_intelligence"]
        assert "categories" in data["error_patterns"]
        
        print(f"All 7 engines present with data")


class TestVolumePrediction:
    """Test GET /api/posting-patterns/advanced-learning/volume-prediction"""
    
    def test_volume_prediction_returns_data(self):
        """Volume prediction endpoint returns prediction data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/volume-prediction")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify prediction fields
        assert "tomorrow" in data, "Missing tomorrow field"
        assert "predicted_volume" in data, "Missing predicted_volume field"
        assert "peak_day" in data, "Missing peak_day field"
        assert "quiet_day" in data, "Missing quiet_day field"
        assert "by_day_of_week" in data, "Missing by_day_of_week field"
        
        # Verify predicted_volume is a number
        assert isinstance(data["predicted_volume"], (int, float)), "predicted_volume should be numeric"
        
        print(f"Volume prediction: {data['predicted_volume']} for {data['tomorrow']}")


class TestVendorMaturity:
    """Test GET /api/posting-patterns/deep-learning/vendor-maturity/ANCH"""
    
    def test_anch_maturity_returns_score(self):
        """ANCH vendor maturity endpoint returns maturity score"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/vendor-maturity/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify maturity fields
        assert "vendor_no" in data, "Missing vendor_no"
        assert data["vendor_no"] == "ANCH", f"Expected vendor_no ANCH, got {data['vendor_no']}"
        assert "maturity_level" in data, "Missing maturity_level"
        assert "composite_score" in data, "Missing composite_score"
        
        # ANCH should have a developing maturity level with score ~58
        assert data["composite_score"] > 0, "composite_score should be > 0"
        assert data["maturity_level"] in ["novice", "learning", "developing", "proficient", "mastered"], \
            f"Invalid maturity_level: {data['maturity_level']}"
        
        # Verify dimensions if present
        if "dimensions" in data and data["dimensions"]:
            expected_dims = ["volume", "accuracy", "consistency", "recency", "field_coverage", "error_rate"]
            for dim in expected_dims:
                assert dim in data["dimensions"], f"Missing dimension: {dim}"
        
        print(f"ANCH maturity: {data['composite_score']} ({data['maturity_level']})")
    
    def test_unknown_vendor_returns_zero_score(self):
        """Unknown vendor returns zero maturity score"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/vendor-maturity/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["composite_score"] == 0, "Unknown vendor should have 0 score"
        assert data["maturity_level"] == "unknown", "Unknown vendor should have 'unknown' level"


class TestLearningPulse:
    """Test GET /api/posting-patterns/learning-pulse/vendor/ANCH"""
    
    def test_anch_learning_pulse_returns_profile(self):
        """ANCH vendor learning pulse returns learning profile"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/vendor/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify vendor_no
        assert "vendor_no" in data, "Missing vendor_no"
        assert data["vendor_no"] == "ANCH", f"Expected vendor_no ANCH, got {data['vendor_no']}"
        
        # Verify intelligence data if present
        if "intelligence" in data and data["intelligence"]:
            intel = data["intelligence"]
            assert "total_documents" in intel, "Missing total_documents in intelligence"
            assert "vendor_no" in intel, "Missing vendor_no in intelligence"
            
            print(f"ANCH learning pulse: {intel.get('total_documents', 0)} documents")
        else:
            print("ANCH learning pulse: No intelligence data yet")
    
    def test_unknown_vendor_returns_no_data_message(self):
        """Unknown vendor returns no data message"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/vendor/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Should return vendor_no and a message or empty intelligence
        assert "vendor_no" in data, "Missing vendor_no"


class TestVendorIntelligenceProfiles:
    """Test GET /api/vendor-intelligence/profiles"""
    
    def test_profiles_returns_list(self):
        """Profiles endpoint returns list of vendor profiles"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/profiles?skip=0&limit=20")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify structure
        assert "profiles" in data, "Missing profiles"
        assert "total" in data, "Missing total"
        assert isinstance(data["profiles"], list), "profiles should be a list"
        assert isinstance(data["total"], int), "total should be an integer"
        
        # Verify profile structure if profiles exist
        if data["profiles"]:
            profile = data["profiles"][0]
            assert "vendor_name" in profile, "Missing vendor_name in profile"
            assert "invoice_count" in profile, "Missing invoice_count in profile"
            
            print(f"Found {data['total']} vendor profiles")
        else:
            print("No vendor profiles found")


class TestVendorIntelligenceStats:
    """Test GET /api/vendor-intelligence/stats"""
    
    def test_stats_returns_data(self):
        """Stats endpoint returns vendor intelligence statistics"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify stats fields
        assert "total_vendors" in data, "Missing total_vendors"
        assert "stable_vendors" in data, "Missing stable_vendors"
        assert "avg_automation_rate" in data, "Missing avg_automation_rate"
        assert "avg_resolution_rate" in data, "Missing avg_resolution_rate"
        
        # Verify types
        assert isinstance(data["total_vendors"], int), "total_vendors should be int"
        assert isinstance(data["stable_vendors"], int), "stable_vendors should be int"
        
        print(f"Stats: {data['total_vendors']} vendors, {data['stable_vendors']} stable")


class TestDeepLearningSummary:
    """Test GET /api/posting-patterns/deep-learning/summary"""
    
    def test_deep_learning_summary_returns_data(self):
        """Deep learning summary endpoint returns all 5 engine summaries"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify all 5 deep learning engines are present
        assert "extraction_patterns" in data, "Missing extraction_patterns"
        assert "document_similarity" in data, "Missing document_similarity"
        assert "self_correction" in data, "Missing self_correction"
        assert "vendor_maturity" in data, "Missing vendor_maturity"
        assert "predictive_readiness" in data, "Missing predictive_readiness"
        
        print(f"Deep learning summary: all 5 engines present")


class TestExtractionPatterns:
    """Test GET /api/posting-patterns/deep-learning/extraction-patterns/ANCH"""
    
    def test_anch_extraction_patterns(self):
        """ANCH extraction patterns endpoint returns pattern data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/extraction-patterns/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Should return pattern data or empty object
        if data and "vendor_no" in data:
            assert data["vendor_no"] == "ANCH"
            print(f"ANCH extraction patterns: {data.get('total_documents', 0)} documents")
        else:
            print("ANCH extraction patterns: No data yet")


class TestLineItemIntelligence:
    """Test GET /api/posting-patterns/advanced-learning/line-items/ANCH"""
    
    def test_anch_line_items(self):
        """ANCH line items endpoint returns suggestions"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/line-items/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Response can be a list or an object with suggestions
        if isinstance(data, list):
            suggestions = data
        elif isinstance(data, dict) and "suggestions" in data:
            suggestions = data["suggestions"]
        else:
            suggestions = []
        
        if suggestions:
            suggestion = suggestions[0]
            assert "description" in suggestion, "Missing description in suggestion"
            assert "seen_count" in suggestion, "Missing seen_count in suggestion"
            print(f"ANCH line items: {len(suggestions)} suggestions")
        else:
            print("ANCH line items: No suggestions yet")


class TestAmountCheck:
    """Test GET /api/posting-patterns/advanced-learning/amount-check/ANCH"""
    
    def test_anch_amount_check_normal(self):
        """ANCH amount check for normal amount"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/amount-check/ANCH?amount=9500")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Should return anomaly check result
        if "is_anomaly" in data:
            print(f"ANCH amount check (9500): is_anomaly={data['is_anomaly']}")
        elif "reason" in data:
            print(f"ANCH amount check: {data['reason']}")


class TestPredictNext:
    """Test GET /api/posting-patterns/advanced-learning/predict-next/ANCH"""
    
    def test_anch_predict_next(self):
        """ANCH predict next document type"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/predict-next/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Should return prediction
        assert "vendor_no" in data, "Missing vendor_no"
        
        if "predicted_next" in data:
            print(f"ANCH predict next: {data['predicted_next']} ({data.get('confidence', 0)*100:.0f}% confidence)")
        else:
            print(f"ANCH predict next: {data.get('prediction', 'unknown')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
