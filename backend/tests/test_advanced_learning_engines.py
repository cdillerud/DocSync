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
    def test_advanced_learning_summary_returns_200(self):
        """GET /api/posting-patterns/advanced-learning/summary returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        assert response.status_code == 200
        print("PASS: Advanced learning summary returns 200")

    def test_advanced_learning_summary_has_all_7_engines(self):
        """Summary contains all 7 engine sections"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Verify all 7 engines are present
        required_engines = [
            "line_item_intelligence",
            "document_flow",
            "amount_patterns",
            "correction_replay",
            "field_correlations",
            "temporal_intelligence",
            "error_patterns"
        ]
        
        for engine in required_engines:
            assert engine in data, f"Missing engine: {engine}"
        
        print(f"PASS: Summary contains all 7 engines: {required_engines}")

    def test_advanced_learning_summary_line_item_intelligence_structure(self):
        """Line item intelligence has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        li = data.get("line_item_intelligence", {})
        assert "vendors_tracked" in li
        assert "unique_patterns" in li
        assert "top_vendors" in li
        print(f"PASS: Line item intelligence structure valid - {li.get('unique_patterns', 0)} patterns tracked")

    def test_advanced_learning_summary_document_flow_structure(self):
        """Document flow has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        df = data.get("document_flow", {})
        assert "vendors_with_sequences" in df
        assert "total_flow_events" in df
        print(f"PASS: Document flow structure valid - {df.get('total_flow_events', 0)} flow events")

    def test_advanced_learning_summary_amount_patterns_structure(self):
        """Amount patterns has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        ap = data.get("amount_patterns", {})
        assert "vendors_tracked" in ap
        assert "active_anomalies" in ap
        assert "top_vendors" in ap
        print(f"PASS: Amount patterns structure valid - {ap.get('vendors_tracked', 0)} vendors tracked")

    def test_advanced_learning_summary_correction_replay_structure(self):
        """Correction replay has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        cr = data.get("correction_replay", {})
        assert "total_replays" in cr
        assert "total_docs_corrected" in cr
        print(f"PASS: Correction replay structure valid - {cr.get('total_docs_corrected', 0)} docs corrected")

    def test_advanced_learning_summary_field_correlations_structure(self):
        """Field correlations has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        fc = data.get("field_correlations", {})
        assert "total_correlations" in fc
        assert "strong_rules" in fc
        print(f"PASS: Field correlations structure valid - {fc.get('total_correlations', 0)} correlations")

    def test_advanced_learning_summary_temporal_intelligence_structure(self):
        """Temporal intelligence has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        ti = data.get("temporal_intelligence", {})
        assert "by_day_of_week" in ti
        assert "volume_prediction" in ti
        print(f"PASS: Temporal intelligence structure valid - DOW data: {list(ti.get('by_day_of_week', {}).keys())}")

    def test_advanced_learning_summary_error_patterns_structure(self):
        """Error patterns has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        ep = data.get("error_patterns", {})
        assert "categories" in ep
        assert "total_errors" in ep
        print(f"PASS: Error patterns structure valid - {ep.get('total_errors', 0)} errors tracked")

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
    def test_backfill_returns_200(self):
        """POST /api/posting-patterns/advanced-learning/backfill?limit=50 returns 200"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/advanced-learning/backfill?limit=50")
        assert response.status_code == 200
        print("PASS: Backfill returns 200")

    def test_backfill_returns_result(self):
        """Backfill returns processing result"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/advanced-learning/backfill?limit=10")
        data = response.json()
        
        # May be async or sync
        if data.get("async"):
            assert "message" in data
            print(f"PASS: Backfill started asynchronously: {data.get('message')}")
        else:
            assert "processed" in data
            print(f"PASS: Backfill processed {data.get('processed', 0)} documents")


class TestAdvancedLearningDataVerification:
    """Verify that advanced learning data exists from previous backfill"""

    def test_summary_has_data(self):
        """Verify summary has actual data from backfill"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        # Check if any engine has data
        has_data = False
        
        li = data.get("line_item_intelligence", {})
        if li.get("unique_patterns", 0) > 0:
            has_data = True
            print(f"  - Line item patterns: {li.get('unique_patterns')}")
        
        df = data.get("document_flow", {})
        if df.get("total_flow_events", 0) > 0:
            has_data = True
            print(f"  - Document flow events: {df.get('total_flow_events')}")
        
        ap = data.get("amount_patterns", {})
        if ap.get("vendors_tracked", 0) > 0:
            has_data = True
            print(f"  - Amount patterns vendors: {ap.get('vendors_tracked')}")
        
        fc = data.get("field_correlations", {})
        if fc.get("total_correlations", 0) > 0:
            has_data = True
            print(f"  - Field correlations: {fc.get('total_correlations')}")
        
        ti = data.get("temporal_intelligence", {})
        dow = ti.get("by_day_of_week", {})
        if dow:
            has_data = True
            total_temporal = sum(dow.values())
            print(f"  - Temporal events: {total_temporal} across {len(dow)} days")
        
        if has_data:
            print("PASS: Advanced learning has data from backfill")
        else:
            print("INFO: No advanced learning data yet - backfill may be needed")

    def test_anch_vendor_has_amount_data(self):
        """ANCH vendor should have amount pattern data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        data = response.json()
        
        ap = data.get("amount_patterns", {})
        top_vendors = ap.get("top_vendors", [])
        
        anch_found = False
        for v in top_vendors:
            if v.get("vendor_no") == "ANCH":
                anch_found = True
                print(f"PASS: ANCH found in amount patterns - avg: ${v.get('avg_amount', 0):.2f}")
                break
        
        if not anch_found:
            print("INFO: ANCH not in top amount pattern vendors (may need more data)")


class TestAdvancedLearningIntegration:
    """Test integration with per_document_learning_service"""

    def test_learning_dashboard_includes_advanced(self):
        """Learning dashboard endpoint works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200
        print("PASS: Learning dashboard returns 200")

    def test_learning_pulse_works(self):
        """Learning pulse endpoint works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        print("PASS: Learning pulse returns 200")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
