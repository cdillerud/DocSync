"""
GPI Hub — Shipment-method rule engine (Lane C Step 2.5)

Pure resolution on top of ``registry.py``. Given a shipment-method code
(and optionally an archetype), returns a frozen ResolvedRules record
summarizing what the system should expect on the document and downstream.

No side effects. No DB. No network. No imports of server.py, services/*,
routers/*, or other workflows/* modules. Unwired by design.
"""

from dataclasses import dataclass
from typing import Optional

from .registry import (
    PostBolUpdate,
    ShipmentMethodRecord,
    get as _get_record,
)

# §4a.1 — default fallback when a record's freight_variance_threshold_usd is None.
# Carrier-level overrides (e.g. XPO/R&L $50) are a future carrier_registry concern.
FREIGHT_VARIANCE_DEFAULT: float = 100.0


@dataclass(frozen=True)
class ResolvedRules:
    """Flat, frozen view of the rules that apply to a shipment-method code.

    ``known=False`` is the sentinel for unknown codes — callers check this
    instead of handling None. The remaining fields carry safe defaults so
    pattern-matching code doesn't have to None-guard every field.
    """
    code: str
    known: bool
    display_name: str
    region: str
    fob_side: str
    date_field_driving_order: str
    freight_line_expected_on: str
    sell_price_source: str
    arranged_by: str
    customs_responsibility: str
    has_freight_line_expected: bool
    expects_freight_invoice: bool
    freight_has_sell_price: bool
    freight_variance_threshold_usd: float
    post_bol_update: Optional[PostBolUpdate]
    archetype_allowed: Optional[bool]        # None when no archetype was supplied
    allowed_archetypes: tuple
    active: bool
    notes: str


_UNKNOWN = ResolvedRules(
    code="",
    known=False,
    display_name="",
    region="",
    fob_side="",
    date_field_driving_order="",
    freight_line_expected_on="neither",
    sell_price_source="not_billed",
    arranged_by="",
    customs_responsibility="n/a",
    has_freight_line_expected=False,
    expects_freight_invoice=False,
    freight_has_sell_price=False,
    freight_variance_threshold_usd=FREIGHT_VARIANCE_DEFAULT,
    post_bol_update=None,
    archetype_allowed=None,
    allowed_archetypes=(),
    active=False,
    notes="",
)


def _derive_has_freight_line_expected(record: ShipmentMethodRecord) -> bool:
    return record.freight_line_expected_on in ("SO", "PO")


def _derive_expects_freight_invoice(record: ShipmentMethodRecord) -> bool:
    # A freight invoice is expected when Gamer arranges carriage. Supplier-
    # arranged methods (DDP/DELIVERED/DDU/DAT/CFR) ship with cost wrapped into
    # the item; customer-arranged (CPU/COLLECT) and third-party billed are
    # outside Gamer's AP scope.
    return record.arranged_by == "gamer"


def _derive_freight_has_sell_price(record: ShipmentMethodRecord) -> bool:
    return record.sell_price_source == "customer_billed"


def resolve_rules(code: str, archetype: Optional[str] = None) -> ResolvedRules:
    """Resolve the rule set for ``code``.

    If ``archetype`` is provided, ``archetype_allowed`` reflects membership
    in the record's ``allowed_archetypes`` tuple; otherwise it is None.

    Unknown codes return the ``_UNKNOWN`` sentinel with ``known=False``.
    """
    record = _get_record(code)
    if record is None:
        if archetype is None:
            return _UNKNOWN
        # Even for unknown codes we still reflect that the archetype is not
        # in any allowed set (since allowed_archetypes=() here).
        return ResolvedRules(**{**_UNKNOWN.__dict__, "archetype_allowed": False})

    archetype_allowed: Optional[bool]
    if archetype is None:
        archetype_allowed = None
    else:
        archetype_allowed = archetype in record.allowed_archetypes

    threshold = (
        record.freight_variance_threshold_usd
        if record.freight_variance_threshold_usd is not None
        else FREIGHT_VARIANCE_DEFAULT
    )

    return ResolvedRules(
        code=record.code,
        known=True,
        display_name=record.display_name,
        region=record.region,
        fob_side=record.fob_side,
        date_field_driving_order=record.date_field_driving_order,
        freight_line_expected_on=record.freight_line_expected_on,
        sell_price_source=record.sell_price_source,
        arranged_by=record.arranged_by,
        customs_responsibility=record.customs_responsibility,
        has_freight_line_expected=_derive_has_freight_line_expected(record),
        expects_freight_invoice=_derive_expects_freight_invoice(record),
        freight_has_sell_price=_derive_freight_has_sell_price(record),
        freight_variance_threshold_usd=threshold,
        post_bol_update=record.post_bol_update,
        archetype_allowed=archetype_allowed,
        allowed_archetypes=record.allowed_archetypes,
        active=record.active,
        notes=record.notes,
    )
