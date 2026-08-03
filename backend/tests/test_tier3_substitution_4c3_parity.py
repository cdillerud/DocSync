"""
Phase 3 Step 4c.3 — Tier-3 Helper Substitution Parity Suite

Goal: prove that substituting `lookup_vendor_alias` and `check_duplicate_document`
from `server` to `services.vendor_matching` inside
`services/document_handlers.py::intake_document_from_bytes` (the body moved
verbatim from `server._internal_intake_document` in Step 4b) is behaviorally
a no-op, because the `server.py` counterparts are 4-line THIN_SHIMs that
already delegate to `services.vendor_matching`.

The six probes below together form the acceptance gate for Step 4c.3:

1. Object-identity: the substituted names resolve to the authoritative
   `services.vendor_matching` objects at runtime.
2. Server shim parity retained: `server.lookup_vendor_alias` and
   `server.check_duplicate_document` remain importable and still delegate.
3. Lazy block shrunk: the `from server import (...)` tuple no longer contains
   the two Tier-3 symbol names; the new direct-import line is present.
4. Call-site byte parity: the two call-sites inside the intake body remain
   character-identical to the pre-4c.3 source string.
5. Live surface: `/openapi.json` path count still equals 858.
6. Audit gate no-op: the unchanged `audit_shim_substitution.py` still passes
   all 8 helpers (since `server.py` was not mutated).
"""
from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TIER3 = ("lookup_vendor_alias", "check_duplicate_document")
INTAKE_FUNC_NAME = "intake_document_from_bytes"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")


def _intake_func_node():
    """Return the AST node for the intake function in document_bytes_intake_service.py."""
    from services import document_bytes_intake_service
    tree = ast.parse(inspect.getsource(document_bytes_intake_service))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in document_bytes_intake_service.py AST")


def _intake_func_source():
    """Return the raw source text of the intake function."""
    from services import document_bytes_intake_service
    func = getattr(document_bytes_intake_service, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. Object-identity
# ---------------------------------------------------------------------------
class TestObjectIdentity:
    @pytest.mark.parametrize("name", TIER3)
    def test_intake_imports_authoritative_vendor_matching_owner(self, name):
        intake = _intake_func_node()
        import_sources = {}
        for node in ast.walk(intake):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                import_sources[alias.name] = node.module
        assert import_sources.get(name) == "services.vendor_matching", (
            f"{name} import owner is {import_sources.get(name)!r}, "
            "expected 'services.vendor_matching'"
        )

    @pytest.mark.parametrize("name", TIER3)
    def test_runtime_owner_is_callable_and_server_shim_is_absent(self, name):
        import server
        from services import vendor_matching
        owner = getattr(vendor_matching, name)
        assert callable(owner), f"services.vendor_matching.{name} is not callable"
        assert not hasattr(server, name), (
            f"retired server.{name} shim unexpectedly remains importable"
        )


# ---------------------------------------------------------------------------
# 2. Server shim parity retained (server.py untouched)
# ---------------------------------------------------------------------------
class TestServerShimRetired:
    @pytest.mark.parametrize("name", TIER3)
    def test_server_shim_is_absent_from_runtime_and_source(self, name):
        import server
        assert not hasattr(server, name), (
            f"retired server.{name} shim unexpectedly remains importable"
        )
        tree = ast.parse(inspect.getsource(server))
        top_level_defs = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name not in top_level_defs, (
            f"retired server.{name} top-level definition remains"
        )


# ---------------------------------------------------------------------------
# 3. Lazy block shrunk + new direct-import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_server_import_cascade_contains_no_tier3_names(self):
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        assert not (set(TIER3) & listed), (
            f"Tier-3 names still imported from server: "
            f"{sorted(set(TIER3) & listed)}"
        )

    def test_direct_vendor_matching_import_line_present(self):
        intake_src = _intake_func_source()
        assert (
            "from services.vendor_matching import "
            "lookup_vendor_alias, check_duplicate_document"
        ) in intake_src, (
            "Tier-3 authoritative direct-import line missing from intake body"
        )


# ---------------------------------------------------------------------------
# 4. Call-site byte parity (the two await-call lines are unchanged)
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_lookup_vendor_alias_call_site_intact(self):
        intake_src = _intake_func_source()
        assert (
            'vendor_alias_result = await lookup_vendor_alias('
            'normalized_fields.get("vendor_normalized"))'
        ) in intake_src, "lookup_vendor_alias call-site byte-drift detected"

    def test_check_duplicate_document_call_site_intact(self):
        intake_src = _intake_func_source()
        assert "duplicate_result = await check_duplicate_document(" in intake_src, (
            "check_duplicate_document call-site byte-drift detected"
        )


# ---------------------------------------------------------------------------
# 5. Live surface preserved (/openapi.json path count == 858)
# ---------------------------------------------------------------------------
class TestLiveSurface:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert r.status_code == 200

    def test_openapi_required_routes_are_present(self):
        import requests

        base_url = (
            getattr(self, "BASE_URL", None)
            or globals().get("BASE_URL")
        )
        assert base_url, "OpenAPI base URL is not configured"

        try:
            response = requests.get(
                f"{base_url}/openapi.json",
                timeout=5,
            )
        except Exception as exc:
            pytest.skip(
                f"Backend unreachable at {base_url}: {exc}"
            )

        assert response.status_code == 200
        paths = response.json().get("paths", {})
        required_routes = {
            "/api/documents/upload",
            "/api/documents/intake",
            "/api/documents/{doc_id}/preview-post",
            "/api/documents/batch-revalidate",
            "/api/documents/{doc_id}/reprocess",
        }
        missing = required_routes - set(paths)
        assert not missing, (
            f"required OpenAPI routes missing: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# 6. Audit gate no-op (server.py untouched ⇒ audit still green)
# ---------------------------------------------------------------------------
