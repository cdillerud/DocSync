"""Semantic-preserving hydration for V117 learned AP routing.

The legacy corpus hydrator extracted PDF text for BC/reference work but did not
persist that text into the supervised example. This adapter preserves a bounded
route-neutral semantic snapshot before the source file is deleted. It does not
inspect or select route labels; Accounting placement remains the only label.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional

import httpx

from services import ap_routing_corpus_service as corpus
from services.ap_routing_learned_features_service import (
    SEMANTIC_FEATURE_SCHEMA,
    semantic_feature_snapshot,
)


logger = logging.getLogger(__name__)

HYDRATION_POLICY_VERSION = "v117-hydration-retry-v1"
HYDRATION_MAX_ATTEMPTS = 3
_HYDRATION_RETRY_DELAYS_SECONDS = (0.5, 1.5)

_COMPACT_FILENAME_DATE_TOKEN = re.compile(r"(?<![A-Z0-9])(\d{6}|\d{8})(?![A-Z0-9])", re.IGNORECASE)
_EXPLICIT_PO_PREFIX = re.compile(
    r"(?:^|[_\-\s.])(?:P\.?O\.?|PURCHASE[_\-\s.]+ORDER)[_\-\s.]*$",
    re.IGNORECASE,
)
_RESOLVED_BC_CONTEXT_STATUSES = {"resolved", "resolved_shipment", "matched", "verified"}
_BC_AUTHORITY_KEYS = (
    "po_number",
    "bc_record_id",
    "bc_entity_type",
    "confidence",
    "match_method",
    "lookup_source",
    "bc_vendor_no",
    "bc_vendor_name",
    "bc_customer_no",
    "bc_customer_name",
    "bc_order_number",
    "bc_status",
    "live_bc_context",
    "location_code",
    "ship_to_name",
    "ship_to_address",
    "ship_to_city",
    "ship_to_state",
    "ship_to_country",
)


def _is_compact_calendar_date(value: str) -> bool:
    token = str(value or "").strip()
    if not token.isdigit():
        return False
    formats = ("%m%d%y",) if len(token) == 6 else (("%m%d%Y", "%Y%m%d") if len(token) == 8 else ())
    for fmt in formats:
        try:
            datetime.strptime(token, fmt)
            return True
        except ValueError:
            continue
    return False


def _normalize_numeric_reference(value: Any) -> str:
    token = str(value or "").strip().upper()
    if token.isdigit():
        return token.lstrip("0") or "0"
    return token


def compact_unlabeled_filename_date_refs(file_name: str) -> set[str]:
    """Return normalized compact date tokens that must not act as PO evidence.

    Explicitly PO-labeled values (for example PO_091026) are intentionally
    retained because the label is stronger evidence than the numeric shape.
    """
    name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    refs: set[str] = set()
    for match in _COMPACT_FILENAME_DATE_TOKEN.finditer(name):
        raw = match.group(1)
        if not _is_compact_calendar_date(raw):
            continue
        if _EXPLICIT_PO_PREFIX.search(name[: match.start()]):
            continue
        refs.add(raw.lstrip("0") or "0")
    return refs


def sanitize_filename_for_reference_resolution(file_name: str) -> str:
    """Blank ambiguous compact dates before the read-only BC PO resolver runs."""
    name = str(file_name or "")

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        if not _is_compact_calendar_date(raw):
            return raw
        if _EXPLICIT_PO_PREFIX.search(name[: match.start()]):
            return raw
        return " "

    return _COMPACT_FILENAME_DATE_TOKEN.sub(_replace, name)


def _resolved_filename_date_collisions(context: Dict[str, Any], file_name: str) -> set[str]:
    """Return compact filename-date refs that won a resolved BC lookup."""
    status = str(context.get("status") or context.get("resolution_status") or "").strip().lower()
    if status not in _RESOLVED_BC_CONTEXT_STATUSES:
        return set()
    blocked = compact_unlabeled_filename_date_refs(file_name)
    if not blocked:
        return set()
    live = context.get("live_bc_context") or {}
    values = (
        context.get("po_number"),
        context.get("bc_document_no"),
        context.get("bc_order_number"),
        live.get("bc_document_no"),
        live.get("bc_order_number"),
    )
    resolved = {_normalize_numeric_reference(value) for value in values if value}
    return blocked.intersection(resolved)


def _remove_blocked_reference_tokens(value: Any, blocked_refs: set[str]) -> Any:
    """Remove only tokens that normalize to blocked filename-date references."""
    if not blocked_refs:
        return value
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            raw = match.group(1)
            return " " if _normalize_numeric_reference(raw) in blocked_refs else raw

        cleaned = _COMPACT_FILENAME_DATE_TOKEN.sub(_replace, value)
        if "," in cleaned:
            parts = []
            for part in cleaned.split(","):
                candidate = part.strip()
                if candidate and _normalize_numeric_reference(candidate) not in blocked_refs:
                    parts.append(candidate)
            return ", ".join(parts)
        return cleaned.strip()
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _remove_blocked_reference_tokens(item, blocked_refs)) not in (None, "")
        ]
    return value


def _sanitize_resolver_inputs_for_filename_dates(
    document: Dict[str, Any],
    bundle: Optional[Dict[str, Any]],
    file_name: str,
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Remove filename-date-shaped values from every BC resolver input channel.

    This is intentionally conservative. If a filename contains an unlabeled
    compact calendar date, that value may not become BC authority through a
    secondary extraction channel (AI fields, raw text, or supporting refs).
    Explicitly PO-labeled filename values are not in the blocked set and remain.
    """
    blocked_refs = compact_unlabeled_filename_date_refs(file_name)
    prepared = dict(document)
    prepared["file_name"] = sanitize_filename_for_reference_resolution(file_name)
    if not blocked_refs:
        return prepared, bundle

    fields = dict(prepared.get("extracted_fields") or {})
    for key, value in list(fields.items()):
        fields[key] = _remove_blocked_reference_tokens(value, blocked_refs)
    prepared["extracted_fields"] = fields
    prepared["raw_text"] = _remove_blocked_reference_tokens(prepared.get("raw_text") or "", blocked_refs)

    if not bundle:
        return prepared, bundle
    cleaned_bundle = dict(bundle)
    references = {}
    for field, items in dict(bundle.get("references") or {}).items():
        kept = []
        for item in items or []:
            raw_value = item.get("value") if isinstance(item, dict) else item
            if _normalize_numeric_reference(raw_value) in blocked_refs:
                continue
            kept.append(dict(item) if isinstance(item, dict) else item)
        references[field] = kept
    cleaned_bundle["references"] = references
    return prepared, cleaned_bundle


