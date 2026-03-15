"""
GPI Document Hub - Decision Policy Engine

Makes consistent, explainable automation decisions across the entire
document processing pipeline. Single source of truth for what the system
should do next: create_draft, link_existing, hold_for_review, or block.

SAFETY: No inventory mutations, no BC calls, no auto-finalization.
Separates deciding from doing.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

POLICIES_COLLECTION = "automation_policies"
DECISIONS_COLLECTION = "automation_decisions"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
BUNDLES_COLLECTION = "document_bundles"
VALIDATIONS_COLLECTION = "lifecycle_validations"
ACTIVITIES_COLLECTION = "activities"

# Decision actions
ACTION_CREATE_DRAFT = "create_draft"
ACTION_LINK_EXISTING = "link_existing"
ACTION_HOLD = "hold_for_review"
ACTION_BLOCK = "block"

# Automation levels
LEVEL_MANUAL = "manual_only"
LEVEL_CONFIRM = "human_confirm"
LEVEL_AUTO_DRAFT = "auto_draft"
LEVEL_AUTO_LINK = "auto_link"

# Decision statuses
DS_READY = "ready"
DS_REVIEW = "review_required"
DS_BLOCKED = "blocked"
DS_EXECUTED = "executed"
DS_SKIPPED = "skipped"


async def _create_activity(db, entity_id, entity_type, activity_type, title, body="", metadata=None):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body,
        "created_by": "system",
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLLECTION].insert_one(record.copy())
    record.pop("_id", None)


# ── Default Policies (seeded on first use) ───────────────────────────────────

DEFAULT_POLICIES = [
    {
        "name": "Auto-draft ready customer PO",
        "document_type": "Sales_PO",
        "bundle_type": None,
        "target_entity_type": "so_draft",
        "priority": 10,
        "conditions": {
            "automation_readiness": "ready",
            "entity_resolution_status": {"$in": ["resolved", "confirmed", None]},
            "transaction_match_status": {"$in": ["unmatched", None]},
            "lifecycle_status": {"$nin": ["duplicate_detected", "inconsistent"]},
        },
        "decision_action": ACTION_CREATE_DRAFT,
        "automation_level": LEVEL_AUTO_DRAFT,
        "reason_template": "Customer PO is automation-ready with resolved entities and no existing transaction match",
    },
    {
        "name": "Auto-link matched customer PO",
        "document_type": "Sales_PO",
        "bundle_type": None,
        "target_entity_type": "so_draft",
        "priority": 5,
        "conditions": {
            "automation_readiness": "ready",
            "transaction_match_status": {"$in": ["matched", "confirmed"]},
            "auto_link_available": True,
        },
        "decision_action": ACTION_LINK_EXISTING,
        "automation_level": LEVEL_AUTO_LINK,
        "reason_template": "Customer PO matched existing Sales Order Draft — auto-link available",
    },
    {
        "name": "Auto-draft ready AP invoice",
        "document_type": "AP_Invoice",
        "bundle_type": None,
        "target_entity_type": "ap_intake_draft",
        "priority": 10,
        "conditions": {
            "automation_readiness": "ready",
            "entity_resolution_status": {"$in": ["resolved", "confirmed", None]},
            "transaction_match_status": {"$in": ["unmatched", None]},
            "lifecycle_status": {"$nin": ["duplicate_detected"]},
        },
        "decision_action": ACTION_CREATE_DRAFT,
        "automation_level": LEVEL_AUTO_DRAFT,
        "reason_template": "AP Invoice is automation-ready with no duplicate or existing match",
    },
    {
        "name": "Auto-link matched AP invoice",
        "document_type": "AP_Invoice",
        "bundle_type": None,
        "target_entity_type": "ap_intake_draft",
        "priority": 5,
        "conditions": {
            "automation_readiness": "ready",
            "transaction_match_status": {"$in": ["matched", "confirmed"]},
            "auto_link_available": True,
        },
        "decision_action": ACTION_LINK_EXISTING,
        "automation_level": LEVEL_AUTO_LINK,
        "reason_template": "AP Invoice matched existing draft — auto-link available",
    },
    {
        "name": "Hold ambiguous entity resolution",
        "document_type": None,
        "bundle_type": None,
        "target_entity_type": None,
        "priority": 20,
        "conditions": {
            "entity_resolution_status": "ambiguous",
        },
        "decision_action": ACTION_HOLD,
        "automation_level": LEVEL_CONFIRM,
        "reason_template": "Entity resolution is ambiguous — human confirmation required",
    },
    {
        "name": "Hold ambiguous transaction match",
        "document_type": None,
        "bundle_type": None,
        "target_entity_type": None,
        "priority": 20,
        "conditions": {
            "transaction_match_status": "ambiguous",
        },
        "decision_action": ACTION_HOLD,
        "automation_level": LEVEL_CONFIRM,
        "reason_template": "Multiple transaction match candidates — human selection required",
    },
    {
        "name": "Block critical fields missing",
        "document_type": None,
        "bundle_type": None,
        "target_entity_type": None,
        "priority": 1,
        "conditions": {
            "automation_readiness": "blocked",
        },
        "decision_action": ACTION_BLOCK,
        "automation_level": LEVEL_MANUAL,
        "reason_template": "Critical fields missing or automation blocked — manual processing required",
    },
    {
        "name": "Block duplicate detected",
        "document_type": None,
        "bundle_type": None,
        "target_entity_type": None,
        "priority": 2,
        "conditions": {
            "lifecycle_status": "duplicate_detected",
        },
        "decision_action": ACTION_BLOCK,
        "automation_level": LEVEL_MANUAL,
        "reason_template": "Duplicate document detected — review and resolve before proceeding",
    },
    {
        "name": "Hold needs-review readiness",
        "document_type": None,
        "bundle_type": None,
        "target_entity_type": None,
        "priority": 15,
        "conditions": {
            "automation_readiness": "needs_review",
        },
        "decision_action": ACTION_HOLD,
        "automation_level": LEVEL_CONFIRM,
        "reason_template": "Document needs human review before automation can proceed",
    },
]


async def _seed_default_policies(db):
    """Seed default policies if none exist."""
    count = await db[POLICIES_COLLECTION].count_documents({})
    if count > 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    for p in DEFAULT_POLICIES:
        record = {
            "policy_id": f"POL-{uuid.uuid4().hex[:8].upper()}",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": "system",
            **p,
        }
        await db[POLICIES_COLLECTION].insert_one(record.copy())
    logger.info("Seeded %d default automation policies", len(DEFAULT_POLICIES))


# ── Policy CRUD ──────────────────────────────────────────────────────────────

async def create_policy(data: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "policy_id": f"POL-{uuid.uuid4().hex[:8].upper()}",
        "name": data.get("name", ""),
        "document_type": data.get("document_type"),
        "bundle_type": data.get("bundle_type"),
        "target_entity_type": data.get("target_entity_type"),
        "is_active": data.get("is_active", True),
        "priority": data.get("priority", 50),
        "conditions": data.get("conditions", {}),
        "decision_action": data.get("decision_action", ACTION_HOLD),
        "automation_level": data.get("automation_level", LEVEL_CONFIRM),
        "reason_template": data.get("reason_template", ""),
        "created_at": now,
        "updated_at": now,
        "created_by": data.get("created_by", "admin"),
    }
    await db[POLICIES_COLLECTION].insert_one(record.copy())
    record.pop("_id", None)
    return record


async def list_policies(
    document_type: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    db = get_db()
    await _seed_default_policies(db)
    query = {}
    if document_type:
        query["document_type"] = document_type
    if target_entity_type:
        query["target_entity_type"] = target_entity_type
    if is_active is not None:
        query["is_active"] = is_active
    policies = await db[POLICIES_COLLECTION].find(
        query, {"_id": 0}
    ).sort("priority", 1).to_list(200)
    return policies


async def update_policy(policy_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    existing = await db[POLICIES_COLLECTION].find_one({"policy_id": policy_id}, {"_id": 0})
    if not existing:
        raise ValueError(f"Policy not found: {policy_id}")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    updates.pop("policy_id", None)
    updates.pop("_id", None)
    await db[POLICIES_COLLECTION].update_one(
        {"policy_id": policy_id}, {"$set": updates}
    )
    return await db[POLICIES_COLLECTION].find_one({"policy_id": policy_id}, {"_id": 0})


async def delete_policy(policy_id: str) -> Dict[str, Any]:
    db = get_db()
    existing = await db[POLICIES_COLLECTION].find_one({"policy_id": policy_id}, {"_id": 0})
    if not existing:
        raise ValueError(f"Policy not found: {policy_id}")
    await db[POLICIES_COLLECTION].update_one(
        {"policy_id": policy_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"deleted": True, "policy_id": policy_id}


# ── Policy Evaluation ────────────────────────────────────────────────────────

def _check_condition(field_val, condition_val) -> bool:
    """Check a single condition against a field value."""
    if isinstance(condition_val, dict):
        for op, operand in condition_val.items():
            if op == "$in":
                if field_val not in operand:
                    return False
            elif op == "$nin":
                if field_val in operand:
                    return False
            elif op == "$eq":
                if field_val != operand:
                    return False
            elif op == "$ne":
                if field_val == operand:
                    return False
            elif op == "$gte":
                if not (field_val is not None and field_val >= operand):
                    return False
            elif op == "$lte":
                if not (field_val is not None and field_val <= operand):
                    return False
        return True
    else:
        return field_val == condition_val


def _evaluate_policy_conditions(policy: Dict, snapshot: Dict) -> bool:
    """Check if all conditions in a policy match the input snapshot."""
    conditions = policy.get("conditions", {})
    if not conditions:
        return True

    for field, expected in conditions.items():
        actual = snapshot.get(field)
        if not _check_condition(actual, expected):
            return False
    return True


def _build_input_snapshot(intel: Dict, bundle: Optional[Dict] = None, lifecycle: Optional[Dict] = None) -> Dict:
    """Build a flat snapshot of all decision-relevant fields."""
    snapshot = {
        "document_type": intel.get("document_type", ""),
        "classification_confidence": intel.get("classification_confidence", 0),
        "automation_readiness": intel.get("automation_readiness", ""),
        "automation_readiness_score": intel.get("automation_readiness_score", 0),
        "entity_resolution_status": intel.get("entity_resolution_status"),
        "transaction_match_status": intel.get("transaction_match_status"),
        "auto_link_available": intel.get("auto_link_available", False),
        "auto_draft_suppressed": intel.get("auto_draft_suppressed_due_to_match", False),
        "auto_draft_created": intel.get("auto_draft_created", False),
        "auto_link_created": intel.get("auto_link_created", False),
        "lifecycle_status": intel.get("lifecycle_status"),
        "lifecycle_stage": intel.get("lifecycle_stage"),
        "bundle_id": intel.get("bundle_id"),
        "bundle_type": intel.get("bundle_type"),
        "bundle_status": intel.get("bundle_status"),
        "bundle_completeness_status": intel.get("bundle_completeness_status"),
        "has_blocking_items": bool(intel.get("entity_resolution_blocking_items")),
        "target_entity_type": intel.get("target_entity_type", ""),
    }

    # Check field completeness
    fields = intel.get("extracted_fields", {})
    schema = intel.get("extraction_schema", {})
    required = schema.get("required", [])
    missing_required = [f for f in required if not fields.get(f)]
    snapshot["missing_required_fields"] = missing_required
    snapshot["required_fields_complete"] = len(missing_required) == 0

    if bundle:
        snapshot["bundle_completeness_status"] = bundle.get("completeness_status", snapshot.get("bundle_completeness_status"))
        snapshot["bundle_status"] = bundle.get("bundle_status", snapshot.get("bundle_status"))

    if lifecycle:
        snapshot["lifecycle_status"] = lifecycle.get("validation_status", snapshot.get("lifecycle_status"))
        snapshot["lifecycle_stage"] = lifecycle.get("detected_stage", snapshot.get("lifecycle_stage"))
        snapshot["has_duplicates"] = len(lifecycle.get("duplicate_documents", [])) > 0
        snapshot["has_inconsistencies"] = len(lifecycle.get("inconsistent_references", [])) > 0

    return snapshot


def _generate_reasons(policy: Dict, snapshot: Dict) -> List[Dict[str, str]]:
    """Generate human-readable and machine-readable reasons for a decision."""
    reasons = []

    # Primary reason from policy template
    template = policy.get("reason_template", "")
    if template:
        reasons.append({"code": "policy_match", "message": template})

    # Add context reasons
    action = policy.get("decision_action", "")

    if action == ACTION_CREATE_DRAFT:
        if snapshot.get("automation_readiness") == "ready":
            reasons.append({"code": "readiness_ok", "message": f"Automation readiness: ready (score: {snapshot.get('automation_readiness_score', 0)})"})
        if snapshot.get("required_fields_complete"):
            reasons.append({"code": "fields_complete", "message": "All required fields extracted"})
        if snapshot.get("transaction_match_status") in ("unmatched", None):
            reasons.append({"code": "no_existing_match", "message": "No existing transaction match found"})

    elif action == ACTION_LINK_EXISTING:
        if snapshot.get("auto_link_available"):
            reasons.append({"code": "link_available", "message": "High-confidence transaction match available for linking"})
        if snapshot.get("transaction_match_status") in ("matched", "confirmed"):
            reasons.append({"code": "match_found", "message": f"Transaction match status: {snapshot.get('transaction_match_status')}"})

    elif action == ACTION_HOLD:
        if snapshot.get("entity_resolution_status") == "ambiguous":
            reasons.append({"code": "entity_ambiguous", "message": "Entity resolution returned ambiguous results"})
        if snapshot.get("transaction_match_status") == "ambiguous":
            reasons.append({"code": "match_ambiguous", "message": "Multiple transaction match candidates found"})
        if snapshot.get("automation_readiness") == "needs_review":
            reasons.append({"code": "needs_review", "message": "Document flagged for human review"})

    elif action == ACTION_BLOCK:
        if snapshot.get("automation_readiness") == "blocked":
            reasons.append({"code": "readiness_blocked", "message": "Automation blocked — critical fields missing or validation failed"})
        if snapshot.get("lifecycle_status") == "duplicate_detected":
            reasons.append({"code": "duplicate", "message": "Duplicate document detected in lifecycle validation"})
        missing = snapshot.get("missing_required_fields", [])
        if missing:
            reasons.append({"code": "missing_fields", "message": f"Missing required fields: {', '.join(missing)}"})
        if snapshot.get("has_blocking_items"):
            reasons.append({"code": "blocking_items", "message": "Unresolved blocking entity items"})

    return reasons


async def evaluate_decision(doc_id: str, evaluated_by: str = "system") -> Dict[str, Any]:
    """
    The authoritative decision endpoint. Evaluates all active policies
    in priority order and determines the best action for a document.
    """
    db = get_db()
    await _seed_default_policies(db)
    now = datetime.now(timezone.utc).isoformat()

    # Load intelligence result
    intel = await db[INTELLIGENCE_COLLECTION].find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    if not intel:
        raise ValueError(f"No intelligence result for document: {doc_id}")

    # Load bundle if present
    bundle = None
    bundle_id = intel.get("bundle_id", "")
    if bundle_id:
        bundle = await db[BUNDLES_COLLECTION].find_one(
            {"bundle_id": bundle_id}, {"_id": 0}
        )

    # Load lifecycle if present
    lifecycle = None
    target_type = intel.get("target_entity_type", "")
    target_id = intel.get("target_entity_id", "")
    if target_type and target_id:
        lifecycle = await db[VALIDATIONS_COLLECTION].find_one(
            {"entity_type": target_type, "entity_id": target_id}, {"_id": 0}
        )

    # Build input snapshot
    snapshot = _build_input_snapshot(intel, bundle, lifecycle)

    # Load active policies, sorted by priority (lower = higher priority)
    policies = await db[POLICIES_COLLECTION].find(
        {"is_active": True}, {"_id": 0}
    ).sort("priority", 1).to_list(200)

    # Evaluate policies
    matched_policy = None
    for policy in policies:
        # Filter by document_type if specified
        p_doc_type = policy.get("document_type")
        if p_doc_type and p_doc_type != snapshot.get("document_type"):
            continue

        # Filter by bundle_type if specified
        p_bundle_type = policy.get("bundle_type")
        if p_bundle_type and p_bundle_type != snapshot.get("bundle_type"):
            continue

        if _evaluate_policy_conditions(policy, snapshot):
            matched_policy = policy
            break

    # Fallback: if no policy matched, hold for review
    if not matched_policy:
        matched_policy = {
            "policy_id": "FALLBACK",
            "name": "Default fallback",
            "decision_action": ACTION_HOLD,
            "automation_level": LEVEL_CONFIRM,
            "reason_template": "No matching policy found — holding for human review",
            "target_entity_type": target_type,
        }

    action = matched_policy["decision_action"]
    level = matched_policy["automation_level"]
    reasons = _generate_reasons(matched_policy, snapshot)

    # Determine decision status
    if action == ACTION_BLOCK:
        decision_status = DS_BLOCKED
    elif action == ACTION_HOLD:
        decision_status = DS_REVIEW
    elif intel.get("auto_draft_created") or intel.get("auto_link_created"):
        decision_status = DS_EXECUTED
    else:
        decision_status = DS_READY

    # Determine target
    target_entity_type = matched_policy.get("target_entity_type") or intel.get("target_entity_type", "")
    target_entity_id = intel.get("target_entity_id", "")
    if action == ACTION_LINK_EXISTING and intel.get("best_transaction_match"):
        target_entity_id = intel["best_transaction_match"].get("entity_id", "")
        target_entity_type = intel["best_transaction_match"].get("entity_type", target_entity_type)

    # Target summary for UI
    target_summary = ""
    if action == ACTION_CREATE_DRAFT:
        target_summary = f"Create {target_entity_type} from extracted fields"
    elif action == ACTION_LINK_EXISTING:
        target_summary = f"Link to existing {target_entity_type}: {target_entity_id}" if target_entity_id else f"Link to existing {target_entity_type}"
    elif action == ACTION_HOLD:
        target_summary = "Requires human review before proceeding"
    elif action == ACTION_BLOCK:
        target_summary = "Automation blocked — resolve issues first"

    decision_id = f"DEC-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "decision_id": decision_id,
        "document_id": doc_id,
        "bundle_id": bundle_id,
        "policy_id": matched_policy.get("policy_id", "FALLBACK"),
        "policy_name": matched_policy.get("name", ""),
        "decision_action": action,
        "automation_level": level,
        "decision_status": decision_status,
        "decision_reasons": reasons,
        "input_snapshot": snapshot,
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "target_summary": target_summary,
        "evaluated_at": now,
        "evaluated_by": evaluated_by,
        "notes": "",
    }

    # Upsert — one decision per document
    await db[DECISIONS_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": record},
        upsert=True,
    )

    # Enrich document intelligence with decision data
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": {
            "latest_decision_action": action,
            "latest_automation_level": level,
            "latest_decision_status": decision_status,
            "latest_decision_reasons": [r["message"] for r in reasons],
            "decision_executable": decision_status == DS_READY,
            "decision_target_summary": target_summary,
        }},
    )

    # Activity
    activity_type = "decision_evaluated"
    if decision_status == DS_BLOCKED:
        activity_type = "decision_blocked"
    elif decision_status == DS_REVIEW:
        activity_type = "decision_held"

    await _create_activity(
        db, doc_id, "document", activity_type,
        f"Decision: {action} ({level}) — {decision_status}",
        reasons[0]["message"] if reasons else "",
        metadata={"decision_id": decision_id, "action": action, "status": decision_status},
    )

    # Clean _id if present
    record.pop("_id", None)
    return record


async def execute_decision(decision_id: str, executed_by: str = "admin") -> Dict[str, Any]:
    """
    Execute a decision — calls existing auto-draft or auto-link logic.
    Only executes 'ready' decisions. Hold/block decisions are not executable.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    decision = await db[DECISIONS_COLLECTION].find_one(
        {"decision_id": decision_id}, {"_id": 0}
    )
    if not decision:
        raise ValueError(f"Decision not found: {decision_id}")

    action = decision["decision_action"]
    status = decision["decision_status"]
    doc_id = decision["document_id"]

    if status == DS_BLOCKED:
        return {
            "executed": False,
            "decision_id": decision_id,
            "reason": "Decision is blocked — resolve issues before executing",
            "decision_action": action,
            "decision_status": status,
        }

    if status == DS_REVIEW:
        return {
            "executed": False,
            "decision_id": decision_id,
            "reason": "Decision requires human review — confirm or override before executing",
            "decision_action": action,
            "decision_status": status,
        }

    if status == DS_EXECUTED:
        return {
            "executed": False,
            "decision_id": decision_id,
            "reason": "Decision already executed",
            "decision_action": action,
            "decision_status": status,
        }

    if status == DS_SKIPPED:
        return {
            "executed": False,
            "decision_id": decision_id,
            "reason": "Decision was skipped",
            "decision_action": action,
            "decision_status": status,
        }

    # Execute based on action
    result = None
    try:
        if action == ACTION_CREATE_DRAFT:
            from services.document_intelligence_service import create_auto_draft
            result = await create_auto_draft(doc_id)

        elif action == ACTION_LINK_EXISTING:
            from services.transaction_matching_service import auto_link
            result = await auto_link(doc_id)

        else:
            return {
                "executed": False,
                "decision_id": decision_id,
                "reason": f"Action '{action}' is not auto-executable",
                "decision_action": action,
                "decision_status": status,
            }

        # Update decision status
        await db[DECISIONS_COLLECTION].update_one(
            {"decision_id": decision_id},
            {"$set": {
                "decision_status": DS_EXECUTED,
                "executed_at": now,
                "executed_by": executed_by,
                "execution_result": str(result)[:500] if result else "",
            }},
        )

        # Update intelligence enrichment
        await db[INTELLIGENCE_COLLECTION].update_one(
            {"document_id": doc_id},
            {"$set": {
                "latest_decision_status": DS_EXECUTED,
                "decision_executable": False,
            }},
        )

        await _create_activity(
            db, doc_id, "document", "decision_executed",
            f"Decision executed: {action} by {executed_by}",
            metadata={"decision_id": decision_id, "action": action},
        )

        return {
            "executed": True,
            "decision_id": decision_id,
            "decision_action": action,
            "decision_status": DS_EXECUTED,
            "result": result,
        }

    except Exception as e:
        logger.error("Decision execution failed for %s: %s", decision_id, e)
        await db[DECISIONS_COLLECTION].update_one(
            {"decision_id": decision_id},
            {"$set": {"execution_error": str(e), "decision_status": DS_READY}},
        )
        raise


