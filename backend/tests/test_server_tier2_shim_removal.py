from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
MAX_SERVER_LINES = 1674

REMOVED = {
    "classify_document_with_ai": (
        "services/document_intel_helpers.py",
        "classify_document_with_ai",
    ),
    "make_automation_decision": (
        "services/document_intel_helpers.py",
        "make_automation_decision",
    ),
    "classify_document_type": (
        "services/classification_helpers.py",
        "classify_document_type",
    ),
}


def parse(path: Path):
    return ast.parse(
        path.read_text(encoding="utf-8")
    )


def top_level_names(path: Path):
    return {
        node.name
        for node in parse(path).body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }


def test_removed_tier_two_server_shims_are_absent():
    assert not (
        set(REMOVED)
        & top_level_names(SERVER)
    )


def test_canonical_owner_definitions_are_present():
    for name, (
        relative_path,
        owner_name,
    ) in REMOVED.items():
        owner_path = BACKEND / relative_path
        assert owner_path.exists(), name
        assert (
            owner_name
            in top_level_names(owner_path)
        ), name


def test_on_document_ingested_has_one_private_decision_call():
    tree = parse(SERVER)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "on_document_ingested"
    )

    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "_make_automation_decision"
    ]

    assert len(calls) == 1


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
        except (
            SyntaxError,
            UnicodeDecodeError,
        ):
            continue

        aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        aliases.add(
                            alias.asname or "server"
                        )

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                for alias in node.names:
                    if (
                        alias.name == "*"
                        or alias.name in REMOVED
                    ):
                        violations.append(
                            f"{path.relative_to(BACKEND)}:"
                            f"{node.lineno} imports "
                            f"{alias.name}"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(
                    node.value,
                    ast.Name,
                )
                and node.value.id in aliases
                and node.attr in REMOVED
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:"
                    f"{node.lineno} references "
                    f"{node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_audit_no_longer_lists_tier_two_helpers():
    audit = (
        BACKEND
        / "tests"
        / "audit_shim_substitution.py"
    ).read_text(encoding="utf-8")

    for name in REMOVED:
        assert (
            f'("{name}",'
            not in audit
        )


def test_server_line_count_is_monotonic():
    count = sum(
        1
        for _ in SERVER.open(
            "r",
            encoding="utf-8",
        )
    )

    assert count <= MAX_SERVER_LINES
