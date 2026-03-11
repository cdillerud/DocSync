"""
GPI Document Hub - Stable Vendor Auto-Ready Service

Evaluates vendor stability and document auto-ready eligibility to safely
reduce manual review effort for predictable, high-confidence vendors.

This service produces SIGNALS consumed by the existing automation flow:
  - stable_vendor_flag / stable_vendor_score
  - stable_vendor_routing (auto_ready | low_priority_review | manual_review)
  - stable_vendor_reasons[]

Safety constraints:
  - NEVER creates BC records or posts invoices
  - NEVER bypasses validation failure, duplicate detection, or unresolved classification
  - Only changes workflow readiness and review priority
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# ============================================================================
# DEFAULT CONFIGURATION (stored in MongoDB, adjustable without code changes)
# ============================================================================

DEFAULT_STABLE_VENDOR_CONFIG = {
    "config_id": "stable_vendor_defaults",

    # --- Vendor stability thresholds ---
    "min_documents_processed": 50,
    "min_automation_success_rate": 0.90,
    "min_reference_resolution_rate": 0.90,
    "max_correction_rate": 0.10,
    "min_validation_pass_rate": 0.85,

    # --- Document auto-ready thresholds ---
    "resolver_confidence_auto_ready": 0.90,
    "resolver_confidence_low_priority": 0.70,

    # --- Amount anomaly detection ---
    "amount_anomaly_enabled": True,
    "amount_anomaly_std_multiplier": 3.0,  # flag if > 3 std devs from mean

    # --- Layout family guards ---
    "block_new_layout_families": True,
    "min_layout_family_automation_rate": 0.60,

    # --- Drift / regression thresholds ---
    "drift_correction_rate_ceiling": 0.15,
    "drift_validation_fail_rate_ceiling": 0.20,

    # --- Feature toggle ---
    "enabled": True,
}


class StableVendorService:
    """
    Evaluates vendor stability and document auto-ready eligibility.
    Produces signals consumed by the automation pipeline.
    """

    def __init__(self, db, event_service=None, vendor_intel_service=None,
                 layout_fp_service=None, alert_service=None):
        self.db = db
        self.event_service = event_service
        self.vendor_intel = vendor_intel_service
        self.layout_fp = layout_fp_service
        self.alert_service = alert_service
        self._config_cache: Optional[Dict] = None

    async def initialize(self):
        """Ensure config document exists in MongoDB."""
        existing = await self.db.stable_vendor_config.find_one(
            {"config_id": "stable_vendor_defaults"}, {"_id": 0}
        )
        if not existing:
            await self.db.stable_vendor_config.insert_one(
                {**DEFAULT_STABLE_VENDOR_CONFIG}
            )
            logger.info("[StableVendor] Default configuration seeded")
        self._config_cache = None
        logger.info("[StableVendor] Service initialized")

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    async def get_config(self) -> Dict:
        if self._config_cache:
            return self._config_cache
        doc = await self.db.stable_vendor_config.find_one(
            {"config_id": "stable_vendor_defaults"}, {"_id": 0}
        )
        self._config_cache = doc or DEFAULT_STABLE_VENDOR_CONFIG
        return self._config_cache

    async def update_config(self, updates: Dict) -> Dict:
        updates.pop("config_id", None)
        updates.pop("_id", None)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.stable_vendor_config.update_one(
            {"config_id": "stable_vendor_defaults"},
            {"$set": updates},
            upsert=True,
        )
        self._config_cache = None
        return await self.get_config()

    # =========================================================================
    # VENDOR STABILITY EVALUATION
    # =========================================================================

    async def evaluate_vendor_stability(self, vendor_id: str) -> Dict[str, Any]:
        """
        Evaluate whether a vendor qualifies as stable.
        Returns stability flag, score, and detailed reasoning.
        """
        cfg = await self.get_config()
        if not cfg.get("enabled", True):
            return self._vendor_result(False, 0.0, ["Stable vendor feature disabled"])

        profile = None
        if self.vendor_intel:
            profile = await self.vendor_intel.get_profile(vendor_id)
        if not profile:
            return self._vendor_result(False, 0.0, ["No vendor intelligence profile found"])

        reasons = []
        checks = []
        score_components = []

        # Check 1: Document volume
        doc_count = profile.get("invoice_count", 0)
        min_docs = cfg["min_documents_processed"]
        vol_pass = doc_count >= min_docs
        checks.append({
            "check": "document_volume",
            "passed": vol_pass,
            "value": doc_count,
            "threshold": min_docs,
        })
        if vol_pass:
            reasons.append(f"Document volume: {doc_count} >= {min_docs}")
            score_components.append(min(doc_count / min_docs, 1.5) * 0.2)
        else:
            reasons.append(f"Insufficient volume: {doc_count} < {min_docs}")

        # Check 2: Automation success rate
        auto_rate = profile.get("automation_success_rate", 0)
        min_auto = cfg["min_automation_success_rate"]
        auto_pass = auto_rate >= min_auto
        checks.append({
            "check": "automation_success_rate",
            "passed": auto_pass,
            "value": round(auto_rate, 4),
            "threshold": min_auto,
        })
        if auto_pass:
            reasons.append(f"Automation rate: {auto_rate:.1%} >= {min_auto:.0%}")
            score_components.append(auto_rate * 0.3)
        else:
            reasons.append(f"Low automation rate: {auto_rate:.1%} < {min_auto:.0%}")

        # Check 3: Reference resolution success
        res_rate = profile.get("reference_resolution_success_rate", 0)
        min_res = cfg["min_reference_resolution_rate"]
        res_pass = res_rate >= min_res
        checks.append({
            "check": "reference_resolution_rate",
            "passed": res_pass,
            "value": round(res_rate, 4),
            "threshold": min_res,
        })
        if res_pass:
            reasons.append(f"Resolution rate: {res_rate:.1%} >= {min_res:.0%}")
            score_components.append(res_rate * 0.25)
        else:
            reasons.append(f"Low resolution rate: {res_rate:.1%} < {min_res:.0%}")

        # Check 4: Correction rate (lower is better)
        correction_rate = self._calc_correction_rate(profile)
        max_corr = cfg["max_correction_rate"]
        corr_pass = correction_rate <= max_corr
        checks.append({
            "check": "correction_rate",
            "passed": corr_pass,
            "value": round(correction_rate, 4),
            "threshold": max_corr,
        })
        if corr_pass:
            reasons.append(f"Correction rate: {correction_rate:.1%} <= {max_corr:.0%}")
            score_components.append((1 - correction_rate) * 0.15)
        else:
            reasons.append(f"High correction rate: {correction_rate:.1%} > {max_corr:.0%}")

        # Check 5: Validation pass rate
        val_rate = profile.get("validation_pass_rate", 0)
        min_val = cfg["min_validation_pass_rate"]
        val_pass = val_rate >= min_val
        checks.append({
            "check": "validation_pass_rate",
            "passed": val_pass,
            "value": round(val_rate, 4),
            "threshold": min_val,
        })
        if val_pass:
            reasons.append(f"Validation pass rate: {val_rate:.1%} >= {min_val:.0%}")
            score_components.append(val_rate * 0.1)
        else:
            reasons.append(f"Low validation pass rate: {val_rate:.1%} < {min_val:.0%}")

        is_stable = all(c["passed"] for c in checks)
        score = round(sum(score_components), 4) if score_components else 0.0

        return {
            "stable_vendor_flag": is_stable,
            "stable_vendor_score": score,
            "stable_vendor_last_evaluated": datetime.now(timezone.utc).isoformat(),
            "vendor_id": vendor_id,
            "vendor_name": profile.get("vendor_name", vendor_id),
            "vendor_no": profile.get("vendor_no", ""),
            "invoice_count": doc_count,
            "checks": checks,
            "reasons": reasons,
        }

    # =========================================================================
    # DOCUMENT AUTO-READY ELIGIBILITY
    # =========================================================================

    async def evaluate_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a document's eligibility for auto-ready or low-priority routing.
        This is the main entry point called by the automation pipeline.

        Returns a decision dict with routing outcome and full reasoning.
        """
        cfg = await self.get_config()
        doc_id = doc.get("id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        if not cfg.get("enabled", True):
            return self._doc_decision(doc_id, "manual_review",
                                      ["Stable vendor feature disabled"], now)

        reasons = []
        checks = []

        # -------------------------------------------------------------------
        # Step 1: Identify vendor and get stability
        # -------------------------------------------------------------------
        vendor_name = (
            doc.get("vendor_raw")
            or doc.get("matched_vendor_name")
            or doc.get("vendor_canonical")
            or doc.get("vendor_normalized")
        )
        if not vendor_name:
            return self._doc_decision(doc_id, "manual_review",
                                      ["No vendor identified on document"], now)

        vendor_eval = await self.evaluate_vendor_stability(vendor_name)
        is_stable = vendor_eval["stable_vendor_flag"]
        checks.append({
            "check": "vendor_stability",
            "passed": is_stable,
            "value": vendor_eval["stable_vendor_score"],
            "detail": f"Vendor '{vendor_name}' stable={is_stable}",
        })

        if not is_stable:
            reasons.append(f"Vendor not stable: {', '.join(r for r in vendor_eval['reasons'] if 'Low' in r or 'Insufficient' in r or 'High corr' in r)}")
            return self._doc_decision(
                doc_id, "manual_review", reasons or ["Vendor not stable"], now,
                vendor_eval=vendor_eval, checks=checks,
            )

        reasons.append("Vendor meets stability thresholds")

        # -------------------------------------------------------------------
        # Step 2: SAFETY — Validation state (NEVER bypass)
        # -------------------------------------------------------------------
        val_state = doc.get("validation_state") or "unknown"
        val_results = doc.get("validation_results") or {}
        val_passed = val_state == "pass" or (
            val_results.get("all_passed", False)
        )
        checks.append({
            "check": "validation_state",
            "passed": val_passed,
            "value": val_state,
        })
        if not val_passed:
            reasons.append(f"Validation failed: {val_state}")
            return self._doc_decision(
                doc_id, "manual_review", reasons, now,
                vendor_eval=vendor_eval, checks=checks,
            )
        reasons.append("Validation passed")

        # -------------------------------------------------------------------
        # Step 3: SAFETY — Duplicate detection (NEVER bypass)
        # -------------------------------------------------------------------
        is_duplicate = doc.get("possible_duplicate", False) or doc.get("duplicate_of_document_id")
        checks.append({
            "check": "duplicate_check",
            "passed": not is_duplicate,
            "value": bool(is_duplicate),
        })
        if is_duplicate:
            reasons.append("Duplicate detected")
            return self._doc_decision(
                doc_id, "manual_review", reasons, now,
                vendor_eval=vendor_eval, checks=checks,
            )
        reasons.append("No duplicate detected")

        # -------------------------------------------------------------------
        # Step 4: SAFETY — Vendor match confidence
        # -------------------------------------------------------------------
        match_method = doc.get("match_method") or doc.get("vendor_match_method") or "none"
        has_vendor_match = match_method not in ("none", "", None)
        checks.append({
            "check": "vendor_match",
            "passed": has_vendor_match,
            "value": match_method,
        })
        if not has_vendor_match:
            reasons.append(f"Vendor not matched (method={match_method})")
            return self._doc_decision(
                doc_id, "manual_review", reasons, now,
                vendor_eval=vendor_eval, checks=checks,
            )
        reasons.append(f"Vendor matched via {match_method}")

        # -------------------------------------------------------------------
        # Step 5: Resolver confidence
        # -------------------------------------------------------------------
        ref_intel = doc.get("reference_intelligence") or {}
        best_match = ref_intel.get("best_match") or {}
        resolver_score = best_match.get("match_score", 0)

        auto_ready_threshold = cfg["resolver_confidence_auto_ready"]
        low_priority_threshold = cfg["resolver_confidence_low_priority"]

        checks.append({
            "check": "resolver_confidence",
            "passed": resolver_score >= low_priority_threshold,
            "value": round(resolver_score, 4),
            "auto_ready_threshold": auto_ready_threshold,
            "low_priority_threshold": low_priority_threshold,
        })
        reasons.append(f"Resolver confidence: {resolver_score:.2f}")

        # Track downgrade signals — start optimistic, downgrade as needed
        downgrade_to_low_priority = False
        downgrade_reasons = []

        if resolver_score < low_priority_threshold:
            reasons.append(f"Resolver confidence {resolver_score:.2f} below low-priority threshold {low_priority_threshold}")
            return self._doc_decision(
                doc_id, "manual_review", reasons, now,
                vendor_eval=vendor_eval, checks=checks,
            )
        elif resolver_score < auto_ready_threshold:
            downgrade_to_low_priority = True
            downgrade_reasons.append(
                f"Resolver confidence {resolver_score:.2f} below auto-ready threshold {auto_ready_threshold}"
            )

        # -------------------------------------------------------------------
        # Step 6: SAFETY — Freight/accounting classification
        # -------------------------------------------------------------------
        doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
        freight_types = {"Freight_Document", "Freight_Invoice", "Freight Invoice", "Freight"}
        if doc_type in freight_types:
            gl_info = doc.get("freight_gl_classification") or {}
            gl_direction = gl_info.get("direction", "unknown")
            gl_number = gl_info.get("gl_number", "")
            has_gl = gl_direction != "unknown" and gl_number and "unclassified" not in gl_number.lower()
            checks.append({
                "check": "freight_gl_classification",
                "passed": has_gl,
                "value": f"{gl_direction} / {gl_number}",
            })
            if not has_gl:
                reasons.append("Freight GL classification unresolved")
                return self._doc_decision(
                    doc_id, "manual_review", reasons, now,
                    vendor_eval=vendor_eval, checks=checks,
                )
            reasons.append(f"Freight GL routing known: {gl_direction}/{gl_number}")

        # -------------------------------------------------------------------
        # Step 7: Blocking issues check
        # -------------------------------------------------------------------
        blocking = doc.get("blocking_issues") or []
        if not blocking:
            derived = doc.get("derived_state") or {}
            blocking = derived.get("blocking_issues") or []
        checks.append({
            "check": "blocking_issues",
            "passed": len(blocking) == 0,
            "value": blocking,
        })
        if blocking:
            reasons.append(f"Blocking issues: {', '.join(str(b) for b in blocking[:3])}")
            return self._doc_decision(
                doc_id, "manual_review", reasons, now,
                vendor_eval=vendor_eval, checks=checks,
            )
        reasons.append("No blocking issues")

        # -------------------------------------------------------------------
        # Step 8: Layout family guard
        # -------------------------------------------------------------------
        if self.layout_fp and cfg.get("block_new_layout_families", True):
            fp_info = await self._check_layout_family(doc, vendor_name, cfg)
            checks.append({
                "check": "layout_family",
                "passed": fp_info["safe"],
                "value": fp_info.get("detail", ""),
            })
            if not fp_info["safe"]:
                downgrade_to_low_priority = True
                downgrade_reasons.append(fp_info["reason"])
            else:
                reasons.append(fp_info.get("reason", "Layout family trusted"))

        # -------------------------------------------------------------------
        # Step 9: Active alert check
        # -------------------------------------------------------------------
        if self.alert_service:
            alert_block = await self._check_active_alerts(vendor_name, doc)
            checks.append({
                "check": "active_alerts",
                "passed": not alert_block["has_critical"],
                "value": alert_block.get("detail", ""),
            })
            if alert_block["has_critical"]:
                downgrade_to_low_priority = True
                downgrade_reasons.append(alert_block["reason"])
            else:
                reasons.append("No critical alerts for vendor")

        # -------------------------------------------------------------------
        # Step 10: Amount anomaly detection
        # -------------------------------------------------------------------
        if cfg.get("amount_anomaly_enabled", True):
            anomaly = await self._check_amount_anomaly(doc, vendor_name, cfg)
            checks.append({
                "check": "amount_anomaly",
                "passed": not anomaly["is_anomaly"],
                "value": anomaly.get("detail", ""),
            })
            if anomaly["is_anomaly"]:
                downgrade_to_low_priority = True
                downgrade_reasons.append(anomaly["reason"])
            else:
                reasons.append("Amount within expected range")

        # -------------------------------------------------------------------
        # Final decision
        # -------------------------------------------------------------------
        if downgrade_to_low_priority:
            reasons.extend(downgrade_reasons)
            routing = "low_priority_review"
        else:
            routing = "auto_ready"

        reasons.append(f"Final routing: {routing}")

        result = self._doc_decision(
            doc_id, routing, reasons, now,
            vendor_eval=vendor_eval, checks=checks,
        )

        # Emit audit event
        if self.event_service:
            await self.event_service.emit(
                event_type=f"stable_vendor.{routing}",
                document_id=doc_id,
                source_service="stable_vendor",
                payload={
                    "vendor_name": vendor_name,
                    "vendor_no": vendor_eval.get("vendor_no", ""),
                    "stable_vendor_flag": True,
                    "resolver_confidence": resolver_score,
                    "validation_state": val_state,
                    "routing_outcome": routing,
                    "decision_reasons": reasons,
                },
            )

        return result

    # =========================================================================
    # BATCH VENDOR REEVALUATION
    # =========================================================================

    async def reevaluate_all_vendors(self) -> Dict[str, Any]:
        """
        Reevaluate all vendors for stability. Handles drift/regression:
        vendors that no longer meet thresholds lose stable status.
        """
        if not self.vendor_intel:
            return {"status": "error", "message": "Vendor intelligence not available"}

        cfg = await self.get_config()
        profiles = await self.vendor_intel.get_all_profiles(limit=5000)

        results = {"evaluated": 0, "promoted": 0, "demoted": 0, "stable": 0, "not_stable": 0}

        for profile in profiles:
            vid = profile.get("vendor_no") or profile.get("vendor_name", "")
            if not vid:
                continue

            eval_result = await self.evaluate_vendor_stability(vid)
            new_stable = eval_result["stable_vendor_flag"]
            old_stable = profile.get("stable_vendor_flag", False)

            # Update the vendor profile with stability fields
            update_fields = {
                "stable_vendor_flag": new_stable,
                "stable_vendor_score": eval_result["stable_vendor_score"],
                "stable_vendor_last_evaluated": eval_result["stable_vendor_last_evaluated"],
            }

            filter_q = {"$or": [
                {"vendor_no": profile.get("vendor_no", "")},
                {"vendor_name": profile.get("vendor_name", "")}
            ]}
            await self.db.vendor_intelligence_profiles.update_one(
                filter_q, {"$set": update_fields}
            )

            results["evaluated"] += 1
            if new_stable:
                results["stable"] += 1
            else:
                results["not_stable"] += 1

            if new_stable and not old_stable:
                results["promoted"] += 1
                if self.event_service:
                    await self.event_service.emit(
                        event_type="stable_vendor.promoted",
                        document_id="system",
                        source_service="stable_vendor",
                        payload={"vendor": vid, "score": eval_result["stable_vendor_score"]},
                    )
            elif old_stable and not new_stable:
                results["demoted"] += 1
                logger.warning("[StableVendor] Vendor %s DEMOTED from stable", vid)
                if self.event_service:
                    await self.event_service.emit(
                        event_type="stable_vendor.demoted",
                        document_id="system",
                        source_service="stable_vendor",
                        payload={
                            "vendor": vid,
                            "reasons": eval_result["reasons"],
                        },
                    )

        # Invalidate vendor intel caches
        if self.vendor_intel:
            self.vendor_intel._cache.clear()

        logger.info(
            "[StableVendor] Reevaluated %d vendors: %d stable, %d promoted, %d demoted",
            results["evaluated"], results["stable"], results["promoted"], results["demoted"],
        )
        return results

    # =========================================================================
    # DASHBOARD METRICS
    # =========================================================================

    async def get_dashboard_metrics(self) -> Dict[str, Any]:
        """Get headline KPIs for the dashboard widget."""
        cfg = await self.get_config()

        # Stable vendors count
        stable_count = await self.db.vendor_intelligence_profiles.count_documents(
            {"stable_vendor_flag": True}
        )
        total_vendors = await self.db.vendor_intelligence_profiles.count_documents({})

        # Today's routing decisions
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        auto_ready_today = await self.db.hub_documents.count_documents({
            "stable_vendor_routing.routing": "auto_ready",
            "stable_vendor_routing.evaluated_at": {"$gte": today_start},
        })
        low_priority_today = await self.db.hub_documents.count_documents({
            "stable_vendor_routing.routing": "low_priority_review",
            "stable_vendor_routing.evaluated_at": {"$gte": today_start},
        })
        total_processed_today = await self.db.hub_documents.count_documents({
            "created_utc": {"$gte": today_start},
        })

        auto_rate = round(
            auto_ready_today / max(total_processed_today, 1), 4
        )

        return {
            "stable_vendors_count": stable_count,
            "total_vendors": total_vendors,
            "auto_ready_today": auto_ready_today,
            "low_priority_today": low_priority_today,
            "total_processed_today": total_processed_today,
            "stable_vendor_automation_rate": auto_rate,
            "feature_enabled": cfg.get("enabled", True),
        }

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _calc_correction_rate(self, profile: Dict) -> float:
        """Calculate correction rate from label correction patterns."""
        patterns = profile.get("label_correction_patterns", {})
        total_corrections = sum(p.get("count", 0) for p in patterns.values())
        doc_count = profile.get("invoice_count", 1)
        return round(total_corrections / max(doc_count, 1), 4)

    async def _check_layout_family(self, doc: Dict, vendor_name: str, cfg: Dict) -> Dict:
        """Check if document's layout family is trusted."""
        doc_id = doc.get("id", "")
        try:
            fp = await self.layout_fp.get_fingerprint_for_document(doc_id)
            if not fp:
                return {"safe": True, "reason": "No fingerprint (new doc)", "detail": "no_fingerprint"}

            if fp.get("new_layout_detected", False):
                return {
                    "safe": False,
                    "reason": "New layout family detected — downgrade to low-priority review",
                    "detail": "new_layout",
                }

            family_id = fp.get("layout_family_id")
            if family_id:
                family = await self.layout_fp.families_collection.find_one(
                    {"layout_family_id": family_id}, {"_id": 0}
                )
                if family:
                    pm = family.get("performance_metrics", {})
                    auto_rate = pm.get("automation_success_rate", 0)
                    min_rate = cfg.get("min_layout_family_automation_rate", 0.60)
                    if auto_rate < min_rate and pm.get("automation_total_count", 0) >= 5:
                        return {
                            "safe": False,
                            "reason": f"Layout family automation rate {auto_rate:.0%} < {min_rate:.0%}",
                            "detail": f"family={family_id} auto_rate={auto_rate:.2f}",
                        }

            return {"safe": True, "reason": "Layout family trusted", "detail": f"family={family_id}"}
        except Exception as e:
            logger.warning("[StableVendor] Layout check error: %s", e)
            return {"safe": True, "reason": "Layout check skipped (error)", "detail": str(e)}

    async def _check_active_alerts(self, vendor_name: str, doc: Dict) -> Dict:
        """Check if there are critical alerts for this vendor."""
        try:
            alerts = await self.db.threshold_alerts.find({
                "status": "active",
                "severity": "critical",
                "$or": [
                    {"vendor_name": vendor_name},
                    {"vendor_no": vendor_name},
                    {"scope": "global"},
                ],
            }).to_list(10)

            if alerts:
                alert_summaries = [a.get("alert_type", "unknown") for a in alerts]
                return {
                    "has_critical": True,
                    "reason": f"Critical alerts active: {', '.join(alert_summaries[:3])}",
                    "detail": f"{len(alerts)} critical alert(s)",
                }
            return {"has_critical": False, "reason": "No critical alerts", "detail": "clear"}
        except Exception as e:
            logger.warning("[StableVendor] Alert check error: %s", e)
            return {"has_critical": False, "reason": "Alert check skipped", "detail": str(e)}

    async def _check_amount_anomaly(self, doc: Dict, vendor_name: str, cfg: Dict) -> Dict:
        """Basic amount anomaly detection using vendor history."""
        try:
            amount = doc.get("amount_float") or 0
            if not amount:
                raw = doc.get("amount_raw") or doc.get("extracted_fields", {}).get("amount")
                if raw:
                    try:
                        amount = float(str(raw).replace(",", "").replace("$", ""))
                    except (ValueError, TypeError):
                        pass
            if not amount:
                return {"is_anomaly": False, "reason": "No amount", "detail": "no_amount"}

            # Get vendor's amount stats from recent documents
            pipeline = [
                {"$match": {
                    "$or": [
                        {"vendor_raw": vendor_name},
                        {"vendor_canonical": vendor_name},
                        {"matched_vendor_name": vendor_name},
                    ],
                    "amount_float": {"$exists": True, "$gt": 0},
                }},
                {"$group": {
                    "_id": None,
                    "avg_amount": {"$avg": "$amount_float"},
                    "std_amount": {"$stdDevPop": "$amount_float"},
                    "min_amount": {"$min": "$amount_float"},
                    "max_amount": {"$max": "$amount_float"},
                    "count": {"$sum": 1},
                }},
            ]
            agg = await self.db.hub_documents.aggregate(pipeline).to_list(1)
            if not agg or agg[0].get("count", 0) < 10:
                return {"is_anomaly": False, "reason": "Insufficient history", "detail": "low_sample"}

            stats = agg[0]
            avg = stats["avg_amount"]
            std = stats.get("std_amount", 0) or 0
            multiplier = cfg.get("amount_anomaly_std_multiplier", 3.0)

            if std > 0 and abs(amount - avg) > (std * multiplier):
                return {
                    "is_anomaly": True,
                    "reason": f"Amount ${amount:,.2f} is {abs(amount - avg)/std:.1f} std devs from vendor avg ${avg:,.2f}",
                    "detail": f"amount={amount} avg={avg:.2f} std={std:.2f}",
                }

            return {
                "is_anomaly": False,
                "reason": f"Amount ${amount:,.2f} within range (avg ${avg:,.2f})",
                "detail": f"amount={amount} avg={avg:.2f}",
            }
        except Exception as e:
            logger.warning("[StableVendor] Amount anomaly check error: %s", e)
            return {"is_anomaly": False, "reason": "Check skipped", "detail": str(e)}

    def _vendor_result(self, stable: bool, score: float, reasons: List[str]) -> Dict:
        return {
            "stable_vendor_flag": stable,
            "stable_vendor_score": score,
            "stable_vendor_last_evaluated": datetime.now(timezone.utc).isoformat(),
            "reasons": reasons,
            "checks": [],
        }

    def _doc_decision(self, doc_id: str, routing: str, reasons: List[str],
                      evaluated_at: str, vendor_eval: Dict = None,
                      checks: List = None) -> Dict:
        return {
            "document_id": doc_id,
            "routing": routing,
            "reasons": reasons,
            "evaluated_at": evaluated_at,
            "vendor_stability": vendor_eval or {},
            "checks": checks or [],
        }


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_stable_vendor_service: Optional[StableVendorService] = None


def get_stable_vendor_service() -> Optional[StableVendorService]:
    return _stable_vendor_service


def set_stable_vendor_service(db, event_service=None, vendor_intel_service=None,
                              layout_fp_service=None, alert_service=None) -> StableVendorService:
    global _stable_vendor_service
    _stable_vendor_service = StableVendorService(
        db, event_service, vendor_intel_service, layout_fp_service, alert_service
    )
    return _stable_vendor_service
