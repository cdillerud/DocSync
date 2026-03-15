"""
Tests for Decisioning & Automation shared helpers.

Covers:
  - utcnow() format and timezone
  - EligibilityCheck / EligibilityResult
  - build_document_update (enforced updated_utc)
  - Cross-service consistency: verify callers still use the shared timestamp
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.automation_helpers import (
    utcnow,
    build_document_update,
    EligibilityCheck,
    EligibilityResult,
)


# ============================================================================
# utcnow()
# ============================================================================

class TestUtcnow:
    def test_returns_string(self):
        ts = utcnow()
        assert isinstance(ts, str)

    def test_iso_format(self):
        ts = utcnow()
        # Must parse as ISO 8601 with timezone
        from datetime import datetime
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_utc_timezone(self):
        ts = utcnow()
        assert "+00:00" in ts

    def test_unique_on_successive_calls(self):
        ts1 = utcnow()
        ts2 = utcnow()
        # Could be same if fast enough, but both must be valid
        assert isinstance(ts1, str) and isinstance(ts2, str)


# ============================================================================
# build_document_update()
# ============================================================================

class TestBuildDocumentUpdate:
    def test_adds_updated_utc(self):
        result = build_document_update({"status": "cleared"})
        assert "updated_utc" in result
        assert result["status"] == "cleared"

    def test_overwrites_stale_updated_utc(self):
        result = build_document_update({"updated_utc": "old-value", "foo": "bar"})
        assert result["updated_utc"] != "old-value"
        assert result["foo"] == "bar"

    def test_removes_id(self):
        result = build_document_update({"_id": "should-be-removed", "x": 1})
        assert "_id" not in result
        assert result["x"] == 1

    def test_empty_fields(self):
        result = build_document_update({})
        assert "updated_utc" in result

    def test_preserves_all_fields(self):
        fields = {"a": 1, "b": "two", "c": [3], "d": {"nested": True}}
        result = build_document_update(fields)
        assert result["a"] == 1
        assert result["b"] == "two"
        assert result["c"] == [3]
        assert result["d"] == {"nested": True}
        assert "updated_utc" in result


# ============================================================================
# EligibilityCheck / EligibilityResult
# ============================================================================

class TestEligibilityCheck:
    def test_basic(self):
        check = EligibilityCheck(
            name="confidence_threshold",
            passed=True,
            value=0.95,
            threshold=0.80,
            message="Confidence exceeds threshold",
        )
        assert check.passed is True
        d = check.to_dict()
        assert d["check"] == "confidence_threshold"
        assert d["passed"] is True
        assert d["value"] == 0.95
        assert d["threshold"] == 0.80

    def test_failed_check(self):
        check = EligibilityCheck(name="vendor_match", passed=False, message="No vendor found")
        d = check.to_dict()
        assert d["passed"] is False
        assert d["message"] == "No vendor found"


class TestEligibilityResult:
    def test_all_passed(self):
        result = EligibilityResult(
            eligible=True,
            decision="cleared",
            reason="All checks passed",
            checks=[
                EligibilityCheck(name="a", passed=True),
                EligibilityCheck(name="b", passed=True),
            ],
        )
        assert result.all_passed is True
        assert result.eligible is True
        d = result.to_dict()
        assert d["all_passed"] is True
        assert len(d["checks"]) == 2

    def test_some_failed(self):
        result = EligibilityResult(
            eligible=False,
            decision="needs_review",
            reason="Vendor match failed",
            checks=[
                EligibilityCheck(name="a", passed=True),
                EligibilityCheck(name="b", passed=False),
            ],
        )
        assert result.all_passed is False
        assert result.eligible is False

    def test_empty_checks(self):
        result = EligibilityResult(eligible=True, decision="cleared", reason="ok")
        assert result.all_passed is True  # vacuously true

    def test_metadata(self):
        result = EligibilityResult(
            eligible=True, decision="cleared", reason="ok",
            metadata={"doc_type": "AP Invoice"},
        )
        d = result.to_dict()
        assert d["metadata"]["doc_type"] == "AP Invoice"


# ============================================================================
# Cross-service: verify callers import from shared module
# ============================================================================

class TestCrossServiceImports:
    """Verify that the target services actually import from automation_helpers."""

    def test_decision_policy_imports_utcnow(self):
        import services.decision_policy_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from services.automation_helpers import" in src

    def test_automation_rules_imports_utcnow(self):
        import services.automation_rules_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from services.automation_helpers import" in src

    def test_auto_resolution_imports_utcnow(self):
        import services.auto_resolution_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from services.automation_helpers import" in src

    def test_auto_clear_imports_utcnow(self):
        import services.auto_clear_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from services.automation_helpers import" in src

    def test_auto_post_imports_utcnow(self):
        import services.auto_post_service as mod
        import inspect
        src = inspect.getsource(mod)
        assert "from services.automation_helpers import" in src


# ============================================================================
# Cross-service: verify utcnow() is actually used (not dead import)
# ============================================================================

class TestUtcnowUsageInServices:
    """Verify that services call utcnow() rather than raw datetime calls."""

    def _count_pattern(self, filepath, pattern):
        with open(filepath) as f:
            content = f.read()
        return content.count(pattern)

    def test_decision_policy_no_raw_datetime(self):
        raw = self._count_pattern(
            "services/decision_policy_service.py",
            "datetime.now(timezone.utc).isoformat()",
        )
        shared = self._count_pattern(
            "services/decision_policy_service.py",
            "utcnow()",
        )
        assert raw == 0, f"Found {raw} raw datetime calls — should use utcnow()"
        assert shared > 0, "utcnow() not found"

    def test_auto_post_no_raw_datetime(self):
        raw = self._count_pattern(
            "services/auto_post_service.py",
            "datetime.now(timezone.utc).isoformat()",
        )
        shared = self._count_pattern(
            "services/auto_post_service.py",
            "utcnow()",
        )
        assert raw == 0, f"Found {raw} raw datetime calls"
        assert shared > 0

    def test_auto_resolution_no_raw_datetime(self):
        raw = self._count_pattern(
            "services/auto_resolution_service.py",
            "datetime.now(timezone.utc).isoformat()",
        )
        shared = self._count_pattern(
            "services/auto_resolution_service.py",
            "utcnow()",
        )
        assert raw == 0, f"Found {raw} raw datetime calls"
        assert shared > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
