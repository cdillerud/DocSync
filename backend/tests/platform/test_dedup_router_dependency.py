from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import dedup as router_module
from routers.dedup import _doc_score, router


def make_cursor(results: list[dict]) -> MagicMock:
    cursor = MagicMock(name="mongo_cursor")
    cursor.to_list = AsyncMock(return_value=results)
    return cursor


@pytest.fixture
def hub_documents() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.aggregate.return_value = make_cursor([])
    collection.find.return_value = make_cursor([])
    collection.update_many = AsyncMock()
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
        ({}, 0),
        ({"status": "Completed"}, 100),
        ({"status": "Posted"}, 95),
        ({"status": "Archived"}, 90),
        ({"status": "StoredInSP"}, 80),
        ({"status": "ReadyToLink"}, 75),
        ({"status": "ValidationPassed"}, 70),
        ({"status": "NeedsReview"}, 50),
        ({"status": "Classified"}, 40),
        ({"status": "Received"}, 10),
        ({"status": "captured"}, 5),
        (
            {
                "status": "NeedsReview",
                "auto_cleared": True,
                "vendor_canonical": "VENDOR-A",
                "extracted_fields": {"invoice_no": "1"},
                "validation_results": {"valid": True},
                "bc_record_id": "bc-1",
            },
            170,
        ),
    ],
)
def test_doc_score(
    document: dict,
    expected: int,
) -> None:
    assert _doc_score(document) == expected


