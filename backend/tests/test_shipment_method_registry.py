"""Pytest for Lane C Step 2.5 — shipment-method registry foundation.

Covers:
  1. Seed shape: all 13 codes, uppercase, unique, correct region split.
  2. Lookups: get/exists/list_codes/list_by_region/list_for_archetype.
  3. Rule resolution for representative codes + unknown sentinel behavior.
  4. §4a.1 variance threshold defaulting.
  5. §4a.2 post-BOL reviewer-choice descriptor for PPDADD/PPD.
  6. Archetype applicability filter.
  7. Structural guardrail: the new module is UNWIRED — no imports of
     ``workflows.freight.shipment_methods`` exist anywhere in the backend
     outside the module itself and this test file.
"""

from pathlib import Path

import pytest

from workflows.freight.shipment_methods import (
    FREIGHT_VARIANCE_DEFAULT,
    PostBolUpdate,
    ResolvedRules,
    ShipmentMethodRecord,
    exists,
    get,
    list_all,
    list_by_region,
    list_codes,
    list_for_archetype,
    resolve_rules,
)


EXPECTED_DOMESTIC = {
    "PPDADD",
    "PPD",
    "CPU",
    "DELIVERED",
    "COLLECT",
    "GAMER_ARRANGED",
    "THIRD_PARTY",
}
EXPECTED_INTERNATIONAL = {
    "EX_WORK",
    "FOB_PORT",
    "DDP",
    "DDU",
    "CFR",
    "DAT",
}
EXPECTED_ALL = EXPECTED_DOMESTIC | EXPECTED_INTERNATIONAL


# ---------------------------------------------------------------------------
# 1. Seed shape
# ---------------------------------------------------------------------------

class TestSeedShape:
    def test_has_exactly_13_records(self):
        assert len(list_all()) == 13

    def test_codes_match_signed_scope(self):
        assert set(list_codes()) == EXPECTED_ALL

    def test_all_codes_uppercase(self):
        for code in list_codes():
            assert code == code.upper(), f"{code} is not uppercase"

    def test_codes_are_unique(self):
        codes = list_codes()
        assert len(codes) == len(set(codes))

    def test_region_split_7_and_6(self):
        domestic = list_by_region("domestic")
        international = list_by_region("international")
        assert len(domestic) == 7
        assert len(international) == 6
        assert {r.code for r in domestic} == EXPECTED_DOMESTIC
        assert {r.code for r in international} == EXPECTED_INTERNATIONAL

    def test_records_are_frozen_dataclass(self):
        rec = get("PPDADD")
        assert isinstance(rec, ShipmentMethodRecord)
        with pytest.raises(Exception):
            rec.code = "MUTATED"   # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Lookups
# ---------------------------------------------------------------------------

class TestLookups:
    def test_get_known_code(self):
        rec = get("PPDADD")
        assert rec is not None
        assert rec.code == "PPDADD"
        assert rec.display_name == "Prepaid & Add"

    def test_get_is_case_insensitive(self):
        assert get("ppdadd") is get("PPDADD")
        assert get("  ppdadd  ") is get("PPDADD")

    def test_get_unknown_returns_none_not_raise(self):
        assert get("NOT_A_CODE") is None
        assert get("") is None
        assert get(None) is None   # type: ignore[arg-type]

    def test_exists_boolean(self):
        assert exists("DDP") is True
        assert exists("ddp") is True
        assert exists("UNKNOWN") is False
        assert exists("") is False

    def test_list_for_archetype_membership(self):
        ds = list_for_archetype("drop_ship")
        ds_codes = {r.code for r in ds}
        # All 7 domestic codes apply to drop_ship; 3 international codes do.
        assert EXPECTED_DOMESTIC.issubset(ds_codes)
        assert "EX_WORK" in ds_codes
        assert "FOB_PORT" in ds_codes

    def test_list_for_unknown_archetype_empty(self):
        assert list_for_archetype("not_an_archetype") == ()


# ---------------------------------------------------------------------------
# 3. Rule resolution
# ---------------------------------------------------------------------------

