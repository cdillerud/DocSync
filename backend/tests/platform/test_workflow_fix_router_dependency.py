from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import workflow_fix as router_module
from routers.workflow_fix import _derive_status, router


def make_cursor(results: list[dict]) -> MagicMock:
    cursor = MagicMock(name="workflow_cursor")
    cursor.to_list = AsyncMock(return_value=results)
    return cursor


@pytest.fixture
def hub_documents() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.find.return_value = make_cursor([])
    collection.update_one = AsyncMock()
    return collection


@pytest.fixture
def database(hub_documents: MagicMock) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = hub_documents
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"auto_cleared": True}, "completed"),
        ({"status": "Completed"}, "completed"),
        ({"status": "Posted"}, "completed"),
        ({"status": "Archived"}, "completed"),
        ({"status": "Exception"}, "exception"),
        ({"status": "ReadyToLink"}, "ready_for_approval"),
        ({"status": "LinkedToBC"}, "ready_for_approval"),
        ({"status": "StoredInSP"}, "processed"),
        ({"status": "Validated"}, "validation_passed"),
        ({"status": "ValidationPassed"}, "validation_passed"),
        (
            {"routing_status": "auto_process"},
            "validation_passed",
        ),
        (
            {"automation_decision": "auto_link"},
            "validation_passed",
        ),
        ({"status": "NeedsReview"}, "needs_review"),
        ({"doc_type": "invoice"}, "classified"),
        ({"document_type": "invoice"}, "classified"),
        ({"suggested_job_type": "AP"}, "classified"),
        ({}, "captured"),
    ],
)
def test_derive_status(
    document: dict,
    expected: str,
) -> None:
    assert _derive_status(document) == expected


