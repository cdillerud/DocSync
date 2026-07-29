# Guardrails for removal of the dead server batch-revalidation handler.

from __future__ import annotations

import ast
import inspect
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
EXPECTED_SERVER_MIN = 3422
EXPECTED_SERVER_MAX = 3058


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


def test_server_duplicate_is_absent():
    names = _top_level_names(SERVER_PATH)
    assert "batch_revalidate_documents" not in names


def test_authoritative_service_remains_complete():
    path = (
        BACKEND_DIR
        / "services"
        / "document_batch_revalidate_service.py"
    )
    assert "batch_revalidate_documents" in _top_level_names(path)


def test_handler_facade_exports_authoritative_function():
    from services import document_handlers
    from services import document_batch_revalidate_service

    assert (
        document_handlers.batch_revalidate_documents
        is
        document_batch_revalidate_service.batch_revalidate_documents
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
        == "/api/documents/batch-revalidate"
        and "POST" in getattr(route, "methods", set())
    ]

    assert len(matches) == 1
    assert (
        matches[0].endpoint
        is document_handlers.batch_revalidate_documents
    )


def test_no_production_module_imports_duplicate_from_server():
    target = "batch_revalidate_documents"
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue

        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8")
            )
        except (SyntaxError, UnicodeDecodeError):
            continue

        if path == SERVER_PATH:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == target
                ):
                    violations.append(
                        f"server.py loads {target} "
                        f"at line {node.lineno}"
                    )
            continue

        aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        aliases.add(alias.asname or "server")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
                and any(
                    alias.name == target
                    for alias in node.names
                )
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"imports {target} from server"
                )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr == target
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.{target}"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_server_line_count_matches_cleanup_band():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )
    assert total <= EXPECTED_SERVER_MAX


def test_authoritative_signature_is_stable():
    from services.document_batch_revalidate_service import (
        batch_revalidate_documents,
    )

    assert list(
        inspect.signature(
            batch_revalidate_documents
        ).parameters
    ) == [
        "doc_types",
        "limit",
        "skip_completed",
        "background_tasks",
    ]
