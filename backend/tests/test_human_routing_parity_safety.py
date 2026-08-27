from pathlib import Path


def test_human_routing_correction_never_auto_creates_reusable_rule():
    source = Path("routers/human_routing_review.py").read_text(encoding="utf-8")

    assert "record_correction(" not in source
    assert "routing_feedback_candidates" in source
    assert '"status": "pending_admin_promotion"' in source
    assert '"reusable_rule_created": False' in source
    assert "Single-document routing decisions do not auto-create reusable vendor rules" in source


def test_human_routing_preserves_document_specific_audit():
    source = Path("routers/human_routing_review.py").read_text(encoding="utf-8")

    required = (
        '"previous_folder": profile["current_folder"]',
        '"suggested_folder": suggested_folder',
        '"selected_folder": selected_folder',
        '"human_routing_decision": decision_record',
        "await db.human_routing_decisions.insert_one(decision_record)",
    )
    for token in required:
        assert token in source, token
