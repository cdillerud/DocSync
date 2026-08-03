"""Historical-test contract for delegated application shutdown ownership.

This is intentionally a non-collected helper. The existing historical test
invokes ``assert_shutdown_ownership_contract`` so the modernization replaces
one stale assertion without changing the repository's collected-test count.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MAIN = BACKEND / "main.py"
SERVER = BACKEND / "server.py"
LIFECYCLE = BACKEND / "services" / "lifecycle_service.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _function(tree: ast.AST, name: str):
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1, (
        f"expected exactly one {name}; found {len(matches)}"
    )
    return matches[0]


def assert_shutdown_ownership_contract() -> None:
    """Assert the canonical delegated shutdown and shared-client contract."""
    main_tree = _parse(MAIN)
    server_tree = _parse(SERVER)
    lifecycle_tree = _parse(LIFECYCLE)

    main_shutdown = _function(main_tree, "shutdown")
    main_delegations = [
        item.value
        for item in ast.walk(main_shutdown)
        if isinstance(item, ast.Await)
        and isinstance(item.value, ast.Call)
        and isinstance(item.value.func, ast.Attribute)
        and item.value.func.attr == "shutdown_db_client"
        and isinstance(item.value.func.value, ast.Name)
        and item.value.func.value.id == "server"
    ]
    assert len(main_delegations) == 1, (
        "main.shutdown must await server.shutdown_db_client exactly once"
    )

    server_shutdown = _function(server_tree, "shutdown_db_client")
    lifecycle_delegations = [
        item.value
        for item in ast.walk(server_shutdown)
        if isinstance(item, ast.Await)
        and isinstance(item.value, ast.Call)
        and isinstance(item.value.func, ast.Name)
        and item.value.func.id == "shutdown_application"
    ]
    assert len(lifecycle_delegations) == 1, (
        "server.shutdown_db_client must await shutdown_application exactly once"
    )

    client_keywords = [
        keyword
        for keyword in lifecycle_delegations[0].keywords
        if keyword.arg == "client"
    ]
    assert len(client_keywords) == 1
    assert isinstance(client_keywords[0].value, ast.Name)
    assert client_keywords[0].value.id == "client", (
        "server.shutdown_db_client must pass its canonical client"
    )

    lifecycle_shutdown = _function(
        lifecycle_tree,
        "shutdown_application",
    )
    close_calls = [
        item
        for item in ast.walk(lifecycle_shutdown)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "close"
        and isinstance(item.func.value, ast.Name)
        and item.func.value.id == "client"
    ]
    assert len(close_calls) == 1, (
        "shutdown_application must retain exactly one client.close operation"
    )

    backend_path = str(BACKEND)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    server = importlib.import_module("server")
    database = importlib.import_module("database")
    assert server.client is database.client, (
        "server.client must be the canonical database.client object"
    )
