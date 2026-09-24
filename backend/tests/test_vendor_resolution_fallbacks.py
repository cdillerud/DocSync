"""Vendor resolution fallbacks: alias key variants, guarded aliases,
live BC search retries, and adopting BC validation's vendor match."""

import re
from types import SimpleNamespace

import pytest

import services.vendor_matching as matching


def _matches(doc, clause):
    for field, want in clause.items():
        have = doc.get(field)
        if isinstance(want, dict) and "$regex" in want:
            flags = re.I if "i" in want.get("$options", "") else 0
            if have is None or not re.search(want["$regex"], str(have), flags):
                return False
        elif have != want:
            return False
    return True


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, n):
        return [dict(d) for d in self.docs[:n]]


class Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updated = []

    def _filter(self, query):
        if not query:
            return list(self.docs)
        if "$or" in query:
            return [d for d in self.docs if any(_matches(d, c) for c in query["$or"])]
        return [d for d in self.docs if _matches(d, query)]

    def find(self, query=None, projection=None):
        return Cursor(self._filter(query))

    async def find_one(self, query, projection=None):
        found = self._filter(query)
        return dict(found[0]) if found else None

    async def update_one(self, query, update):
        self.updated.append((query, update))


OK = "success"


def _bc(responses):
    """Fake search_vendors_by_name: fragment -> list of BC vendors."""
    calls = []

    async def search(fragment, limit=20):
        calls.append(fragment)
        return SimpleNamespace(status=OK, data={"vendors": responses.get(fragment, [])})

    return search, calls


@pytest.fixture
def env(monkeypatch):
    def setup(aliases=(), bc_responses=None):
        db = SimpleNamespace(
            vendor_aliases=Collection(aliases),
            hub_bc_vendors=Collection(),
        )
        search, calls = _bc(bc_responses or {})
        monkeypatch.setattr(matching, "get_db", lambda: db)
        monkeypatch.setattr(
            matching, "_bc_search",
            lambda: (search, SimpleNamespace(SUCCESS=OK)),
        )
        return db, calls
    return setup


OWENS_ALIAS = {
    "alias_id": "a-owens",
    "alias": "OI PACKAGING SOLUTIONS",
    "alias_string": "OI Packaging Solutions",
    "normalized_alias": "oi packaging solutions",
    "vendor_no": "OWENS",
    "canonical_vendor_id": "OWENS",
    "vendor_name": "OI Packaging Solutions",
    "source": "auto_confirm",
}
POISONED_VIT1_ALIAS = {
    "alias_id": "a-vit1",
    "alias": "OI PACKAGING SOLUTIONS",
    "alias_string": "OI PACKAGING SOLUTIONS",
    "normalized_alias": "oi packaging solutions",
    "vendor_no": "VIT1",
    "canonical_vendor_id": "VIT1",
    "vendor_name": "Gamer Packaging, Inc.",
    "source": "auto_learned",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [0, 1])
async def test_oi_resolves_via_stripped_key_past_poisoned_alias(env, order):
    aliases = [POISONED_VIT1_ALIAS, OWENS_ALIAS]
    if order:
        aliases.reverse()
    db, _ = env(aliases)

    result = await matching.lookup_vendor_alias("o-i packaging solutions llc")

    assert result["vendor_canonical"] == "OWENS"
    assert result["vendor_match_method"] == "alias_match"
    assert db.vendor_aliases.updated[0][0] == {"alias_id": "a-owens"}


@pytest.mark.asyncio
async def test_conflicting_gap_closer_alias_is_ignored(env):
    env([{
        "alias_id": "a-ward",
        "alias_string": "Ward Trucking, LLC",
        "normalized_alias": "ward trucking",
        "vendor_no": "OWENS",
        "canonical_vendor_id": "OWENS",
        "vendor_name": "OI Packaging Solutions",
        "source": "auto_gap_closer",
    }])

    result = await matching.lookup_vendor_alias("ward trucking, llc")

    assert result["vendor_canonical"] is None


