"""
Phase 3 Step 4d.6 — `_update_ap_workflow_status` Body-Move Parity Suite

Second TRUE body-bearing Class 3 carve-out (mirrors 4d.5 shape).

Pattern (per signed declaration):
1. Capture golden source of server._update_ap_workflow_status BEFORE the
   move (5,062 chars).
2. Move the body VERBATIM into a NEW module
   ``workflows.ap_invoice.rules.workflow_status`` as
   ``update_ap_workflow_status`` (public name; underscore prefix dropped
   to match the 4d.4b precedent at
   ``workflows.ap_invoice.rules.vendor_profile.update_vendor_profile_incremental``).
3. Leave a 4-statement delegating shim at server.py:2253 so
   ``from server import _update_ap_workflow_status`` continues to resolve.
4. Rewire ``services.document_handlers.intake_document_from_bytes`` lazy
   import cascade with alias preservation:
   ``from workflows.ap_invoice.rules.workflow_status import
      update_ap_workflow_status as _update_ap_workflow_status``.

``_build_vendor_resolution`` is explicitly out of scope.
``_update_standard_workflow_status``, ``_attempt_llm_vendor_ranking`` are
also out of scope.

14 probes:
1. AST-level import source.
2. AST-level alias preservation.
3. Lazy ``from server`` tuple — name-removal invariant (`_update_ap_workflow_status`
   removed; expected residents are exactly the 3 remaining body-bearing helpers).
4. server.py shim is async def.
5. server.py shim body structural invariant (1 ImportFrom + 1 Return).
6. server.py shim retained at module surface.
7. Positional-forwarding parity (param names/order match canonical).
8. Authoritative function exists (async callable in canonical module).
9. Authoritative body byte-identical modulo def rename
   (golden SHA-256 captured pre-move).
10. Call-site byte parity in intake_document_from_bytes.
11. Sibling-landscape acknowledgment — the 4d.4b sibling
    ``workflows.ap_invoice.rules.vendor_profile`` is unchanged.
12. New-module hygiene — exactly one public callable; module-level imports
    match the declared minimal prelude (no surprise imports).
13. Live surface — backend reachable & /openapi.json path count ==858.
14. Audit script still reports 8 passing.
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

AUTHORITATIVE_NAME = "update_ap_workflow_status"
BOUND_NAME = "_update_ap_workflow_status"
CANONICAL_MODULE = "workflows.ap_invoice.rules.workflow_status"

# Golden source of server._update_ap_workflow_status captured immediately
# before the 4d.6 body move.
UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_SHA256 = (
    "11e29d0dd3eba631171ccc42afac7573595bd52d4c3f0383e93e48e82fe41a37"
)
UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_LEN = 5062

# The 3 body-bearing helpers expected to remain in the lazy `from server`
# tuple after 4d.6 lands. (`_emit_intake_events`,
# `_derive_workflow_status`, `_update_vendor_profile_incremental` already
# migrated in 4d.5 / 4d.4a / 4d.4b respectively; `_update_ap_workflow_status`
# is migrated by this step.)
EXPECTED_LAZY_TUPLE = {
    "_attempt_llm_vendor_ranking",
    "_build_vendor_resolution",
    "_update_standard_workflow_status",
}

# Declared minimal prelude (per signed Step 4d.6 declaration §3.B).
# AST-level import-from / import nodes the new module is allowed to carry.
ALLOWED_PRELUDE_IMPORT_FROMS = {
    ("typing", frozenset({"Dict"})),
    ("datetime", frozenset({"datetime", "timezone"})),
    ("database", frozenset({"db"})),
    ("workflows.core.engine", frozenset({"WorkflowEngine", "WorkflowEvent"})),
}
ALLOWED_PRELUDE_PLAIN_IMPORTS = {"logging"}


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
                    f"{BOUND_NAME} still imported from server: {sorted(names)}"
                )

    def test_lazy_tuple_now_three_private_helpers(self):
        """
        Post-4d.6 structural check: `_update_ap_workflow_status` has been
        REMOVED from the ``from server import (...)`` tuple.

        Note: originally asserted the tuple was the exact set of 3 named
        helpers as a cumulative-state proxy; rewritten to a name-removal
        invariant so the probe remains valid as subsequent carve-outs
        continue to shrink the tuple.
        """
        fn = _intake_func_node()
        server_imports = [n for n in _iter_importfroms(fn) if n.module == "server"]
        assert len(server_imports) == 1, (
            f"expected exactly one `from server import (...)` in lazy cascade, "
            f"found {len(server_imports)}"
        )
        names = {alias.name for alias in server_imports[0].names}
        assert "_update_ap_workflow_status" not in names, (
            f"Expected `_update_ap_workflow_status` removed from lazy tuple "
            f"after Step 4d.6, got {sorted(names)}"
        )

    def test_new_4d6_import_line_with_alias_present(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert (
            "from workflows.ap_invoice.rules.workflow_status import (\n"
            "        update_ap_workflow_status as _update_ap_workflow_status,\n"
            "    )"
        ) in handlers_src, "Step 4d.6 alias-import block missing"


# ---------------------------------------------------------------------------
# 4+5+6. server.py shim structural invariant & retention
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
        node = _server_shim_node()
        assert isinstance(node, ast.AsyncFunctionDef)

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
        assert kinds == ["ImportFrom", "Return"], (
            f"shim body structure drift: {kinds}"
        )


class TestServerShimRetained:
    def test_server_still_exposes_bound_name(self):
        import server
        assert hasattr(server, BOUND_NAME), (
            f"server.{BOUND_NAME} no longer importable"
        )


# ---------------------------------------------------------------------------
# 7. Positional-forwarding parity
# ---------------------------------------------------------------------------
class TestSignatureForwardingParity:
    def test_shim_params_match_canonical(self):
        import server
        from workflows.ap_invoice.rules import workflow_status as wf_mod
        shim_params = list(
            inspect.signature(getattr(server, BOUND_NAME)).parameters
        )
        canonical_params = list(
            inspect.signature(getattr(wf_mod, AUTHORITATIVE_NAME)).parameters
        )
        assert shim_params == canonical_params, (
            f"server.{BOUND_NAME} params {shim_params} != "
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} params {canonical_params}"
        )


# ---------------------------------------------------------------------------
# 8. Authoritative function exists
# ---------------------------------------------------------------------------
class TestAuthoritativeExists:
    def test_authoritative_is_async_callable(self):
        from workflows.ap_invoice.rules import workflow_status as wf_mod
        fn = getattr(wf_mod, AUTHORITATIVE_NAME, None)
        assert fn is not None, (
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} missing after 4d.6 move"
        )
        assert inspect.iscoroutinefunction(fn), (
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} is not async"
        )
        assert fn.__module__ == CANONICAL_MODULE, (
            f"{AUTHORITATIVE_NAME}.__module__ drift: {fn.__module__}"
        )


# ---------------------------------------------------------------------------
# 9. Authoritative body byte-identical modulo the def rename
# ---------------------------------------------------------------------------
class TestAuthoritativeBodyByteIdentical:
    def test_update_ap_workflow_status_source_matches_golden(self):
        from workflows.ap_invoice.rules import workflow_status as wf_mod
        new_src = inspect.getsource(getattr(wf_mod, AUTHORITATIVE_NAME))
        reverted = new_src.replace(
            f"async def {AUTHORITATIVE_NAME}(",
            f"async def {BOUND_NAME}(",
            1,
        )
        assert len(reverted) == UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_LEN, (
            f"length drift after move: got {len(reverted)}, "
            f"expected {UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_LEN}"
        )
        sha = hashlib.sha256(reverted.encode()).hexdigest()
        assert sha == UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_SHA256, (
            f"SHA-256 drift after move: got {sha}, "
            f"expected {UPDATE_AP_WORKFLOW_STATUS_PRE_4D6_SHA256}"
        )


# ---------------------------------------------------------------------------
# 10. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_use_site_intact(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert "await _update_ap_workflow_status(" in handlers_src, (
            "intake call-site byte parity lost"
        )


# ---------------------------------------------------------------------------
# 11. Sibling-landscape acknowledgment — 4d.4b sibling unchanged
# ---------------------------------------------------------------------------
class TestSiblingLandscapeAcknowledgment:
    def test_vendor_profile_sibling_module_unchanged(self):
        from workflows.ap_invoice.rules import vendor_profile
        # Public callables resident in this sibling module: must remain
        # exactly one — `update_vendor_profile_incremental`.
        public_callables = [
            name for name in dir(vendor_profile)
            if not name.startswith("_")
            and callable(getattr(vendor_profile, name, None))
            and getattr(getattr(vendor_profile, name), "__module__", "")
                == "workflows.ap_invoice.rules.vendor_profile"
        ]
        assert public_callables == ["update_vendor_profile_incremental"], (
            f"4d.4b sibling drift: {public_callables}"
        )


# ---------------------------------------------------------------------------
# 12. New-module hygiene
# ---------------------------------------------------------------------------
class TestNewModuleHygiene:
    def test_new_module_exposes_exactly_one_public_callable(self):
        from workflows.ap_invoice.rules import workflow_status as wf_mod
        public_callables = [
            name for name in dir(wf_mod)
            if not name.startswith("_")
            and callable(getattr(wf_mod, name, None))
            and getattr(getattr(wf_mod, name), "__module__", "")
                == CANONICAL_MODULE
        ]
        assert public_callables == [AUTHORITATIVE_NAME], (
            f"new module exposes unexpected publics: {public_callables}"
        )

    def test_new_module_imports_match_declared_prelude(self):
        path = (
            BACKEND_ROOT / "workflows" / "ap_invoice" / "rules"
            / "workflow_status.py"
        )
        tree = ast.parse(path.read_text())
        module_level = [
            node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
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


# ---------------------------------------------------------------------------
# 13+14. Live surface & audit script
# ---------------------------------------------------------------------------
class TestLiveSurfaceAndAudit:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200, f"/api/health → {r.status_code}"

    def test_openapi_path_count_858(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert len(paths) == 858, (
            f"OpenAPI path count drifted: got {len(paths)}, expected 858"
        )

    def test_audit_script_reports_eight_passing(self):
        script = BACKEND_ROOT / "tests" / "audit_shim_substitution.py"
        if not script.exists():
            pytest.skip("audit_shim_substitution.py not present")
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"audit exited {result.returncode}: {result.stderr[-400:]}"
        )
        out = result.stdout
        assert "Passing (8):" in out, f"audit tail:\n{out[-600:]}"
