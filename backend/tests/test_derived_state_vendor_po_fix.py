"""
Test that the derived state service correctly handles:
1. Vendor matched in BC validation but vendor.match.failed event fired earlier
2. PO validation failed but manual_po_override is set
3. Blocking issues reflect ACTUAL failures, not stale event history
"""
import pytest
from services.derived_state_service import DerivedStateService


def make_event(event_type, payload=None, status="completed", source="test"):
    return {
        "event_id": f"evt-{event_type}",
        "document_id": "test-doc",
        "event_type": event_type,
        "status": status,
        "source_service": source,
        "payload": payload or {},
        "timestamp": "2026-04-02T11:08:48Z",
    }


# Document that mirrors the user's real scenario:
# - Vendor matched via BC at 100%
# - PO not found in BC
# - All other fields extracted
BASE_DOC = {
    "id": "test-doc",
    "status": "NeedsReview",
    "document_type": "AP_Invoice",
    "vendor_canonical": "TUMALOC",
    "bc_vendor_number": "TUMALOC",
    "validation_results": {
        "checks": [
            {"check_name": "vendor_match", "passed": True, "details": "Found vendor via business_central: Tumalo Creek (score: 100%)", "vendor_no": "TUMALOC", "vendor_name": "Tumalo Creek Transportation"},
            {"check_name": "po_validation", "passed": False, "details": "PO 'P0024310-2' not found in BC", "required": True},
            {"check_name": "duplicate_check", "passed": True, "details": "No duplicate found"},
            {"check_name": "freight_direction", "passed": True, "details": "INBOUND freight"},
        ],
        "bc_record_info": {"number": "TUMALOC", "displayName": "Tumalo Creek Transportation"},
    },
    "extracted_fields": {
        "vendor": "TUMALO CREEK Transportation",
        "invoice_number": "0304866",
        "amount": "1750.00",
        "invoice_date": "2026-04-02",
        "po_number": "P0024310-2",
    },
}


# Event sequence that mirrors user's document timeline
EVENTS = [
    make_event("document.received", source="auto_split"),
    make_event("system.reprocessed", source="ap_auto_post_service"),
    make_event("classification.completed", {"doc_type": "AP_Invoice", "confidence": 1.0}, source="ai_classifier"),
    make_event("vendor.match.failed", {"reason": "No match found"}, status="failed", source="unified_vendor_matcher"),
    make_event("bc.validation.failed", {
        "failed_checks": ["po_validation"],
        "checks_passed": 3,
        "checks_total": 4,
        "errors": ["PO 'P0024310-2' not found in BC"],
    }, status="failed", source="bc_sandbox_service"),
    make_event("sharepoint.upload.succeeded", source="sharepoint_service"),
    make_event("automation.decision.completed", {
        "decision": "needs_review",
        "reason": "AP invoices use strict auto-post service",
    }, source="auto_clear_service"),
    make_event("automation.decision.completed", {
        "decision": "NeedsReview",
        "auto_clear": False,
        "auto_post": False,
        "reason": "AP invoice not ready: PO extracted but not found/matched in BC",
        "failures": ["PO extracted but not found/matched in BC"],
        "source": "auto",
    }, source="ap_auto_post_service"),
    make_event("validation.completed", {
        "document_type": "AP_Invoice",
        "validation_state": "warning",
        "all_passed": False,
        "blocking_issues_count": 0,
        "warnings_count": 3,
        "vendor_resolved": True,
        "invoice_number_present": True,
        "invoice_date_present": True,
        "total_amount_present": True,
        "is_duplicate": False,
    }, source="auto_resolution"),
]


