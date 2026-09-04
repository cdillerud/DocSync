"""Profiled customer-PDF mapping rules proven from Gamer Packaging evidence.

This layer is deliberately separate from parsing:

- Parsers preserve what the customer PO says.
- This module applies narrowly proven customer/item/ship-to/UOM mappings.
- Business Central still owns final transaction validation and price authority.
- Duplicate evidence wins over PASS: an already-existing customer PO must never create
  a second Sales Order.

The rules here are intentionally fail-closed. They do not generalize from one customer
format to another, and they do not treat historical quantity as a universal template.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re
from typing import Mapping, Optional

from .models import NormalizedInboundOrder, ProposedAction


_BERNER_CUSTOMER_NO = "BERNER"
_BERNER_SOURCE_PART = "811476"
_BERNER_SOURCE_ALIAS = "21579-858231"
_BERNER_BC_ITEM = "21759-858231"
_BERNER_SHIP_TO = "78899028"
_BERNER_LOCATION = "00"
_BERNER_PROVEN_SOURCE_QTY = Decimal("68000")
_BERNER_PROVEN_BC_QTY = 72.2
_BERNER_BC_UOM = "M"

_HERDEZ_CUSTOMER_NO = "HERDEZ"
_HERDEZ_SOURCE_PART = "000000000004003467"
_HERDEZ_BC_ITEM = "20113526"
_HERDEZ_SHIP_TO = "001"
_HERDEZ_LOCATION = "00"
_HERDEZ_BC_UOM = "M"


def _normalized(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _decimal(value: Optional[float]) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def _set_duplicate(
    order: NormalizedInboundOrder,
    *,
    existing_order: str,
) -> NormalizedInboundOrder:
    for release in order.releases:
        release.existing_gamer_order = existing_order
    if order.validation is None:
        raise ValueError("Normalized customer PO must include validation before mapping.")
    order.validation.duplicate_status = "DUPLICATE_EXISTING_GAMER_ORDER"
    order.validation.proposed_action = ProposedAction.DUPLICATE
    order.validation.exceptions.append(
        f"Customer PO already exists in Gamer Business Central as Sales Order {existing_order}; creation blocked."
    )
    return order


def _resolve_berner(order: NormalizedInboundOrder) -> NormalizedInboundOrder:
    if order.validation is None:
        raise ValueError("Normalized customer PO must include validation before mapping.")
    if len(order.releases) != 1:
        order.validation.exceptions.append(
            "Berner profiled rule currently requires exactly one customer product line; REVIEW."
        )
        return order

    release = order.releases[0]
    source_ship_to = _normalized(release.ship_to_candidate)
    description = _normalized(release.description)
    source_qty = _decimal(release.physical_quantity)

    customer_match = "BERNER" in _normalized(order.customer.candidate_customer_name)
    item_match = release.customer_item_reference == _BERNER_SOURCE_PART
    alias_match = _normalized(_BERNER_SOURCE_ALIAS) in description
    ship_to_match = (
        "5778BAXTERROAD" in source_ship_to
        and "ROCKFORD" in source_ship_to
        and "61109" in source_ship_to
    )
    uom_match = (release.physical_uom or "").upper() == "EA"
    quantity_match = source_qty == _BERNER_PROVEN_SOURCE_QTY

    if not customer_match:
        order.validation.exceptions.append("Berner customer identity did not match the profiled customer rule.")
        return order
    if not item_match or not alias_match:
        order.validation.item_status = "REVIEW_SOURCE_ITEM_NOT_PROFILED"
        order.validation.exceptions.append(
            "Berner line must contain source part 811476 and repeated source alias 21579-858231; REVIEW."
        )
        return order
    if not ship_to_match:
        order.validation.ship_to_status = "REVIEW_SHIP_TO_NOT_PROFILED"
        order.validation.exceptions.append(
            "Berner profiled rule requires 5778 Baxter Road, Rockford IL 61109; REVIEW."
        )
        return order
    if not uom_match or not quantity_match:
        order.validation.quantity_status = "REVIEW_BERNER_PACKOUT_NOT_PROFILED"
        order.validation.exceptions.append(
            "Berner 72.2 M conversion is proven only for the repeated 68,000 EA source pattern; a different quantity/UOM must not inherit that historical packout."
        )
        return order

    order.customer.resolved_customer_no = _BERNER_CUSTOMER_NO
    order.customer.resolution_method = "profiled_customer_pdf_repeated_bc_transaction_evidence"
    order.customer.resolution_confidence = 1.0
    order.customer.evidence.append(
        "Three independent Berner PO/Sales Order chains resolve 811476 + 21579-858231 to BC item 21759-858231 and Ship-to 78899028."
    )

    release.resolved_item_no = _BERNER_BC_ITEM
    release.item_resolution_method = "berner_profile_3_exact_po_so_chains"
    release.resolved_ship_to_code = _BERNER_SHIP_TO
    release.ship_to_resolution_method = "exact_profiled_address"
    release.resolved_location_code = _BERNER_LOCATION
    release.quantity = _BERNER_PROVEN_BC_QTY
    release.uom = _BERNER_BC_UOM
    release.quantity_resolution_method = "berner_exact_68000_ea_to_72_2_m_profile"
    release.parser_review_reasons = [
        reason
        for reason in release.parser_review_reasons
        if "BC transaction quantity/UOM unresolved" not in reason
    ]

    order.validation.customer_status = "RESOLVED_PROFILED_CUSTOMER"
    order.validation.item_status = "RESOLVED_PROFILED_CUSTOMER_ITEM_ALIAS"
    order.validation.quantity_status = "RESOLVED_EXACT_PROFILED_PACKOUT"
    order.validation.ship_to_status = "RESOLVED_PROFILED_SHIP_TO"
    order.validation.location_status = "RESOLVED_PROFILED_LOCATION"
    order.validation.price_status = "SOURCE_CORROBORATION_ONLY_BC_AUTHORITY_REQUIRED"
    order.validation.exceptions = [
        "Source price matches repeated historical evidence but is not pricing authority; Business Central must independently resolve/validate price."
    ]
    order.validation.proposed_action = ProposedAction.PASS
    return order


def _resolve_herdez(order: NormalizedInboundOrder) -> NormalizedInboundOrder:
    if order.validation is None:
        raise ValueError("Normalized customer PO must include validation before mapping.")
    if len(order.releases) != 1:
        order.validation.exceptions.append(
            "Herdez profiled rule currently requires exactly one customer product line; REVIEW."
        )
        return order

    release = order.releases[0]
    source_ship_to = _normalized(release.ship_to_candidate)
    source_qty = _decimal(release.physical_quantity)

    customer_match = "HERDEZ" in _normalized(order.customer.candidate_customer_name)
    item_match = release.customer_item_reference == _HERDEZ_SOURCE_PART
    ship_to_match = (
        "AVINDUSTRIAS3815" in source_ship_to
        and "78395" in source_ship_to
    )
    uom_match = (release.physical_uom or "").upper() == _HERDEZ_BC_UOM
    quantity_valid = source_qty is not None and source_qty > 0

    if not customer_match:
        order.validation.exceptions.append("Herdez customer identity did not match the profiled customer rule.")
        return order
    if not item_match:
        order.validation.item_status = "REVIEW_SOURCE_ITEM_NOT_PROFILED"
        order.validation.exceptions.append(
            "Herdez source material is not the proven 000000000004003467 mapping; REVIEW."
        )
        return order
    if not ship_to_match:
        order.validation.ship_to_status = "REVIEW_SHIP_TO_NOT_PROFILED"
        order.validation.exceptions.append(
            "Herdez profiled rule requires the SLP factory address at AV. INDUSTRIAS 3815 / 78395; REVIEW."
        )
        return order
    if not uom_match or not quantity_valid:
        order.validation.quantity_status = "REVIEW_HERDEZ_UOM_NOT_PROFILED"
        order.validation.exceptions.append(
            "Herdez direct quantity mapping requires a positive source quantity semantically normalized to M; REVIEW."
        )
        return order

    order.customer.resolved_customer_no = _HERDEZ_CUSTOMER_NO
    order.customer.resolution_method = "profiled_customer_pdf_current_bc_transaction_evidence"
    order.customer.resolution_confidence = 1.0
    order.customer.evidence.append(
        "Current Sales Order evidence and eleven current item lines corroborate HERDEZ / 20113526 / M / Location 00."
    )

    release.resolved_item_no = _HERDEZ_BC_ITEM
    release.item_resolution_method = "herdez_profile_current_bc_order_plus_repeated_item_lines"
    release.resolved_ship_to_code = _HERDEZ_SHIP_TO
    release.ship_to_resolution_method = "exact_profiled_address"
    release.resolved_location_code = _HERDEZ_LOCATION
    # Incoming PO owns quantity. Once THOUSAND->M semantics and the exact customer/item
    # UOM relationship are proven, carry the incoming positive M quantity through.
    release.quantity = float(source_qty)
    release.uom = _HERDEZ_BC_UOM
    release.quantity_resolution_method = "direct_incoming_quantity_after_profiled_thousand_to_m_equivalence"
    release.parser_review_reasons = [
        reason
        for reason in release.parser_review_reasons
        if "BC transaction" not in reason and "BC transaction equivalence" not in reason
    ]

    order.validation.customer_status = "RESOLVED_PROFILED_CUSTOMER"
    order.validation.item_status = "RESOLVED_PROFILED_CUSTOMER_ITEM"
    order.validation.quantity_status = "RESOLVED_DIRECT_INCOMING_QUANTITY"
    order.validation.ship_to_status = "RESOLVED_PROFILED_SHIP_TO"
    order.validation.location_status = "RESOLVED_PROFILED_LOCATION"
    order.validation.price_status = "SOURCE_CORROBORATION_ONLY_BC_AUTHORITY_REQUIRED"
    order.validation.exceptions = [
        "Source price is corroborating evidence only; Business Central must independently resolve/validate price."
    ]
    order.validation.proposed_action = ProposedAction.PASS
    return order


def apply_profiled_customer_pdf_mapping(
    inbound_order: NormalizedInboundOrder,
    *,
    existing_customer_po_orders: Optional[Mapping[str, str]] = None,
) -> NormalizedInboundOrder:
    """Apply only the currently proven Berner/Herdez customer-PDF mappings.

    ``existing_customer_po_orders`` is explicit duplicate evidence from BC discovery.
    A matching customer PO is marked DUPLICATE after mapping, so the caller can still
    inspect the deterministic mapping while creation remains blocked.
    """

    order = deepcopy(inbound_order)
    if order.validation is None:
        raise ValueError("Normalized customer PO must include validation before mapping.")

    if order.source.source_format == "BERNER_PDF":
        order = _resolve_berner(order)
    elif order.source.source_format == "HERDEZ_COUPA_PDF_TEXT":
        order = _resolve_herdez(order)
    else:
        order.validation.exceptions.append(
            f"No profiled customer-PDF mapping exists for source format {order.source.source_format!r}."
        )
        return order

    existing = None
    if existing_customer_po_orders and order.document.customer_order_reference:
        existing = existing_customer_po_orders.get(order.document.customer_order_reference)
    if existing:
        return _set_duplicate(order, existing_order=existing)
    return order
