from __future__ import annotations

import ast
import inspect
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
INTAKE = (
    BACKEND
    / "services"
    / "document_bytes_intake_service.py"
)
RETIRED_AUDIT = (
    BACKEND
    / "tests"
    / ("audit_" + "shim_substitution.py")
)

REMOVED_SERVER_IMPORTS = {
    "compute_ap_normalized_fields":
        "services.document_intel_helpers",
    "compute_ap_validation":
        "services.ap_computation",
}


def parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_retired_audit_module_is_absent():
    assert not RETIRED_AUDIT.exists()


def test_unused_direct_server_imports_are_absent():
    imported = set()

    for node in parse(SERVER).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)

    assert not (set(REMOVED_SERVER_IMPORTS) & imported)


def test_canonical_owner_definitions_are_preserved():
    from services import (
        ap_computation,
        document_intel_helpers,
    )

    owners = {
        "compute_ap_normalized_fields":
            document_intel_helpers.compute_ap_normalized_fields,
        "compute_ap_validation":
            ap_computation.compute_ap_validation,
    }

    for name, owner in owners.items():
        assert callable(owner), name
        assert not inspect.iscoroutinefunction(owner), name


def test_bytes_intake_keeps_canonical_imports():
    tree = parse(INTAKE)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "intake_document_from_bytes"
    )
    imports = {}

    for node in ast.walk(function):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module

    assert imports.get(
        "compute_ap_normalized_fields"
    ) == "services.document_intel_helpers"
    assert imports.get(
        "compute_ap_validation"
    ) == "services.ap_computation"


def test_no_production_server_surface_dependencies():
    violations = []
    removed = set(REMOVED_SERVER_IMPORTS)

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

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                for alias in node.names:
                    if alias.name == "*" or alias.name in removed:
                        violations.append(
                            f"{path}:{node.lineno}: import {alias.name}"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr in removed
            ):
                violations.append(
                    f"{path}:{node.lineno}: "
                    f"{node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(sorted(set(violations)))


def test_no_executable_python_dependency_on_retired_audit():
    token = "audit_" + "shim_substitution"
    violations = []

    for path in BACKEND.rglob("*.py"):
        if path == Path(__file__) or "__pycache__" in path.parts:
            continue

        try:
            tree = parse(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        docstrings = set()

        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)

            if not (isinstance(body, list) and body):
                continue

            first = body[0]

            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(first.value)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if token in alias.name:
                        violations.append(
                            f"{path}:{node.lineno}: import {alias.name}"
                        )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""

                if token in module:
                    violations.append(
                        f"{path}:{node.lineno}: from {module}"
                    )

                for alias in node.names:
                    if token in alias.name:
                        violations.append(
                            f"{path}:{node.lineno}: import {alias.name}"
                        )

            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and token in node.value
                and node not in docstrings
            ):
                violations.append(
                    f"{path}:{node.lineno}: runtime string"
                )

    assert not violations, "\n".join(sorted(set(violations)))


def test_server_line_count_is_monotonic():
    count = sum(
        1
        for _ in SERVER.open("r", encoding="utf-8")
    )
    assert count <= 1650
