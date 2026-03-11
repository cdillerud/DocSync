"""GPI Document Hub - Metrics Router

Extracted from server.py monolith.
All analytics/audit/metrics endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from deps import get_db, ENABLE_CREATE_DRAFT_HEADER, DEMO_MODE
from models.document_types import DEFAULT_JOB_TYPES, TransactionAction

router = APIRouter(tags=["Metrics"])

async def _get_automation_metrics_internal(days: int = 30, job_type: str = None):
    """
    Internal helper function to get automation metrics without FastAPI Query parameters.
    Used by other endpoints to aggregate metrics.
    """
    db = get_db()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Build query filter
    query = {"created_utc": {"$gte": cutoff_date}}
    if job_type:
        query["suggested_job_type"] = job_type
    
    # Total documents
    total = await db.hub_documents.count_documents(query)
    
    # Status distribution
    status_counts = {}
    for status in ["Received", "StoredInSP", "Classified", "NeedsReview", "LinkedToBC", "Exception"]:
        status_query = {**query, "status": status}
        status_counts[status] = await db.hub_documents.count_documents(status_query)
    
    # Percentages
    status_percentages = {
        status: round((count / total * 100) if total > 0 else 0, 1)
        for status, count in status_counts.items()
    }
    
    # Job type breakdown
    job_type_breakdown = {}
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({**query, "suggested_job_type": jt})
        if count > 0:
            job_type_breakdown[jt] = count
    
    # Confidence distribution
    confidence_ranges = {
        "high_0.9_1.0": 0,
        "medium_0.7_0.9": 0,
        "low_0_0.7": 0
    }
    
    docs_with_confidence = await db.hub_documents.find(
        {**query, "ai_confidence": {"$exists": True}},
        {"ai_confidence": 1, "_id": 0}
    ).to_list(10000)
    
    for doc in docs_with_confidence:
        conf = doc.get("ai_confidence") or 0
        if conf >= 0.9:
            confidence_ranges["high_0.9_1.0"] += 1
        elif conf >= 0.7:
            confidence_ranges["medium_0.7_0.9"] += 1
        else:
            confidence_ranges["low_0_0.7"] += 1
    
    # Average confidence
    total_confidence = sum((doc.get("ai_confidence") or 0) for doc in docs_with_confidence)
    avg_confidence = round(total_confidence / len(docs_with_confidence), 3) if docs_with_confidence else 0
    
    # Duplicate prevention count
    duplicate_prevented = await db.hub_documents.count_documents({
        **query,
        "validation_results.checks": {
            "$elemMatch": {"check_name": "duplicate_check", "passed": False}
        }
    })
    
    # Match method breakdown
    match_method_breakdown = {
        "exact_no": 0, "exact_name": 0, "normalized": 0,
        "alias": 0, "fuzzy": 0, "manual": 0, "none": 0
    }
    
    docs_with_match = await db.hub_documents.find(
        query, {"match_method": 1, "status": 1, "_id": 0}
    ).to_list(10000)
    
    alias_auto_linked = 0
    alias_needs_review = 0
    
    for doc in docs_with_match:
        method = doc.get("match_method", "none")
        if method in match_method_breakdown:
            match_method_breakdown[method] += 1
        else:
            match_method_breakdown["none"] += 1
        
        if method == "alias":
            if doc.get("status") == "LinkedToBC":
                alias_auto_linked += 1
            elif doc.get("status") == "NeedsReview":
                alias_needs_review += 1
    
    total_alias = alias_auto_linked + alias_needs_review
    alias_exception_rate = round((alias_needs_review / total_alias * 100) if total_alias > 0 else 0, 1)
    
    # Draft creation metrics
    draft_created_count = await db.hub_documents.count_documents({
        **query, "transaction_action": TransactionAction.DRAFT_CREATED
    })
    
    linked_only_count = await db.hub_documents.count_documents({
        **query, "transaction_action": TransactionAction.LINKED_ONLY
    })
    
    linked_total = status_counts.get("LinkedToBC", 0)
    draft_creation_rate = round((draft_created_count / linked_total * 100) if linked_total > 0 else 0, 1)
    
    return {
        "period_days": days,
        "total_documents": total,
        "status_distribution": {
            "counts": status_counts,
            "percentages": status_percentages
        },
        "job_type_breakdown": job_type_breakdown,
        "confidence_distribution": confidence_ranges,
        "average_confidence": avg_confidence,
        "duplicate_prevented": duplicate_prevented,
        "automation_rate": status_percentages.get("LinkedToBC", 0),
        "review_rate": status_percentages.get("NeedsReview", 0),
        "match_method_breakdown": match_method_breakdown,
        "alias_auto_linked": alias_auto_linked,
        "alias_exception_rate": alias_exception_rate,
        "draft_created_count": draft_created_count,
        "linked_only_count": linked_only_count,
        "draft_creation_rate": draft_creation_rate,
        "draft_feature_enabled": ENABLE_CREATE_DRAFT_HEADER,
        "header_only_flag": True
    }


@router.get("/metrics/automation")
async def get_automation_metrics(
    days: int = Query(30, description="Number of days to include"),
    job_type: Optional[str] = Query(None, description="Filter by job type")
):
    """
    Get comprehensive automation metrics for the audit dashboard.
    """
    return await _get_automation_metrics_internal(days=days, job_type=job_type)

@router.get("/metrics/vendors")
async def get_vendor_friction_metrics(days: int = Query(30)):
    db = get_db()
    """
    Get vendor friction index - shows where alias mapping will have biggest ROI.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get all documents with vendor info
    docs = await db.hub_documents.find(
        {
            "created_utc": {"$gte": cutoff_date},
            "extracted_fields.vendor": {"$exists": True}
        },
        {"extracted_fields.vendor": 1, "status": 1, "ai_confidence": 1, "match_method": 1, "_id": 0}
    ).to_list(5000)
    
    # Get existing aliases
    aliases = await db.vendor_aliases.find({}, {"alias_string": 1, "vendor_name": 1}).to_list(500)
    alias_strings = set(a.get("alias_string", "").lower() for a in aliases)
    
    # Aggregate by vendor
    vendor_stats = {}
    for doc in docs:
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {
                "total": 0,
                "linked": 0,
                "needs_review": 0,
                "exception": 0,
                "total_confidence": 0,
                "alias_matches": 0,
                "has_alias": vendor.lower() in alias_strings
            }
        
        vendor_stats[vendor]["total"] += 1
        vendor_stats[vendor]["total_confidence"] += doc.get("ai_confidence", 0)
        
        # Track alias-based matches
        if doc.get("match_method") == "alias":
            vendor_stats[vendor]["alias_matches"] += 1
        
        status = doc.get("status", "")
        if status == "LinkedToBC":
            vendor_stats[vendor]["linked"] += 1
        elif status == "NeedsReview":
            vendor_stats[vendor]["needs_review"] += 1
        elif status == "Exception":
            vendor_stats[vendor]["exception"] += 1
    
    # Calculate friction index and ROI hints
    vendor_friction = []
    for vendor, stats in vendor_stats.items():
        total = stats["total"]
        if total > 0:
            exception_rate = stats["needs_review"] / total
            avg_confidence = stats["total_confidence"] / total
            auto_rate = stats["linked"] / total
            
            # Friction index: higher = more manual intervention needed
            friction_index = round(exception_rate * 100, 1)
            
            # ROI hint: estimate potential improvement if alias is created
            # If no alias exists and high friction, alias could help
            potential_auto_rate = None
            roi_hint = None
            
            if not stats["has_alias"] and friction_index > 50 and avg_confidence >= 0.85:
                # Documents with high confidence but failing vendor match
                # Would likely auto-link if alias existed
                potential_docs = stats["needs_review"]
                potential_auto_rate = round((stats["linked"] + potential_docs) / total * 100, 1)
                roi_hint = f"Creating alias could reduce review rate from {friction_index}% to ~{100 - potential_auto_rate}%"
            elif stats["has_alias"]:
                roi_hint = "Alias exists - monitoring impact"
            
            vendor_friction.append({
                "vendor": vendor,
                "total_documents": total,
                "auto_linked": stats["linked"],
                "needs_review": stats["needs_review"],
                "alias_matches": stats["alias_matches"],
                "auto_rate": round(auto_rate * 100, 1),
                "avg_confidence": round(avg_confidence, 3),
                "friction_index": friction_index,
                "has_alias": stats["has_alias"],
                "potential_auto_rate": potential_auto_rate,
                "roi_hint": roi_hint
            })
    
    # Sort by friction index (highest first = most opportunity)
    vendor_friction.sort(key=lambda x: x["friction_index"], reverse=True)
    
    return {
        "period_days": days,
        "vendor_count": len(vendor_friction),
        "vendors": vendor_friction[:20],  # Top 20 friction vendors
        "total_analyzed": len(docs)
    }

