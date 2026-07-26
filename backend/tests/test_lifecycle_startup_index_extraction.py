"""
Regression coverage for core startup-index extraction.
"""

from __future__ import annotations

from pathlib import Path
import ast
from unittest.mock import Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

def _source_order_create_index_calls():
    """
    Read create_index calls in source execution order.

    ast.walk() is breadth-first and does not preserve
    statement order around try/except blocks.
    """
    service_path = (
        BACKEND_DIR
        / "services"
        / "lifecycle_startup_service.py"
    )

    tree = ast.parse(
        service_path.read_text()
    )

    ordered_calls = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        func = node.func

        if not (
            isinstance(
                func,
                ast.Attribute,
            )
            and func.attr == "create_index"
            and isinstance(
                func.value,
                ast.Attribute,
            )
            and isinstance(
                func.value.value,
                ast.Name,
            )
            and func.value.value.id == "db"
        ):
            continue

        collection_name = (
            func.value.attr
        )

        args = tuple(
            ast.literal_eval(argument)
            for argument in node.args
        )

        kwargs = {
            keyword.arg:
            ast.literal_eval(
                keyword.value
            )
            for keyword in node.keywords
        }

        ordered_calls.append(
            (
                node.lineno,
                node.col_offset,
                (
                    collection_name,
                    args,
                    kwargs,
                ),
            )
        )

    ordered_calls.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    return [
        call
        for _, _, call
        in ordered_calls
    ]


EXPECTED_CREATE_INDEX_CALLS = (
    _source_order_create_index_calls()
)


class FakeCollection:
    def __init__(
        self,
        name,
        calls,
        fail_named_index=None,
    ):
        self.name = name
        self.calls = calls
        self.fail_named_index = (
            fail_named_index
        )

    async def create_index(
        self,
        *args,
        **kwargs,
    ):
        self.calls.append(
            (
                self.name,
                args,
                kwargs,
            )
        )

        if (
            self.fail_named_index
            and kwargs.get("name")
            == self.fail_named_index
        ):
            raise RuntimeError(
                "simulated index failure"
            )

        return kwargs.get("name") or "index"


class FakeDB:
    def __init__(
        self,
        *,
        fail_named_index=None,
    ):
        self.calls = []
        self.fail_named_index = (
            fail_named_index
        )
        self.collections = {}

    def __getattr__(self, name):
        if name not in self.collections:
            self.collections[name] = (
                FakeCollection(
                    name,
                    self.calls,
                    self.fail_named_index,
                )
            )

        return self.collections[name]


class TestSourceExtraction:
    def test_server_startup_delegates_once(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                == (
                    "services."
                    "lifecycle_startup_service"
                )
                and any(
                    alias.name
                    == "initialize_core_indexes"
                    for alias in node.names
                )
            )
        ]

        calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "initialize_core_indexes"
            )
        ]

        assert len(imports) == 1
        assert len(calls) == 1

    def test_startup_service_has_no_server_import(self):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_startup_service.py"
            ).read_text()
        )

        server_imports = [
            node
            for node in ast.walk(tree)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                in {
                    "server",
                    "backend.server",
                }
            )
            or (
                isinstance(
                    node,
                    ast.Import,
                )
                and any(
                    alias.name
                    in {
                        "server",
                        "backend.server",
                    }
                    for alias in node.names
                )
            )
        ]

        assert server_imports == []


class TestRuntimeParity:
    @pytest.mark.asyncio
    async def test_exact_index_calls_and_order(self):
        from services.lifecycle_startup_service import (
            initialize_core_indexes,
        )

        db = FakeDB()
        logger = Mock()

        await initialize_core_indexes(
            db=db,
            logger=logger,
        )

        assert (
            db.calls
            == EXPECTED_CREATE_INDEX_CALLS
        )

    @pytest.mark.asyncio
    async def test_fulltext_failure_is_nonfatal(self):
        from services.lifecycle_startup_service import (
            initialize_core_indexes,
        )

        db = FakeDB(
            fail_named_index=(
                "hub_documents_fulltext"
            )
        )
        logger = Mock()

        await initialize_core_indexes(
            db=db,
            logger=logger,
        )

        logger.warning.assert_called_once()

        warning_args = (
            logger.warning.call_args.args
        )

        assert (
            "Full-text index creation skipped"
            in warning_args[0]
        )

        fulltext_position = next(
            index
            for index, call
            in enumerate(
                EXPECTED_CREATE_INDEX_CALLS
            )
            if call[2].get("name")
            == "hub_documents_fulltext"
        )

        assert (
            db.calls[
                fulltext_position + 1:
            ]
            == EXPECTED_CREATE_INDEX_CALLS[
                fulltext_position + 1:
            ]
        )
