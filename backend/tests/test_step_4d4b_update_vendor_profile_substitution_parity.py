"""
Phase 3 Step 4d.4b — `_update_vendor_profile_incremental` THIN_SHIM Parity Suite

Substitutes the intake binding of `_update_vendor_profile_incremental`
from `server` (a 10-line async COMPATIBILITY WRAPPER at server.py:2409)
to the authoritative home
`workflows.ap_invoice.rules.vendor_profile.update_vendor_profile_incremental`.

Naming drift note: authoritative function is
`update_vendor_profile_incremental` (no underscore); intake call-site
uses `_update_vendor_profile_incremental`. The `as` alias is load-bearing.

Nine probe classes:
1. AST-level import source.
2. AST-level alias preservation.
3. THIN_SHIM structural invariant on server.py:2409 shim.
4. Signature-forwarding parity.
5. Server shim retained.
6. Lazy block shrunk + structural milestone (5 private helpers remain).
7. Call-site byte parity.
8. Sibling-landscape acknowledgment (canonical module exports exactly
   one public function — no prior migrations from this module exist).
9. Authoritative body byte-identical (golden SHA-256).
"""
from __future__ import annotations

import ast
import hashlib
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

INTAKE_FUNC_NAME = "intake_document_from_bytes"
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "http://localhost:8001"
).rstrip("/")

AUTHORITATIVE_NAME = "update_vendor_profile_incremental"
BOUND_NAME = "_update_vendor_profile_incremental"
CANONICAL_MODULE = "workflows.ap_invoice.rules.vendor_profile"

# Golden hash captured immediately before the 4d.4b edit.
UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_SHA256 = (
    "c16571c17462f5e1d2b692c2e7e85760380bd3126dacedf582e1f85f737c4b35"
)
UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_LEN = 3105


def _intake_func_node():
    from services import document_handlers
    tree = ast.parse(inspect.getsource(document_handlers))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in AST")