@router.get("/metrics/alias-impact")
async def get_alias_impact_metrics():
    """
    Track alias learning impact over time.
    Shows compounding intelligence.
    """
    db = get_db()
    # Get all aliases with usage stats
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    
    total_aliases = len(aliases)
    total_usage = sum(a.get("usage_count", 0) for a in aliases)
    
    # Get match method distribution from recent documents
    docs = await db.hub_documents.find(
        {"validation_results.checks": {"$exists": True}},
        {"validation_results.checks": 1, "_id": 0}
    ).sort("created_utc", -1).limit(1000).to_list(1000)
    
    match_methods = {
        "exact_no": 0,
        "exact_name": 0,
        "normalized": 0,
        "alias": 0,
        "fuzzy": 0,
        "no_match": 0
    }
    
    for doc in docs:
        checks = doc.get("validation_results", {}).get("checks", [])
        for check in checks:
            if check.get("check_name") in ("vendor_match", "customer_match"):
                method = check.get("match_method", "no_match")
                if method in match_methods:
                    match_methods[method] += 1
                elif not check.get("passed"):
                    match_methods["no_match"] += 1
    
    total_matches = sum(match_methods.values())
    
    return {
        "total_aliases": total_aliases,
        "total_alias_usage": total_usage,
        "top_aliases": sorted(aliases, key=lambda x: x.get("usage_count", 0), reverse=True)[:10],
        "match_method_distribution": match_methods,
        "match_method_percentages": {
            k: round(v / total_matches * 100, 1) if total_matches > 0 else 0
            for k, v in match_methods.items()
        },
        "alias_contribution": round(match_methods.get("alias", 0) / total_matches * 100, 1) if total_matches > 0 else 0
    }