class TestRuleResolution:
    def test_ppdadd_resolves_to_customer_billed_freight_with_sell_price(self):
        r = resolve_rules("PPDADD")
        assert r.known is True
        assert r.code == "PPDADD"
        assert r.region == "domestic"
        assert r.has_freight_line_expected is True
        assert r.freight_has_sell_price is True
        assert r.expects_freight_invoice is True
        assert r.sell_price_source == "customer_billed"
        assert r.freight_line_expected_on == "SO"

    def test_ppd_has_freight_line_without_sell_price(self):
        r = resolve_rules("PPD")
        assert r.known is True
        assert r.has_freight_line_expected is True
        assert r.freight_has_sell_price is False
        assert r.expects_freight_invoice is True

    def test_delivered_wraps_cost_no_freight_line_no_invoice_expected(self):
        r = resolve_rules("DELIVERED")
        assert r.known is True
        assert r.has_freight_line_expected is False
        assert r.expects_freight_invoice is False
        assert r.arranged_by == "supplier"

    def test_cpu_customer_arranged_not_billed(self):
        r = resolve_rules("CPU")
        assert r.known is True
        assert r.arranged_by == "customer"
        assert r.expects_freight_invoice is False
        assert r.sell_price_source == "not_billed"

    def test_third_party_not_gamer_billed(self):
        r = resolve_rules("THIRD_PARTY")
        assert r.known is True
        assert r.arranged_by == "third_party"
        assert r.expects_freight_invoice is False

    def test_ex_work_international_freight_on_po(self):
        r = resolve_rules("EX_WORK")
        assert r.known is True
        assert r.region == "international"
        assert r.freight_line_expected_on == "PO"
        assert r.customs_responsibility == "gamer"

    def test_ddp_international_supplier_owns_everything(self):
        r = resolve_rules("DDP")
        assert r.known is True
        assert r.region == "international"
        assert r.customs_responsibility == "supplier"
        assert r.has_freight_line_expected is False

    def test_unknown_code_returns_sentinel(self):
        r = resolve_rules("NOT_A_CODE")
        assert isinstance(r, ResolvedRules)
        assert r.known is False
        assert r.code == ""
        assert r.has_freight_line_expected is False
        assert r.expects_freight_invoice is False
        # §4a.1 — unknown falls back to default threshold.
        assert r.freight_variance_threshold_usd == FREIGHT_VARIANCE_DEFAULT
        assert r.archetype_allowed is None

    def test_unknown_code_with_archetype_marks_disallowed(self):
        r = resolve_rules("NOT_A_CODE", archetype="drop_ship")
        assert r.known is False
        assert r.archetype_allowed is False


# ---------------------------------------------------------------------------
# 4. §4a.1 threshold defaulting
# ---------------------------------------------------------------------------

class TestVarianceThreshold:
    def test_default_is_100_usd(self):
        assert FREIGHT_VARIANCE_DEFAULT == 100.0

    def test_all_seeds_default_to_fallback_when_null(self):
        # Per seed, all 13 records set freight_variance_threshold_usd=None,
        # so every resolved rule should report the default.
        for code in list_codes():
            r = resolve_rules(code)
            assert r.freight_variance_threshold_usd == FREIGHT_VARIANCE_DEFAULT


# ---------------------------------------------------------------------------
# 5. §4a.2 post-BOL reviewer-choice descriptor
# ---------------------------------------------------------------------------

class TestPostBolReviewerChoice:
    @pytest.mark.parametrize("code", ["PPDADD", "PPD"])
    def test_reviewer_choice_shape_for_ppdadd_and_ppd(self, code):
        r = resolve_rules(code)
        assert isinstance(r.post_bol_update, PostBolUpdate)
        assert r.post_bol_update.when == "bol_received"
        assert r.post_bol_update.requires_reviewer_choice is True
        assert set(r.post_bol_update.new_code_options) == {"THIRD_PARTY", "COLLECT"}
        assert "drop_ship" in r.post_bol_update.applies_to_archetypes
        assert "warehouse_order" in r.post_bol_update.applies_to_archetypes

    @pytest.mark.parametrize(
        "code",
        ["CPU", "DELIVERED", "COLLECT", "GAMER_ARRANGED", "THIRD_PARTY",
         "EX_WORK", "FOB_PORT", "DDP", "DDU", "CFR", "DAT"],
    )
    def test_other_codes_have_no_post_bol_descriptor(self, code):
        r = resolve_rules(code)
        assert r.post_bol_update is None


# ---------------------------------------------------------------------------
# 6. Archetype applicability filter
# ---------------------------------------------------------------------------

class TestArchetypeApplicability:
    def test_ppdadd_allowed_on_drop_ship(self):
        r = resolve_rules("PPDADD", archetype="drop_ship")
        assert r.archetype_allowed is True

    def test_ppdadd_not_allowed_on_consignment(self):
        r = resolve_rules("PPDADD", archetype="consignment")
        assert r.archetype_allowed is False

    def test_ddp_international_not_allowed_on_reroute(self):
        # International archetypes list does not include "reroute".
        r = resolve_rules("DDP", archetype="reroute")
        assert r.archetype_allowed is False

    def test_archetype_none_yields_none(self):
        r = resolve_rules("PPDADD")
        assert r.archetype_allowed is None


# ---------------------------------------------------------------------------
# 7. Structural guardrail — unwired
# ---------------------------------------------------------------------------

class TestUnwiredGuardrail:
    """The module must not be imported from anywhere else in the backend yet.

    Lane C Step 2.5 is explicitly foundation-only; wiring lands in Step 5.
    This test fails the moment an unintentional import sneaks in.
    """

    def test_no_external_imports_of_shipment_methods(self):
        backend_root = Path(__file__).resolve().parent.parent  # /app/backend
        allowed_prefixes = (
            backend_root / "workflows" / "freight" / "shipment_methods",
            backend_root / "tests" / "test_shipment_method_registry.py",
        )

        needles = (
            "workflows.freight.shipment_methods",
            "from workflows.freight import shipment_methods",
        )

        offenders: list[str] = []
        for py in backend_root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            # Skip files inside the shipment_methods package itself and this test.
            if any(str(py).startswith(str(prefix)) for prefix in allowed_prefixes):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
                    break

        assert offenders == [], (
            "workflows.freight.shipment_methods must stay UNWIRED until "
            "Lane C Step 5. Offending files:\n  " + "\n  ".join(offenders)
        )
