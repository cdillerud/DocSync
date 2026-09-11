from services.ap_routing_learned_autonomy_service import evaluate_learned_autonomy


PROPOSED = "Rhonda - Issues"
OTHER = "Dropship Not International/Freight"


def doc(text="detention invoice"):
    return {
        "file_name": "114745_TUMALO_0309048 CP_07012026 - DET waiting for corrected invoice.pdf",
        "vendor_name": "TUMALO CREEK TRANSPORTATION",
        "vendor_canonical": "TUMALO CREEK TRANSPORTATION",
        "document_type": "AP_Invoice",
        "raw_text": text,
        "extracted_fields": {
            "vendor": "TUMALO CREEK TRANSPORTATION",
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
    }


def ex(route, fingerprint, *, text="standard freight invoice"):
    return {
        "fingerprint": fingerprint,
        "vendor_name": "TUMALO CREEK TRANSPORTATION",
        "normalized_vendor": "TUMALO CREEK TRANSPORTATION",
        "document_type": "AP_Invoice",
        "route_path": route,
        "label_source": "accounting_temp",
        "active": True,
        "split": "train",
        "file_name": f"{fingerprint}.pdf",
        "raw_text_excerpt": text,
        "extracted_fields": {
            "vendor": "TUMALO CREEK TRANSPORTATION",
            "document_type": "AP_Invoice",
        },
        "bc_context": {},
    }


def ai(route=PROPOSED, confidence=0.98):
    return {
        "proposed_route": route,
        "route_path": route,
        "confidence": confidence,
        "prediction": {
            "proposed_route": route,
            "confidence": confidence,
            "unresolved": [],
        },
    }


def test_discriminating_workflow_blocks_broad_vendor_autonomy_with_only_one_semantic_support():
    rows = [
        ex(PROPOSED, "semantic-support-1", text="detention invoice awaiting correction"),
        *[ex(PROPOSED, f"broad-support-{i}") for i in range(6)],
        ex(OTHER, "contradiction"),
    ]

    decision = evaluate_learned_autonomy(
        document=doc(),
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert "detention" in guard["features"]
    assert guard["support_count"] == 1
    assert guard["minimum_support"] == 2
    assert guard["authority_ready"] is False
    assert decision["decision"] == "needs_review"
    assert decision["route_path"] == ""
    assert decision["ai_proposed_route"] == PROPOSED


def test_discriminating_workflow_allows_broad_vendor_autonomy_after_two_semantic_supports():
    rows = [
        ex(PROPOSED, "semantic-support-1", text="detention invoice awaiting correction"),
        ex(PROPOSED, "semantic-support-2", text="detention freight invoice"),
        *[ex(PROPOSED, f"broad-support-{i}") for i in range(5)],
        ex(OTHER, "contradiction"),
    ]

    decision = evaluate_learned_autonomy(
        document=doc(),
        ai_decision=ai(),
        train_examples=rows,
    )

    guard = decision["discriminating_semantic_authority"]
    assert guard["active"] is True
    assert guard["support_count"] >= 2
    assert guard["authority_ready"] is True
    assert decision["decision"] == "auto_route"
    assert decision["route_path"] == PROPOSED
    assert decision["route_preserved"] is True