@router.get("/metrics/resolution-time")
async def get_resolution_time_metrics(days: int = Query(30)):
    db = get_db()
    """
    Track time from Received to LinkedToBC.
    Shows efficiency improvements.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get documents that reached LinkedToBC status
    linked_docs = await db.hub_documents.find(
        {
            "created_utc": {"$gte": cutoff_date},
            "status": "LinkedToBC"
        },
        {"created_utc": 1, "updated_utc": 1, "resolved_utc": 1, "suggested_job_type": 1, "_id": 0}
    ).to_list(5000)
    
    resolution_times = []
    by_job_type = {}
    
    for doc in linked_docs:
        try:
            created = datetime.fromisoformat(doc["created_utc"].replace("Z", "+00:00"))
            # Use resolved_utc if available, otherwise updated_utc
            resolved = doc.get("resolved_utc") or doc.get("updated_utc")
            if resolved:
                resolved = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                minutes = (resolved - created).total_seconds() / 60
                resolution_times.append(minutes)
                
                jt = doc.get("suggested_job_type", "Unknown")
                if jt not in by_job_type:
                    by_job_type[jt] = []
                by_job_type[jt].append(minutes)
        except Exception:
            continue
    
    # Calculate statistics
    if resolution_times:
        resolution_times.sort()
        median_time = resolution_times[len(resolution_times) // 2]
        p95_time = resolution_times[int(len(resolution_times) * 0.95)] if len(resolution_times) > 20 else max(resolution_times)
        avg_time = sum(resolution_times) / len(resolution_times)
    else:
        median_time = 0
        p95_time = 0
        avg_time = 0
    
    # Per job type stats
    job_type_stats = {}
    for jt, times in by_job_type.items():
        if times:
            times.sort()
            job_type_stats[jt] = {
                "count": len(times),
                "median_minutes": round(times[len(times) // 2], 2),
                "avg_minutes": round(sum(times) / len(times), 2)
            }
    
    return {
        "period_days": days,
        "total_resolved": len(resolution_times),
        "median_minutes": round(median_time, 2),
        "p95_minutes": round(p95_time, 2),
        "avg_minutes": round(avg_time, 2),
        "by_job_type": job_type_stats
    }

@router.get("/metrics/daily")
async def get_daily_metrics(days: int = Query(14)):
    db = get_db()
    """
    Get daily aggregated metrics for trend charts.
    """
    daily_metrics = []
    
    for i in range(days):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        start = date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        
        query = {"created_utc": {"$gte": start, "$lte": end}}
        
        total = await db.hub_documents.count_documents(query)
        linked = await db.hub_documents.count_documents({**query, "status": "LinkedToBC"})
        review = await db.hub_documents.count_documents({**query, "status": "NeedsReview"})
        
        daily_metrics.append({
            "date": date_str,
            "total": total,
            "auto_linked": linked,
            "needs_review": review,
            "auto_rate": round(linked / total * 100, 1) if total > 0 else 0
        })
    
    # Reverse to chronological order
    daily_metrics.reverse()
    
    return {"daily_metrics": daily_metrics}

# ==================== ENHANCED DASHBOARD ====================

@router.get("/dashboard/email-stats")
async def get_email_stats():
    db = get_db()
    """Get email processing statistics."""
    total_email = await db.hub_documents.count_documents({"source": "email"})
    needs_review = await db.hub_documents.count_documents({"source": "email", "status": "NeedsReview"})
    auto_linked = await db.hub_documents.count_documents({"source": "email", "status": "LinkedToBC"})
    stored_sp = await db.hub_documents.count_documents({"source": "email", "status": "StoredInSP"})
    
    # Get by job type
    by_job_type = {}
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({"source": "email", "suggested_job_type": jt})
        if count > 0:
            by_job_type[jt] = count
    
    # Recent email documents
    recent = await db.hub_documents.find(
        {"source": "email"},
        {"_id": 0}
    ).sort("created_utc", -1).limit(10).to_list(10)
    
    return {
        "total_email_documents": total_email,
        "needs_review": needs_review,
        "auto_linked": auto_linked,
        "stored_sp": stored_sp,
        "by_job_type": by_job_type,
        "recent": recent
    }

# ==================== PHASE 6: SHADOW MODE INSTRUMENTATION ====================

@router.get("/metrics/match-score-distribution")
async def get_match_score_distribution(
    from_date: str = None,
    to_date: str = None
):
    """
    Get match score distribution histogram for Phase 6 Shadow Mode analysis.
    
    This is the cornerstone metric that tells you whether 0.92 threshold is conservative or tight.
    
    Buckets:
    - 0.95-1.00: Very high confidence (ideal candidates for draft creation)
    - 0.92-0.95: High confidence (meets draft threshold)
    - 0.88-0.92: Near threshold (watch zone)
    - <0.88: Low confidence (not eligible)
    
    Args:
        from_date: Start date (YYYY-MM-DD), defaults to 14 days ago
        to_date: End date (YYYY-MM-DD), defaults to today
    """
    db = get_db()
    # Default to last 14 days
    if not to_date:
        to_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime('%Y-%m-%d')
    
    query = {
        "created_utc": {
            "$gte": from_date,
            "$lte": to_date + "T23:59:59"
        },
        "match_score": {"$exists": True, "$ne": None}
    }
    
    # Get all documents with match scores in range
    docs = await db.hub_documents.find(
        query,
        {"match_score": 1, "match_method": 1, "status": 1, "_id": 0}
    ).to_list(10000)
    
    # Initialize buckets
    buckets = {
        "0.95_1.00": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "0.92_0.95": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "0.88_0.92": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "lt_0.88": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0}
    }
    
    total_docs = len(docs)
    
    for doc in docs:
        score = doc.get("match_score", 0) or 0
        method = doc.get("match_method", "none")
        status = doc.get("status", "Unknown")
        
        # Determine bucket
        if score >= 0.95:
            bucket_key = "0.95_1.00"
        elif score >= 0.92:
            bucket_key = "0.92_0.95"
        elif score >= 0.88:
            bucket_key = "0.88_0.92"
        else:
            bucket_key = "lt_0.88"
        
        buckets[bucket_key]["count"] += 1
        
        # Track method breakdown within bucket
        if method not in buckets[bucket_key]["by_method"]:
            buckets[bucket_key]["by_method"][method] = 0
        buckets[bucket_key]["by_method"][method] += 1
        
        # Track outcome within bucket
        if status == "LinkedToBC":
            buckets[bucket_key]["linked"] += 1
        elif status == "NeedsReview":
            buckets[bucket_key]["needs_review"] += 1
    
    # Calculate high-confidence eligible (>= 0.92)
    high_confidence_count = buckets["0.95_1.00"]["count"] + buckets["0.92_0.95"]["count"]
    high_confidence_pct = round((high_confidence_count / total_docs * 100) if total_docs > 0 else 0, 1)
    
    # Calculate threshold eligibility
    threshold_eligible = high_confidence_count
    near_threshold = buckets["0.88_0.92"]["count"]
    below_threshold = buckets["lt_0.88"]["count"]
    
    # Generate interpretation
    if high_confidence_pct >= 80:
        interpretation = f"Excellent: {high_confidence_pct}% of documents are above 0.92 threshold. Your threshold is conservative and safe for production."
    elif high_confidence_pct >= 60:
        interpretation = f"Good: {high_confidence_pct}% of documents are above 0.92 threshold. Consider monitoring the {near_threshold} documents in the 0.88-0.92 watch zone."
    elif high_confidence_pct >= 40:
        interpretation = f"Moderate: {high_confidence_pct}% of documents are above 0.92 threshold. Investigate the {below_threshold + near_threshold} documents below threshold before enabling draft creation."
    else:
        interpretation = f"Caution: Only {high_confidence_pct}% of documents are above 0.92 threshold. Review vendor data hygiene and alias coverage before enabling draft creation."
    
    return {
        "period": {
            "from_date": from_date,
            "to_date": to_date
        },
        "total_documents": total_docs,
        "buckets": buckets,
        "summary": {
            "high_confidence_eligible": high_confidence_count,
            "high_confidence_pct": high_confidence_pct,
            "near_threshold": near_threshold,
            "below_threshold": below_threshold,
            "interpretation": interpretation
        },
        "threshold_analysis": {
            "current_threshold": 0.92,
            "above_threshold_count": threshold_eligible,
            "above_threshold_pct": high_confidence_pct,
            "near_threshold_count": near_threshold,
            "near_threshold_pct": round((near_threshold / total_docs * 100) if total_docs > 0 else 0, 1)
        }
    }


@router.get("/metrics/alias-exceptions")
async def get_alias_exception_metrics(days: int = 14):
    """
    Enhanced alias exception tracking for Phase 6.
    
    This is the second key signal that tells you:
    - Data hygiene ROI is real
    - Alias engine is compounding over time
    
    Returns:
    - Total alias matches vs exceptions
    - Alias exception rate trend
    - Top 10 vendors by alias exceptions
    - Top 10 vendors by alias contribution
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    # Get all documents with match data
    docs = await db.hub_documents.find(
        query,
        {"match_method": 1, "status": 1, "extracted_fields.vendor": 1, "_id": 0}
    ).to_list(10000)
    
    # Calculate overall alias metrics
    alias_matches_total = 0
    alias_matches_success = 0  # LinkedToBC
    alias_matches_needs_review = 0  # NeedsReview (exceptions)
    
    # Vendor-level tracking
    vendor_alias_stats = {}
    
    for doc in docs:
        method = doc.get("match_method", "none")
        status = doc.get("status", "Unknown")
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        
        # Initialize vendor if not seen
        if vendor not in vendor_alias_stats:
            vendor_alias_stats[vendor] = {
                "total_docs": 0,
                "alias_matches": 0,
                "alias_success": 0,
                "alias_exceptions": 0,
                "non_alias_linked": 0
            }
        
        vendor_alias_stats[vendor]["total_docs"] += 1
        
        if method == "alias":
            alias_matches_total += 1
            vendor_alias_stats[vendor]["alias_matches"] += 1
            
            if status == "LinkedToBC":
                alias_matches_success += 1
                vendor_alias_stats[vendor]["alias_success"] += 1
            elif status == "NeedsReview":
                alias_matches_needs_review += 1
                vendor_alias_stats[vendor]["alias_exceptions"] += 1
        elif status == "LinkedToBC":
            vendor_alias_stats[vendor]["non_alias_linked"] += 1
    
    # Calculate alias exception rate
    alias_exception_rate = round(
        (alias_matches_needs_review / alias_matches_total * 100) if alias_matches_total > 0 else 0, 1
    )
    
    # Top 10 vendors by alias exceptions
    top_exception_vendors = sorted(
        [{"vendor": v, **stats} for v, stats in vendor_alias_stats.items() if stats["alias_exceptions"] > 0],
        key=lambda x: x["alias_exceptions"],
        reverse=True
    )[:10]
    
    # Top 10 vendors by alias contribution (alias drives 60%+ of their automation)
    # Calculate alias contribution % per vendor
    for vendor, stats in vendor_alias_stats.items():
        total_linked = stats["alias_success"] + stats["non_alias_linked"]
        stats["alias_contribution_pct"] = round(
            (stats["alias_success"] / total_linked * 100) if total_linked > 0 else 0, 1
        )
    
    high_alias_contribution_vendors = sorted(
        [{"vendor": v, **stats} for v, stats in vendor_alias_stats.items() 
         if stats["alias_contribution_pct"] >= 60 and stats["alias_matches"] >= 2],
        key=lambda x: x["alias_contribution_pct"],
        reverse=True
    )[:10]
    
    # Daily trend (last 7 days)
    daily_alias_trend = []
    for i in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime('%Y-%m-%d')
        day_query = {
            "created_utc": {"$gte": day, "$lt": day + "T23:59:59"},
            "match_method": "alias"
        }
        day_total = await db.hub_documents.count_documents(day_query)
        day_success = await db.hub_documents.count_documents({**day_query, "status": "LinkedToBC"})
        day_exception = await db.hub_documents.count_documents({**day_query, "status": "NeedsReview"})
        
        daily_alias_trend.append({
            "date": day,
            "total": day_total,
            "success": day_success,
            "exceptions": day_exception,
            "exception_rate": round((day_exception / day_total * 100) if day_total > 0 else 0, 1)
        })
    
    # Reverse to show oldest first
    daily_alias_trend.reverse()
    
    return {
        "period_days": days,
        "alias_totals": {
            "alias_matches_total": alias_matches_total,
            "alias_matches_success": alias_matches_success,
            "alias_matches_needs_review": alias_matches_needs_review,
            "alias_exception_rate": alias_exception_rate
        },
        "interpretation": {
            "status": "healthy" if alias_exception_rate < 10 else ("watch" if alias_exception_rate < 25 else "attention"),
            "message": f"Alias exception rate is {alias_exception_rate}%. " + (
                "Alias engine is performing well." if alias_exception_rate < 10 else
                "Monitor vendor data for inconsistencies." if alias_exception_rate < 25 else
                "High alias exceptions suggest alias data hygiene issues."
            )
        },
        "top_exception_vendors": top_exception_vendors,
        "high_alias_contribution_vendors": high_alias_contribution_vendors,
        "daily_trend": daily_alias_trend
    }


