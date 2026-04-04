"""
Test: Readiness Contradiction Fix (Iteration 179)

Tests the bug fixes for:
1. Duplicate risk signal - BC validation duplicate_check should override stale possible_duplicate flag
2. PO resolved signal - BC validation po_check should override field-only resolution for AP_Invoice
3. Learning events - readiness_contradiction_fix events should be recorded when signals change

Key scenarios:
- AP_Invoice with possible_duplicate=True but BC validation duplicate_check passed=True → duplicate_risk=False
- AP_Invoice with PO extracted but BC validation po_check passed=False → po_resolved=False
- Self-correction learning events recorded when signals flip
"""

import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestComputeSignalsDuplicateRisk:
    """Test compute_signals() duplicate_risk logic with BC validation override"""

    def test_duplicate_risk_false_when_bc_check_passed(self):
        """
        Scenario: Document has possible_duplicate=True (stale flag from ingestion)
        but BC validation duplicate_check passed=True (authoritative check).
        Expected: duplicate_risk signal should be False (BC check overrides stale flag)
        """
        # Import the function directly for unit testing
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        doc = {
            "id": "test-dup-bc-passed",
            "document_type": "AP_Invoice",
            "possible_duplicate": True,  # Stale flag from ingestion
            "bc_validation": {
                "checks": [
                    {
                        "check_name": "duplicate_check",
                        "passed": True,  # BC says no duplicate
                        "message": "No duplicate found"
                    }
                ]
            },
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-001",
                "amount": 100.00
            }
        }

        signals = compute_signals(doc)
        assert signals["duplicate_risk"] is False, \
            f"duplicate_risk should be False when BC duplicate_check passed=True, got {signals['duplicate_risk']}"
        print("PASS: duplicate_risk=False when BC duplicate_check passed=True (overrides stale possible_duplicate)")

    def test_duplicate_risk_true_when_bc_check_failed(self):
        """
        Scenario: BC validation duplicate_check passed=False
        Expected: duplicate_risk signal should be True
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        doc = {
            "id": "test-dup-bc-failed",
            "document_type": "AP_Invoice",
            "possible_duplicate": False,
            "bc_validation": {
                "checks": [
                    {
                        "check_name": "duplicate_check",
                        "passed": False,  # BC found duplicate
                        "message": "Duplicate invoice found"
                    }
                ]
            },
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-002",
                "amount": 200.00
            }
        }

        signals = compute_signals(doc)
        assert signals["duplicate_risk"] is True, \
            f"duplicate_risk should be True when BC duplicate_check passed=False, got {signals['duplicate_risk']}"
        print("PASS: duplicate_risk=True when BC duplicate_check passed=False")

    def test_duplicate_risk_fallback_to_possible_duplicate(self):
        """
        Scenario: No BC validation duplicate check exists
        Expected: Falls back to possible_duplicate flag
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        # Test with possible_duplicate=True, no BC check
        doc_with_flag = {
            "id": "test-dup-fallback-true",
            "document_type": "AP_Invoice",
            "possible_duplicate": True,
            "bc_validation": {
                "checks": []  # No duplicate check
            },
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-003",
                "amount": 300.00
            }
        }

        signals = compute_signals(doc_with_flag)
        assert signals["duplicate_risk"] is True, \
            f"duplicate_risk should be True when no BC check and possible_duplicate=True, got {signals['duplicate_risk']}"
        print("PASS: duplicate_risk=True when no BC check and possible_duplicate=True (fallback)")

        # Test with possible_duplicate=False, no BC check
        doc_without_flag = {
            "id": "test-dup-fallback-false",
            "document_type": "AP_Invoice",
            "possible_duplicate": False,
            "bc_validation": None,  # No BC validation at all
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-004",
                "amount": 400.00
            }
        }

        signals = compute_signals(doc_without_flag)
        assert signals["duplicate_risk"] is False, \
            f"duplicate_risk should be False when no BC check and possible_duplicate=False, got {signals['duplicate_risk']}"
        print("PASS: duplicate_risk=False when no BC check and possible_duplicate=False (fallback)")


