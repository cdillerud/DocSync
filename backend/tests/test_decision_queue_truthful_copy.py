from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
FRONTEND_ROOT = ROOT / "frontend"


def _bulk_classify_source() -> str:
    path = BACKEND_ROOT / "routers" / "documents.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "bulk_classify_documents"
        ):
            return ast.get_source_segment(source, node) or ""

    raise AssertionError(
        "bulk_classify_documents function not found"
    )


def test_bulk_classify_documentation_is_document_scoped():
    source = _bulk_classify_source()

    normalized_source = " ".join(
        source.replace('"', "").split()
    )

    assert (
        "This endpoint does not create a sender-wide routing rule."
        in normalized_source
    )
    assert (
        "Sender-wide routing rules require"
        in normalized_source
    )
    assert (
        "are not created by this endpoint"
        in normalized_source
    )

    assert (
        "teaches the system this sender's"
        not in normalized_source
    )
    assert (
        "writes a sender routing override rule"
        not in normalized_source
    )


def test_bulk_classify_does_not_request_sender_wide_learning():
    source = _bulk_classify_source()

    assert "learn_sender_rule=True" not in source


def test_decision_queue_intro_matches_document_scoped_routing():
    path = (
        FRONTEND_ROOT
        / "src"
        / "pages"
        / "HumanDecisionQueuePage.js"
    )
    source = path.read_text(encoding="utf-8")

    assert "Wrong routing lane" in source
    assert (
        "routing changes apply only to the current document"
        in source
    )

    assert "Wrong mailbox" not in source
    assert (
        "Every routing decision becomes reusable AI guidance"
        not in source
    )


def test_classification_dialog_retains_scope_warning():
    path = (
        FRONTEND_ROOT
        / "src"
        / "components"
        / "DecisionQueueClassificationDialog.js"
    )
    source = path.read_text(encoding="utf-8")

    assert "This changes only this document." in source
    assert (
        "It does not create a sender-wide routing rule"
        in source
    )
