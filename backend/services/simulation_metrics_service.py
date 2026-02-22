"""
GPI Document Hub - Simulation Metrics Service

Aggregates simulation results across documents for dashboard visualization.
Provides metrics by doc_type, success/failure, failure_reason, and source_system.

This is a READ-ONLY diagnostic service for the shadow pilot.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# FAILURE REASON CODES
# =============================================================================

class FailureReasonCode(str, Enum):
    """Standardized failure reason codes for grouping."""
    VENDOR_NOT_FOUND = "VENDOR_NOT_FOUND"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    PO_NOT_FOUND = "PO_NOT_FOUND"
    MISSING_VENDOR = "MISSING_VENDOR"
    MISSING_CUSTOMER = "MISSING_CUSTOMER"
    MISSING_INVOICE_NUMBER = "MISSING_INVOICE_NUMBER"
    MISSING_AMOUNT = "MISSING_AMOUNT"
    MISSING_PO_NUMBER = "MISSING_PO_NUMBER"
    MISSING_FILE_URL = "MISSING_FILE_URL"
    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    OTHER = "OTHER"


def normalize_failure_reason(raw_reason: str) -> str:
    """
    Normalize a raw failure reason string to a standardized code.
    
    Args:
        raw_reason: The raw failure_reason from simulation result
        
    Returns:
        Standardized failure reason code
    """
    if not raw_reason:
        return FailureReasonCode.OTHER.value
    
    reason_lower = raw_reason.lower()
    
    # Check for specific patterns
    if "vendor" in reason_lower and "not found" in reason_lower:
        return FailureReasonCode.VENDOR_NOT_FOUND.value
    elif "customer" in reason_lower and "not found" in reason_lower:
        return FailureReasonCode.CUSTOMER_NOT_FOUND.value
    elif "po" in reason_lower and "not found" in reason_lower:
        return FailureReasonCode.PO_NOT_FOUND.value
    elif "missing vendor" in reason_lower:
        return FailureReasonCode.MISSING_VENDOR.value
    elif "missing customer" in reason_lower:
        return FailureReasonCode.MISSING_CUSTOMER.value
    elif "missing invoice" in reason_lower:
        return FailureReasonCode.MISSING_INVOICE_NUMBER.value
    elif "missing amount" in reason_lower:
        return FailureReasonCode.MISSING_AMOUNT.value
    elif "missing po" in reason_lower:
        return FailureReasonCode.MISSING_PO_NUMBER.value
    elif "file url" in reason_lower or "no file" in reason_lower:
        return FailureReasonCode.MISSING_FILE_URL.value
    elif "missing" in reason_lower:
        return FailureReasonCode.MISSING_REQUIRED_FIELDS.value
    elif "validation" in reason_lower:
        return FailureReasonCode.VALIDATION_FAILED.value
    else:
        return FailureReasonCode.OTHER.value


# =============================================================================
# METRICS CALCULATION
# =============================================================================

class SimulationMetricsService:
    """
    Service for calculating and aggregating simulation metrics.
    """
    
    def __init__(self, db):
        """
        Initialize with database reference.
        
        Args:
            db: Motor database instance
        """
        self.db = db
    
    async def get_global_metrics(
        self,
        days: int = 14,
        doc_type_filter: str = None,
        source_system_filter: str = None
    ) -> Dict[str, Any]:
        """
        Get global simulation metrics summary.
        
        Args:
            days: Number of days to look back
            doc_type_filter: Optional filter by doc_type
            source_system_filter: Optional filter by source_system
            
        Returns:
            Global metrics summary dict
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Build query
        query = {"timestamp": {"$gte": cutoff.isoformat()}}
        
        # Get all simulation results
        cursor = self.db.pilot_simulation_results.find(query, {"_id": 0})
        results = await cursor.to_list(10000)
        
        # Get document metadata for enrichment
        doc_ids = list(set(r.get("document_id") for r in results if r.get("document_id")))
        
        doc_metadata = {}
        if doc_ids:
            doc_cursor = self.db.hub_documents.find(
                {"id": {"$in": doc_ids}},
                {"_id": 0, "id": 1, "doc_type": 1, "source_system": 1, "workflow_status": 1}
            )
            async for doc in doc_cursor:
                doc_metadata[doc.get("id")] = doc
        
        # Apply filters and calculate metrics
        filtered_results = []
        for r in results:
            doc_id = r.get("document_id")
            doc_info = doc_metadata.get(doc_id, {})
            
            # Apply filters
            if doc_type_filter and doc_info.get("doc_type") != doc_type_filter:
                continue
            if source_system_filter and doc_info.get("source_system") != source_system_filter:
                continue
            
            # Enrich result with document metadata
            r["_doc_type"] = doc_info.get("doc_type", "UNKNOWN")
            r["_source_system"] = doc_info.get("source_system", "UNKNOWN")
            r["_workflow_status"] = doc_info.get("workflow_status", "unknown")
            
            filtered_results.append(r)
        
        # Calculate metrics
        return self._calculate_metrics(filtered_results, days)
    
    def _calculate_metrics(self, results: List[Dict], days: int) -> Dict[str, Any]:
        """
        Calculate metrics from a list of simulation results.
        """
        if not results:
            return {
                "total_simulated_docs": 0,
                "total_simulations": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "by_doc_type": {},
                "by_failure_reason": {},
                "by_source_system": {},
                "by_workflow_status": {},
                "by_simulation_type": {},
                "period_days": days,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        
        # Unique documents
        unique_doc_ids = set(r.get("document_id") for r in results)
        
        # Success/failure counts
        success_count = sum(1 for r in results if r.get("would_succeed_in_production"))
        failure_count = len(results) - success_count
        
        # By doc_type
        by_doc_type = defaultdict(lambda: {"success": 0, "failure": 0, "total": 0})
        for r in results:
            doc_type = r.get("_doc_type", "UNKNOWN")
            by_doc_type[doc_type]["total"] += 1
            if r.get("would_succeed_in_production"):
                by_doc_type[doc_type]["success"] += 1
            else:
                by_doc_type[doc_type]["failure"] += 1
        
        # By failure_reason (normalized)
        by_failure_reason = defaultdict(int)
        for r in results:
            if not r.get("would_succeed_in_production"):
                raw_reason = r.get("failure_reason", "")
                normalized = normalize_failure_reason(raw_reason)
                by_failure_reason[normalized] += 1
        
        # By source_system
        by_source_system = defaultdict(lambda: {"success": 0, "failure": 0, "total": 0})
        for r in results:
            source = r.get("_source_system", "UNKNOWN")
            by_source_system[source]["total"] += 1
            if r.get("would_succeed_in_production"):
                by_source_system[source]["success"] += 1
            else:
                by_source_system[source]["failure"] += 1
        
        # By workflow_status
        by_workflow_status = defaultdict(lambda: {"success": 0, "failure": 0, "total": 0})
        for r in results:
            status = r.get("_workflow_status", "unknown")
            by_workflow_status[status]["total"] += 1
            if r.get("would_succeed_in_production"):
                by_workflow_status[status]["success"] += 1
            else:
                by_workflow_status[status]["failure"] += 1
        
        # By simulation_type
        by_simulation_type = defaultdict(lambda: {"success": 0, "failure": 0, "total": 0})
        for r in results:
            sim_type = r.get("simulation_type", "unknown")
            by_simulation_type[sim_type]["total"] += 1
            if r.get("would_succeed_in_production"):
                by_simulation_type[sim_type]["success"] += 1
            else:
                by_simulation_type[sim_type]["failure"] += 1
        
        # Calculate success rate
        total = len(results)
        success_rate = round(success_count / total * 100, 1) if total > 0 else 0.0
        
        return {
            "total_simulated_docs": len(unique_doc_ids),
            "total_simulations": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
            "by_doc_type": dict(by_doc_type),
            "by_failure_reason": dict(by_failure_reason),
            "by_source_system": dict(by_source_system),
            "by_workflow_status": dict(by_workflow_status),
            "by_simulation_type": dict(by_simulation_type),
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_failure_details(
        self,
        failure_reason: str = None,
        doc_type: str = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get detailed list of failed simulations.
        
        Args:
            failure_reason: Filter by normalized failure reason
            doc_type: Filter by doc_type
            limit: Maximum results to return
            
        Returns:
            Dict with failed simulation details
        """
        query = {"would_succeed_in_production": False}
        
        cursor = self.db.pilot_simulation_results.find(query, {"_id": 0}).limit(limit * 2)
        results = await cursor.to_list(limit * 2)
        
        # Get document metadata
        doc_ids = list(set(r.get("document_id") for r in results))
        doc_metadata = {}
        if doc_ids:
            doc_cursor = self.db.hub_documents.find(
                {"id": {"$in": doc_ids}},
                {"_id": 0, "id": 1, "doc_type": 1, "source_system": 1, "workflow_status": 1,
                 "vendor_canonical": 1, "customer_number": 1, "invoice_number": 1}
            )
            async for doc in doc_cursor:
                doc_metadata[doc.get("id")] = doc
        
        # Filter and enrich
        failures = []
        for r in results:
            doc_id = r.get("document_id")
            doc_info = doc_metadata.get(doc_id, {})
            
            # Apply filters
            if doc_type and doc_info.get("doc_type") != doc_type:
                continue
            
            raw_reason = r.get("failure_reason", "")
            normalized_reason = normalize_failure_reason(raw_reason)
            
            if failure_reason and normalized_reason != failure_reason:
                continue
            
            failures.append({
                "document_id": doc_id,
                "doc_type": doc_info.get("doc_type"),
                "source_system": doc_info.get("source_system"),
                "workflow_status": doc_info.get("workflow_status"),
                "simulation_type": r.get("simulation_type"),
                "failure_reason": raw_reason,
                "failure_reason_code": normalized_reason,
                "timestamp": r.get("timestamp"),
                "vendor": doc_info.get("vendor_canonical"),
                "customer": doc_info.get("customer_number"),
                "invoice": doc_info.get("invoice_number")
            })
            
            if len(failures) >= limit:
                break
        
        return {
            "total_failures": len(failures),
            "filters": {
                "failure_reason": failure_reason,
                "doc_type": doc_type
            },
            "failures": failures
        }
    
    async def get_success_details(
        self,
        doc_type: str = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get detailed list of successful simulations.
        """
        query = {"would_succeed_in_production": True}
        
        cursor = self.db.pilot_simulation_results.find(query, {"_id": 0}).limit(limit * 2)
        results = await cursor.to_list(limit * 2)
        
        # Get document metadata
        doc_ids = list(set(r.get("document_id") for r in results))
        doc_metadata = {}
        if doc_ids:
            doc_cursor = self.db.hub_documents.find(
                {"id": {"$in": doc_ids}},
                {"_id": 0, "id": 1, "doc_type": 1, "source_system": 1, "workflow_status": 1}
            )
            async for doc in doc_cursor:
                doc_metadata[doc.get("id")] = doc
        
        # Filter and enrich
        successes = []
        for r in results:
            doc_id = r.get("document_id")
            doc_info = doc_metadata.get(doc_id, {})
            
            if doc_type and doc_info.get("doc_type") != doc_type:
                continue
            
            successes.append({
                "document_id": doc_id,
                "doc_type": doc_info.get("doc_type"),
                "source_system": doc_info.get("source_system"),
                "workflow_status": doc_info.get("workflow_status"),
                "simulation_type": r.get("simulation_type"),
                "simulated_bc_number": r.get("simulated_bc_response", {}).get("number"),
                "timestamp": r.get("timestamp")
            })
            
            if len(successes) >= limit:
                break
        
        return {
            "total_successes": len(successes),
            "filters": {"doc_type": doc_type},
            "successes": successes
        }
    
    async def get_trend_data(
        self,
        days: int = 14,
        granularity: str = "day"
    ) -> Dict[str, Any]:
        """
        Get simulation trend data over time.
        
        Args:
            days: Number of days to look back
            granularity: "day" or "hour"
            
        Returns:
            Trend data for charting
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        cursor = self.db.pilot_simulation_results.find(
            {"timestamp": {"$gte": cutoff.isoformat()}},
            {"_id": 0, "timestamp": 1, "would_succeed_in_production": 1}
        )
        results = await cursor.to_list(10000)
        
        # Group by date
        by_date = defaultdict(lambda: {"success": 0, "failure": 0, "total": 0})
        
        for r in results:
            ts = r.get("timestamp", "")
            if ts:
                # Parse and truncate to day
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if granularity == "day":
                        date_key = dt.strftime("%Y-%m-%d")
                    else:
                        date_key = dt.strftime("%Y-%m-%d %H:00")
                    
                    by_date[date_key]["total"] += 1
                    if r.get("would_succeed_in_production"):
                        by_date[date_key]["success"] += 1
                    else:
                        by_date[date_key]["failure"] += 1
                except (ValueError, TypeError):
                    pass
        
        # Convert to sorted list
        trend_data = [
            {"date": k, **v}
            for k, v in sorted(by_date.items())
        ]
        
        return {
            "period_days": days,
            "granularity": granularity,
            "data_points": len(trend_data),
            "trend": trend_data
        }
    
    async def get_documents_needing_simulation(
        self,
        doc_type: str = None,
        workflow_status: str = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get documents that haven't been simulated yet.
        """
        # Get all simulated document IDs
        simulated_ids = await self.db.pilot_simulation_results.distinct("document_id")
        
        # Query for documents not in that list
        query = {"id": {"$nin": simulated_ids}}
        if doc_type:
            query["doc_type"] = doc_type
        if workflow_status:
            query["workflow_status"] = workflow_status
        
        cursor = self.db.hub_documents.find(
            query,
            {"_id": 0, "id": 1, "doc_type": 1, "source_system": 1, "workflow_status": 1}
        ).limit(limit)
        
        docs = await cursor.to_list(limit)
        
        return {
            "total_needing_simulation": len(docs),
            "documents": docs
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_simulation_metrics_service(db) -> SimulationMetricsService:
    """Factory function to create a SimulationMetricsService instance."""
    return SimulationMetricsService(db)