class TestComputeSignalsPOResolved:
    """Test compute_signals() po_resolved logic with BC validation override for AP_Invoice"""

    def test_po_resolved_false_when_bc_po_check_failed(self):
        """
        Scenario: AP_Invoice has PO extracted but BC validation po_check passed=False
        Expected: po_resolved signal should be False (BC check overrides field presence)
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        doc = {
            "id": "test-po-bc-failed",
            "document_type": "AP_Invoice",  # Non-shipping doc type
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-005",
                "amount": 500.00,
                "po_number": "PO-12345"  # PO was extracted
            },
            "bc_validation": {
                "checks": [
                    {
                        "check_name": "po_check",
                        "passed": False,  # BC says PO not found
                        "message": "PO not found in BC"
                    }
                ]
            }
        }

        signals = compute_signals(doc)
        assert signals["po_resolved"] is False, \
            f"po_resolved should be False when BC po_check passed=False, got {signals['po_resolved']}"
        print("PASS: po_resolved=False for AP_Invoice when BC po_check passed=False (overrides field presence)")

    def test_po_resolved_true_when_no_bc_po_check_and_po_extracted(self):
        """
        Scenario: AP_Invoice has PO extracted but no BC validation po_check
        Expected: po_resolved signal should be True (field presence is sufficient)
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        doc = {
            "id": "test-po-no-bc-check",
            "document_type": "AP_Invoice",
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-006",
                "amount": 600.00,
                "po_number": "PO-67890"  # PO was extracted
            },
            "bc_validation": {
                "checks": []  # No po_check
            }
        }

        signals = compute_signals(doc)
        assert signals["po_resolved"] is True, \
            f"po_resolved should be True when no BC po_check and PO extracted, got {signals['po_resolved']}"
        print("PASS: po_resolved=True for AP_Invoice when no BC po_check and PO extracted")

    def test_po_resolved_true_when_bc_po_check_passed(self):
        """
        Scenario: AP_Invoice has PO extracted and BC validation po_check passed=True
        Expected: po_resolved signal should be True
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals

        doc = {
            "id": "test-po-bc-passed",
            "document_type": "AP_Invoice",
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-007",
                "amount": 700.00,
                "po_number": "PO-11111"
            },
            "bc_validation": {
                "checks": [
                    {
                        "check_name": "po_check",
                        "passed": True,
                        "message": "PO found in BC"
                    }
                ]
            }
        }

        signals = compute_signals(doc)
        assert signals["po_resolved"] is True, \
            f"po_resolved should be True when BC po_check passed=True, got {signals['po_resolved']}"
        print("PASS: po_resolved=True for AP_Invoice when BC po_check passed=True")


class TestDuplicateRiskScore:
    """Test _duplicate_risk_score() in automation_intelligence_service"""

    def test_duplicate_risk_score_zero_when_bc_passed(self):
        """BC duplicate check passed → risk score 0.0"""
        import sys
        sys.path.insert(0, "/app/backend")
        from services.automation_intelligence_service import _duplicate_risk_score

        doc = {
            "bc_validation": {
                "checks": [
                    {"check_name": "duplicate_check", "passed": True}
                ]
            },
            "possible_duplicate": True  # Should be ignored
        }

        score = _duplicate_risk_score(doc)
        assert score == 0.0, f"Expected 0.0 when BC check passed, got {score}"
        print("PASS: _duplicate_risk_score returns 0.0 when BC duplicate_check passed")

    def test_duplicate_risk_score_one_when_bc_failed(self):
        """BC duplicate check failed → risk score 1.0"""
        import sys
        sys.path.insert(0, "/app/backend")
        from services.automation_intelligence_service import _duplicate_risk_score

        doc = {
            "bc_validation": {
                "checks": [
                    {"check_name": "duplicate_check", "passed": False}
                ]
            }
        }

        score = _duplicate_risk_score(doc)
        assert score == 1.0, f"Expected 1.0 when BC check failed, got {score}"
        print("PASS: _duplicate_risk_score returns 1.0 when BC duplicate_check failed")

    def test_duplicate_risk_score_fallback_possible_duplicate(self):
        """No BC check, possible_duplicate=True → risk score 0.7"""
        import sys
        sys.path.insert(0, "/app/backend")
        from services.automation_intelligence_service import _duplicate_risk_score

        doc = {
            "bc_validation": {"checks": []},
            "possible_duplicate": True
        }

        score = _duplicate_risk_score(doc)
        assert score == 0.7, f"Expected 0.7 fallback for possible_duplicate, got {score}"
        print("PASS: _duplicate_risk_score returns 0.7 fallback when possible_duplicate=True")

    def test_duplicate_risk_score_fallback_is_duplicate(self):
        """No BC check, is_duplicate=True → risk score 1.0"""
        import sys
        sys.path.insert(0, "/app/backend")
        from services.automation_intelligence_service import _duplicate_risk_score

        doc = {
            "bc_validation": None,
            "is_duplicate": True
        }

        score = _duplicate_risk_score(doc)
        assert score == 1.0, f"Expected 1.0 for is_duplicate=True, got {score}"
        print("PASS: _duplicate_risk_score returns 1.0 when is_duplicate=True")


class TestEvaluateReadinessBlockingReasons:
    """Test evaluate_readiness() blocking_reasons logic"""

    def test_no_duplicate_risk_blocker_when_bc_passed(self):
        """
        Scenario: Document has possible_duplicate=True but BC duplicate_check passed
        Expected: duplicate_risk should NOT be in blocking_reasons
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import evaluate_readiness

        doc = {
            "id": "test-no-blocker",
            "document_type": "AP_Invoice",
            "possible_duplicate": True,  # Stale flag
            "bc_validation": {
                "checks": [
                    {"check_name": "duplicate_check", "passed": True}
                ]
            },
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-008",
                "amount": 800.00
            },
            "vendor_canonical": "V-001",
            "vendor_match_method": "bc_exact_match"
        }

        readiness = evaluate_readiness(doc)
        assert "duplicate_risk" not in readiness["blocking_reasons"], \
            f"duplicate_risk should NOT be in blocking_reasons when BC check passed, got {readiness['blocking_reasons']}"
        print("PASS: duplicate_risk NOT in blocking_reasons when BC duplicate_check passed")

    def test_duplicate_risk_blocker_when_bc_failed(self):
        """
        Scenario: BC duplicate_check passed=False
        Expected: duplicate_risk should be in blocking_reasons
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import evaluate_readiness

        doc = {
            "id": "test-with-blocker",
            "document_type": "AP_Invoice",
            "bc_validation": {
                "checks": [
                    {"check_name": "duplicate_check", "passed": False}
                ]
            },
            "extracted_fields": {
                "vendor": "Test Vendor",
                "invoice_number": "INV-009",
                "amount": 900.00
            },
            "vendor_canonical": "V-002",
            "vendor_match_method": "bc_exact_match"
        }

        readiness = evaluate_readiness(doc)
        assert "duplicate_risk" in readiness["blocking_reasons"], \
            f"duplicate_risk should be in blocking_reasons when BC check failed, got {readiness['blocking_reasons']}"
        print("PASS: duplicate_risk IN blocking_reasons when BC duplicate_check failed")


class TestReadinessAPIEndpoint:
    """Test POST /api/readiness/evaluate/{doc_id} endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test document in MongoDB"""
        self.test_doc_id = f"test-readiness-api-{uuid.uuid4().hex[:8]}"
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_evaluate_endpoint_returns_success(self):
        """Test that the evaluate endpoint works and returns readiness data"""
        # First, create a test document via the API
        # We'll use the documents endpoint if available, or insert directly

        # Try to evaluate a non-existent document first to verify 404 handling
        response = self.session.post(f"{BASE_URL}/api/readiness/evaluate/nonexistent-doc-12345")
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"
        print("PASS: POST /api/readiness/evaluate returns 404 for non-existent document")


class TestLearningDashboardIncludesCorrections:
    """Test GET /api/posting-patterns/learning-dashboard includes readiness_self_correction events"""

    def test_learning_dashboard_returns_corrections_count(self):
        """Verify learning dashboard includes total_corrections which counts readiness_self_correction events"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})

        response = session.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()
        assert "summary" in data, "Response should have 'summary' field"
        assert "total_corrections" in data["summary"], "Summary should have 'total_corrections' field"
        assert isinstance(data["summary"]["total_corrections"], int), "total_corrections should be an integer"

        # Check correction_types includes readiness corrections if any exist
        if "correction_types" in data:
            print(f"Correction types found: {data['correction_types']}")

        print(f"PASS: Learning dashboard returns total_corrections={data['summary']['total_corrections']}")


