from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
DOCUMENTS = BACKEND / "routers" / "documents.py"
MAX_SERVER_LINES = 1749
CANDIDATE = "reset_document_retries"


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def definitions(path: Path):
    return [
        node
        for node in parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == CANDIDATE
    ]


def call_names(node):
    names = set()

    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue

        if isinstance(item.func, ast.Name):
            names.add(item.func.id)
            continue

        if isinstance(item.func, ast.Attribute):
            parts = []
            current = item.func

            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value

            if isinstance(current, ast.Name):
                parts.append(current.id)
                names.add(".".join(reversed(parts)))

    return names


def test_duplicate_server_handler_is_absent():
    assert definitions(SERVER) == []


def test_authoritative_router_handler_is_present_once():
    matches = definitions(DOCUMENTS)
    assert len(matches) == 1
    assert isinstance(matches[0], ast.AsyncFunctionDef)


def test_authoritative_route_contract_is_preserved():
    node = definitions(DOCUMENTS)[0]
    routes = []

    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            and decorator.func.attr == "post"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ):
            routes.append(
                (
                    decorator.func.attr.upper(),
                    decorator.args[0].value,
                )
            )

    assert routes == [
        (
            "POST",
            "/{doc_id}/reset-retries",
        )
    ]


def test_authoritative_semantics_are_preserved():
    node = definitions(DOCUMENTS)[0]

    assert {
        "db.hub_documents.find_one",
        "reset_retry_counter",
        "datetime.now",
        "db.hub_documents.update_one",
    } <= call_names(node)

    returned = [
        tuple(
            key.value
            if isinstance(key, ast.Constant)
            else None
            for key in item.value.keys
        )
        for item in ast.walk(node)
        if isinstance(item, ast.Return)
        and isinstance(item.value, ast.Dict)
    ]

    assert returned == [
        (
            "success",
            "message",
            "document_id",
            "retry_count",
        )
    ]


def test_no_production_module_imports_removed_server_handler():
    violations = []

    for path in BACKEND.rglob("*.py"):
        if (
            path == SERVER
            or "tests" in path.parts
            or "__pycache__" in path.parts
        ):
            continue

        try:
            tree = parse(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        aliases.add(alias.asname or "server")

            elif isinstance(node, ast.ImportFrom) and node.module == "server":
                for alias in node.names:
                    if alias.name in {CANDIDATE, "*"}:
                        violations.append(
                            f"{path.relative_to(BACKEND)}:"
                            f"{node.lineno} imports {alias.name}"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr == CANDIDATE
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:"
                    f"{node.lineno} references "
                    f"{node.value.id}.{CANDIDATE}"
                )

    assert not violations, "\n".join(sorted(set(violations)))


def test_server_line_count_is_monotonic():
    count = sum(
        1
        for _ in SERVER.open("r", encoding="utf-8")
    )

    assert count <= MAX_SERVER_LINES
