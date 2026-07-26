"""
Parity tests for removal of two unreferenced server compatibility wrappers.
"""

from __future__ import annotations

from pathlib import Path
import ast
import importlib
import inspect


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

REMOVED_WRAPPERS = {
    "_aggregate_document_types_data": (
        "services.dashboard_helpers",
        "aggregate_document_types_data",
    ),
    "_get_category_for_doc_type": (
        "services.classification_helpers",
        "get_category_for_doc_type",
    ),
}


class TestRemovedWrappers:
    def test_server_definitions_are_gone(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        definitions = {
            node.name
            for node in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

        assert (
            definitions
            & set(REMOVED_WRAPPERS)
            == set()
        )

    def test_canonical_targets_remain_callable(self):
        for (
            _wrapper_name,
            (
                module_name,
                target_name,
            ),
        ) in REMOVED_WRAPPERS.items():
            module = importlib.import_module(
                module_name
            )
            target = getattr(
                module,
                target_name,
                None,
            )

            assert target is not None
            assert callable(target)

    def test_no_ast_references_remain(self):
        violations = []

        for path in BACKEND_DIR.rglob(
            "*.py"
        ):
            if path.name.endswith(".bak"):
                continue

            tree = ast.parse(
                path.read_text()
            )

            for node in ast.walk(tree):
                if (
                    isinstance(
                        node,
                        ast.Name,
                    )
                    and isinstance(
                        node.ctx,
                        ast.Load,
                    )
                    and node.id
                    in REMOVED_WRAPPERS
                ):
                    violations.append(
                        f"{path}:"
                        f"{node.lineno}:"
                        f"{node.id}"
                    )

                elif (
                    isinstance(
                        node,
                        ast.Attribute,
                    )
                    and isinstance(
                        node.ctx,
                        ast.Load,
                    )
                    and node.attr
                    in REMOVED_WRAPPERS
                ):
                    violations.append(
                        f"{path}:"
                        f"{node.lineno}:"
                        f"{node.attr}"
                    )

        assert violations == []


class TestCanonicalShape:
    def test_dashboard_target_is_async(self):
        from services.dashboard_helpers import (
            aggregate_document_types_data,
        )

        assert inspect.iscoroutinefunction(
            aggregate_document_types_data
        )

    def test_category_target_is_sync(self):
        from services.classification_helpers import (
            get_category_for_doc_type,
        )

        assert not inspect.iscoroutinefunction(
            get_category_for_doc_type
        )
