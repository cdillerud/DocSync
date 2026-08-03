from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
INTAKE = BACKEND / "services" / "document_bytes_intake_service.py"
MAX_SERVER_LINES = 1656

REMOVED = {
    "lookup_vendor_alias",
    "check_duplicate_document",
}


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def top_level_names(path: Path):
    return {
        node.name
        for node in parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def intake_imports():
    function = next(
        node
        for node in ast.walk(parse(INTAKE))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "intake_document_from_bytes"
    )
    imports = {}
    for node in ast.walk(function):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module
    return imports


def test_removed_tier_three_server_shims_are_absent():
    import server

    assert not (REMOVED & top_level_names(SERVER))
    for name in REMOVED:
        assert not hasattr(server, name), name


def test_canonical_vendor_matching_owners_are_preserved():
    from services import vendor_matching

    for name in REMOVED:
        owner = getattr(vendor_matching, name)
        assert callable(owner), name
        assert inspect.iscoroutinefunction(owner), name


def test_authoritative_intake_uses_canonical_tier_three_imports():
    imports = intake_imports()
    for name in REMOVED:
        assert imports.get(name) == "services.vendor_matching", name


def test_no_production_module_imports_removed_server_shims():
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
                    if alias.name == "*" or alias.name in REMOVED:
                        violations.append(
                            f"{path.relative_to(BACKEND)}:"
                            f"{node.lineno} imports {alias.name}"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr in REMOVED
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:"
                    f"{node.lineno} references "
                    f"{node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(sorted(set(violations)))
def test_server_line_count_is_monotonic():
    count = sum(1 for _ in SERVER.open("r", encoding="utf-8"))
    assert count <= MAX_SERVER_LINES
