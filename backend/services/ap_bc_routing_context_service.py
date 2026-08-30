"""Read-only Business Central context enrichment for AP routing.

The purpose of this service is to give routing intelligence authoritative BC
facts without embedding routing policy in the BC lookup itself. It never writes
to BC. The learned routing model decides how verified BC facts relate to the
Accounting Temp labels, subject to the route safety contract.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.po_resolution_service import resolve_po_from_document

logger = logging.getLogger(__name__)


def _values_from_bundle(bundle: Optional[Dict[str, Any]], field: str) -> List[str]:
    if not bundle:
        return []
    refs = (bundle.get("references") or {}).get(field) or []
    values: List[str] = []
    for item in refs:
        value = item.get("value") if isinstance(item, dict) else item
        if value and str(value).strip() not in values:
            values.append(str(value).strip())
    return values


def enrich_document_with_bundle_refs(
    document: Dict[str, Any],
    bundle_refs: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Copy a document and expose bundle PO/order evidence to the existing resolver."""
    enriched = dict(document)
    fields = dict(enriched.get("extracted_fields") or enriched.get("ai_extraction") or {})

    po_values = _values_from_bundle(bundle_refs, "po_numbers")
    order_values = _values_from_bundle(bundle_refs, "order_numbers")
    bol_values = _values_from_bundle(bundle_refs, "bol_numbers")
    shipment_values = _values_from_bundle(bundle_refs, "shipment_numbers")
    reference_values = _values_from_bundle(bundle_refs, "reference_numbers")

    if po_values:
        fields["po_number"] = ", ".join(po_values)
    if order_values and not fields.get("order_number"):
        fields["order_number"] = ", ".join(order_values)
    if bol_values and not fields.get("bol_number"):
        fields["bol_number"] = bol_values[0]
    if shipment_values and not fields.get("shipment_number"):
        fields["shipment_number"] = shipment_values[0]
    if reference_values and not fields.get("reference_number"):
        fields["reference_number"] = reference_values[0]

    enriched["extracted_fields"] = fields
    enriched["bundle_reference_evidence"] = bundle_refs or {}
    return enriched


async def _fetch_live_purchase_order_context(po_number: str) -> Dict[str, Any]:
    """Query BC READ environment for route-relevant PO facts.

    The standard helper currently omits locationCode despite its docstring. We
    request route-relevant fields explicitly and fall back to the standard
    helper if a tenant/API version rejects one of the optional fields.
    """
    if not po_number:
        return {}

    try:
        import httpx
        from services.business_central_service import (
            BC_API_BASE,
            BC_READ_ENVIRONMENT,
            BC_REQUEST_TIMEOUT,
            BC_TENANT_ID,
            get_bc_service,
            get_bc_token,
        )

        service = get_bc_service()
        if getattr(service, "use_mock", False):
            return {}
        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await service._get_company_id(environment=BC_READ_ENVIRONMENT)
        url = (
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/"
            f"companies({company_id})/purchaseOrders"
        )
        desired_fields = [
            "id",
            "number",
            "vendorNumber",
            "vendorName",
            "orderDate",
            "status",
            "locationCode",
            "shipToName",
            "shipToAddressLine1",
            "shipToCity",
            "shipToState",
            "shipToCountry",
        ]
        params = {
            "$filter": f"number eq '{str(po_number).replace(chr(39), chr(39) * 2)}'",
            "$select": ",".join(desired_fields),
            "$top": "1",
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if response.status_code == 200:
                rows = response.json().get("value", [])
                if rows:
                    row = rows[0]
                    return {
                        "bc_record_id": row.get("id", ""),
                        "bc_document_no": row.get("number", ""),
                        "bc_vendor_no": row.get("vendorNumber", ""),
                        "bc_vendor_name": row.get("vendorName", ""),
                        "bc_status": row.get("status", ""),
                        "bc_order_date": row.get("orderDate", ""),
                        "location_code": row.get("locationCode", ""),
                        "ship_to_name": row.get("shipToName", ""),
                        "ship_to_address": row.get("shipToAddressLine1", ""),
                        "ship_to_city": row.get("shipToCity", ""),
                        "ship_to_state": row.get("shipToState", ""),
                        "ship_to_country": row.get("shipToCountry", ""),
                        "context_source": "bc_api_route_context",
                    }

        # API versions can reject optional select fields. Fall back to the
        # existing read-only helper rather than treating that as no PO.
        fallback = await service.find_purchase_order_by_number(po_number)
        if fallback:
            return {
                "bc_record_id": fallback.get("id", ""),
                "bc_document_no": fallback.get("number", ""),
                "bc_vendor_no": fallback.get("vendorNumber", ""),
                "bc_vendor_name": fallback.get("vendorName", ""),
                "bc_status": fallback.get("status", ""),
                "bc_order_date": fallback.get("orderDate", ""),
                "location_code": fallback.get("locationCode", ""),
                "context_source": "bc_api_standard_fallback",
            }
    except Exception as exc:
        logger.warning("AP route BC context enrichment failed for PO %s: %s", po_number, str(exc)[:300])
    return {}


async def resolve_ap_routing_context(
    document: Dict[str, Any],
    *,
    bundle_refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve document references then enrich the winning PO with BC facts."""
    candidate_doc = enrich_document_with_bundle_refs(document, bundle_refs)
    resolution = await resolve_po_from_document(candidate_doc)
    context: Dict[str, Any] = dict(resolution or {})

    verified = []
    if context.get("po_number"):
        verified.append(str(context["po_number"]))
    for match in context.get("matches") or []:
        number = match.get("bc_document_no") if isinstance(match, dict) else None
        if number and str(number) not in verified:
            verified.append(str(number))
    context["verified_order_numbers"] = verified

    if str(context.get("status") or "").lower() in {"resolved", "resolved_shipment"}:
        po_number = str(context.get("po_number") or "")
        live = await _fetch_live_purchase_order_context(po_number)
        if live:
            context["live_bc_context"] = live
            # Promote non-empty route-relevant facts for easy prompt/governor use.
            for key in (
                "location_code",
                "ship_to_name",
                "ship_to_address",
                "ship_to_city",
                "ship_to_state",
                "ship_to_country",
            ):
                if live.get(key):
                    context[key] = live[key]
    return context
