from services.ap_routing_learned_features_service import feature_similarity, semantic_features
from services.ap_routing_learned_neighborhood_service import summarize_authority_neighborhood


DETENTION = "Vendor Credit Memos/Ball Detention Credits"
DNP = "DO NOT PAY"


def doc(text: str, *, file_name: str = "_Ball_6363143_08082026.pdf"):
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
        "bc_context": {},
    }


def ex(route: str, text: str, fingerprint: str):
    row = doc(text, file_name=f"example_{fingerprint}.pdf")
    row.update(
        {
            "fingerprint": fingerprint,
            "route_path": route,
            "label_source": "accounting_temp",
            "active": True,
            "split": "train",
            "raw_text_excerpt": text,
        }
    )
    return row


def test_reversal_phrase_is_route_neutral_exception_feature():
    features = semantic_features(
        doc(
            "Credit memo for the detention charge. "
            "Reversing this credit memo as per the request in the email below."
        )
    )
    assert "credit_document" in features
    assert "detention" in features
    assert "reversal_or_void" in features


def test_reversal_matching_example_scores_above_ordinary_transaction():
    current = doc(
        "Credit memo for detention. Reversing this credit memo as requested."
    )
    reversal = ex(
        DNP,
        "Credit memo for detention. Reversing this credit memo as requested.",
        "reversal",
    )
    ordinary = ex(
        DETENTION,
        "Credit memo for detention charge on shipment.",
        "ordinary",
    )
    assert feature_similarity(current, reversal)["score"] > feature_similarity(current, ordinary)["score"]


def test_exceptional_reversal_cannot_earn_from_ordinary_detention_consensus():
    current = doc(
        "Credit memo for the detention charge. "
        "Reversing this credit memo as per the request in the email below."
    )
    rows = [
        ex(DETENTION, "Credit memo for detention charge on shipment.", f"d{i}")
        for i in range(5)
    ]
    result = summarize_authority_neighborhood(
        document=current,
        proposed_route=DETENTION,
        train_examples=rows,
    )
    assert result["exceptional_workflow_features"] == ["reversal_or_void"]
    assert result["exception_mismatch_support_count"] >= 3
    assert result["exception_support_count"] == 0
    assert result["authority_ready"] is False


def test_exceptional_reversal_can_earn_only_from_exception_matched_human_support():
    current = doc(
        "Credit memo for detention. Reversing this credit memo as requested."
    )
    rows = [
        ex(
            DNP,
            "Credit memo for detention. Reversing this credit memo as requested.",
            f"r{i}",
        )
        for i in range(4)
    ] + [
        ex(DETENTION, "Credit memo for detention charge on shipment.", "ordinary")
    ]
    result = summarize_authority_neighborhood(
        document=current,
        proposed_route=DNP,
        train_examples=rows,
    )
    assert result["exception_support_count"] >= 3
    assert result["exception_support_ready"] is True
    assert result["authority_ready"] is True
