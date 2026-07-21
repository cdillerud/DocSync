"""Read-only AP decision replay and provenance trace.

This module intentionally performs only MongoDB reads plus pure in-process
calculations.  It does not call live Business Central, Spiro, SharePoint, LLM
services, or any learning/persistence method.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional

from services.folder_routing_service import determine_ap_routing_decision
from services.vendor_name_helpers import normalize_vendor_name, vendor_identity_agrees


_REPLAY_VERSION = "ap-decision-replay-v1"
_FOLDER_SLASH_RE = re.compile(r"/+")
_KNOWN_SHAREPOINT_BASES = (
    "general/accounting/accounts payable/temp folder",
    "temp folder",
)
_BASE_FOLDER_DISPLAY = "Temp Folder"


READ_ONLY_GUARDRAILS = {
    "mongo_writes": False,
    "sharepoint_writes": False,
    "business_central_writes": False,
    "learning_writes": False,
    "external_service_calls": False,
}

REPLAY_LIMITATIONS = [
    "Uses MongoDB evidence and deterministic local routing rules only.",
    "Does not call live Business Central, Spiro, SharePoint, or an LLM.",
    "Validation is a safety summary, not a posting or BC-validation attempt.",
    "Historical records and routing snapshots are never changed.",
]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
            continue
        if value:
            return value
    return ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "international", "intl"
    }


def _normalized_folder_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip()
    return _FOLDER_SLASH_RE.sub("/", path).strip("/").casefold()


def _folder_comparison_key(value: Any) -> str:
    path = _normalized_folder_path(value)
    if not path:
        return ""
    for base in _KNOWN_SHAREPOINT_BASES:
        if path == base:
            return ""
        prefix = f"{base}/"
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _display_folder(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip().strip("/")
    key = _folder_comparison_key(path)
    if not key:
        return _BASE_FOLDER_DISPLAY
    for base in _KNOWN_SHAREPOINT_BASES:
        normalized = _normalized_folder_path(path)
        prefix = f"{base}/"
        if normalized.startswith(prefix):
            parts = path.split("/")
            tail_count = len(key.split("/"))
            return "/".join(parts[-tail_count:])
    return path


def _folders_equivalent(left: Any, right: Any) -> Optional[bool]:
    if left is None or right is None:
        return None
    left_key = _folder_comparison_key(left)
    right_key = _folder_comparison_key(right)
    if left_key or right_key:
        return bool(left_key and right_key and left_key == right_key)
    return True


def _document_evidence(document: Dict[str, Any]) -> Dict[str, Any]:
    extracted = document.get("extracted_fields") or {}
    normalized = document.get("normalized_fields") or {}
    ai_extraction = document.get("ai_extraction") or {}
    canonical = document.get("canonical_fields") or {}

    vendor = _first_nonempty(
        normalized.get("vendor_raw"),
        normalized.get("vendor"),
        document.get("vendor_raw"),
        extracted.get("vendor"),
        extracted.get("vendor_name"),
        ai_extraction.get("vendor"),
    )
    po_number = _first_nonempty(
        document.get("po_number_clean"),
        document.get("po_number_extracted"),
        normalized.get("po_number"),
        canonical.get("po_number"),
        extracted.get("po_number"),
        extracted.get("order_number"),
        ai_extraction.get("po_number"),
    )
    invoice_number = _first_nonempty(
        document.get("invoice_number_clean"),
        normalized.get("invoice_number"),
        canonical.get("invoice_number"),
        extracted.get("invoice_number"),
        ai_extraction.get("invoice_number"),
    )
    amount = _first_nonempty(
        document.get("amount_float"),
        normalized.get("amount"),
        canonical.get("amount"),
        extracted.get("total_amount"),
        extracted.get("amount"),
        ai_extraction.get("total_amount"),
    )
    sender = _first_nonempty(
        document.get("email_sender"),
        document.get("sender_email"),
        document.get("sender"),
        extracted.get("_sender_email"),
        extracted.get("sender_email"),
    )

    return {
        "vendor_extracted": vendor,
        "vendor_normalized": normalize_vendor_name(str(vendor or "")),
        "po_number": po_number,
        "invoice_number": invoice_number,
        "amount": amount,
        "sender_email": str(sender or "").strip().lower(),
        "document_type": _first_nonempty(
            document.get("document_type"),
            document.get("suggested_job_type"),
            document.get("doc_type"),
        ),
        "classification_method": document.get("classification_method"),
        "classification_confidence": _first_nonempty(
            document.get("ai_confidence"), document.get("confidence")
        ),
    }


def _candidate(
    *,
    source: str,
    vendor_name: Any = "",
    vendor_no: Any = "",
    method: str = "",
    extracted_vendor: str = "",
    priority: int = 0,
    authoritative: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    name = str(vendor_name or "").strip()
    number = str(vendor_no or "").strip()
    found = bool(name or number)
    agrees = None
    status = "not_found"
    reason = "No local evidence found"

    if found:
        comparison_name = name or number
        agrees = vendor_identity_agrees(extracted_vendor, comparison_name)
        if authoritative or agrees:
            status = "accepted"
            reason = (
                "Authoritative manual mapping"
                if authoritative
                else "Resolved identity agrees with extracted vendor"
            )
        else:
            status = "rejected"
            reason = "Resolved identity conflicts with extracted vendor"

    return {
        "source": source,
        "status": status,
        "reason": reason,
        "vendor_name": name,
        "vendor_no": number,
        "method": method or source,
        "identity_agrees": agrees,
        "priority": priority,
        "authoritative": authoritative,
        "details": details or {},
    }


def _history_display_name(doc: Dict[str, Any]) -> str:
    resolution = doc.get("vendor_resolution") or {}
    validation = doc.get("validation_results") or {}
    routing_validation = (
        (doc.get("routing_details") or {}).get("validation_results") or {}
    )
    return str(
        _first_nonempty(
            resolution.get("vendor_name"),
            resolution.get("display_name"),
            (validation.get("bc_record_info") or {}).get("displayName"),
            (routing_validation.get("bc_record_info") or {}).get("displayName"),
            doc.get("vendor_name_resolved"),
            doc.get("vendor_name"),
            doc.get("vendor_canonical"),
        )
        or ""
    ).strip()


async def _sender_candidate(db: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    sender = evidence["sender_email"]
    extracted_vendor = evidence["vendor_extracted"]
    if not sender:
        return _candidate(source="sender_mapping", extracted_vendor=extracted_vendor, priority=80)

    mapping = await db.sender_vendor_map.find_one(
        {"sender_email": sender}, {"_id": 0}
    )
    matched_kind = "sender_email"
    if not mapping:
        domain = sender.split("@", 1)[1] if "@" in sender else ""
        if domain:
            mapping = await db.sender_vendor_map.find_one(
                {"sender_domain": domain, "domain_confidence": {"$gte": 2}},
                {"_id": 0},
            )
            matched_kind = "sender_domain"

    mapping = mapping or {}
    return _candidate(
        source="sender_mapping",
        vendor_name=mapping.get("vendor_name") or mapping.get("vendor_canonical"),
        vendor_no=mapping.get("vendor_no") or mapping.get("vendor_canonical"),
        method=matched_kind,
        extracted_vendor=extracted_vendor,
        priority=80,
        details={"sender_email": sender},
    )


async def _alias_candidate(db: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    normalized = evidence["vendor_normalized"]
    extracted_vendor = evidence["vendor_extracted"]
    if not normalized:
        return _candidate(source="vendor_alias", extracted_vendor=extracted_vendor, priority=90)

    alias = await db.vendor_aliases.find_one(
        {
            "$or": [
                {"normalized": normalized},
                {"normalized_alias": normalized},
                {"alias_string": {"$regex": f"^{re.escape(normalized)}$", "$options": "i"}},
                {"alias": normalized.upper()},
            ]
        },
        {"_id": 0},
    )
    alias = alias or {}
    source_kind = str(alias.get("source") or "").strip().lower()
    authoritative = source_kind in {"manual", "manual_resolution", "operator"}
    priority = 100 if authoritative else 90
    return _candidate(
        source="vendor_alias",
        vendor_name=alias.get("vendor_name"),
        vendor_no=(
            alias.get("vendor_no")
            or alias.get("canonical_vendor_id")
            or alias.get("vendor_name")
        ),
        method=alias.get("match_method") or source_kind or "alias_match",
        extracted_vendor=extracted_vendor,
        priority=priority,
        authoritative=authoritative,
        details={"alias_source": alias.get("source")},
    )


async def _bc_cache_candidate(db: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    normalized = evidence["vendor_normalized"]
    extracted_vendor = evidence["vendor_extracted"]
    if not normalized:
        return _candidate(source="bc_cache_exact", extracted_vendor=extracted_vendor, priority=95)

    vendor = await db.hub_bc_vendors.find_one(
        {"name_normalized": normalized},
        {"_id": 0, "displayName": 1, "name": 1, "number": 1, "id": 1},
    )
    vendor = vendor or {}
    return _candidate(
        source="bc_cache_exact",
        vendor_name=vendor.get("displayName") or vendor.get("name"),
        vendor_no=vendor.get("number") or vendor.get("id"),
        method="bc_cache_exact",
        extracted_vendor=extracted_vendor,
        priority=95,
    )


async def _history_candidate(db: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    extracted_vendor = evidence["vendor_extracted"]
    if not extracted_vendor:
        return _candidate(source="document_history", extracted_vendor="", priority=75)

    exact = {"$regex": f"^{re.escape(str(extracted_vendor))}$", "$options": "i"}
    projection = {
        "_id": 0,
        "vendor_canonical": 1,
        "vendor_name": 1,
        "vendor_name_resolved": 1,
        "vendor_resolution": 1,
        "bc_vendor_number": 1,
        "bc_vendor_id": 1,
        "validation_results.bc_record_info": 1,
        "routing_details.validation_results.bc_record_info": 1,
    }
    doc = await db.hub_documents.find_one(
        {
            "$or": [
                {"extracted_fields.vendor": exact},
                {"normalized_fields.vendor": exact},
                {"vendor_raw": exact},
            ],
            "bc_vendor_number": {"$exists": True, "$nin": [None, ""]},
        },
        projection,
    )
    doc = doc or {}
    return _candidate(
        source="document_history",
        vendor_name=_history_display_name(doc),
        vendor_no=doc.get("bc_vendor_number"),
        method="document_history_extracted_agreement",
        extracted_vendor=str(extracted_vendor),
        priority=75,
    )


async def _vendor_match_cache_candidate(db: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    normalized = evidence["vendor_normalized"]
    extracted_vendor = evidence["vendor_extracted"]
    if not normalized:
        return _candidate(source="vendor_match_cache", extracted_vendor=extracted_vendor, priority=70)

    match = await db.vendor_matches.find_one(
        {"input_normalized": normalized}, {"_id": 0}
    )
    match = match or {}
    return _candidate(
        source="vendor_match_cache",
        vendor_name=match.get("matched_name"),
        vendor_no=match.get("bc_vendor_number"),
        method="vendor_matches_cache",
        extracted_vendor=extracted_vendor,
        priority=70,
        details={"score": match.get("score")},
    )


def _stored_vendor_candidate(document: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    validation = document.get("validation_results") or {}
    bc_info = validation.get("bc_record_info") or {}
    resolution = document.get("vendor_resolution") or {}
    return _candidate(
        source="stored_document_resolution",
        vendor_name=_first_nonempty(
            resolution.get("vendor_name"),
            resolution.get("display_name"),
            bc_info.get("displayName"),
            document.get("vendor_name_resolved"),
            document.get("vendor_canonical"),
        ),
        vendor_no=_first_nonempty(
            document.get("vendor_no"),
            document.get("bc_vendor_number"),
            resolution.get("vendor_no"),
            bc_info.get("number"),
            document.get("vendor_canonical"),
        ),
        method=_first_nonempty(
            document.get("vendor_match_method"),
            validation.get("match_method"),
            resolution.get("method"),
            "stored_document_resolution",
        ),
        extracted_vendor=evidence["vendor_extracted"],
        priority=60,
        details={"historical": True},
    )


def _resolution_key(candidate: Dict[str, Any]) -> str:
    return normalize_vendor_name(
        str(candidate.get("vendor_name") or candidate.get("vendor_no") or "")
    )


def _select_resolution(candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    accepted = [c for c in candidates if c.get("status") == "accepted"]
    accepted.sort(key=lambda c: int(c.get("priority") or 0), reverse=True)
    if not accepted:
        return {
            "status": "unresolved",
            "reason": "No locally available vendor evidence was safely accepted",
            "selected": None,
            "conflicts": [],
        }

    selected = accepted[0]
    conflicts: List[Dict[str, Any]] = []
    for candidate in accepted[1:]:
        left = selected.get("vendor_name") or selected.get("vendor_no")
        right = candidate.get("vendor_name") or candidate.get("vendor_no")
        if left and right and not vendor_identity_agrees(str(left), str(right)):
            conflicts.append(candidate)

    if conflicts:
        return {
            "status": "conflict",
            "reason": "Multiple accepted evidence sources identify materially different vendors",
            "selected": None,
            "conflicts": [selected, *conflicts],
        }

    return {
        "status": "resolved",
        "reason": f"Selected highest-priority accepted source: {selected['source']}",
        "selected": selected,
        "conflicts": [],
    }


async def _vendor_trace(db: Any, document: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    candidates = [
        _stored_vendor_candidate(document, evidence),
        await _sender_candidate(db, evidence),
        await _alias_candidate(db, evidence),
        await _bc_cache_candidate(db, evidence),
        await _history_candidate(db, evidence),
        await _vendor_match_cache_candidate(db, evidence),
    ]
    resolution = _select_resolution(candidates)
    return {
        "extracted_vendor": evidence["vendor_extracted"],
        "resolution": resolution,
        "candidates": candidates,
        "accepted_count": sum(c["status"] == "accepted" for c in candidates),
        "rejected_count": sum(c["status"] == "rejected" for c in candidates),
    }


def _historical_routing(document: Dict[str, Any]) -> Dict[str, Any]:
    suggestion = document.get("routing_suggestion_snapshot") or {}
    gate = document.get("routing_gate_snapshot") or {}

    if suggestion:
        original = {
            "folder_path": _display_folder(suggestion.get("folder_path")),
            "raw_folder_path": suggestion.get("folder_path", ""),
            "reason": suggestion.get("reason"),
            "source": suggestion.get("source"),
            "capture_type": suggestion.get("capture_type"),
            "captured_at": _first_nonempty(
                suggestion.get("captured_at"), suggestion.get("suggested_at")
            ),
        }
    else:
        original_folder = _first_nonempty(
            document.get("initial_suggested_folder"),
            document.get("sharepoint_folder_suggestion"),
        )
        original = {
            "folder_path": _display_folder(original_folder) if original_folder or original_folder == "" else None,
            "raw_folder_path": original_folder,
            "reason": _first_nonempty(
                document.get("initial_routing_reason"),
                document.get("sharepoint_folder_reason"),
            ),
            "source": document.get("initial_routing_source"),
            "capture_type": "legacy_initial_fields" if original_folder else None,
            "captured_at": _first_nonempty(
                document.get("initial_routing_suggested_at"),
                document.get("routing_suggested_at"),
            ),
        }

    final_raw = _first_nonempty(
        document.get("sharepoint_folder_path"),
        document.get("sharepoint_folder"),
        document.get("filed_folder"),
        document.get("filed_to"),
    )
    final = {
        "folder_path": _display_folder(final_raw) if final_raw else None,
        "raw_folder_path": final_raw,
        "filed_at": _first_nonempty(
            document.get("filed_at"), document.get("sharepoint_folder_assigned_at")
        ),
        "sharepoint_item_id": document.get("sharepoint_item_id"),
        "sharepoint_web_url": document.get("sharepoint_web_url"),
    }

    gate_trace = None
    if gate:
        gate_trace = {
            "folder_path": _display_folder(gate.get("folder_path")),
            "raw_folder_path": gate.get("folder_path", ""),
            "reason": gate.get("reason"),
            "source": gate.get("source"),
            "capture_type": gate.get("capture_type"),
            "captured_at": _first_nonempty(
                gate.get("captured_at"), document.get("routing_gate_checked_at")
            ),
            "comparable_to_original_filing": False,
        }

    return {
        "original_suggestion": original,
        "routing_gate_snapshot": gate_trace,
        "final_filing": final,
        "original_matches_final": _folders_equivalent(
            original.get("raw_folder_path"), final_raw
        ) if original.get("capture_type") and final_raw else None,
    }


def _routing_replay(
    document: Dict[str, Any],
    evidence: Dict[str, Any],
    vendor_trace: Dict[str, Any],
    historical: Dict[str, Any],
) -> Dict[str, Any]:
    routing_input = deepcopy(document)
    selected = (vendor_trace.get("resolution") or {}).get("selected") or {}

    # Do not let a stored, identity-conflicting canonical drive the replay.
    selected_name = selected.get("vendor_name") or evidence.get("vendor_extracted")
    routing_input["vendor_canonical"] = selected_name or ""
    routing_input["vendor_no"] = selected.get("vendor_no") or ""
    routing_input["vendor_match_method"] = selected.get("method") or "unresolved_local_replay"

    decision = determine_ap_routing_decision(
        routing_input,
        freight_direction=document.get("freight_direction"),
        is_international=_as_bool(document.get("is_international")),
        location_code=_first_nonempty(
            document.get("resolved_location_code"), document.get("location_code")
        ) or None,
    )
    raw_folder = decision.get("folder_path", "")
    final_raw = (historical.get("final_filing") or {}).get("raw_folder_path")
    original_raw = (historical.get("original_suggestion") or {}).get("raw_folder_path")

    return {
        **decision,
        "folder_path_display": _display_folder(raw_folder),
        "uses_vendor": selected_name,
        "uses_vendor_no": selected.get("vendor_no"),
        "vendor_resolution_status": (vendor_trace.get("resolution") or {}).get("status"),
        "matches_historical_final": _folders_equivalent(raw_folder, final_raw) if final_raw else None,
        "matches_original_suggestion": _folders_equivalent(raw_folder, original_raw)
        if (historical.get("original_suggestion") or {}).get("capture_type")
        else None,
    }


def _validation_trace(
    document: Dict[str, Any],
    evidence: Dict[str, Any],
    vendor_trace: Dict[str, Any],
) -> Dict[str, Any]:
    stored = document.get("validation_results") or {}
    resolution = vendor_trace.get("resolution") or {}
    checks = [
        {
            "check": "vendor_identity",
            "passed": resolution.get("status") == "resolved",
            "status": resolution.get("status"),
            "details": resolution.get("reason"),
        },
        {
            "check": "po_evidence",
            "passed": bool(evidence.get("po_number") or document.get("no_po_required")),
            "status": "present" if evidence.get("po_number") else "not_present",
            "details": evidence.get("po_number") or "No PO number found in local document evidence",
        },
        {
            "check": "duplicate_flag",
            "passed": not bool(document.get("possible_duplicate") or document.get("is_duplicate")),
            "status": "flagged" if document.get("possible_duplicate") or document.get("is_duplicate") else "clear",
            "details": _first_nonempty(
                document.get("duplicate_reason"),
                document.get("duplicate_of"),
                "No duplicate flag stored",
            ),
        },
    ]
    return {
        "local_safety_checks": checks,
        "all_local_safety_checks_passed": all(c["passed"] for c in checks),
        "stored_validation": {
            "all_passed": stored.get("all_passed"),
            "match_method": stored.get("match_method"),
            "match_score": stored.get("match_score"),
            "checks": stored.get("checks", []),
            "bc_record_info": stored.get("bc_record_info"),
        },
        "not_performed": [
            "live_bc_vendor_validation",
            "live_po_validation",
            "live_duplicate_search",
            "posting_eligibility",
        ],
    }


async def build_ap_decision_replay(db: Any, document: Dict[str, Any]) -> Dict[str, Any]:
    """Build a read-only local replay for one AP document."""
    evidence = _document_evidence(document)
    vendor_trace = await _vendor_trace(db, document, evidence)
    historical = _historical_routing(document)
    routing = _routing_replay(document, evidence, vendor_trace, historical)
    validation = _validation_trace(document, evidence, vendor_trace)

    return {
        "replay_version": _REPLAY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_local_replay",
        "document_id": document.get("id"),
        "file_name": document.get("file_name"),
        "document_status": {
            "status": document.get("status"),
            "workflow_status": document.get("workflow_status"),
            "automation_decision": document.get("automation_decision"),
        },
        "guardrails": dict(READ_ONLY_GUARDRAILS),
        "limitations": list(REPLAY_LIMITATIONS),
        "document_evidence": evidence,
        "vendor_trace": vendor_trace,
        "validation_trace": validation,
        "historical_routing": historical,
        "current_rule_routing": routing,
        "writes": {
            "performed": [],
            "would_perform": [],
            "statement": "Replay completed without persistence or external writes.",
        },
    }
