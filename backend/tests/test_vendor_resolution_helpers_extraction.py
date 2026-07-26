"""
Parity tests for the final vendor-resolution helper extraction.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "vendor_resolution_helpers_extraction_baseline.json"
)

HELPER_NAMES = (
    "_build_vendor_resolution",
    "_attempt_llm_vendor_ranking",
)

CANONICAL_MODULE = (
    "services.vendor_resolution_helpers"
)


def _baseline() -> dict:
    return json.loads(
        BASELINE_PATH.read_text()
    )


def _normalized_source(function) -> str:
    source = textwrap.dedent(
        inspect.getsource(function)
    )

    return (
        "\n".join(
            line.rstrip()
            for line in source.splitlines()
        )
        + "\n"
    )


class TestHelperSourceParity:
    @pytest.mark.parametrize(
        "helper_name",
        HELPER_NAMES,
    )
    def test_source_matches_baseline(
        self,
        helper_name,
    ):
        import services.vendor_resolution_helpers as module

        baseline = _baseline()
        function = getattr(
            module,
            helper_name,
        )
        source = _normalized_source(
            function
        )
        metadata = baseline[
            "helpers"
        ][helper_name]

        actual_sha = hashlib.sha256(
            source.encode("utf-8")
        ).hexdigest()

        assert (
            actual_sha
            == metadata["normalized_source_sha256"]
        )
        assert (
            len(source.splitlines())
            == metadata[
                "normalized_source_line_count"
            ]
        )
        assert (
            len(source)
            == metadata[
                "normalized_source_char_count"
            ]
        )

    def test_signatures_and_kinds(self):
        import services.vendor_resolution_helpers as module

        build = module._build_vendor_resolution
        ranking = (
            module._attempt_llm_vendor_ranking
        )

        assert list(
            inspect.signature(
                build
            ).parameters
        ) == [
            "vendor_raw",
            "match_result",
        ]

        assert list(
            inspect.signature(
                ranking
            ).parameters
        ) == [
            "doc_id",
            "vendor_alias_result",
            "vendor_raw",
            "normalized_fields",
        ]

        assert not inspect.iscoroutinefunction(
            build
        )
        assert inspect.iscoroutinefunction(
            ranking
        )


class TestCanonicalModule:
    def test_module_has_no_server_import(self):
        source = (
            BACKEND_DIR
            / "services"
            / "vendor_resolution_helpers.py"
        ).read_text()

        tree = ast.parse(source)

        assert not any(
            isinstance(node, ast.ImportFrom)
            and node.module == "server"
            for node in ast.walk(tree)
        )

    def test_module_uses_server_logger_category(self):
        import services.vendor_resolution_helpers as module

        assert module.logger.name == "server"


class TestServerCompatibilityWrappers:
    @pytest.mark.parametrize(
        "helper_name,expected_kind",
        [
            (
                "_build_vendor_resolution",
                ast.FunctionDef,
            ),
            (
                "_attempt_llm_vendor_ranking",
                ast.AsyncFunctionDef,
            ),
        ],
    )
    def test_wrapper_is_thin(
        self,
        helper_name,
        expected_kind,
    ):
        source = (
            BACKEND_DIR / "server.py"
        ).read_text()

        tree = ast.parse(source)

        node = next(
            item
            for item in tree.body
            if isinstance(
                item,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and item.name == helper_name
        )

        assert isinstance(
            node,
            expected_kind,
        )

        executable = [
            item
            for item in node.body
            if not (
                isinstance(item, ast.Expr)
                and isinstance(
                    item.value,
                    ast.Constant,
                )
                and isinstance(
                    item.value.value,
                    str,
                )
            )
        ]

        assert [
            type(item).__name__
            for item in executable
        ] == ["ImportFrom", "Return"]

        import_node = executable[0]

        assert (
            import_node.module
            == CANONICAL_MODULE
        )
        assert len(import_node.names) == 1
        assert (
            import_node.names[0].name
            == helper_name
        )
        assert (
            import_node.names[0].asname
            == "_impl"
        )

    def test_wrapper_signatures_match(self):
        import server
        import services.vendor_resolution_helpers as module

        for helper_name in HELPER_NAMES:
            assert list(
                inspect.signature(
                    getattr(
                        server,
                        helper_name,
                    )
                ).parameters
            ) == list(
                inspect.signature(
                    getattr(
                        module,
                        helper_name,
                    )
                ).parameters
            )


class TestRawIntakeRewire:
    def test_raw_intake_uses_canonical_module(self):
        source = (
            BACKEND_DIR
            / "services"
            / "document_bytes_intake_service.py"
        ).read_text()

        tree = ast.parse(source)

        function_node = next(
            node
            for node in tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "intake_document_from_bytes"
        )

        canonical_imports = [
            node
            for node in ast.walk(
                function_node
            )
            if isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module
            == CANONICAL_MODULE
        ]

        assert len(
            canonical_imports
        ) == 1

        names = {
            alias.name
            for alias in canonical_imports[
                0
            ].names
        }

        assert names == set(
            HELPER_NAMES
        )

        assert not any(
            isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module == "server"
            for node in ast.walk(
                function_node
            )
        )

    def test_no_production_server_imports_remain(self):
        roots = [
            BACKEND_DIR / "services",
            BACKEND_DIR / "workflows",
            BACKEND_DIR / "routers",
        ]

        violations = []

        for root in roots:
            for path in root.rglob("*.py"):
                source = path.read_text()
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if (
                        isinstance(
                            node,
                            ast.ImportFrom,
                        )
                        and node.module
                        == "server"
                    ):
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)}:"
                            f"{node.lineno}"
                        )

                    elif isinstance(
                        node,
                        ast.Import,
                    ):
                        if any(
                            alias.name
                            == "server"
                            for alias in node.names
                        ):
                            violations.append(
                                f"{path.relative_to(BACKEND_DIR)}:"
                                f"{node.lineno}"
                            )

        assert violations == []


class TestHelperBehavior:
    def test_build_resolution_success(
        self,
        monkeypatch,
    ):
        """
        Prove the preserved success branch by injecting the optional
        build_resolution_object dependency expected by the helper.
        """
        import sys
        from types import ModuleType

        import services.vendor_resolution_helpers as module

        calls = []

        def fake_builder(
            *,
            vendor_raw,
            match_result,
        ):
            calls.append(
                (
                    vendor_raw,
                    match_result,
                )
            )
            return {
                "status": "matched",
                "vendor": vendor_raw,
            }

        fake_service = ModuleType(
            "services.vendor_resolution_service"
        )
        fake_service.build_resolution_object = (
            fake_builder
        )

        monkeypatch.setitem(
            sys.modules,
            "services.vendor_resolution_service",
            fake_service,
        )

        match_result = {
            "vendor_no": "V100",
        }

        result = module._build_vendor_resolution(
            "Acme",
            match_result,
        )

        assert calls == [
            (
                "Acme",
                match_result,
            )
        ]
        assert result == {
            "status": "matched",
            "vendor": "Acme",
        }

    def test_build_resolution_fallback(
        self,
        monkeypatch,
    ):
        """
        Prove that an unavailable or failing optional builder cannot break
        intake and produces the historical unresolved fallback object.
        """
        import sys
        from types import ModuleType

        import services.vendor_resolution_helpers as module

        def failing_builder(**kwargs):
            raise RuntimeError(
                "test failure"
            )

        fake_service = ModuleType(
            "services.vendor_resolution_service"
        )
        fake_service.build_resolution_object = (
            failing_builder
        )

        monkeypatch.setitem(
            sys.modules,
            "services.vendor_resolution_service",
            fake_service,
        )

        assert module._build_vendor_resolution(
            "",
            {},
        ) == {
            "status": "unresolved",
            "method": "none",
            "raw": "",
        }

    @pytest.mark.asyncio
    async def test_ranking_disabled_is_noop(
        self,
        monkeypatch,
    ):
        import services.vendor_resolution_helpers as module

        monkeypatch.setenv(
            "ENABLE_LLM_VENDOR_RANKING",
            "false",
        )

        original = {
            "vendor_match_method": "none",
        }

        result = await module._attempt_llm_vendor_ranking(
            "document-1",
            original,
            "Acme",
            {},
        )

        assert result == (
            original,
            None,
            None,
        )
        assert result[0] is original

    @pytest.mark.asyncio
    async def test_high_confidence_match_is_not_overridden(
        self,
        monkeypatch,
    ):
        import services.vendor_resolution_helpers as module

        monkeypatch.setenv(
            "ENABLE_LLM_VENDOR_RANKING",
            "true",
        )

        original = {
            "vendor_match_method": "alias",
            "match_score": 1.0,
        }

        result = await module._attempt_llm_vendor_ranking(
            "document-2",
            original,
            "Acme",
            {},
        )

        assert result == (
            original,
            None,
            None,
        )
        assert result[0] is original

    @pytest.mark.asyncio
    async def test_missing_vendor_raw_is_noop(
        self,
        monkeypatch,
    ):
        import services.vendor_resolution_helpers as module

        monkeypatch.setenv(
            "ENABLE_LLM_VENDOR_RANKING",
            "true",
        )

        original = {
            "vendor_match_method": "none",
            "match_score": 0,
        }

        result = await module._attempt_llm_vendor_ranking(
            "document-3",
            original,
            "",
            {},
        )

        assert result == (
            original,
            None,
            None,
        )


class TestImportOrderSafety:
    def test_service_then_server(self):
        script = textwrap.dedent(
            """
            import services.vendor_resolution_helpers as svc
            import server
            assert hasattr(
                svc,
                "_build_vendor_resolution",
            )
            assert hasattr(
                svc,
                "_attempt_llm_vendor_ranking",
            )
            assert hasattr(
                server,
                "_build_vendor_resolution",
            )
            assert hasattr(
                server,
                "_attempt_llm_vendor_ranking",
            )
            print("OK")
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(BACKEND_DIR),
            env={
                **os.environ,
                "PYTHONPATH": str(
                    BACKEND_DIR
                ),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            result.stdout
            + result.stderr
        )
        assert "OK" in result.stdout

    def test_server_then_service(self):
        script = textwrap.dedent(
            """
            import server
            import services.vendor_resolution_helpers as svc
            assert hasattr(
                server,
                "_build_vendor_resolution",
            )
            assert hasattr(
                server,
                "_attempt_llm_vendor_ranking",
            )
            assert hasattr(
                svc,
                "_build_vendor_resolution",
            )
            assert hasattr(
                svc,
                "_attempt_llm_vendor_ranking",
            )
            print("OK")
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(BACKEND_DIR),
            env={
                **os.environ,
                "PYTHONPATH": str(
                    BACKEND_DIR
                ),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            result.stdout
            + result.stderr
        )
        assert "OK" in result.stdout
