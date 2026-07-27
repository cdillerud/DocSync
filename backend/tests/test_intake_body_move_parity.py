"""
Raw-bytes intake body and service-seam parity tests.

The original Step 4b fixture remains preserved as historical evidence of the
move from server.py. A second fixture captures the current body after the
approved Step 4c and Step 4d helper migrations and immediately before the
dedicated raw-intake service extraction.

Tests resolve the callable through document_bytes_intake_service so they remain
valid both before and after the final authoritative body move.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import inspect
import json
import os
import textwrap
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent

ORIGINAL_BASELINE_PATH = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "intake_body_move_baseline.json"
)

CURRENT_BASELINE_PATH = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "intake_body_current_baseline.json"
)

EXPECTED_PARAMETERS = [
    "file_content",
    "filename",
    "content_type",
    "source",
    "sender",
    "subject",
    "email_id",
    "mailbox_category",
]

VENDOR_RESOLUTION_MODULE = (
    "services.vendor_resolution_helpers"
)

EXPECTED_VENDOR_RESOLUTION_IMPORTS = {
    "_attempt_llm_vendor_ranking",
    "_build_vendor_resolution",
}

EXPECTED_SERVER_IMPORTS = set()

MIGRATED_HELPER_SOURCES = {
    "_attempt_llm_vendor_ranking":
        VENDOR_RESOLUTION_MODULE,
    "_build_vendor_resolution":
        VENDOR_RESOLUTION_MODULE,
    "_derive_workflow_status":
        "services.classification_helpers",
    "_emit_intake_events":
        "services.event_service",
    "_update_ap_workflow_status":
        "workflows.ap_invoice.rules.workflow_status",
    "_update_standard_workflow_status":
        "workflows.document_capture.rules.workflow_status",
    "_update_vendor_profile_incremental":
        "workflows.ap_invoice.rules.vendor_profile",
}


def _load_json(path: Path) -> dict:
    assert path.exists(), f"Baseline fixture missing: {path}"
    return json.loads(path.read_text())


def _intake_function():
    from services.document_bytes_intake_service import (
        intake_document_from_bytes,
    )

    return intake_document_from_bytes


def _intake_source_and_node():
    source = textwrap.dedent(
        inspect.getsource(_intake_function())
    )
    tree = ast.parse(source)

    assert len(tree.body) == 1
    node = tree.body[0]
    assert isinstance(node, ast.AsyncFunctionDef)
    assert node.name == "intake_document_from_bytes"

    return source, node


def _extract_current_body_source() -> str:
    source, node = _intake_source_and_node()
    body = list(node.body)

    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    while body and isinstance(
        body[0],
        (ast.Import, ast.ImportFrom),
    ):
        body = body[1:]

    assert body, "No executable intake body found"

    lines = source.splitlines(keepends=True)

    return textwrap.dedent(
        "".join(
            lines[
                body[0].lineno - 1:
                body[-1].end_lineno
            ]
        )
    )


def _function_import_sources() -> dict[str, str]:
    _, node = _intake_source_and_node()
    sources: dict[str, str] = {}

    for item in ast.walk(node):
        if isinstance(item, ast.ImportFrom):
            for alias in item.names:
                bound_name = alias.asname or alias.name
                sources[bound_name] = item.module or ""

    return sources


def _authoritative_module_source() -> str:
    function = _intake_function()
    module = inspect.getmodule(function)

    assert module is not None
    return inspect.getsource(module)


class TestBodySourceByteIdentity:
    def test_original_step4b_fixture_is_preserved(self):
        baseline = _load_json(ORIGINAL_BASELINE_PATH)

        assert (
            baseline["pre_move_source_function_name"]
            == "_internal_intake_document"
        )
        assert baseline["pre_move_source_module"] == "server"
        assert "pre_move_source_sha256" in baseline
        assert "pre_move_body_source" in baseline

    def test_current_fixture_is_well_formed(self):
        baseline = _load_json(CURRENT_BASELINE_PATH)

        required = {
            "baseline_kind",
            "source_module",
            "function_name",
            "body_sha256",
            "body_line_count",
            "body_char_count",
            "signature_parameters",
            "source_default",
            "optional_defaults",
        }

        assert required <= set(baseline)
        assert (
            baseline["function_name"]
            == "intake_document_from_bytes"
        )

    def test_current_body_sha256_matches_baseline(self):
        baseline = _load_json(CURRENT_BASELINE_PATH)
        body = _extract_current_body_source()
        actual = hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()

        assert actual == baseline["body_sha256"]

    def test_current_body_line_count_matches_baseline(self):
        baseline = _load_json(CURRENT_BASELINE_PATH)
        body = _extract_current_body_source()

        assert (
            len(body.splitlines())
            == baseline["body_line_count"]
        )

    def test_current_body_char_count_matches_baseline(self):
        baseline = _load_json(CURRENT_BASELINE_PATH)
        body = _extract_current_body_source()

        assert len(body) == baseline["body_char_count"]

    def test_signature_contract_matches_baseline(self):
        baseline = _load_json(CURRENT_BASELINE_PATH)
        signature = inspect.signature(_intake_function())

        assert (
            list(signature.parameters)
            == baseline["signature_parameters"]
            == EXPECTED_PARAMETERS
        )
        assert (
            signature.parameters["source"].default
            == baseline["source_default"]
        )

        for name in (
            "sender",
            "subject",
            "email_id",
            "mailbox_category",
        ):
            assert signature.parameters[name].default is None


class TestReferencedNamesResolvable:
    def test_no_server_imports_remain(self):
        imports = _function_import_sources()

        actual = {
            name
            for name, module in imports.items()
            if module == "server"
        }

        assert actual == EXPECTED_SERVER_IMPORTS == set()

        vendor_resolution_imports = {
            name
            for name, module in imports.items()
            if module == VENDOR_RESOLUTION_MODULE
        }

        assert (
            vendor_resolution_imports
            == EXPECTED_VENDOR_RESOLUTION_IMPORTS
        )

    @pytest.mark.parametrize(
        "bound_name,expected_module",
        tuple(MIGRATED_HELPER_SOURCES.items()),
    )
    def test_migrated_helpers_use_canonical_modules(
        self,
        bound_name,
        expected_module,
    ):
        imports = _function_import_sources()

        assert imports.get(bound_name) == expected_module

    def test_every_original_baseline_name_is_resolvable(self):
        original = _load_json(ORIGINAL_BASELINE_PATH)
        referenced_names = set(
            original["pre_move_body_referenced_names"]
        )

        _, function_node = _intake_source_and_node()

        local_names = {
            arg.arg
            for arg in (
                list(function_node.args.args)
                + list(function_node.args.kwonlyargs)
            )
        }

        for node in ast.walk(function_node):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
            ):
                local_names.add(node.id)

            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_names.add(
                        alias.asname or alias.name
                    )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local_names.add(
                        alias.asname
                        or alias.name.split(".")[0]
                    )

            elif (
                isinstance(node, ast.ExceptHandler)
                and node.name
            ):
                local_names.add(node.name)

            elif isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                local_names.add(node.name)

        module_source = _authoritative_module_source()
        module_tree = ast.parse(module_source)
        module_names = set()

        for node in module_tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    module_names.add(
                        alias.asname or alias.name
                    )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_names.add(
                        alias.asname
                        or alias.name.split(".")[0]
                    )

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_names.add(target.id)

            elif isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ):
                module_names.add(node.name)

        resolvable = (
            local_names
            | module_names
            | set(dir(builtins))
            | {"True", "False", "None", "self"}
        )

        unresolved = sorted(
            referenced_names - resolvable
        )

        assert not unresolved, (
            "Original baseline names unresolved at the "
            f"current call site: {unresolved[:20]}"
        )


class TestLiveSurfaceAndCallerImports:
    BASE_URL = os.environ.get(
        "REACT_APP_BACKEND_URL",
        "http://localhost:8001",
    ).rstrip("/")

    def _reachable(self) -> bool:
        try:
            import requests

            response = requests.get(
                f"{self.BASE_URL}/openapi.json",
                timeout=2,
            )
            return response.status_code == 200
        except Exception:
            return False

    def test_openapi_path_count_888(self):
        if not self._reachable():
            pytest.skip(
                "No backend reachable on localhost:8001"
            )

        import requests

        paths = requests.get(
            f"{self.BASE_URL}/openapi.json"
        ).json().get("paths", {})

        assert len(paths) == 888

    @pytest.mark.parametrize(
        "module_name",
        [
            "routers.sales_pipeline_demo",
            "routers.pilot",
            "services.email_polling_service",
            "services.inside_sales_pilot_service",
            "services.batch_po_splitter",
        ],
    )
    def test_caller_module_imports_cleanly(
        self,
        module_name,
    ):
        module = importlib.import_module(module_name)
        assert module is not None

    def test_service_seam_resolves_coroutine(self):
        function = _intake_function()

        assert inspect.iscoroutinefunction(function)
        assert (
            list(inspect.signature(function).parameters)
            == EXPECTED_PARAMETERS
        )

    def test_service_and_handler_exports_are_identical(self):
        import services.document_handlers as handlers

        assert (
            _intake_function()
            is handlers.intake_document_from_bytes
        )


class TestSourceInspectionGuardrails:
    def test_server_no_longer_defines_internal_intake(self):
        source = (
            BACKEND_DIR / "server.py"
        ).read_text()

        assert (
            "async def _internal_intake_document("
            not in source
        )

    def test_server_move_marker_remains(self):
        source = (
            BACKEND_DIR / "server.py"
        ).read_text()

        assert "_internal_intake_document moved" in source
        assert "intake_document_from_bytes" in source

    def test_server_line_count_matches_current_extracted_band(self):
        total = sum(
            1
            for _ in (
                BACKEND_DIR / "server.py"
            ).open()
        )

        assert 4434 <= total <= 4454, (
            f"server.py line count {total} outside "
            "the current extracted baseline band "
            "(4434-4454)."
        )

    def test_authoritative_body_remains_large(self):
        source = inspect.getsource(_intake_function())
        code_lines = [
            line
            for line in source.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
        ]

        assert len(code_lines) >= 500

    def test_first_body_import_is_vendor_resolution_service(self):
        _, node = _intake_source_and_node()
        body = list(node.body)

        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(
                body[0].value,
                ast.Constant,
            )
            and isinstance(
                body[0].value.value,
                str,
            )
        ):
            body = body[1:]

        assert isinstance(
            body[0],
            ast.ImportFrom,
        )
        assert (
            body[0].module
            == VENDOR_RESOLUTION_MODULE
        )

        names = {
            alias.asname or alias.name
            for alias in body[0].names
        }

        assert (
            names
            == EXPECTED_VENDOR_RESOLUTION_IMPORTS
        )

    @pytest.mark.parametrize(
        "relative_path",
        [
            "services/document_handlers.py",
            "services/document_bytes_intake_service.py",
        ],
    )
    def test_no_internal_intake_backward_import(
        self,
        relative_path,
    ):
        source = (
            BACKEND_DIR / relative_path
        ).read_text()
        tree = ast.parse(source)

        for node in tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                names = {
                    alias.name for alias in node.names
                }

                assert (
                    "_internal_intake_document"
                    not in names
                )

    def test_both_baseline_fixtures_are_committed(self):
        original = _load_json(ORIGINAL_BASELINE_PATH)
        current = _load_json(CURRENT_BASELINE_PATH)

        assert "pre_move_source_sha256" in original
        assert "body_sha256" in current
