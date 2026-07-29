# Parity guardrails for removal of the dead server preview duplicate.

from __future__ import annotations

import ast
import inspect
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
EXPECTED_SERVER_MIN = 3548
EXPECTED_SERVER_MAX = 3568


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    return {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }


def test_server_preview_duplicate_is_absent():
    names = _top_level_names(SERVER_PATH)

    assert "DryRunPreviewRequest" not in names
    assert "preview_post_to_bc" not in names
    assert "process_incoming_email" in names


def test_authoritative_preview_service_remains_complete():
    service_path = (
        BACKEND_DIR
        / "services"
        / "document_preview_service.py"
    )
    names = _top_level_names(service_path)

    assert "DryRunPreviewRequest" in names
    assert "preview_post_to_bc" in names


def test_handler_facade_exports_authoritative_objects():
    from services import document_handlers
    from services import document_preview_service

    assert (
        document_handlers.DryRunPreviewRequest
        is document_preview_service.DryRunPreviewRequest
    )
    assert (
        document_handlers.preview_post_to_bc
        is document_preview_service.preview_post_to_bc
    )


def test_router_registration_uses_authoritative_handler(
    monkeypatch,
):
    from fastapi import FastAPI
    import routers.documents as documents
    from services import document_handlers

    monkeypatch.setattr(
        documents,
        "_routes_registered",
        False,
    )

    app = FastAPI()
    documents.register_server_routes(app)

    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/documents/{doc_id}/preview-post"
        and "POST" in getattr(route, "methods", set())
    ]

    assert len(matches) == 1
    assert (
        matches[0].endpoint
        is document_handlers.preview_post_to_bc
    )


def test_no_production_module_imports_preview_from_server():
    targets = {
        "DryRunPreviewRequest",
        "preview_post_to_bc",
    }
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if path == SERVER_PATH:
            continue

        if "tests" in path.parts:
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        server_aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        server_aliases.add(
                            alias.asname or "server"
                        )

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                imported = {
                    alias.name
                    for alias in node.names
                } & targets

                if imported:
                    violations.append(
                        f"{path.relative_to(BACKEND_DIR)} "
                        f"imports {sorted(imported)} from server"
                    )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in server_aliases
                and node.attr in targets
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(sorted(set(violations)))


def test_server_line_count_matches_cleanup_band():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX


def test_preview_service_signature_is_stable():
    from services.document_preview_service import (
        preview_post_to_bc,
    )

    signature = inspect.signature(preview_post_to_bc)

    assert list(signature.parameters) == [
        "doc_id",
        "request",
    ]