def test_dry_run_uses_injected_database_and_counts_changes(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    documents = [
        {
            "id": "doc-1",
            "workflow_status": "captured",
            "status": "NeedsReview",
            "auto_cleared": True,
        },
        {
            "id": "doc-2",
            "workflow_status": "captured",
            "status": "Validated",
        },
        {
            "id": "doc-3",
            "workflow_status": "captured",
            "status": "",
        },
        {
            "id": "doc-4",
            "workflow_status": "needs_review",
            "status": "NeedsReview",
        },
    ]
    hub_documents.find.return_value = make_cursor(documents)

    with TestClient(app) as client:
        response = client.post("/workflow-fix/dry-run")

    assert response.status_code == 200
    assert response.json() == {
        "total_found": 4,
        "would_fix": 2,
        "would_remain": 2,
        "target_statuses": {
            "completed (status=Completed)": 1,
            "validation_passed (status=ValidationPassed)": 1,
        },
    }

    hub_documents.find.assert_called_once()
    query, projection = hub_documents.find.call_args.args

    assert "$or" in query
    assert len(query["$or"]) == 5
    assert projection["_id"] == 0
    assert projection["id"] == 1
    assert projection["workflow_status"] == 1

    hub_documents.find.return_value.to_list.assert_awaited_once_with(
        10000
    )
    hub_documents.update_one.assert_not_called()


def test_dry_run_handles_empty_result(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.find.return_value = make_cursor([])

    with TestClient(app) as client:
        response = client.post("/workflow-fix/dry-run")

    assert response.status_code == 200
    assert response.json() == {
        "total_found": 0,
        "would_fix": 0,
        "would_remain": 0,
        "target_statuses": {},
    }


def test_run_uses_injected_database_and_updates_documents(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    documents = [
        {
            "id": "doc-1",
            "workflow_status": "captured",
            "status": "NeedsReview",
            "auto_cleared": True,
            "automation_decision": None,
        },
        {
            "id": "doc-2",
            "workflow_status": "captured",
            "status": "Validated",
            "auto_cleared": False,
            "automation_decision": None,
        },
        {
            "id": "doc-3",
            "workflow_status": "needs_review",
            "status": "NeedsReview",
            "auto_cleared": False,
            "automation_decision": None,
        },
    ]
    hub_documents.find.return_value = make_cursor(documents)

    with TestClient(app) as client:
        response = client.post("/workflow-fix/run")

    assert response.status_code == 200

    body = response.json()
    assert body["total_found"] == 3
    assert body["fixed"] == 2
    assert body["remained"] == 1
    assert body["by_new_status"] == {
        "completed (status=Completed)": 1,
        "validation_passed (status=ValidationPassed)": 1,
    }

    timestamp = body["timestamp"]
    datetime.fromisoformat(timestamp)

    assert hub_documents.update_one.await_count == 2

    first_call = hub_documents.update_one.await_args_list[0]
    assert first_call.args[0] == {"id": "doc-1"}

    first_update = first_call.args[1]
    assert first_update["$set"] == {
        "workflow_status": "completed",
        "workflow_status_updated_utc": timestamp,
        "status": "Completed",
    }
    assert first_update["$push"]["workflow_history"] == {
        "timestamp": timestamp,
        "from_status": "captured",
        "to_status": "completed",
        "event": "batch_workflow_fix",
        "actor": "system",
        "reason": (
            "Batch fix: old_status=NeedsReview, "
            "decision=None, auto_cleared=True"
        ),
    }

    second_call = hub_documents.update_one.await_args_list[1]
    assert second_call.args[0] == {"id": "doc-2"}

    second_update = second_call.args[1]
    assert second_update["$set"] == {
        "workflow_status": "validation_passed",
        "workflow_status_updated_utc": timestamp,
        "status": "ValidationPassed",
    }
    assert second_update["$push"]["workflow_history"][
        "to_status"
    ] == "validation_passed"


def test_run_updates_workflow_status_without_top_level_status(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.find.return_value = make_cursor(
        [
            {
                "id": "doc-1",
                "workflow_status": "classified",
                "status": "",
            }
        ]
    )

    with TestClient(app) as client:
        response = client.post("/workflow-fix/run")

    assert response.status_code == 200
    assert response.json()["fixed"] == 1

    update = hub_documents.update_one.await_args.args[1]

    assert update["$set"]["workflow_status"] == "captured"
    assert "status" not in update["$set"]


def test_run_skips_document_already_consistent(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.find.return_value = make_cursor(
        [
            {
                "id": "doc-1",
                "workflow_status": "completed",
                "status": "Completed",
                "auto_cleared": True,
            }
        ]
    )

    with TestClient(app) as client:
        response = client.post("/workflow-fix/run")

    assert response.status_code == 200
    assert response.json()["fixed"] == 0
    assert response.json()["remained"] == 1
    assert response.json()["by_new_status"] == {}

    hub_documents.update_one.assert_not_awaited()


def test_run_uses_expected_query_and_projection(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.find.return_value = make_cursor([])

    with TestClient(app) as client:
        response = client.post("/workflow-fix/run")

    assert response.status_code == 200

    query, projection = hub_documents.find.call_args.args

    assert "$or" in query
    assert len(query["$or"]) == 5
    assert projection == {
        "_id": 0,
        "id": 1,
        "status": 1,
        "doc_type": 1,
        "document_type": 1,
        "automation_decision": 1,
        "auto_cleared": 1,
        "routing_status": 1,
        "suggested_job_type": 1,
        "workflow_status": 1,
    }

    hub_documents.find.return_value.to_list.assert_awaited_once_with(
        10000
    )


def test_database_dependencies_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/workflow-fix/dry-run"]["post"],
        paths["/workflow-fix/run"]["post"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_router_source_has_no_legacy_database_dependency() -> None:
    source_path = router_module.__file__

    assert source_path is not None

    with open(source_path, encoding="utf-8") as router_file:
        source = router_file.read()

    assert "from deps import get_db" not in source
    assert "get_db()" not in source
    assert "db.hub_documents" not in source

    assert source.count(
        "Depends(get_platform_database)"
    ) == 2
    assert source.count("database.hub_documents") == 3