@router.get("/metrics/vendor-stability")
async def get_vendor_stability_analysis(days: int = 14):
    """
    Vendor friction stability analysis for Phase 6.
    
    This informs Vendor Threshold Overrides (future architecture).
    
    Identifies:
    - Vendors consistently under 50% automation
    - Vendors with high match scores but high exception rates (process issue)
    - Vendors with consistently high confidence (candidates for lower thresholds)
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    # Get all documents
    docs = await db.hub_documents.find(
        query,
        {"extracted_fields.vendor": 1, "match_score": 1, "status": 1, "ai_confidence": 1, "_id": 0}
    ).to_list(10000)
    
    # Vendor-level analysis
    vendor_stats = {}
    
    for doc in docs:
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        if vendor == "Unknown":
            continue
            
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {
                "total_docs": 0,
                "linked": 0,
                "needs_review": 0,
                "match_scores": [],
                "confidence_scores": []
            }
        
        vendor_stats[vendor]["total_docs"] += 1
        
        if doc.get("status") == "LinkedToBC":
            vendor_stats[vendor]["linked"] += 1
        elif doc.get("status") == "NeedsReview":
            vendor_stats[vendor]["needs_review"] += 1
        
        if doc.get("match_score"):
            vendor_stats[vendor]["match_scores"].append(doc["match_score"])
        if doc.get("ai_confidence"):
            vendor_stats[vendor]["confidence_scores"].append(doc["ai_confidence"])
    
    # Calculate aggregates per vendor
    analyzed_vendors = []
    
    for vendor, stats in vendor_stats.items():
        if stats["total_docs"] < 2:  # Need at least 2 docs for meaningful analysis
            continue
        
        automation_rate = round((stats["linked"] / stats["total_docs"] * 100), 1)
        exception_rate = round((stats["needs_review"] / stats["total_docs"] * 100), 1)
        avg_match_score = round(sum(stats["match_scores"]) / len(stats["match_scores"]), 3) if stats["match_scores"] else 0
        avg_confidence = round(sum(stats["confidence_scores"]) / len(stats["confidence_scores"]), 3) if stats["confidence_scores"] else 0
        
        analyzed_vendors.append({
            "vendor": vendor,
            "total_docs": stats["total_docs"],
            "automation_rate": automation_rate,
            "exception_rate": exception_rate,
            "avg_match_score": avg_match_score,
            "avg_confidence": avg_confidence,
            "min_match_score": min(stats["match_scores"]) if stats["match_scores"] else 0,
            "max_match_score": max(stats["match_scores"]) if stats["match_scores"] else 0,
        })
    
    # Categorize vendors
    low_automation_vendors = [v for v in analyzed_vendors if v["automation_rate"] < 50]
    high_score_high_exception = [v for v in analyzed_vendors 
                                  if v["avg_match_score"] >= 0.85 and v["exception_rate"] >= 40]
    consistently_high_confidence = [v for v in analyzed_vendors 
                                     if v["avg_match_score"] >= 0.92 and v["min_match_score"] >= 0.88 
                                     and v["automation_rate"] >= 80]
    
    # Sort by impact
    low_automation_vendors.sort(key=lambda x: x["total_docs"], reverse=True)
    high_score_high_exception.sort(key=lambda x: x["exception_rate"], reverse=True)
    consistently_high_confidence.sort(key=lambda x: x["avg_match_score"], reverse=True)
    
    return {
        "period_days": days,
        "total_vendors_analyzed": len(analyzed_vendors),
        "categories": {
            "low_automation": {
                "description": "Vendors consistently under 50% automation - need attention",
                "count": len(low_automation_vendors),
                "vendors": low_automation_vendors[:10]
            },
            "high_score_high_exception": {
                "description": "High match scores but high exceptions - likely process or data issue",
                "count": len(high_score_high_exception),
                "vendors": high_score_high_exception[:10]
            },
            "consistently_high_confidence": {
                "description": "Candidates for threshold override (consistent high scores)",
                "count": len(consistently_high_confidence),
                "vendors": consistently_high_confidence[:10]
            }
        },
        "threshold_override_candidates": [
            {
                "vendor": v["vendor"],
                "recommended_threshold": max(0.88, v["min_match_score"] - 0.02),
                "avg_match_score": v["avg_match_score"],
                "min_match_score": v["min_match_score"],
                "automation_rate": v["automation_rate"]
            }
            for v in consistently_high_confidence[:5]
        ]
    }


class ShadowModeConfig(BaseModel):
    """Configuration for shadow mode tracking."""
    shadow_mode_started_at: Optional[str] = None
    shadow_mode_notes: Optional[str] = None


@router.get("/settings/shadow-mode")
async def get_shadow_mode_status():
    """
    Get shadow mode status for Phase 6 monitoring.
    
    Returns feature flag status, shadow mode duration, and quick health indicators.
    """
    db = get_db()
    # Get shadow mode config from settings
    settings = await db.hub_settings.find_one({"type": "shadow_mode"}, {"_id": 0})
    
    if not settings:
        # Initialize shadow mode settings if not exists
        settings = {
            "type": "shadow_mode",
            "shadow_mode_started_at": None,
            "shadow_mode_notes": "",
            "created_utc": datetime.now(timezone.utc).isoformat()
        }
    
    # Calculate days in shadow mode
    days_in_shadow_mode = 0
    if settings.get("shadow_mode_started_at"):
        start_date = datetime.fromisoformat(settings["shadow_mode_started_at"].replace('Z', '+00:00'))
        days_in_shadow_mode = (datetime.now(timezone.utc) - start_date).days
    
    # Get quick health indicators (last 7 days)
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    query_7d = {"created_utc": {"$gte": cutoff_7d}}
    
    # High confidence docs percentage
    docs_with_score = await db.hub_documents.find(
        {**query_7d, "match_score": {"$exists": True, "$ne": None}},
        {"match_score": 1, "_id": 0}
    ).to_list(10000)
    
    high_conf_count = sum(1 for d in docs_with_score if (d.get("match_score") or 0) >= 0.92)
    high_conf_pct = round((high_conf_count / len(docs_with_score) * 100) if docs_with_score else 0, 1)
    
    # Alias exception rate (last 7 days)
    alias_total_7d = await db.hub_documents.count_documents({**query_7d, "match_method": "alias"})
    alias_exceptions_7d = await db.hub_documents.count_documents({
        **query_7d, "match_method": "alias", "status": "NeedsReview"
    })
    alias_exception_rate_7d = round((alias_exceptions_7d / alias_total_7d * 100) if alias_total_7d > 0 else 0, 1)
    
    # Top friction vendor this week
    top_friction_vendor = None
    vendor_friction = await db.hub_documents.aggregate([
        {"$match": {**query_7d, "status": "NeedsReview"}},
        {"$group": {"_id": "$extracted_fields.vendor", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1}
    ]).to_list(1)
    
    if vendor_friction:
        top_friction_vendor = {
            "vendor": vendor_friction[0]["_id"],
            "exception_count": vendor_friction[0]["count"]
        }
    
    return {
        "feature_flags": {
            "CREATE_DRAFT_HEADER": ENABLE_CREATE_DRAFT_HEADER,
            "DEMO_MODE": DEMO_MODE
        },
        "shadow_mode": {
            "started_at": settings.get("shadow_mode_started_at"),
            "days_running": days_in_shadow_mode,
            "notes": settings.get("shadow_mode_notes", ""),
            "is_active": settings.get("shadow_mode_started_at") is not None and not ENABLE_CREATE_DRAFT_HEADER
        },
        "health_indicators_7d": {
            "high_confidence_docs_pct": high_conf_pct,
            "alias_exception_rate": alias_exception_rate_7d,
            "top_friction_vendor": top_friction_vendor,
            "total_docs_processed": len(docs_with_score)
        },
        # Phase C1: Email polling health (passive tap - read-only)
        "email_polling": {
            "enabled": EMAIL_POLLING_ENABLED,
            "mode": "passive_tap",
            "user": EMAIL_POLLING_USER or "(not configured)",
            "interval_minutes": EMAIL_POLLING_INTERVAL_MINUTES,
            "permissions": "Mail.Read (read-only)"
        },
        "readiness_assessment": {
            "high_confidence_ok": high_conf_pct >= 60,
            "alias_exception_ok": alias_exception_rate_7d < 15,
            "sufficient_data": len(docs_with_score) >= 20,
            "recommended_action": (
                "Ready for controlled draft enablement" 
                if high_conf_pct >= 60 and alias_exception_rate_7d < 15 and len(docs_with_score) >= 20
                else "Continue monitoring - need more data or better metrics"
            )
        },
        "draft_creation_thresholds": DRAFT_CREATION_CONFIG
    }


@router.post("/settings/shadow-mode")
async def update_shadow_mode_settings(config: ShadowModeConfig):
    """
    Update shadow mode configuration.
    
    Use this to:
    - Set shadow_mode_started_at when deploying to production
    - Add notes about deployments, vendor changes, alias imports
    """
    db = get_db()
    update_data = {}
    
    if config.shadow_mode_started_at is not None:
        update_data["shadow_mode_started_at"] = config.shadow_mode_started_at
    
    if config.shadow_mode_notes is not None:
        update_data["shadow_mode_notes"] = config.shadow_mode_notes
    
    if update_data:
        update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
        
        await db.hub_settings.update_one(
            {"type": "shadow_mode"},
            {"$set": update_data},
            upsert=True
        )
    
    return await get_shadow_mode_status()


@router.get("/reports/shadow-mode-performance")
async def get_shadow_mode_performance_report(days: int = 14):
    """
    Generate comprehensive Shadow Mode Performance report for ELT.
    
    This endpoint produces the complete analysis needed to decide
    whether to enable draft creation.
    
    Returns exportable JSON structure for executive presentation.
    """
    db = get_db()
    # Gather all metrics
    score_dist = await get_match_score_distribution()
    alias_metrics = await get_alias_exception_metrics(days=days)
    vendor_stability = await get_vendor_stability_analysis(days=days)
    shadow_status = await get_shadow_mode_status()
    automation_metrics = await _get_automation_metrics_internal(days=days)
    
    # Calculate production readiness score (0-100)
    # LOCKED FORMULA - Phase 7 explicit gates (do not modify without business justification)
    # Factor weights: High Conf (35) + Alias Exception (20) + Stable Vendors (25) + Data Volume (20) = 100
    readiness_factors = []
    
    # Factor 1: % docs with match_score >= 0.92 (weight: 35)
    # Target: 60% of documents should be high-confidence
    high_conf_pct = score_dist["summary"]["high_confidence_pct"]
    high_conf_score = min(35, (high_conf_pct / 60) * 35) if high_conf_pct < 60 else 35
    readiness_factors.append({
        "factor": "High Confidence Documents (≥0.92)",
        "value": high_conf_pct,
        "target": "≥60%",
        "score": round(high_conf_score, 1),
        "max_score": 35,
        "gate_passed": high_conf_pct >= 60
    })
    
    # Factor 2: Alias exception rate < 5% (weight: 20)
    # Full score if < 5%, proportional reduction otherwise
    alias_exc_rate = alias_metrics["alias_totals"]["alias_exception_rate"]
    if alias_exc_rate < 5:
        alias_score = 20
    elif alias_exc_rate < 10:
        alias_score = 15  # Partial credit
    elif alias_exc_rate < 20:
        alias_score = 10  # Minimal credit
    else:
        alias_score = 0
    readiness_factors.append({
        "factor": "Alias Exception Rate",
        "value": alias_exc_rate,
        "target": "<5%",
        "score": alias_score,
        "max_score": 20,
        "gate_passed": alias_exc_rate < 5
    })
    
    # Factor 3: ≥ 3 vendors stable (consistently high match scores) (weight: 25)
    # A vendor is "stable" if avg_match_score >= 0.94 and min_match_score >= 0.88
    stable_vendors_count = vendor_stability["categories"]["consistently_high_confidence"]["count"]
    if stable_vendors_count >= 3:
        vendor_score = 25
    elif stable_vendors_count >= 2:
        vendor_score = 18
    elif stable_vendors_count >= 1:
        vendor_score = 10
    else:
        vendor_score = 0
    readiness_factors.append({
        "factor": "Stable Vendors (≥0.94 avg score)",
        "value": stable_vendors_count,
        "target": "≥3",
        "score": vendor_score,
        "max_score": 25,
        "gate_passed": stable_vendors_count >= 3
    })
    
    # Factor 4: ≥ 100 docs observed (weight: 20)
    # Need meaningful volume for statistical confidence
    total_docs = automation_metrics["total_documents"]
    if total_docs >= 100:
        volume_score = 20
    elif total_docs >= 50:
        volume_score = round((total_docs / 100) * 20, 1)
    else:
        volume_score = round((total_docs / 100) * 10, 1)  # Slower ramp-up below 50
    readiness_factors.append({
        "factor": "Data Volume (Observed Docs)",
        "value": total_docs,
        "target": "≥100",
        "score": round(volume_score, 1),
        "max_score": 20,
        "gate_passed": total_docs >= 100
    })
    
    total_readiness_score = round(sum(f["score"] for f in readiness_factors), 1)
    gates_passed = sum(1 for f in readiness_factors if f["gate_passed"])
    
    # Determine recommendation (all 4 gates must pass for full readiness)
    if total_readiness_score >= 80 and gates_passed == 4:
        recommendation = "READY: All gates passed. System validated for controlled vendor enablement."
        recommendation_detail = "Enable CREATE_DRAFT_HEADER for 3 stable vendors (exact_no/exact_name/normalized only)."
    elif total_readiness_score >= 80:
        recommendation = "NEAR READY: Score high but not all gates passed."
        recommendation_detail = f"Review failing gates ({4 - gates_passed} of 4 not passed). Address before enablement."
    elif total_readiness_score >= 60:
        recommendation = "APPROACHING: System is close to production readiness."
        recommendation_detail = "Continue monitoring for 1-2 more weeks. Address failing gates."
    elif total_readiness_score >= 40:
        recommendation = "BUILDING: System needs more time and data."
        recommendation_detail = "Focus on improving alias coverage and vendor data hygiene."
    else:
        recommendation = "EARLY: System is in early shadow mode."
        recommendation_detail = "Continue collecting data. Review vendor friction and alias exceptions."
    
    return {
        "report_title": "Shadow Mode Performance Analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_period_days": days,
        "executive_summary": {
            "readiness_score": total_readiness_score,
            "readiness_max": 100,
            "gates_passed": gates_passed,
            "gates_total": 4,
            "recommendation": recommendation,
            "recommendation_detail": recommendation_detail,
            "shadow_mode_days": shadow_status["shadow_mode"]["days_running"],
            "total_documents_processed": total_docs,
            "high_confidence_pct": high_conf_pct
        },
        "readiness_factors": readiness_factors,
        "match_score_analysis": {
            "buckets": score_dist["buckets"],
            "summary": score_dist["summary"],
            "threshold_analysis": score_dist["threshold_analysis"]
        },
        "alias_engine_performance": {
            "totals": alias_metrics["alias_totals"],
            "interpretation": alias_metrics["interpretation"],
            "daily_trend": alias_metrics["daily_trend"],
            "top_exception_vendors": alias_metrics["top_exception_vendors"][:5],
            "high_contribution_vendors": alias_metrics["high_alias_contribution_vendors"][:5]
        },
        "vendor_friction_analysis": {
            "total_vendors": vendor_stability["total_vendors_analyzed"],
            "low_automation_count": vendor_stability["categories"]["low_automation"]["count"],
            "process_issue_count": vendor_stability["categories"]["high_score_high_exception"]["count"],
            "threshold_override_candidates": vendor_stability["threshold_override_candidates"]
        },
        "shadow_mode_status": shadow_status["shadow_mode"],
        "feature_flags": shadow_status["feature_flags"],
        "health_indicators": shadow_status["health_indicators_7d"],
        "next_steps": [
            "Review match score distribution for threshold confidence",
            "Address top friction vendors",
            "Consider creating aliases for high-exception vendors",
            "Monitor alias exception rate trend",
            "When readiness score >= 80, prepare for controlled enablement"
        ]
    }


@router.get("/metrics/extraction-quality")
async def get_extraction_quality_metrics(days: int = 7):
    """
    Phase 7 extraction quality metrics.
    
    Measures:
    - Field extraction completeness rates
    - Ready for draft candidate rate (Phase 7 Week 1)
    - Vendor name variation tracking
    - Canonical fields completeness
    """
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "extracted_fields": 1, 
            "canonical_fields": 1,
            "validation_results.extraction_quality": 1,
            "validation_results.normalized_fields": 1,
            "ai_confidence": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "draft_candidate_score": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    total = len(docs)
    if total == 0:
        return {
            "period_days": days,
            "total_documents": 0,
            "extraction_rates": {},
            "ready_for_draft_rate": 0,
            "vendor_variations": []
        }
    
    # Track field extraction rates
    field_counts = {
        "vendor": 0,
        "invoice_number": 0,
        "amount": 0,
        "po_number": 0,
        "due_date": 0
    }
    
    ready_for_draft = 0
    ready_to_link = 0
    draft_candidates_count = 0  # Phase 7 Week 1: computed flag
    vendor_names = {}  # Track variations
    
    for doc in docs:
        fields = doc.get("extracted_fields", {}) or {}
        norm_fields = doc.get("validation_results", {}).get("normalized_fields", {}) or {}
        canonical = doc.get("canonical_fields", {}) or {}
        
        # Use canonical fields first, then normalized, then raw
        check_fields = canonical if canonical else (norm_fields if norm_fields else fields)
        
        for field in field_counts.keys():
            # Check multiple possible field names
            val = (check_fields.get(field) or 
                   check_fields.get(f"{field}_normalized") or
                   check_fields.get(f"{field}_clean") or
                   fields.get(field))
            if val:
                field_counts[field] += 1
        
        # Check ready for draft (extraction completeness - legacy calc)
        has_vendor = bool(check_fields.get("vendor") or check_fields.get("vendor_normalized") or fields.get("vendor"))
        has_invoice = bool(check_fields.get("invoice_number") or check_fields.get("invoice_number_clean") or fields.get("invoice_number"))
        has_amount = (check_fields.get("amount") is not None or 
                     check_fields.get("amount_float") is not None or
                     fields.get("amount") is not None)
        
        if has_vendor and has_invoice and has_amount:
            ready_for_draft += 1
        
        # Phase 7 Week 1: Count computed draft candidates
        if doc.get("draft_candidate"):
            draft_candidates_count += 1
        
        # Track vendor name variations
        vendor = fields.get("vendor", "").strip() if fields.get("vendor") else ""
        if vendor:
            normalized = normalize_vendor_name(vendor)
            if normalized not in vendor_names:
                vendor_names[normalized] = {"variations": set(), "count": 0}
            vendor_names[normalized]["variations"].add(vendor)
            vendor_names[normalized]["count"] += 1
    
    # Calculate rates
    extraction_rates = {k: round(v / total * 100, 1) for k, v in field_counts.items()}
    
    # Find vendors with multiple name variations
    vendor_variations = [
        {
            "normalized": norm,
            "variations": list(data["variations"]),
            "count": data["count"]
        }
        for norm, data in vendor_names.items()
        if len(data["variations"]) > 1
    ]
    vendor_variations.sort(key=lambda x: x["count"], reverse=True)
    
    # Identify stable vendors (candidates for Phase 8)
    stable_vendors = [
        {
            "normalized": norm,
            "count": data["count"],
            "variations": list(data["variations"])
        }
        for norm, data in vendor_names.items()
        if data["count"] >= 5  # At least 5 docs
    ]
    stable_vendors.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "period_days": days,
        "total_documents": total,
        "extraction_rates": extraction_rates,
        "readiness_metrics": {
            "ready_for_draft": {
                "count": ready_for_draft,
                "rate": round(ready_for_draft / total * 100, 1),
                "description": "Docs with vendor + invoice_number + amount extracted"
            },
            "draft_candidates": {
                "count": draft_candidates_count,
                "rate": round(draft_candidates_count / total * 100, 1),
                "description": "Phase 7: Computed draft_candidate flag (AP + all fields + confidence >= 0.92)"
            },
            "ready_to_link": {
                "count": ready_to_link,
                "rate": round(ready_to_link / total * 100, 1) if total > 0 else 0,
                "description": "Docs matched to existing BC record (match_score >= 0.80)"
            }
        },
        "completeness_summary": {
            "all_required_fields": ready_for_draft,
            "missing_vendor": total - field_counts["vendor"],
            "missing_invoice_number": total - field_counts["invoice_number"],
            "missing_amount": total - field_counts["amount"]
        },
        "vendor_variations": vendor_variations[:20],
        "stable_vendors": stable_vendors[:10],
        "phase_7_recommendation": "Draft Candidates is the primary indicator for Phase 8 readiness. Lead with extraction completeness + confidence."
    }


@router.get("/metrics/extraction-misses")
async def get_extraction_misses(
    field: str = Query("vendor", description="Field to check: vendor, invoice_number, amount"),
    days: int = Query(7),
    limit: int = Query(100)
):
    """
    Phase 7: Diagnostic endpoint for documents missing specific fields.
    
    Filter AP_Invoice documents from the last N days by the given missing field:
    - field=vendor → vendor_normalized missing
    - field=invoice_number → invoice_number_clean missing
    - field=amount → amount_float missing
    
    Returns data needed for debugging extraction during observation mode.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Map field parameter to actual document field
    field_map = {
        "vendor": "vendor_normalized",
        "invoice_number": "invoice_number_clean",
        "amount": "amount_float"
    }
    
    actual_field = field_map.get(field, f"extracted_fields.{field}")
    
    # Build query for AP_Invoice documents missing the specified field
    query = {
        "created_utc": {"$gte": cutoff},
        "document_type": {"$in": ["AP_Invoice", "AP Invoice"]},
        "$or": [
            {actual_field: {"$exists": False}},
            {actual_field: None},
            {actual_field: ""}
        ]
    }
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "file_name": 1,
            "source": 1,
            "document_type": 1,
            "status": 1,
            "ai_confidence": 1,
            "vendor_raw": 1,
            "vendor_normalized": 1,
            "invoice_number_raw": 1,
            "invoice_number_clean": 1,
            "amount_raw": 1,
            "amount_float": 1,
            "due_date_raw": 1,
            "po_number_raw": 1,
            "email_sender": 1,
            "email_subject": 1,
            "created_utc": 1,
            "_id": 0
        }
    ).sort("created_utc", -1).to_list(limit)
    
    results = []
    for d in docs:
        # Build text snippet from email subject
        text_snippet = ""
        if d.get("email_subject"):
            text_snippet = d["email_subject"][:500]
        elif d.get("email_sender"):
            text_snippet = f"From: {d['email_sender']}"
        
        results.append({
            "document_id": d.get("id"),
            "file_name": d.get("file_name"),
            "document_type": d.get("document_type"),
            "status": d.get("status"),
            "vendor_raw": d.get("vendor_raw"),
            "invoice_number_raw": d.get("invoice_number_raw"),
            "amount_raw": d.get("amount_raw"),
            "due_date_raw": d.get("due_date_raw"),
            "po_number_raw": d.get("po_number_raw"),
            "ai_confidence": d.get("ai_confidence"),
            "first_500_chars_text": text_snippet,
            "created_utc": d.get("created_utc")
        })
    
    return {
        "field": field,
        "period_days": days,
        "missing_count": len(results),
        "documents": results,
        "analysis_hints": [
            f"Review these {len(results)} AP_Invoice documents to understand why '{field}' wasn't extracted",
            "Common causes: unusual document format, scanned PDFs, non-standard layouts",
            "Check ai_confidence - low confidence may indicate OCR quality issues"
        ]
    }


