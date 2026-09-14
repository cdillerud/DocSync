import asyncio
import json

import httpx
import pytest

from services.ap_routing_anchor_authority_service import summarize_high_specificity_anchor_authority
from services.ap_routing_evidence_snapshot_service import (
    load_valid_evidence_snapshot,
    snapshot_examples_sha256,
)
from services.ap_routing_evaluation_service import cutover_qualification_gate
from services.ap_routing_learned_features_service import (
    SEMANTIC_FEATURE_SCHEMA,
    semantic_features,
)
from services.ap_routing_learned_neighborhood_service import summarize_authority_neighborhood
import services.ap_routing_semantic_hydration_service as hydration
from services.ap_routing_semantic_hydration_service import (
    HYDRATION_POLICY_VERSION,
    compact_unlabeled_filename_date_refs,
    enrich_routing_example_with_semantics,
    sanitize_filename_for_reference_resolution,
)

DNP = "DO NOT PAY"
DETENTION = "Vendor Credit Memos/Ball Detention Credits"
AUTHORITY = "gamerpackaging1.sharepoint.com/sites/GamerAccounting/General/Accounting/Accounts Payable/Temp Folder"


def contract():
    return {
        "version": "v117-semantic-evidence-test",
        "static_routes": [DNP, DETENTION],
        "dynamic_routes": [],
        "manual_only_routes": [],
        "review_route": "",
    }


def document(text="", *, file_name="Ball_6363143.pdf"):
    return {
        "file_name": file_name,
        "vendor_name": "Ball Metal Beverage Container",
        "vendor_canonical": "Ball Metal Beverage Container",
        "document_type": "Credit_Memo",
        "suggested_job_type": "Credit_Memo",
        "raw_text": text,
        "extracted_fields": {
            "vendor": "Ball Metal Beverage Container",
            "document_type": "Credit_Memo",
        },
    }


def base_example(route=DETENTION, *, fingerprint="fp"):
    return {
        "fingerprint": fingerprint,
        "source_item_id": fingerprint,
        "file_name": f"{fingerprint}.pdf",
        "vendor_name": "Ball Metal Beverage Container",
        "normalized_vendor": "ball metal beverage container",
        "document_type": "Credit_Memo",
        "route_path": route,
        "label_source": "accounting_temp",
        "active": True,
        "extracted_fields": {
            "vendor": "Ball Metal Beverage Container",
            "document_type": "Credit_Memo",
        },
        "bc_context": {},
    }


def semantic_example(route, text, fingerprint):
    return enrich_routing_example_with_semantics(
        base_example(route, fingerprint=fingerprint),
        document=document(text, file_name=f"{fingerprint}.pdf"),
    )


def write_snapshot(
    path,
    examples,
    *,
    semantic_schema=SEMANTIC_FEATURE_SCHEMA,
    hydration_policy=HYDRATION_POLICY_VERSION,
):
    payload = {
        "schema_version": "v117",
        "semantic_feature_schema": semantic_schema,
        "hydration_policy_version": hydration_policy,
        "authority": AUTHORITY,
        "feature_commit": "test",
        "example_count": len(examples),
        "examples_sha256": snapshot_examples_sha256(examples),
        "examples": examples,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_hydration_enrichment_persists_text_features_and_mirror():
    enriched = semantic_example(
        DNP,
        "Credit memo for detention. Reversing this credit memo as requested.",
        "reversal",
    )
    assert enriched["learned_feature_schema"] == SEMANTIC_FEATURE_SCHEMA
    assert "reversal_or_void" in enriched["learned_semantic_features"]
    assert "detention" in enriched["learned_semantic_features"]
    assert "Reversing this credit memo" in enriched["raw_text_excerpt"]
    assert enriched["extracted_fields"]["_learned_feature_schema"] == SEMANTIC_FEATURE_SCHEMA
    assert enriched["extracted_fields"]["_learned_semantic_features"] == enriched["learned_semantic_features"]


def test_stored_semantics_survive_when_runtime_text_is_missing():
    enriched = semantic_example(
        DNP,
        "Credit memo for detention. Reversing this credit memo as requested.",
        "stored",
    )
    replay_document = {
        "file_name": enriched["file_name"],
        "document_type": enriched["document_type"],
        "raw_text": "",
        "extracted_fields": enriched["extracted_fields"],
        "learned_feature_schema": enriched["learned_feature_schema"],
        "learned_semantic_features": enriched["learned_semantic_features"],
    }
    assert "reversal_or_void" in semantic_features(replay_document)
    assert "detention" in semantic_features(replay_document)


def test_semantic_snapshot_is_route_label_independent():
    text = "Credit memo for detention. Reversing this credit memo as requested."
    a = semantic_example(DNP, text, "a")
    b = semantic_example(DETENTION, text, "b")
    assert a["learned_semantic_features"] == b["learned_semantic_features"]
    assert a["learned_reference_family"] == b["learned_reference_family"]


def test_old_snapshot_without_semantic_schema_is_rejected(tmp_path):
    examples = [
        semantic_example(DNP, "DO NOT PAY", "dnp"),
        semantic_example(DETENTION, "detention credit memo", "detention"),
    ]
    path = tmp_path / "legacy.json"
    write_snapshot(path, examples, semantic_schema="")
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
    )
    assert result["valid"] is False
    assert result["reason"].startswith("semantic_feature_schema_mismatch:")


