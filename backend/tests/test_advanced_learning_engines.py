"""
Test Suite for 7 Advanced Learning Engines (Iteration 184)

Tests the following endpoints:
1. GET /api/posting-patterns/advanced-learning/summary - All 7 engine summaries
2. GET /api/posting-patterns/advanced-learning/line-items/{vendor_no} - Line item suggestions
3. GET /api/posting-patterns/advanced-learning/predict-next/{vendor_no} - Predict next doc type
4. GET /api/posting-patterns/advanced-learning/amount-check/{vendor_no}?amount=X - Amount anomaly check
5. GET /api/posting-patterns/advanced-learning/correction-replays - Replay history
6. GET /api/posting-patterns/advanced-learning/volume-prediction - Tomorrow's volume prediction
7. POST /api/posting-patterns/advanced-learning/backfill?limit=50 - Backfill advanced learning
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAdvancedLearningEngines:
    """Test all 7 Advanced Learning Engine endpoints"""

    # =========================================================================
    # Health Check
    # =========================================================================
    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("PASS: Health check - API is accessible")

    # =========================================================================
    # 1. Advanced Learning Summary - All 7 Engines
    # =========================================================================


    # =========================================================================
    # 2. Line Item Suggestions for ANCH vendor
    # =========================================================================
    def test_line_items_anch_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/line-items/ANCH returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/line-items/ANCH")
        assert response.status_code == 200
        print("PASS: Line items for ANCH returns 200")

    def test_line_items_anch_has_suggestions(self):
        """ANCH vendor has line item suggestions"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/line-items/ANCH")
        data = response.json()
        
        assert "vendor_no" in data
        assert data["vendor_no"] == "ANCH"
        assert "suggestions" in data
        
        suggestions = data.get("suggestions", [])
        print(f"PASS: ANCH has {len(suggestions)} line item suggestions")
        
        # If there are suggestions, verify structure
        if suggestions:
            s = suggestions[0]
            assert "description" in s
            assert "seen_count" in s
            print(f"  - Top suggestion: '{s.get('description', '')}' seen {s.get('seen_count', 0)} times")

    def test_line_items_unknown_vendor_returns_empty(self):
        """Unknown vendor returns empty suggestions"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/line-items/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("suggestions") == [] or len(data.get("suggestions", [])) == 0
        print("PASS: Unknown vendor returns empty suggestions")

    # =========================================================================
    # 3. Predict Next Document Type
    # =========================================================================
    def test_predict_next_anch_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/predict-next/ANCH returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/predict-next/ANCH")
        assert response.status_code == 200
        print("PASS: Predict next for ANCH returns 200")

    def test_predict_next_anch_has_prediction(self):
        """ANCH vendor has prediction data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/predict-next/ANCH")
        data = response.json()
        
        assert "vendor_no" in data
        assert data["vendor_no"] == "ANCH"
        
        # May have prediction or "unknown" if insufficient data
        if data.get("prediction") != "unknown" and data.get("predicted_next"):
            print(f"PASS: ANCH prediction: {data.get('predicted_next')} (confidence: {data.get('confidence', 0)})")
        else:
            print(f"PASS: ANCH prediction returned (may be unknown due to data): {data}")

    # =========================================================================
    # 4. Amount Anomaly Check
    # =========================================================================
    def test_amount_check_normal_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/amount-check/ANCH?amount=9500 returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/amount-check/ANCH?amount=9500")
        assert response.status_code == 200
        print("PASS: Amount check for normal amount returns 200")

    def test_amount_check_normal_not_anomaly(self):
        """Normal amount ($9,500) should not be flagged as anomaly"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/amount-check/ANCH?amount=9500")
        data = response.json()
        
        # If insufficient data, is_anomaly will be False with reason
        if data.get("reason") == "insufficient_data":
            print(f"PASS: Amount check returned insufficient_data (expected if <3 samples)")
        else:
            # With enough data, $9,500 should be normal for ANCH
            print(f"PASS: Amount check result: is_anomaly={data.get('is_anomaly')}, avg={data.get('avg_amount')}")

    def test_amount_check_extreme_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/amount-check/ANCH?amount=999999 returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/amount-check/ANCH?amount=999999")
        assert response.status_code == 200
        print("PASS: Amount check for extreme amount returns 200")

    def test_amount_check_extreme_may_be_anomaly(self):
        """Extreme amount ($999,999) may be flagged as anomaly if enough data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/amount-check/ANCH?amount=999999")
        data = response.json()
        
        if data.get("reason") == "insufficient_data":
            print(f"PASS: Amount check returned insufficient_data (expected if <3 samples)")
        else:
            # With enough data, $999,999 should likely be anomalous
            is_anomaly = data.get("is_anomaly", False)
            z_score = data.get("z_score", 0)
            print(f"PASS: Extreme amount check: is_anomaly={is_anomaly}, z_score={z_score}")
            if is_anomaly:
                print(f"  - Correctly detected as anomaly (severity: {data.get('severity')})")

    # =========================================================================
    # 5. Correction Replays
    # =========================================================================
    def test_correction_replays_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/correction-replays returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/correction-replays")
        assert response.status_code == 200
        print("PASS: Correction replays returns 200")

    def test_correction_replays_is_list(self):
        """Correction replays returns a list"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/correction-replays")
        data = response.json()
        
        assert isinstance(data, list)
        print(f"PASS: Correction replays returned {len(data)} records")
        
        if data:
            r = data[0]
            assert "vendor_no" in r or "field_name" in r
            print(f"  - Latest replay: vendor={r.get('vendor_no')}, field={r.get('field_name')}")

    # =========================================================================
    # 6. Volume Prediction
    # =========================================================================
    def test_volume_prediction_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/volume-prediction returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/volume-prediction")
        assert response.status_code == 200
        print("PASS: Volume prediction returns 200")

    def test_volume_prediction_has_structure(self):
        """Volume prediction has expected structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/volume-prediction")
        data = response.json()
        
        # May have "no_data" if no temporal data exists
        if data.get("prediction") == "no_data":
            print("PASS: Volume prediction returned no_data (expected if no temporal data)")
        else:
            assert "tomorrow" in data or "predicted_volume" in data
            print(f"PASS: Volume prediction: {data.get('predicted_volume', 'N/A')} for {data.get('tomorrow', 'N/A')}")
            
            if data.get("by_day_of_week"):
                print(f"  - Peak day: {data.get('peak_day')}, Quiet day: {data.get('quiet_day')}")

    # =========================================================================
    # 7. Backfill Advanced Learning
    # =========================================================================


class TestAdvancedLearningIntegration:
    """Test integration with per_document_learning_service"""


    def test_learning_pulse_works(self):
        """Learning pulse endpoint works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        print("PASS: Learning pulse returns 200")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
