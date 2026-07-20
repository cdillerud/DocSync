import asyncio
from types import SimpleNamespace

from services import routing_feedback_service as svc


class Result:
    def __init__(self, modified_count=0, deleted_count=0):
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, count):
        return list(self.rows if count is None else self.rows[:count])


class StaticCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []
        self.updated = []

    def find(self, *args, **kwargs):
        return Cursor(self.rows)

    async def find_one(self, *args, **kwargs):
        return self.rows[0] if self.rows else None

    async def insert_one(self, document):
        self.inserted.append(document)
        self.rows.append(document)
        return Result(modified_count=1)

    async def update_one(self, query, update):
        self.updated.append((query, update))
        key = query.get("routing_key")
        for row in self.rows:
            if key is None or row.get("routing_key") == key:
                row.update(update.get("$set", {}))
                return Result(modified_count=1)
        return Result(modified_count=0)

    async def delete_one(self, query):
        return Result(deleted_count=0)

    async def delete_many(self, query):
        return Result(deleted_count=0)


class RoutingFeedbackCollection(StaticCollection):
    def find(self, query=None, projection=None):
        query = query or {}
        rows = list(self.rows)
        keys = ((query.get("routing_key") or {}).get("$in"))
        if keys is not None:
            rows = [row for row in rows if row.get("routing_key") in keys]
        patterns = ((query.get("vendor_pattern") or {}).get("$in"))
        if patterns is not None:
            rows = [row for row in rows if row.get("vendor_pattern") in patterns]
        minimum = ((query.get("confidence") or {}).get("$gte"))
        if minimum is not None:
            rows = [row for row in rows if row.get("confidence", 0) >= minimum]
        for field in ("doc_type", "has_po", "is_international"):
            if field in query:
                rows = [row for row in rows if row.get(field) == query[field]]
        return Cursor(rows)


class FakeDB(SimpleNamespace):
    def __getitem__(self, name):
        return getattr(self, name)


async def _ball_candidates(_vendor):
    return [
        {"value": "BALLCOR", "normalized": "ballcor", "source": "input", "stable": True},
        {
            "value": "BALL METAL BEVERAGE CONTAINER CORP",
            "normalized": "ball metal beverage container",
            "source": "vendor_aliases.alias_string",
            "stable": False,
        },
    ]


def _legacy_ball_rule(confidence=4):
    # Deliberately bypass _make_routing_key. Production created this rule before
    # legal-suffix normalization was introduced, so the stored key still has
    # the trailing "corp" token.
    return {
        "routing_key": "ball metal beverage container corp|AP_Invoice|po|domestic",
        "vendor_pattern": "ball metal beverage container corp",
        "doc_type": "AP_Invoice",
        "has_po": True,
        "is_international": False,
        "correct_folder": "Warehouse Not International",
        "confidence": confidence,
        "examples": [],
    }


def test_lookup_feedback_matches_legacy_raw_name_rule_after_canonicalization(monkeypatch):
    feedback = RoutingFeedbackCollection([_legacy_ball_rule()])

    monkeypatch.setattr(svc, "_db", FakeDB(routing_feedback=feedback))
    monkeypatch.setattr(svc, "_vendor_candidates", _ball_candidates)

    result = asyncio.run(svc.lookup_feedback("BALLCOR", "AP_Invoice", True, False))
    assert result == "Warehouse Not International"


def test_record_correction_strengthens_legacy_alias_rule_instead_of_creating_duplicate(monkeypatch):
    feedback = RoutingFeedbackCollection([_legacy_ball_rule()])

    monkeypatch.setattr(svc, "_db", FakeDB(routing_feedback=feedback))
    monkeypatch.setattr(svc, "_vendor_candidates", _ball_candidates)

    result = asyncio.run(svc.record_correction(
        vendor="BALLCOR",
        doc_type="AP_Invoice",
        has_po=True,
        is_international=False,
        correct_folder="Warehouse Not International",
        file_name="ball.pdf",
        source="human_decision_queue",
    ))

    assert result["status"] == "strengthened"
    assert result["confidence"] == 5
    assert not feedback.inserted
    assert feedback.rows[0]["confidence"] == 5
    assert "BALLCOR" in feedback.rows[0]["vendor_aliases"]


def test_exact_canonical_rule_wins_equal_confidence_alias_conflict(monkeypatch):
    rules = [
        {
            "routing_key": svc._make_routing_key("BALLCOR", "AP_Invoice", True, False),
            "vendor_pattern": svc._normalize_vendor("BALLCOR"),
            "doc_type": "AP_Invoice",
            "has_po": True,
            "is_international": False,
            "correct_folder": "Dropship Not International",
            "confidence": 4,
        },
        _legacy_ball_rule(confidence=4),
    ]
    feedback = RoutingFeedbackCollection(rules)

    monkeypatch.setattr(svc, "_db", FakeDB(routing_feedback=feedback))
    monkeypatch.setattr(svc, "_vendor_candidates", _ball_candidates)

    assert asyncio.run(
        svc.lookup_feedback("BALLCOR", "AP_Invoice", True, False)
    ) == "Dropship Not International"
