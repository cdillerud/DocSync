# Guardrails for removal of duplicate server reference-intelligence handlers.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
ROUTER_PATH = (
    BACKEND_DIR
    / "routers"
    / "reference_intelligence.py"
)
HANDLERS_PATH = (
    BACKEND_DIR
    / "services"
    / "reference_intelligence_handlers.py"
)
BATCH_PATH = (
    BACKEND_DIR
    / "services"
    / "reference_batch_resolve_service.py"
)
EXPECTED_SERVER_MAX = 2541

HANDLER_NAMES = {
    "resolve_bc_reference",
    "resolve_document_reference",
    "resolve_document_intelligence",
    "get_document_reference_intelligence",
    "trigger_auto_resolve",
    "get_matching_debug",
    "rerun_matching_with_diagnostics",
}

BATCH_NAMES = {
    "batch_auto_resolve",
}

REMOVED_NAMES = HANDLER_NAMES | BATCH_NAMES

EXPECTED_ROUTES = {
    "/api/bc/resolve-reference":
        "resolve_bc_reference",
    "/api/documents/{doc_id}/resolve-reference":
        "resolve_document_reference",
    "/api/documents/{doc_id}/resolve-intelligence":
        "resolve_document_intelligence",
    "/api/documents/{doc_id}/reference-intelligence":
        "get_document_reference_intelligence",
    "/api/documents/{doc_id}/auto-resolve":
        "trigger_auto_resolve",
    "/api/admin/batch-auto-resolve":
        "batch_auto_resolve",
    "/api/documents/{doc_id}/matching-debug":
        "get_matching_debug",
    "/api/documents/{doc_id}/matching-debug/rerun":
        "rerun_matching_with_diagnostics",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _function_names(path: Path):
    return {
        node.name
        for node in _tree(path).body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }


def test_duplicate_server_handlers_are_absent():
    assert not (
        REMOVED_NAMES
        & _function_names(SERVER_PATH)
    )


def test_no_production_module_imports_removed_server_surface():
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.parts or path == SERVER_PATH:
            continue

        try:
            tree = _tree(path)
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
                for alias in node.names:
                    if (
                        alias.name in REMOVED_NAMES
                        or alias.name == "*"
                    ):
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)}:"
                            f"{node.lineno} imports "
                            f"{alias.name} from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in server_aliases
                and node.attr in REMOVED_NAMES
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)}:"
                    f"{node.lineno} references "
                    f"{node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_authoritative_service_functions_are_preserved():
    assert HANDLER_NAMES <= _function_names(
        HANDLERS_PATH
    )
    assert BATCH_NAMES <= _function_names(
        BATCH_PATH
    )


def test_router_imports_authoritative_service_functions():
    imports = set()
    batch_imports = set()

    for node in _tree(ROUTER_PATH).body:
        if not (
            isinstance(node, ast.FunctionDef)
            and node.name == "register_server_routes"
        ):
            continue

        for inner in ast.walk(node):
            if not isinstance(inner, ast.ImportFrom):
                continue

            if (
                inner.module
                == "services.reference_intelligence_handlers"
            ):
                imports.update(
                    alias.name
                    for alias in inner.names
                )

            elif (
                inner.module
                == "services.reference_batch_resolve_service"
            ):
                batch_imports.update(
                    alias.name
                    for alias in inner.names
                )

    assert HANDLER_NAMES <= imports
    assert BATCH_NAMES <= batch_imports


def test_router_paths_target_authoritative_names():
    registered = {}

    for node in ast.walk(_tree(ROUTER_PATH)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_api_route"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and isinstance(node.args[1], ast.Name)
        ):
            continue

        registered[node.args[0].value] = (
            node.args[1].id
        )

    for path, endpoint in EXPECTED_ROUTES.items():
        assert registered.get(path) == endpoint


def test_server_line_count_is_monotonic():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
