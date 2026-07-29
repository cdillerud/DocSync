# Guardrails for removal of dead server reprocess wrappers.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
SERVICE_PATH = (
    BACKEND_DIR
    / "services"
    / "document_reprocess_service.py"
)
EXPECTED_SERVER_MIN = 3205
EXPECTED_SERVER_MAX = 3225


def _top_level_names(path: Path):
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


def test_dead_server_reprocess_wrappers_are_absent():
    names = _top_level_names(SERVER_PATH)

    assert "reprocess_document" not in names
    assert "_reprocess_document_inner" not in names
    assert "process_incoming_email" in names


def test_authoritative_reprocess_service_is_complete():
    names = _top_level_names(SERVICE_PATH)

    assert "reprocess_document" in names
    assert "reprocess_document_inner" in names


def test_service_private_alias_is_preserved():
    from services import document_reprocess_service

    assert (
        document_reprocess_service._reprocess_document_inner
        is document_reprocess_service.reprocess_document_inner
    )


def test_handler_facade_uses_authoritative_service():
    from services import document_handlers
    from services import document_reprocess_service

    assert (
        document_handlers.reprocess_document
        is document_reprocess_service.reprocess_document
    )


def test_server_captured_retry_uses_authoritative_inner():
    tree = ast.parse(
        SERVER_PATH.read_text(encoding="utf-8")
    )

    imports = 0
    injections = 0

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            == "services.document_reprocess_service"
        ):
            imports += sum(
                1
                for alias in node.names
                if alias.name
                == "reprocess_document_inner"
            )

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id
            == "start_captured_retry_tasks"
        ):
            for keyword in node.keywords:
                if (
                    keyword.arg
                    == "_reprocess_document_inner"
                    and isinstance(
                        keyword.value,
                        ast.Name,
                    )
                    and keyword.value.id
                    == "reprocess_document_inner"
                ):
                    injections += 1

    assert imports == 1
    assert injections == 1


def test_route_uses_authoritative_reprocess_handler(
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

    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/documents/{doc_id}/reprocess"
        and "POST" in getattr(route, "methods", set())
    ]

    assert len(routes) == 1
    assert (
        routes[0].endpoint
        is document_handlers.reprocess_document
    )


def test_reclassify_remains_optional_query_parameter(
    monkeypatch,
):
    from fastapi import FastAPI
    import routers.documents as documents

    monkeypatch.setattr(
        documents,
        "_routes_registered",
        False,
    )

    app = FastAPI()
    documents.register_server_routes(app)
    operation = app.openapi()["paths"][
        "/api/documents/{doc_id}/reprocess"
    ]["post"]

    parameters = {
        item["name"]: item
        for item in operation["parameters"]
    }

    assert parameters["doc_id"]["in"] == "path"
    assert parameters["reclassify"]["in"] == "query"
    assert parameters["reclassify"]["required"] is False
    assert (
        parameters["reclassify"]["schema"]["default"]
        is False
    )


def test_no_production_module_imports_removed_server_wrappers():
    targets = {
        "reprocess_document",
        "_reprocess_document_inner",
    }
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
                    and node.id in targets
                ):
                    violations.append(
                        f"server.py loads {node.id} "
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
            ):
                for alias in node.names:
                    if alias.name in targets:
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)} "
                            f"imports {alias.name} from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr in targets
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.{node.attr}"
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

    assert EXPECTED_SERVER_MIN <= total <= EXPECTED_SERVER_MAX
