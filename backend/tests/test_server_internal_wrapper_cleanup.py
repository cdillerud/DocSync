"""
Regression coverage for retirement of seven server-internal wrappers.
"""

from __future__ import annotations

from pathlib import Path
import ast
import importlib
import inspect


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

DIRECT_IMPORTS = {
    "create_purchase_invoice_header": (
        "services.bc_draft_service",
        "create_purchase_invoice_header",
    ),
    "is_eligible_for_draft_creation": (
        "services.ap_computation",
        "is_eligible_for_draft_creation",
    ),
    "move_email_to_folder": (
        "services.email_polling_service",
        "move_email_to_folder",
    ),
    "run_upload_and_link_workflow": (
        "services.document_orchestration_service",
        "run_upload_and_link_workflow",
    ),
}

REMOVED_WORKERS = {
    "_sales_email_polling_worker",
    "dynamic_mailbox_polling_worker",
    "email_polling_worker",
}

EXPECTED_DIRECT_USES = {
    "create_purchase_invoice_header": 1,
    "is_eligible_for_draft_creation": 1,
    "move_email_to_folder": 2,
    "run_upload_and_link_workflow": 3,
}

EXPECTED_WORKER_USES = {
    "_sales_email_polling_worker": 1,
    "dynamic_mailbox_polling_worker": 1,
    "email_polling_worker": 1,
}


class TestWrapperDefinitionsRemoved:
    def test_all_seven_definitions_are_removed(self):
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

        targets = (
            set(DIRECT_IMPORTS)
            | REMOVED_WORKERS
        )

        assert definitions & targets == set()


class TestCanonicalServerBindings:
    def test_direct_import_map_is_exact(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        bindings = {}

        for node in tree.body:
            if not isinstance(
                node,
                ast.ImportFrom,
            ):
                continue

            for alias in node.names:
                bound_name = (
                    alias.asname
                    or alias.name
                )

                if bound_name in DIRECT_IMPORTS:
                    bindings[bound_name] = (
                        node.module,
                        alias.name,
                    )

        assert bindings == DIRECT_IMPORTS

    def test_server_exports_canonical_objects(self):
        import server

        for (
            bound_name,
            (
                module_name,
                target_name,
            ),
        ) in DIRECT_IMPORTS.items():
            module = importlib.import_module(
                module_name
            )

            canonical = getattr(
                module,
                target_name,
            )

            assert (
                getattr(server, bound_name)
                is canonical
            )

    def test_server_signatures_match(self):
        import server

        for (
            bound_name,
            (
                module_name,
                target_name,
            ),
        ) in DIRECT_IMPORTS.items():
            module = importlib.import_module(
                module_name
            )

            canonical = getattr(
                module,
                target_name,
            )

            assert (
                inspect.signature(
                    getattr(server, bound_name)
                )
                == inspect.signature(
                    canonical
                )
            )


class TestCallSitesPreserved:
    def test_direct_internal_use_counts(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        counts = {
            name: 0
            for name in DIRECT_IMPORTS
        }

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(
                    node.ctx,
                    ast.Load,
                )
                and node.id in counts
            ):
                counts[node.id] += 1

        assert counts == EXPECTED_DIRECT_USES

    def test_startup_calls_service_worker_attributes(self):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        counts = {
            name: 0
            for name in REMOVED_WORKERS
        }

        for node in ast.walk(tree):
            if not isinstance(
                node,
                ast.Attribute,
            ):
                continue

            if not isinstance(
                node.value,
                ast.Name,
            ):
                continue

            if (
                node.value.id
                == "email_polling_svc"
                and node.attr in counts
            ):
                counts[node.attr] += 1

        assert counts == EXPECTED_WORKER_USES
