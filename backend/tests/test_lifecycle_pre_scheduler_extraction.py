"""
Regression coverage for pre-scheduler startup extraction.
"""

from __future__ import annotations

from pathlib import Path
import ast
from unittest.mock import AsyncMock, Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)


class FakeCursor:
    def __init__(
        self,
        documents,
        error=None,
    ):
        self.documents = documents
        self.error = error

    async def to_list(self, limit):
        if self.error:
            raise self.error

        return list(
            self.documents[:limit]
        )


class FakeCollection:
    def __init__(
        self,
        database,
        name,
    ):
        self.database = database
        self.name = name

    async def create_index(
        self,
        *args,
        **kwargs,
    ):
        self.database.index_calls.append(
            (
                self.name,
                args,
                kwargs,
            )
        )

        return "index"

    async def find_one(self, query):
        self.database.find_one_calls.append(
            (
                self.name,
                query,
            )
        )

        if self.name == "hub_job_types":
            return {"exists": True}

        if self.name == "vendor_aliases":
            return {"exists": True}

        return None

    async def insert_one(self, document):
        self.database.insert_calls.append(
            (
                self.name,
                document,
            )
        )

        return Mock(
            inserted_id="inserted"
        )

    def find(
        self,
        query,
        projection,
    ):
        self.database.find_calls.append(
            (
                self.name,
                query,
                projection,
            )
        )

        if self.name == "vendor_aliases":
            return FakeCursor(
                self.database.alias_documents
            )

        if self.name == "hub_bc_vendors":
            return FakeCursor(
                self.database.bc_vendor_documents,
                self.database.bc_vendor_error,
            )

        return FakeCursor([])


class FakeDB:
    def __init__(
        self,
        *,
        alias_documents=None,
        bc_vendor_documents=None,
        bc_vendor_error=None,
    ):
        self.alias_documents = (
            alias_documents or []
        )

        self.bc_vendor_documents = (
            bc_vendor_documents or []
        )

        self.bc_vendor_error = (
            bc_vendor_error
        )

        self.index_calls = []
        self.find_one_calls = []
        self.insert_calls = []
        self.find_calls = []
        self.collections = {}

    def __getattr__(self, name):
        if name not in self.collections:
            self.collections[name] = (
                FakeCollection(
                    self,
                    name,
                )
            )

        return self.collections[name]


def patch_dependencies(monkeypatch):
    import deps
    import sales_module
    import services.file_ingestion_service as file_ingestion
    import services.routing_feedback_service as routing_feedback
    import services.spiro.spiro_sync as spiro_sync

    dependencies = {
        "set_sales_db": Mock(),
        "initialize_sales_indexes": AsyncMock(),
        "configure_sales_email_polling": Mock(),
        "set_file_ingestion_db": Mock(),
        "set_deps_db": Mock(),
        "set_spiro_db": Mock(),
        "init_feedback_db": Mock(),
    }

    monkeypatch.setattr(
        sales_module,
        "set_db",
        dependencies["set_sales_db"],
    )

    monkeypatch.setattr(
        sales_module,
        "initialize_sales_indexes",
        dependencies[
            "initialize_sales_indexes"
        ],
    )

    monkeypatch.setattr(
        sales_module,
        "configure_sales_email_polling",
        dependencies[
            "configure_sales_email_polling"
        ],
    )

    monkeypatch.setattr(
        file_ingestion,
        "set_file_ingestion_db",
        dependencies[
            "set_file_ingestion_db"
        ],
    )

    monkeypatch.setattr(
        deps,
        "set_db",
        dependencies["set_deps_db"],
    )

    monkeypatch.setattr(
        spiro_sync,
        "set_spiro_db",
        dependencies["set_spiro_db"],
    )

    monkeypatch.setattr(
        routing_feedback,
        "init_feedback_db",
        dependencies[
            "init_feedback_db"
        ],
    )

    return dependencies


class TestSourceExtraction:
    def test_server_delegates_and_preserves_aliases(self):
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

        assignments = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(
                        target,
                        ast.Name,
                    )
                    and target.id == "aliases"
                    for target in node.targets
                )
                and isinstance(
                    node.value,
                    ast.Await,
                )
                and isinstance(
                    node.value.value,
                    ast.Call,
                )
                and isinstance(
                    node.value.value.func,
                    ast.Name,
                )
                and node.value.value.func.id
                == (
                    "initialize_"
                    "pre_scheduler_services"
                )
            )
        ]

        assert len(assignments) == 1

    def test_service_has_no_server_or_task_ownership(self):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_startup_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == (
                    "initialize_"
                    "pre_scheduler_services"
                )
            )
        )

        server_imports = [
            node
            for node in ast.walk(function)
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

        create_tasks = [
            node
            for node in ast.walk(function)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and isinstance(
                    node.func.value,
                    ast.Name,
                )
                and node.func.value.id
                == "asyncio"
                and node.func.attr
                == "create_task"
            )
        ]

        assert server_imports == []
        assert create_tasks == []


