"""
Phase 3 Step 4d.4a — `_derive_workflow_status` THIN_SHIM Substitution Parity Suite

Substitutes the intake binding of `_derive_workflow_status` from `server`
(which is already a 4-line COMPATIBILITY WRAPPER / THIN_SHIM at
server.py:2403–2406) to the authoritative home
`services.classification_helpers.derive_workflow_status`.

Naming drift note: the authoritative function is named
`derive_workflow_status` (no underscore); the intake call-sites use
`_derive_workflow_status` (underscore-prefixed) to match server's shim
name. The new import line therefore uses
``from services.classification_helpers import derive_workflow_status
as _derive_workflow_status`` — the `as` alias is load-bearing for
call-site byte parity.

Nine probe classes form the acceptance gate:

1. AST-level import source (targets services.classification_helpers).
2. AST-level alias preservation (imported = derive_workflow_status,
   bound = _derive_workflow_status).
3. THIN_SHIM structural invariant on server.py:2403 shim.
4. Signature-forwarding parity.
5. Server shim retained (external callers undisturbed).
6. Lazy block shrunk + new 4d.4a direct-import line present.
7. Call-site byte parity + local `_derive_workflow_status_simple`
   untouched (fence against name confusion).
8. 4c.2 family-sibling invariant: classify_document_type binding holds +
   set of names pulled from services.classification_helpers equals
   exactly {classify_document_type, derive_workflow_status}.
9. Authoritative body byte-identical (golden-hash of
   services.classification_helpers.derive_workflow_status source).
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

AUTHORITATIVE_NAME = "derive_workflow_status"
BOUND_NAME = "_derive_workflow_status"
CANONICAL_MODULE = "services.classification_helpers"

# Golden hash captured immediately before the 4d.4a edit.
# Verifies services.classification_helpers.derive_workflow_status body
# remained byte-identical to its pre-step state.
DERIVE_WORKFLOW_STATUS_PRE_4D4A_SHA256 = (
    "baab629e6a2eba917ca29b4e415e7ab54608a8d780e2d400d5637e8ad7b18d68"
)
DERIVE_WORKFLOW_STATUS_PRE_4D4A_LEN = 667


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
    def test_intake_imports_derive_workflow_status_from_classification_helpers(self):
        """
        An ImportFrom targeting services.classification_helpers must
        import `derive_workflow_status` (the authoritative name, not the
        underscored name).
        """
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                imported = [alias.name for alias in node.names]
                if AUTHORITATIVE_NAME in imported:
                    return  # found it
        raise AssertionError(
            f"No `from {CANONICAL_MODULE} import {AUTHORITATIVE_NAME}` "
            "found in intake body"
        )


# ---------------------------------------------------------------------------
# 2. AST-level alias preservation
# ---------------------------------------------------------------------------
class TestAliasPreservation:
    def test_import_uses_as_alias_to_preserve_local_name(self):
        """
        The ImportFrom must contain an alias mapping `derive_workflow_status
        -> _derive_workflow_status` so the existing call-sites inside
        intake remain byte-identical.
        """
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                for alias in node.names:
                    if alias.name == AUTHORITATIVE_NAME \
                            and alias.asname == BOUND_NAME:
                        return  # correct alias found
        raise AssertionError(
            f"Alias `{AUTHORITATIVE_NAME} as {BOUND_NAME}` not found "
            f"in intake body's import from {CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 3. THIN_SHIM structural invariant on server.py shim
# ---------------------------------------------------------------------------
class TestServerShimStructurallyIntact:
    def test_server_shim_is_sync_def_callable(self):
        import server
        shim = getattr(server, BOUND_NAME)
        assert callable(shim), f"server.{BOUND_NAME} is not callable"
        assert not inspect.iscoroutinefunction(shim), (
            f"server.{BOUND_NAME} unexpectedly became an async def"
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
            f"server.{BOUND_NAME} expected exactly 1 reachable return, "
            f"got {len(returns)}"
        )
        assert len(imports) == 1, (
            f"server.{BOUND_NAME} expected exactly 1 local ImportFrom, "
            f"got {len(imports)}"
        )
        assert imports[0].module == CANONICAL_MODULE, (
            f"server.{BOUND_NAME} local ImportFrom targets "
            f"{imports[0].module!r}, expected {CANONICAL_MODULE!r}"
        )
        imported_names = [alias.name for alias in imports[0].names]
        assert AUTHORITATIVE_NAME in imported_names, (
            f"server.{BOUND_NAME} local ImportFrom does not import "
            f"{AUTHORITATIVE_NAME}"
        )


# ---------------------------------------------------------------------------
# 4. Signature-forwarding parity
# ---------------------------------------------------------------------------
class TestSignatureForwardingParity:
    def test_shim_signature_matches_authoritative(self):
        import server
        from services import classification_helpers
        shim_sig = inspect.signature(getattr(server, BOUND_NAME))
        canonical_sig = inspect.signature(
            getattr(classification_helpers, AUTHORITATIVE_NAME)
        )
        assert shim_sig == canonical_sig, (
            f"server.{BOUND_NAME} signature {shim_sig} does not match "
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} signature "
            f"{canonical_sig}"
        )


# ---------------------------------------------------------------------------
# 5. Server shim retained (external callers undisturbed)
# ---------------------------------------------------------------------------
class TestServerShimRetained:
    def test_server_still_exposes_bound_name(self):
        import server
        assert hasattr(server, BOUND_NAME), (
            f"server.{BOUND_NAME} no longer importable"
        )


# ---------------------------------------------------------------------------
# 6. Lazy block shrunk + new direct-import line present
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
            f"{BOUND_NAME} still listed in `from server import (...)` block"
        )

    def test_new_4d4a_import_line_with_alias_present(self):
        src = _intake_func_source()
        assert (
            "from services.classification_helpers import "
            "derive_workflow_status as _derive_workflow_status"
        ) in src, "4d.4a direct-import line (with alias) missing"

    def test_lazy_tuple_now_six_private_helpers(self):
        """
        Post-4d.4a structural check: `_derive_workflow_status` has been
        REMOVED from the ``from server import (...)`` tuple.

        Note: originally this asserted ``len == 6`` as a cumulative-count
        proxy; rewritten to a name-removal invariant so the probe remains
        valid as subsequent carve-outs continue to shrink the tuple.
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
        assert "_derive_workflow_status" not in private_only, (
            f"Expected `_derive_workflow_status` removed from lazy tuple after "
            f"Step 4d.4a, got {sorted(private_only)}"
        )


