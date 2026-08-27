import pytest

from services.operator_identity_correction_service import build_identity_invalidation


def _doc(**overrides):
    base = {
        "id": "doc-1",
        "status": "NeedsReview",
        "vendor_id": "V100",
        "po_number_clean": "PO100",
        "bc_record_id": "old-record-id",
        "bc_system_id": "old-system-id",
        "bc_entity_type": "purchaseOrders",
        "bc_document_no": "PO100",
        "delivery_status": "ImportReady",
        "import_ready": True,
        "po_resolution": {"po_number": "PO100"},
    }
    base.update(overrides)
    return base


def test_po_correction_invalidates_derived_bc_identity_and_readiness():
    change = build_identity_invalidation(_doc(), po_number="PO200")

    assert change["changed"] is True
    fields = change["set"]
    assert fields["bc_record_id"] is None
    assert fields["bc_system_id"] is None
    assert fields["bc_entity_type"] is None
    assert fields["bc_document_no"] is None
    assert fields["po_resolution"] is None
    assert fields["import_ready"] is False
    assert fields["delivery_status"] == "NeedsResolution"
    assert fields["status"] == "NeedsReview"
    assert fields["sharepoint_parity_metadata_stale"] is True
    assert change["audit"]["previous_bc_system_id"] == "old-system-id"
    assert change["audit"]["previous_po_number"] == "PO100"
    assert change["audit"]["corrected_po_number"] == "PO200"


def test_vendor_correction_also_invalidates_identity():
    change = build_identity_invalidation(_doc(), vendor_id="V200")
    assert change["changed"] is True
    assert change["set"]["identity_correction_pending_resolution"] is True
    assert change["audit"]["previous_vendor_id"] == "V100"
    assert change["audit"]["corrected_vendor_id"] == "V200"


def test_same_vendor_and_po_do_not_invalidate_identity():
    change = build_identity_invalidation(
        _doc(), vendor_id="V100", po_number="PO100"
    )
    assert change == {"changed": False, "set": {}, "audit": None}


def test_final_bc_linkage_cannot_be_silently_repointed():
    with pytest.raises(ValueError, match="explicit unlink/recovery"):
        build_identity_invalidation(
            _doc(status="LinkedToBC"), po_number="PO200"
        )


def test_explicit_bc_link_created_cannot_be_silently_repointed():
    with pytest.raises(ValueError, match="explicit unlink/recovery"):
        build_identity_invalidation(
            _doc(bc_link_created=True), vendor_id="V200"
        )