class TestRuntimeParity:
    @pytest.mark.asyncio
    async def test_initializes_services_and_aliases(
        self,
        monkeypatch,
    ):
        from services.lifecycle_startup_service import (
            initialize_pre_scheduler_services,
        )

        dependencies = patch_dependencies(
            monkeypatch
        )

        alias_documents = [
            {
                "alias_string": "Example Co",
                "normalized_alias": "example",
                "vendor_name": "Example Company",
                "vendor_no": "EXAMPLE",
            }
        ]

        db = FakeDB(
            alias_documents=alias_documents,
        )

        logger = Mock()
        load_config = AsyncMock()
        vendor_alias_map = {}

        aliases = (
            await initialize_pre_scheduler_services(
                db=db,
                logger=logger,
                sales_email_polling_enabled=True,
                sales_email_polling_user=(
                    "sales@example.com"
                ),
                sales_email_polling_interval_minutes=9,
                load_config_from_db=load_config,
                default_job_types={
                    "A": {
                        "job_type": "A",
                    },
                    "B": {
                        "job_type": "B",
                    },
                },
                vendor_alias_map=(
                    vendor_alias_map
                ),
            )
        )

        assert aliases == alias_documents

        dependencies[
            "set_sales_db"
        ].assert_called_once_with(db)

        dependencies[
            "initialize_sales_indexes"
        ].assert_awaited_once_with(db)

        dependencies[
            "set_file_ingestion_db"
        ].assert_called_once_with(db)

        dependencies[
            "set_deps_db"
        ].assert_called_once_with(db)

        dependencies[
            "set_spiro_db"
        ].assert_called_once_with(db)

        dependencies[
            "init_feedback_db"
        ].assert_called_once_with(db)

        dependencies[
            "configure_sales_email_polling"
        ].assert_called_once_with(
            enabled=True,
            mailbox="sales@example.com",
            interval_minutes=9,
        )

        load_config.assert_awaited_once_with()

        assert vendor_alias_map == {
            "Example Co": "Example Company",
            "example": "Example Company",
        }

        assert db.insert_calls == []

        assert db.index_calls == [
            (
                "routing_feedback",
                ("routing_key",),
                {"unique": True},
            ),
            (
                "routing_feedback",
                ("confidence",),
                {},
            ),
            (
                "sender_vendor_map",
                ("sender_email",),
                {},
            ),
            (
                "sender_vendor_map",
                ("sender_domain",),
                {},
            ),
            (
                "spiro_contacts",
                ("spiro_id",),
                {"unique": True},
            ),
            (
                "spiro_contacts",
                ("email",),
                {},
            ),
            (
                "spiro_contacts",
                ("email_domain",),
                {},
            ),
            (
                "spiro_contacts",
                ("company_id",),
                {},
            ),
            (
                "spiro_companies",
                ("spiro_id",),
                {"unique": True},
            ),
            (
                "spiro_companies",
                ("name_normalized",),
                {},
            ),
            (
                "spiro_companies",
                ("email_domain",),
                {},
            ),
            (
                "spiro_opportunities",
                ("spiro_id",),
                {"unique": True},
            ),
            (
                "spiro_opportunities",
                ("company_id",),
                {},
            ),
            (
                "spiro_sync_status",
                ("entity_type",),
                {"unique": True},
            ),
        ]

    @pytest.mark.asyncio
    async def test_bc_bootstrap_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        from services.lifecycle_startup_service import (
            initialize_pre_scheduler_services,
        )

        patch_dependencies(
            monkeypatch
        )

        db = FakeDB(
            bc_vendor_error=RuntimeError(
                "simulated BC vendor failure"
            )
        )

        logger = Mock()

        aliases = (
            await initialize_pre_scheduler_services(
                db=db,
                logger=logger,
                sales_email_polling_enabled=False,
                sales_email_polling_user="",
                sales_email_polling_interval_minutes=5,
                load_config_from_db=AsyncMock(),
                default_job_types={},
                vendor_alias_map={},
            )
        )

        assert aliases == []

        warning_messages = [
            call.args[0]
            for call in logger.warning.call_args_list
        ]

        assert any(
            "BC vendor alias bootstrap failed"
            in message
            for message in warning_messages
        )
