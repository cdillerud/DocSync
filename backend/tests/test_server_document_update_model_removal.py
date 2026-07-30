# Guardrails for removal of the duplicate server DocumentUpdate model.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
ROUTER_PATH = BACKEND_DIR / "routers" / "documents.py"
EXPECTED_SERVER_MAX = 2978

EXPECTED_FIELDS = {
    "document_type",
    "bc_record_type",
    "bc_record_id",
    "bc_document_no",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _model_fields(node: ast.ClassDef):
    return {
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
    }


def test_duplicate_server_document_update_model_is_absent():
    models = [
        node
        for node in _tree(SERVER_PATH).body
        if isinstance(node, ast.ClassDef)
        and node.name == "DocumentUpdate"
    ]

    assert not models


def test_documents_router_owns_document_update_model():
    tree = _tree(ROUTER_PATH)
    models = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "DocumentUpdate"
    ]

    assert len(models) == 1
    assert _model_fields(models[0]) == EXPECTED_FIELDS


def test_router_document_update_model_is_used_by_write_route():
    tree = _tree(ROUTER_PATH)
    consumers = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue

        annotated = any(
            isinstance(arg.annotation, ast.Name)
            and arg.annotation.id == "DocumentUpdate"
            for arg in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
        )

        if not annotated:
            continue

        methods = set()

        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
            ):
                continue

            methods.add(decorator.func.attr.lower())

        consumers.append((node.name, methods))

    assert consumers
    assert any(
        methods & {"put", "patch", "post"}
        for _name, methods in consumers
    )


def test_no_production_module_uses_server_document_update():
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue

        try:
            tree = _tree(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        if path == SERVER_PATH:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == "DocumentUpdate"
                ):
                    violations.append(
                        "server.py loads DocumentUpdate "
                        f"at line {node.lineno}"
                    )

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
                    if alias.name == "DocumentUpdate":
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)} "
                            "imports DocumentUpdate from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in server_aliases
                and node.attr == "DocumentUpdate"
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.DocumentUpdate"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_server_line_count_is_monotonic():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