def test_snapshot_missing_hydration_policy_is_rejected(tmp_path):
    examples = [
        semantic_example(DNP, "DO NOT PAY", "dnp"),
        semantic_example(DETENTION, "detention credit memo", "detention"),
    ]
    path = tmp_path / "pre-retry-policy.json"
    write_snapshot(path, examples, hydration_policy="")
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
    )
    assert result["valid"] is False
    assert result["reason"] == (
        "hydration_policy_version_mismatch:missing!=" + HYDRATION_POLICY_VERSION
    )


def test_snapshot_missing_semantic_mirror_is_rejected(tmp_path):
    examples = [
        semantic_example(DNP, "DO NOT PAY", "dnp"),
        semantic_example(DETENTION, "detention credit memo", "detention"),
    ]
    examples[0]["extracted_fields"].pop("_learned_semantic_features")
    path = tmp_path / "bad-mirror.json"
    write_snapshot(path, examples)
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
    )
    assert result["valid"] is False
    assert result["reason"] == "example_semantic_feature_mirror_mismatch"


def test_semantic_complete_snapshot_replays_with_sha_verification(tmp_path):
    examples = [
        semantic_example(DNP, "DO NOT PAY replaced by invoice", "dnp"),
        semantic_example(DETENTION, "detention credit memo", "detention"),
    ]
    path = tmp_path / "good.json"
    write_snapshot(path, examples)
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
    )
    assert result["valid"] is True
    assert result["integrity"] == "sha256_verified"
    assert result["semantic_feature_schema"] == SEMANTIC_FEATURE_SCHEMA
    assert result["hydration_policy_version"] == HYDRATION_POLICY_VERSION


def test_compact_filename_dates_are_not_bc_reference_evidence_and_stale_snapshot_fails_closed(tmp_path, monkeypatch):
    buske = "119065_Buske_091026_.pdf"
    reile = "118911_REILE'S_090326_BOL - need to receive.pdf"
    bb = "119006_B&B Packaging_090926_BOL.pdf"

    assert compact_unlabeled_filename_date_refs(buske) == {"91026"}
    assert compact_unlabeled_filename_date_refs(reile) == {"90326"}
    assert compact_unlabeled_filename_date_refs(bb) == {"90926"}
    assert "091026" not in sanitize_filename_for_reference_resolution(buske)
    assert "090326" not in sanitize_filename_for_reference_resolution(reile)
    assert "090926" not in sanitize_filename_for_reference_resolution(bb)
    assert "119065" in sanitize_filename_for_reference_resolution(buske)
    assert "118911" in sanitize_filename_for_reference_resolution(reile)
    assert "119006" in sanitize_filename_for_reference_resolution(bb)

    explicit = "PO_091026_vendor.pdf"
    assert compact_unlabeled_filename_date_refs(explicit) == set()
    assert "091026" in sanitize_filename_for_reference_resolution(explicit)

    examples = [
        semantic_example(DNP, "DO NOT PAY", "dnp"),
        semantic_example(DETENTION, "detention credit memo", "detention"),
    ]
    examples[0]["file_name"] = buske
    examples[0]["bc_context"] = {"status": "resolved", "po_number": "91026"}
    path = tmp_path / "date-derived-ref.json"
    write_snapshot(path, examples)
    result = load_valid_evidence_snapshot(
        path,
        expected_authority=AUTHORITY,
        contract=contract(),
        minimum_examples=2,
    )
    assert result["valid"] is False
    assert result["reason"] == "resolved_bc_reference_matches_compact_filename_date"

    dirty_document = {
        "file_name": buske,
        "document_type": "AP_Invoice",
        "raw_text": "Invoice date 091026. Real order 119065.",
        "extracted_fields": {"po_number": "091026", "order_number": "119065"},
    }
    dirty_bundle = {
        "references": {
            "po_numbers": [
                {"value": "091026", "source": "supporting_page_ai"},
                {"value": "119065", "source": "labeled_regex"},
            ]
        }
    }
    calls = []

    async def resolves_cleanly(candidate, *, bundle_refs=None):
        calls.append((candidate, bundle_refs))
        if len(calls) == 1:
            return {"status": "resolved", "po_number": "91026"}
        assert "091026" not in candidate["file_name"]
        assert "091026" not in candidate["raw_text"]
        assert candidate["extracted_fields"]["po_number"] == ""
        assert candidate["extracted_fields"]["order_number"] == "119065"
        assert [x["value"] for x in bundle_refs["references"]["po_numbers"]] == ["119065"]
        return {"status": "resolved", "po_number": "119065"}

    monkeypatch.setattr(hydration.corpus, "resolve_ap_routing_context", resolves_cleanly)
    rerun = asyncio.run(
        hydration._resolve_context_without_filename_date_collision(
            dirty_document,
            dirty_bundle,
            buske,
        )
    )
    assert len(calls) == 2
    assert rerun["status"] == "resolved"
    assert rerun["po_number"] == "119065"

    async def still_contaminated(candidate, *, bundle_refs=None):
        return {"status": "resolved", "po_number": "91026", "bc_vendor_name": "Wrong Winner"}

    monkeypatch.setattr(hydration.corpus, "resolve_ap_routing_context", still_contaminated)
    quarantined = asyncio.run(
        hydration._resolve_context_without_filename_date_collision(
            dirty_document,
            dirty_bundle,
            buske,
        )
    )
    assert quarantined["status"] == "not_found"
    assert quarantined["miss_reason"] == "filename_compact_date_collision"
    assert quarantined.get("po_number") is None
    assert quarantined.get("bc_vendor_name") is None
    assert quarantined["filename_date_collision_refs"] == ["91026"]


