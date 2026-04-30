"""Phase 4C(c) — Unit tests for the deterministic PDF field extractors.

Inline string fixtures (no PDF bytes needed) — exercises each of the
five field families across positive + negative cases.
"""

from __future__ import annotations

import pytest

from services.contracts.pdf_field_extractors import (
    extract_all_fields,
    extract_freight,
    extract_moq_header,
    extract_moq_per_line,
    extract_payment_term_discount,
    extract_tooling,
    extract_volume_commitment,
    extract_volume_tier_discount,
)


# ---------------------------------------------------------------------------
# 1. Freight
# ---------------------------------------------------------------------------


class TestFreight:
    def test_labeled_incoterm_with_named_place(self):
        out = extract_freight("Incoterm: FOB Garden Grove, CA. Other notes.")
        assert any(f.key == "freight_inco_term" for f in out)
        f = next(f for f in out if f.key == "freight_inco_term")
        assert f.value["incoterm"] == "FOB"
        assert "Garden Grove" in f.value["named_place"]
        assert f.confidence >= 0.9

    def test_shipping_terms_dap(self):
        out = extract_freight("Shipping Terms: DAP Chicago, IL.")
        assert any(f.value.get("incoterm") == "DAP" for f in out)

    def test_freight_payer_prepaid_buyer(self):
        out = extract_freight("Freight prepaid by Buyer; routing TBD.")
        f = next(f for f in out if f.key == "freight_payer")
        assert f.value["payer"] == "prepaid"
        assert f.value["subject"] == "buyer"
        assert f.confidence >= 0.8

    def test_no_match_on_irrelevant_text(self):
        out = extract_freight("This contract has no freight provisions.")
        assert out == []

    def test_bare_incoterm_requires_freight_keyword(self):
        # "FOB" alone with no nearby "freight"/"shipping" → no match.
        out = extract_freight("Quote includes FOB at point of origin.")
        assert not any(f.key == "freight_inco_term" for f in out)

    def test_bare_incoterm_accepted_with_shipping_keyword(self):
        out = extract_freight(
            "Shipping arranged by buyer. FOB Newark, NJ applies."
        )
        assert any(f.value.get("incoterm") == "FOB" for f in out)


# ---------------------------------------------------------------------------
# 2. MOQ — header + per-line
# ---------------------------------------------------------------------------


class TestMOQHeader:
    def test_labeled_moq_with_unit(self):
        out = extract_moq_header("Minimum Order Quantity: 25,000 EA per shipment.")
        assert len(out) == 1
        assert out[0].value == {"quantity": 25000.0, "unit": "EA"}
        assert out[0].confidence >= 0.85

    def test_short_form_moq(self):
        out = extract_moq_header("MOQ 5 pallets.")
        assert len(out) == 1
        assert out[0].value["quantity"] == 5.0
        assert out[0].value["unit"] == "PALLETS"

    def test_decimal_quantity(self):
        out = extract_moq_header("Minimum order quantity: 1,250.5 LBS")
        assert out[0].value["quantity"] == 1250.5
        assert out[0].value["unit"] == "LBS"

    def test_no_match(self):
        assert extract_moq_header("No order minimums apply.") == []

    def test_dedup_of_repeated_statement(self):
        out = extract_moq_header(
            "Minimum Order Quantity: 25,000 EA. ... Minimum Order Quantity: 25,000 EA."
        )
        assert len(out) == 1


class TestMOQPerLine:
    def test_basic_line_moq(self):
        out = extract_moq_per_line("Item ACME-WIDGET-12 MOQ: 5000")
        assert len(out) == 1
        assert out[0].item_label == "ACME-WIDGET-12"
        assert out[0].min_quantity == 5000.0

    def test_two_line_moqs(self):
        out = extract_moq_per_line(
            "Item ACME-A MOQ: 1000\nItem ACME-B MOQ: 2,500"
        )
        labels = {lp.item_label for lp in out}
        assert "ACME-A" in labels and "ACME-B" in labels
        assert any(lp.min_quantity == 2500.0 for lp in out)

    def test_no_match_on_header_only_moq(self):
        out = extract_moq_per_line("Minimum Order Quantity: 25,000 EA")
        assert out == []


# ---------------------------------------------------------------------------
# 3. Volume commitment
# ---------------------------------------------------------------------------


class TestVolumeCommitment:
    def test_basic_yearly_commitment(self):
        out = extract_volume_commitment(
            "Customer commits to purchase 100,000 units per year."
        )
        assert len(out) == 1
        assert out[0].value["quantity"] == 100000.0
        assert out[0].value["unit"] == "units"
        assert out[0].value["period"] == "year"

    def test_minimum_total_phrasing(self):
        out = extract_volume_commitment(
            "Buyer agrees to purchase a minimum of 12,000 cases annually."
        )
        assert out[0].value["quantity"] == 12000.0
        assert out[0].value["period"] == "annually"

    def test_no_match(self):
        assert extract_volume_commitment("Pricing is firm but volume is flexible.") == []


# ---------------------------------------------------------------------------
# 4. Tooling amortization
# ---------------------------------------------------------------------------


