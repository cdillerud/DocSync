from copy import deepcopy
from types import SimpleNamespace

import pytest

from services.alert_pattern_service import AlertPatternService


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)

        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$nin" in expected and actual in expected["$nin"]:
                return False
        elif actual != expected:
            return False

    return True


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length):
        return deepcopy(self.documents[:length])


class FakeCollection:
    def __init__(self):
        self.documents = []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if _matches(document, query):
                return deepcopy(document)
        return None

    async def insert_one(self, document):
        self.documents.append(deepcopy(document))
        return SimpleNamespace(inserted_id=document["pattern_key"])

    async def update_one(self, query, update):
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def find(self, query):
        matches = [
            document
            for document in self.documents
            if _matches(document, query)
        ]
        return FakeCursor(matches)


class FakeEventService:
    def __init__(self):
        self.events = []

    async def emit(self, **kwargs):
        self.events.append(deepcopy(kwargs))


def _service():
    alerts = FakeCollection()
    db = SimpleNamespace(
        alert_patterns=alerts,
        reference_label_corrections=FakeCollection(),
    )
    events = FakeEventService()
    return AlertPatternService(db, events), alerts, events


def _healthy():
    return {
        "status": "healthy",
        "last_sync": "2026-07-21T02:18:48+00:00",
        "alerts": [],
    }


def _item_catalog_failure():
    return {
        "status": "degraded",
        "last_sync": "2026-07-21T02:18:48+00:00",
        "alerts": [{
            "code": "item_catalog_below_minimum",
            "severity": "critical",
            "message": (
                "BC item catalog cache is below its configured minimum."
            ),
            "actual": 218,
            "minimum": 8000,
        }],
    }


@pytest.mark.asyncio
async def test_cache_alert_is_created_once_and_deduplicated():
    service, alerts, events = _service()

    first = await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    assert first["created"] == 1
    assert first["updated"] == 0
    assert len(alerts.documents) == 1
    assert len(events.events) == 1

    alert = alerts.documents[0]
    assert alert["pattern_key"] == (
        "system:bc-item-catalog-below-minimum"
    )
    assert alert["vendor_scope"] == "system"
    assert alert["system_component"] == "bc_reference_cache"
    assert alert["severity_level"] == "critical"
    assert alert["status"] == "active"

    second = await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    assert second["created"] == 0
    assert second["updated"] == 1
    assert len(alerts.documents) == 1
    assert len(events.events) == 1


@pytest.mark.asyncio
async def test_cache_alert_resolves_and_reactivates_on_recurrence():
    service, alerts, events = _service()

    await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    recovered = await service._evaluate_cache_health_alerts(
        _healthy()
    )

    assert recovered["resolved"] == 1
    assert alerts.documents[0]["status"] == "resolved"
    assert alerts.documents[0]["resolved_reason"] == (
        "cache_health_recovered"
    )

    recurrence = await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    assert recurrence["created"] == 0
    assert recurrence["updated"] == 1
    assert alerts.documents[0]["status"] == "active"

    # Initial incident plus recurrence after recovery.
    assert len(events.events) == 2


@pytest.mark.asyncio
async def test_dismissed_cache_alert_stays_dismissed_until_recovery():
    service, alerts, events = _service()

    await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )
    alerts.documents[0]["status"] = "dismissed"

    result = await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    assert result["updated"] == 1
    assert alerts.documents[0]["status"] == "dismissed"
    assert len(events.events) == 1

    recovered = await service._evaluate_cache_health_alerts(
        _healthy()
    )

    assert recovered["resolved"] == 1
    assert alerts.documents[0]["status"] == "resolved"


class FakeEmailService:
    def __init__(self):
        self.messages = []

    async def send_email(
        self,
        to,
        subject,
        html_body,
        text_body=None,
        **kwargs,
    ):
        self.messages.append({
            "to": to,
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
        })

        return SimpleNamespace(
            success=True,
            provider="microsoft_graph",
            message_id="test-message-id",
            error=None,
        )


@pytest.mark.asyncio
async def test_critical_cache_alert_sends_one_email(
    monkeypatch,
):
    import services.alert_pattern_service as alert_module

    service, alerts, events = _service()
    email_service = FakeEmailService()

    monkeypatch.setenv(
        "BC_CACHE_ALERT_EMAIL_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "BC_CACHE_ALERT_EMAIL_RECIPIENTS",
        "cdillerud@gamerpackaging.com",
    )
    monkeypatch.setattr(
        alert_module,
        "get_email_service",
        lambda: email_service,
    )

    await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )
    await service._evaluate_cache_health_alerts(
        _item_catalog_failure()
    )

    assert len(email_service.messages) == 1

    message = email_service.messages[0]
    assert message["to"] == [
        "cdillerud@gamerpackaging.com"
    ]
    assert "CRITICAL BC Cache Alert" in message["subject"]
    assert "Item Catalog Below Minimum" in message["subject"]

    alert = alerts.documents[0]
    assert alert["last_notification_status"] == "sent"
    assert alert["last_notification_provider"] == (
        "microsoft_graph"
    )
    assert alert["last_notification_message_id"] == (
        "test-message-id"
    )
