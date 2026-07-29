# Guardrails for dead server classification and resolution removal.

from __future__ import annotations

import ast
import inspect
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
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


def _learning_triggers(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    triggers = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue

        call = node.value

        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "record_document_learning"
        ):
            continue

        if len(call.args) >= 3 and isinstance(
            call.args[2],
            ast.Constant,
        ):
            triggers.append(call.args[2].value)

    return triggers


def test_dead_server_objects_are_absent():
    names = _top_level_names(SERVER_PATH)

    assert "classify_document" not in names
    assert "ResolveRequest" not in names
    assert "resolve_and_link_document" not in names

    assert "process_incoming_email" in names


def test_authoritative_services_remain_complete():
    classification = (
        BACKEND_DIR
        / "services"
        / "document_classification_service.py"
    )
    resolution = (
        BACKEND_DIR
        / "services"
        / "document_resolution_service.py"
    )

    assert "classify_document" in _top_level_names(
        classification
    )

    resolution_names = _top_level_names(resolution)

    assert "ResolveRequest" in resolution_names
    assert "resolve_and_link_document" in resolution_names


def test_learning_hooks_remain_intact():
    classification = (
        BACKEND_DIR
        / "services"
        / "document_classification_service.py"
    )
    resolution = (
        BACKEND_DIR
        / "services"
        / "document_resolution_service.py"
    )

    assert _learning_triggers(classification) == [
        "classification"
    ]
    assert _learning_triggers(resolution) == ["link"]


def test_handler_facade_exports_authoritative_objects():
    from services import document_handlers
    from services import document_classification_service
    from services import document_resolution_service

    assert (
        document_handlers.classify_document
        is document_classification_service.classify_document
    )
    assert (
        document_handlers.ResolveRequest
        is document_resolution_service.ResolveRequest
    )
    assert (
        document_handlers.resolve_and_link_document
        is document_resolution_service.resolve_and_link_document
    )


def test_route_registration_uses_authoritative_handlers(
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

    classify_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/documents/{doc_id}/classify"
        and "POST" in getattr(route, "methods", set())
    ]

    resolve_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/documents/{doc_id}/resolve"
        and "POST" in getattr(route, "methods", set())
    ]

    assert len(classify_routes) == 1
    assert len(resolve_routes) == 1

    assert (
        classify_routes[0].endpoint
        is document_handlers.classify_document
    )
    assert (
        resolve_routes[0].endpoint
        is document_handlers.resolve_and_link_document
    )


def test_resolve_annotation_uses_authoritative_model():
    from services import document_handlers

    signature = inspect.signature(
        document_handlers.resolve_and_link_document
    )

    assert (
        signature.parameters["resolve"].annotation
        is document_handlers.ResolveRequest
    )


def test_resolution_service_initializes_bc_entity_safely():
    path = (
        BACKEND_DIR
        / "services"
        / "document_resolution_service.py"
    )
    source = path.read_text(encoding="utf-8")

    default_position = source.find(
        'bc_entity = "salesOrders"'
    )
    conditional_position = source.find(
        "if not share_link and file_content:"
    )

    assert default_position >= 0
    assert conditional_position >= 0
    assert default_position < conditional_position


def test_no_production_module_imports_dead_server_objects():
    targets = {
        "classify_document",
        "ResolveRequest",
        "resolve_and_link_document",
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