async def get_decision(doc_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest decision for a document."""
    db = get_db()
    return await db[DECISIONS_COLLECTION].find_one(
        {"document_id": doc_id}, {"_id": 0}
    )


async def get_decision_queue(
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get documents with review_required or blocked decisions."""
    db = get_db()
    query = {"decision_status": {"$in": [DS_REVIEW, DS_BLOCKED]}}
    total = await db[DECISIONS_COLLECTION].count_documents(query)
    decisions = await db[DECISIONS_COLLECTION].find(
        query, {"_id": 0}
    ).sort("evaluated_at", -1).skip(offset).limit(limit).to_list(limit)

    # Enrich with doc metadata
    for dec in decisions:
        doc = await db.hub_documents.find_one(
            {"id": dec["document_id"]},
            {"_id": 0, "file_name": 1, "status": 1},
        )
        dec["file_name"] = doc.get("file_name", "") if doc else ""
        dec["doc_status"] = doc.get("status", "") if doc else ""
        dec["reason_summary"] = dec["decision_reasons"][0]["message"] if dec.get("decision_reasons") else ""

    # Status counts
    all_decs = await db[DECISIONS_COLLECTION].find(
        {}, {"_id": 0, "decision_status": 1}
    ).to_list(1000)
    status_counts = {}
    for d in all_decs:
        s = d.get("decision_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total": total,
        "decisions": decisions,
        "status_counts": status_counts,
    }
