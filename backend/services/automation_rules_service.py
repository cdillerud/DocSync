"""
GPI Document Hub - Automation Rules Engine

Configurable rules that determine workflow routing based on:
- Vendor identity & intelligence profile
- Document type & classification
- Reference resolver results
- Validation state

Rules only control workflow routing — never BC writes.
First-match-wins evaluation in priority order.
In-memory cache for <5ms evaluation.

Events: automation.rule.triggered, .skipped, .failed
"""

import logging
import uuid
from typing import Optional, Dict, Any, List

from services.automation_helpers import utcnow

logger = logging.getLogger(__name__)


# =============================================================================
# RULE ACTION TYPES
# =============================================================================

VALID_ACTIONS = {
    "route_to_queue",
    "assign_review_priority",
    "flag_for_manual_review",
    "auto_mark_ready",
    "auto_route_to_accounting_queue",
}

VALID_CONDITION_FIELDS = {
    # Vendor conditions
    "vendor_no", "vendor_name", "stable_vendor_flag",
    # Document conditions
    "document_type", "classification_confidence_gte",
    # Validation conditions
    "validation_state", "duplicate_check",
    # Resolver conditions
    "resolver_match_type", "resolver_match_score_gte", "reference_domain",
    # Vendor intelligence conditions
    "automation_success_rate_gte", "po_reference_frequency_gte",
    "shipment_reference_frequency_gte", "bol_presence_rate_gte",
}


def _matches_condition(condition_key: str, condition_value, doc_ctx: Dict) -> bool:
    """Check if a single condition matches against the document context."""
    actual = doc_ctx.get(condition_key)

    # Handle _gte (greater than or equal) suffixed conditions
    if condition_key.endswith("_gte"):
        base_key = condition_key[:-4]
        actual = doc_ctx.get(base_key)
        if actual is None:
            return False
        try:
            return float(actual) >= float(condition_value)
        except (ValueError, TypeError):
            return False

    # Boolean conditions
    if isinstance(condition_value, bool):
        return bool(actual) == condition_value

    # String match (case-insensitive)
    if isinstance(condition_value, str) and isinstance(actual, str):
        return actual.lower() == condition_value.lower()

    # Direct equality
    return actual == condition_value


def build_document_context(doc: Dict, vendor_profile: Dict = None) -> Dict:
    """
    Build a flat context dict from a document and vendor profile
    for rule evaluation.
    """
    ref_intel = doc.get("reference_intelligence") or {}
    best_match = ref_intel.get("best_match") or {}
    validation = doc.get("validation_results") or {}

    ctx = {
        # Vendor
        "vendor_no": (doc.get("unified_vendor_match") or {}).get("bc_vendor_no", ""),
        "vendor_name": doc.get("vendor_raw") or doc.get("matched_vendor_name") or doc.get("vendor_canonical") or "",
        # Document
        "document_type": doc.get("document_type") or doc.get("suggested_job_type") or "",
        "classification_confidence": doc.get("ai_confidence") or 0,
        # Validation
        "validation_state": validation.get("validation_state") or doc.get("validation_state") or "",
        "duplicate_check": "pass" if not validation.get("is_duplicate") else "fail",
        # Resolver
        "resolver_match_type": best_match.get("entity_type") or doc.get("reference_intelligence_outcome") or "",
        "resolver_match_score": best_match.get("match_score") or doc.get("reference_intelligence_best_score") or 0,
        "reference_domain": ref_intel.get("document_type") or "",
    }

    # Vendor intelligence conditions
    if vendor_profile:
        ctx["stable_vendor_flag"] = vendor_profile.get("stable_vendor_flag", False)
        ctx["automation_success_rate"] = vendor_profile.get("automation_success_rate", 0)
        ctx["po_reference_frequency"] = vendor_profile.get("po_reference_frequency", 0)
        ctx["shipment_reference_frequency"] = vendor_profile.get("shipment_reference_frequency", 0)
        ctx["bol_presence_rate"] = vendor_profile.get("bol_presence_rate", 0)

    return ctx


