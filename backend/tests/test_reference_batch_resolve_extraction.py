"""
Parity tests for batch_auto_resolve extraction.
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

import pytest
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "reference_batch_resolve_extraction_baseline.json"
)


def _baseline() -> dict:
    return json.loads(
        BASELINE_PATH.read_text()
    )


def _normalized_service_source() -> str:
    from services.reference_batch_resolve_service import (
        batch_auto_resolve,
    )

    source = textwrap.dedent(
        inspect.getsource(batch_auto_resolve)
    )

    return (
        "\n".join(
            line.rstrip()
            for line in source.splitlines()
        )
        + "\n"
    )


class _FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)
        self.limit_value = None
        self.to_list_value = None

    def limit(self, value):
        self.limit_value = value
        return self

    async def to_list(self, value):
        self.to_list_value = value
        return self.documents[:value]


class _FakeCollection:
    def __init__(self, documents):
        self.documents = list(documents)
        self.find_calls = []
        self.update_calls = []
        self.cursor = None

    def find(self, query, projection):
        self.find_calls.append(
            (query, projection)
        )
        self.cursor = _FakeCursor(
            self.documents
        )
        return self.cursor

    async def update_one(self, query, update):
        self.update_calls.append(
            (query, update)
        )


class _FakeDb:
    def __init__(self, documents):
        self.hub_documents = _FakeCollection(
            documents
        )


class _FakeService:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, doc_id):
        self.enqueued.append(doc_id)


class TestBatchResolveSourceParity:
    def test_baseline_is_present(self):
        baseline = _baseline()

        assert (
            baseline["pre_move_module"]
            == "server"
        )
        assert (
            baseline["authoritative_module"]
            == "services.reference_batch_resolve_service"
        )
        assert (
            baseline["signature_parameters"]
            == ["limit", "status_filter"]
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
        from services.reference_batch_resolve_service import (
            batch_auto_resolve,
        )

        signature = inspect.signature(
            batch_auto_resolve
        )

        assert list(signature.parameters) == [
            "limit",
            "status_filter",
        ]
        assert inspect.iscoroutinefunction(
            batch_auto_resolve
        )


class TestBatchResolveDependencies:
    def test_service_has_no_server_import(self):
        source = (
            BACKEND_DIR
            / "services"
            / "reference_batch_resolve_service.py"
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
            / "reference_batch_resolve_service.py"
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
        assert (
            "get_auto_resolve_service"
            in imports[
                "services.auto_resolution_service"
            ]
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
            and item.name == "batch_auto_resolve"
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
            == "services.reference_batch_resolve_service"
        )
        assert len(import_node.names) == 1
        assert (
            import_node.names[0].name
            == "batch_auto_resolve"
        )
        assert (
            import_node.names[0].asname
            == "_impl"
        )

    def test_wrapper_signature_matches_service(self):
        import server
        from services.reference_batch_resolve_service import (
            batch_auto_resolve,
        )

        assert list(
            inspect.signature(
                server.batch_auto_resolve
            ).parameters
        ) == list(
            inspect.signature(
                batch_auto_resolve
            ).parameters
        )


class TestRouterRewire:
    def test_router_imports_service(self):
        source = (
            BACKEND_DIR
            / "routers"
            / "reference_intelligence.py"
        ).read_text()

        tree = ast.parse(source)

        register_node = next(
            item
            for item in tree.body
            if isinstance(
                item,
                ast.FunctionDef,
            )
            and item.name
            == "register_server_routes"
        )

        imports = [
            item
            for item in ast.walk(register_node)
            if isinstance(item, ast.ImportFrom)
        ]

        assert any(
            item.module
            == "services.reference_batch_resolve_service"
            and any(
                alias.name == "batch_auto_resolve"
                for alias in item.names
            )
            for item in imports
        )

        assert not any(
            item.module == "server"
            and any(
                alias.name == "batch_auto_resolve"
                for alias in item.names
            )
            for item in imports
        )

    def test_router_imports_cleanly(self):
        module = importlib.import_module(
            "routers.reference_intelligence"
        )
        assert module is not None


class TestBatchResolveBehavior:
    @pytest.mark.asyncio
    async def test_needs_review_filter(
        self,
        monkeypatch,
    ):
        import services.reference_batch_resolve_service as module

        fake_db = _FakeDb([
            {"id": "doc-1"},
            {"id": "doc-2"},
            {"id": "doc-3"},
        ])
        fake_service = _FakeService()

        monkeypatch.setattr(
            module,
            "db",
            fake_db,
        )
        monkeypatch.setattr(
            module,
            "get_auto_resolve_service",
            lambda: fake_service,
        )

        result = await module.batch_auto_resolve(
            limit=2,
            status_filter="NeedsReview",
        )

        assert fake_db.hub_documents.find_calls == [
            (
                {"status": "NeedsReview"},
                {"id": 1, "_id": 0},
            )
        ]
        assert (
            fake_db.hub_documents.cursor.limit_value
            == 2
        )
        assert (
            fake_db.hub_documents.cursor.to_list_value
            == 2
        )
        assert fake_service.enqueued == [
            "doc-1",
            "doc-2",
        ]
        assert len(
            fake_db.hub_documents.update_calls
        ) == 2
        assert result == {
            "status": "batch_queued",
            "enqueued": 2,
            "filter": "NeedsReview",
        }

    @pytest.mark.asyncio
    async def test_not_run_filter(
        self,
        monkeypatch,
    ):
        import services.reference_batch_resolve_service as module

        fake_db = _FakeDb([
            {"id": "doc-9"},
        ])
        fake_service = _FakeService()

        monkeypatch.setattr(
            module,
            "db",
            fake_db,
        )
        monkeypatch.setattr(
            module,
            "get_auto_resolve_service",
            lambda: fake_service,
        )

        result = await module.batch_auto_resolve(
            limit=50,
            status_filter="not_run",
        )

        assert fake_db.hub_documents.find_calls == [
            (
                {
                    "reference_intelligence_status": {
                        "$in": [None, "not_run"],
                    },
                },
                {"id": 1, "_id": 0},
            )
        ]
        assert fake_service.enqueued == [
            "doc-9"
        ]
        assert result["enqueued"] == 1
        assert result["filter"] == "not_run"

    @pytest.mark.asyncio
    async def test_unknown_filter_uses_open_query(
        self,
        monkeypatch,
    ):
        import services.reference_batch_resolve_service as module

        fake_db = _FakeDb([])
        fake_service = _FakeService()

        monkeypatch.setattr(
            module,
            "db",
            fake_db,
        )
        monkeypatch.setattr(
            module,
            "get_auto_resolve_service",
            lambda: fake_service,
        )

        result = await module.batch_auto_resolve(
            limit=10,
            status_filter="all",
        )

        assert fake_db.hub_documents.find_calls == [
            ({}, {"id": 1, "_id": 0})
        ]
        assert result == {
            "status": "batch_queued",
            "enqueued": 0,
            "filter": "all",
        }

    @pytest.mark.asyncio
    async def test_missing_service_returns_503(
        self,
        monkeypatch,
    ):
        import services.reference_batch_resolve_service as module

        monkeypatch.setattr(
            module,
            "get_auto_resolve_service",
            lambda: None,
        )

        with pytest.raises(
            HTTPException
        ) as error:
            await module.batch_auto_resolve(
                limit=10,
                status_filter="NeedsReview",
            )

        assert error.value.status_code == 503


class TestReverseImportSafety:
    def test_service_then_server(self):
        script = textwrap.dedent(
            """
            import services.reference_batch_resolve_service as svc
            import server
            assert hasattr(svc, "batch_auto_resolve")
            assert hasattr(server, "batch_auto_resolve")
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
            import services.reference_batch_resolve_service as svc
            assert hasattr(server, "batch_auto_resolve")
            assert hasattr(svc, "batch_auto_resolve")
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