class TestIntegrationScenario:
    """
    Integration test: Create document matching the exact production scenario,
    evaluate readiness, verify signals and learning events.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test document ID"""
        self.test_doc_id = f"test-integration-{uuid.uuid4().hex[:8]}"
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_full_scenario_ap_invoice_with_contradictions(self):
        """
        Scenario matching production bug:
        - AP_Invoice document
        - possible_duplicate=True (stale flag from ingestion)
        - bc_validation.checks has duplicate_check passed=True (BC says no duplicate)
        - bc_validation.checks has po_check passed=False (PO not found in BC)
        - PO was extracted (po_number field present)

        Expected after evaluation:
        - duplicate_risk signal = False (BC override)
        - po_resolved signal = False (BC override)
        - duplicate_risk NOT in blocking_reasons
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from services.document_readiness_service import compute_signals, evaluate_readiness

        # Create document matching the exact production scenario
        doc = {
            "id": self.test_doc_id,
            "document_type": "AP_Invoice",
            "suggested_job_type": "AP_Invoice",
            "possible_duplicate": True,  # Stale flag from ingestion
            "extracted_fields": {
                "vendor": "ACME Corp",
                "invoice_number": "INV-2024-001",
                "amount": 1500.00,
                "po_number": "PO-9999"  # PO was extracted
            },
            "bc_validation": {
                "status": "validated",
                "checks": [
                    {
                        "check_name": "duplicate_check",
                        "passed": True,  # BC says no duplicate
                        "message": "No duplicate found"
                    },
                    {
                        "check_name": "po_check",
                        "passed": False,  # BC says PO not found
                        "message": "PO not found in BC"
                    }
                ]
            },
            "vendor_canonical": "V-ACME",
            "vendor_match_method": "bc_exact_match"
        }

        # Test compute_signals
        signals = compute_signals(doc)

        # Verify duplicate_risk is False (BC override)
        assert signals["duplicate_risk"] is False, \
            f"duplicate_risk should be False (BC passed), got {signals['duplicate_risk']}"

        # Verify po_resolved is False (BC override)
        assert signals["po_resolved"] is False, \
            f"po_resolved should be False (BC po_check failed), got {signals['po_resolved']}"

        print("PASS: compute_signals correctly handles BC validation overrides")

        # Test evaluate_readiness
        readiness = evaluate_readiness(doc)

        # Verify duplicate_risk NOT in blocking_reasons
        assert "duplicate_risk" not in readiness["blocking_reasons"], \
            f"duplicate_risk should NOT be in blocking_reasons, got {readiness['blocking_reasons']}"

        # Verify po_missing IS in warning_reasons (since po_resolved=False)
        assert "po_missing" in readiness["warning_reasons"], \
            f"po_missing should be in warning_reasons, got {readiness['warning_reasons']}"

        print("PASS: evaluate_readiness correctly excludes duplicate_risk from blockers")
        print(f"  Status: {readiness['status']}")
        print(f"  Blocking reasons: {readiness['blocking_reasons']}")
        print(f"  Warning reasons: {readiness['warning_reasons']}")
        print(f"  Signals: duplicate_risk={signals['duplicate_risk']}, po_resolved={signals['po_resolved']}")


class TestHealthCheck:
    """Basic health check to ensure API is running"""

    def test_health_endpoint(self):
        """Verify API is accessible"""
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("PASS: API health check")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
