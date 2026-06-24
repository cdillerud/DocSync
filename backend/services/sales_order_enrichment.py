"""Read-only enrichment for customer sales-order review.

The production GPI Hub already contains customer resolution, item mapping, learned
line patterns, and a Business Central reference cache.  This module calls those
services when they are available, while remaining import-safe in isolated feature
builds where the production-only services have not yet been reconciled into Git.
"""

from __future__ import annotations

import copy
import importlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.sales_order_preflight import build_sales_order_candidate


def _optional_attr(module_name: str, attribute: str):
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return None
    return getattr(module, attribute, None)


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _normalize_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _normalize_number(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _tokens(value: Any) -> set[str]:
    return {token for token in _normalize_text(value).split() if len(token) > 1}


def _customer_from_cache(record: Dict[str, Any]) -> Tuple[str, str]:
    return (
        str(
            _first(
                record.get("bc_customer_no"),
                record.get("customerNumber"),
                record.get("customer_no"),
                record.get("number") if record.get("bc_entity_type") == "customer" else None,
            )
            or ""
        ).strip(),
        str(
            _first(
                record.get("bc_customer_name"),
                record.get("customerName"),
                record.get("customer_name"),
                record.get("displayName"),
            )
            or ""
        ).strip(),
    )


def _existing_order_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    customer_no, customer_name = _customer_from_cache(record)
    return {
        "bc_record_id": record.get("bc_record_id") or record.get("id"),
        "bc_order_number": _first(
            record.get("bc_document_no"),
            record.get("number"),
            record.get("bc_order_number"),
        ),
        "external_document_number": _first(
            record.get("bc_external_document_no"),
            record.get("externalDocumentNumber"),
        ),
        "customer_number": customer_no,
        "customer_name": customer_name,
        "status": record.get("status"),
        "source": "bc_reference_cache",
    }


def _apply_customer(
    doc: Dict[str, Any],
    *,
    customer_number: str,
    customer_name: str,
    method: str,
    confidence: float,
    source: str,
) -> None:
    customer_number = str(customer_number or "").strip()
    customer_name = str(customer_name or "").strip()
    if customer_number:
        doc["bc_customer_no"] = customer_number
        doc["bc_customer_number"] = customer_number
        doc["customer_number_resolved"] = customer_number
        doc["matched_customer_no"] = customer_number
    if customer_name:
        doc["customer_name_extracted"] = customer_name

    doc["resolved_customer"] = {
        "number": customer_number,
        "customerNumber": customer_number,
        "displayName": customer_name,
        "name": customer_name,
        "match_method": method,
        "confidence": confidence,
        "source": source,
    }


async def _find_existing_order(
    db,
    external_document_number: str,
    customer_number: str = "",
) -> Tuple[Optional[Dict[str, Any]], Any, List[str]]:
    warnings: List[str] = []
    cache_class = _optional_attr(
        "services.bc_reference_cache_service",
        "BCReferenceCacheService",
    )
    if cache_class is None or not external_document_number:
        return None, None, warnings

    try:
        cache = cache_class(db)
        matches = await cache.search_by_external_reference(
            external_document_number,
            entity_types=["sales_order"],
        )
        if not matches:
            matches = await cache.search_multi(
                external_document_number,
                entity_types=["sales_order"],
            )
    except Exception as exc:  # enrichment must never make review unavailable
        warnings.append(f"BC order cache lookup failed: {exc}")
        return None, None, warnings

    if not matches:
        return None, cache, warnings

    if customer_number:
        normalized_customer = _normalize_number(customer_number)
        for match in matches:
            match_customer, _ = _customer_from_cache(match)
            if _normalize_number(match_customer) == normalized_customer:
                return match, cache, warnings

    return matches[0], cache, warnings


async def _fetch_bc_order_lines(
    cache,
    record: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if cache is None:
        return [], None

    record_id = record.get("bc_record_id") or record.get("id")
    if not record_id:
        return [], "Existing BC order cache record has no BC record ID"

    module_name = "services.bc_reference_cache_service"
    api_base = _optional_attr(module_name, "BC_API_BASE")
    tenant_id = _optional_attr(module_name, "BC_TENANT_ID")
    environment = _optional_attr(module_name, "BC_PROD_ENVIRONMENT")
    if not all((api_base, tenant_id, environment)):
        return [], "BC cache service does not expose production API configuration"

    try:
        import httpx

        token = await cache._get_token()
        if not token:
            return [], "BC token was unavailable for existing-order line lookup"
        company_id = await cache._get_company_id(token)
        if not company_id:
            return [], "BC company ID was unavailable for existing-order line lookup"

        url = (
            f"{api_base}/{tenant_id}/{environment}/api/v2.0/"
            f"companies({company_id})/salesOrders({record_id})/salesOrderLines"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$select": (
                        "lineType,lineObjectNumber,description,quantity,"
                        "unitPrice,unitOfMeasureCode"
                    )
                },
            )
        if response.status_code != 200:
            return [], (
                "Existing BC order line lookup failed with HTTP "
                f"{response.status_code}"
            )
        return response.json().get("value") or [], None
    except Exception as exc:  # read-only enrichment failure is nonfatal
        return [], f"Existing BC order line lookup failed: {exc}"


