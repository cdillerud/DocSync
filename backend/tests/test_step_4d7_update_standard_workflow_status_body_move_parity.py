"""
Phase 3 Step 4d.7 — `_update_standard_workflow_status` Body-Move Parity Suite

Third TRUE body-bearing Class 3 carve-out. The largest body-move yet
(440 lines / 21,160 chars) and the first to bootstrap a new archetypal
package (``workflows/document_capture/``).

Pattern (per signed declaration):
1. Capture golden source of server._update_standard_workflow_status BEFORE
   the move (21,160 chars).
2. Move the body VERBATIM into a NEW module
   ``workflows.document_capture.rules.workflow_status`` as
   ``update_standard_workflow_status`` (public; underscore prefix dropped).
3. Leave a 4-statement delegating shim at server.py:1811 so existing
   imports continue to resolve.
4. Rewire the INTAKE call site only (`document_handlers.py:1565` lazy
   tuple) with alias preservation. The two non-intake call sites
   (``document_handlers.py:1079``, ``server.py:3646``) are explicitly
   preserved and continue to resolve via the shim.

``_build_vendor_resolution`` is explicitly out of scope.
``_attempt_llm_vendor_ranking`` is explicitly out of scope.

17 probes covering AST shape, byte-identity, shim integrity, package
bootstrap, prelude contract, reverse-arrow safety, and live surface.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import os
import subprocess
import sys
import textwrap
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

AUTHORITATIVE_NAME = "update_standard_workflow_status"
BOUND_NAME = "_update_standard_workflow_status"
CANONICAL_MODULE = "workflows.document_capture.rules.workflow_status"

# Golden captured immediately before the 4d.7 body move.
UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_SHA256 = (
    "21c2a1ca5418d0b54048c85841dd96e59b573e4827697709016ff9251f8dc7f2"
)
UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_LEN = 21160

# After 4d.7, the lazy `from server import (...)` tuple in
# intake_document_from_bytes should be exactly these 2 names.
EXPECTED_LAZY_TUPLE = {
    "_attempt_llm_vendor_ranking",
    "_build_vendor_resolution",
}

# Declared minimal prelude (per signed Step 4d.7 declaration §3.B).
ALLOWED_PRELUDE_IMPORT_FROMS = {
    ("datetime", frozenset({"datetime", "timezone"})),
    ("typing", frozenset({"Dict"})),
    ("database", frozenset({"db"})),
    ("workflows.core.engine",
        frozenset({"DocType", "WorkflowEngine", "WorkflowEvent"})),
    ("services.square9_workflow",
        frozenset({"Square9Stage", "validate_location_code"})),
    ("services.auto_post_service",
        frozenset({"attempt_auto_create_sales_order"})),
    ("services.business_central_service", frozenset({"get_bc_service"})),
    # Temporary reverse-arrow imports — explicitly approved by signed declaration.
    ("server",
        frozenset({"_run_pilot_enrichment", "AUTO_CREATE_SALES_ORDER_ENABLED"})),
}
ALLOWED_PRELUDE_PLAIN_IMPORTS = {"asyncio", "logging", "uuid"}

# The exact two reverse-arrow names approved by the declaration.
DECLARED_REVERSE_ARROW_NAMES = frozenset({
    "_run_pilot_enrichment",
    "AUTO_CREATE_SALES_ORDER_ENABLED",
})


def _intake_func_node():
    from services import document_handlers
    tree = ast.parse(inspect.getsource(document_handlers))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in document_handlers")


def _iter_importfroms(fn_node):
    for node in ast.walk(fn_node):
        if isinstance(node, ast.ImportFrom):
            yield node


# ---------------------------------------------------------------------------
# 1. AST-level import source
# ---------------------------------------------------------------------------
class TestASTImportSource:
    def test_intake_imports_from_canonical_module(self):
        fn = _intake_func_node()
        matches = [
            n for n in _iter_importfroms(fn)
            if n.module == CANONICAL_MODULE
            and any(alias.name == AUTHORITATIVE_NAME for alias in n.names)
        ]
        assert matches, (
            f"{INTAKE_FUNC_NAME} does not import {AUTHORITATIVE_NAME} "
            f"from {CANONICAL_MODULE}"
        )


# ---------------------------------------------------------------------------
# 2. AST-level alias preservation
# ---------------------------------------------------------------------------
class TestAliasPreservation:
    def test_import_uses_as_alias(self):
        fn = _intake_func_node()
        for n in _iter_importfroms(fn):
            if n.module != CANONICAL_MODULE:
                continue
            for alias in n.names:
                if alias.name == AUTHORITATIVE_NAME:
                    assert alias.asname == BOUND_NAME, (
                        f"expected `{AUTHORITATIVE_NAME} as {BOUND_NAME}`, "
                        f"got `{AUTHORITATIVE_NAME} as {alias.asname}`"
                    )
                    return
        raise AssertionError(
            f"no ImportFrom for {CANONICAL_MODULE}.{AUTHORITATIVE_NAME}"
        )


# ---------------------------------------------------------------------------
# 3. Lazy `from server` tuple — name-removal invariant
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_tuple_no_longer_lists_bound_name(self):
        fn = _intake_func_node()
        for n in _iter_importfroms(fn):
            if n.module == "server":
                names = {alias.name for alias in n.names}
                assert BOUND_NAME not in names, (
                    f"{BOUND_NAME} still in lazy tuple: {sorted(names)}"
                )

    def test_lazy_tuple_now_two_private_helpers(self):
        fn = _intake_func_node()
        server_imports = [n for n in _iter_importfroms(fn) if n.module == "server"]
        assert len(server_imports) == 1
        names = {alias.name for alias in server_imports[0].names}
        assert names == EXPECTED_LAZY_TUPLE, (
            f"expected lazy tuple == {sorted(EXPECTED_LAZY_TUPLE)}, "
            f"got {sorted(names)}"
        )

    def test_new_4d7_import_line_with_alias_present(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert (
            "from workflows.document_capture.rules.workflow_status import (\n"
            "        update_standard_workflow_status "
            "as _update_standard_workflow_status,\n"
            "    )"
        ) in handlers_src, "Step 4d.7 alias-import block missing"


# ---------------------------------------------------------------------------
# 4+5+6. server.py shim
# ---------------------------------------------------------------------------
def _server_shim_node():
    import server
    tree = ast.parse(inspect.getsource(server))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == BOUND_NAME:
            return node
    raise AssertionError(f"server.{BOUND_NAME} not found")


class TestServerShimStructurallyIntact:
    def test_server_shim_is_async_def(self):
        assert isinstance(_server_shim_node(), ast.AsyncFunctionDef)

    def test_server_shim_body_exactly_one_importfrom_and_one_return(self):
        node = _server_shim_node()
        executable = [
            s for s in node.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        kinds = [type(s).__name__ for s in executable]
        assert kinds == ["ImportFrom", "Return"], f"shim drift: {kinds}"


class TestServerShimRetained:
    def test_server_still_exposes_bound_name(self):
        import server
        assert hasattr(server, BOUND_NAME)


# ---------------------------------------------------------------------------
# 7. Positional-forwarding parity
# ---------------------------------------------------------------------------
class TestSignatureForwardingParity:
    def test_shim_params_match_canonical(self):
        import server
        from workflows.document_capture.rules import workflow_status as wf
        shim_params = list(
            inspect.signature(getattr(server, BOUND_NAME)).parameters
        )
        canonical_params = list(
            inspect.signature(getattr(wf, AUTHORITATIVE_NAME)).parameters
        )
        assert shim_params == canonical_params, (
            f"shim/canonical param mismatch: {shim_params} vs {canonical_params}"
        )


# ---------------------------------------------------------------------------
# 8. Authoritative function exists
# ---------------------------------------------------------------------------
class TestAuthoritativeExists:
    def test_authoritative_is_async_callable(self):
        from workflows.document_capture.rules import workflow_status as wf
        fn = getattr(wf, AUTHORITATIVE_NAME, None)
        assert fn is not None
        assert inspect.iscoroutinefunction(fn)
        assert fn.__module__ == CANONICAL_MODULE


# ---------------------------------------------------------------------------
# 9. Body byte-identical modulo def rename
# ---------------------------------------------------------------------------
class TestAuthoritativeBodyByteIdentical:
    def test_update_standard_workflow_status_source_matches_golden(self):
        from workflows.document_capture.rules import workflow_status as wf
        new_src = inspect.getsource(getattr(wf, AUTHORITATIVE_NAME))
        reverted = new_src.replace(
            f"async def {AUTHORITATIVE_NAME}(",
            f"async def {BOUND_NAME}(",
            1,
        )
        assert len(reverted) == UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_LEN, (
            f"length drift: got {len(reverted)}, "
            f"expected {UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_LEN}"
        )
        sha = hashlib.sha256(reverted.encode()).hexdigest()
        assert sha == UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_SHA256, (
            f"SHA drift: {sha}"
        )


# ---------------------------------------------------------------------------
# 10. Inner `async def handle_warehouse_validation_failure` survived
# ---------------------------------------------------------------------------
class TestInnerDefSurvived:
    def test_handle_warehouse_validation_failure_is_inner_def(self):
        from workflows.document_capture.rules import workflow_status as wf
        outer = getattr(wf, AUTHORITATIVE_NAME)
        outer_src = inspect.getsource(outer)
        outer_tree = ast.parse(textwrap.dedent(outer_src))
        outer_fn = outer_tree.body[0]
        assert isinstance(outer_fn, ast.AsyncFunctionDef)
        inner_names = {
            n.name for n in ast.walk(outer_fn)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n is not outer_fn
        }
        assert "handle_warehouse_validation_failure" in inner_names, (
            "inner closure `handle_warehouse_validation_failure` not preserved "
            f"after move; saw inners: {sorted(inner_names)}"
        )


# ---------------------------------------------------------------------------
# 11. Intake call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_use_site_intact(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert "await _update_standard_workflow_status(" in handlers_src


# ---------------------------------------------------------------------------
# 12. Non-intake call sites preserved unchanged
# ---------------------------------------------------------------------------
class TestNonIntakeCallSitesPreserved:
    def test_non_intake_handlers_call_site_intact(self):
        """Out-of-scope: document_handlers.py:~1079 uses
        `from server import _update_standard_workflow_status` directly,
        not the intake lazy tuple. It must still resolve via the shim."""
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert (
            "from server import _update_standard_workflow_status"
            in handlers_src
        ), "non-intake `from server import _update_standard_workflow_status` " \
           "lost — out of scope for 4d.7"

    def test_in_server_call_site_intact(self):
        """server.py:~3646 calls `_update_standard_workflow_status` from
        within server itself; the shim is what makes that resolve."""
        server_src = Path(BACKEND_ROOT / "server.py").read_text()
        assert "await _update_standard_workflow_status(" in server_src

    def test_server_shim_resolves(self):
        import server
        assert callable(server._update_standard_workflow_status)
        assert inspect.iscoroutinefunction(server._update_standard_workflow_status)


# ---------------------------------------------------------------------------
# 13. Reverse-arrow import safety — no circular import
# ---------------------------------------------------------------------------
class TestReverseArrowImportSafety:
    def test_canonical_then_server_imports_in_subprocess(self):
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            import workflows.document_capture.rules.workflow_status as wf
            import server
            assert hasattr(server, '_update_standard_workflow_status')
            assert hasattr(wf, 'update_standard_workflow_status')
            print('OK')
        """) % str(BACKEND_ROOT)
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert result.returncode == 0, (
            f"reverse-arrow load failed:\nstdout={result.stdout}\n"
            f"stderr={result.stderr[-600:]}"
        )
        assert "OK" in result.stdout

    def test_server_then_canonical_imports_in_subprocess(self):
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            import server
            import workflows.document_capture.rules.workflow_status as wf
            assert hasattr(server, '_update_standard_workflow_status')
            assert hasattr(wf, 'update_standard_workflow_status')
            print('OK')
        """) % str(BACKEND_ROOT)
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert result.returncode == 0, (
            f"reverse-arrow load failed:\nstdout={result.stdout}\n"
            f"stderr={result.stderr[-600:]}"
        )
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 14. Sibling-landscape acknowledgment
# ---------------------------------------------------------------------------
class TestSiblingLandscapeAcknowledgment:
    def test_ap_invoice_siblings_unchanged(self):
        from workflows.ap_invoice.rules import vendor_profile, workflow_status as ap_wf

        vp_publics = [
            n for n in dir(vendor_profile)
            if not n.startswith("_")
            and callable(getattr(vendor_profile, n, None))
            and getattr(getattr(vendor_profile, n), "__module__", "")
                == "workflows.ap_invoice.rules.vendor_profile"
        ]
        assert vp_publics == ["update_vendor_profile_incremental"], (
            f"AP vendor_profile sibling drift: {vp_publics}"
        )

        ap_wf_publics = [
            n for n in dir(ap_wf)
            if not n.startswith("_")
            and callable(getattr(ap_wf, n, None))
            and getattr(getattr(ap_wf, n), "__module__", "")
                == "workflows.ap_invoice.rules.workflow_status"
        ]
        assert ap_wf_publics == ["update_ap_workflow_status"], (
            f"AP workflow_status sibling drift: {ap_wf_publics}"
        )


# ---------------------------------------------------------------------------
# 15. New-module hygiene — exactly one public callable + prelude verbatim
# ---------------------------------------------------------------------------
class TestNewModuleHygiene:
    def test_new_module_exposes_exactly_one_public_callable(self):
        from workflows.document_capture.rules import workflow_status as wf
        publics = [
            n for n in dir(wf)
            if not n.startswith("_")
            and callable(getattr(wf, n, None))
            and getattr(getattr(wf, n), "__module__", "")
                == CANONICAL_MODULE
        ]
        assert publics == [AUTHORITATIVE_NAME], (
            f"unexpected publics in new module: {publics}"
        )

    def test_new_module_imports_match_declared_prelude(self):
        path = (
            BACKEND_ROOT / "workflows" / "document_capture" / "rules"
            / "workflow_status.py"
        )
        tree = ast.parse(path.read_text())
        module_level = [
            n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        observed_froms = {
            (n.module, frozenset(a.name for a in n.names))
            for n in module_level if isinstance(n, ast.ImportFrom)
        }
        observed_plain = {
            a.name for n in module_level
            if isinstance(n, ast.Import) for a in n.names
        }
        assert observed_froms == ALLOWED_PRELUDE_IMPORT_FROMS, (
            f"prelude `from` imports drift:\n"
            f"  observed: {sorted(observed_froms)}\n"
            f"  declared: {sorted(ALLOWED_PRELUDE_IMPORT_FROMS)}"
        )
        assert observed_plain == ALLOWED_PRELUDE_PLAIN_IMPORTS, (
            f"prelude plain imports drift:\n"
            f"  observed: {sorted(observed_plain)}\n"
            f"  declared: {sorted(ALLOWED_PRELUDE_PLAIN_IMPORTS)}"
        )

    def test_reverse_arrow_imports_are_exactly_two_declared_names(self):
        """Probe #6 in the post-implementation report contract: confirms
        the reverse-arrow `from server import ...` is exactly the two
        declared names and nothing more."""
        path = (
            BACKEND_ROOT / "workflows" / "document_capture" / "rules"
            / "workflow_status.py"
        )
        tree = ast.parse(path.read_text())
        server_imports = [
            n for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert len(server_imports) == 1, (
            f"expected exactly one `from server import (...)` in new module, "
            f"got {len(server_imports)}"
        )
        names = frozenset(a.name for a in server_imports[0].names)
        assert names == DECLARED_REVERSE_ARROW_NAMES, (
            f"reverse-arrow drift:\n"
            f"  observed: {sorted(names)}\n"
            f"  declared: {sorted(DECLARED_REVERSE_ARROW_NAMES)}"
        )


# ---------------------------------------------------------------------------
# 16. Package scaffolding present
# ---------------------------------------------------------------------------
class TestPackageScaffolding:
    def test_document_capture_init_exists_and_minimal(self):
        path = BACKEND_ROOT / "workflows" / "document_capture" / "__init__.py"
        assert path.exists(), "workflows/document_capture/__init__.py missing"
        # Empty or whitespace/docstring-only.
        content = path.read_text()
        if content.strip():
            tree = ast.parse(content)
            for node in tree.body:
                assert isinstance(node, ast.Expr) and isinstance(
                    node.value, ast.Constant
                ), "document_capture/__init__.py contains executable code"

    def test_rules_init_exists_and_minimal(self):
        path = (
            BACKEND_ROOT / "workflows" / "document_capture" / "rules"
            / "__init__.py"
        )
        assert path.exists(), "workflows/document_capture/rules/__init__.py missing"
        content = path.read_text()
        if content.strip():
            tree = ast.parse(content)
            for node in tree.body:
                assert isinstance(node, ast.Expr) and isinstance(
                    node.value, ast.Constant
                ), "rules/__init__.py contains executable code"


# ---------------------------------------------------------------------------
# 17. Live surface & audit script
# ---------------------------------------------------------------------------
class TestLiveSurfaceAndAudit:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200

    def test_openapi_path_count_858(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert len(paths) == 858, f"OpenAPI path count drift: {len(paths)}"

    def test_audit_script_reports_eight_passing(self):
        script = BACKEND_ROOT / "tests" / "audit_shim_substitution.py"
        if not script.exists():
            pytest.skip("audit script missing")
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BACKEND_ROOT),
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        assert "Passing (8):" in result.stdout