def _quarantine_filename_date_collision(
    context: Dict[str, Any],
    collisions: set[str],
) -> Dict[str, Any]:
    """Fail closed when a compact filename date still wins after re-resolution."""
    quarantined = dict(context)
    for key in _BC_AUTHORITY_KEYS:
        quarantined.pop(key, None)
    quarantined.update(
        {
            "status": "not_found",
            "miss_reason": "filename_compact_date_collision",
            "reason": "resolved_bc_reference_matches_compact_filename_date",
            "verified_order_numbers": [],
            "best_match": None,
            "matches": [],
            "candidates_raw": [],
            "candidates_valid": [],
            "candidates_tried": [],
            "lookup_trace": [],
            "filename_date_collision_refs": sorted(collisions),
        }
    )
    return quarantined


async def _resolve_context_without_filename_date_collision(
    document: Dict[str, Any],
    bundle: Optional[Dict[str, Any]],
    file_name: str,
) -> Dict[str, Any]:
    """Resolve BC context and guarantee the stored winner is replay-safe."""
    initial_document = dict(document)
    initial_document["file_name"] = sanitize_filename_for_reference_resolution(file_name)
    context = await corpus.resolve_ap_routing_context(initial_document, bundle_refs=bundle)
    collisions = _resolved_filename_date_collisions(context, file_name)
    if not collisions:
        return context

    safe_document, safe_bundle = _sanitize_resolver_inputs_for_filename_dates(
        document,
        bundle,
        file_name,
    )
    rerun = await corpus.resolve_ap_routing_context(safe_document, bundle_refs=safe_bundle)
    remaining = _resolved_filename_date_collisions(rerun, file_name)
    if remaining:
        final = _quarantine_filename_date_collision(rerun, remaining)
        outcome = "quarantined"
        final_ref = ""
    else:
        final = rerun
        outcome = "reresolved"
        final_ref = str(rerun.get("po_number") or rerun.get("bc_order_number") or "")
    print(
        "V117_FILENAME_DATE_COLLISION_RERESOLVE="
        f"file={file_name};blocked_refs={','.join(sorted(collisions))};"
        f"outcome={outcome};final_ref={final_ref}",
        flush=True,
    )
    return final