# ---------------------------------------------------------------------------
# 7. Call-site byte parity + _derive_workflow_status_simple fence
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_use_site_intact(self):
        """The 3-arg use-site must still appear in the intake body."""
        src = _intake_func_source()
        assert (
            "_derive_workflow_status(final_status, doc_type_value, decision)"
        ) in src, "4d.4a call-site byte-drift"

    def test_derive_workflow_status_simple_still_defined_locally(self):
        """
        Fence against name confusion: the local 2-arg helper
        `_derive_workflow_status_simple` in document_handlers.py must
        remain unchanged and NOT be conflated with the migrated
        3-arg helper.
        """
        from services import document_handlers
        assert hasattr(document_handlers, "_derive_workflow_status_simple"), (
            "_derive_workflow_status_simple no longer defined in "
            "document_handlers — out-of-scope fence violated"
        )
        local_fn = document_handlers._derive_workflow_status_simple
        sig = inspect.signature(local_fn)
        assert len(sig.parameters) == 2, (
            f"_derive_workflow_status_simple signature drifted: "
            f"expected 2 params, got {len(sig.parameters)}"
        )


# ---------------------------------------------------------------------------
# 8. 4c.2 family-sibling invariant (classify_document_type)
# ---------------------------------------------------------------------------
class TestClassifyDocumentTypeSiblingInvariant:
    def test_intake_still_imports_classify_document_type_from_canonical(self):
        src = _intake_func_source()
        assert (
            "from services.classification_helpers import classify_document_type"
        ) in src, (
            "4c.2 classify_document_type direct-import line drifted"
        )

    def test_ast_union_of_names_from_canonical_is_exactly_expected(self):
        """
        Walk the intake body, collect every ImportFrom whose module is
        services.classification_helpers, and assert the union of
        imported names is EXACTLY
        {classify_document_type, derive_workflow_status}.
        """
        intake = _intake_func_node()
        pulled = set()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                for alias in node.names:
                    pulled.add(alias.name)
        expected = {"classify_document_type", "derive_workflow_status"}
        assert pulled == expected, (
            f"Intake pulls {pulled!r} from {CANONICAL_MODULE}, "
            f"expected exactly {expected!r}"
        )


# ---------------------------------------------------------------------------
# 9. Authoritative body byte-identical (golden hash)
# ---------------------------------------------------------------------------
class TestAuthoritativeBodyByteIdentical:
    def test_derive_workflow_status_source_unchanged(self):
        from services.classification_helpers import derive_workflow_status
        src = inspect.getsource(derive_workflow_status)
        assert len(src) == DERIVE_WORKFLOW_STATUS_PRE_4D4A_LEN, (
            f"services.classification_helpers.derive_workflow_status "
            f"source length drifted: {len(src)} vs pre-4d.4a "
            f"{DERIVE_WORKFLOW_STATUS_PRE_4D4A_LEN}"
        )
        h = hashlib.sha256(src.encode()).hexdigest()
        assert h == DERIVE_WORKFLOW_STATUS_PRE_4D4A_SHA256, (
            "services.classification_helpers.derive_workflow_status "
            "body drifted (SHA-256 mismatch against golden pre-4d.4a "
            "baseline). Expected: "
            f"{DERIVE_WORKFLOW_STATUS_PRE_4D4A_SHA256}, got: {h}"
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
            f"audit script exited {result.returncode}: {result.stderr[-400:]}"
        )
        out = result.stdout
        assert "Passing (8):" in out, (
            f"audit not reporting 8 passing helpers:\n{out[-600:]}"
        )
        assert "Failing (0):" in out, (
            f"audit reports some failing helpers:\n{out[-600:]}"
        )
