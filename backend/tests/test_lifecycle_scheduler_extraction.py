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

    def test_server_delegates_status_sync_task_ownership(
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

        helper_imports = [
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
                    == "start_status_sync_tasks"
                    for alias in node.names
                )
            )
        ]

        legacy_imports = [
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
                    alias.name in {
                        "startup_sync_status",
                        "periodic_sync_status",
                    }
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
                == "start_status_sync_tasks"
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id in {
                    "startup_sync_status",
                    "periodic_sync_status",
                }
            )
        ]

        assert len(helper_imports) == 1
        assert legacy_imports == []
        assert len(calls) == 1
        assert direct_calls == []

        assert {
            keyword.arg: keyword.value.id
            for keyword in calls[0].keywords
        } == {
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }


    def test_registry_name_and_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_status_sync_tasks"
            )
        )

        wrappers = [
            node
            for node in ast.walk(helper)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "register_background_task"
            )
        ]

        assert len(wrappers) == 2

        observed = {}

        for wrapper in wrappers:
            task_name = next(
                keyword.value.value
                for keyword in wrapper.keywords
                if keyword.arg == "name"
            )

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

            coroutine = create_task.args[0]

            assert isinstance(
                coroutine.func,
                ast.Name,
            )

            observed[task_name] = {
                keyword.arg: keyword.value.id
                for keyword
                in coroutine.keywords
            }

        assert observed == {
            "startup_sync_status": {
                "logger": "logger",
            },
            "periodic_sync_status": {
                "logger": "logger",
            },
        }

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


    def test_service_has_no_server_dependency_and_limited_task_ownership(
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
                and node.module in {
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
                    alias.name in {
                        "server",
                        "backend.server",
                    }
                    for alias in node.names
                )
            )
        ]

        parents = {}

        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(
                node
            ):
                parents[child] = node

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

        owners = []

        for create_task in create_tasks:
            current = parents.get(
                create_task
            )

            while current is not None:
                if isinstance(
                    current,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                ):
                    owners.append(
                        current.name
                    )
                    break

                current = parents.get(
                    current
                )

        assert server_imports == []
        assert len(create_tasks) == 26

        assert sorted(owners) == [
            "start_bc_maintenance_tasks",
            "start_bc_maintenance_tasks",
            "start_captured_retry_tasks",
            "start_catalog_sync_tasks",
            "start_draft_feedback_tasks",
            "start_email_polling_tasks",
            "start_email_polling_tasks",
            "start_email_polling_tasks",
            "start_inside_sales_pilot_tasks",
            "start_intake_learning_tasks",
            "start_intake_learning_tasks",
            "start_intelligence_tasks",
            "start_intelligence_tasks",
            "start_learning_reporting_tasks",
            "start_learning_reporting_tasks",
            "start_monitoring_tasks",
            "start_monitoring_tasks",
            "start_pi_backfill_tasks",
            "start_pilot_summary_tasks",
            "start_po_retry_tasks",
            "start_ready_to_post_tasks",
            "start_startup_repair_tasks",
            "start_startup_repair_tasks",
            "start_startup_requeue_tasks",
            "start_status_sync_tasks",
            "start_status_sync_tasks",
        ]

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

    def test_server_no_longer_owns_periodic_coroutine(
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

        periodic_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "periodic_sync_status"
                    for alias in node.names
                )
            )
        ]

        periodic_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "periodic_sync_status"
            )
        ]

        ownership_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_status_sync_tasks"
            )
        ]

        assert periodic_imports == []
        assert periodic_calls == []
        assert len(ownership_calls) == 1


    def test_periodic_registry_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_status_sync_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
        coroutine = create_task.args[0]

        assert (
            coroutine.func.id
            == "periodic_sync_status"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "logger": "logger",
        }

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


def _assert_server_delegates_lifecycle_task(
    helper_name,
    scheduler_name,
):
    tree = ast.parse(
        (BACKEND_DIR / "server.py").read_text()
    )
    startup = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "startup"
    )

    imports = [
        alias.name
        for node in ast.walk(startup)
        if isinstance(node, ast.ImportFrom)
        and node.module
        == "services.lifecycle_scheduler_service"
        for alias in node.names
    ]
    calls = [
        node.func.id
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    ]

    assert imports.count(helper_name) == 1
    assert calls.count(helper_name) == 1
    assert scheduler_name not in imports
    assert scheduler_name not in calls
    assert not [
        node
        for statement in startup.body
        for node in ast.walk(statement)
        if isinstance(node, ast.AsyncFunctionDef)
    ]


def _assert_lifecycle_helper_ownership(
    helper_name,
    scheduler_name,
    registry_name,
    expected_bindings,
):
    tree = ast.parse(
        (
            BACKEND_DIR
            / "services"
            / "lifecycle_scheduler_service.py"
        ).read_text()
    )
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == helper_name
    )

    wrappers = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "register_background_task"
        and any(
            keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == registry_name
            for keyword in node.keywords
        )
    ]

    assert len(wrappers) == 1
    create_task = wrappers[0].args[0]
    assert isinstance(create_task, ast.Call)
    assert isinstance(create_task.func, ast.Attribute)
    assert create_task.func.attr == "create_task"

    coroutine = create_task.args[0]
    assert isinstance(coroutine, ast.Call)
    assert isinstance(coroutine.func, ast.Name)
    assert coroutine.func.id == scheduler_name

    bindings = {
        keyword.arg: (
            keyword.value.id
            if isinstance(keyword.value, ast.Name)
            else None
        )
        for keyword in coroutine.keywords
    }
    assert bindings == expected_bindings