@router.get("/metrics/stable-vendors")
async def get_stable_vendors(
    min_count: int = Query(5, description="Minimum document count to be stable"),
    min_completeness: float = Query(0.85, description="Minimum field completeness rate (0-1)"),
    max_variants: int = Query(3, description="Maximum allowed name variations"),
    days: int = Query(30)
):
    """
    Phase 7 Week 1: Stable Vendor metric endpoint.
    
    Stable Vendor Criteria (Phase 7 metric only):
    - count >= min_count (default 5)
    - required field completeness >= min_completeness (default 85%)
    - alias variance <= max_variants (default 3 variants)
    - no conflicting invoice numbers
    
    This does NOT enable anything - it only reports candidates for Phase 8.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "extracted_fields": 1,
            "canonical_fields": 1,
            "ai_confidence": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    # Group by normalized vendor
    vendor_data = {}
    
    for doc in docs:
        extracted = doc.get("extracted_fields", {}) or {}
        canonical = doc.get("canonical_fields", {}) or {}
        
        # Get vendor - prefer canonical normalized
        vendor_normalized = canonical.get("vendor_normalized") or ""
        if not vendor_normalized and extracted.get("vendor"):
            vendor_normalized = normalize_vendor_name(extracted.get("vendor", ""))
        
        if not vendor_normalized:
            continue
        
        if vendor_normalized not in vendor_data:
            vendor_data[vendor_normalized] = {
                "variations": set(),
                "count": 0,
                "has_vendor": 0,
                "has_invoice_number": 0,
                "has_amount": 0,
                "invoice_numbers": set(),
                "draft_candidates": 0,
                "high_confidence_count": 0  # ai_confidence >= 0.92
            }
        
        vd = vendor_data[vendor_normalized]
        vd["count"] += 1
        
        # Track variations
        raw_vendor = extracted.get("vendor", "")
        if raw_vendor:
            vd["variations"].add(raw_vendor)
        
        # Field completeness
        if extracted.get("vendor") or canonical.get("vendor_normalized"):
            vd["has_vendor"] += 1
        if extracted.get("invoice_number") or canonical.get("invoice_number_clean"):
            vd["has_invoice_number"] += 1
            inv_num = canonical.get("invoice_number_clean") or extracted.get("invoice_number", "")
            if inv_num:
                vd["invoice_numbers"].add(str(inv_num))
        if extracted.get("amount") is not None or canonical.get("amount_float") is not None:
            vd["has_amount"] += 1
        
        # Draft candidate tracking
        if doc.get("draft_candidate"):
            vd["draft_candidates"] += 1
        
        # High confidence tracking
        confidence = doc.get("ai_confidence", 0)
        if confidence and confidence >= 0.92:
            vd["high_confidence_count"] += 1
    
    # Evaluate stability
    stable_vendors = []
    unstable_vendors = []
    
    for vendor_name, data in vendor_data.items():
        count = data["count"]
        
        # Calculate completeness
        completeness_rate = 0.0
        if count > 0:
            completeness_rate = (
                (data["has_vendor"] + data["has_invoice_number"] + data["has_amount"]) / 
                (count * 3)
            )
        
        # Check for duplicate/conflicting invoice numbers
        has_conflicts = len(data["invoice_numbers"]) < count * 0.5 if count > 2 else False
        
        vendor_record = {
            "vendor_normalized": vendor_name,
            "count": count,
            "variations": list(data["variations"]),
            "variation_count": len(data["variations"]),
            "completeness_rate": round(completeness_rate, 3),
            "field_breakdown": {
                "vendor": data["has_vendor"],
                "invoice_number": data["has_invoice_number"],
                "amount": data["has_amount"]
            },
            "draft_candidates": data["draft_candidates"],
            "draft_candidate_rate": round(data["draft_candidates"] / count, 3) if count > 0 else 0,
            "high_confidence_count": data["high_confidence_count"],
            "high_confidence_rate": round(data["high_confidence_count"] / count, 3) if count > 0 else 0,
            "unique_invoices": len(data["invoice_numbers"]),
            "potential_conflicts": has_conflicts
        }
        
        # Check stability criteria
        is_stable = (
            count >= min_count and
            completeness_rate >= min_completeness and
            len(data["variations"]) <= max_variants and
            not has_conflicts
        )
        
        vendor_record["is_stable"] = is_stable
        
        if is_stable:
            vendor_record["stability_reasons"] = ["Meets all criteria"]
            stable_vendors.append(vendor_record)
        else:
            reasons = []
            if count < min_count:
                reasons.append(f"count {count} < {min_count}")
            if completeness_rate < min_completeness:
                reasons.append(f"completeness {completeness_rate:.1%} < {min_completeness:.0%}")
            if len(data["variations"]) > max_variants:
                reasons.append(f"variations {len(data['variations'])} > {max_variants}")
            if has_conflicts:
                reasons.append("potential invoice conflicts")
            vendor_record["stability_reasons"] = reasons
            unstable_vendors.append(vendor_record)
    
    # Sort by count descending
    stable_vendors.sort(key=lambda x: x["count"], reverse=True)
    unstable_vendors.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "period_days": days,
        "criteria": {
            "min_count": min_count,
            "min_completeness": min_completeness,
            "max_variants": max_variants
        },
        "summary": {
            "total_vendors": len(vendor_data),
            "stable_vendors": len(stable_vendors),
            "unstable_vendors": len(unstable_vendors),
            "stable_rate": round(len(stable_vendors) / len(vendor_data), 3) if vendor_data else 0
        },
        "stable_vendors": stable_vendors[:20],
        "near_stable_vendors": [
            v for v in unstable_vendors 
            if v["count"] >= min_count - 2 and v["completeness_rate"] >= min_completeness - 0.1
        ][:10],
        "phase_8_note": "Stable vendors are candidates for controlled draft enablement in Phase 8. This endpoint is metric-only and does not enable any automation."
    }


@router.get("/metrics/draft-candidates")
async def get_draft_candidate_metrics(days: int = Query(7)):
    db = get_db()
    """
    Phase 7 Week 1: Draft Candidate metrics endpoint.
    
    Shows distribution of draft candidate flags computed at ingestion.
    This is NON-OPERATIONAL - it only reports what WOULD be ready for draft creation.
    
    Dashboard can show:
    - ReadyForDraftCandidate: X%
    - ReadyToLink: Y%  
    - NeedsHumanReview: Z%
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "draft_candidate_score": 1,
            "draft_candidate_reason": 1,
            "ai_confidence": 1,
            "status": 1,
            "match_method": 1,
            "match_score": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    total = len(docs)
    if total == 0:
        return {
            "period_days": days,
            "total_documents": 0,
            "draft_candidate_rate": 0,
            "readiness_breakdown": {}
        }
    
    # Count draft candidates
    draft_candidates = sum(1 for d in docs if d.get("draft_candidate"))
    
    # Count by score bucket
    score_buckets = {
        "100_ready": 0,      # Perfect score, draft ready
        "75_needs_confidence": 0,   # Missing confidence only
        "50_needs_fields": 0,       # Missing 1-2 fields
        "25_not_ap": 0,             # Not AP_Invoice
        "0_missing_all": 0          # Multiple issues
    }
    
    # Count by missing reason
    missing_reasons = {
        "missing vendor": 0,
        "missing invoice_number": 0,
        "missing amount": 0,
        "low_confidence": 0,
        "wrong_doc_type": 0
    }
    
    # Count ready to link
    ready_to_link = 0
    needs_review = 0
    
    for doc in docs:
        score = doc.get("draft_candidate_score", 0)
        reasons = doc.get("draft_candidate_reason", [])
        status = doc.get("status", "")
        
        # Bucket by score
        if score == 100:
            score_buckets["100_ready"] += 1
        elif score >= 75:
            score_buckets["75_needs_confidence"] += 1
        elif score >= 50:
            score_buckets["50_needs_fields"] += 1
        elif score >= 25:
            score_buckets["25_not_ap"] += 1
        else:
            score_buckets["0_missing_all"] += 1
        
        # Track missing reasons
        for reason in reasons:
            if "vendor" in reason.lower():
                missing_reasons["missing vendor"] += 1
            if "invoice_number" in reason.lower():
                missing_reasons["missing invoice_number"] += 1
            if "amount" in reason.lower():
                missing_reasons["missing amount"] += 1
            if "confidence" in reason.lower():
                missing_reasons["low_confidence"] += 1
            if "document_type" in reason.lower() or "not AP" in reason:
                missing_reasons["wrong_doc_type"] += 1
        
        # Track status
        if status in ("ReadyToLink", "LinkedToBC"):
            ready_to_link += 1
        elif status == "NeedsReview":
            needs_review += 1
    
    return {
        "period_days": days,
        "total_documents": total,
        "draft_candidate_summary": {
            "draft_candidates": draft_candidates,
            "draft_candidate_rate": round(draft_candidates / total * 100, 1),
            "description": "Documents that WOULD be ready for draft creation if Phase 8 was enabled"
        },
        "readiness_breakdown": {
            "ReadyForDraftCandidate": round(draft_candidates / total * 100, 1),
            "ReadyToLink": round(ready_to_link / total * 100, 1),
            "NeedsHumanReview": round(needs_review / total * 100, 1),
            "Other": round((total - draft_candidates - ready_to_link - needs_review) / total * 100, 1)
        },
        "score_distribution": {
            k: {"count": v, "rate": round(v / total * 100, 1)} 
            for k, v in score_buckets.items()
        },
        "missing_field_analysis": missing_reasons,
        "phase_7_note": "This is observation-only. Draft creation is NOT enabled. Use this data to improve extraction quality."
    }