class AutomationRulesService:
    """
    Evaluates and executes automation rules for document workflow routing.
    Rules are cached in memory for fast evaluation (<5ms).
    """

    def __init__(self, db, event_service=None, vendor_intel_service=None):
        self.db = db
        self.event_service = event_service
        self.vendor_intel = vendor_intel_service
        self.collection = db.automation_rules
        self._rules_cache: List[Dict] = []
        self._cache_loaded = False

    async def initialize(self):
        """Create indexes and load rules into memory."""
        await self.collection.create_index("priority")
        await self.collection.create_index("enabled")
        await self._reload_cache()
        logger.info("[RulesEngine] Initialized with %d rules", len(self._rules_cache))

    async def _reload_cache(self):
        """Load all enabled rules into memory, sorted by priority."""
        cursor = self.collection.find(
            {"enabled": True}, {"_id": 0}
        ).sort("priority", 1)
        self._rules_cache = await cursor.to_list(length=500)
        self._cache_loaded = True

    # =========================================================================
    # CRUD
    # =========================================================================

    async def create_rule(self, rule_data: Dict) -> Dict:
        """Create a new automation rule."""
        rule = {
            "rule_id": str(uuid.uuid4())[:8],
            "rule_name": rule_data.get("rule_name", "Untitled Rule"),
            "enabled": rule_data.get("enabled", True),
            "vendor_no": rule_data.get("vendor_no"),
            "vendor_name": rule_data.get("vendor_name"),
            "document_type": rule_data.get("document_type"),
            "conditions": rule_data.get("conditions", {}),
            "actions": rule_data.get("actions", {}),
            "priority": rule_data.get("priority", 100),
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        await self.collection.insert_one(rule)
        rule.pop("_id", None)
        await self._reload_cache()

        if self.event_service:
            await self.event_service.emit(
                event_type="automation.rule.created",
                document_id="system",
                source_service="automation_rules",
                payload={"rule_id": rule["rule_id"], "rule_name": rule["rule_name"]}
            )
        return rule

    async def update_rule(self, rule_id: str, updates: Dict) -> Optional[Dict]:
        """Update an existing rule."""
        updates["updated_at"] = utcnow()
        updates.pop("rule_id", None)
        updates.pop("_id", None)

        result = await self.collection.find_one_and_update(
            {"rule_id": rule_id},
            {"$set": updates},
            return_document=True
        )
        if result:
            result.pop("_id", None)
            await self._reload_cache()
        return result

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule."""
        result = await self.collection.delete_one({"rule_id": rule_id})
        if result.deleted_count > 0:
            await self._reload_cache()
            return True
        return False

    async def toggle_rule(self, rule_id: str) -> Optional[Dict]:
        """Toggle a rule's enabled state."""
        rule = await self.collection.find_one({"rule_id": rule_id})
        if not rule:
            return None
        new_state = not rule.get("enabled", True)
        return await self.update_rule(rule_id, {"enabled": new_state})

    async def get_rule(self, rule_id: str) -> Optional[Dict]:
        return await self.collection.find_one({"rule_id": rule_id}, {"_id": 0})

    async def list_rules(self) -> List[Dict]:
        cursor = self.collection.find({}, {"_id": 0}).sort("priority", 1)
        return await cursor.to_list(length=500)

    # =========================================================================
    # EVALUATION
    # =========================================================================

    async def evaluate(self, doc: Dict, vendor_profile: Dict = None) -> Optional[Dict]:
        """
        Evaluate rules against a document. Returns the first matching rule
        and executes its actions. Returns None if no rule matches.
        """
        if not self._cache_loaded:
            await self._reload_cache()

        if not self._rules_cache:
            return None

        # Build context
        if not vendor_profile and self.vendor_intel:
            vendor_name = (
                doc.get("vendor_raw")
                or doc.get("matched_vendor_name")
                or doc.get("vendor_canonical") or ""
            )
            if vendor_name:
                vendor_profile = await self.vendor_intel.get_profile(vendor_name)

        ctx = build_document_context(doc, vendor_profile)
        doc_id = doc.get("id", "unknown")

        # Evaluate rules in priority order
        for rule in self._rules_cache:
            if not rule.get("enabled"):
                continue

            matched = self._check_rule_conditions(rule, ctx)

            if matched:
                logger.info(
                    "[RulesEngine] Rule '%s' matched for doc %s",
                    rule.get("rule_name"), doc_id[:8]
                )
                # Execute actions
                actions_result = await self._execute_actions(doc_id, rule)

                if self.event_service:
                    await self.event_service.emit(
                        event_type="automation.rule.triggered",
                        document_id=doc_id,
                        source_service="automation_rules",
                        payload={
                            "rule_id": rule["rule_id"],
                            "rule_name": rule["rule_name"],
                            "matched_conditions": rule.get("conditions", {}),
                            "actions": rule.get("actions", {}),
                            "vendor_no": ctx.get("vendor_no"),
                        }
                    )

                return {
                    "matched": True,
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["rule_name"],
                    "actions_executed": actions_result,
                }

        # No rule matched
        if self.event_service:
            await self.event_service.emit(
                event_type="automation.rule.skipped",
                document_id=doc_id,
                source_service="automation_rules",
                payload={"reason": "no_matching_rule", "rules_evaluated": len(self._rules_cache)}
            )

        return None

    def _check_rule_conditions(self, rule: Dict, ctx: Dict) -> bool:
        """Check if all conditions in a rule match the document context."""
        conditions = rule.get("conditions", {})
        if not conditions:
            return False

        for key, value in conditions.items():
            if not _matches_condition(key, value, ctx):
                return False

        return True

    async def _execute_actions(self, doc_id: str, rule: Dict) -> Dict:
        """Execute the actions defined in a matched rule."""
        actions = rule.get("actions", {})
        updates = {}
        result = {}

        if "route_to_queue" in actions:
            updates["workflow_queue"] = actions["route_to_queue"]
            result["route_to_queue"] = actions["route_to_queue"]

        if "assign_review_priority" in actions:
            updates["review_priority"] = actions["assign_review_priority"]
            result["assign_review_priority"] = actions["assign_review_priority"]

        if actions.get("flag_for_manual_review"):
            updates["flagged_for_review"] = True
            updates["review_flag_reason"] = f"Rule: {rule.get('rule_name', '')}"
            result["flagged_for_review"] = True

        if actions.get("auto_mark_ready"):
            updates["workflow_status"] = "ready_for_posting"
            updates["auto_marked_ready"] = True
            updates["auto_marked_ready_by_rule"] = rule.get("rule_id")
            result["auto_mark_ready"] = True

        if "auto_route_to_accounting_queue" in actions:
            updates["workflow_queue"] = "accounting_review"
            updates["review_priority"] = actions.get("auto_route_to_accounting_queue", "normal")
            result["auto_route_to_accounting_queue"] = True

        if updates:
            updates["automation_rule_applied"] = rule.get("rule_id")
            updates["automation_rule_name"] = rule.get("rule_name")
            updates["automation_rule_applied_at"] = utcnow()
            updates["updated_utc"] = utcnow()
            await self.db.hub_documents.update_one({"id": doc_id}, {"$set": updates})

        return result

    # =========================================================================
    # SUGGESTIONS
    # =========================================================================

    async def generate_suggestions(self) -> List[Dict]:
        """
        Generate rule suggestions from vendor intelligence profiles.
        Suggests rules for vendors with high automation potential.
        """
        if not self.vendor_intel:
            return []

        profiles = await self.vendor_intel.get_all_profiles(limit=50, sort_by="invoice_count")
        suggestions = []

        for p in profiles:
            if p.get("invoice_count", 0) < 5:
                continue

            vendor_name = p.get("vendor_name", "")
            vendor_no = p.get("vendor_no", "")
            ship_freq = p.get("shipment_reference_frequency", 0)
            po_freq = p.get("po_reference_frequency", 0)
            auto_rate = p.get("automation_success_rate", 0)
            resolution_rate = p.get("reference_resolution_success_rate", 0)
            stable = p.get("stable_vendor_flag", False)
            typical_types = p.get("typical_bc_match_types", [])

            # High-confidence freight/shipping vendor
            if ship_freq > 0.7 and resolution_rate > 0.5:
                suggestions.append({
                    "vendor_name": vendor_name,
                    "vendor_no": vendor_no,
                    "suggestion_type": "freight_automation",
                    "confidence": round(min(ship_freq * resolution_rate * 1.2, 0.95), 2),
                    "description": f"Freight invoices from {vendor_name} consistently reference shipments ({ship_freq:.0%}). Auto-route to accounting review.",
                    "suggested_rule": {
                        "rule_name": f"{vendor_name} - Freight Auto-Route",
                        "conditions": {
                            "vendor_name": vendor_name,
                            "resolver_match_type": typical_types[0] if typical_types else "posted_sales_shipment",
                            "validation_state": "pass",
                        },
                        "actions": {
                            "route_to_queue": "accounting_review",
                            "assign_review_priority": "low",
                        },
                        "priority": 50,
                    },
                    "metrics": {
                        "invoice_count": p["invoice_count"],
                        "shipment_ref_freq": ship_freq,
                        "resolution_rate": resolution_rate,
                        "automation_rate": auto_rate,
                    }
                })

            # High-confidence PO vendor
            elif po_freq > 0.7 and resolution_rate > 0.5:
                suggestions.append({
                    "vendor_name": vendor_name,
                    "vendor_no": vendor_no,
                    "suggestion_type": "po_automation",
                    "confidence": round(min(po_freq * resolution_rate * 1.2, 0.95), 2),
                    "description": f"AP invoices from {vendor_name} consistently reference POs ({po_freq:.0%}). Auto-route to accounting review.",
                    "suggested_rule": {
                        "rule_name": f"{vendor_name} - PO Auto-Route",
                        "conditions": {
                            "vendor_name": vendor_name,
                            "resolver_match_type": "purchase_order",
                            "validation_state": "pass",
                        },
                        "actions": {
                            "route_to_queue": "accounting_review",
                            "assign_review_priority": "low",
                        },
                        "priority": 50,
                    },
                    "metrics": {
                        "invoice_count": p["invoice_count"],
                        "po_ref_freq": po_freq,
                        "resolution_rate": resolution_rate,
                        "automation_rate": auto_rate,
                    }
                })

            # Stable vendor — eligible for auto-ready
            if stable:
                suggestions.append({
                    "vendor_name": vendor_name,
                    "vendor_no": vendor_no,
                    "suggestion_type": "stable_vendor_auto_ready",
                    "confidence": round(auto_rate, 2),
                    "description": f"{vendor_name} is a STABLE vendor ({auto_rate:.0%} automation). Consider auto-marking as ready.",
                    "suggested_rule": {
                        "rule_name": f"{vendor_name} - Stable Auto-Ready",
                        "conditions": {
                            "vendor_name": vendor_name,
                            "stable_vendor_flag": True,
                            "validation_state": "pass",
                            "resolver_match_score_gte": 0.8,
                        },
                        "actions": {
                            "auto_mark_ready": True,
                        },
                        "priority": 30,
                    },
                    "metrics": {
                        "invoice_count": p["invoice_count"],
                        "automation_rate": auto_rate,
                        "stable": True,
                    }
                })

        suggestions.sort(key=lambda s: s["confidence"], reverse=True)
        return suggestions


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_rules_service: Optional[AutomationRulesService] = None


def get_automation_rules_service() -> Optional[AutomationRulesService]:
    return _rules_service


def set_automation_rules_service(db, event_service=None, vendor_intel_service=None) -> AutomationRulesService:
    global _rules_service
    _rules_service = AutomationRulesService(db, event_service, vendor_intel_service)
    return _rules_service
