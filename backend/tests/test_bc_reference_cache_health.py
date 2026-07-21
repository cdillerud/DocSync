from datetime import datetime, timedelta, timezone

from routers.cache import router
from services.bc_reference_cache_service import evaluate_cache_health


NOW = datetime(2026, 7, 21, 3, 0, tzinfo=timezone.utc)


def _iso(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_cache_health_is_healthy_at_production_item_count():
    result = evaluate_cache_health(
        {
            "item": 8779,
            "purchase_order": 1512,
            "posted_sales_invoice": 58657,
        },
        _iso(5),
        item_numbered_count=8778,
        now=NOW,
        sync_interval_minutes=10,
        item_min_count=8000,
    )

    assert result["status"] == "healthy"
    assert result["healthy"] is True
    assert result["alerts"] == []
    assert result["item_catalog"]["total"] == 8779
    assert result["item_catalog"]["numbered"] == 8778
    assert result["item_catalog"]["blank_numbers"] == 1


def test_cache_health_detects_incomplete_item_catalog():
    result = evaluate_cache_health(
        {"item": 218, "purchase_order": 1512},
        _iso(5),
        item_numbered_count=218,
        now=NOW,
        item_min_count=8000,
    )

    assert result["status"] == "degraded"
    assert result["healthy"] is False
    assert {
        alert["code"] for alert in result["alerts"]
    } == {"item_catalog_below_minimum"}


def test_cache_health_detects_stale_sync():
    result = evaluate_cache_health(
        {"item": 8779},
        _iso(31),
        item_numbered_count=8778,
        now=NOW,
        sync_interval_minutes=10,
        item_min_count=8000,
    )

    assert result["status"] == "stale"
    assert "cache_sync_stale" in {
        alert["code"] for alert in result["alerts"]
    }


def test_cache_health_detects_missing_sync_metadata():
    result = evaluate_cache_health(
        {"item": 8779},
        None,
        item_numbered_count=8778,
        now=NOW,
        item_min_count=8000,
    )

    assert result["status"] == "empty"
    assert "last_sync_missing" in {
        alert["code"] for alert in result["alerts"]
    }


def test_cache_health_route_is_registered():
    paths = {route.path for route in router.routes}

    assert "/cache/status" in paths
    assert "/cache/health" in paths