def test_transient_hydration_transport_failure_recovers_with_bounded_retry(monkeypatch):
    calls = 0

    async def flaky_once(label, *, routing_contract=None):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectTimeout("temporary Graph timeout")
        return {"file_name": label["file_name"], "route_path": "DO NOT PAY"}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(hydration, "_hydrate_accounting_label_with_semantics_once", flaky_once)
    monkeypatch.setattr(hydration.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        hydration.hydrate_accounting_label_with_semantics({"file_name": "retry.pdf"})
    )
    assert result["file_name"] == "retry.pdf"
    assert calls == hydration.HYDRATION_MAX_ATTEMPTS == 3


def test_permanent_hydration_failure_does_not_retry(monkeypatch):
    calls = 0

    async def malformed_once(label, *, routing_contract=None):
        nonlocal calls
        calls += 1
        raise ValueError("malformed pdf")

    async def unexpected_sleep(_delay):
        raise AssertionError("permanent failures must not sleep/retry")

    monkeypatch.setattr(hydration, "_hydrate_accounting_label_with_semantics_once", malformed_once)
    monkeypatch.setattr(hydration.asyncio, "sleep", unexpected_sleep)

    with pytest.raises(ValueError, match="malformed pdf"):
        asyncio.run(
            hydration.hydrate_accounting_label_with_semantics({"file_name": "bad.pdf"})
        )
    assert calls == 1


def test_cutover_qualification_allows_shadow_rehearsal_but_not_cutover_at_low_coverage():
    result = cutover_qualification_gate(
        {
            "holdout_count": 37,
            "coverage": 0.2162,
            "auto_route_accuracy": 1.0,
            "wrong_auto_routes": 0,
        },
        labeled_example_count=323,
        focused_regressions_passed=True,
        source_health_ok=True,
        production_mutation_none=True,
        hydration_policy_validated=True,
        evidence_replay_validated=True,
    )
    assert result["mode"] == "SHADOW_REHEARSAL"
    assert result["shadow_rehearsal_ready"] is True
    assert result["cutover_ready"] is False
    assert result["production_promotion_gate"]["ready_for_runtime_authority"] is False
    assert result["production_promotion_gate"]["reasons"] == [
        "auto-route coverage 21.6% below 90.0%"
    ]


def test_cutover_qualification_blocks_shadow_rehearsal_on_any_wrong_auto_route():
    result = cutover_qualification_gate(
        {
            "holdout_count": 37,
            "coverage": 0.95,
            "auto_route_accuracy": 0.9722,
            "wrong_auto_routes": 1,
        },
        labeled_example_count=323,
        focused_regressions_passed=True,
        source_health_ok=True,
        production_mutation_none=True,
        hydration_policy_validated=True,
        evidence_replay_validated=True,
    )
    assert result["mode"] == "BLOCKED"
    assert result["shadow_rehearsal_ready"] is False
    assert result["cutover_ready"] is False
    assert "1 wrong auto-route(s) in holdout" in result["reasons"]


def test_cutover_qualification_requires_full_promotion_gate_for_cutover_ready():
    result = cutover_qualification_gate(
        {
            "holdout_count": 40,
            "coverage": 0.90,
            "auto_route_accuracy": 1.0,
            "wrong_auto_routes": 0,
        },
        labeled_example_count=323,
        focused_regressions_passed=True,
        source_health_ok=True,
        production_mutation_none=True,
        hydration_policy_validated=True,
        evidence_replay_validated=True,
    )
    assert result["mode"] == "CUTOVER_READY"
    assert result["shadow_rehearsal_ready"] is True
    assert result["cutover_ready"] is True
    assert result["production_promotion_gate"]["ready_for_runtime_authority"] is True
