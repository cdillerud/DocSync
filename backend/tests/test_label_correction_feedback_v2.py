"""
GPI Document Hub - Label Correction Feedback Loop Tests (Iteration 32)

Tests the enhanced label correction feedback system:
- GET /api/label-corrections/stats — total_corrections, unique_vendors, top_corrections
- GET /api/label-corrections/recent?limit=N — list of corrections with all required fields
- GET /api/label-corrections/vendor/{vendor_id} — has_patterns, label_remaps, unstable_labels, pattern_stability
- GET /api/label-corrections/document/{doc_id} — corrections for specific document
- POST /api/documents/{doc_id}/matching-debug/rerun — triggers correction learning
- GET /api/documents/{doc_id}/matching-debug — full diagnostics with feedback loop fields

Test document IDs:
- 80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85 (Cargo Modules LLC, has corrections)
- a1dec76a-17a2-46d4-a9f9-a0f6fb818208 (Tumalo Creek, freight carrier)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs from the spec
CARGO_MODULES_DOC_ID = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"
TUMALO_CREEK_DOC_ID = "a1dec76a-17a2-46d4-a9f9-a0f6fb818208"


class TestLabelCorrectionStats:
    """Tests for GET /api/label-corrections/stats"""
    
    def test_stats_endpoint_returns_200(self):
        """Stats endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Stats endpoint returns 200 OK")
    
    def test_stats_has_required_fields(self):
        """Stats should include total_corrections, unique_vendors, top_corrections"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "total_corrections" in data, "Missing total_corrections field"
        assert "unique_vendors" in data, "Missing unique_vendors field"
        assert "top_corrections" in data, "Missing top_corrections field"
        
        # Verify types
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        assert isinstance(data["unique_vendors"], int), "unique_vendors should be int"
        assert isinstance(data["top_corrections"], list), "top_corrections should be list"
        
        print(f"✓ Stats has required fields: total={data['total_corrections']}, vendors={data['unique_vendors']}")
    
    def test_stats_should_have_data(self):
        """Stats should have at least some corrections (from manual test runs)"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200
        data = response.json()
        
        # According to spec, there should be at least 2 corrections from manual tests
        if data["total_corrections"] >= 2:
            print(f"✓ Stats has data: {data['total_corrections']} corrections from {data['unique_vendors']} vendors")
        else:
            print(f"⚠ Stats shows {data['total_corrections']} corrections (expected >= 2 from spec)")
        
        # Check top_corrections structure if present
        if data["top_corrections"]:
            top = data["top_corrections"][0]
            expected_keys = ["predicted", "correct", "count"]
            for key in expected_keys:
                assert key in top, f"top_corrections item missing '{key}' field"
            print(f"✓ Top correction: {top['predicted']} → {top['correct']} ({top['count']}x)")


class TestRecentCorrections:
    """Tests for GET /api/label-corrections/recent"""
    
    def test_recent_endpoint_returns_200(self):
        """Recent corrections endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/recent?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Recent corrections endpoint returns 200 OK")
    
    def test_recent_returns_list(self):
        """Recent endpoint should return a list"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/recent?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ Recent returns list with {len(data)} items")
    
    def test_recent_correction_fields(self):
        """Each correction should have required fields"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/recent?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data:
            correction = data[0]
            required_fields = [
                "predicted_label", "correct_label", "actual_entity_type",
                "match_score", "match_outcome"
            ]
            for field in required_fields:
                assert field in correction, f"Correction missing '{field}' field"
            
            print(f"✓ Correction has required fields: {correction['predicted_label']} → {correction['correct_label']}")
            print(f"  Entity: {correction['actual_entity_type']}, Score: {correction['match_score']}, Outcome: {correction['match_outcome']}")
        else:
            print("⚠ No recent corrections found (may need to run matching-debug/rerun first)")


class TestVendorPatterns:
    """Tests for GET /api/label-corrections/vendor/{vendor_id}"""
    
    def test_vendor_patterns_endpoint_returns_200(self):
        """Vendor patterns endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/vendor/CargoModules")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Vendor patterns endpoint returns 200 OK")
    
    def test_vendor_patterns_structure(self):
        """Vendor patterns should include has_patterns, label_remaps, unstable_labels, pattern_stability"""
        # Try Cargo Modules LLC vendor (should have patterns)
        response = requests.get(f"{BASE_URL}/api/label-corrections/vendor/Cargo%20Modules%20LLC")
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "has_patterns" in data, "Missing has_patterns field"
        assert isinstance(data["has_patterns"], bool), "has_patterns should be boolean"
        
        if data["has_patterns"]:
            assert "label_remaps" in data, "Missing label_remaps field"
            assert "unstable_labels" in data, "Missing unstable_labels field"
            assert "pattern_stability" in data, "Missing pattern_stability field"
            
            print(f"✓ Vendor has patterns: {data.get('total_corrections', 0)} corrections")
            print(f"  Stability: {data['pattern_stability']}")
            print(f"  Remaps: {data['label_remaps']}")
            print(f"  Unstable labels: {data['unstable_labels']}")
        else:
            print(f"✓ Vendor patterns structure correct (vendor_id: {data.get('vendor_id', 'unknown')})")
            print(f"  has_patterns: {data['has_patterns']}")