def enrich_routing_example_with_semantics(
    example: Dict[str, Any],
    *,
    document: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach route-neutral semantic evidence to a human-labeled example."""
    prepared = dict(example)
    snapshot = semantic_feature_snapshot(document)
    features = list(snapshot["features"])
    fields = dict(prepared.get("extracted_fields") or document.get("extracted_fields") or {})
    fields["_learned_feature_schema"] = SEMANTIC_FEATURE_SCHEMA
    fields["_learned_semantic_features"] = features

    prepared.update(
        {
            "raw_text_excerpt": str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:12000],
            "learned_feature_schema": SEMANTIC_FEATURE_SCHEMA,
            "learned_semantic_features": features,
            "learned_reference_family": snapshot["reference_family"],
            "extracted_fields": fields,
        }
    )
    return prepared


def _is_transient_hydration_error(exc: BaseException) -> bool:
    """Return True only for bounded retry-safe transport failures."""
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


async def _hydrate_accounting_label_with_semantics_once(
    label: Dict[str, Any],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hydrate one Accounting label once; caller owns retry policy."""
    file_name = str(label["file_name"])
    suffix = Path(file_name).suffix or ".bin"
    local_path = await corpus._download_graph_file(label["drive_id"], label["item_id"], suffix)
    try:
        primary = await corpus.classify_primary_document(local_path, file_name)
        primary_type = primary.get("suggested_job_type") or primary.get("document_type") or "Unknown_Document"
        primary_fields = dict(primary.get("extracted_fields") or {})
        bundle = await corpus.extract_supporting_references(
            local_path,
            file_name,
            primary_document_type=primary_type,
            primary_fields=primary_fields,
        )
        raw_text = corpus._extract_text_excerpt(local_path)
        document = {
            "id": f"accounting-temp:{label['item_id']}",
            "file_name": file_name,
            "document_type": primary_type,
            "suggested_job_type": primary_type,
            "confidence": primary.get("confidence"),
            "extracted_fields": primary_fields,
            "raw_text": raw_text,
        }
        # Filename dates such as 091026, 090326, and 090926 can otherwise look
        # like legitimate 5-6 digit BC POs after leading-zero normalization.
        # The first pass preserves all non-filename evidence. If one of those
        # unlabeled filename dates still wins through another extraction channel,
        # re-resolve with that date removed from every resolver input and fail
        # closed if it somehow remains the winner.
        bc_context = await _resolve_context_without_filename_date_collision(
            document,
            bundle,
            file_name,
        )
        vendor_name = (
            primary_fields.get("vendor")
            or primary_fields.get("vendor_name")
            or bc_context.get("bc_vendor_name")
            or ((bc_context.get("live_bc_context") or {}).get("bc_vendor_name"))
            or ""
        )

        queue_route = corpus.normalize_route_path(label.get("route_path"))
        source_route = corpus.normalize_route_path(label.get("source_route_path") or queue_route)
        label_resolution = str(label.get("route_label_resolution") or "raw_accounting_placement")
        if (
            routing_contract
            and source_route
            and source_route != queue_route
            and not corpus._learning_exclusion_for_route(source_route, routing_contract)
            and corpus.route_is_allowed(source_route, routing_contract, bc_context)
        ):
            queue_route = source_route
            label_resolution = "verified_dynamic_route"

        example = {
            "label_source": corpus.LABEL_SOURCE_ACCOUNTING_TEMP,
            "source_item_id": label["item_id"],
            "source_drive_id": label["drive_id"],
            "source_web_url": label.get("web_url"),
            "source_route_path": source_route,
            "route_label_resolution": label_resolution,
            "file_name": file_name,
            "route_path": queue_route,
            "vendor_name": vendor_name,
            "document_type": primary_type,
            "classification_confidence": primary.get("confidence"),
            "extracted_fields": primary_fields,
            "bundle_references": bundle,
            "bc_context": bc_context,
            "key_evidence": {
                "invoice_number": primary_fields.get("invoice_number"),
                "po_number": bc_context.get("po_number"),
                "location_code": bc_context.get("location_code"),
                "supporting_references": bundle.get("references"),
            },
            "created_at": label.get("created_at"),
            "modified_at": label.get("modified_at"),
        }
        return corpus.prepare_routing_example(
            enrich_routing_example_with_semantics(example, document=document)
        )
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass


async def hydrate_accounting_label_with_semantics(
    label: Dict[str, Any],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Hydrate with bounded retry for transient transport failures only."""
    file_name = str(label.get("file_name") or "")
    for attempt in range(1, HYDRATION_MAX_ATTEMPTS + 1):
        try:
            result = await _hydrate_accounting_label_with_semantics_once(
                label,
                routing_contract=routing_contract,
            )
            if attempt > 1:
                print(
                    "V117_HYDRATION_RETRY_RECOVERED="
                    f"file={file_name};attempts={attempt};policy={HYDRATION_POLICY_VERSION}",
                    flush=True,
                )
            return result
        except Exception as exc:
            transient = _is_transient_hydration_error(exc)
            if not transient or attempt >= HYDRATION_MAX_ATTEMPTS:
                raise
            delay = _HYDRATION_RETRY_DELAYS_SECONDS[attempt - 1]
            print(
                "V117_HYDRATION_RETRY="
                f"file={file_name};attempt={attempt};next_attempt={attempt + 1};"
                f"delay_seconds={delay};error={type(exc).__name__};policy={HYDRATION_POLICY_VERSION}",
                flush=True,
            )
            logger.warning(
                "V117 transient hydration failure for %s on attempt %s/%s: %s",
                file_name,
                attempt,
                HYDRATION_MAX_ATTEMPTS,
                str(exc)[:300],
            )
            await asyncio.sleep(delay)
