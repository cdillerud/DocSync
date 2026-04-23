"""
GPI Hub — Canonical shipment-method registry (Lane C Step 2.5)

Source of truth for the 13-code shipment-method catalog defined in
memory/LANE_A_SIGNED_SCOPE.md §4a. Python-declarative seed; no DB, no I/O,
no behavioral wiring. Lookups are pure.

This module is intentionally UNWIRED. Do not import from:
  - backend/server.py
  - any other workflows/ module (exception: the warehouse_order archetype
    package, which became the first canonical consumer in Lane C Step 5)
  - services/*
  - routers/*

Convergence into live freight logic is complete: the prior dormant
shipment-method dict and accessor in
``workflows/freight/item_charges.py`` were deleted in Step 5 after
grep-verifying zero external callers. This module is now the sole
source of shipment-method truth in the backend.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

Region = Literal["domestic", "international"]
FobSide = Literal["origin", "destination"]
DateFieldDrivingOrder = Literal["pickup_date", "delivery_date"]
FreightLineExpectedOn = Literal["SO", "PO", "neither"]
SellPriceSource = Literal["customer_billed", "not_billed", "wrapped_in_item_cost"]
ArrangedBy = Literal["gamer", "supplier", "customer", "third_party"]
CustomsResponsibility = Literal["gamer", "supplier", "n/a"]


@dataclass(frozen=True)
class PostBolUpdate:
    """§4a.2 — reviewer-choice model for post-BOL code updates.

    requires_reviewer_choice defaults True because no deterministic mapping
    exists today. If a deterministic rule is ever added, set False and the
    reviewer-choice prompt collapses.
    """
    new_code_options: Tuple[str, ...]
    when: str                                # e.g. "bol_received"
    requires_reviewer_choice: bool
    applies_to_archetypes: Tuple[str, ...]


@dataclass(frozen=True)
class ShipmentMethodRecord:
    """Schema per LANE_A_SIGNED_SCOPE.md §4a.

    freight_variance_threshold_usd is Optional[float]. None means "fall back
    to FREIGHT_VARIANCE_DEFAULT in rules.py" (§4a.1). Carrier-level overrides
    are a future concern handled by a separate carrier registry.
    """
    code: str                                # unique uppercase
    display_name: str
    region: Region
    fob_side: FobSide
    date_field_driving_order: DateFieldDrivingOrder
    freight_line_expected_on: FreightLineExpectedOn
    sell_price_source: SellPriceSource
    arranged_by: ArrangedBy
    customs_responsibility: CustomsResponsibility
    freight_variance_threshold_usd: Optional[float]
    post_bol_update: Optional[PostBolUpdate]
    allowed_archetypes: Tuple[str, ...]
    notes: str = ""
    active: bool = True


# -----------------------------------------------------------------------------
# 13-code seed — LANE_A_SIGNED_SCOPE.md §4a
# -----------------------------------------------------------------------------
# Domestic (7): PPDADD, PPD, CPU, DELIVERED, COLLECT, GAMER_ARRANGED, THIRD_PARTY
# International (6): EX_WORK, FOB_PORT, DDP, DDU, CFR, DAT
#
# TODO (§4a.1): XPO and R&L are LTL carriers that historically warrant a $50
# freight-variance threshold override. Carrier-level overrides are handled by
# a future carrier_registry module, not here. These seed values use the
# $100 default fallback for domestic methods.
# -----------------------------------------------------------------------------

_DROP_SHIP_WAREHOUSE = ("drop_ship", "warehouse_order")
_ALL_OUTBOUND = (
    "drop_ship",
    "warehouse_order",
    "produce_and_hold",
    "assembly_order",
    "reroute",
)
_INTERNATIONAL_ARCHETYPES = (
    "drop_ship",
    "warehouse_order",
    "produce_and_hold",
)


_SEED: Tuple[ShipmentMethodRecord, ...] = (
    # ---------- Domestic ----------
    ShipmentMethodRecord(
        code="PPDADD",
        display_name="Prepaid & Add",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="SO",
        sell_price_source="customer_billed",
        arranged_by="gamer",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=PostBolUpdate(
            new_code_options=("THIRD_PARTY", "COLLECT"),
            when="bol_received",
            requires_reviewer_choice=True,
            applies_to_archetypes=_DROP_SHIP_WAREHOUSE,
        ),
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Freight on separate line with cost and sell price.",
    ),
    ShipmentMethodRecord(
        code="PPD",
        display_name="Prepaid",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="SO",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="gamer",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=PostBolUpdate(
            new_code_options=("THIRD_PARTY", "COLLECT"),
            when="bol_received",
            requires_reviewer_choice=True,
            applies_to_archetypes=_DROP_SHIP_WAREHOUSE,
        ),
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Freight cost wrapped in item sell price; FREIGHT line carries cost only.",
    ),
    ShipmentMethodRecord(
        code="CPU",
        display_name="Customer Pickup",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="neither",
        sell_price_source="not_billed",
        arranged_by="customer",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Customer arranges pickup at origin; no freight line expected.",
    ),
    ShipmentMethodRecord(
        code="DELIVERED",
        display_name="Delivered",
        region="domestic",
        fob_side="destination",
        date_field_driving_order="delivery_date",
        freight_line_expected_on="neither",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="supplier",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Vendor-arranged delivery; no freight line, no freight bill expected.",
    ),
    ShipmentMethodRecord(
        code="COLLECT",
        display_name="Collect",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="neither",
        sell_price_source="not_billed",
        arranged_by="customer",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Customer's carrier bills customer directly; GPI not invoiced.",
    ),
    ShipmentMethodRecord(
        code="GAMER_ARRANGED",
        display_name="Gamer Arranged",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="SO",
        sell_price_source="customer_billed",
        arranged_by="gamer",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Gamer sources and pays the carrier; rebilled to customer on SO.",
    ),
    ShipmentMethodRecord(
        code="THIRD_PARTY",
        display_name="Third-Party Billed",
        region="domestic",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="neither",
        sell_price_source="not_billed",
        arranged_by="third_party",
        customs_responsibility="n/a",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_ALL_OUTBOUND,
        notes="Carrier bills a third-party account; no GPI freight line.",
    ),
    # ---------- International (Incoterms) ----------
    ShipmentMethodRecord(
        code="EX_WORK",
        display_name="Ex Works (EXW)",
        region="international",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="PO",
        sell_price_source="not_billed",
        arranged_by="gamer",
        customs_responsibility="gamer",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Buyer (Gamer) bears all cost/risk from supplier's dock onward.",
    ),
    ShipmentMethodRecord(
        code="FOB_PORT",
        display_name="Free on Board (FOB) — Port",
        region="international",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="PO",
        sell_price_source="not_billed",
        arranged_by="gamer",
        customs_responsibility="gamer",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Risk transfers when goods pass ship's rail at origin port.",
    ),
    ShipmentMethodRecord(
        code="DDP",
        display_name="Delivered Duty Paid",
        region="international",
        fob_side="destination",
        date_field_driving_order="delivery_date",
        freight_line_expected_on="neither",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="supplier",
        customs_responsibility="supplier",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Supplier bears cost, risk, and duty through delivery.",
    ),
    ShipmentMethodRecord(
        code="DDU",
        display_name="Delivered Duty Unpaid",
        region="international",
        fob_side="destination",
        date_field_driving_order="delivery_date",
        freight_line_expected_on="neither",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="supplier",
        customs_responsibility="gamer",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Supplier delivers; buyer handles import duties/taxes.",
    ),
    ShipmentMethodRecord(
        code="CFR",
        display_name="Cost and Freight",
        region="international",
        fob_side="origin",
        date_field_driving_order="pickup_date",
        freight_line_expected_on="PO",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="supplier",
        customs_responsibility="gamer",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Supplier pays freight to named destination port; risk transfers at origin.",
    ),
    ShipmentMethodRecord(
        code="DAT",
        display_name="Delivered at Terminal",
        region="international",
        fob_side="destination",
        date_field_driving_order="delivery_date",
        freight_line_expected_on="neither",
        sell_price_source="wrapped_in_item_cost",
        arranged_by="supplier",
        customs_responsibility="gamer",
        freight_variance_threshold_usd=None,
        post_bol_update=None,
        allowed_archetypes=_INTERNATIONAL_ARCHETYPES,
        notes="Supplier delivers and unloads at named terminal; buyer clears customs.",
    ),
)


# Index by uppercase code. Unique enforcement happens at import time below.
_BY_CODE: dict[str, ShipmentMethodRecord] = {}
for _rec in _SEED:
    _normalized = _rec.code.upper()
    if _normalized != _rec.code:
        raise ValueError(
            f"shipment_methods seed code {_rec.code!r} must be uppercase"
        )
    if _normalized in _BY_CODE:
        raise ValueError(
            f"shipment_methods seed contains duplicate code: {_normalized!r}"
        )
    _BY_CODE[_normalized] = _rec


# -----------------------------------------------------------------------------
# Public lookups — pure, no I/O
# -----------------------------------------------------------------------------

def get(code: str) -> Optional[ShipmentMethodRecord]:
    """Return the record for ``code`` (case-insensitive) or None if unknown."""
    if not code:
        return None
    return _BY_CODE.get(code.strip().upper())


def exists(code: str) -> bool:
    """True iff ``code`` (case-insensitive) is a known shipment method."""
    return get(code) is not None


def list_all() -> Tuple[ShipmentMethodRecord, ...]:
    """All 13 seed records in declaration order."""
    return _SEED


def list_by_region(region: Region) -> Tuple[ShipmentMethodRecord, ...]:
    """Records filtered by ``region`` in declaration order."""
    return tuple(r for r in _SEED if r.region == region)


def list_codes() -> Tuple[str, ...]:
    """All 13 seed codes in declaration order."""
    return tuple(r.code for r in _SEED)


def list_for_archetype(archetype: str) -> Tuple[ShipmentMethodRecord, ...]:
    """Records whose ``allowed_archetypes`` includes ``archetype``.

    Matching is exact (case-sensitive) since archetype identifiers are
    controlled strings, not user input.
    """
    return tuple(r for r in _SEED if archetype in r.allowed_archetypes)
