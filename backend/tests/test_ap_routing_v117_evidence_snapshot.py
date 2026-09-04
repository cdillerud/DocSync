import json
import os
import time

from services.ap_routing_evidence_snapshot_service import (
    load_valid_evidence_snapshot,
    snapshot_examples_sha256,
)


AUTHORITY = "gamerpackaging1.sharepoint.com/sites/GamerAccounting/General/Accounting/Accounts Payable/Temp Folder"
ROUTE_A = "DO NOT PAY"
ROUTE_B = "Rhonda - Issues"


def contract(*routes):
    return {
        "version": "v117-snapshot-test",
        "static_routes": list(routes or (ROUTE_A, ROUTE_B)),
        "dynamic_routes": [],
    }


def example(idx, route, **overrides):
    row = {
        "fingerprint": f"example-{idx}",
        "file_name": f"example-{idx}.pdf",
        "vendor_name": "Test Vendor",
        "document_type": "AP_Invoice",
        "route_path": route,
        "label_source": "accounting_temp",
        "active": True,
        "extracted_fields": {"vendor": "Test Vendor"},
        "bc_context": {},
    }
    row.update(overrides)
    return row


def write_snapshot(path, examples, **overrides):
    payload = {
        "schema_version": "1.0",
        "feature_commit": "source-feature",
        "authority": AUTHORITY,
        "example_count": len(examples),
        "examples": examples,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def load(path, **kwargs):
    return load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
        **kwargs,
    )


def two_examples():
    return [example(1, ROUTE_A), example(2, ROUTE_B)]


def test_valid_legacy_snapshot_is_accepted_without_granting_new_authority(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, two_examples())
    result = load(path)
    assert result["valid"] is True
    assert result["reason"] == "validated"
    assert result["example_count"] == 2
    assert result["integrity"] == "legacy_no_digest"


def test_new_snapshot_sha256_is_verified(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = two_examples()
    write_snapshot(path, rows, examples_sha256=snapshot_examples_sha256(rows))
    result = load(path)
    assert result["valid"] is True
    assert result["integrity"] == "sha256_verified"


def test_digest_mismatch_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, two_examples(), examples_sha256="0" * 64)
    result = load(path)
    assert result["valid"] is False
    assert result["reason"] == "snapshot_digest_mismatch"


def test_stale_snapshot_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, two_examples())
    old = time.time() - (25 * 3600)
    os.utime(path, (old, old))
    result = load(path, max_age_hours=24)
    assert result["valid"] is False
    assert result["reason"] == "snapshot_stale"


def test_wrong_accounting_authority_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, two_examples(), authority="wrong/site")
    result = load(path)
    assert result["valid"] is False
    assert result["reason"] == "authority_mismatch"


def test_unreviewed_ai_example_cannot_enter_snapshot_authority(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = two_examples()
    rows[0]["label_source"] = "ai_prediction"
    rows[0]["ai_generated"] = True
    write_snapshot(path, rows)
    result = load(path)
    assert result["valid"] is False
    assert result["reason"].startswith("non_human_label_source:")


def test_holdout_or_test_evidence_cannot_be_replayed_as_train_authority(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = two_examples()
    rows[0]["split"] = "holdout"
    write_snapshot(path, rows)
    result = load(path)
    assert result["valid"] is False
    assert result["reason"] == "non_train_split:holdout"


def test_duplicate_example_identity_fails_closed(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = two_examples()
    rows[1]["fingerprint"] = rows[0]["fingerprint"]
    write_snapshot(path, rows)
    result = load(path)
    assert result["valid"] is False
    assert result["reason"] == "duplicate_example_identity"


def test_route_removed_from_current_contract_forces_live_rebuild(tmp_path):
    path = tmp_path / "snapshot.json"
    rows = two_examples()
    write_snapshot(path, rows)
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(ROUTE_A),
        minimum_examples=2,
    )
    assert result["valid"] is False
    assert result["reason"] == f"route_not_allowed:{ROUTE_B}"