class TestDerivedStateVendorPOFix:
    """Test that vendor blocking issues are cleared when vendor is matched."""

    def _get_events_for_derive(self):
        """Return events in newest-first order (as the DB query returns them)."""
        return list(reversed(EVENTS))

    def test_vendor_not_in_blocking_issues_when_matched(self):
        """Core bug: vendor.match.failed fires, then bc.validation shows vendor IS matched.
        Blocking issues should NOT contain 'Vendor not matched'."""
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(BASE_DOC, self._get_events_for_derive())

        # "Vendor not matched" should NOT be in blocking issues
        for issue in result["blocking_issues"]:
            assert "Vendor" not in issue and "vendor" not in issue.lower(), (
                f"Stale vendor blocking issue found: '{issue}'"
            )

    def test_only_actual_po_failure_in_blocking_issues(self):
        """Blocking issues should contain only the real PO failure, not vendor noise."""
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(BASE_DOC, self._get_events_for_derive())

        # Should have exactly the PO failure
        po_blocks = [i for i in result["blocking_issues"] if "PO" in i or "po" in i.lower()]
        assert len(po_blocks) >= 1, f"PO failure should be in blocking issues. Got: {result['blocking_issues']}"

    def test_state_reason_mentions_po_not_vendor(self):
        """State reason should be about PO, not vendor."""
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(BASE_DOC, self._get_events_for_derive())

        assert "PO" in result["state_reason"] or "po" in result["state_reason"].lower(), (
            f"State reason should mention PO: '{result['state_reason']}'"
        )
        # Vendor should not be in state_reason
        assert "Vendor not matched" not in result["state_reason"]

    def test_manual_po_override_clears_po_blocks(self):
        """When manual_po_override is set, PO blocking issues should be cleared."""
        doc = {**BASE_DOC, "manual_po_override": True}
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(doc, self._get_events_for_derive())

        # No blocking issues should remain
        assert len(result["blocking_issues"]) == 0, (
            f"With manual_po_override, no blocking issues expected. Got: {result['blocking_issues']}"
        )

    def test_manual_po_override_upgrades_validation_state(self):
        """With override and no blocks, validation should upgrade from fail."""
        doc = {**BASE_DOC, "manual_po_override": True}
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(doc, self._get_events_for_derive())

        assert result["validation_state"] in ("pass", "warning"), (
            f"With override and no blocks, validation should be pass/warning. Got: {result['validation_state']}"
        )

    def test_manual_po_override_state_reason(self):
        """With override, state_reason should mention override, not PO failure."""
        doc = {**BASE_DOC, "manual_po_override": True}
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(doc, self._get_events_for_derive())

        assert "overridden" in result["state_reason"].lower(), (
            f"State reason should mention override: '{result['state_reason']}'"
        )

    def test_no_vendor_blocks_even_without_override(self):
        """Even without PO override, vendor should never be in blocking issues
        when BC validation shows vendor matched."""
        doc = {**BASE_DOC, "manual_po_override": False}
        dss = DerivedStateService(db=None)
        result = dss._derive_from_events(doc, self._get_events_for_derive())

        vendor_blocks = [i for i in result["blocking_issues"] if "Vendor" in i or "vendor" in i.lower()]
        assert len(vendor_blocks) == 0, f"Vendor blocks should be empty: {vendor_blocks}"

    def test_bc_validation_failed_clears_vendor_when_only_po_fails(self):
        """When bc.validation.failed has failed_checks=['po_validation'],
        vendor blocks should be cleared because vendor is NOT in failed checks."""
        dss = DerivedStateService(db=None)

        # Minimal event sequence: vendor.match.failed then bc.validation.failed
        # Events in newest-first order (as DB returns)
        events = [
            make_event("bc.validation.failed", {
                "failed_checks": ["po_validation"],
            }, status="failed"),
            make_event("vendor.match.failed", status="failed"),
        ]

        result = dss._derive_from_events(BASE_DOC, events)

        vendor_blocks = [i for i in result["blocking_issues"] if "Vendor" in i or "vendor" in i.lower()]
        assert len(vendor_blocks) == 0, f"Vendor blocks should be cleared: {vendor_blocks}"
        assert "po_validation" in result["blocking_issues"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
