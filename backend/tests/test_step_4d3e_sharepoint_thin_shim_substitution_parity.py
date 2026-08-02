# Current SharePoint helper ownership regression tests.

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
INTAKE_PATH = BACKEND_ROOT / "services" / "document_bytes_intake_service.py"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
SHAREPOINT_HELPERS = {"upload_to_sharepoint", "ensure_sharepoint_folder_exists", "upload_to_sharepoint_with_routing", "create_sharing_link"}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _intake_node():
    matches = [node for node in ast.walk(_tree(INTAKE_PATH)) if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes"]
    assert len(matches) == 1
    return matches[0]


def test_canonical_sharepoint_helpers_exist():
    from services import sharepoint_service
    for name in SHAREPOINT_HELPERS:
        helper = getattr(sharepoint_service, name)
        assert callable(helper)
        assert inspect.iscoroutinefunction(helper)


def test_authoritative_intake_uses_canonical_sharepoint_imports():
    imports = {}
    for node in ast.walk(_intake_node()):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports[alias.name] = node.module
    assert imports.get("create_sharing_link") == "services.sharepoint_service"
    assert imports.get("upload_to_sharepoint_with_routing") == "services.sharepoint_service"


def test_server_sharepoint_wrappers_are_absent():
    import server
    definitions = {node.name for node in _tree(BACKEND_ROOT / "server.py").body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not (SHAREPOINT_HELPERS & definitions)
    for name in SHAREPOINT_HELPERS:
        assert not hasattr(server, name)


def test_no_production_server_sharepoint_wrapper_references():
    violations = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if path.name == "server.py" or "tests" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            tree = _tree(path)
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
                    if alias.name == "*" or alias.name in SHAREPOINT_HELPERS:
                        violations.append(f"{path}:{node.lineno}:import {alias.name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases and node.attr in SHAREPOINT_HELPERS:
                violations.append(f"{path}:{node.lineno}:{node.value.id}.{node.attr}")
    assert not violations, "\n".join(sorted(set(violations)))


def test_document_intake_route_present():
    try:
        response = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
    except Exception as exc:
        pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
    assert response.status_code == 200
    assert "/api/documents/intake" in response.json().get("paths", {})
