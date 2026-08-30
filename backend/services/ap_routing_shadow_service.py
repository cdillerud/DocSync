"""Non-authoritative AP routing shadow evaluation.

This service observes the *completed* SharePoint upload event.  The existing
routing path has therefore already been selected and the file has already been
uploaded before this code runs.  The AI route can be measured, logged, and
(optionally) persisted as telemetry, but it has no mechanism to alter the
SharePoint destination, document status, Business Central state, or intake
result.

Shadow mode is disabled by default.  Enable only with
``AP_AI_ROUTING_SHADOW_ENABLED=true`` after the candidate code has passed the
held-out/golden regression gates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_SHADOW_TASKS: set[asyncio.Task] = set()
_AP_TYPES = {
    "AP_INVOICE",
    "PURCHASE_INVOICE",
    "CREDIT_MEMO",
    "PURCHASE_CREDIT_MEMO",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def shadow_enabled() -> bool:
    """Return the live feature-flag state.

    This is intentionally evaluated per call instead of at module import so a
    test/runtime harness can prove the disabled path without reloading modules.
    """
    return _env_bool("AP_AI_ROUTING_SHADOW_ENABLED", False)


def shadow_persistence_enabled() -> bool:
    return _env_bool("AP_AI_ROUTING_SHADOW_PERSIST", True)


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("AP_AI_ROUTING_SHADOW_TIMEOUT_SECONDS", "90")))
    except (TypeError, ValueError):
        return 90.0


def _normalize_type(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def is_ap_shadow_candidate(document: Dict[str, Any]) -> bool:
    """Include payable/credit documents and anything arriving on the AP lane."""
    for key in ("doc_type", "document_type", "suggested_job_type"):
        if _normalize_type(document.get(key)) in _AP_TYPES:
            return True
    return str(document.get("mailbox_category") or "").strip().upper() == "AP"


def _normalize_route(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def normalize_authoritative_route(
    folder_path: Any,
    *,
    contract: Optional[Dict[str, Any]] = None,
) -> str:
    """Convert an uploaded SharePoint folder into a Temp-relative label.

    Production events may contain the full
    ``General/Accounting/Accounts Payable/Temp Folder/...`` path.  Test events
    may contain only the deterministic relative route.  Both normalize to the
    same supervised label.  The Temp root itself is represented by ``""``.
    """
    path = _normalize_route(folder_path)
    if not path:
        return ""

    base = _normalize_route((contract or {}).get("base_path"))
    if base:
        p_cf = path.casefold()
        b_cf = base.casefold()
        if p_cf == b_cf:
            return ""
        if p_cf.startswith(b_cf + "/"):
            return path[len(base) + 1 :]

    marker = "temp folder"
    parts = path.split("/")
    for index, part in enumerate(parts):
        if part.strip().casefold() == marker:
            return "/".join(parts[index + 1 :])

    return path


def predicted_temp_folder(relative_route: Any) -> str:
    """Human-readable Temp path; empty route means the Temp root, not _NeedsReview."""
    route = _normalize_route(relative_route)
    return "Temp Folder" if not route else f"Temp Folder/{route}"


def build_shadow_telemetry(
    *,
    document_id: str,
    file_name: str,
    authoritative_folder: Any,
    analysis: Dict[str, Any],
    evaluated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the immutable comparison record for one shadow decision."""
    contract = analysis.get("routing_contract") or {}
    # Current intelligence result exposes contract_version, while the loaded
    # contract itself is not serialized.  Full-path normalization still works
    # via the stable Temp Folder segment when `contract` is absent.
    authoritative_route = normalize_authoritative_route(
        authoritative_folder,
        contract=contract,
    )
    predicted_route = _normalize_route(
        analysis.get("proposed_temp_route")
        if "proposed_temp_route" in analysis
        else (analysis.get("routing") or {}).get("route_path")
    )
    routing = analysis.get("routing") or {}
    auto_route_ready = bool(
        analysis.get("auto_route_ready")
        if "auto_route_ready" in analysis
        else routing.get("decision") == "auto_route"
    )
    manual_validation_required = bool(
        analysis.get("manual_validation_required")
        if "manual_validation_required" in analysis
        else not auto_route_ready
    )
    agreement = authoritative_route.casefold() == predicted_route.casefold()
    wrong_auto_route = bool(auto_route_ready and not agreement)
    coverage_candidate = bool(auto_route_ready and agreement)

    if wrong_auto_route:
        disposition = "auto_route_disagreement"
    elif coverage_candidate:
        disposition = "auto_route_agreement"
    elif agreement:
        disposition = "review_agreement"
    else:
        disposition = "review_or_uncertain_disagreement"

    return {
        "schema_version": "1.0",
        "mode": "shadow",
        "document_id": document_id,
        "file_name": file_name,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "authoritative_folder": _normalize_route(authoritative_folder),
        "authoritative_relative_route": authoritative_route,
        "predicted_relative_route": predicted_route,
        "predicted_temp_folder": predicted_temp_folder(predicted_route),
        "agreement": agreement,
        "auto_route_ready": auto_route_ready,
        "manual_validation_required": manual_validation_required,
        "coverage_candidate": coverage_candidate,
        "wrong_auto_route": wrong_auto_route,
        "disposition": disposition,
        "classification_confidence": analysis.get("classification_confidence"),
        "routing_confidence": routing.get("confidence"),
        "routing_reason": routing.get("reason"),
        "routing_blockers": list(routing.get("blockers") or []),
        "routing_warnings": list(routing.get("warnings") or []),
        "bc_resolution_status": (analysis.get("bc_context") or {}).get("status"),
        "contract_version": analysis.get("contract_version") or routing.get("contract_version"),
        "model": (routing.get("prediction") or {}).get("model"),
        "analysis_schema_version": analysis.get("schema_version"),
    }


