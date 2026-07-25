from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import file_integrity
from routers.file_integrity import router


@pytest.fixture
def documents_collection() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.update_one = AsyncMock()
    return collection


@pytest.fixture
def database(documents_collection: MagicMock) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = documents_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def configure_find(
    documents_collection: MagicMock,
    documents: list[dict],
) -> MagicMock:
    cursor = MagicMock(name="documents_cursor")
    cursor.to_list = AsyncMock(return_value=documents)
    documents_collection.find.return_value = cursor
    return cursor


def test_dry_run_uses_platform_database_and_reports_missing_files(
    app: FastAPI,
    database: MagicMock,
    documents_collection: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = [
        {
            "id": "doc-found",
            "file_name": "found.pdf",
            "source": "email",
            "doc_type": "invoice",
            "status": "Pending",
        },
        {
            "id": "doc-missing",
            "file_name": "missing.pdf",
            "source": "upload",
            "document_type": "purchase_order",
            "status": "Pending",
        },
        {
            "id": "doc-unknown",
            "file_name": "unknown.pdf",
            "source": "upload",
            "status": "Pending",
        },
    ]
    cursor = configure_find(documents_collection, documents)

    monkeypatch.setattr(file_integrity, "UPLOAD_DIR", tmp_path)
    (tmp_path / "doc-found").write_bytes(b"pdf")

    with TestClient(app) as client:
        response = client.post("/file-integrity/dry-run")

    assert response.status_code == 200
    assert response.json() == {
        "total_scanned": 3,
        "files_found": 1,
        "files_missing": 2,
        "by_source": {"upload": 2},
        "sample_missing": [
            {
                "id": "doc-missing",
                "file_name": "missing.pdf",
                "source": "upload",
                "type": "purchase_order",
            },
            {
                "id": "doc-unknown",
                "file_name": "unknown.pdf",
                "source": "upload",
                "type": "unknown",
            },
        ],
    }

    assert database.hub_documents is documents_collection

    find_filter, projection = documents_collection.find.call_args.args
    assert find_filter == {
        "is_duplicate": {"$ne": True},
        "auto_cleared": {"$ne": True},
        "file_missing": {"$ne": True},
        "status": {
            "$nin": ["Completed", "Posted", "Archived", "Duplicate"]
        },
    }
    assert projection["_id"] == 0
    assert projection["id"] == 1
    assert projection["file_name"] == 1
    cursor.to_list.assert_awaited_once_with(5000)


def test_dry_run_limits_missing_sample_to_twenty(
    app: FastAPI,
    documents_collection: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = [
        {
            "id": f"missing-{index}",
            "file_name": f"missing-{index}.pdf",
            "source": "email",
            "doc_type": "invoice",
        }
        for index in range(25)
    ]
    configure_find(documents_collection, documents)
    monkeypatch.setattr(file_integrity, "UPLOAD_DIR", tmp_path)

    with TestClient(app) as client:
        response = client.post("/file-integrity/dry-run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["files_missing"] == 25
    assert payload["by_source"] == {"email": 25}
    assert len(payload["sample_missing"]) == 20


def test_scan_uses_platform_database_and_flags_missing_files(
    app: FastAPI,
    database: MagicMock,
    documents_collection: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = [
        {
            "id": "doc-found",
            "file_name": "found.pdf",
            "source": "email",
        },
        {
            "id": "doc-missing",
            "file_name": "missing.pdf",
            "source": "upload",
        },
    ]
    cursor = configure_find(documents_collection, documents)

    monkeypatch.setattr(file_integrity, "UPLOAD_DIR", tmp_path)
    (tmp_path / "doc-found").write_bytes(b"pdf")

    with TestClient(app) as client:
        response = client.post("/file-integrity/scan")

    assert response.status_code == 200
    payload = response.json()

    assert payload["total_scanned"] == 2
    assert payload["flagged_missing"] == 1
    assert isinstance(payload["timestamp"], str)

    assert database.hub_documents is documents_collection

    find_filter, projection = documents_collection.find.call_args.args
    assert find_filter == {
        "is_duplicate": {"$ne": True},
        "file_missing": {"$ne": True},
        "status": {
            "$nin": ["Completed", "Posted", "Archived", "Duplicate"]
        },
    }
    assert projection == {
        "_id": 0,
        "id": 1,
        "file_name": 1,
        "source": 1,
    }
    cursor.to_list.assert_awaited_once_with(5000)

    documents_collection.update_one.assert_awaited_once()
    update_filter, update_document = (
        documents_collection.update_one.await_args.args
    )

    assert update_filter == {"id": "doc-missing"}
    assert update_document["$set"]["file_missing"] is True
    assert (
        update_document["$set"]["workflow_status"]
        == "file_missing"
    )
    assert update_document["$set"]["status"] == "FileMissing"
    assert (
        update_document["$set"]["file_missing_flagged_utc"]
        == payload["timestamp"]
    )


def test_scan_does_not_update_documents_with_existing_files(
    app: FastAPI,
    documents_collection: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = [
        {
            "id": "doc-found",
            "file_name": "found.pdf",
            "source": "email",
        }
    ]
    configure_find(documents_collection, documents)

    monkeypatch.setattr(file_integrity, "UPLOAD_DIR", tmp_path)
    (tmp_path / "doc-found").write_bytes(b"pdf")

    with TestClient(app) as client:
        response = client.post("/file-integrity/scan")

    assert response.status_code == 200
    assert response.json()["flagged_missing"] == 0
    documents_collection.update_one.assert_not_awaited()


def test_scan_handles_empty_queue(
    app: FastAPI,
    documents_collection: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_find(documents_collection, [])
    monkeypatch.setattr(file_integrity, "UPLOAD_DIR", tmp_path)

    with TestClient(app) as client:
        response = client.post("/file-integrity/scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_scanned"] == 0
    assert payload["flagged_missing"] == 0
    documents_collection.update_one.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/file-integrity/dry-run", "post"),
        ("/file-integrity/scan", "post"),
    ],
)
def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
    path: str,
    method: str,
) -> None:
    operation = app.openapi()["paths"][path][method]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )
