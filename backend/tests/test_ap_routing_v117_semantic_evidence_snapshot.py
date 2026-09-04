import json

from services.ap_routing_evidence_snapshot_service import (
    load_valid_evidence_snapshot,
    snapshot_examples_sha256,
)
from services.ap_routing_learned_features_service import (
    SEMANTIC_FEATURE_SCHEMA,
    semantic_features,
)
from services.ap_routing_learned_neighborhood_service import summarize_authority_neighborhood
from services.ap_routing_semantic_hydration_service import enrich_routing_example_with_semantics

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


def write_snapshot(path, examples, *, semantic_schema=SEMANTIC_FEATURE_SCHEMA):
    payload = {
        "schema_version": "v117",
        "semantic_feature_schema": semantic_schema,
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


def test_stored_reversal_feature_blocks_ordinary_detention_bootstrap():
    current = semantic_example(
        DNP,
        "Credit memo for detention. Reversing this credit memo as requested.",
        "current",
    )
    current["raw_text_excerpt"] = ""
    rows = [
        semantic_example(DETENTION, "Credit memo for detention charge.", f"ordinary-{i}")
        for i in range(5)
    ]
    result = summarize_authority_neighborhood(
        document=current,
        proposed_route=DETENTION,
        train_examples=rows,
    )
    assert result["exceptional_workflow_features"] == ["reversal_or_void"]
    assert result["exception_support_count"] == 0
    assert result["exception_mismatch_support_count"] >= 3
    assert result["authority_ready"] is False


def test_explicit_stop_pay_is_not_forced_into_reversal_exception_boundary():
    current = semantic_example(DNP, "DO NOT PAY this invoice", "current-dnp")
    rows = [semantic_example(DNP, "DO NOT PAY this invoice", f"dnp-{i}") for i in range(5)]
    result = summarize_authority_neighborhood(
        document=current,
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["exceptional_workflow_features"] == []
    assert result["authority_ready"] is True
