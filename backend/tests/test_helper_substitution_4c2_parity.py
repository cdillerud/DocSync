# Post-cleanup Tier-2 ownership regression tests.

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
INTAKE_PATH = (
    BACKEND_DIR
    / "services"
    / "document_bytes_intake_service.py"
)
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "http://localhost:8001",
).rstrip("/")

REMOVED_TIER_2 = {
    "classify_document_with_ai",
    "make_automation_decision",
    "classify_document_type",
}

CANONICAL_OWNERS = {
    "classify_document_with_ai": (
        "services.document_intel_helpers",
        True,
    ),
    "make_automation_decision": (
        "services.document_intel_helpers",
        False,
    ),
    "classify_document_type": (
        "services.classification_helpers",
        True,
    ),
}


def _tree(path: Path):
    return ast.parse(
        path.read_text(encoding="utf-8")
    )


def _intake_node():
    matches = [
        node
        for node in ast.walk(_tree(INTAKE_PATH))
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "intake_document_from_bytes"
    ]

    assert len(matches) == 1
    return matches[0]


def _on_ingested_node():
    matches = [
        node
        for node in _tree(SERVER_PATH).body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "on_document_ingested"
    ]

    assert len(matches) == 1
    return matches[0]


def test_authoritative_intake_imports_all_tier_two_helpers():
    imports = {}

    for node in ast.walk(_intake_node()):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module

    for name, (
        module,
        _,
    ) in CANONICAL_OWNERS.items():
        assert imports.get(name) == module


def test_removed_server_tier_two_shims_are_absent():
    import server

    definitions = {
        node.name
        for node in _tree(SERVER_PATH).body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    assert not (
        REMOVED_TIER_2
        & definitions
    )

    for name in REMOVED_TIER_2:
        assert not hasattr(server, name), name


def test_canonical_owner_shapes_are_preserved():
    from services import (
        classification_helpers,
        document_intel_helpers,
    )

    owners = {
        "classify_document_with_ai":
            document_intel_helpers.classify_document_with_ai,
        "make_automation_decision":
            document_intel_helpers.make_automation_decision,
        "classify_document_type":
            classification_helpers.classify_document_type,
    }

    for name, owner in owners.items():
        expected_async = CANONICAL_OWNERS[name][1]
        assert callable(owner), name
        assert (
            inspect.iscoroutinefunction(owner)
            == expected_async
        ), name


def test_on_document_ingested_uses_private_canonical_alias():
    tree = _tree(SERVER_PATH)
    aliases = set()

    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            == "services.document_intel_helpers"
        ):
            for alias in node.names:
                if (
                    alias.name
                    == "make_automation_decision"
                ):
                    aliases.add(
                        alias.asname or alias.name
                    )

    assert aliases == {
        "_make_automation_decision"
    }

    calls = [
        node
        for node in ast.walk(_on_ingested_node())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "_make_automation_decision"
    ]

    assert len(calls) == 1


def test_shim_audit_reports_tier_two_removed():
    script = (
        BACKEND_DIR
        / "tests"
        / "audit_shim_substitution.py"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND_DIR),
    }

    tier = subprocess.run(
        [
            sys.executable,
            str(script),
            "2",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert tier.returncode == 0, tier.stderr
    assert "Passing (0):" in tier.stdout
    assert "Failing (0):" in tier.stdout

    all_result = subprocess.run(
        [
            sys.executable,
            str(script),
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert all_result.returncode == 0, all_result.stderr
    assert "Passing (4):" in all_result.stdout
    assert "Failing (0):" in all_result.stdout

    for name in REMOVED_TIER_2:
        assert name not in all_result.stdout


def test_document_handlers_facade_reexports_authoritative_intake():
    from services import (
        document_bytes_intake_service,
        document_handlers,
    )

    assert (
        document_handlers.intake_document_from_bytes
        is document_bytes_intake_service.intake_document_from_bytes
    )


def test_document_intake_route_present():
    try:
        response = requests.get(
            f"{BASE_URL}/openapi.json",
            timeout=5,
        )
    except Exception as exc:
        pytest.skip(
            f"Backend unreachable at {BASE_URL}: {exc}"
        )

    assert response.status_code == 200
    assert (
        "/api/documents/intake"
        in response.json().get("paths", {})
    )