def _assert_lifecycle_scheduler_contract(
    scheduler_name,
    expected_body_hash,
    expected_parameters,
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
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == scheduler_name
    )
    assert _body_hash(function) == expected_body_hash

    import services.lifecycle_scheduler_service as scheduler
    signature = inspect.signature(
        getattr(scheduler, scheduler_name)
    )
    assert list(signature.parameters) == expected_parameters
    assert all(
        parameter.kind
        is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


class TestStartupRequeueExtraction:
    def test_server_uses_canonical_requeue_coroutine(
        self,
    ):
        _assert_server_delegates_lifecycle_task(
            "start_startup_requeue_tasks",
            "startup_requeue_not_run",
        )

    def test_requeue_registry_ownership_preserved(
        self,
    ):
        _assert_lifecycle_helper_ownership(
            "start_startup_requeue_tasks",
            "startup_requeue_not_run",
            "startup_requeue_not_run",
            {
                "db": "db",
                "logger": "logger",
                "get_auto_resolve_service":
                    "get_auto_resolve_service",
            },
        )

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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "catalog_sync_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "catalog_sync_scheduler"
            )
        ]

        helper_imports = [
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
                    == "start_catalog_sync_tasks"
                    for alias in node.names
                )
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_catalog_sync_tasks"
            )
        ]

        assert nested == []
        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_imports) == 1
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

    def test_catalog_registry_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_catalog_sync_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "shipment_sync_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "shipment_sync_scheduler"
            )
        ]

        helper_imports = [
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
                    == "start_bc_maintenance_tasks"
                    for alias in node.names
                )
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_bc_maintenance_tasks"
            )
        ]

        assert nested == []
        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_imports) == 1
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

    def test_shipment_registry_ownership_preserved(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_bc_maintenance_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "daily_trace_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "daily_trace_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_monitoring_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_monitoring_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
                "daily_trace"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine_call.func.id
            == "daily_trace_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

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

        assert (
            _body_hash(function)
            == "dd9ff7359a9cd41391c3a82559590833d6490a9f3be7455fb0197867a0c9b946"
        )

        from services.lifecycle_scheduler_service import (
            daily_trace_scheduler,
        )

        signature = inspect.signature(
            daily_trace_scheduler
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "knowledge_seed_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "knowledge_seed_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_bc_maintenance_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_bc_maintenance_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "intake_pattern_hygiene_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "intake_pattern_hygiene_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_intake_learning_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_intake_learning_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
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


class TestDriftAlertExtraction:
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "drift_alert_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "drift_alert_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_learning_reporting_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_learning_reporting_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
                "drift_alert"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine_call.func.id
            == "drift_alert_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "drift_alert_scheduler"
        )

        assert (
            _body_hash(function)
            == "d59460658d0b45de09c5909c02710c47c200500a8acac37727a3fc3108be8cb0"
        )

        from services.lifecycle_scheduler_service import (
            drift_alert_scheduler,
        )

        signature = inspect.signature(
            drift_alert_scheduler
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


class TestDriftAlertRuntime:
    @pytest.mark.asyncio
    async def test_success(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        run_drift_scan = AsyncMock(
            return_value={
                "rules_fired": 4,
                "open_alerts_total": 11,
            }
        )

        module = ModuleType(
            "services.drift_alert_service"
        )

        module.run_drift_scan = (
            run_drift_scan
        )

        monkeypatch.setitem(
            sys.modules,
            "services.drift_alert_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "drift_alert_service",
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
            await scheduler.drift_alert_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (900,),
            (24 * 3600,),
        ]

        run_drift_scan.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.info.assert_called_once_with(
            "[DriftAlerts.scheduler] "
            "done — fired=%d open_total=%d",
            4,
            11,
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
            "simulated drift scan failure"
        )

        run_drift_scan = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "services.drift_alert_service"
        )

        module.run_drift_scan = (
            run_drift_scan
        )

        monkeypatch.setitem(
            sys.modules,
            "services.drift_alert_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "drift_alert_service",
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
            await scheduler.drift_alert_scheduler(
                logger=logger,
            )

        run_drift_scan.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.warning.assert_called_once_with(
            "[DriftAlerts.scheduler] "
            "failed: %s",
            error,
        )


class TestWeeklyDigestExtraction:
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "weekly_digest_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "weekly_digest_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_learning_reporting_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_learning_reporting_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
                "weekly_digest"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine_call.func.id
            == "weekly_digest_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "weekly_digest_scheduler"
        )

        assert (
            _body_hash(function)
            == "32832b5937ee75d34c7c0ec01f057f3a008f89c6e6a6c8a47cdf5533e3765153"
        )

        from services.lifecycle_scheduler_service import (
            weekly_digest_scheduler,
        )

        signature = inspect.signature(
            weekly_digest_scheduler
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


class TestWeeklyDigestRuntime:
    @pytest.mark.asyncio
    async def test_success(
        self,
        monkeypatch,
    ):
        import workflows.core
        import services.lifecycle_scheduler_service as scheduler

        build_weekly_digest = AsyncMock(
            return_value={
                "week_key": "2026-W30",
                "events": {
                    "total": 48,
                },
                "top_reviewers": [
                    {"name": "One"},
                    {"name": "Two"},
                    {"name": "Three"},
                ],
                "drift_summary": {
                    "total_new": 7,
                },
            }
        )

        module = ModuleType(
            "workflows.core.learning_core"
        )

        module.build_weekly_digest = (
            build_weekly_digest
        )

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
            await scheduler.weekly_digest_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (1200,),
            (24 * 3600,),
        ]

        build_weekly_digest.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.info.assert_called_once_with(
            "[WeeklyDigest.scheduler] "
            "built %s — events=%d reviewers=%d "
            "drift=%d",
            "2026-W30",
            48,
            3,
            7,
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
            "simulated digest failure"
        )

        build_weekly_digest = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "workflows.core.learning_core"
        )

        module.build_weekly_digest = (
            build_weekly_digest
        )

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
            await scheduler.weekly_digest_scheduler(
                logger=logger,
            )

        build_weekly_digest.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.warning.assert_called_once_with(
            "[WeeklyDigest.scheduler] "
            "failed: %s",
            error,
        )


class TestIntakeLearningRefreshExtraction:
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "intake_learning_refresh_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "intake_learning_refresh_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_intake_learning_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_intake_learning_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
                "intake_learning_refresh"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine_call.func.id
            == "intake_learning_refresh_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "intake_learning_refresh_scheduler"
        )

        assert (
            _body_hash(function)
            == "a9d97505a40b74f1bde205ccadecab29972fcf26b54cbab29773e792fa4022a3"
        )

        from services.lifecycle_scheduler_service import (
            intake_learning_refresh_scheduler,
        )

        signature = inspect.signature(
            intake_learning_refresh_scheduler
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


class TestIntakeLearningRefreshRuntime:
    @pytest.mark.asyncio
    async def test_success(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "INTAKE_LEARNING_LOOKBACK_HOURS",
            "36",
        )

        monkeypatch.setenv(
            "INTAKE_LEARNING_INTERVAL_SECONDS",
            "1234",
        )

        refresh_active_customers = AsyncMock(
            return_value={
                "active_customers": 8,
                "docs_refreshed": 27,
                "xls_refreshed": 4,
            }
        )

        module = ModuleType(
            "services.sales_intake_learning_service"
        )

        module.refresh_active_customers = (
            refresh_active_customers
        )

        monkeypatch.setitem(
            sys.modules,
            "services.sales_intake_learning_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "sales_intake_learning_service",
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
            await scheduler.intake_learning_refresh_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (300,),
            (1234,),
        ]

        refresh_active_customers.assert_awaited_once_with(
            lookback_hours=36,
        )

        assert (
            logger.info.call_args_list[
                0
            ].args
            == (
                "[IntakeLearning.scheduler] "
                "Starting daily refresh "
                "(lookback=%dh)",
                36,
            )
        )

        assert (
            logger.info.call_args_list[
                1
            ].args
            == (
                "[IntakeLearning.scheduler] "
                "done — customers=%d docs=%d "
                "xls=%d",
                8,
                27,
                4,
            )
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_environment_values(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.delenv(
            "INTAKE_LEARNING_LOOKBACK_HOURS",
            raising=False,
        )

        monkeypatch.delenv(
            "INTAKE_LEARNING_INTERVAL_SECONDS",
            raising=False,
        )

        refresh_active_customers = AsyncMock(
            return_value={}
        )

        module = ModuleType(
            "services.sales_intake_learning_service"
        )

        module.refresh_active_customers = (
            refresh_active_customers
        )

        monkeypatch.setitem(
            sys.modules,
            "services.sales_intake_learning_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "sales_intake_learning_service",
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
            await scheduler.intake_learning_refresh_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (300,),
            (24 * 3600,),
        ]

        refresh_active_customers.assert_awaited_once_with(
            lookback_hours=24,
        )

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "INTAKE_LEARNING_LOOKBACK_HOURS",
            "12",
        )

        monkeypatch.setenv(
            "INTAKE_LEARNING_INTERVAL_SECONDS",
            "777",
        )

        error = RuntimeError(
            "simulated intake refresh failure"
        )

        refresh_active_customers = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "services.sales_intake_learning_service"
        )

        module.refresh_active_customers = (
            refresh_active_customers
        )

        monkeypatch.setitem(
            sys.modules,
            "services.sales_intake_learning_service",
            module,
        )

        monkeypatch.setattr(
            services,
            "sales_intake_learning_service",
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
            await scheduler.intake_learning_refresh_scheduler(
                logger=logger,
            )

        refresh_active_customers.assert_awaited_once_with(
            lookback_hours=12,
        )

        logger.warning.assert_called_once_with(
            "[IntakeLearning.scheduler] "
            "failed: %s",
            error,
        )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (300,),
            (777,),
        ]


class TestDriftWatchlistExtraction:
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

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "drift_watchlist_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "drift_watchlist_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_monitoring_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_monitoring_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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
                "drift_watchlist"
            ]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine_call = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine_call.func.id
            == "drift_watchlist_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine_call.keywords
        } == {
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "drift_watchlist_scheduler"
        )

        assert (
            _body_hash(function)
            == "d508ef124ec7f92b94049730b37d8dd2ce7cb7f8811ba92e0624a8fcbe8481e8"
        )

        from services.lifecycle_scheduler_service import (
            drift_watchlist_scheduler,
        )

        signature = inspect.signature(
            drift_watchlist_scheduler
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


class TestDriftWatchlistRuntime:
    @pytest.mark.asyncio
    async def test_disabled_by_default(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.delenv(
            "DRIFT_WATCHLIST_ENABLED",
            raising=False,
        )

        monkeypatch.delenv(
            "DRIFT_WATCHLIST_CRON_DOW",
            raising=False,
        )

        monkeypatch.delenv(
            "DRIFT_WATCHLIST_CRON_HOUR",
            raising=False,
        )

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        logger = Mock()

        await scheduler.drift_watchlist_scheduler(
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            1500
        )

        logger.info.assert_called_once_with(
            "Drift Watchlist scheduler "
            "disabled "
            "(set DRIFT_WATCHLIST_ENABLED=true "
            "to enable)"
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_window_dispatches(
        self,
        monkeypatch,
    ):
        import workflows.core.learning_core
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_ENABLED",
            "true",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_DOW",
            "0",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_HOUR",
            "7",
        )

        class FixedDateTime:
            @classmethod
            def now(cls):
                from datetime import (
                    datetime as real_datetime,
                )

                return real_datetime(
                    2026,
                    7,
                    27,
                    7,
                    15,
                    0,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        send_watchlist = AsyncMock(
            return_value={
                "vendor_count": 6,
                "per_channel": {
                    "teams_webhook": {
                        "ok": True,
                    },
                    "email": {
                        "ok": True,
                    },
                },
            }
        )

        module = ModuleType(
            "workflows.core.learning_core."
            "drift_watchlist_service"
        )

        module.send_watchlist = (
            send_watchlist
        )

        monkeypatch.setitem(
            sys.modules,
            (
                "workflows.core.learning_core."
                "drift_watchlist_service"
            ),
            module,
        )

        monkeypatch.setattr(
            workflows.core.learning_core,
            "drift_watchlist_service",
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
            await scheduler.drift_watchlist_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call
            in sleep.await_args_list
        ] == [
            (1500,),
            (3600,),
        ]

        send_watchlist.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.info.assert_called_once_with(
            "[DriftWatchlist.scheduler] "
            "dispatched: vendors=%d "
            "channels=%s",
            6,
            [
                "teams_webhook",
                "email",
            ],
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_day_dispatches_once(
        self,
        monkeypatch,
    ):
        import workflows.core.learning_core
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_ENABLED",
            "yes",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_DOW",
            "0",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_HOUR",
            "7",
        )

        class FixedDateTime:
            @classmethod
            def now(cls):
                from datetime import (
                    datetime as real_datetime,
                )

                return real_datetime(
                    2026,
                    7,
                    27,
                    7,
                    30,
                    0,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        send_watchlist = AsyncMock(
            return_value={
                "vendor_count": 2,
                "per_channel": {
                    "email": {
                        "ok": True,
                    },
                },
            }
        )

        module = ModuleType(
            "workflows.core.learning_core."
            "drift_watchlist_service"
        )

        module.send_watchlist = (
            send_watchlist
        )

        monkeypatch.setitem(
            sys.modules,
            (
                "workflows.core.learning_core."
                "drift_watchlist_service"
            ),
            module,
        )

        monkeypatch.setattr(
            workflows.core.learning_core,
            "drift_watchlist_service",
            module,
            raising=False,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
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
            await scheduler.drift_watchlist_scheduler(
                logger=logger,
            )

        assert [
            call.args
            for call
            in sleep.await_args_list
        ] == [
            (1500,),
            (3600,),
            (3600,),
        ]

        send_watchlist.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.info.assert_called_once()

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonmatching_window_skips(
        self,
        monkeypatch,
    ):
        import workflows.core.learning_core
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_ENABLED",
            "1",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_DOW",
            "0",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_HOUR",
            "7",
        )

        class FixedDateTime:
            @classmethod
            def now(cls):
                from datetime import (
                    datetime as real_datetime,
                )

                return real_datetime(
                    2026,
                    7,
                    28,
                    7,
                    0,
                    0,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        send_watchlist = AsyncMock()

        module = ModuleType(
            "workflows.core.learning_core."
            "drift_watchlist_service"
        )

        module.send_watchlist = (
            send_watchlist
        )

        monkeypatch.setitem(
            sys.modules,
            (
                "workflows.core.learning_core."
                "drift_watchlist_service"
            ),
            module,
        )

        monkeypatch.setattr(
            workflows.core.learning_core,
            "drift_watchlist_service",
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
            await scheduler.drift_watchlist_scheduler(
                logger=logger,
            )

        send_watchlist.assert_not_awaited()

        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import workflows.core.learning_core
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_ENABLED",
            "true",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_DOW",
            "0",
        )

        monkeypatch.setenv(
            "DRIFT_WATCHLIST_CRON_HOUR",
            "7",
        )

        class FixedDateTime:
            @classmethod
            def now(cls):
                from datetime import (
                    datetime as real_datetime,
                )

                return real_datetime(
                    2026,
                    7,
                    27,
                    7,
                    0,
                    0,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        error = RuntimeError(
            "simulated watchlist failure"
        )

        send_watchlist = AsyncMock(
            side_effect=error
        )

        module = ModuleType(
            "workflows.core.learning_core."
            "drift_watchlist_service"
        )

        module.send_watchlist = (
            send_watchlist
        )

        monkeypatch.setitem(
            sys.modules,
            (
                "workflows.core.learning_core."
                "drift_watchlist_service"
            ),
            module,
        )

        monkeypatch.setattr(
            workflows.core.learning_core,
            "drift_watchlist_service",
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
            await scheduler.drift_watchlist_scheduler(
                logger=logger,
            )

        send_watchlist.assert_awaited_once_with(
            actor="scheduler",
        )

        logger.warning.assert_called_once_with(
            "[DriftWatchlist.scheduler] "
            "tick failed: %s",
            error,
        )


class TestStartupNoiseCleanupExtraction:
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
            == "_startup_clean_noise_learning_events"
            for node in startup.body
        )

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "startup_clean_noise_learning_events"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "startup_clean_noise_learning_events"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_startup_repair_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_startup_repair_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

            if names == ["startup_clean_noise_learning_events"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine.func.id
            == "startup_clean_noise_learning_events"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "startup_clean_noise_learning_events"
            )
        )

        assert (
            _body_hash(function)
            == "d49c6afbc0f0986ece81e76ff66195acfe1e87e5599e9fedd6524294376b00d7"
        )

        from services.lifecycle_scheduler_service import (
            startup_clean_noise_learning_events,
        )

        signature = inspect.signature(
            startup_clean_noise_learning_events
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


class TestStartupNoiseCleanupRuntime:
    @pytest.mark.asyncio
    async def test_removes_all_noise_categories(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()

        collection.count_documents = AsyncMock(
            side_effect=[
                2,
                3,
                4,
            ]
        )

        collection.delete_many = AsyncMock(
            side_effect=[
                Mock(deleted_count=2),
                Mock(deleted_count=3),
                Mock(deleted_count=4),
            ]
        )

        db = Mock()
        db.posting_learning_events = collection

        logger = Mock()

        await scheduler.startup_clean_noise_learning_events(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            45
        )

        assert (
            collection.count_documents.await_count
            == 3
        )

        assert (
            collection.delete_many.await_count
            == 3
        )

        assert [
            call.args
            for call
            in logger.info.call_args_list
        ] == [
            (
                "[Startup] Cleaned %d noise "
                "events from "
                "posting_learning_events "
                "(readiness self-corrections)",
                2,
            ),
            (
                "[Startup] Cleaned %d "
                "blank-vendor/zero-amount "
                "noise events from "
                "posting_learning_events",
                3,
            ),
            (
                "[Startup] Cleaned %d ghost "
                "learning events "
                "($0/no-lines/no-items)",
                4,
            ),
        ]

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_clean_collection_skips_deletes(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()

        collection.count_documents = AsyncMock(
            side_effect=[
                0,
                0,
                0,
            ]
        )

        collection.delete_many = AsyncMock()

        db = Mock()
        db.posting_learning_events = collection

        logger = Mock()

        await scheduler.startup_clean_noise_learning_events(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            45
        )

        assert (
            collection.count_documents.await_count
            == 3
        )

        collection.delete_many.assert_not_awaited()

        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated cleanup failure"
        )

        collection = Mock()

        collection.count_documents = AsyncMock(
            side_effect=error
        )

        collection.delete_many = AsyncMock()

        db = Mock()
        db.posting_learning_events = collection

        logger = Mock()

        await scheduler.startup_clean_noise_learning_events(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            45
        )

        collection.delete_many.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[Startup] Noise event cleanup "
            "failed: %s",
            error,
        )


class TestStartupShippingPOFixExtraction:
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
            == "_startup_fix_shipping_po_escalations"
            for node in startup.body
        )

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "startup_fix_shipping_po_escalations"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "startup_fix_shipping_po_escalations"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_startup_repair_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_startup_repair_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

            if names == ["startup_fix_shipping_po_escalations"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine.func.id
            == "startup_fix_shipping_po_escalations"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "startup_fix_shipping_po_escalations"
            )
        )

        assert (
            _body_hash(function)
            == "a565914464dd32ec54bff185447251c49a0f828061093eec411ad9da8b9bd902"
        )

        from services.lifecycle_scheduler_service import (
            startup_fix_shipping_po_escalations,
        )

        signature = inspect.signature(
            startup_fix_shipping_po_escalations
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


class TestStartupShippingPOFixRuntime:
    @pytest.mark.asyncio
    async def test_updates_both_shipping_error_states(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()

        collection.update_many = AsyncMock(
            side_effect=[
                Mock(modified_count=2),
                Mock(modified_count=3),
            ]
        )

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_fix_shipping_po_escalations(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            12
        )

        assert (
            collection.update_many.await_count
            == 2
        )

        first_query = (
            collection.update_many
            .await_args_list[0]
            .args[0]
        )

        first_update = (
            collection.update_many
            .await_args_list[0]
            .args[1]
        )

        second_query = (
            collection.update_many
            .await_args_list[1]
            .args[0]
        )

        second_update = (
            collection.update_many
            .await_args_list[1]
            .args[1]
        )

        assert (
            first_query[
                "po_pending_parked"
            ]
            is True
        )

        assert (
            first_update["$set"][
                "po_pending_parked"
            ]
            is False
        )

        assert (
            first_update["$unset"][
                "escalation_reason"
            ]
            == ""
        )

        assert (
            second_query[
                "escalation_reason"
            ]["$regex"]
            == "PO not found"
        )

        assert (
            second_query[
                "escalation_reason"
            ]["$options"]
            == "i"
        )

        assert (
            second_update["$set"][
                "po_pending_parked"
            ]
            is False
        )

        assert (
            second_update["$unset"]
            == {
                "escalation_reason": "",
                "auto_escalated": "",
            }
        )

        logger.info.assert_called_once_with(
            "[Startup] Fixed %d incorrectly "
            "PO-parked + %d incorrectly "
            "escalated non-AP docs",
            2,
            3,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_modifications_skips_info_log(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()

        collection.update_many = AsyncMock(
            side_effect=[
                Mock(modified_count=0),
                Mock(modified_count=0),
            ]
        )

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_fix_shipping_po_escalations(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            12
        )

        assert (
            collection.update_many.await_count
            == 2
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
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated shipping fix failure"
        )

        collection = Mock()

        collection.update_many = AsyncMock(
            side_effect=error
        )

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_fix_shipping_po_escalations(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            12
        )

        logger.warning.assert_called_once_with(
            "[Startup] Shipping "
            "PO-escalation fix failed: %s",
            error,
        )


class TestStartupPINumberBackfillExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        _assert_server_delegates_lifecycle_task(
            "start_pi_backfill_tasks",
            "startup_backfill_pi_no",
        )
        _assert_lifecycle_helper_ownership(
            "start_pi_backfill_tasks",
            "startup_backfill_pi_no",
            "startup_backfill_pi_no",
            {
                "db": "db",
                "logger": "logger",
            },
        )
        _assert_lifecycle_scheduler_contract(
            "startup_backfill_pi_no",
            "679d9e0b57e5a28aad94b993b6ef599f4f16e3b13d2c41093ece797c4d4bb62d",
            ["db", "logger"],
        )


class TestStartupPINumberBackfillRuntime:
    @pytest.mark.asyncio
    async def test_backfills_valid_pi_numbers(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        class AsyncCursor:
            def __init__(
                self,
                documents,
            ):
                self._iterator = iter(
                    documents
                )

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(
                        self._iterator
                    )
                except StopIteration:
                    raise StopAsyncIteration

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        documents = [
            {
                "id": "doc-1",
                "bc_purchase_invoice": {
                    "bc_record_no": "PI-1001",
                },
            },
            {
                "id": "doc-2",
                "bc_purchase_invoice": {
                    "bc_record_no": "",
                },
            },
            {
                "id": "doc-3",
                "bc_purchase_invoice": {
                    "bc_record_no": "PI-1003",
                },
            },
            {
                "id": "doc-4",
                "bc_purchase_invoice": None,
            },
        ]

        collection = Mock()

        collection.find = Mock(
            return_value=AsyncCursor(
                documents
            )
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_backfill_pi_no(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            15
        )

        collection.find.assert_called_once_with(
            {
                (
                    "bc_purchase_invoice."
                    "bc_record_no"
                ): {
                    "$exists": True,
                    "$nin": [
                        None,
                        "",
                    ],
                },
                "$or": [
                    {
                        "bc_purchase_invoice_no": {
                            "$exists": False,
                        },
                    },
                    {
                        "bc_purchase_invoice_no": None,
                    },
                    {
                        "bc_purchase_invoice_no": "",
                    },
                ],
            },
            {
                "_id": 0,
                "id": 1,
                (
                    "bc_purchase_invoice."
                    "bc_record_no"
                ): 1,
            },
        )

        assert (
            collection.update_one.await_count
            == 2
        )

        assert [
            call.args
            for call
            in collection.update_one.await_args_list
        ] == [
            (
                {
                    "id": "doc-1",
                },
                {
                    "$set": {
                        "bc_purchase_invoice_no": "PI-1001",
                    },
                },
            ),
            (
                {
                    "id": "doc-3",
                },
                {
                    "$set": {
                        "bc_purchase_invoice_no": "PI-1003",
                    },
                },
            ),
        ]

        logger.info.assert_called_once_with(
            "[Startup] Backfilled "
            "bc_purchase_invoice_no on "
            "%d documents",
            2,
        )

        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_valid_numbers_skips_updates(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        class AsyncCursor:
            def __init__(
                self,
                documents,
            ):
                self._iterator = iter(
                    documents
                )

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(
                        self._iterator
                    )
                except StopIteration:
                    raise StopAsyncIteration

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()

        collection.find = Mock(
            return_value=AsyncCursor(
                [
                    {
                        "id": "doc-1",
                        "bc_purchase_invoice": {
                            "bc_record_no": "",
                        },
                    },
                    {
                        "id": "doc-2",
                        "bc_purchase_invoice": None,
                    },
                ]
            )
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_backfill_pi_no(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            15
        )

        collection.update_one.assert_not_awaited()

        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            return_value=None
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated PI backfill failure"
        )

        collection = Mock()

        collection.find = Mock(
            side_effect=error
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        await scheduler.startup_backfill_pi_no(
            db=db,
            logger=logger,
        )

        sleep.assert_awaited_once_with(
            15
        )

        collection.update_one.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[Startup] PI no backfill "
            "failed: %s",
            error,
        )


class TestDeepLearningExtraction:
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
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        assert not any(
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_deep_learning_scheduler"
            for node in startup.body
        )

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "deep_learning_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "deep_learning_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_intelligence_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_intelligence_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

            if names == ["deep_learning"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine.func.id
            == "deep_learning_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "deep_learning_scheduler"
            )
        )

        assert (
            _body_hash(function)
            == "68bfb7601679614c15c43b1e20d460cefbd8acf964d8db6cc2c8e238a4e6110e"
        )

        from services.lifecycle_scheduler_service import (
            deep_learning_scheduler,
        )

        signature = inspect.signature(
            deep_learning_scheduler
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


class TestDeepLearningRuntime:
    @pytest.mark.asyncio
    async def test_runs_audit_and_vendor_maturity(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        audit = AsyncMock(
            return_value={
                "audited": 100,
                "drifts": 4,
                "drift_rate": 0.04,
            }
        )

        maturity = AsyncMock(
            return_value={
                "computed": 12,
                "levels": {
                    "mature": 8,
                    "learning": 4,
                },
            }
        )

        module = ModuleType(
            "services.deep_learning_engine"
        )

        module.run_self_correction_audit = audit
        module.compute_all_vendor_maturity = maturity

        monkeypatch.setitem(
            sys.modules,
            "services.deep_learning_engine",
            module,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.deep_learning_scheduler(
                db=db,
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (300,),
            (4 * 3600,),
        ]

        audit.assert_awaited_once_with(
            db,
            sample_size=100,
        )

        maturity.assert_awaited_once_with(
            db
        )

        logger.info.assert_any_call(
            "[DeepLearning] Running scheduled "
            "self-correction audit + "
            "vendor maturity..."
        )

        logger.info.assert_any_call(
            "[DeepLearning] Self-correction: "
            "%d audited, %d drifts (%.1f%%)",
            100,
            4,
            4.0,
        )

        logger.info.assert_any_call(
            "[DeepLearning] Vendor maturity: "
            "%d vendors scored, levels=%s",
            12,
            {
                "mature": 8,
                "learning": 4,
            },
        )

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
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated deep learning failure"
        )

        audit = AsyncMock(
            side_effect=error
        )

        maturity = AsyncMock()

        module = ModuleType(
            "services.deep_learning_engine"
        )

        module.run_self_correction_audit = audit
        module.compute_all_vendor_maturity = maturity

        monkeypatch.setitem(
            sys.modules,
            "services.deep_learning_engine",
            module,
        )

        db = Mock()
        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.deep_learning_scheduler(
                db=db,
                logger=logger,
            )

        audit.assert_awaited_once_with(
            db,
            sample_size=100,
        )

        maturity.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[DeepLearning] Scheduled deep "
            "learning failed: %s",
            error,
        )


class TestDraftFeedbackExtraction:
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
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        assert not any(
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_draft_feedback_sync_scheduler"
            for node in startup.body
        )

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "draft_feedback_sync_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "draft_feedback_sync_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_draft_feedback_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_draft_feedback_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

            if names == ["draft_feedback_sync"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine.func.id
            == "draft_feedback_sync_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "draft_feedback_sync_scheduler"
            )
        )

        assert (
            _body_hash(function)
            == "a13282b312ffca016cf3c63e76440b8965817dd7a6d0a9aa11957aa980f853fb"
        )

        from services.lifecycle_scheduler_service import (
            draft_feedback_sync_scheduler,
        )

        signature = inspect.signature(
            draft_feedback_sync_scheduler
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


class TestDraftFeedbackRuntime:
    @pytest.mark.asyncio
    async def test_runs_all_learning_stages(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        process_feedback_batch = AsyncMock(
            return_value={
                "processed": 3,
                "changes_found": 1,
                "no_changes": 2,
                "errors": 0,
            }
        )

        run_all_learning_engines = AsyncMock(
            return_value={
                "posted_draft_detection": {
                    "posted_found": 2,
                },
                "cross_vendor_learning": {
                    "propagated_to_vendors": 4,
                },
                "confidence_auto_promotion": {
                    "promoted": ["V100"],
                    "demoted": [],
                },
            }
        )

        auto_approve_drafts = AsyncMock(
            return_value={
                "approved": 2,
                "skipped": 1,
            }
        )

        learn_from_posting = AsyncMock()

        feedback_module = ModuleType(
            "services.draft_feedback_service"
        )

        feedback_module.process_feedback_batch = (
            process_feedback_batch
        )

        learning_module = ModuleType(
            "services.continuous_learning_service"
        )

        learning_module.run_all_learning_engines = (
            run_all_learning_engines
        )

        posting_module = ModuleType(
            "routers.posting_patterns"
        )

        posting_module.auto_approve_drafts = (
            auto_approve_drafts
        )

        analyzer_module = ModuleType(
            "services.posting_pattern_analyzer"
        )

        analyzer_module.learn_from_posting = (
            learn_from_posting
        )

        monkeypatch.setitem(
            sys.modules,
            "services.draft_feedback_service",
            feedback_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.continuous_learning_service",
            learning_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "routers.posting_patterns",
            posting_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.posting_pattern_analyzer",
            analyzer_module,
        )

        cursor = Mock()

        cursor.limit = Mock(
            return_value=cursor
        )

        cursor.to_list = AsyncMock(
            return_value=[
                {
                    "id": "doc-1",
                    "bc_vendor_number": "V100",
                    "bc_purchase_invoice": {
                        "lines": [
                            {
                                "no": "ITEM-1",
                                "description": "Widget",
                                "quantity": 2,
                                "directUnitCost": 12.50,
                                "amountIncludingVAT": 25.00,
                            },
                        ],
                    },
                },
            ]
        )

        collection = Mock()

        collection.find = Mock(
            return_value=cursor
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.draft_feedback_sync_scheduler(
                db=db,
                logger=logger,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (300,),
            (2 * 3600,),
        ]

        process_feedback_batch.assert_awaited_once_with(
            db,
            limit=100,
        )

        run_all_learning_engines.assert_awaited_once_with(
            db
        )

        auto_approve_drafts.assert_awaited_once_with(
            min_vendor_invoices=5,
            min_confidence="medium",
            dry_run=False,
            limit=500,
        )

        collection.find.assert_called_once()

        cursor.limit.assert_called_once_with(
            50
        )

        cursor.to_list.assert_awaited_once_with(
            50
        )

        expected_lines = [
            {
                "No_": "ITEM-1",
                "Description": "Widget",
                "Quantity": 2,
                "Direct_Unit_Cost": 12.50,
                "Amount": 25.00,
            },
        ]

        learn_from_posting.assert_awaited_once_with(
            db,
            "doc-1",
            "V100",
            expected_lines,
            result_status="Posted",
            source="bc_sync_backfill",
        )

        collection.update_one.assert_awaited_once_with(
            {
                "id": "doc-1",
            },
            {
                "$set": {
                    "amount_learning_backfilled": True,
                },
            },
        )

        logger.warning.assert_not_called()

        logger.info.assert_any_call(
            "[DraftFeedback] Sync complete: "
            "processed=%d, changes=%d, "
            "no_changes=%d, errors=%d",
            3,
            1,
            2,
            0,
        )

        logger.info.assert_any_call(
            "[DraftAutoApprove] Auto-approved "
            "%d drafts, skipped %d",
            2,
            1,
        )

        logger.info.assert_any_call(
            "[VendorLearnBackfill] Backfilled "
            "learning data for %d docs",
            1,
        )

    @pytest.mark.asyncio
    async def test_stage_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated feedback failure"
        )

        process_feedback_batch = AsyncMock(
            side_effect=error
        )

        run_all_learning_engines = AsyncMock(
            return_value={
                "posted_draft_detection": {},
                "cross_vendor_learning": {},
                "confidence_auto_promotion": {},
            }
        )

        auto_approve_drafts = AsyncMock(
            return_value={
                "approved": 0,
                "skipped": 0,
            }
        )

        learn_from_posting = AsyncMock()

        modules = {
            "services.draft_feedback_service": (
                "process_feedback_batch",
                process_feedback_batch,
            ),
            "services.continuous_learning_service": (
                "run_all_learning_engines",
                run_all_learning_engines,
            ),
            "routers.posting_patterns": (
                "auto_approve_drafts",
                auto_approve_drafts,
            ),
            "services.posting_pattern_analyzer": (
                "learn_from_posting",
                learn_from_posting,
            ),
        }

        for module_name, (
            attribute,
            value,
        ) in modules.items():
            module = ModuleType(
                module_name
            )

            setattr(
                module,
                attribute,
                value,
            )

            monkeypatch.setitem(
                sys.modules,
                module_name,
                module,
            )

        cursor = Mock()

        cursor.limit = Mock(
            return_value=cursor
        )

        cursor.to_list = AsyncMock(
            return_value=[]
        )

        collection = Mock()
        collection.find = Mock(
            return_value=cursor
        )
        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.draft_feedback_sync_scheduler(
                db=db,
                logger=logger,
            )

        logger.warning.assert_called_once_with(
            "[DraftFeedback] Scheduled sync "
            "failed: %s",
            error,
        )

        run_all_learning_engines.assert_awaited_once_with(
            db
        )

        auto_approve_drafts.assert_awaited_once()


class TestIntelligenceMaintenanceExtraction:
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
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        assert not any(
            isinstance(
                node,
                ast.AsyncFunctionDef,
            )
            and node.name
            == "_intelligence_maintenance_scheduler"
            for node in startup.body
        )

        direct_imports = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and any(
                    alias.name
                    == "intelligence_maintenance_scheduler"
                    for alias in node.names
                )
            )
        ]

        direct_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "intelligence_maintenance_scheduler"
            )
        ]

        helper_calls = [
            node
            for node in ast.walk(startup)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "start_intelligence_tasks"
            )
        ]

        assert direct_imports == []
        assert direct_calls == []
        assert len(helper_calls) == 1

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in helper_calls[0].keywords
        } == {
            "db": "db",
            "logger": "logger",
            "register_background_task": (
                "register_background_task"
            ),
        }

        service_tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_scheduler_service.py"
            ).read_text()
        )

        helper = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "start_intelligence_tasks"
            )
        )

        wrappers = []

        for node in ast.walk(helper):
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

            if names == ["intelligence_maintenance"]:
                wrappers.append(node)

        assert len(wrappers) == 1

        create_task = wrappers[0].args[0]
        coroutine = create_task.args[0]

        assert (
            create_task.func.attr
            == "create_task"
        )

        assert (
            coroutine.func.id
            == "intelligence_maintenance_scheduler"
        )

        assert {
            keyword.arg: keyword.value.id
            for keyword
            in coroutine.keywords
        } == {
            "db": "db",
            "logger": "logger",
        }

        function = next(
            node
            for node in service_tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "intelligence_maintenance_scheduler"
            )
        )

        assert (
            _body_hash(function)
            == "3512d1ba9395b885eedaf16dae92ba2f20eb1c634a462f1fa0a48cbe0fa9bd95"
        )

        from services.lifecycle_scheduler_service import (
            intelligence_maintenance_scheduler,
        )

        signature = inspect.signature(
            intelligence_maintenance_scheduler
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


class TestIntelligenceMaintenanceRuntime:
    @pytest.mark.asyncio
    async def test_runs_all_maintenance_stages(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler
        from datetime import datetime as real_datetime

        class FixedDateTime(real_datetime):
            @classmethod
            def now(
                cls,
                tz=None,
            ):
                return cls(
                    2026,
                    7,
                    26,
                    12,
                    0,
                    0,
                    tzinfo=tz,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        batch_clear = AsyncMock(
            return_value={
                "cleared": 2,
                "safe_vendors": 1,
            }
        )

        record_automation = AsyncMock()
        record_duplicate = AsyncMock()

        run_readiness = AsyncMock(
            return_value={
                "status": "ready_for_post",
                "blocking_reasons": [],
            }
        )

        duplicate_module = ModuleType(
            "services.duplicate_intelligence_service"
        )

        duplicate_module.batch_auto_clear_safe_duplicates = (
            batch_clear
        )

        duplicate_module.record_duplicate_outcome = (
            record_duplicate
        )

        escalation_module = ModuleType(
            "services.escalation_intelligence_service"
        )

        escalation_module.record_automation_outcome = (
            record_automation
        )

        validation_module = ModuleType(
            "services.unified_validation_service"
        )

        validation_module.run_readiness = (
            run_readiness
        )

        monkeypatch.setitem(
            sys.modules,
            "services.duplicate_intelligence_service",
            duplicate_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.escalation_intelligence_service",
            escalation_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.unified_validation_service",
            validation_module,
        )

        class Cursor:
            def __init__(
                self,
                documents,
            ):
                self.limit = Mock(
                    return_value=self
                )

                self.to_list = AsyncMock(
                    return_value=documents
                )

        escalation_cursor = Cursor(
            [
                {
                    "id": "doc-1",
                    "bc_vendor_number": "V100",
                    "document_type": (
                        "PURCHASE_INVOICE"
                    ),
                    "status": "Completed",
                },
            ]
        )

        duplicate_cursor = Cursor(
            [
                {
                    "id": "doc-2",
                    "vendor_no": "V200",
                },
            ]
        )

        gap_cursor = Cursor(
            [
                {
                    "id": "doc-3",
                },
            ]
        )

        collection = Mock()

        collection.find = Mock(
            side_effect=[
                escalation_cursor,
                duplicate_cursor,
                gap_cursor,
            ]
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await (
                scheduler
                .intelligence_maintenance_scheduler(
                    db=db,
                    logger=logger,
                )
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (180,),
            (2 * 3600,),
        ]

        batch_clear.assert_awaited_once_with(
            db,
            limit=200,
        )

        record_automation.assert_awaited_once_with(
            db,
            "V100",
            "PURCHASE_INVOICE",
            "success",
            "doc-1",
        )

        record_duplicate.assert_awaited_once_with(
            db,
            doc_id="doc-2",
            vendor_no="V200",
            was_flagged_duplicate=True,
            actual_outcome="false_positive",
            resolution_source="backfill_completed",
        )

        run_readiness.assert_awaited_once_with(
            "doc-3"
        )

        assert (
            collection.update_one.await_count
            == 3
        )

        assert [
            call.args
            for call
            in collection.update_one.await_args_list
        ] == [
            (
                {
                    "id": "doc-1",
                },
                {
                    "$set": {
                        "escalation_tracked": True,
                    },
                },
            ),
            (
                {
                    "id": "doc-2",
                },
                {
                    "$set": {
                        "duplicate_outcome_tracked": True,
                    },
                },
            ),
            (
                {
                    "id": "doc-3",
                },
                {
                    "$set": {
                        "gap_closer_last_run": (
                            "2026-07-26T12:00:00+00:00"
                        ),
                    },
                },
            ),
        ]

        logger.warning.assert_not_called()

        logger.info.assert_any_call(
            "[IntelMaint] Duplicate clear: "
            "%d cleared, %d safe vendors",
            2,
            1,
        )

        logger.info.assert_any_call(
            "[IntelMaint] Escalation backfill: "
            "tracked %d documents",
            1,
        )

        logger.info.assert_any_call(
            "[IntelMaint] Duplicate backfill: "
            "tracked %d false positives",
            1,
        )

        logger.info.assert_any_call(
            "[IntelMaint] Gap closer: "
            "resolved %d/%d validation gaps",
            1,
            1,
        )

    @pytest.mark.asyncio
    async def test_stage_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler
        from datetime import datetime as real_datetime

        class FixedDateTime(real_datetime):
            @classmethod
            def now(
                cls,
                tz=None,
            ):
                return cls(
                    2026,
                    7,
                    26,
                    12,
                    0,
                    0,
                    tzinfo=tz,
                )

        monkeypatch.setattr(
            scheduler,
            "datetime",
            FixedDateTime,
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated duplicate clear failure"
        )

        batch_clear = AsyncMock(
            side_effect=error
        )

        record_automation = AsyncMock()
        record_duplicate = AsyncMock()
        run_readiness = AsyncMock()

        duplicate_module = ModuleType(
            "services.duplicate_intelligence_service"
        )

        duplicate_module.batch_auto_clear_safe_duplicates = (
            batch_clear
        )

        duplicate_module.record_duplicate_outcome = (
            record_duplicate
        )

        escalation_module = ModuleType(
            "services.escalation_intelligence_service"
        )

        escalation_module.record_automation_outcome = (
            record_automation
        )

        validation_module = ModuleType(
            "services.unified_validation_service"
        )

        validation_module.run_readiness = (
            run_readiness
        )

        monkeypatch.setitem(
            sys.modules,
            "services.duplicate_intelligence_service",
            duplicate_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.escalation_intelligence_service",
            escalation_module,
        )

        monkeypatch.setitem(
            sys.modules,
            "services.unified_validation_service",
            validation_module,
        )

        class Cursor:
            def __init__(
                self,
                documents,
            ):
                self.limit = Mock(
                    return_value=self
                )

                self.to_list = AsyncMock(
                    return_value=documents
                )

        collection = Mock()

        collection.find = Mock(
            side_effect=[
                Cursor(
                    [
                        {
                            "id": "doc-4",
                            "vendor_no": "V400",
                            "suggested_job_type": (
                                "PACKING_SLIP"
                            ),
                            "status": "Posted",
                        },
                    ]
                ),
                Cursor([]),
                Cursor([]),
            ]
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await (
                scheduler
                .intelligence_maintenance_scheduler(
                    db=db,
                    logger=logger,
                )
            )

        batch_clear.assert_awaited_once_with(
            db,
            limit=200,
        )

        logger.warning.assert_called_once_with(
            "[IntelMaint] Duplicate clear "
            "failed: %s",
            error,
        )

        record_automation.assert_awaited_once_with(
            db,
            "V400",
            "PACKING_SLIP",
            "success",
            "doc-4",
        )

        collection.update_one.assert_awaited_once_with(
            {
                "id": "doc-4",
            },
            {
                "$set": {
                    "escalation_tracked": True,
                },
            },
        )


class TestPORetryExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        _assert_server_delegates_lifecycle_task(
            "start_po_retry_tasks",
            "po_retry_scheduler",
        )
        _assert_lifecycle_helper_ownership(
            "start_po_retry_tasks",
            "po_retry_scheduler",
            "po_retry",
            {
                "db": "db",
                "logger": "logger",
                "PO_RETRY_INTERVAL_HOURS":
                    "PO_RETRY_INTERVAL_HOURS",
                "PO_MAX_WAIT_DAYS": "PO_MAX_WAIT_DAYS",
                "PO_MAX_RETRIES": "PO_MAX_RETRIES",
            },
        )
        _assert_lifecycle_scheduler_contract(
            "po_retry_scheduler",
            "5cf811fe6b6334ac74ab558bcc38fc3fa77ed8878d8ee5a31a4bb548d070ab7c",
            [
                "db",
                "logger",
                "PO_RETRY_INTERVAL_HOURS",
                "PO_MAX_WAIT_DAYS",
                "PO_MAX_RETRIES",
            ],
        )


class TestPORetryRuntime:
    @pytest.mark.asyncio
    async def test_processes_retry_outcomes(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        run_readiness = AsyncMock(
            side_effect=[
                {
                    "status": "waiting",
                    "signals": {
                        "po_resolved": True,
                    },
                },
                {
                    "status": "waiting",
                    "signals": {
                        "po_resolved": False,
                    },
                },
                {
                    "status": "waiting",
                    "signals": {
                        "po_resolved": False,
                    },
                },
            ]
        )

        validation_module = ModuleType(
            "services.unified_validation_service"
        )

        validation_module.run_readiness = (
            run_readiness
        )

        monkeypatch.setitem(
            sys.modules,
            "services.unified_validation_service",
            validation_module,
        )

        pending_documents = [
            {
                "id": "doc-resolved",
                "po_pending_retry_count": 0,
                "po_pending_max_retries": 18,
            },
            {
                "id": "doc-escalated",
                "po_pending_retry_count": 17,
                "po_pending_max_retries": 18,
            },
            {
                "id": "doc-waiting",
                "po_pending_retry_count": 1,
                "po_pending_max_retries": 18,
            },
        ]

        cursor = Mock()

        cursor.limit = Mock(
            return_value=cursor
        )

        cursor.to_list = AsyncMock(
            return_value=pending_documents
        )

        first_update = Mock()
        first_update.modified_count = 2

        cleanup_update = Mock()
        cleanup_update.modified_count = 1

        collection = Mock()

        collection.update_many = AsyncMock(
            side_effect=[
                first_update,
                cleanup_update,
            ]
        )

        collection.find = Mock(
            return_value=cursor
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.po_retry_scheduler(
                db=db,
                logger=logger,
                PO_RETRY_INTERVAL_HOURS=4,
                PO_MAX_WAIT_DAYS=3,
                PO_MAX_RETRIES=18,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (600,),
            (4 * 3600,),
        ]

        assert [
            call.args
            for call
            in run_readiness.await_args_list
        ] == [
            ("doc-resolved",),
            ("doc-escalated",),
            ("doc-waiting",),
        ]

        assert (
            collection.update_many.await_count
            == 2
        )

        first_update_args = (
            collection
            .update_many
            .await_args_list[0]
            .args
        )

        assert (
            first_update_args[1]["$set"]
            ["po_pending_max_retries"]
            == 18
        )

        assert (
            first_update_args[1]["$set"]
            ["workflow_status"]
            == "po_pending"
        )

        cleanup_args = (
            collection
            .update_many
            .await_args_list[1]
            .args
        )

        assert cleanup_args[1] == {
            "$set": {
                "po_pending_parked": False,
            },
            "$unset": {
                "escalation_reason": "",
            },
        }

        assert (
            collection.update_one.await_count
            == 3
        )

        updates = [
            call.args
            for call
            in collection.update_one.await_args_list
        ]

        assert updates[0][0] == {
            "id": "doc-resolved",
        }

        assert updates[0][1]["$set"][
            "po_pending_parked"
        ] is False

        assert updates[0][1]["$set"][
            "po_pending_retry_count"
        ] == 1

        assert updates[1][0] == {
            "id": "doc-escalated",
        }

        assert updates[1][1]["$set"][
            "status"
        ] == "Exception"

        assert updates[1][1]["$set"][
            "workflow_status"
        ] == "exception_review"

        assert updates[1][1]["$set"][
            "po_pending_retry_count"
        ] == 18

        assert (
            "3 days"
            in updates[1][1]["$set"][
                "escalation_reason"
            ]
        )

        assert updates[2][0] == {
            "id": "doc-waiting",
        }

        assert updates[2][1]["$set"][
            "po_pending_retry_count"
        ] == 2

        assert (
            "po_pending_last_retry"
            in updates[2][1]["$set"]
        )

        logger.warning.assert_not_called()

        logger.info.assert_any_call(
            "[PO Retry] Auto-parked "
            "%d new PO-gap docs",
            2,
        )

        logger.info.assert_any_call(
            "[PO Retry] Cycle done: "
            "%d checked, %d resolved, "
            "%d still waiting, %d escalated",
            3,
            1,
            1,
            1,
        )

        logger.info.assert_any_call(
            "[PO Retry] Cleaned up "
            "%d incorrectly parked "
            "non-AP/cleared docs",
            1,
        )

    @pytest.mark.asyncio
    async def test_cycle_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated PO retry failure"
        )

        collection = Mock()

        collection.update_many = AsyncMock(
            side_effect=error
        )

        collection.find = Mock()
        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.po_retry_scheduler(
                db=db,
                logger=logger,
                PO_RETRY_INTERVAL_HOURS=4,
                PO_MAX_WAIT_DAYS=3,
                PO_MAX_RETRIES=18,
            )

        sleep.assert_any_await(
            600
        )

        sleep.assert_any_await(
            4 * 3600
        )

        collection.update_many.assert_awaited_once()
        collection.find.assert_not_called()
        collection.update_one.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[PO Retry] Scheduled cycle "
            "failed: %s",
            error,
        )


class TestReadyToPostExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        _assert_server_delegates_lifecycle_task(
            "start_ready_to_post_tasks",
            "ready_to_post_scheduler",
        )
        _assert_lifecycle_helper_ownership(
            "start_ready_to_post_tasks",
            "ready_to_post_scheduler",
            "ready_to_post",
            {
                "db": "db",
                "logger": "logger",
                "READY_POST_INTERVAL_SECONDS":
                    "READY_POST_INTERVAL_SECONDS",
                "READY_POST_MAX_RETRIES":
                    "READY_POST_MAX_RETRIES",
            },
        )
        _assert_lifecycle_scheduler_contract(
            "ready_to_post_scheduler",
            "ff6f7e12afd600383f8c400af7d6b606a7fb826ab50006de8adf564a67fe1192",
            [
                "db",
                "logger",
                "READY_POST_INTERVAL_SECONDS",
                "READY_POST_MAX_RETRIES",
            ],
        )


class TestReadyToPostRuntime:
    @pytest.mark.asyncio
    async def test_skips_when_bc_write_disabled(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "BC_WRITE_ENABLED",
            "false",
        )

        class StopLoop(BaseException):
            pass

        sleep = AsyncMock(
            side_effect=[
                None,
                StopLoop(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        collection = Mock()
        collection.find = Mock()
        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopLoop
        ):
            await scheduler.ready_to_post_scheduler(
                db=db,
                logger=logger,
                READY_POST_INTERVAL_SECONDS=300,
                READY_POST_MAX_RETRIES=5,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (120,),
            (300,),
        ]

        collection.find.assert_not_called()
        collection.update_one.assert_not_awaited()

        logger.debug.assert_called_once_with(
            "[ReadyToPost] "
            "BC_WRITE_ENABLED=false, "
            "skipping cycle"
        )

    @pytest.mark.asyncio
    async def test_posts_and_tracks_failures(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "BC_WRITE_ENABLED",
            "true",
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        create_invoice = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "bc_record_no": "PI-1001",
                    "bc_system_id": "system-1",
                },
                {
                    "success": False,
                    "error_message": (
                        "Temporary BC failure"
                    ),
                },
                {
                    "success": False,
                    "error": (
                        "Permanent BC failure"
                    ),
                },
            ]
        )

        integration_module = ModuleType(
            "routers.gpi_integration"
        )

        integration_module.create_purchase_invoice_from_document = (
            create_invoice
        )

        monkeypatch.setitem(
            sys.modules,
            "routers.gpi_integration",
            integration_module,
        )

        documents = [
            {
                "id": "doc-posted",
                "bc_vendor_number": "V100",
                "ready_post_retry_count": 0,
            },
            {
                "id": "doc-retry",
                "vendor_no": "V200",
                "ready_post_retry_count": 1,
            },
            {
                "id": "doc-exhausted",
                "vendor_no": "V300",
                "ready_post_retry_count": 4,
            },
        ]

        cursor = Mock()

        cursor.limit = Mock(
            return_value=cursor
        )

        cursor.to_list = AsyncMock(
            return_value=documents
        )

        collection = Mock()

        collection.find = Mock(
            return_value=cursor
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.ready_to_post_scheduler(
                db=db,
                logger=logger,
                READY_POST_INTERVAL_SECONDS=300,
                READY_POST_MAX_RETRIES=5,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (120,),
            (300,),
        ]

        collection.find.assert_called_once()

        cursor.limit.assert_called_once_with(
            50
        )

        cursor.to_list.assert_awaited_once_with(
            50
        )

        assert [
            call.args
            for call
            in create_invoice.await_args_list
        ] == [
            (
                "doc-posted",
            ),
            (
                "doc-retry",
            ),
            (
                "doc-exhausted",
            ),
        ]

        for call in create_invoice.await_args_list:
            assert call.kwargs == {
                "vendor_no_override": "",
                "force": False,
            }

        assert (
            collection.update_one.await_count
            == 3
        )

        updates = [
            call.args
            for call
            in collection.update_one.await_args_list
        ]

        assert updates[0][0] == {
            "id": "doc-posted",
        }

        assert updates[0][1]["$set"][
            "status"
        ] == "Posted"

        assert updates[0][1]["$set"][
            "workflow_status"
        ] == "posted"

        assert updates[0][1]["$set"][
            "bc_record_no"
        ] == "PI-1001"

        assert updates[0][1]["$set"][
            "bc_purchase_invoice_no"
        ] == "PI-1001"

        assert updates[0][1]["$set"][
            "bc_system_id"
        ] == "system-1"

        assert updates[0][1]["$set"][
            "ready_post_retry_count"
        ] == 1

        assert updates[1][0] == {
            "id": "doc-retry",
        }

        assert updates[1][1]["$set"][
            "ready_post_retry_count"
        ] == 2

        assert updates[1][1]["$set"][
            "ready_post_last_error"
        ] == "Temporary BC failure"

        assert (
            "ready_post_exhausted"
            not in updates[1][1]["$set"]
        )

        assert updates[2][0] == {
            "id": "doc-exhausted",
        }

        assert updates[2][1]["$set"][
            "ready_post_retry_count"
        ] == 5

        assert updates[2][1]["$set"][
            "ready_post_exhausted"
        ] is True

        assert updates[2][1]["$set"][
            "ready_post_last_error"
        ] == "Permanent BC failure"

        logger.info.assert_any_call(
            "[ReadyToPost] Found %d "
            "ReadyForPost docs to attempt posting",
            3,
        )

        logger.info.assert_any_call(
            "[ReadyToPost] Posted doc %s "
            "to BC: PI #%s",
            "doc-post",
            "PI-1001",
        )

        logger.info.assert_any_call(
            "[ReadyToPost] BC post attempt "
            "%d/%d failed for %s: %s",
            2,
            5,
            "doc-retr",
            "Temporary BC failure",
        )

        logger.warning.assert_any_call(
            "[ReadyToPost] Exhausted retries "
            "for doc %s after %d attempts: %s",
            "doc-exha",
            5,
            "Permanent BC failure",
        )

        logger.info.assert_any_call(
            "[ReadyToPost] Cycle done: "
            "%d found, %d posted, "
            "%d failed (will retry), "
            "%d exhausted",
            3,
            1,
            1,
            1,
        )

    @pytest.mark.asyncio
    async def test_cycle_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        monkeypatch.setenv(
            "BC_WRITE_ENABLED",
            "true",
        )

        sleep = AsyncMock(
            side_effect=[
                None,
                StopAsyncIteration(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated ReadyToPost failure"
        )

        collection = Mock()

        collection.find = Mock(
            side_effect=error
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        logger = Mock()

        with pytest.raises(
            StopAsyncIteration
        ):
            await scheduler.ready_to_post_scheduler(
                db=db,
                logger=logger,
                READY_POST_INTERVAL_SECONDS=300,
                READY_POST_MAX_RETRIES=5,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (120,),
            (300,),
        ]

        collection.find.assert_called_once()
        collection.update_one.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[ReadyToPost] Scheduled cycle "
            "failed: %s",
            error,
        )


class TestCapturedRetryExtraction:
    def test_source_registry_body_and_signature(
        self,
    ):
        _assert_server_delegates_lifecycle_task(
            "start_captured_retry_tasks",
            "captured_retry_scheduler",
        )
        _assert_lifecycle_helper_ownership(
            "start_captured_retry_tasks",
            "captured_retry_scheduler",
            "captured_retry",
            {
                "db": "db",
                "logger": "logger",
                "_reprocess_document_inner":
                    "_reprocess_document_inner",
                "CAPTURED_RETRY_INTERVAL_SECONDS":
                    "CAPTURED_RETRY_INTERVAL_SECONDS",
                "CAPTURED_STALE_THRESHOLD_SECONDS":
                    "CAPTURED_STALE_THRESHOLD_SECONDS",
                "CAPTURED_MAX_RETRIES": "CAPTURED_MAX_RETRIES",
            },
        )
        _assert_lifecycle_scheduler_contract(
            "captured_retry_scheduler",
            "e652fe1401cc94971dac44fde5c4889e43a42a049e62560fd6e2070437f5d617",
            [
                "db",
                "logger",
                "_reprocess_document_inner",
                "CAPTURED_RETRY_INTERVAL_SECONDS",
                "CAPTURED_STALE_THRESHOLD_SECONDS",
                "CAPTURED_MAX_RETRIES",
            ],
        )


class TestCapturedRetryRuntime:
    @pytest.mark.asyncio
    async def test_retries_escalates_and_tracks_failures(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        class StopLoop(BaseException):
            pass

        sleep = AsyncMock(
            side_effect=[
                None,
                StopLoop(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        stuck_documents = [
            {
                "id": "doc-escalated",
                "file_name": "escalated.pdf",
                "captured_retry_count": 4,
            },
            {
                "id": "doc-moved",
                "file_name": "moved.pdf",
                "captured_retry_count": 0,
            },
            {
                "id": "doc-failed",
                "file_name": "failed.pdf",
                "captured_retry_count": 1,
            },
        ]

        cursor = Mock()

        cursor.limit = Mock(
            return_value=cursor
        )

        cursor.to_list = AsyncMock(
            return_value=stuck_documents
        )

        collection = Mock()

        collection.find = Mock(
            return_value=cursor
        )

        collection.find_one = AsyncMock(
            side_effect=[
                {
                    "id": "doc-moved",
                    "workflow_status": "captured",
                },
                {
                    "workflow_status": "validated",
                    "status": "Validated",
                },
                {
                    "id": "doc-failed",
                    "workflow_status": "captured",
                },
            ]
        )

        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        reprocess_error = RuntimeError(
            "simulated reprocess failure"
        )

        reprocess = AsyncMock(
            side_effect=[
                {
                    "reprocessed": True,
                },
                reprocess_error,
            ]
        )

        logger = Mock()

        with pytest.raises(
            StopLoop
        ):
            await scheduler.captured_retry_scheduler(
                db=db,
                logger=logger,
                _reprocess_document_inner=reprocess,
                CAPTURED_RETRY_INTERVAL_SECONDS=300,
                CAPTURED_STALE_THRESHOLD_SECONDS=300,
                CAPTURED_MAX_RETRIES=4,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (180,),
            (300,),
        ]

        collection.find.assert_called_once()

        cursor.limit.assert_called_once_with(
            50
        )

        cursor.to_list.assert_awaited_once_with(
            50
        )

        query = collection.find.call_args.args[0]

        assert query[
            "workflow_status"
        ] == {
            "$in": [
                "captured",
                "Captured",
            ],
        }

        assert query[
            "captured_retry_escalated"
        ] == {
            "$ne": True,
        }

        assert "$lt" in query[
            "created_utc"
        ]

        assert [
            call.args
            for call
            in reprocess.await_args_list
        ] == [
            (
                "doc-moved",
                {
                    "id": "doc-moved",
                    "workflow_status": "captured",
                },
            ),
            (
                "doc-failed",
                {
                    "id": "doc-failed",
                    "workflow_status": "captured",
                },
            ),
        ]

        for call in reprocess.await_args_list:
            assert call.kwargs == {
                "reclassify": True,
            }

        assert (
            collection.find_one.await_count
            == 3
        )

        assert (
            collection.update_one.await_count
            == 3
        )

        updates = [
            call.args
            for call
            in collection.update_one.await_args_list
        ]

        assert updates[0][0] == {
            "id": "doc-escalated",
        }

        assert updates[0][1]["$set"][
            "status"
        ] == "Exception"

        assert updates[0][1]["$set"][
            "workflow_status"
        ] == "exception_review"

        assert updates[0][1]["$set"][
            "captured_retry_escalated"
        ] is True

        assert updates[0][1]["$set"][
            "captured_retry_count"
        ] == 5

        assert (
            updates[0][1]["$push"]
            ["workflow_history"]["event"]
            == "captured_retry_escalation"
        )

        assert updates[1][0] == {
            "id": "doc-moved",
        }

        assert updates[1][1]["$set"][
            "captured_retry_count"
        ] == 1

        assert (
            updates[1][1]["$push"]
            ["workflow_history"]["to_status"]
            == "validated"
        )

        assert (
            updates[1][1]["$push"]
            ["workflow_history"]["event"]
            == "captured_auto_retry"
        )

        assert updates[2][0] == {
            "id": "doc-failed",
        }

        assert updates[2][1]["$set"][
            "captured_retry_count"
        ] == 2

        assert updates[2][1]["$set"][
            "captured_last_retry_error"
        ] == "simulated reprocess failure"

        logger.info.assert_any_call(
            "[CapturedRetry] Escalated doc %s "
            "to Exception Queue (retries=%d)",
            "doc-esca",
            4,
        )

        logger.info.assert_any_call(
            "[CapturedRetry] Doc %s moved "
            "to '%s' after retry %d",
            "doc-move",
            "validated",
            1,
        )

        logger.warning.assert_called_once_with(
            "[CapturedRetry] Error "
            "reprocessing doc %s: %s",
            "doc-fail",
            "simulated reprocess failure",
        )

        logger.info.assert_any_call(
            "[CapturedRetry] Cycle done: "
            "%d found, %d retried, "
            "%d escalated, %d failed",
            3,
            1,
            1,
            1,
        )

    @pytest.mark.asyncio
    async def test_cycle_failure_is_nonfatal(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        class StopLoop(BaseException):
            pass

        sleep = AsyncMock(
            side_effect=[
                None,
                StopLoop(),
            ]
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "sleep",
            sleep,
        )

        error = RuntimeError(
            "simulated captured retry failure"
        )

        collection = Mock()

        collection.find = Mock(
            side_effect=error
        )

        collection.find_one = AsyncMock()
        collection.update_one = AsyncMock()

        db = Mock()
        db.hub_documents = collection

        reprocess = AsyncMock()
        logger = Mock()

        with pytest.raises(
            StopLoop
        ):
            await scheduler.captured_retry_scheduler(
                db=db,
                logger=logger,
                _reprocess_document_inner=reprocess,
                CAPTURED_RETRY_INTERVAL_SECONDS=300,
                CAPTURED_STALE_THRESHOLD_SECONDS=300,
                CAPTURED_MAX_RETRIES=4,
            )

        assert [
            call.args
            for call in sleep.await_args_list
        ] == [
            (180,),
            (300,),
        ]

        collection.find.assert_called_once()
        collection.find_one.assert_not_awaited()
        collection.update_one.assert_not_awaited()
        reprocess.assert_not_awaited()

        logger.warning.assert_called_once_with(
            "[CapturedRetry] Scheduled "
            "cycle failed: %s",
            error,
        )


class TestStatusSyncTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        startup_coroutine = object()
        periodic_coroutine = object()

        startup = Mock(
            return_value=startup_coroutine
        )

        periodic = Mock(
            return_value=periodic_coroutine
        )

        create_task = Mock(
            side_effect=[
                "startup-task",
                "periodic-task",
            ]
        )

        register = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "startup_sync_status",
            startup,
        )

        monkeypatch.setattr(
            scheduler,
            "periodic_sync_status",
            periodic,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_status_sync_tasks(
            logger=logger,
            register_background_task=register,
        )

        startup.assert_called_once_with(
            logger=logger
        )

        periodic.assert_called_once_with(
            logger=logger
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (startup_coroutine,),
            (periodic_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("startup-task",),
            ("periodic-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": "startup_sync_status",
            },
            {
                "name": "periodic_sync_status",
            },
        ]


class TestIntakeLearningTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        refresh_coroutine = object()
        hygiene_coroutine = object()

        refresh = Mock(
            return_value=refresh_coroutine
        )

        hygiene = Mock(
            return_value=hygiene_coroutine
        )

        create_task = Mock(
            side_effect=[
                "refresh-task",
                "hygiene-task",
            ]
        )

        register = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "intake_learning_refresh_scheduler",
            refresh,
        )

        monkeypatch.setattr(
            scheduler,
            "intake_pattern_hygiene_scheduler",
            hygiene,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_intake_learning_tasks(
            logger=logger,
            register_background_task=register,
        )

        refresh.assert_called_once_with(
            logger=logger
        )

        hygiene.assert_called_once_with(
            logger=logger
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (refresh_coroutine,),
            (hygiene_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("refresh-task",),
            ("hygiene-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": (
                    "intake_learning_refresh"
                ),
            },
            {
                "name": (
                    "intake_pattern_hygiene"
                ),
            },
        ]


class TestLearningReportingTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        drift_coroutine = object()
        digest_coroutine = object()

        drift = Mock(
            return_value=drift_coroutine
        )

        digest = Mock(
            return_value=digest_coroutine
        )

        create_task = Mock(
            side_effect=[
                "drift-task",
                "digest-task",
            ]
        )

        register = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "drift_alert_scheduler",
            drift,
        )

        monkeypatch.setattr(
            scheduler,
            "weekly_digest_scheduler",
            digest,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_learning_reporting_tasks(
            logger=logger,
            register_background_task=register,
        )

        drift.assert_called_once_with(
            logger=logger
        )

        digest.assert_called_once_with(
            logger=logger
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (drift_coroutine,),
            (digest_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("drift-task",),
            ("digest-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": "drift_alert",
            },
            {
                "name": "weekly_digest",
            },
        ]


class TestMonitoringTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        watchlist_coroutine = object()
        trace_coroutine = object()

        watchlist = Mock(
            return_value=watchlist_coroutine
        )

        trace = Mock(
            return_value=trace_coroutine
        )

        create_task = Mock(
            side_effect=[
                "watchlist-task",
                "trace-task",
            ]
        )

        register = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "drift_watchlist_scheduler",
            watchlist,
        )

        monkeypatch.setattr(
            scheduler,
            "daily_trace_scheduler",
            trace,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_monitoring_tasks(
            logger=logger,
            register_background_task=register,
        )

        watchlist.assert_called_once_with(
            logger=logger
        )

        trace.assert_called_once_with(
            logger=logger
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (watchlist_coroutine,),
            (trace_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("watchlist-task",),
            ("trace-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": "drift_watchlist",
            },
            {
                "name": "daily_trace",
            },
        ]


class TestBCMaintenanceTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        shipment_coroutine = object()
        knowledge_coroutine = object()

        shipment = Mock(
            return_value=shipment_coroutine
        )

        knowledge = Mock(
            return_value=knowledge_coroutine
        )

        create_task = Mock(
            side_effect=[
                "shipment-task",
                "knowledge-task",
            ]
        )

        register = Mock()
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "shipment_sync_scheduler",
            shipment,
        )

        monkeypatch.setattr(
            scheduler,
            "knowledge_seed_scheduler",
            knowledge,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_bc_maintenance_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
        )

        shipment.assert_called_once_with(
            db=db,
            logger=logger,
        )

        knowledge.assert_called_once_with(
            db=db,
            logger=logger,
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (shipment_coroutine,),
            (knowledge_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("shipment-task",),
            ("knowledge-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": "shipment_sync",
            },
            {
                "name": "knowledge_seed",
            },
        ]


class TestIntelligenceTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        deep_coroutine = object()
        maintenance_coroutine = object()

        deep_learning = Mock(
            return_value=deep_coroutine
        )

        maintenance = Mock(
            return_value=maintenance_coroutine
        )

        create_task = Mock(
            side_effect=[
                "deep-learning-task",
                "maintenance-task",
            ]
        )

        register = Mock()
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "deep_learning_scheduler",
            deep_learning,
        )

        monkeypatch.setattr(
            scheduler,
            "intelligence_maintenance_scheduler",
            maintenance,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_intelligence_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
        )

        deep_learning.assert_called_once_with(
            db=db,
            logger=logger,
        )

        maintenance.assert_called_once_with(
            db=db,
            logger=logger,
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (deep_coroutine,),
            (maintenance_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("deep-learning-task",),
            ("maintenance-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": "deep_learning",
            },
            {
                "name": (
                    "intelligence_maintenance"
                ),
            },
        ]


class TestStartupRepairTaskOwnershipRuntime:
    def test_helper_creates_and_registers_both_tasks(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        cleanup_coroutine = object()
        shipping_coroutine = object()

        cleanup = Mock(
            return_value=cleanup_coroutine
        )

        shipping = Mock(
            return_value=shipping_coroutine
        )

        create_task = Mock(
            side_effect=[
                "cleanup-task",
                "shipping-task",
            ]
        )

        register = Mock()
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "startup_clean_noise_learning_events",
            cleanup,
        )

        monkeypatch.setattr(
            scheduler,
            "startup_fix_shipping_po_escalations",
            shipping,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_startup_repair_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
        )

        cleanup.assert_called_once_with(
            db=db,
            logger=logger,
        )

        shipping.assert_called_once_with(
            db=db,
            logger=logger,
        )

        assert [
            call.args
            for call
            in create_task.call_args_list
        ] == [
            (cleanup_coroutine,),
            (shipping_coroutine,),
        ]

        assert [
            call.args
            for call
            in register.call_args_list
        ] == [
            ("cleanup-task",),
            ("shipping-task",),
        ]

        assert [
            call.kwargs
            for call
            in register.call_args_list
        ] == [
            {
                "name": (
                    "startup_clean_noise_learning_events"
                ),
            },
            {
                "name": (
                    "startup_fix_shipping_po_escalations"
                ),
            },
        ]


class TestSeparatedSchedulerOwnershipRuntime:
    def test_catalog_helper_creates_and_registers_task(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        coroutine = object()
        catalog = Mock(
            return_value=coroutine
        )

        create_task = Mock(
            return_value="catalog-task"
        )

        register = Mock()
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "catalog_sync_scheduler",
            catalog,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_catalog_sync_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
        )

        catalog.assert_called_once_with(
            db=db,
            logger=logger,
        )

        create_task.assert_called_once_with(
            coroutine
        )

        register.assert_called_once_with(
            "catalog-task",
            name="catalog_sync",
        )

    def test_draft_feedback_helper_creates_and_registers_task(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        coroutine = object()
        draft_feedback = Mock(
            return_value=coroutine
        )

        create_task = Mock(
            return_value="draft-feedback-task"
        )

        register = Mock()
        db = Mock()
        logger = Mock()

        monkeypatch.setattr(
            scheduler,
            "draft_feedback_sync_scheduler",
            draft_feedback,
        )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            create_task,
        )

        scheduler.start_draft_feedback_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
        )

        draft_feedback.assert_called_once_with(
            db=db,
            logger=logger,
        )

        create_task.assert_called_once_with(
            coroutine
        )

        register.assert_called_once_with(
            "draft-feedback-task",
            name="draft_feedback_sync",
        )


class TestRetryAndPostingTaskOwnership:
    HELPERS = {
        "start_captured_retry_tasks": "captured_retry_scheduler",
        "start_po_retry_tasks": "po_retry_scheduler",
        "start_ready_to_post_tasks": "ready_to_post_scheduler",
    }

    def test_server_delegates_retry_and_posting_tasks(self):
        tree = ast.parse(
            (BACKEND_DIR / "server.py").read_text()
        )

        startup = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "startup"
        )

        imported = {
            alias.name
            for node in ast.walk(startup)
            if isinstance(node, ast.ImportFrom)
            and node.module == "services.lifecycle_scheduler_service"
            for alias in node.names
        }

        called = [
            node.func.id
            for node in ast.walk(startup)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        ]

        assert set(self.HELPERS) <= imported

        for helper_name, scheduler_name in self.HELPERS.items():
            assert called.count(helper_name) == 1
            assert scheduler_name not in imported
            assert scheduler_name not in called

        helper_lines = {
            name: next(
                node.lineno
                for node in ast.walk(startup)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            )
            for name in self.HELPERS
        }

        assert (
            helper_lines["start_captured_retry_tasks"]
            < helper_lines["start_po_retry_tasks"]
            < helper_lines["start_ready_to_post_tasks"]
        )

    def test_runtime_registry_body_and_signatures(
        self,
        monkeypatch,
    ):
        import services.lifecycle_scheduler_service as scheduler

        db = object()
        logger = Mock()
        reprocess = object()
        registered = []

        markers = {
            "captured_retry_scheduler": object(),
            "po_retry_scheduler": object(),
            "ready_to_post_scheduler": object(),
        }

        scheduler_mocks = {}

        for name, marker in markers.items():
            scheduler_mocks[name] = Mock(return_value=marker)
            monkeypatch.setattr(
                scheduler,
                name,
                scheduler_mocks[name],
            )

        monkeypatch.setattr(
            scheduler.asyncio,
            "create_task",
            lambda coroutine: ("task", coroutine),
        )

        def register(task, *, name):
            registered.append((task, name))
            return task

        scheduler.start_captured_retry_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
            _reprocess_document_inner=reprocess,
            CAPTURED_RETRY_INTERVAL_SECONDS=300,
            CAPTURED_STALE_THRESHOLD_SECONDS=301,
            CAPTURED_MAX_RETRIES=4,
        )

        scheduler.start_po_retry_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
            PO_RETRY_INTERVAL_HOURS=4,
            PO_MAX_WAIT_DAYS=3,
            PO_MAX_RETRIES=18,
        )

        scheduler.start_ready_to_post_tasks(
            db=db,
            logger=logger,
            register_background_task=register,
            READY_POST_INTERVAL_SECONDS=300,
            READY_POST_MAX_RETRIES=5,
        )

        assert [
            name for _, name in registered
        ] == [
            "captured_retry",
            "po_retry",
            "ready_to_post",
        ]

        assert [
            task[1] for task, _ in registered
        ] == [
            markers["captured_retry_scheduler"],
            markers["po_retry_scheduler"],
            markers["ready_to_post_scheduler"],
        ]

        scheduler_mocks[
            "captured_retry_scheduler"
        ].assert_called_once_with(
            db=db,
            logger=logger,
            _reprocess_document_inner=reprocess,
            CAPTURED_RETRY_INTERVAL_SECONDS=300,
            CAPTURED_STALE_THRESHOLD_SECONDS=301,
            CAPTURED_MAX_RETRIES=4,
        )

        scheduler_mocks[
            "po_retry_scheduler"
        ].assert_called_once_with(
            db=db,
            logger=logger,
            PO_RETRY_INTERVAL_HOURS=4,
            PO_MAX_WAIT_DAYS=3,
            PO_MAX_RETRIES=18,
        )

        scheduler_mocks[
            "ready_to_post_scheduler"
        ].assert_called_once_with(
            db=db,
            logger=logger,
            READY_POST_INTERVAL_SECONDS=300,
            READY_POST_MAX_RETRIES=5,
        )

        assert list(
            inspect.signature(
                scheduler.start_captured_retry_tasks
            ).parameters
        ) == [
            "db",
            "logger",
            "register_background_task",
            "_reprocess_document_inner",
            "CAPTURED_RETRY_INTERVAL_SECONDS",
            "CAPTURED_STALE_THRESHOLD_SECONDS",
            "CAPTURED_MAX_RETRIES",
        ]

        assert list(
            inspect.signature(
                scheduler.start_po_retry_tasks
            ).parameters
        ) == [
            "db",
            "logger",
            "register_background_task",
            "PO_RETRY_INTERVAL_HOURS",
            "PO_MAX_WAIT_DAYS",
            "PO_MAX_RETRIES",
        ]

        assert list(
            inspect.signature(
                scheduler.start_ready_to_post_tasks
            ).parameters
        ) == [
            "db",
            "logger",
            "register_background_task",
            "READY_POST_INTERVAL_SECONDS",
            "READY_POST_MAX_RETRIES",
        ]


def _assert_server_delegates_polling_tasks():
    server_tree = ast.parse(
        (BACKEND_DIR / "server.py").read_text()
    )
    startup = next(
        node
        for node in server_tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "startup"
    )

    helper_names = {
        "start_email_polling_tasks",
        "start_inside_sales_pilot_tasks",
    }

    imported = [
        alias.name
        for node in ast.walk(startup)
        if isinstance(node, ast.ImportFrom)
        and node.module
        == "services.lifecycle_scheduler_service"
        for alias in node.names
    ]

    called = [
        node.func.id
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    ]

    for helper_name in helper_names:
        assert imported.count(helper_name) == 1
        assert called.count(helper_name) == 1

    worker_names = {
        "dynamic_mailbox_polling_worker",
        "email_polling_worker",
        "_sales_email_polling_worker",
        "inside_sales_pilot_worker",
    }

    direct_tasks = [
        node
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "create_task"
        and node.args
        and isinstance(node.args[0], ast.Call)
        and (
            (
                isinstance(node.args[0].func, ast.Name)
                and node.args[0].func.id in worker_names
            )
            or (
                isinstance(node.args[0].func, ast.Attribute)
                and node.args[0].func.attr in worker_names
            )
        )
    ]

    assert direct_tasks == []

    service_tree = ast.parse(
        (
            BACKEND_DIR
            / "services"
            / "lifecycle_scheduler_service.py"
        ).read_text()
    )

    service_functions = {
        node.name: node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef)
    }

    expected = {
        "start_email_polling_tasks": {
            "dynamic_mailbox_polling",
            "email_polling",
            "sales_polling",
        },
        "start_inside_sales_pilot_tasks": {
            "inside_sales_pilot",
        },
    }

    for helper_name, registry_names in expected.items():
        helper = service_functions[helper_name]
        observed = {
            keyword.value.value
            for node in ast.walk(helper)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id
            == "register_background_task"
            for keyword in node.keywords
            if keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
        }
        assert observed == registry_names
