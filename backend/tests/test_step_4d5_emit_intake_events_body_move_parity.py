"""
Phase 3 Step 4d.5 — `_emit_intake_events` Body-Move Parity Suite

First TRUE body-bearing Class 3 carve-out (not a thin-shim substitution).

Pattern (per signed declaration):
1. Capture golden source of server._emit_intake_events BEFORE the move.
2. Move the body VERBATIM into services.event_service as
   ``emit_intake_events`` (public name, underscore prefix dropped to
   match the 6 sibling ``emit_*`` primitives already resident there).
3. Leave a 4-line delegating shim at server.py:2712 so
   ``from server import _emit_intake_events`` continues to resolve.
4. Rewire ``services.document_handlers.intake_document_from_bytes``
   lazy-import cascade with alias preservation:
   ``from services.event_service import emit_intake_events
    as _emit_intake_events``.

``_build_vendor_resolution`` is explicitly out of scope.

13 probes:
1. AST-level import source.
2. AST-level alias preservation.
3. Lazy ``from server`` tuple shrunk to 4 entries.
4. server.py shim is async def.
5. server.py shim body structural invariant (1 ImportFrom + 1 Return).
6. server.py shim retained at module surface.
7. Positional-forwarding parity (param names/order match canonical).
8. Authoritative function exists (async callable in event_service).
9. Authoritative body byte-identical modulo the def rename
   (golden SHA-256 captured pre-move).
10. Call-site byte parity in intake_document_from_bytes.
11. Sibling-landscape acknowledgment — the 6 prior ``emit_*`` primitives
    in services.event_service are untouched (module-level callable
    identity preserved; names unchanged).
12. Live surface — backend reachable & /openapi.json path count ==858.
13. Audit script still reports 8 passing.
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

AUTHORITATIVE_NAME = "emit_intake_events"
BOUND_NAME = "_emit_intake_events"
CANONICAL_MODULE = "services.event_service"

# Golden source of server._emit_intake_events captured immediately
# before the 4d.5 body move.
EMIT_INTAKE_EVENTS_PRE_4D5_SHA256 = (
    "b99fd1d49fa7d72195d4e369419aa22c918c515a4c91edc1213ece526e063e2a"
)
EMIT_INTAKE_EVENTS_PRE_4D5_LEN = 2510

SIBLING_EMITS = (
    "emit_document_received",
    "emit_classification_completed",
    "emit_vendor_match",
    "emit_bc_validation",
    "emit_sharepoint_upload",
    "emit_automation_decision",
)


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
            and any(
                (alias.name == AUTHORITATIVE_NAME)
                for alias in n.names
            )
        ]
        assert matches, (
            f"{INTAKE_FUNC_NAME} does not import "
            f"{AUTHORITATIVE_NAME} from {CANONICAL_MODULE}"
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
# 3. Lazy `from server` tuple shrunk to 4 entries
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

    def test_lazy_tuple_now_four_private_helpers(self):
        fn = _intake_func_node()
        server_imports = [n for n in _iter_importfroms(fn) if n.module == "server"]
        assert len(server_imports) == 1, (
            f"expected exactly one `from server import (...)` in lazy cascade, "
            f"found {len(server_imports)}"
        )
        names = {alias.name for alias in server_imports[0].names}
        expected = {
            "_attempt_llm_vendor_ranking",
            "_build_vendor_resolution",
            "_update_ap_workflow_status",
            "_update_standard_workflow_status",
        }
        assert names == expected, (
            f"expected lazy tuple to shrink to {sorted(expected)}, got {sorted(names)}"
        )

    def test_new_4d5_import_line_with_alias_present(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert (
            "from services.event_service import "
            "emit_intake_events as _emit_intake_events"
        ) in handlers_src, "Step 4d.5 alias-import line missing"


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
        # Docstring (Expr/Constant) is allowed; the executable statements
        # must be exactly 1 ImportFrom + 1 Return.
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
        from services import event_service
        shim_params = list(
            inspect.signature(getattr(server, BOUND_NAME)).parameters
        )
        canonical_params = list(
            inspect.signature(
                getattr(event_service, AUTHORITATIVE_NAME)
            ).parameters
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
        from services import event_service
        fn = getattr(event_service, AUTHORITATIVE_NAME, None)
        assert fn is not None, (
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} missing after 4d.5 move"
        )
        assert inspect.iscoroutinefunction(fn), (
            f"{CANONICAL_MODULE}.{AUTHORITATIVE_NAME} is not async"
        )


# ---------------------------------------------------------------------------
# 9. Authoritative body byte-identical modulo the def rename
# ---------------------------------------------------------------------------
class TestAuthoritativeBodyByteIdentical:
    def test_emit_intake_events_source_matches_golden_modulo_def_rename(self):
        from services import event_service
        new_src = inspect.getsource(
            getattr(event_service, AUTHORITATIVE_NAME)
        )
        reverted = new_src.replace(
            f"async def {AUTHORITATIVE_NAME}(",
            f"async def {BOUND_NAME}(",
            1,
        )
        assert len(reverted) == EMIT_INTAKE_EVENTS_PRE_4D5_LEN, (
            f"length drift after move: got {len(reverted)}, "
            f"expected {EMIT_INTAKE_EVENTS_PRE_4D5_LEN}"
        )
        sha = hashlib.sha256(reverted.encode()).hexdigest()
        assert sha == EMIT_INTAKE_EVENTS_PRE_4D5_SHA256, (
            f"SHA-256 drift after move: got {sha}, "
            f"expected {EMIT_INTAKE_EVENTS_PRE_4D5_SHA256}"
        )


# ---------------------------------------------------------------------------
# 10. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_use_site_intact(self):
        handlers_src = Path(
            BACKEND_ROOT / "services" / "document_handlers.py"
        ).read_text()
        assert "await _emit_intake_events(" in handlers_src, (
            "intake call-site byte parity lost"
        )
        # Exact canonical argument spelling (byte-identical to pre-4d.5).
        assert (
            "await _emit_intake_events(\n"
            "            doc_id, correlation_id, classification, validation_results,\n"
            "            sp_result, decision, auto_clear_result\n"
            "        )"
        ) in handlers_src, "intake call-site arg-shape drift"


# ---------------------------------------------------------------------------
# 11. Sibling-landscape acknowledgment
# ---------------------------------------------------------------------------
class TestSiblingLandscapeAcknowledgment:
    def test_six_prior_emit_siblings_unchanged(self):
        from services import event_service
        for name in SIBLING_EMITS:
            fn = getattr(event_service, name, None)
            assert fn is not None, (
                f"sibling {CANONICAL_MODULE}.{name} missing after 4d.5 move"
            )
            assert inspect.iscoroutinefunction(fn), (
                f"sibling {CANONICAL_MODULE}.{name} no longer async"
            )
            # Module-level residency: defined in event_service, not aliased
            # from elsewhere.
            assert fn.__module__ == CANONICAL_MODULE, (
                f"sibling {name} module drift: {fn.__module__}"
            )

    def test_event_service_now_has_seven_emit_callables(self):
        from services import event_service
        emit_callables = [
            name for name in dir(event_service)
            if name.startswith("emit_")
            and inspect.iscoroutinefunction(
                getattr(event_service, name, None)
            )
            and getattr(
                getattr(event_service, name), "__module__", ""
            ) == CANONICAL_MODULE
        ]
        assert len(emit_callables) == 7, (
            f"expected 7 emit_* coroutines in event_service "
            f"(6 prior + emit_intake_events), got {len(emit_callables)}: "
            f"{sorted(emit_callables)}"
        )
        assert AUTHORITATIVE_NAME in emit_callables


# ---------------------------------------------------------------------------
# 12+13. Live surface & audit script
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