async def evaluate_ap_routing_shadow(
    db,
    *,
    document_id: str,
    file_path: str,
    file_name: str,
    authoritative_folder: Any,
    persist: bool = True,
    timeout_seconds: Optional[float] = None,
    analyzer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Run one bounded shadow analysis and return telemetry.

    All model failures/timeouts are converted into telemetry; nothing is raised
    into the authoritative intake/event pipeline.
    """
    started = datetime.now(timezone.utc).isoformat()
    try:
        if analyzer is None:
            from services.ap_routing_intelligence_service import analyze_ap_routing
            analyzer = analyze_ap_routing

        analysis = await asyncio.wait_for(
            analyzer(
                db,
                file_path=str(file_path),
                file_name=file_name,
                document_id=document_id,
                persist_decision=False,
            ),
            timeout=timeout_seconds or _timeout_seconds(),
        )
        telemetry = build_shadow_telemetry(
            document_id=document_id,
            file_name=file_name,
            authoritative_folder=authoritative_folder,
            analysis=analysis or {},
            evaluated_at=started,
        )
        telemetry["status"] = "completed"
        telemetry["error"] = None
    except asyncio.TimeoutError:
        telemetry = {
            "schema_version": "1.0",
            "mode": "shadow",
            "status": "timeout",
            "document_id": document_id,
            "file_name": file_name,
            "evaluated_at": started,
            "authoritative_folder": _normalize_route(authoritative_folder),
            "authoritative_relative_route": normalize_authoritative_route(authoritative_folder),
            "agreement": False,
            "auto_route_ready": False,
            "manual_validation_required": True,
            "coverage_candidate": False,
            "wrong_auto_route": False,
            "disposition": "shadow_timeout",
            "error": "shadow evaluation timed out",
        }
    except Exception as exc:
        logger.warning(
            "[APRouteShadow] analysis failed doc=%s error=%s",
            str(document_id)[:12],
            type(exc).__name__,
        )
        telemetry = {
            "schema_version": "1.0",
            "mode": "shadow",
            "status": "error",
            "document_id": document_id,
            "file_name": file_name,
            "evaluated_at": started,
            "authoritative_folder": _normalize_route(authoritative_folder),
            "authoritative_relative_route": normalize_authoritative_route(authoritative_folder),
            "agreement": False,
            "auto_route_ready": False,
            "manual_validation_required": True,
            "coverage_candidate": False,
            "wrong_auto_route": False,
            "disposition": "shadow_error",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }

    if persist and db is not None and document_id:
        try:
            await db.hub_documents.update_one(
                {"id": document_id},
                {"$set": {
                    "ap_routing_shadow": telemetry,
                    "ap_routing_shadow_last_evaluated_utc": telemetry.get("evaluated_at"),
                }},
            )
        except Exception as exc:
            logger.warning(
                "[APRouteShadow] telemetry persistence failed doc=%s error=%s",
                str(document_id)[:12],
                type(exc).__name__,
            )

    logger.info(
        "[APRouteShadow] %s",
        json.dumps(
            {
                "document_id": document_id,
                "authoritative": telemetry.get("authoritative_relative_route"),
                "predicted": telemetry.get("predicted_relative_route"),
                "agreement": telemetry.get("agreement"),
                "auto_route_ready": telemetry.get("auto_route_ready"),
                "coverage_candidate": telemetry.get("coverage_candidate"),
                "wrong_auto_route": telemetry.get("wrong_auto_route"),
                "status": telemetry.get("status"),
            },
            default=str,
        ),
    )
    return telemetry


async def _evaluate_from_sharepoint_event(
    db,
    event,
    *,
    analyzer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
) -> Optional[Dict[str, Any]]:
    document_id = str(getattr(event, "document_id", "") or "")
    payload = dict(getattr(event, "payload", {}) or {})
    if not document_id:
        return None

    document = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not document or not is_ap_shadow_candidate(document):
        return None

    from paths import UPLOAD_DIR
    file_path = Path(UPLOAD_DIR) / document_id
    if not file_path.exists():
        logger.warning("[APRouteShadow] local file missing for doc=%s", document_id[:12])
        return None

    file_name = str(document.get("file_name") or payload.get("name") or document_id)
    authoritative_folder = payload.get("folder_path") or document.get("sharepoint_folder_path") or ""
    return await evaluate_ap_routing_shadow(
        db,
        document_id=document_id,
        file_path=str(file_path),
        file_name=file_name,
        authoritative_folder=authoritative_folder,
        persist=shadow_persistence_enabled(),
        analyzer=analyzer,
    )


def _retain_task(task: asyncio.Task) -> asyncio.Task:
    _SHADOW_TASKS.add(task)

    def _done(completed: asyncio.Task) -> None:
        _SHADOW_TASKS.discard(completed)
        try:
            completed.result()
        except Exception:
            logger.exception("[APRouteShadow] background task escaped its safety boundary")

    task.add_done_callback(_done)
    return task


def register_ap_routing_shadow_subscriber(event_service, db) -> bool:
    """Subscribe after startup. Returns False when the feature flag is off."""
    if not shadow_enabled():
        logger.info("[APRouteShadow] disabled (AP_AI_ROUTING_SHADOW_ENABLED=false)")
        return False
    if event_service is None or db is None:
        logger.warning("[APRouteShadow] registration skipped: event service or db unavailable")
        return False

    async def _on_sharepoint_uploaded(event) -> None:
        # Never await the model inside EventService._notify_subscribers.  The
        # authoritative intake/event path returns immediately while a retained
        # best-effort task performs the read-only AI/BC work.
        _retain_task(asyncio.create_task(_evaluate_from_sharepoint_event(db, event)))

    event_service.register_subscriber("sharepoint.upload.succeeded", _on_sharepoint_uploaded)
    logger.info("[APRouteShadow] registered on sharepoint.upload.succeeded")
    return True