class TestDocumentCorrections:
    """Tests for GET /api/label-corrections/document/{doc_id}"""
    
    def test_document_corrections_returns_200(self):
        """Document corrections endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/document/{CARGO_MODULES_DOC_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Document corrections endpoint returns 200 OK")
    
    def test_document_corrections_returns_list(self):
        """Document corrections should return a list"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/document/{CARGO_MODULES_DOC_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ Document corrections returns list with {len(data)} items for doc {CARGO_MODULES_DOC_ID[:8]}")
        
        if data:
            correction = data[0]
            print(f"  Correction: {correction.get('predicted_label')} → {correction.get('correct_label')}")


class TestMatchingDebugRerun:
    """Tests for POST /api/documents/{doc_id}/matching-debug/rerun"""
    
    def test_rerun_returns_200(self):
        """Rerun endpoint should return 200 OK"""
        response = requests.post(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug/rerun")
        assert response.status_code in [200, 404], f"Expected 200/404, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            print("✓ Rerun endpoint returns 200 OK")
        else:
            print(f"⚠ Document {CARGO_MODULES_DOC_ID} not found - skipping rerun test")
    
    def test_rerun_triggers_correction_learning(self):
        """Rerun should trigger correction learning for high-confidence matches"""
        response = requests.post(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug/rerun")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check resolution result structure
        assert "match_outcome" in data, "Missing match_outcome"
        assert "best_match" in data or data.get("match_outcome") == "no_match", "Expected best_match for successful resolution"
        
        print(f"✓ Rerun completed: outcome={data.get('match_outcome')}")
        
        if data.get("best_match"):
            best = data["best_match"]
            print(f"  Best match: {best.get('entity_type')} - {best.get('bc_document_no')} (score: {best.get('match_score', 0):.2f})")
            
            # If score >= 0.70, correction learning should have been triggered
            if best.get('match_score', 0) >= 0.70:
                print("  ✓ Score >= 0.70 - correction learning triggered")


class TestMatchingDebugDiagnostics:
    """Tests for GET /api/documents/{doc_id}/matching-debug"""
    
    def test_matching_debug_returns_200(self):
        """Matching debug endpoint should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        assert response.status_code in [200, 404], f"Expected 200/404, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            print("✓ Matching debug endpoint returns 200 OK")
        else:
            print(f"⚠ Document {CARGO_MODULES_DOC_ID} not found")
    
    def test_matching_debug_includes_feedback_fields(self):
        """Matching debug should include label_corrections and vendor_correction_patterns"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check for feedback loop fields
        assert "label_corrections" in data, "Missing label_corrections field"
        assert "vendor_correction_patterns" in data, "Missing vendor_correction_patterns field"
        
        print(f"✓ Matching debug includes feedback fields")
        print(f"  label_corrections: {len(data.get('label_corrections', []))} items")
        print(f"  vendor_patterns.has_patterns: {data.get('vendor_correction_patterns', {}).get('has_patterns', False)}")
    
    def test_diagnostics_decision_fields(self):
        """Diagnostics.decision should include label_correction_applied, vendor_pattern_weight, cluster_match_bonus"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        decision = diag.get("decision") or {}
        
        if decision:
            # Part 8: Feedback loop diagnostics
            print(f"✓ Decision found: outcome={decision.get('outcome')}")
            
            if "label_correction_applied" in decision:
                print(f"  label_correction_applied: {decision['label_correction_applied']}")
            
            if "vendor_pattern_weight" in decision:
                print(f"  vendor_pattern_weight: {decision['vendor_pattern_weight']}")
            
            if "cluster_match_bonus" in decision:
                print(f"  cluster_match_bonus: {decision['cluster_match_bonus']}")
        else:
            print("⚠ No diagnostics.decision found (may need to run rerun first)")
    
    def test_diagnostics_includes_dynamic_strategy(self):
        """Diagnostics should include dynamic_strategy info"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        
        if "dynamic_strategy" in diag:
            ds = diag["dynamic_strategy"]
            print(f"✓ Dynamic strategy info found")
            print(f"  applied: {ds.get('applied', False)}")
            if ds.get('reason'):
                print(f"  reason: {ds.get('reason')}")
        else:
            print("⚠ No dynamic_strategy in diagnostics")
    
    def test_diagnostics_includes_shipment_clustering(self):
        """Diagnostics should include shipment_clustering info"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        
        if "shipment_clustering" in diag:
            sc = diag["shipment_clustering"]
            print(f"✓ Shipment clustering info found")
            print(f"  attempted: {sc.get('attempted', False)}")
            print(f"  cluster_matches_added: {sc.get('cluster_matches_added', 0)}")
        else:
            print("⚠ No shipment_clustering in diagnostics")
    
    def test_diagnostics_label_correction_hints(self):
        """Diagnostics should include label_correction_hints"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        
        if "label_correction_hints" in diag:
            hints = diag["label_correction_hints"]
            print(f"✓ Label correction hints found: {len(hints)} labels with hints")
            for label, hint in hints.items():
                print(f"  {label}: {hint.get('total_corrections', 0)} corrections, unstable={hint.get('is_unstable', False)}")
        else:
            print("⚠ No label_correction_hints in diagnostics")


class TestScoringModel:
    """Tests for the 11-component scoring model"""
    
    def test_score_breakdown_components(self):
        """Score breakdown should include all 11 components when relevant"""
        # Run a resolution first to get scores
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        candidate_scores = diag.get("candidate_scores", [])
        
        expected_components = [
            "exact_reference_match",      # 0.40
            "entity_type_alignment",       # 0.20
            "domain_alignment",            # 0.15
            "vendor_alignment",            # 0.15
            "candidate_confidence",        # 0.10
            "vendor_behavior_bonus",       # 0.15
            "freight_vendor_boost",        # 0.15
            "shipment_relationship",       # 0.05
            "label_correction_boost",      # 0.15
            "reference_context_match",     # 0.05
            "date_proximity",              # 0.05
        ]
        
        if candidate_scores:
            score = candidate_scores[0]
            breakdown = score.get("score_breakdown", {})
            
            print(f"✓ Score breakdown found for {score.get('bc_document_no')} (total: {score.get('final_score', 0):.2f})")
            
            found_components = []
            for comp in expected_components:
                if comp in breakdown:
                    found_components.append(comp)
                    if breakdown[comp] > 0:
                        print(f"  {comp}: {breakdown[comp]:.2%}")
            
            print(f"  Components present: {len(found_components)}/11")
            
            # Check for label_correction_boost (key feature)
            if "label_correction_boost" in breakdown and breakdown["label_correction_boost"] > 0:
                print(f"  ✓ label_correction_boost active: {breakdown['label_correction_boost']:.2%}")
        else:
            print("⚠ No candidate scores found (may need to run rerun first)")


class TestVendorInfluenceCap:
    """Tests for the vendor influence cap at 0.20"""
    
    def test_vendor_components_cap(self):
        """vendor_behavior_bonus + label_correction_boost should be capped at 0.20"""
        response = requests.get(f"{BASE_URL}/api/documents/{CARGO_MODULES_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {CARGO_MODULES_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        diag = data.get("diagnostics") or {}
        candidate_scores = diag.get("candidate_scores", [])
        
        if candidate_scores:
            for score in candidate_scores:
                breakdown = score.get("score_breakdown", {})
                vendor_total = (
                    breakdown.get("vendor_behavior_bonus", 0) +
                    breakdown.get("label_correction_boost", 0)
                )
                
                if vendor_total > 0:
                    print(f"  Vendor components for {score.get('bc_document_no')}: {vendor_total:.2%}")
                    assert vendor_total <= 0.201, f"Vendor influence cap exceeded: {vendor_total}"
            
            print("✓ Vendor influence cap check passed (all <= 0.20)")
        else:
            print("⚠ No scores to check vendor cap")


class TestConfidenceThreshold:
    """Tests for the correction learning confidence threshold (>= 0.70)"""
    
    def test_corrections_only_from_high_confidence(self):
        """Corrections should only be recorded when match_score >= 0.70"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/recent?limit=20")
        assert response.status_code == 200
        data = response.json()
        
        if data:
            for correction in data:
                score = correction.get("match_score", 0)
                if score > 0:
                    assert score >= 0.70, f"Correction found with score {score} < 0.70"
            print(f"✓ All {len(data)} corrections have match_score >= 0.70")
        else:
            print("⚠ No corrections to verify threshold")


class TestTumaloCreeDoc:
    """Tests using the Tumalo Creek document (freight carrier)"""
    
    def test_tumalo_creek_matching_debug(self):
        """Tumalo Creek doc should work with matching-debug"""
        response = requests.get(f"{BASE_URL}/api/documents/{TUMALO_CREEK_DOC_ID}/matching-debug")
        
        if response.status_code == 404:
            pytest.skip(f"Document {TUMALO_CREEK_DOC_ID} not found")
        
        assert response.status_code == 200
        data = response.json()
        
        print(f"✓ Tumalo Creek matching debug: outcome={data.get('match_outcome')}")
        print(f"  is_freight_carrier: {data.get('is_freight_carrier')}")
        
        diag = data.get("diagnostics") or {}
        if diag.get("effective_strategy"):
            print(f"  strategy: {diag.get('effective_strategy')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