@pytest.mark.asyncio
async def test_bc_seeded_plant_alias_stays_authoritative(env):
    env([{
        "alias_id": "a-plant",
        "alias": "OI - AUBURN PLANT",
        "normalized_alias": "oi - auburn plant",
        "vendor_no": "OWENS",
        "canonical_vendor_id": "OWENS",
        "vendor_name": "Owens Illinois Glass",
        "source": "bc_cache_seed",
    }])

    result = await matching.lookup_vendor_alias("oi - auburn plant")

    assert result["vendor_canonical"] == "OWENS"


@pytest.mark.asyncio
async def test_bc_search_retries_without_legal_suffix(env):
    _, calls = env(bc_responses={
        "Straitlink Global Logistics": [
            {"number": "STRAITL", "displayName": "Straitlink Global Logistics"},
        ],
    })

    result = await matching.lookup_vendor_alias("straitlink global logistics inc.")

    assert calls[:2] == ["Straitlink Global Logistics Inc.", "Straitlink Global Logistics"]
    assert result["vendor_canonical"] == "STRAITL"


@pytest.mark.asyncio
async def test_first_word_fallback_scores_when_full_search_is_empty(env):
    env(bc_responses={
        "Canworks": [{"number": "CANWORK", "displayName": "Canworks, Inc"}],
    })

    result = await matching.lookup_vendor_alias("canworks incorporated usa")

    assert result["vendor_canonical"] == "CANWORK"


def _validation(number, name, method, score=1.0):
    return {
        "match_method": method,
        "match_score": score,
        "bc_record_info": {"id": None, "number": number, "displayName": name},
    }


@pytest.mark.asyncio
async def test_live_bc_validation_match_is_adopted(env):
    env()

    result = await matching.resolve_vendor_from_bc_validation(
        "Celtic International, LLC",
        _validation("CELTICI", "Celtic International, LLC.", "business_central", 0.93),
    )

    assert result == {
        "vendor_canonical": "CELTICI",
        "vendor_match_method": "bc_validation_match",
        "vendor_name": "Celtic International, LLC.",
        "vendor_no": "CELTICI",
        "match_score": 0.93,
    }


@pytest.mark.asyncio
async def test_history_match_confirmed_in_bc_is_adopted(env):
    env(bc_responses={
        "R & L Carriers, Inc.": [{"number": "R & L", "displayName": "R & L Carriers, Inc."}],
    })

    result = await matching.resolve_vendor_from_bc_validation(
        "R+L Carriers, Inc.",
        _validation("R & L", "R & L Carriers, Inc.", "document_history"),
    )

    assert result["vendor_canonical"] == "R & L"


@pytest.mark.asyncio
async def test_history_match_with_wrong_number_is_rejected(env):
    # Past documents recorded R+L under "CA" (Ca Franchise Tax Board)
    env(bc_responses={
        "R & L Carriers, Inc.": [{"number": "R & L", "displayName": "R & L Carriers, Inc."}],
    })

    result = await matching.resolve_vendor_from_bc_validation(
        "R+L Carriers, Inc.",
        _validation("CA", "R & L Carriers, Inc.", "document_history"),
    )

    assert result["vendor_canonical"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("validation", [
    _validation("VIT1", "Gamer Packaging, Inc.", "business_central"),
    _validation("CELTICI", "Celtic International, LLC.", "business_central", 0.7),
    _validation("CELTICI", "Celtic International, LLC.", "spiro_crm"),
    {"match_method": "none", "match_score": 0, "bc_record_info": None},
])
async def test_weak_or_conflicting_validation_match_is_rejected(env, validation):
    env()

    result = await matching.resolve_vendor_from_bc_validation(
        "Celtic International, LLC", validation,
    )

    assert result["vendor_canonical"] is None
