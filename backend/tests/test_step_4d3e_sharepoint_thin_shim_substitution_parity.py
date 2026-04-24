"""
Phase 3 Step 4d.3e — sharepoint_service Thin-Shim Substitution Parity Suite

Substitutes the final Class 2 helper in
`services/document_handlers.py::intake_document_from_bytes`'s lazy
import block from `server` to its authoritative home
`services.sharepoint_service`:

- upload_to_sharepoint_with_routing

Unlike the pure re-exports migrated in 4d.3a–d, this helper is a
**THIN_SHIM**. `server.upload_to_sharepoint_with_routing` at
server.py:357 is a 4-line `async def` that forwards all 5 parameters to
`services.sharepoint_service.upload_to_sharepoint_with_routing`. The shim
and the implementation are DISTINCT Python objects by design; object-
identity (`is`) would correctly fail. The parity shape here mirrors
4c.2/4c.3 (Tier-2/Tier-3 shim substitution): AST + structural + signature-
forwarding invariants.

Structural milestone asserted: after 4d.3e, the lazy
`from server import (...)` tuple inside intake contains only underscore-
prefixed server-private helpers (zero public Class 2 helpers remaining).

Eight probe classes form the acceptance gate:

1. AST-level import source for the intake binding.
2. Binding-target: intake's binding resolves via services.sharepoint_service.
3. THIN_SHIM structural invariant (server shim remains a 4-line delegator).
4. Server shim retained (external callers undisturbed).
5. Lazy block shrunk + structural milestone (zero public helpers remain).
6. Call-site byte parity.
7. 4c.2 family-sibling invariant: create_sharing_link binding still holds.
8. Live surface + audit gate no-op.
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

INTAKE_FUNC_NAME = "intake_document_from_bytes"
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "http://localhost:8001"
).rstrip("/")

SYMBOL = "upload_to_sharepoint_with_routing"
CANONICAL_MODULE = "services.sharepoint_service"


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
    def test_intake_imports_from_sharepoint_service(self):
        intake = _intake_func_node()
        import_sources = {}
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_sources[alias.name] = node.module
        assert SYMBOL in import_sources, (
            f"{SYMBOL} not imported anywhere inside {INTAKE_FUNC_NAME}"
        )
        assert import_sources[SYMBOL] == CANONICAL_MODULE, (
            f"{SYMBOL} imported from {import_sources[SYMBOL]!r}, "
            f"expected {CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 2. Binding-target: intake binding resolves through the canonical module
# ---------------------------------------------------------------------------
class TestBindingTarget:
    def test_canonical_module_exposes_symbol(self):
        """
        The canonical module must expose the symbol as an awaitable
        callable (i.e., a coroutine function). This confirms the target
        of the new import line is the real implementation, not a missing
        attribute.
        """
        from services import sharepoint_service
        obj = getattr(sharepoint_service, SYMBOL, None)
        assert obj is not None, (
            f"{CANONICAL_MODULE}.{SYMBOL} does not exist — "
            "cannot be the authoritative target"
        )
        assert callable(obj), (
            f"{CANONICAL_MODULE}.{SYMBOL} is not callable"
        )
        assert inspect.iscoroutinefunction(obj), (
            f"{CANONICAL_MODULE}.{SYMBOL} is not an async def; "
            "4d.3e premise violated"
        )


# ---------------------------------------------------------------------------
# 3. THIN_SHIM structural invariant (server.py shim is a 4-line delegator)
# ---------------------------------------------------------------------------
class TestServerShimStructurallyIntact:
    def test_server_shim_is_async_def_callable(self):
        import server
        shim = getattr(server, SYMBOL)
        assert callable(shim), f"server.{SYMBOL} is not callable"
        assert inspect.iscoroutinefunction(shim), (
            f"server.{SYMBOL} is no longer an async def — THIN_SHIM "
            "structure broken"
        )

    def test_server_shim_body_exactly_one_return_and_one_importfrom(self):
        """
        THIN_SHIM structural probe: the shim body contains exactly
        1 reachable `return` statement and exactly 1 local `ImportFrom`.
        """
        import server
        shim = getattr(server, SYMBOL)
        src = inspect.getsource(shim)
        tree = ast.parse(src)
        fn = tree.body[0]
        returns = [s for s in fn.body if isinstance(s, ast.Return)]
        imports = [s for s in fn.body if isinstance(s, ast.ImportFrom)]
        assert len(returns) == 1, (
            f"server.{SYMBOL} expected exactly 1 reachable return, "
            f"got {len(returns)} — THIN_SHIM structure drifted"
        )
        assert len(imports) == 1, (
            f"server.{SYMBOL} expected exactly 1 local ImportFrom, "
            f"got {len(imports)} — THIN_SHIM structure drifted"
        )
        assert imports[0].module == CANONICAL_MODULE, (
            f"server.{SYMBOL} local ImportFrom targets "
            f"{imports[0].module!r}, expected {CANONICAL_MODULE!r}"
        )
        imported_names = [alias.name for alias in imports[0].names]
        assert SYMBOL in imported_names, (
            f"server.{SYMBOL} local ImportFrom does not import "
            f"{SYMBOL} — delegation target mismatch"
        )

    def test_server_shim_signature_matches_canonical(self):
        """
        Signature-forwarding parity: server shim's parameters
        match services.sharepoint_service.upload_to_sharepoint_with_routing
        parameter-for-parameter (name, default, kind).
        """
        import server
        from services import sharepoint_service
        shim_sig = inspect.signature(getattr(server, SYMBOL))
        canonical_sig = inspect.signature(
            getattr(sharepoint_service, SYMBOL)
        )
        assert shim_sig == canonical_sig, (
            f"server.{SYMBOL} signature {shim_sig} does not match "
            f"{CANONICAL_MODULE}.{SYMBOL} signature {canonical_sig} — "
            "THIN_SHIM signature parity broken"
        )


# ---------------------------------------------------------------------------
# 4. Server shim retained (external callers undisturbed)
# ---------------------------------------------------------------------------
class TestServerShimRetained:
    def test_server_still_exposes_symbol(self):
        import server
        assert hasattr(server, SYMBOL), (
            f"server.{SYMBOL} no longer importable"
        )

    def test_server_py_source_contains_shim_definition(self):
        """
        Belt-and-suspenders: server.py still defines the async shim
        with the exact signature header used as the anchor for
        external-caller compatibility.
        """
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        assert (
            "async def upload_to_sharepoint_with_routing(\n"
            "    file_content: bytes,\n"
            "    file_name: str,\n"
            "    doc: Dict[str, Any],\n"
            "    freight_direction: Optional[str] = None,\n"
            "    is_international: bool = False\n"
            ") -> Dict[str, Any]:"
        ) in srv_src, (
            "server.py shim definition drifted"
        )


# ---------------------------------------------------------------------------
# 5. Lazy block shrunk + structural milestone
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d3e_symbol(self):
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        assert SYMBOL not in listed, (
            f"{SYMBOL} still listed in `from server import (...)` block"
        )

    def test_new_4d3e_import_line_present(self):
        src = _intake_func_source()
        assert (
            "from services.sharepoint_service import "
            "upload_to_sharepoint_with_routing"
        ) in src, "4d.3e direct-import line missing from intake body"

    def test_structural_milestone_only_server_private_helpers_remain(self):
        """
        Structural milestone: after 4d.3e, the lazy `from server import`
        tuple contains ONLY underscore-prefixed (server-private) helpers.
        No public Class 2 helpers should remain.
        """
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        assert listed, (
            "lazy `from server import (...)` tuple empty — expected the "
            "7 Class 3 server-private helpers"
        )
        public_remaining = {n for n in listed if not n.startswith("_")}
        assert not public_remaining, (
            f"Public helpers still in lazy tuple post-4d.3e: "
            f"{sorted(public_remaining)}. Expected only underscore-"
            "prefixed private helpers."
        )


# ---------------------------------------------------------------------------
# 6. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_use_site_intact(self):
        """The existing intake use-site `await upload_to_sharepoint_with_routing(`
        must still appear in the body."""
        src = _intake_func_source()
        assert "await upload_to_sharepoint_with_routing(" in src, (
            "use-site drift: `await upload_to_sharepoint_with_routing(` "
            "no longer present in intake body"
        )


# ---------------------------------------------------------------------------
# 7. 4c.2 family-sibling invariant (create_sharing_link binding still holds)
# ---------------------------------------------------------------------------
class TestCreateSharingLinkSiblingInvariant:
    """
    Regression guard: pulling upload_to_sharepoint_with_routing from
    services.sharepoint_service must not disturb the earlier 4c.2
    migration of create_sharing_link from the same module.
    """

    def test_intake_still_imports_create_sharing_link_from_sharepoint_service(self):
        """AST-level guard: the 4c.2 direct-import line is byte-intact."""
        src = _intake_func_source()
        assert (
            "from services.sharepoint_service import create_sharing_link"
        ) in src, (
            "4c.2 create_sharing_link direct-import line drifted or removed"
        )

    def test_intake_create_sharing_link_source_is_sharepoint_service(self):
        """AST-walk confirms create_sharing_link is imported from the
        canonical module only — never from server."""
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "create_sharing_link":
                        assert node.module == CANONICAL_MODULE, (
                            f"create_sharing_link imported from "
                            f"{node.module!r}, expected "
                            f"{CANONICAL_MODULE!r} (4c.2 invariant)"
                        )

    def test_server_create_sharing_link_is_thin_shim(self):
        """
        server.create_sharing_link must still be a THIN_SHIM that
        delegates to services.sharepoint_service.create_sharing_link
        (the 4c.2 contract). Same structural probe shape as used for
        upload_to_sharepoint_with_routing above.
        """
        import server
        shim = getattr(server, "create_sharing_link")
        assert callable(shim), "server.create_sharing_link not callable"
        assert inspect.iscoroutinefunction(shim), (
            "server.create_sharing_link no longer an async def — "
            "4c.2 invariant regressed"
        )
        src = inspect.getsource(shim)
        tree = ast.parse(src)
        fn = tree.body[0]
        returns = [s for s in fn.body if isinstance(s, ast.Return)]
        imports = [s for s in fn.body if isinstance(s, ast.ImportFrom)]
        assert len(returns) == 1 and len(imports) == 1, (
            "server.create_sharing_link shim structure drifted — "
            "4c.2 invariant regressed"
        )
        assert imports[0].module == CANONICAL_MODULE, (
            f"server.create_sharing_link now delegates to "
            f"{imports[0].module!r}, expected {CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 8. Live surface + audit gate no-op
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