def _match_existing_order_line(
    source_line: Dict[str, Any],
    bc_lines: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    source_number = _normalize_number(
        _first(source_line.get("customerItemNumber"), source_line.get("itemNumber"))
    )
    source_description = _normalize_text(source_line.get("description"))
    source_tokens = _tokens(source_line.get("description"))

    if source_number:
        for line in bc_lines:
            if _normalize_number(line.get("lineObjectNumber")) == source_number:
                return {
                    "line": line,
                    "method": "existing_bc_order_item_exact",
                    "confidence": 1.0,
                }

    if source_description:
        for line in bc_lines:
            if _normalize_text(line.get("description")) == source_description:
                return {
                    "line": line,
                    "method": "existing_bc_order_description_exact",
                    "confidence": 0.99,
                }

    best_line = None
    best_score = 0.0
    for line in bc_lines:
        candidate_tokens = _tokens(line.get("description"))
        if len(source_tokens & candidate_tokens) < 2:
            continue
        score = len(source_tokens & candidate_tokens) / max(
            len(source_tokens), len(candidate_tokens), 1
        )
        if score > best_score:
            best_score = score
            best_line = line

    if best_line is not None and best_score >= 0.80:
        return {
            "line": best_line,
            "method": "existing_bc_order_description_tokens",
            "confidence": round(min(best_score, 0.97), 3),
        }
    return None


async def _catalog_item(db, item_number: str) -> Optional[Dict[str, Any]]:
    collection_name = _optional_attr(
        "services.bc_catalog_sync_service",
        "ITEMS_COLLECTION",
    )
    if not collection_name or not item_number:
        return None
    try:
        collection = db[collection_name]
        return await collection.find_one(
            {"item_no": item_number},
            {"_id": 0},
        )
    except Exception:
        return None


def _catalog_uom(item: Optional[Dict[str, Any]]) -> str:
    item = item or {}
    return str(
        _first(
            item.get("base_uom"),
            item.get("baseUnitOfMeasureCode"),
            item.get("unitOfMeasureCode"),
            item.get("uom"),
        )
        or ""
    ).strip()


async def enrich_sales_order_document(
    db,
    document: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return an enriched copy and read-only match evidence.

    No Business Central or Mongo writes occur here.  The caller decides what to
    persist after deterministic preflight completes.
    """

    enriched = copy.deepcopy(document)
    initial_candidate = build_sales_order_candidate(enriched)
    document_id = str(
        _first(enriched.get("document_id"), enriched.get("id")) or ""
    )
    evidence: Dict[str, Any] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "customer_resolution": None,
        "existing_order": None,
        "existing_order_lines_checked": 0,
        "line_mappings": [],
        "suggested_lines": [],
        "warnings": [],
    }

    external_number = str(initial_candidate.get("externalDocumentNumber") or "")
    current_customer = str(initial_candidate.get("customerNumber") or "")
    existing_order, cache, cache_warnings = await _find_existing_order(
        db,
        external_number,
        current_customer,
    )
    evidence["warnings"].extend(cache_warnings)

    bc_order_lines: List[Dict[str, Any]] = []
    if existing_order:
        summary = _existing_order_summary(existing_order)
        evidence["existing_order"] = summary
        if summary.get("customer_number"):
            _apply_customer(
                enriched,
                customer_number=summary.get("customer_number") or "",
                customer_name=summary.get("customer_name") or "",
                method="existing_bc_order",
                confidence=1.0,
                source="bc_reference_cache",
            )
        bc_order_lines, line_warning = await _fetch_bc_order_lines(
            cache,
            existing_order,
        )
        evidence["existing_order_lines_checked"] = len(bc_order_lines)
        if line_warning:
            evidence["warnings"].append(line_warning)

    candidate_after_cache = build_sales_order_candidate(enriched)
    if not candidate_after_cache.get("customerNumber"):
        resolver = _optional_attr(
            "services.entity_resolution_service",
            "resolve_customer",
        )
        if resolver is not None:
            try:
                resolution = await resolver(enriched)
                resolution_dict = (
                    resolution.to_dict()
                    if hasattr(resolution, "to_dict")
                    else dict(resolution or {})
                )
                evidence["customer_resolution"] = resolution_dict
                customer_number = str(
                    _first(
                        getattr(resolution, "customer_no", None),
                        resolution_dict.get("customer_no"),
                        resolution_dict.get("customerNumber"),
                    )
                    or ""
                )
                customer_name = str(
                    _first(
                        getattr(resolution, "customer_name", None),
                        resolution_dict.get("customer_name"),
                        resolution_dict.get("customerName"),
                    )
                    or ""
                )
                if customer_number:
                    _apply_customer(
                        enriched,
                        customer_number=customer_number,
                        customer_name=customer_name,
                        method=str(
                            _first(
                                getattr(resolution, "match_method", None),
                                resolution_dict.get("match_method"),
                                "entity_resolution",
                            )
                        ),
                        confidence=float(
                            _first(
                                getattr(resolution, "confidence", None),
                                resolution_dict.get("confidence"),
                                0,
                            )
                            or 0
                        ),
                        source=str(
                            _first(
                                getattr(resolution, "source", None),
                                resolution_dict.get("source"),
                                "entity_resolution",
                            )
                        ),
                    )
            except Exception as exc:
                evidence["warnings"].append(
                    f"Customer resolution failed: {exc}"
                )

    candidate = build_sales_order_candidate(enriched)
    customer_number = str(candidate.get("customerNumber") or "")
    lines = [dict(line) for line in (candidate.get("lines") or [])]
    mapper = _optional_attr(
        "services.item_mapping_service",
        "map_line_to_item",
    )

    for index, line in enumerate(lines, start=1):
        line_evidence: Dict[str, Any] = {
            "line": index,
            "matched": False,
            "method": "none",
            "confidence": 0.0,
            "item_number": line.get("itemNumber"),
            "uom": line.get("unitOfMeasureCode"),
        }

        existing_line_match = _match_existing_order_line(line, bc_order_lines)
        if existing_line_match:
            bc_line = existing_line_match["line"]
            line["itemNumber"] = bc_line.get("lineObjectNumber")
            line["unitOfMeasureCode"] = _first(
                line.get("unitOfMeasureCode"),
                bc_line.get("unitOfMeasureCode"),
            )
            line["unitPrice"] = _first(
                line.get("unitPrice"),
                bc_line.get("unitPrice"),
            )
            line["mappingStatus"] = "existing_bc_order"
            line["itemMatchConfidence"] = existing_line_match["confidence"]
            line["mappingMethod"] = existing_line_match["method"]
            line["catalogValidated"] = True
            line_evidence.update(
                {
                    "matched": True,
                    "method": existing_line_match["method"],
                    "confidence": existing_line_match["confidence"],
                    "item_number": line.get("itemNumber"),
                    "uom": line.get("unitOfMeasureCode"),
                    "source": "existing_bc_order",
                }
            )
        elif not line.get("itemNumber") and mapper is not None:
            try:
                mapping = await mapper(
                    db,
                    description=str(line.get("description") or ""),
                    extracted_sku=str(line.get("customerItemNumber") or ""),
                    customer_no=customer_number,
                    doc_id=document_id,
                )
            except Exception as exc:
                evidence["warnings"].append(
                    f"Line {index} item mapping failed: {exc}"
                )
                mapping = {}

            if mapping.get("matched") and mapping.get("target_type") == "item":
                item_number = str(mapping.get("target_no") or "").strip()
                catalog = await _catalog_item(db, item_number)
                catalog_validated = bool(mapping.get("catalog_validated")) or bool(
                    catalog and not catalog.get("blocked")
                )
                confidence = float(mapping.get("confidence") or 0)
                line["itemNumber"] = item_number
                line["unitOfMeasureCode"] = _first(
                    line.get("unitOfMeasureCode"),
                    _catalog_uom(catalog),
                )
                line["mappingStatus"] = (
                    "auto_matched"
                    if catalog_validated and confidence >= 0.95
                    else "suggested"
                )
                line["itemMatchConfidence"] = confidence
                line["mappingMethod"] = mapping.get("method")
                line["mappingId"] = mapping.get("mapping_id")
                line["catalogValidated"] = catalog_validated
                line_evidence.update(
                    {
                        "matched": True,
                        "method": mapping.get("method") or "item_mapping",
                        "confidence": confidence,
                        "item_number": item_number,
                        "uom": line.get("unitOfMeasureCode"),
                        "catalog_validated": catalog_validated,
                        "source": "item_mapping_service",
                    }
                )

        if line.get("itemNumber") and not line.get("unitOfMeasureCode"):
            catalog = await _catalog_item(db, str(line.get("itemNumber")))
            uom = _catalog_uom(catalog)
            if uom:
                line["unitOfMeasureCode"] = uom
                line_evidence["uom"] = uom

        evidence["line_mappings"].append(line_evidence)

    enriched["sales_order_lines"] = lines

    suggester = _optional_attr(
        "services.order_line_patterns",
        "get_suggested_lines",
    )
    if suggester is not None and customer_number and lines:
        try:
            evidence["suggested_lines"] = await suggester(
                db,
                customer_number,
                lines,
            )
        except Exception as exc:
            evidence["warnings"].append(
                f"Learned line suggestion lookup failed: {exc}"
            )

    enriched["sales_order_enrichment"] = evidence
    return enriched, evidence