def _intake_func_source() -> str:
    from services import document_handlers
    func = getattr(document_handlers, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. AST-level import source
# ---------------------------------------------------------------------------
class TestASTImportSource:
    def test_intake_imports_from_canonical_module(self):
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                imported = [alias.name for alias in node.names]
                if AUTHORITATIVE_NAME in imported:
                    return
        raise AssertionError(
            f"No `from {CANONICAL_MODULE} import {AUTHORITATIVE_NAME}` "
            "found in intake body"
        )


# ---------------------------------------------------------------------------
# 2. AST-level alias preservation
# ---------------------------------------------------------------------------
class TestAliasPreservation:
    def test_import_uses_as_alias(self):
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                for alias in node.names:
                    if alias.name == AUTHORITATIVE_NAME \
                            and alias.asname == BOUND_NAME:
                        return
        raise AssertionError(
            f"Alias `{AUTHORITATIVE_NAME} as {BOUND_NAME}` not found "
            f"in intake body's import from {CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 3. THIN_SHIM structural invariant on server.py:2409 shim
# ---------------------------------------------------------------------------
class TestServerShimStructurallyIntact:
    def test_server_shim_is_async_def(self):
        import server
        shim = getattr(server, BOUND_NAME)
        assert callable(shim), f"server.{BOUND_NAME} not callable"
        assert inspect.iscoroutinefunction(shim), (
            f"server.{BOUND_NAME} is no longer an async def"
        )

    def test_server_shim_body_exactly_one_return_and_one_importfrom(self):
        import server
        shim = getattr(server, BOUND_NAME)
        src = inspect.getsource(shim)
        tree = ast.parse(src)
        fn = tree.body[0]
        returns = [s for s in fn.body if isinstance(s, ast.Return)]
        imports = [s for s in fn.body if isinstance(s, ast.ImportFrom)]
        assert len(returns) == 1, (
            f"server.{BOUND_NAME} expected exactly 1 return, got {len(returns)}"
        )
        assert len(imports) == 1, (
            f"server.{BOUND_NAME} expected exactly 1 local ImportFrom, "
            f"got {len(imports)}"
        )
        assert imports[0].module == CANONICAL_MODULE, (
            f"server.{BOUND_NAME} local ImportFrom targets "
            f"{imports[0].module!r}, expected {CANONICAL_MODULE!r}"
        )
        imported = [alias.name for alias in imports[0].names]
        assert AUTHORITATIVE_NAME in imported, (
            f"server.{BOUND_NAME} local ImportFrom does not import "
            f"{AUTHORITATIVE_NAME}"
        )


# ---------------------------------------------------------------------------
# 4. Signature-forwarding parity
# ---------------------------------------------------------------------------
class TestSignatureForwardingParity:
    def test_shim_signature_matches_authoritative(self):
        """
        Positional-forwarding parity: compare parameter names/order only.
        The shim is a 10-line COMPATIBILITY WRAPPER at server.py:2409 whose
        annotation style (e.g. `update_data: dict` vs `Dict[str, Any]`,
        missing `-> None`) predates 4d.4b and is not in-scope for this
        substitution edit. What matters for forwarding correctness is that
        positional argument names and order match canonical.
        """
        import server
        from workflows.ap_invoice.rules import vendor_profile
        shim_params = list(
            inspect.signature(getattr(server, BOUND_NAME)).parameters
        )
        canonical_params = list(
            inspect.signature(
                getattr(vendor_profile, AUTHORITATIVE_NAME)
            ).parameters
        )
        assert shim_params == canonical_params, (
            f"server.{BOUND_NAME} params {shim_params} do not match "
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} params "
            f"{canonical_params}"
        )


# ---------------------------------------------------------------------------
# 5. Server shim retained
# ---------------------------------------------------------------------------
class TestServerShimRetained:
    def test_server_still_exposes_bound_name(self):
        import server
        assert hasattr(server, BOUND_NAME), (
            f"server.{BOUND_NAME} no longer importable"
        )


# ---------------------------------------------------------------------------
# 6. Lazy block shrunk + structural milestone (5 private helpers remain)
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_bound_name(self):
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        assert BOUND_NAME not in listed, (
            f"{BOUND_NAME} still listed in `from server import` block"
        )

    def test_new_4d4b_import_line_with_alias_present(self):
        src = _intake_func_source()
        assert (
            "from workflows.ap_invoice.rules.vendor_profile import (\n"
            "        update_vendor_profile_incremental as "
            "_update_vendor_profile_incremental,\n"
            "    )"
        ) in src, "4d.4b direct-import line (with alias) missing"

    def test_lazy_tuple_now_five_private_helpers(self):
        """Post-4d.4b: `_update_vendor_profile_incremental` has been REMOVED
        from the ``from server import (...)`` tuple.

        Note: originally asserted ``len == 5`` as a cumulative-count proxy;
        rewritten to a name-removal invariant so the probe remains valid as
        subsequent carve-outs continue to shrink the tuple.
        """
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        private_only = {n for n in listed if n.startswith("_")}
        public_leaked = listed - private_only
        assert not public_leaked, (
            f"Public helpers leaked back into lazy tuple: {public_leaked}"
        )
        assert "_update_vendor_profile_incremental" not in private_only, (
            f"Expected `_update_vendor_profile_incremental` removed from lazy "
            f"tuple after Step 4d.4b, got {sorted(private_only)}"
        )


# ---------------------------------------------------------------------------
# 7. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_use_site_intact(self):
        src = _intake_func_source()
        assert (
            "_update_vendor_profile_incremental("
            "db, doc_id, vendor_name, update_data, final_status)"
        ) in src, "4d.4b call-site byte-drift"

    def test_non_intake_direct_import_line_735_untouched(self):
        """
        Fence: the pre-existing direct import at document_handlers.py:735
        (in a non-intake code path, using the non-underscored name) must
        remain exactly as it was.
        """
        dh_src = (
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert (
            "from workflows.ap_invoice.rules.vendor_profile "
            "import update_vendor_profile_incremental\n"
            "            await update_vendor_profile_incremental("
        ) in dh_src, (
            "Pre-existing non-intake direct import at "
            "document_handlers.py:735 drifted — out-of-scope fence violated"
        )


# ---------------------------------------------------------------------------
# 8. Sibling-landscape acknowledgment
# ---------------------------------------------------------------------------
class TestSiblingLandscapeAcknowledgment:
    """
    Forward-contract guard: the canonical module
    `workflows.ap_invoice.rules.vendor_profile` currently exports exactly
    one public function. If a future change adds another public function
    without reviewing sibling-invariance implications for `document_handlers`
    imports, this probe fails loudly.
    """
    def test_canonical_module_exports_exactly_one_public_function(self):
        from workflows.ap_invoice.rules import vendor_profile
        public_functions = {
            name for name in dir(vendor_profile)
            if not name.startswith("_")
            and callable(getattr(vendor_profile, name))
            and inspect.isfunction(getattr(vendor_profile, name))
            and getattr(vendor_profile, name).__module__
            == CANONICAL_MODULE
        }
        expected = {AUTHORITATIVE_NAME}
        assert public_functions == expected, (
            f"Sibling-landscape drifted. Canonical module public-function "
            f"export set is now {public_functions!r}, expected {expected!r}. "
            "Any new public function requires sibling-invariance review "
            "before migrating additional Phase 3 sub-steps from this module."
        )


# ---------------------------------------------------------------------------
# 9. Authoritative body byte-identical (golden hash)
# ---------------------------------------------------------------------------
class TestAuthoritativeBodyByteIdentical:
    def test_update_vendor_profile_incremental_source_unchanged(self):
        from workflows.ap_invoice.rules.vendor_profile import (
            update_vendor_profile_incremental,
        )
        src = inspect.getsource(update_vendor_profile_incremental)
        assert len(src) == UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_LEN, (
            f"Authoritative source length drifted: {len(src)} vs "
            f"pre-4d.4b {UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_LEN}"
        )
        h = hashlib.sha256(src.encode()).hexdigest()
        assert h == UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_SHA256, (
            f"Authoritative body SHA-256 mismatch. Expected "
            f"{UPDATE_VENDOR_PROFILE_INCR_PRE_4D4B_SHA256}, got {h}"
        )


# ---------------------------------------------------------------------------
# Standard: live surface + audit gate no-op
# ---------------------------------------------------------------------------
class TestLiveSurfaceAndAudit:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert r.status_code == 200

    def test_openapi_path_count_858(self):
        try:
            paths = (
                requests.get(f"{BASE_URL}/openapi.json", timeout=5)
                .json()
                .get("paths", {})
            )
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert len(paths) == 858, (
            f"openapi path count drift: got {len(paths)}, expected 858"
        )

    def test_audit_script_reports_eight_passing(self):
        script = BACKEND_ROOT / "tests" / "audit_shim_substitution.py"
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"audit exited {result.returncode}: {result.stderr[-400:]}"
        )
        out = result.stdout
        assert "Passing (8):" in out, f"audit tail:\n{out[-600:]}"
        assert "Failing (0):" in out, f"audit tail:\n{out[-600:]}"
