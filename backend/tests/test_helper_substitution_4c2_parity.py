# Current Tier-2 helper ownership regression tests.

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
INTAKE_PATH = BACKEND_DIR / "services" / "document_bytes_intake_service.py"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
TIER_2_HELPERS = [
    ("classify_document_with_ai", "services.document_intel_helpers"),
    ("make_automation_decision", "services.document_intel_helpers"),
    ("classify_document_type", "services.classification_helpers"),
]


def _intake_node():
    tree = ast.parse(INTAKE_PATH.read_text(encoding="utf-8"))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes"]
    assert len(matches) == 1
    return matches[0]


def test_current_intake_imports_remaining_tier_two_helpers():
    imports = {}
    for node in ast.walk(_intake_node()):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module
    for name, module in TIER_2_HELPERS:
        assert imports.get(name) == module
    assert imports.get("create_sharing_link") == "services.sharepoint_service"


def test_remaining_server_shims_match_canonical_signatures():
    import server
    from services import classification_helpers, document_intel_helpers
    owners = {
        "classify_document_with_ai": document_intel_helpers.classify_document_with_ai,
        "make_automation_decision": document_intel_helpers.make_automation_decision,
        "classify_document_type": classification_helpers.classify_document_type,
    }
    for name, owner in owners.items():
        shim = getattr(server, name)
        assert list(inspect.signature(shim).parameters) == list(inspect.signature(owner).parameters)
        assert inspect.iscoroutinefunction(shim) == inspect.iscoroutinefunction(owner)
    assert not hasattr(server, "create_sharing_link")


def test_shim_audit_reports_current_counts():
    script = BACKEND_DIR / "tests" / "audit_shim_substitution.py"
    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR)}
    tier = subprocess.run([sys.executable, str(script), "2"], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60)
    assert tier.returncode == 0, tier.stderr
    assert "Passing (3):" in tier.stdout
    assert "Failing (0):" in tier.stdout
    all_result = subprocess.run([sys.executable, str(script)], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60)
    assert all_result.returncode == 0, all_result.stderr
    assert "Passing (7):" in all_result.stdout
    assert "Failing (0):" in all_result.stdout
    assert "create_sharing_link" not in all_result.stdout


def test_document_handlers_facade_reexports_authoritative_intake():
    from services import document_bytes_intake_service, document_handlers
    assert document_handlers.intake_document_from_bytes is document_bytes_intake_service.intake_document_from_bytes


def test_document_intake_route_present():
    try:
        response = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
    except Exception as exc:
        pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
    assert response.status_code == 200
    assert "/api/documents/intake" in response.json().get("paths", {})