def test_stats_uses_injected_database(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    groups = [
        {
            "_id": "abcdef1234567890",
            "count": 4,
            "sample_name": "invoice-a.pdf",
        },
        {
            "_id": "1234567890abcdef",
            "count": 2,
            "sample_name": "invoice-b.pdf",
        },
    ]
    hub_documents.aggregate.return_value = make_cursor(groups)

    with TestClient(app) as client:
        response = client.get("/dedup/stats")

    assert response.status_code == 200
    assert response.json() == {
        "duplicate_groups": 2,
        "total_extra_copies": 4,
        "top_groups": [
            {
                "hash": "abcdef123456",
                "copies": 4,
                "file": "invoice-a.pdf",
            },
            {
                "hash": "1234567890ab",
                "copies": 2,
                "file": "invoice-b.pdf",
            },
        ],
    }

    pipeline = hub_documents.aggregate.call_args.args[0]

    assert pipeline[0] == {
        "$match": {"is_duplicate": {"$ne": True}}
    }
    assert pipeline[-1] == {"$limit": 50}

    hub_documents.aggregate.return_value.to_list.assert_awaited_once_with(
        50
    )


def test_stats_limits_top_groups_to_twenty(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    groups = [
        {
            "_id": f"{index:064x}",
            "count": 2,
            "sample_name": f"file-{index}.pdf",
        }
        for index in range(25)
    ]
    hub_documents.aggregate.return_value = make_cursor(groups)

    with TestClient(app) as client:
        response = client.get("/dedup/stats")

    assert response.status_code == 200
    assert response.json()["duplicate_groups"] == 25
    assert len(response.json()["top_groups"]) == 20


def test_dry_run_keeps_highest_scoring_document(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    groups = [
        {
            "_id": "hash-a",
            "count": 3,
            "doc_ids": ["doc-1", "doc-2", "doc-3"],
        }
    ]
    documents = [
        {
            "id": "doc-1",
            "status": "NeedsReview",
            "file_name": "one.pdf",
        },
        {
            "id": "doc-2",
            "status": "Completed",
            "file_name": "two.pdf",
        },
        {
            "id": "doc-3",
            "status": "Validated",
            "file_name": "three.pdf",
        },
    ]

    hub_documents.aggregate.return_value = make_cursor(groups)
    hub_documents.find.return_value = make_cursor(documents)

    with TestClient(app) as client:
        response = client.post("/dedup/dry-run")

    assert response.status_code == 200
    assert response.json() == {
        "duplicate_groups": 1,
        "would_mark_as_duplicate": 2,
        "by_status": {
            "Validated": 1,
            "NeedsReview": 1,
        },
    }

    hub_documents.find.assert_called_once()
    query, projection = hub_documents.find.call_args.args

    assert query == {
        "id": {"$in": ["doc-1", "doc-2", "doc-3"]}
    }
    assert projection["_id"] == 0
    assert projection["id"] == 1
    assert projection["file_name"] == 1

    hub_documents.find.return_value.to_list.assert_awaited_once_with(
        3
    )
    hub_documents.update_many.assert_not_called()


def test_dry_run_handles_multiple_groups(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    groups = [
        {
            "_id": "hash-a",
            "count": 2,
            "doc_ids": ["a-1", "a-2"],
        },
        {
            "_id": "hash-b",
            "count": 3,
            "doc_ids": ["b-1", "b-2", "b-3"],
        },
    ]

    hub_documents.aggregate.return_value = make_cursor(groups)
    hub_documents.find.side_effect = [
        make_cursor(
            [
                {"id": "a-1", "status": "Completed"},
                {"id": "a-2", "status": "Received"},
            ]
        ),
        make_cursor(
            [
                {"id": "b-1", "status": "Posted"},
                {"id": "b-2", "status": "NeedsReview"},
                {"id": "b-3", "status": "Classified"},
            ]
        ),
    ]

    with TestClient(app) as client:
        response = client.post("/dedup/dry-run")

    assert response.status_code == 200
    assert response.json() == {
        "duplicate_groups": 2,
        "would_mark_as_duplicate": 3,
        "by_status": {
            "Received": 1,
            "NeedsReview": 1,
            "Classified": 1,
        },
    }


def test_run_marks_lower_scoring_documents(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    groups = [
        {
            "_id": "hash-a",
            "count": 3,
            "doc_ids": ["doc-1", "doc-2", "doc-3"],
        }
    ]
    documents = [
        {
            "id": "doc-1",
            "status": "NeedsReview",
        },
        {
            "id": "doc-2",
            "status": "Completed",
        },
        {
            "id": "doc-3",
            "status": "Validated",
        },
    ]

    hub_documents.aggregate.return_value = make_cursor(groups)
    hub_documents.find.return_value = make_cursor(documents)

    with TestClient(app) as client:
        response = client.post("/dedup/run")

    assert response.status_code == 200

    body = response.json()
    assert body["duplicate_groups"] == 1
    assert body["kept"] == 1
    assert body["marked_as_duplicate"] == 2

    timestamp = body["timestamp"]
    datetime.fromisoformat(timestamp)

    hub_documents.update_many.assert_awaited_once_with(
        {"id": {"$in": ["doc-3", "doc-1"]}},
        {
            "$set": {
                "is_duplicate": True,
                "duplicate_of": "doc-2",
                "duplicate_marked_utc": timestamp,
                "status": "Duplicate",
                "workflow_status": "duplicate",
            }
        },
    )


def test_run_does_not_update_when_group_has_one_loaded_document(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.aggregate.return_value = make_cursor(
        [
            {
                "_id": "hash-a",
                "count": 2,
                "doc_ids": ["doc-1", "doc-2"],
            }
        ]
    )
    hub_documents.find.return_value = make_cursor(
        [
            {
                "id": "doc-1",
                "status": "Completed",
            }
        ]
    )

    with TestClient(app) as client:
        response = client.post("/dedup/run")

    assert response.status_code == 200
    assert response.json()["kept"] == 1
    assert response.json()["marked_as_duplicate"] == 0

    hub_documents.update_many.assert_not_awaited()


def test_run_handles_no_duplicate_groups(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    hub_documents.aggregate.return_value = make_cursor([])

    with TestClient(app) as client:
        response = client.post("/dedup/run")

    assert response.status_code == 200
    assert response.json()["duplicate_groups"] == 0
    assert response.json()["kept"] == 0
    assert response.json()["marked_as_duplicate"] == 0

    hub_documents.find.assert_not_called()
    hub_documents.update_many.assert_not_awaited()


def test_database_dependencies_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/dedup/stats"]["get"],
        paths["/dedup/dry-run"]["post"],
        paths["/dedup/run"]["post"],
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
    ) == 3
    assert source.count("database.hub_documents") == 6
