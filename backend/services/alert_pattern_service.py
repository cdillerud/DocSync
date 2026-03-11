"""
GPI Document Hub - Alert Pattern Service

Automated threshold-based alert system for label correction patterns.
Evaluates correction data periodically and flags systemic extraction problems.

Strictly read-only — does NOT modify documents, resolver scoring, or vendor intelligence.

Alert severity levels:
- info: Pattern seen repeatedly but below warning threshold
- warning: Pattern exceeds 20 occurrences in 7 days
- critical: Pattern exceeds 50 in 30 days OR vendor mislabel rate ≥ 40%

Threshold rules:
- Warning: ≥ 20 in last 7 days
- Critical: ≥ 50 in last 30 days
- Vendor Critical: vendor mislabel rate ≥ 40%
- Trend Alert: frequency increasing > 30% week-over-week
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Thresholds
WARNING_COUNT_7D = 20
CRITICAL_COUNT_30D = 50
VENDOR_CRITICAL_RATE = 0.40
TREND_INCREASE_THRESHOLD = 0.30

# Evaluation interval (seconds)
ALERT_EVAL_INTERVAL = 600  # 10 minutes

# Suggestion templates
SUGGESTION_TEMPLATES = {
    ("PO", "posted_sales_shipment"): (
        "Freight vendors frequently label shipment numbers as PO. "
        "Adjust extraction prompt to classify freight references as BOL or shipment before PO."
    ),
    ("PO", "sales_shipment"): (
        "Freight vendors frequently label shipment numbers as PO. "
        "Adjust extraction prompt to prefer shipment classification for freight carriers."
    ),
    ("INVOICE", "posted_sales_shipment"): (
        "Invoice labels are resolving to shipments. Check extraction logic "
        "for freight documents where tracking numbers are mislabeled as invoices."
    ),
    ("ORDER", "purchase_order"): (
        "Generic ORDER labels are being corrected to PO. Add PO-specific "
        "extraction patterns when document context contains purchase keywords."
    ),
    ("BOL", "purchase_order"): (
        "BOL labels are resolving to purchase orders. Review freight detection "
        "logic — these references may not be actual bills of lading."
    ),
}


def _make_pattern_key(predicted_label: str, actual_entity_type: str) -> str:
    return f"{predicted_label}→{actual_entity_type}"


def _generate_suggestion(predicted_label: str, actual_entity_type: str,
                         count: int, vendors: list) -> str:
    """Generate context-aware suggestion for an alert."""
    key = (predicted_label, actual_entity_type)
    if key in SUGGESTION_TEMPLATES:
        return SUGGESTION_TEMPLATES[key]

    vendor_text = ""
    if vendors:
        vendor_text = f" Strongest vendor: {vendors[0]}."

    if "shipment" in actual_entity_type.lower():
        return (
            f"Label '{predicted_label}' is being corrected to shipment-type "
            f"entities in {count} cases.{vendor_text} Consider adjusting "
            f"extraction prompt to prefer shipment classification for these vendors."
        )

    return (
        f"Label '{predicted_label}' is consistently resolving to "
        f"'{actual_entity_type}' ({count} occurrences).{vendor_text} "
        f"Review extraction prompt for this label type."
    )


class AlertPatternService:
    """
    Evaluates correction patterns against thresholds and manages alert state.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.alerts_collection = db.alert_patterns
        self.corrections_collection = db.reference_label_corrections
        self._eval_task = None
        self._running = False

    async def initialize(self):
        """Create indexes for efficient queries."""
        await self.alerts_collection.create_index("pattern_key", unique=True)
        await self.alerts_collection.create_index("severity_level")
        await self.alerts_collection.create_index("status")
        await self.alerts_collection.create_index("vendor_scope")
        await self.alerts_collection.create_index("last_updated")
        logger.info("[AlertPatterns] Indexes created")

    def start_background_eval(self):
        """Start the periodic alert evaluation background task."""
        if not self._running:
            self._running = True
            self._eval_task = asyncio.create_task(self._eval_loop())
            logger.info("[AlertPatterns] Background evaluation started (interval: %ds)", ALERT_EVAL_INTERVAL)

    def stop_background_eval(self):
        """Stop the background evaluation."""
        self._running = False
        if self._eval_task:
            self._eval_task.cancel()

    async def _eval_loop(self):
        """Periodic evaluation loop."""
        while self._running:
            try:
                await self.evaluate_patterns()
            except Exception as e:
                logger.error("[AlertPatterns] Evaluation error: %s", str(e))
            await asyncio.sleep(ALERT_EVAL_INTERVAL)

    # =========================================================================
    # CORE EVALUATION
    # =========================================================================

    async def evaluate_patterns(self) -> Dict[str, Any]:
        """
        Main evaluation: analyze correction patterns and update alert state.
        Returns summary of evaluation results.
        """
        now = datetime.now(timezone.utc)
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        fourteen_days_ago = (now - timedelta(days=14)).isoformat()

        # 1. Global pattern analysis (last 30 days)
        global_pipeline = [
            {"$match": {"created_at": {"$gte": thirty_days_ago}}},
            {"$group": {
                "_id": {
                    "predicted_label": "$predicted_label",
                    "actual_entity_type": "$actual_entity_type",
                    "correct_label": "$correct_label",
                },
                "count_30d": {"$sum": 1},
                "vendors": {"$addToSet": "$vendor_name"},
                "avg_score": {"$avg": "$match_score"},
                "latest": {"$max": "$created_at"},
            }},
            {"$sort": {"count_30d": -1}},
        ]
        global_patterns = await self.corrections_collection.aggregate(global_pipeline).to_list(50)

        # 2. Last-7-day counts for warning threshold
        recent_pipeline = [
            {"$match": {"created_at": {"$gte": seven_days_ago}}},
            {"$group": {
                "_id": {
                    "predicted_label": "$predicted_label",
                    "actual_entity_type": "$actual_entity_type",
                },
                "count_7d": {"$sum": 1},
            }},
        ]
        recent_counts = await self.corrections_collection.aggregate(recent_pipeline).to_list(50)
        recent_map = {
            f"{r['_id']['predicted_label']}→{r['_id']['actual_entity_type']}": r["count_7d"]
            for r in recent_counts
        }

        # 3. Trend analysis: compare last 7 days vs prior 7 days
        prior_pipeline = [
            {"$match": {"created_at": {"$gte": fourteen_days_ago, "$lt": seven_days_ago}}},
            {"$group": {
                "_id": {
                    "predicted_label": "$predicted_label",
                    "actual_entity_type": "$actual_entity_type",
                },
                "count_prior_7d": {"$sum": 1},
            }},
        ]
        prior_counts = await self.corrections_collection.aggregate(prior_pipeline).to_list(50)
        prior_map = {
            f"{r['_id']['predicted_label']}→{r['_id']['actual_entity_type']}": r["count_prior_7d"]
            for r in prior_counts
        }

        alerts_created = 0
        alerts_updated = 0
        alerts_resolved = 0

        for gp in global_patterns:
            predicted = gp["_id"]["predicted_label"]
            actual = gp["_id"]["actual_entity_type"]
            correct = gp["_id"]["correct_label"]
            pattern_key = _make_pattern_key(predicted, actual)
            count_30d = gp["count_30d"]
            count_7d = recent_map.get(pattern_key, 0)
            count_prior = prior_map.get(pattern_key, 0)
            vendors = [v for v in gp.get("vendors", []) if v]

            # Determine severity
            severity = self._compute_severity(count_7d, count_30d, count_prior)
            if severity == "none":
                continue

            # Compute trend
            trend = self._compute_trend(count_7d, count_prior)

            # Generate suggestion
            suggestion = _generate_suggestion(predicted, actual, count_30d, vendors)

            # Upsert alert
            existing = await self.alerts_collection.find_one(
                {"pattern_key": pattern_key}, {"_id": 0}
            )

            alert_doc = {
                "pattern_key": pattern_key,
                "predicted_label": predicted,
                "actual_entity_type": actual,
                "correct_label": correct,
                "vendor_scope": "global",
                "occurrence_count_7d": count_7d,
                "occurrence_count_30d": count_30d,
                "severity_level": severity,
                "affected_vendors": vendors[:10],
                "affected_vendor_count": len(vendors),
                "trend": trend,
                "trend_pct": self._trend_pct(count_7d, count_prior),
                "avg_match_score": round(gp.get("avg_score", 0), 3),
                "suggested_action": suggestion,
                "last_updated": now.isoformat(),
                "status": "active",
            }

            if existing:
                old_severity = existing.get("severity_level")
                await self.alerts_collection.update_one(
                    {"pattern_key": pattern_key},
                    {"$set": alert_doc, "$setOnInsert": {"first_detected": now.isoformat()}}
                )
                alerts_updated += 1

                # Emit notification on severity escalation
                if self._severity_rank(severity) > self._severity_rank(old_severity):
                    await self._emit_alert_event(pattern_key, severity, alert_doc)
            else:
                alert_doc["first_detected"] = now.isoformat()
                await self.alerts_collection.insert_one(alert_doc)
                alerts_created += 1

                if severity == "critical":
                    await self._emit_alert_event(pattern_key, severity, alert_doc)

        # 4. Vendor-specific critical alerts
        vendor_alerts = await self._evaluate_vendor_alerts(thirty_days_ago)
        alerts_created += vendor_alerts.get("created", 0)
        alerts_updated += vendor_alerts.get("updated", 0)

        # 5. Resolve stale alerts (patterns no longer meeting thresholds)
        active_keys = {_make_pattern_key(gp["_id"]["predicted_label"], gp["_id"]["actual_entity_type"])
                       for gp in global_patterns
                       if self._compute_severity(
                           recent_map.get(_make_pattern_key(gp["_id"]["predicted_label"], gp["_id"]["actual_entity_type"]), 0),
                           gp["count_30d"],
                           prior_map.get(_make_pattern_key(gp["_id"]["predicted_label"], gp["_id"]["actual_entity_type"]), 0)
                       ) != "none"}

        stale = await self.alerts_collection.find(
            {"status": "active", "vendor_scope": "global", "pattern_key": {"$nin": list(active_keys)}}
        ).to_list(50)
        for s in stale:
            await self.alerts_collection.update_one(
                {"pattern_key": s["pattern_key"]},
                {"$set": {"status": "resolved", "last_updated": now.isoformat()}}
            )
            alerts_resolved += 1

        summary = {
            "evaluated_at": now.isoformat(),
            "patterns_analyzed": len(global_patterns),
            "alerts_created": alerts_created,
            "alerts_updated": alerts_updated,
            "alerts_resolved": alerts_resolved,
        }
        logger.info("[AlertPatterns] Evaluation: %s", summary)
        return summary

    async def _evaluate_vendor_alerts(self, since: str) -> Dict[str, int]:
        """Evaluate vendor-specific critical alerts (mislabel rate ≥ 40%)."""
        vendor_pipeline = [
            {"$match": {"created_at": {"$gte": since}}},
            {"$group": {
                "_id": {"$ifNull": ["$vendor_name", "$vendor_no"]},
                "correction_count": {"$sum": 1},
                "top_predicted": {"$first": "$predicted_label"},
                "top_entity": {"$first": "$actual_entity_type"},
                "top_correct": {"$first": "$correct_label"},
            }},
            {"$match": {"_id": {"$ne": ""}}},
            {"$sort": {"correction_count": -1}},
            {"$limit": 20},
        ]
        vendor_data = await self.corrections_collection.aggregate(vendor_pipeline).to_list(20)

        created = 0
        updated = 0
        now = datetime.now(timezone.utc)

        for vd in vendor_data:
            vendor_id = vd["_id"]
            correction_count = vd["correction_count"]

            # Get total resolutions for this vendor
            total_resolutions = await self.db.hub_documents.count_documents({
                "$or": [
                    {"vendor_raw": vendor_id},
                    {"matched_vendor_name": vendor_id},
                    {"vendor_canonical": vendor_id},
                ],
                "reference_intelligence": {"$exists": True}
            })

            if total_resolutions < 5:
                continue

            mislabel_rate = correction_count / max(total_resolutions, 1)
            if mislabel_rate < VENDOR_CRITICAL_RATE:
                continue

            pattern_key = f"vendor:{vendor_id}"
            suggestion = (
                f"Vendor '{vendor_id}' has a {mislabel_rate:.0%} mislabel rate "
                f"({correction_count}/{total_resolutions} resolutions). "
                f"Most common: {vd['top_predicted']} → {vd['top_correct']}. "
                f"Consider adding vendor-specific extraction rules."
            )

            alert_doc = {
                "pattern_key": pattern_key,
                "predicted_label": vd["top_predicted"],
                "actual_entity_type": vd["top_entity"],
                "correct_label": vd["top_correct"],
                "vendor_scope": vendor_id,
                "occurrence_count_7d": correction_count,
                "occurrence_count_30d": correction_count,
                "severity_level": "critical",
                "affected_vendors": [vendor_id],
                "affected_vendor_count": 1,
                "trend": "stable",
                "trend_pct": 0,
                "avg_match_score": 0,
                "suggested_action": suggestion,
                "vendor_mislabel_rate": round(mislabel_rate, 3),
                "vendor_total_resolutions": total_resolutions,
                "last_updated": now.isoformat(),
                "status": "active",
            }

            existing = await self.alerts_collection.find_one({"pattern_key": pattern_key}, {"_id": 0})
            if existing:
                await self.alerts_collection.update_one(
                    {"pattern_key": pattern_key},
                    {"$set": alert_doc, "$setOnInsert": {"first_detected": now.isoformat()}}
                )
                updated += 1
            else:
                alert_doc["first_detected"] = now.isoformat()
                await self.alerts_collection.insert_one(alert_doc)
                created += 1
                await self._emit_alert_event(pattern_key, "critical", alert_doc)

        return {"created": created, "updated": updated}

    # =========================================================================
    # SEVERITY & TREND HELPERS
    # =========================================================================

    def _compute_severity(self, count_7d: int, count_30d: int, count_prior_7d: int) -> str:
        if count_30d >= CRITICAL_COUNT_30D:
            return "critical"
        if count_7d >= WARNING_COUNT_7D:
            return "warning"
        # Trend-based: if count is growing > 30% wow and at least 5 occurrences
        if count_7d >= 5 and count_prior_7d > 0:
            growth = (count_7d - count_prior_7d) / count_prior_7d
            if growth > TREND_INCREASE_THRESHOLD:
                return "warning"
        if count_30d >= 3:
            return "info"
        return "none"

    def _compute_trend(self, count_7d: int, count_prior_7d: int) -> str:
        if count_prior_7d == 0:
            return "new" if count_7d > 0 else "stable"
        pct = (count_7d - count_prior_7d) / count_prior_7d
        if pct > TREND_INCREASE_THRESHOLD:
            return "increasing"
        if pct < -0.20:
            return "decreasing"
        return "stable"

    def _trend_pct(self, count_7d: int, count_prior_7d: int) -> float:
        if count_prior_7d == 0:
            return 100.0 if count_7d > 0 else 0.0
        return round(((count_7d - count_prior_7d) / count_prior_7d) * 100, 1)

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"none": 0, "info": 1, "warning": 2, "critical": 3}.get(severity, 0)

    async def _emit_alert_event(self, pattern_key: str, severity: str, alert: Dict):
        """Emit system event for notification integration."""
        if not self.event_service:
            return
        try:
            await self.event_service.emit(
                event_type=f"alert.{severity}",
                document_id="system",
                source_service="alert_patterns",
                payload={
                    "pattern_key": pattern_key,
                    "severity": severity,
                    "suggested_action": alert.get("suggested_action", ""),
                    "occurrence_count": alert.get("occurrence_count_30d", 0),
                }
            )
        except Exception:
            pass

    # =========================================================================
    # QUERY ENDPOINTS
    # =========================================================================

    async def get_active_alerts(self, severity: str = None,
                                 vendor: str = None,
                                 predicted_label: str = None,
                                 actual_entity_type: str = None) -> List[Dict]:
        """Get active alerts with optional filtering."""
        query = {"status": {"$in": ["active"]}}
        if severity:
            query["severity_level"] = severity
        if vendor:
            query["$or"] = [
                {"vendor_scope": vendor},
                {"affected_vendors": vendor},
            ]
        if predicted_label:
            query["predicted_label"] = predicted_label
        if actual_entity_type:
            query["actual_entity_type"] = actual_entity_type

        cursor = self.alerts_collection.find(query, {"_id": 0}).sort(
            [("severity_level", -1), ("occurrence_count_30d", -1)]
        )
        alerts = await cursor.to_list(100)

        # Sort by severity rank then count
        rank = {"critical": 3, "warning": 2, "info": 1}
        alerts.sort(key=lambda a: (-rank.get(a.get("severity_level", ""), 0),
                                    -a.get("occurrence_count_30d", 0)))
        return alerts

    async def get_all_alerts(self, include_resolved: bool = False) -> List[Dict]:
        """Get all alerts, optionally including resolved/dismissed."""
        query = {} if include_resolved else {"status": "active"}
        cursor = self.alerts_collection.find(query, {"_id": 0}).sort("last_updated", -1)
        return await cursor.to_list(200)

    async def get_alert_summary(self) -> Dict[str, Any]:
        """Summary counts for dashboard header."""
        pipeline = [
            {"$match": {"status": "active"}},
            {"$group": {
                "_id": "$severity_level",
                "count": {"$sum": 1},
            }},
        ]
        results = await self.alerts_collection.aggregate(pipeline).to_list(10)
        counts = {r["_id"]: r["count"] for r in results}

        total = sum(counts.values())
        return {
            "total_active": total,
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
        }

    async def dismiss_alert(self, pattern_key: str) -> bool:
        """Dismiss an alert (mark as acknowledged)."""
        result = await self.alerts_collection.update_one(
            {"pattern_key": pattern_key},
            {"$set": {
                "status": "dismissed",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }}
        )
        return result.modified_count > 0

    async def resolve_alert(self, pattern_key: str) -> bool:
        """Mark an alert as resolved."""
        result = await self.alerts_collection.update_one(
            {"pattern_key": pattern_key},
            {"$set": {
                "status": "resolved",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }}
        )
        return result.modified_count > 0

    async def trigger_evaluation(self) -> Dict[str, Any]:
        """Manually trigger alert evaluation (for API endpoint)."""
        return await self.evaluate_patterns()


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_alert_pattern_service: Optional[AlertPatternService] = None


def get_alert_pattern_service() -> Optional[AlertPatternService]:
    return _alert_pattern_service


def set_alert_pattern_service(db, event_service=None) -> AlertPatternService:
    global _alert_pattern_service
    _alert_pattern_service = AlertPatternService(db, event_service)
    return _alert_pattern_service