class TestTooling:
    def test_explicit_amortization_with_rate(self):
        text = (
            "Tooling cost: $45,000. Amortized over the first 250,000 units "
            "at $0.18 / unit."
        )
        out = extract_tooling(text)
        oblig = next(f for f in out if f.target == "obligation")
        assert oblig.value["lump_sum"] == 45000.0
        assert oblig.value["units"] == 250000.0
        assert oblig.value["rate_per_unit"] == 0.18
        assert oblig.value["rate_source"] == "explicit"
        # Pricing overlay also emitted.
        assert any(f.target == "pricing" for f in out)

    def test_amortization_with_derived_rate(self):
        text = (
            "Tooling cost: $50,000. Amortized over the first 100,000 pieces."
        )
        out = extract_tooling(text)
        oblig = next(f for f in out if f.target == "obligation")
        assert oblig.value["rate_per_unit"] == 0.5  # 50,000 / 100,000
        assert oblig.value["rate_source"] == "derived"

    def test_lump_sum_only(self):
        text = "Tooling cost: $30,000. No amortization schedule provided."
        out = extract_tooling(text)
        oblig = next(f for f in out if f.target == "obligation")
        assert oblig.value["lump_sum"] == 30000.0
        assert oblig.value["rate_per_unit"] is None

    def test_no_tooling_mention(self):
        assert extract_tooling("Pricing is firm.") == []


# ---------------------------------------------------------------------------
# 5. Payment-term discount + volume tier discount
# ---------------------------------------------------------------------------


class TestPaymentTermDiscount:
    def test_classic_pattern(self):
        out = extract_payment_term_discount("Payment Terms: 1% / 10 net 30.")
        assert len(out) == 1
        assert out[0].value == {"discount_pct": 1.0, "early_days": 10, "net_days": 30}

    def test_alternative_separator(self):
        out = extract_payment_term_discount("Payment Terms: 2/15 net 45.")
        assert out[0].value["discount_pct"] == 2.0
        assert out[0].value["early_days"] == 15
        assert out[0].value["net_days"] == 45

    def test_rejects_invalid(self):
        # Early days greater than net days → reject.
        assert extract_payment_term_discount("Bizarre 5% / 60 net 30") == []

    def test_no_match(self):
        assert extract_payment_term_discount("Net 30 with no early discount.") == []


class TestVolumeTier:
    def test_two_tier_table(self):
        out = extract_volume_tier_discount(
            "5% off above 50,000 units. 10% off above 250,000 units."
        )
        assert len(out) == 1
        tiers = out[0].value["tiers"]
        assert len(tiers) == 2
        assert tiers[0]["discount_pct"] == 5.0
        assert tiers[1]["threshold"] == 250000.0

    def test_unit_inference_default(self):
        out = extract_volume_tier_discount("3% discount above 1,000")
        assert out[0].value["tiers"][0]["unit"] == "unit"


# ---------------------------------------------------------------------------
# Aggregator + per-line / header MOQ deduplication
# ---------------------------------------------------------------------------


class TestExtractAllFields:
    def test_aggregates_across_families(self):
        text = (
            "Incoterm: FOB Newark, NJ. Freight prepaid by Buyer. "
            "Minimum Order Quantity: 25,000 EA per shipment. "
            "Payment Terms: 1% / 10 net 30. "
            "Customer commits to purchase 100,000 units per year. "
            "Tooling cost: $45,000. Amortized over the first 250,000 units "
            "at $0.18 / unit. "
            "5% off above 50,000 units."
        )
        result = extract_all_fields(text)
        keys = {f.key for f in result["fields"]}
        assert {
            "freight_inco_term", "freight_payer", "moq",
            "payment_term_discount", "volume_commitment",
            "tooling_amortization", "volume_discount_tier",
        }.issubset(keys)
        assert any(f.target == "pricing" and f.key == "tooling_amortized_unit_rate"
                   for f in result["fields"])

    def test_per_line_moq_dedupes_header_moq(self):
        # Per-line MOQs at 5000 / 12500 should NOT also appear as
        # header MOQ rows.
        text = (
            "Item ACME-A MOQ: 5000\nItem ACME-B MOQ: 12,500"
        )
        result = extract_all_fields(text)
        header_moqs = [f for f in result["fields"] if f.key == "moq"]
        assert header_moqs == []
        assert len(result["line_pricing"]) == 2

    def test_header_moq_kept_when_distinct_from_lines(self):
        text = (
            "Minimum Order Quantity: 25,000 EA per shipment. "
            "Item ACME-A MOQ: 5000"
        )
        result = extract_all_fields(text)
        header_moqs = [f for f in result["fields"] if f.key == "moq"]
        # 25,000 EA stays, 5000 stays as line only.
        assert len(header_moqs) == 1
        assert header_moqs[0].value["quantity"] == 25000.0
        assert len(result["line_pricing"]) == 1


# ---------------------------------------------------------------------------
# Negative aggregation
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    @pytest.mark.parametrize("blank", ["", "    ", "\n\n", None])
    def test_blank_inputs_safe(self, blank):
        result = extract_all_fields(blank or "")
        assert result == {"fields": [], "line_pricing": []}
