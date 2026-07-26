"""
Regression coverage for lifecycle scheduler extraction.
"""

from __future__ import annotations

from pathlib import Path
import ast
import asyncio
import hashlib
import inspect
import sys
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

EXPECTED_BODY_HASH = (
    "842b0098912ac669bf2428f96825b854c76e4b68efa7ac0c460a889bd93d6000"
)


def _body_hash(function_node):
    module = ast.Module(
        body=function_node.body,
        type_ignores=[],
    )

    return hashlib.sha256(
        ast.dump(
            module,
            include_attributes=False,
        ).encode("utf-8")
    ).hexdigest()


class TestSourceExtraction:
    def test_server_uses_canonical_coroutine(
        self,
    ):
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

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_startup_sync_status"
            )
        ]

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
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "startup_sync_status"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_registry_name_and_ownership_preserved(
        self,
    ):
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

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            task_names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if task_names == [
                "startup_sync_status"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        wrapper = wrappers[0]

        assert len(wrapper.args) == 1

        create_task = wrapper.args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "startup_sync_status"
        )

        logger_keywords = [
            keyword
            for keyword
            in coroutine_call.keywords
            if (
                keyword.arg == "logger"
                and isinstance(
                    keyword.value,
                    ast.Name,
                )
                and keyword.value.id
                == "logger"
            )
        ]

        assert len(logger_keywords) == 1

    def test_canonical_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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
                == "startup_sync_status"
            )
        )

        assert (
            _body_hash(function)
            == EXPECTED_BODY_HASH
        )

    def test_service_has_no_server_or_task_ownership(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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

        create_tasks = [
            node
            for node in ast.walk(tree)
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

    def test_canonical_signature(self):
        from services.lifecycle_scheduler_service import (
            startup_sync_status,
        )

        signature = inspect.signature(
            startup_sync_status
        )

        assert list(
            signature.parameters
        ) == ["logger"]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


def install_readiness_module(
    monkeypatch,
    sync_function,
):
    import routers

    readiness_module = ModuleType(
        "routers.readiness"
    )

    readiness_module.sync_readiness_to_status = (
        sync_function
    )

    monkeypatch.setitem(
        sys.modules,
        "routers.readiness",
        readiness_module,
    )

    monkeypatch.setattr(
        routers,
        "readiness",
        readiness_module,
        raising=False,
    )


class TestRuntimeBehavior:
    @pytest.mark.asyncio
    async def test_logs_autofiled_documents(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        sync = AsyncMock(
            return_value={
                "total_fixed": 3,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        sleep.assert_awaited_once_with(30)
        sync.assert_awaited_once_with()

        logger.info.assert_called_once_with(
            "[Startup] Sync-status auto-filed "
            "%d docs that were ready but "
            "sitting in inbox",
            3,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_clean_inbox(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        sync = AsyncMock(
            return_value={
                "total_fixed": 0,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        logger.info.assert_called_once_with(
            "[Startup] Sync-status check: "
            "inbox is clean, no docs to "
            "auto-file"
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        error = RuntimeError(
            "simulated readiness failure"
        )

        sync = AsyncMock(
            side_effect=error
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.startup_sync_status(
            logger=logger
        )

        logger.warning.assert_called_once_with(
            "[Startup] Sync-status "
            "auto-run failed: %s",
            error,
        )


class TestPeriodicSyncStatusExtraction:
    def test_server_uses_canonical_periodic_coroutine(
        self,
    ):
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

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_periodic_sync_status"
            )
        ]

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
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "periodic_sync_status"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_periodic_registry_ownership_preserved(
        self,
    ):
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

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == [
                "periodic_sync_status"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "periodic_sync_status"
        )

        logger_keywords = [
            keyword
            for keyword
            in coroutine_call.keywords
            if (
                keyword.arg == "logger"
                and isinstance(
                    keyword.value,
                    ast.Name,
                )
                and keyword.value.id
                == "logger"
            )
        ]

        assert len(logger_keywords) == 1

    def test_periodic_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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
                == "periodic_sync_status"
            )
        )

        assert (
            _body_hash(function)
            == "6545fc7060f4024d7410a7c17f6fb2b26c9f10213af853b5684fc2530581c766"
        )

    def test_periodic_signature(self):
        from services.lifecycle_scheduler_service import (
            periodic_sync_status,
        )

        signature = inspect.signature(
            periodic_sync_status
        )

        assert list(
            signature.parameters
        ) == ["logger"]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


class TestPeriodicSyncStatusRuntime:
    @pytest.mark.asyncio
    async def test_logs_fixed_documents(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        sync = AsyncMock(
            return_value={
                "total_fixed": 4,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        assert sleep.await_count == 2

        assert (
            sleep.await_args_list[
                0
            ].args
            == (120,)
        )

        assert (
            sleep.await_args_list[
                1
            ].args
            == (30 * 60,)
        )

        sync.assert_awaited_once_with()

        logger.info.assert_called_once_with(
            "[PeriodicSync] Sync-status "
            "auto-filed %d docs",
            4,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_changes_is_quiet(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        sync = AsyncMock(
            return_value={
                "total_fixed": 0,
            }
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        error = RuntimeError(
            "simulated periodic failure"
        )

        sync = AsyncMock(
            side_effect=error
        )

        install_readiness_module(
            monkeypatch,
            sync,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.periodic_sync_status(
                logger=logger
            )

        logger.warning.assert_called_once_with(
            "[PeriodicSync] Sync-status "
            "failed: %s",
            error,
        )


class TestStartupRequeueExtraction:
    def test_server_uses_canonical_requeue_coroutine(
        self,
    ):
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

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_startup_requeue_not_run"
            )
        ]

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
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "startup_requeue_not_run"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_requeue_registry_ownership_preserved(
        self,
    ):
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

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == [
                "startup_requeue_not_run"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "startup_requeue_not_run"
        )

        bindings = {
            keyword.arg: (
                keyword.value.id
                if isinstance(
                    keyword.value,
                    ast.Name,
                )
                else None
            )
            for keyword
            in coroutine_call.keywords
        }

        assert bindings == {
            "db": "db",
            "logger": "logger",
            "get_auto_resolve_service": (
                "get_auto_resolve_service"
            ),
        }

    def test_requeue_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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
                == "startup_requeue_not_run"
            )
        )

        assert (
            _body_hash(function)
            == "6b3dd938ecf63341997b733a70a3342f0db3da25f2a6fa968e8b20b5a32c1ca6"
        )

    def test_requeue_signature(self):
        from services.lifecycle_scheduler_service import (
            startup_requeue_not_run,
        )

        signature = inspect.signature(
            startup_requeue_not_run
        )

        assert list(
            signature.parameters
        ) == [
            "db",
            "logger",
            "get_auto_resolve_service",
        ]

        assert all(
            parameter.kind
            is inspect.Parameter.KEYWORD_ONLY
            for parameter
            in signature.parameters.values()
        )


class TestStartupRequeueRuntime:
    @pytest.mark.asyncio
    async def test_missing_service_exits_cleanly(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        getter = Mock(
            return_value=None
        )
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        await scheduler.startup_requeue_not_run(
            db=db,
            logger=logger,
            get_auto_resolve_service=getter,
        )

        sleep.assert_awaited_once_with(10)
        getter.assert_called_once_with()

        db.hub_documents.find.assert_not_called()
        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueues_not_run_documents(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        svc = Mock()
        svc.enqueue = AsyncMock()

        getter = Mock(
            return_value=svc
        )

        cursor = Mock()
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(
            return_value=[
                {"id": "doc-1"},
                {"id": "doc-2"},
            ]
        )

        db = Mock()
        db.hub_documents.find.return_value = cursor

        logger = Mock()

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        await scheduler.startup_requeue_not_run(
            db=db,
            logger=logger,
            get_auto_resolve_service=getter,
        )

        db.hub_documents.find.assert_called_once_with(
            {
                "reference_intelligence_status": {
                    "$in": [None, "not_run"]
                }
            },
            {"id": 1, "_id": 0},
        )

        cursor.limit.assert_called_once_with(
            500
        )

        cursor.to_list.assert_awaited_once_with(
            500
        )

        assert (
            svc.enqueue.await_count == 2
        )

        assert [
            call.args
            for call in svc.enqueue.await_args_list
        ] == [
            ("doc-1",),
            ("doc-2",),
        ]

        logger.info.assert_called_once_with(
            "[Startup] Re-queued %d "
            "documents with not_run ref "
            "intel status",
            2,
        )

    @pytest.mark.asyncio
    async def test_empty_query_logs_cleanly(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock()
        svc = Mock()
        svc.enqueue = AsyncMock()

        getter = Mock(
            return_value=svc
        )

        cursor = Mock()
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(
            return_value=[]
        )

        db = Mock()
        db.hub_documents.find.return_value = cursor

        logger = Mock()

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        await scheduler.startup_requeue_not_run(
            db=db,
            logger=logger,
            get_auto_resolve_service=getter,
        )

        svc.enqueue.assert_not_awaited()

        logger.info.assert_called_once_with(
            "[Startup] No not_run documents "
            "to re-queue"
        )


class TestCatalogSyncExtraction:
    def test_server_uses_canonical_catalog_coroutine(
        self,
    ):
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

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_catalog_sync_scheduler"
            )
        ]

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
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "catalog_sync_scheduler"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_catalog_registry_ownership_preserved(
        self,
    ):
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

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == ["catalog_sync"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "catalog_sync_scheduler"
        )

        bindings = {
            keyword.arg: (
                keyword.value.id
                if isinstance(
                    keyword.value,
                    ast.Name,
                )
                else None
            )
            for keyword
            in coroutine_call.keywords
        }

        assert bindings == {
            "db": "db",
            "logger": "logger",
        }

    def test_catalog_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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
                == "catalog_sync_scheduler"
            )
        )

        assert (
            _body_hash(function)
            == "a9b26801843f4abcf83cf4d99c358da670ed7d956f9f6090dfd4dfc64e58e953"
        )

    def test_catalog_signature(self):
        from services.lifecycle_scheduler_service import (
            catalog_sync_scheduler,
        )

        signature = inspect.signature(
            catalog_sync_scheduler
        )

        assert list(
            signature.parameters
        ) == [
            "db",
            "logger",
        ]

        assert all(
            parameter.kind
            is inspect.Parameter.KEYWORD_ONLY
            for parameter
            in signature.parameters.values()
        )


class TestCatalogSyncRuntime:
    @pytest.mark.asyncio
    async def test_runs_catalog_sync_and_logs(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        sync_all = AsyncMock(
            return_value={
                "items": 25,
                "gl_accounts": 8,
            }
        )

        catalog_module = ModuleType(
            "services.bc_catalog_sync_service"
        )

        catalog_module.sync_all = sync_all

        monkeypatch.setitem(
            sys.modules,
            "services.bc_catalog_sync_service",
            catalog_module,
        )

        monkeypatch.setattr(
            services,
            "bc_catalog_sync_service",
            catalog_module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.catalog_sync_scheduler(
                db=db,
                logger=logger,
            )

        assert sleep.await_count == 2

        assert (
            sleep.await_args_list[
                0
            ].args
            == (60,)
        )

        assert (
            sleep.await_args_list[
                1
            ].args
            == (24 * 3600,)
        )

        sync_all.assert_awaited_once_with(
            db
        )

        assert (
            logger.info.call_args_list[
                0
            ].args
            == (
                "[CatalogSync] Starting "
                "scheduled BC catalog sync",
            )
        )

        assert (
            logger.info.call_args_list[
                1
            ].args
            == (
                "[CatalogSync] Completed: %s",
                {
                    "items": 25,
                    "gl_accounts": 8,
                },
            )
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_catalog_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        error = RuntimeError(
            "simulated catalog failure"
        )

        sync_all = AsyncMock(
            side_effect=error
        )

        catalog_module = ModuleType(
            "services.bc_catalog_sync_service"
        )

        catalog_module.sync_all = sync_all

        monkeypatch.setitem(
            sys.modules,
            "services.bc_catalog_sync_service",
            catalog_module,
        )

        monkeypatch.setattr(
            services,
            "bc_catalog_sync_service",
            catalog_module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.catalog_sync_scheduler(
                db=db,
                logger=logger,
            )

        logger.warning.assert_called_once_with(
            "[CatalogSync] Scheduled sync "
            "failed: %s",
            error,
        )


class TestShipmentSyncExtraction:
    def test_server_uses_canonical_shipment_coroutine(
        self,
    ):
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

        nested = [
            node
            for node in startup.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "_shipment_sync_scheduler"
            )
        ]

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
                    "lifecycle_scheduler_service"
                )
                and any(
                    alias.name
                    == "shipment_sync_scheduler"
                    for alias in node.names
                )
            )
        ]

        assert nested == []
        assert len(imports) == 1

    def test_shipment_registry_ownership_preserved(
        self,
    ):
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

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == ["shipment_sync"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task,
            ast.Call,
        )

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert isinstance(
            coroutine_call,
            ast.Call,
        )

        assert isinstance(
            coroutine_call.func,
            ast.Name,
        )

        assert (
            coroutine_call.func.id
            == "shipment_sync_scheduler"
        )

        bindings = {
            keyword.arg: (
                keyword.value.id
                if isinstance(
                    keyword.value,
                    ast.Name,
                )
                else None
            )
            for keyword
            in coroutine_call.keywords
        }

        assert bindings == {
            "db": "db",
            "logger": "logger",
        }

    def test_shipment_body_matches_original(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
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
                == "shipment_sync_scheduler"
            )
        )

        assert (
            _body_hash(function)
            == "ac5a7f1f8b453c6c2c906a219364c90ef8bf8bd0b1d41090a2d1f9753c1bf009"
        )

    def test_shipment_signature(self):
        from services.lifecycle_scheduler_service import (
            shipment_sync_scheduler,
        )

        signature = inspect.signature(
            shipment_sync_scheduler
        )

        assert list(
            signature.parameters
        ) == [
            "db",
            "logger",
        ]

        assert all(
            parameter.kind
            is inspect.Parameter.KEYWORD_ONLY
            for parameter
            in signature.parameters.values()
        )


class TestShipmentSyncRuntime:
    @pytest.mark.asyncio
    async def test_runs_shipment_sync_and_logs(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        sync_bc_shipments = AsyncMock(
            return_value={
                "shipments": 7,
                "lines": 18,
            }
        )

        shipment_module = ModuleType(
            "services.inventory_so_integration"
        )

        shipment_module.sync_bc_shipments = (
            sync_bc_shipments
        )

        monkeypatch.setitem(
            sys.modules,
            "services.inventory_so_integration",
            shipment_module,
        )

        monkeypatch.setattr(
            services,
            "inventory_so_integration",
            shipment_module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.shipment_sync_scheduler(
                db=db,
                logger=logger,
            )

        assert sleep.await_count == 2

        assert (
            sleep.await_args_list[
                0
            ].args
            == (120,)
        )

        assert (
            sleep.await_args_list[
                1
            ].args
            == (3600,)
        )

        sync_bc_shipments.assert_awaited_once_with(
            db,
            lookback_hours=24,
        )

        assert (
            logger.info.call_args_list[
                0
            ].args
            == (
                "[ShipmentSync] Starting "
                "scheduled BC shipment sync",
            )
        )

        assert (
            logger.info.call_args_list[
                1
            ].args
            == (
                "[ShipmentSync] Completed: %s",
                {
                    "shipments": 7,
                    "lines": 18,
                },
            )
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_shipment_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        error = RuntimeError(
            "simulated shipment failure"
        )

        sync_bc_shipments = AsyncMock(
            side_effect=error
        )

        shipment_module = ModuleType(
            "services.inventory_so_integration"
        )

        shipment_module.sync_bc_shipments = (
            sync_bc_shipments
        )

        monkeypatch.setitem(
            sys.modules,
            "services.inventory_so_integration",
            shipment_module,
        )

        monkeypatch.setattr(
            services,
            "inventory_so_integration",
            shipment_module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.shipment_sync_scheduler(
                db=db,
                logger=logger,
            )

        sync_bc_shipments.assert_awaited_once_with(
            db,
            lookback_hours=24,
        )

        logger.warning.assert_called_once_with(
            "[ShipmentSync] Scheduled sync "
            "failed: %s",
            error,
        )


class TestDailyTraceExtraction:
    def test_source_registry_body_and_signature(self):
        tree = ast.parse(
            (BACKEND_DIR / "server.py").read_text()
        )

        startup = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "startup"
        )

        assert not any(
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_daily_trace_scheduler"
            for node in startup.body
        )

        imports = [
            node
            for node in ast.walk(startup)
            if isinstance(node, ast.ImportFrom)
            and node.module
            == "services.lifecycle_scheduler_service"
            and any(
                alias.name == "daily_trace_scheduler"
                for alias in node.names
            )
        ]

        assert len(imports) == 1

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "name"
                and isinstance(
                    keyword.value,
                    ast.Constant,
                )
            ]

            if names == ["daily_trace"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        coroutine_call = (
            wrappers[0].args[0].args[0]
        )

        assert (
            coroutine_call.func.id
            == "daily_trace_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword in coroutine_call.keywords
        } == {"logger": "logger"}

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "daily_trace_scheduler"
        )

        assert _body_hash(function) == "dd9ff7359a9cd41391c3a82559590833d6490a9f3be7455fb0197867a0c9b946"

        from services.lifecycle_scheduler_service import (
            daily_trace_scheduler,
        )

        signature = inspect.signature(
            daily_trace_scheduler
        )

        assert list(signature.parameters) == [
            "logger"
        ]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


class TestDailyTraceRuntime:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        import services.lifecycle_scheduler_service as scheduler

        run_daily_traces = AsyncMock(
            return_value={
                "traces_success": 8,
                "traces_requested": 10,
                "avg_match_rate": 92,
            }
        )

        module = __import__("types").ModuleType(
            "routers.posting_patterns"
        )

        module._run_daily_traces = (
            run_daily_traces
        )

        monkeypatch.setitem(
            __import__("sys").modules,
            "routers.posting_patterns",
            module,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.daily_trace_scheduler(
                logger=logger
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (120,),
            (24 * 3600,),
        ]

        run_daily_traces.assert_awaited_once_with()

        logger.info.assert_called_once_with(
            "[DailyTrace] Scheduler complete: "
            "%s/%s success, avg match=%s%%",
            8,
            10,
            92,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        error = RuntimeError(
            "simulated trace failure"
        )

        run_daily_traces = AsyncMock(
            side_effect=error
        )

        module = __import__("types").ModuleType(
            "routers.posting_patterns"
        )

        module._run_daily_traces = (
            run_daily_traces
        )

        monkeypatch.setitem(
            __import__("sys").modules,
            "routers.posting_patterns",
            module,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.daily_trace_scheduler(
                logger=logger
            )

        logger.warning.assert_called_once_with(
            "[DailyTrace] Scheduler failed: %s",
            error,
        )


class TestKnowledgeSeedExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        server_tree = ast.parse(
            (
                BACKEND_DIR
                / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in server_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name == "startup"
        )

        assert not any(
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_knowledge_seed_scheduler"
            for node in startup.body
        )

        imports = [
            node
            for node in ast.walk(startup)
            if isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module
            == (
                "services."
                "lifecycle_scheduler_service"
            )
            and any(
                alias.name
                == "knowledge_seed_scheduler"
                for alias in node.names
            )
        ]

        assert len(imports) == 1

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "name"
                and isinstance(
                    keyword.value,
                    ast.Constant,
                )
            ]

            if names == ["knowledge_seed"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert isinstance(
            create_task.func,
            ast.Attribute,
        )

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert (
            coroutine_call.func.id
            == "knowledge_seed_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "knowledge_seed_scheduler"
        )

        assert (
            _body_hash(function)
            == "1c9482a9c0a11a0e04828976156eb39ab8c95a8b52fc08cfaf10f57ebc3878b6"
        )

        from services.lifecycle_scheduler_service import (
            knowledge_seed_scheduler,
        )

        signature = inspect.signature(
            knowledge_seed_scheduler
        )

        assert list(
            signature.parameters
        ) == [
            "db",
            "logger",
        ]

        assert all(
            parameter.kind
            is inspect.Parameter.KEYWORD_ONLY
            for parameter
            in signature.parameters.values()
        )


class TestKnowledgeSeedRuntime:
    @pytest.mark.asyncio
    async def test_success(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        run_seed = AsyncMock(
            return_value={
                "vendor_aliases": {
                    "total_aliases": 14,
                },
                "vendor_profiles": {
                    "total_profiles": 9,
                },
                "sender_domains": {
                    "total_sender_mappings": 6,
                },
            }
        )

        module = ModuleType(
            "services.knowledge_seed_service"
        )

        module.run_full_knowledge_seed = (
            run_seed
        )

        monkeypatch.setitem(
            sys.modules,
            "services.knowledge_seed_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "knowledge_seed_service",
            module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.knowledge_seed_scheduler(
                db=db,
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (30,),
            (6 * 3600,),
        ]

        run_seed.assert_awaited_once_with(
            db
        )

        assert (
            logger.info.call_args_list[
                0
            ].args
            == (
                "[KnowledgeSeed] Starting "
                "scheduled knowledge seed",
            )
        )

        assert (
            logger.info.call_args_list[
                1
            ].args
            == (
                "[KnowledgeSeed] Scheduled "
                "seed complete: aliases=%s, "
                "profiles=%s, domains=%s",
                14,
                9,
                6,
            )
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        error = RuntimeError(
            "simulated seed failure"
        )

        run_seed = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "services.knowledge_seed_service"
        )

        module.run_full_knowledge_seed = (
            run_seed
        )

        monkeypatch.setitem(
            sys.modules,
            "services.knowledge_seed_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "knowledge_seed_service",
            module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.knowledge_seed_scheduler(
                db=db,
                logger=logger,
            )

        run_seed.assert_awaited_once_with(
            db
        )

        logger.warning.assert_called_once_with(
            "[KnowledgeSeed] Scheduled seed "
            "failed: %s",
            error,
        )


class TestPatternHygieneExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        server_tree = ast.parse(
            (
                BACKEND_DIR
                / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in server_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name == "startup"
        )

        assert not any(
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_intake_pattern_hygiene_scheduler"
            for node in startup.body
        )

        imports = [
            node
            for node in ast.walk(startup)
            if isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module
            == (
                "services."
                "lifecycle_scheduler_service"
            )
            and any(
                alias.name
                == "intake_pattern_hygiene_scheduler"
                for alias in node.names
            )
        ]

        assert len(imports) == 1

        wrappers = []

        for node in ast.walk(startup):
            if not (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            ):
                continue

            names = [
                keyword.value.value
                for keyword in node.keywords
                if (
                    keyword.arg == "name"
                    and isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                )
            ]

            if names == [
                "intake_pattern_hygiene"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        coroutine_call = (
            create_task.args[0]
        )

        assert (
            coroutine_call.func.id
            == "intake_pattern_hygiene_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "intake_pattern_hygiene_scheduler"
        )

        assert (
            _body_hash(function)
            == "4aecbab0dc43b9753cacceaa4cfa9b0ab2a0bbe6ffe65101ca602d8e532af383"
        )

        from services.lifecycle_scheduler_service import (
            intake_pattern_hygiene_scheduler,
        )

        signature = inspect.signature(
            intake_pattern_hygiene_scheduler
        )

        assert list(
            signature.parameters
        ) == ["logger"]

        assert (
            signature.parameters[
                "logger"
            ].kind
            is inspect.Parameter.KEYWORD_ONLY
        )


class TestPatternHygieneRuntime:
    @pytest.mark.asyncio
    async def test_success(
        self,
        monkeypatch,
    ):
        import workflows.core
        import services.lifecycle_scheduler_service as scheduler

        run_hygiene = AsyncMock(
            return_value={
                "total_scanned": 80,
                "total_retired": 5,
                "total_promoted": 3,
            }
        )

        module = ModuleType(
            "workflows.core.learning_core"
        )

        module.run_hygiene = run_hygiene

        monkeypatch.setitem(
            sys.modules,
            "workflows.core.learning_core",
            module,
        )

        monkeypatch.setattr(
            workflows.core,
            "learning_core",
            module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.intake_pattern_hygiene_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (600,),
            (24 * 3600,),
        ]

        run_hygiene.assert_awaited_once_with(
            domain="all",
            actor="scheduler",
        )

        logger.info.assert_called_once_with(
            "[PatternHygiene.scheduler] "
            "done — scanned=%d retired=%d "
            "promoted=%d",
            80,
            5,
            3,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import workflows.core
        import services.lifecycle_scheduler_service as scheduler

        error = RuntimeError(
            "simulated hygiene failure"
        )

        run_hygiene = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "workflows.core.learning_core"
        )

        module.run_hygiene = run_hygiene

        monkeypatch.setitem(
            sys.modules,
            "workflows.core.learning_core",
            module,
        )

        monkeypatch.setattr(
            workflows.core,
            "learning_core",
            module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                asyncio.CancelledError(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        with pytest.raises(
            asyncio.CancelledError
        ):
            await scheduler.intake_pattern_hygiene_scheduler(
                logger=logger,
            )

        run_hygiene.assert_awaited_once_with(
            domain="all",
            actor="scheduler",
        )

        logger.warning.assert_called_once_with(
            "[PatternHygiene.scheduler] "
            "failed: %s",
            error,
        )
