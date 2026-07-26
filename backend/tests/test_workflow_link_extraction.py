"""
Parity tests for workflow-audited link_document extraction.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "workflow_link_extraction_baseline.json"
)


def _baseline() -> dict:
    return json.loads(
        BASELINE_PATH.read_text()
    )


def _normalized_service_source() -> str:
    from services.workflow_link_service import (
        link_document,
    )

    source = textwrap.dedent(
        inspect.getsource(link_document)
    )

    return (
        "\n".join(
            line.rstrip()
            for line in source.splitlines()
        )
        + "\n"
    )


class TestWorkflowLinkSourceParity:
    def test_baseline_is_present(self):
        baseline = _baseline()

        assert (
            baseline["pre_move_module"]
            == "server"
        )
        assert (
            baseline["authoritative_module"]
            == "services.workflow_link_service"
        )
        assert (
            baseline["signature_parameters"]
            == ["doc_id"]
        )

    def test_source_sha_matches_baseline(self):
        baseline = _baseline()
        source = _normalized_service_source()

        actual = hashlib.sha256(
            source.encode("utf-8")
        ).hexdigest()

        assert (
            actual
            == baseline["normalized_source_sha256"]
        )

    def test_source_size_matches_baseline(self):
        baseline = _baseline()
        source = _normalized_service_source()

        assert (
            len(source.splitlines())
            == baseline["normalized_source_line_count"]
        )
        assert (
            len(source)
            == baseline["normalized_source_char_count"]
        )

    def test_signature_is_preserved(self):
        from services.workflow_link_service import (
            link_document,
        )

        signature = inspect.signature(
            link_document
        )

        assert list(signature.parameters) == [
            "doc_id"
        ]
        assert inspect.iscoroutinefunction(
            link_document
        )


class TestWorkflowLinkDependencies:
    def test_service_has_no_server_import(self):
        source = (
            BACKEND_DIR
            / "services"
            / "workflow_link_service.py"
        ).read_text()

        tree = ast.parse(source)

        reverse_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "server"
        ]

        assert reverse_imports == []

    def test_service_uses_canonical_dependencies(self):
        source = (
            BACKEND_DIR
            / "services"
            / "workflow_link_service.py"
        ).read_text()

        tree = ast.parse(source)

        imports = {
            node.module: {
                alias.asname or alias.name
                for alias in node.names
            }
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        }

        assert "db" in imports["database"]
        assert "UPLOAD_DIR" in imports["paths"]
        assert (
            "get_bc_sales_orders"
            in imports["services.bc_api_helpers"]
        )
        assert (
            "link_document_to_bc"
            in imports["services.bc_link_service"]
        )


class TestServerCompatibilityWrapper:
    def test_wrapper_is_thin_and_async(self):
        source = (
            BACKEND_DIR / "server.py"
        ).read_text()

        tree = ast.parse(source)

        node = next(
            item
            for item in tree.body
            if isinstance(
                item,
                ast.AsyncFunctionDef,
            )
            and item.name == "link_document"
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
            == "services.workflow_link_service"
        )
        assert len(import_node.names) == 1
        assert (
            import_node.names[0].name
            == "link_document"
        )
        assert (
            import_node.names[0].asname
            == "_impl"
        )

    def test_wrapper_signature_matches_service(self):
        import server
        from services.workflow_link_service import (
            link_document,
        )

        assert list(
            inspect.signature(
                server.link_document
            ).parameters
        ) == list(
            inspect.signature(
                link_document
            ).parameters
        )


class TestWorkflowRouterRewire:
    def test_retry_route_imports_service(self):
        source = (
            BACKEND_DIR
            / "routers"
            / "workflows.py"
        ).read_text()

        tree = ast.parse(source)

        retry_node = next(
            item
            for item in tree.body
            if isinstance(
                item,
                ast.AsyncFunctionDef,
            )
            and item.name == "retry_workflow"
        )

        imports = [
            item
            for item in ast.walk(retry_node)
            if isinstance(item, ast.ImportFrom)
        ]

        assert any(
            item.module
            == "services.workflow_link_service"
            and any(
                alias.name == "link_document"
                for alias in item.names
            )
            for item in imports
        )

        assert not any(
            item.module == "server"
            and any(
                alias.name == "link_document"
                for alias in item.names
            )
            for item in imports
        )

    def test_router_imports_cleanly(self):
        module = importlib.import_module(
            "routers.workflows"
        )
        assert module is not None


class TestReverseImportSafety:
    def test_service_then_server(self):
        script = textwrap.dedent(
            """
            import services.workflow_link_service as svc
            import server
            assert hasattr(svc, "link_document")
            assert hasattr(server, "link_document")
            print("OK")
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(BACKEND_DIR),
            env={
                **os.environ,
                "PYTHONPATH": str(BACKEND_DIR),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            result.stdout + result.stderr
        )
        assert "OK" in result.stdout

    def test_server_then_service(self):
        script = textwrap.dedent(
            """
            import server
            import services.workflow_link_service as svc
            assert hasattr(server, "link_document")
            assert hasattr(svc, "link_document")
            print("OK")
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(BACKEND_DIR),
            env={
                **os.environ,
                "PYTHONPATH": str(BACKEND_DIR),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            result.stdout + result.stderr
        )
        assert "OK" in result.stdout
