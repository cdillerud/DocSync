from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import vendor_extraction_profiles as router_module
from routers.vendor_extraction_profiles import router


class AsyncIterator:
    def __init__(self, values: list[dict]) -> None:
        self._values = iter(values)

    def __aiter__(self) -> "AsyncIterator":
        return self

    async def __anext__(self) -> dict:
        try:
            return next(self._values)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.fixture
def hub_documents() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.aggregate.return_value = AsyncIterator([])
    return collection


@pytest.fixture
def vendor_profiles() -> MagicMock:
    collection = MagicMock(
        name="vendor_extraction_profiles"
    )
    collection.find.return_value = AsyncIterator([])
    return collection


@pytest.fixture
def database(
    hub_documents: MagicMock,
    vendor_profiles: MagicMock,
) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = hub_documents
    db.vendor_extraction_profiles = vendor_profiles
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_seed_top_vendors_requires_initialized_service(
    app: FastAPI,
    hub_documents: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        router_module,
        "get_vep_service",
        lambda: None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/vendor-extraction-profiles/seed-top-vendors"
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "VEP service not initialized",
    }

    hub_documents.aggregate.assert_not_called()


def test_seed_top_vendors_uses_injected_database(
    app: FastAPI,
    hub_documents: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub_documents.aggregate.return_value = AsyncIterator(
        [
            {
                "_id": "VENDOR-A",
                "count": 12,
            },
            {
                "_id": "VENDOR-B",
                "count": 8,
            },
            {
                "_id": "VENDOR-C",
                "count": 6,
            },
        ]
    )

    service = MagicMock(name="vep_service")
    service.get_profile = AsyncMock(
        side_effect=[
            None,
            {"vendor_no": "VENDOR-B"},
            None,
        ]
    )
    service.generate_profile = AsyncMock(
        side_effect=[
            {"vendor_no": "VENDOR-A"},
            None,
        ]
    )

    monkeypatch.setattr(
        router_module,
        "get_vep_service",
        lambda: service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/vendor-extraction-profiles/seed-top-vendors",
            params={"min_docs": 6},
        )

    assert response.status_code == 200
    assert response.json() == {
        "seeded": 1,
        "skipped": 2,
        "vendors": ["VENDOR-A"],
        "skipped_vendors": [
            "VENDOR-B",
            "VENDOR-C",
        ],
        "total_candidates": 3,
    }

    expected_pipeline = [
        {
            "$match": {
                "vendor_canonical": {
                    "$nin": [None, ""],
                }
            }
        },
        {
            "$group": {
                "_id": "$vendor_canonical",
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gte": 6}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]

    hub_documents.aggregate.assert_called_once_with(
        expected_pipeline
    )

    assert service.get_profile.await_count == 3
    assert service.generate_profile.await_count == 2

    service.get_profile.assert_any_await("VENDOR-A")
    service.get_profile.assert_any_await("VENDOR-B")
    service.get_profile.assert_any_await("VENDOR-C")

    service.generate_profile.assert_any_await("VENDOR-A")
    service.generate_profile.assert_any_await("VENDOR-C")


def test_seed_top_vendors_rejects_min_docs_below_one(
    app: FastAPI,
    hub_documents: MagicMock,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/vendor-extraction-profiles/seed-top-vendors",
            params={"min_docs": 0},
        )

    assert response.status_code == 422
    hub_documents.aggregate.assert_not_called()


def test_coverage_uses_injected_database(
    app: FastAPI,
    hub_documents: MagicMock,
    vendor_profiles: MagicMock,
) -> None:
    hub_documents.aggregate.return_value = AsyncIterator(
        [
            {
                "_id": "VENDOR-A",
                "doc_count": 20,
            },
            {
                "_id": "VENDOR-B",
                "doc_count": 10,
            },
            {
                "_id": "VENDOR-C",
                "doc_count": 5,
            },
        ]
    )

    vendor_profiles.find.return_value = AsyncIterator(
        [
            {
                "vendor_no": "VENDOR-A",
                "vendor_name": "Vendor A",
            },
            {
                "vendor_no": None,
                "vendor_name": "VENDOR-C",
            },
        ]
    )

    with TestClient(app) as client:
        response = client.get(
            "/vendor-extraction-profiles/coverage"
        )

    assert response.status_code == 200
    assert response.json() == {
        "total_vendors": 3,
        "vendors_with_profiles": 2,
        "vendors_without_profiles": 1,
        "coverage_pct": 66.7,
        "top_unprofiled": [
            {
                "vendor_id": "VENDOR-B",
                "doc_count": 10,
            }
        ],
    }

    expected_pipeline = [
        {
            "$match": {
                "vendor_canonical": {
                    "$nin": [None, ""],
                }
            }
        },
        {
            "$group": {
                "_id": "$vendor_canonical",
                "doc_count": {"$sum": 1},
            }
        },
        {"$sort": {"doc_count": -1}},
    ]

    hub_documents.aggregate.assert_called_once_with(
        expected_pipeline
    )
    vendor_profiles.find.assert_called_once_with(
        {},
        {
            "_id": 0,
            "vendor_no": 1,
            "vendor_name": 1,
        },
    )


def test_coverage_handles_no_vendors(
    app: FastAPI,
    hub_documents: MagicMock,
    vendor_profiles: MagicMock,
) -> None:
    hub_documents.aggregate.return_value = AsyncIterator([])
    vendor_profiles.find.return_value = AsyncIterator([])

    with TestClient(app) as client:
        response = client.get(
            "/vendor-extraction-profiles/coverage"
        )

    assert response.status_code == 200
    assert response.json() == {
        "total_vendors": 0,
        "vendors_with_profiles": 0,
        "vendors_without_profiles": 0,
        "coverage_pct": 0.0,
        "top_unprofiled": [],
    }


def test_coverage_limits_unprofiled_list_to_ten(
    app: FastAPI,
    hub_documents: MagicMock,
    vendor_profiles: MagicMock,
) -> None:
    vendors = [
        {
            "_id": f"VENDOR-{index:02d}",
            "doc_count": 20 - index,
        }
        for index in range(15)
    ]

    hub_documents.aggregate.return_value = AsyncIterator(vendors)
    vendor_profiles.find.return_value = AsyncIterator([])

    with TestClient(app) as client:
        response = client.get(
            "/vendor-extraction-profiles/coverage"
        )

    assert response.status_code == 200

    body = response.json()
    assert body["total_vendors"] == 15
    assert body["vendors_without_profiles"] == 15
    assert len(body["top_unprofiled"]) == 10
    assert body["top_unprofiled"][0] == {
        "vendor_id": "VENDOR-00",
        "doc_count": 20,
    }
    assert body["top_unprofiled"][-1] == {
        "vendor_id": "VENDOR-09",
        "doc_count": 11,
    }


def test_service_only_endpoint_does_not_require_database(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock(name="vep_service")
    service.get_all_profiles = AsyncMock(
        return_value=[
            {
                "vendor_no": "VENDOR-A",
                "enabled": True,
            }
        ]
    )

    monkeypatch.setattr(
        router_module,
        "get_vep_service",
        lambda: service,
    )

    with TestClient(app) as client:
        response = client.get(
            "/vendor-extraction-profiles"
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "vendor_no": "VENDOR-A",
            "enabled": True,
        }
    ]

    service.get_all_profiles.assert_awaited_once_with()


def test_database_dependencies_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths[
            "/vendor-extraction-profiles/seed-top-vendors"
        ]["post"],
        paths[
            "/vendor-extraction-profiles/coverage"
        ]["get"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_service_only_routes_do_not_gain_database_parameter(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/vendor-extraction-profiles"]["get"],
        paths[
            "/vendor-extraction-profiles/stats"
        ]["get"],
        paths[
            "/vendor-extraction-profiles/{vendor_id}"
        ]["get"],
        paths[
            "/vendor-extraction-profiles/{vendor_id}/generate"
        ]["post"],
        paths[
            "/vendor-extraction-profiles/generate-all"
        ]["post"],
        paths[
            "/vendor-extraction-profiles/{vendor_id}/toggle"
        ]["post"],
        paths[
            "/vendor-extraction-profiles/{vendor_id}/reset"
        ]["post"],
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
    assert "db.vendor_extraction_profiles" not in source

    assert source.count(
        "Depends(get_platform_database)"
    ) == 2
    assert source.count(
        "database.hub_documents"
    ) == 2
    assert source.count(
        "database.vendor_extraction_profiles"
    ) == 1
