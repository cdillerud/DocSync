"""
GPI Document Hub - Pilot Summary Generator

Generates daily summary reports for the 14-day shadow pilot.
Includes metrics, doc type breakdown, stalls, and misclassifications.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from services.pilot_config import (
    PILOT_MODE_ENABLED, CURRENT_PILOT_PHASE,
    PILOT_START_DATE, PILOT_END_DATE,
    get_stuck_threshold_hours, STUCK_THRESHOLDS
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Email recipients for daily summary
PILOT_SUMMARY_RECIPIENTS = [
    "rhonda@gamerpackaging.com",
    "paula@gamerpackaging.com",
    "cdillerud@gamerpackaging.com",
]

# Feature flag for daily emails
DAILY_PILOT_EMAIL_ENABLED = True

# Cron schedule (hour in CST - note: server may be in UTC)
PILOT_SUMMARY_CRON_HOUR_UTC = 13  # 7 AM CST = 13:00 UTC


# =============================================================================
# SUMMARY DATA STRUCTURES
# =============================================================================

@dataclass
class DocTypeSummary:
    """Summary metrics for a single doc type."""
    doc_type: str
    count_24h: int
    cumulative_count: int
    deterministic_count: int
    ai_count: int
    stall_count: int
    status_distribution: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PilotDailySummary:
    """Complete daily pilot summary."""
    # Meta
    phase: str
    report_date: str
    pilot_day: int
    pilot_total_days: int
    generated_at: str
    
    # High-level metrics
    total_documents_24h: int
    total_documents_cumulative: int
    classification_accuracy: float
    ai_usage_rate: float
    deterministic_count: int
    ai_count: int
    corrected_count: int
    
    # Stalls and issues
    workflow_stalls_24h: int
    stalls_by_status: Dict[str, int]
    extraction_errors: Dict[str, int]
    top_misclassifications: List[Dict[str, Any]]
    
    # Breakdown by doc type
    by_doc_type: List[DocTypeSummary]
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["by_doc_type"] = [dt.to_dict() if hasattr(dt, 'to_dict') else dt for dt in self.by_doc_type]
        return result


# =============================================================================
# SUMMARY GENERATOR
# =============================================================================

async def generate_daily_pilot_summary(db) -> PilotDailySummary:
    """
    Generate a daily summary of pilot metrics.
    
    Args:
        db: MongoDB database instance
        
    Returns:
        PilotDailySummary with all metrics
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday = now - timedelta(hours=24)
    
    # Calculate pilot day
    try:
        pilot_start = datetime.strptime(PILOT_START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        pilot_day = (now - pilot_start).days + 1
    except Exception:
        pilot_day = 1
    
    # Base match for pilot documents
    base_match = {"pilot_phase": CURRENT_PILOT_PHASE}
    
    # 24h match
    match_24h = {
        **base_match,
        "pilot_date": {"$gte": yesterday.isoformat()}
    }
    
    # === HIGH-LEVEL METRICS ===
    
    # Total documents (24h)
    total_24h = await db.hub_documents.count_documents(match_24h)
    
    # Total documents (cumulative)
    total_cumulative = await db.hub_documents.count_documents(base_match)
    
    # Classification breakdown
    classification_pipeline = [
        {"$match": base_match},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^deterministic"}},
                    "deterministic",
                    {"$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}},
                        "ai",
                        "other"
                    ]}
                ]
            },
            "count": {"$sum": 1}
        }}
    ]
    classification_results = await db.hub_documents.aggregate(classification_pipeline).to_list(10)
    
    deterministic_count = 0
    ai_count = 0
    other_count = 0
    for r in classification_results:
        if r["_id"] == "deterministic":
            deterministic_count = r["count"]
        elif r["_id"] == "ai":
            ai_count = r["count"]
        # 'other' count not currently used but captured in aggregate
    
    # Corrected documents
    corrected_pipeline = [
        {"$match": {
            **base_match,
            "$or": [
                {"classification_override": {"$exists": True}},
                {"manual_doc_type_correction": {"$exists": True}}
            ]
        }},
        {"$count": "corrected"}
    ]
    corrected_result = await db.hub_documents.aggregate(corrected_pipeline).to_list(1)
    corrected_count = corrected_result[0]["corrected"] if corrected_result else 0
    
    # Calculate accuracy
    accuracy = ((total_cumulative - corrected_count) / total_cumulative * 100) if total_cumulative > 0 else 100.0
    
    # AI usage rate
    ai_usage_rate = (ai_count / total_cumulative * 100) if total_cumulative > 0 else 0.0
    
    # === WORKFLOW STALLS ===
    
    threshold_24h = (now - timedelta(hours=24)).isoformat()
    stuck_statuses = list(STUCK_THRESHOLDS.keys())
    stuck_statuses.remove("default")
    
    stalls_pipeline = [
        {"$match": {
            **base_match,
            "workflow_status": {"$in": stuck_statuses},
            "workflow_status_updated_utc": {"$lt": threshold_24h}
        }},
        {"$group": {
            "_id": "$workflow_status",
            "count": {"$sum": 1}
        }}
    ]
    stalls_results = await db.hub_documents.aggregate(stalls_pipeline).to_list(20)
    stalls_by_status = {r["_id"]: r["count"] for r in stalls_results}
    total_stalls = sum(stalls_by_status.values())
    
    # === EXTRACTION ERRORS ===
    
    extraction_errors_pipeline = [
        {"$match": base_match},
        {"$project": {
            "doc_type": 1,
            "missing_vendor": {
                "$cond": [
                    {"$and": [
                        {"$eq": ["$doc_type", "AP_INVOICE"]},
                        {"$or": [
                            {"$eq": [{"$ifNull": ["$vendor_name", None]}, None]},
                            {"$eq": ["$vendor_name", ""]}
                        ]}
                    ]},
                    1, 0
                ]
            },
            "missing_invoice_number": {
                "$cond": [
                    {"$or": [
                        {"$eq": [{"$ifNull": ["$invoice_number_clean", None]}, None]},
                        {"$eq": ["$invoice_number_clean", ""]}
                    ]},
                    1, 0
                ]
            },
            "missing_amount": {
                "$cond": [
                    {"$eq": [{"$ifNull": ["$amount_float", None]}, None]},
                    1, 0
                ]
            }
        }},
        {"$group": {
            "_id": None,
            "missing_vendor": {"$sum": "$missing_vendor"},
            "missing_invoice_number": {"$sum": "$missing_invoice_number"},
            "missing_amount": {"$sum": "$missing_amount"}
        }}
    ]
    extraction_results = await db.hub_documents.aggregate(extraction_errors_pipeline).to_list(1)
    extraction_errors = {}
    if extraction_results:
        r = extraction_results[0]
        if r.get("missing_vendor", 0) > 0:
            extraction_errors["missing_vendor"] = r["missing_vendor"]
        if r.get("missing_invoice_number", 0) > 0:
            extraction_errors["missing_invoice_number"] = r["missing_invoice_number"]
        if r.get("missing_amount", 0) > 0:
            extraction_errors["missing_amount"] = r["missing_amount"]
    
    # === TOP MISCLASSIFICATIONS ===
    
    misclass_pipeline = [
        {"$match": {
            **base_match,
            "classification_override": {"$exists": True}
        }},
        {"$group": {
            "_id": {
                "original": "$ai_classification.suggested_type",
                "corrected": "$doc_type"
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    misclass_results = await db.hub_documents.aggregate(misclass_pipeline).to_list(10)
    top_misclassifications = [
        {
            "original": r["_id"]["original"],
            "corrected": r["_id"]["corrected"],
            "count": r["count"]
        }
        for r in misclass_results
    ]
    
    # === DOC TYPE BREAKDOWN ===
    
    doc_type_breakdown = []
    
    # Get all doc types
    doc_types_pipeline = [
        {"$match": base_match},
        {"$group": {"_id": "$doc_type"}}
    ]
    doc_types = await db.hub_documents.aggregate(doc_types_pipeline).to_list(20)
    
    for dt_result in doc_types:
        doc_type = dt_result["_id"] or "OTHER"
        
        # Count 24h
        count_24h = await db.hub_documents.count_documents({
            **match_24h,
            "doc_type": doc_type
        })
        
        # Cumulative count
        cumulative = await db.hub_documents.count_documents({
            **base_match,
            "doc_type": doc_type
        })
        
        # Classification for this type
        dt_class_pipeline = [
            {"$match": {**base_match, "doc_type": doc_type}},
            {"$group": {
                "_id": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^deterministic"}},
                        "deterministic",
                        {"$cond": [
                            {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}},
                            "ai",
                            "other"
                        ]}
                    ]
                },
                "count": {"$sum": 1}
            }}
        ]
        dt_class_results = await db.hub_documents.aggregate(dt_class_pipeline).to_list(5)
        
        dt_deterministic = sum(r["count"] for r in dt_class_results if r["_id"] == "deterministic")
        dt_ai = sum(r["count"] for r in dt_class_results if r["_id"] == "ai")
        
        # Status distribution
        status_pipeline = [
            {"$match": {**base_match, "doc_type": doc_type}},
            {"$group": {
                "_id": "$workflow_status",
                "count": {"$sum": 1}
            }}
        ]
        status_results = await db.hub_documents.aggregate(status_pipeline).to_list(20)
        status_dist = {r["_id"]: r["count"] for r in status_results}
        
        # Stalls for this type
        dt_stalls = await db.hub_documents.count_documents({
            **base_match,
            "doc_type": doc_type,
            "workflow_status": {"$in": stuck_statuses},
            "workflow_status_updated_utc": {"$lt": threshold_24h}
        })
        
        doc_type_breakdown.append(DocTypeSummary(
            doc_type=doc_type,
            count_24h=count_24h,
            cumulative_count=cumulative,
            deterministic_count=dt_deterministic,
            ai_count=dt_ai,
            stall_count=dt_stalls,
            status_distribution=status_dist
        ))
    
    # Sort by cumulative count
    doc_type_breakdown.sort(key=lambda x: x.cumulative_count, reverse=True)
    
    return PilotDailySummary(
        phase=CURRENT_PILOT_PHASE,
        report_date=today_str,
        pilot_day=pilot_day,
        pilot_total_days=14,
        generated_at=now.isoformat(),
        total_documents_24h=total_24h,
        total_documents_cumulative=total_cumulative,
        classification_accuracy=round(accuracy, 2),
        ai_usage_rate=round(ai_usage_rate, 2),
        deterministic_count=deterministic_count,
        ai_count=ai_count,
        corrected_count=corrected_count,
        workflow_stalls_24h=total_stalls,
        stalls_by_status=stalls_by_status,
        extraction_errors=extraction_errors,
        top_misclassifications=top_misclassifications,
        by_doc_type=doc_type_breakdown
    )


# =============================================================================
# HTML EMAIL TEMPLATE
# =============================================================================

def generate_summary_html(summary: PilotDailySummary) -> str:
    """
    Generate an HTML email from the pilot summary.
    
    Args:
        summary: PilotDailySummary data
        
    Returns:
        HTML string for the email body
    """
    
    # Status indicator for stalls
    stall_color = "#ef4444" if summary.workflow_stalls_24h > 0 else "#22c55e"
    stall_icon = "⚠️" if summary.workflow_stalls_24h > 0 else "✓"
    
    # Build doc type rows
    doc_type_rows = ""
    for dt in summary.by_doc_type:
        doc_type_rows += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #374151;">{dt.doc_type}</td>
            <td style="padding: 12px; border-bottom: 1px solid #374151; text-align: center;">{dt.count_24h}</td>
            <td style="padding: 12px; border-bottom: 1px solid #374151; text-align: center;">{dt.cumulative_count}</td>
            <td style="padding: 12px; border-bottom: 1px solid #374151; text-align: center;">{dt.deterministic_count}</td>
            <td style="padding: 12px; border-bottom: 1px solid #374151; text-align: center;">{dt.ai_count}</td>
            <td style="padding: 12px; border-bottom: 1px solid #374151; text-align: center; color: {'#ef4444' if dt.stall_count > 0 else '#9ca3af'};">{dt.stall_count}</td>
        </tr>
        """
    
    # Build stalls rows
    stalls_rows = ""
    if summary.stalls_by_status:
        for status, count in summary.stalls_by_status.items():
            stalls_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #374151;">{status}</td>
                <td style="padding: 8px; border-bottom: 1px solid #374151; text-align: center;">{count}</td>
            </tr>
            """
    else:
        stalls_rows = """
        <tr>
            <td colspan="2" style="padding: 16px; text-align: center; color: #22c55e;">
                ✓ No workflow stalls detected
            </td>
        </tr>
        """
    
    # Build misclassification rows
    misclass_rows = ""
    if summary.top_misclassifications:
        for mc in summary.top_misclassifications[:5]:
            misclass_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #374151;">{mc.get('original', '-')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #374151;">→</td>
                <td style="padding: 8px; border-bottom: 1px solid #374151;">{mc.get('corrected', '-')}</td>
                <td style="padding: 8px; border-bottom: 1px solid #374151; text-align: center;">{mc.get('count', 0)}</td>
            </tr>
            """
    else:
        misclass_rows = """
        <tr>
            <td colspan="4" style="padding: 16px; text-align: center; color: #22c55e;">
                ✓ No misclassifications detected
            </td>
        </tr>
        """
    
    # Build extraction errors section
    extraction_section = ""
    if summary.extraction_errors:
        extraction_items = "".join([
            f"<li style='margin: 4px 0;'>{k.replace('_', ' ').title()}: <strong>{v}</strong></li>"
            for k, v in summary.extraction_errors.items()
        ])
        extraction_section = f"""
        <div style="background: #7f1d1d; border-radius: 8px; padding: 16px; margin-top: 16px;">
            <h4 style="color: #fca5a5; margin: 0 0 8px 0;">Extraction Issues</h4>
            <ul style="color: #fca5a5; margin: 0; padding-left: 20px;">
                {extraction_items}
            </ul>
        </div>
        """
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #111827; color: #f3f4f6;">
    <div style="max-width: 800px; margin: 0 auto; padding: 20px;">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="background: rgba(255,255,255,0.2); border-radius: 8px; padding: 8px;">
                    <span style="font-size: 24px;">📊</span>
                </div>
                <div>
                    <h1 style="margin: 0; font-size: 24px; color: white;">GPI Document Hub</h1>
                    <p style="margin: 4px 0 0 0; color: #bfdbfe; font-size: 14px;">Shadow Pilot Daily Summary</p>
                </div>
            </div>
            <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.2);">
                <span style="background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 16px; font-size: 14px; color: white;">
                    Day {summary.pilot_day} of {summary.pilot_total_days}
                </span>
                <span style="color: #bfdbfe; font-size: 14px; margin-left: 12px;">
                    {summary.report_date}
                </span>
            </div>
        </div>
        
        <!-- Summary Cards -->
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px;">
            <!-- Total Documents -->
            <div style="background: #1f2937; border-radius: 12px; padding: 20px;">
                <p style="margin: 0; color: #9ca3af; font-size: 12px; text-transform: uppercase;">Documents (24h)</p>
                <p style="margin: 8px 0 0 0; font-size: 32px; font-weight: bold; color: #3b82f6;">{summary.total_documents_24h}</p>
                <p style="margin: 4px 0 0 0; color: #6b7280; font-size: 12px;">{summary.total_documents_cumulative} total</p>
            </div>
            
            <!-- Accuracy -->
            <div style="background: #1f2937; border-radius: 12px; padding: 20px;">
                <p style="margin: 0; color: #9ca3af; font-size: 12px; text-transform: uppercase;">Accuracy Score</p>
                <p style="margin: 8px 0 0 0; font-size: 32px; font-weight: bold; color: #22c55e;">{summary.classification_accuracy}%</p>
                <p style="margin: 4px 0 0 0; color: #6b7280; font-size: 12px;">{summary.corrected_count} corrected</p>
            </div>
            
            <!-- AI Usage -->
            <div style="background: #1f2937; border-radius: 12px; padding: 20px;">
                <p style="margin: 0; color: #9ca3af; font-size: 12px; text-transform: uppercase;">AI Usage Rate</p>
                <p style="margin: 8px 0 0 0; font-size: 32px; font-weight: bold; color: #a855f7;">{summary.ai_usage_rate}%</p>
                <p style="margin: 4px 0 0 0; color: #6b7280; font-size: 12px;">{summary.ai_count} AI / {summary.deterministic_count} deterministic</p>
            </div>
        </div>
        
        <!-- Stalls Card -->
        <div style="background: #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 24px; border-left: 4px solid {stall_color};">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 20px;">{stall_icon}</span>
                <div>
                    <p style="margin: 0; font-weight: bold; color: {stall_color};">
                        {summary.workflow_stalls_24h} Workflow Stall{"s" if summary.workflow_stalls_24h != 1 else ""}
                    </p>
                    <p style="margin: 2px 0 0 0; color: #9ca3af; font-size: 12px;">
                        Documents stuck in same status for &gt;24 hours
                    </p>
                </div>
            </div>
        </div>
        
        {extraction_section}
        
        <!-- Doc Type Breakdown -->
        <div style="background: #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 24px; margin-top: 24px;">
            <h3 style="margin: 0 0 16px 0; color: #f3f4f6; font-size: 16px;">📁 Document Type Breakdown</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #374151;">
                        <th style="padding: 12px; text-align: left; color: #9ca3af;">Type</th>
                        <th style="padding: 12px; text-align: center; color: #9ca3af;">24h</th>
                        <th style="padding: 12px; text-align: center; color: #9ca3af;">Total</th>
                        <th style="padding: 12px; text-align: center; color: #9ca3af;">Determ.</th>
                        <th style="padding: 12px; text-align: center; color: #9ca3af;">AI</th>
                        <th style="padding: 12px; text-align: center; color: #9ca3af;">Stalls</th>
                    </tr>
                </thead>
                <tbody>
                    {doc_type_rows if doc_type_rows else '<tr><td colspan="6" style="padding: 16px; text-align: center; color: #6b7280;">No documents ingested yet</td></tr>'}
                </tbody>
            </table>
        </div>
        
        <!-- Two Column: Stalls and Misclassifications -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px;">
            <!-- Stalls Detail -->
            <div style="background: #1f2937; border-radius: 12px; padding: 20px;">
                <h3 style="margin: 0 0 16px 0; color: #f3f4f6; font-size: 16px;">⏱️ Stalls by Status</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead>
                        <tr style="background: #374151;">
                            <th style="padding: 8px; text-align: left; color: #9ca3af;">Status</th>
                            <th style="padding: 8px; text-align: center; color: #9ca3af;">Count</th>
                        </tr>
                    </thead>
                    <tbody>
                        {stalls_rows}
                    </tbody>
                </table>
            </div>
            
            <!-- Misclassifications -->
            <div style="background: #1f2937; border-radius: 12px; padding: 20px;">
                <h3 style="margin: 0 0 16px 0; color: #f3f4f6; font-size: 16px;">🔄 Misclassifications</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead>
                        <tr style="background: #374151;">
                            <th style="padding: 8px; text-align: left; color: #9ca3af;">Original</th>
                            <th style="padding: 8px; color: #9ca3af;"></th>
                            <th style="padding: 8px; text-align: left; color: #9ca3af;">Corrected</th>
                            <th style="padding: 8px; text-align: center; color: #9ca3af;">#</th>
                        </tr>
                    </thead>
                    <tbody>
                        {misclass_rows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Footer -->
        <div style="background: #1f2937; border-radius: 12px; padding: 16px; text-align: center;">
            <p style="margin: 0; color: #6b7280; font-size: 12px;">
                Phase: <strong style="color: #9ca3af;">{summary.phase}</strong> |
                Generated: {summary.generated_at[:19].replace('T', ' ')} UTC |
                Environment: Shadow Pilot
            </p>
            <p style="margin: 8px 0 0 0; color: #4b5563; font-size: 11px;">
                This is an automated summary from GPI Document Hub. Do not reply to this email.
            </p>
        </div>
        
    </div>
</body>
</html>
"""
    return html


# =============================================================================
# EMAIL SENDING
# =============================================================================

async def send_daily_pilot_summary(db, email_service) -> Dict[str, Any]:
    """
    Generate and send the daily pilot summary email.
    
    Args:
        db: MongoDB database instance
        email_service: EmailService instance
        
    Returns:
        Dict with summary data and email result
    """
    from services.pilot_config import PILOT_MODE_ENABLED
    
    # Check if pilot mode is enabled
    if not PILOT_MODE_ENABLED:
        logger.info("Pilot mode disabled - skipping daily summary email")
        return {
            "sent": False,
            "reason": "pilot_mode_disabled",
            "summary": None
        }
    
    # Check if daily emails are enabled
    if not DAILY_PILOT_EMAIL_ENABLED:
        logger.info("Daily pilot emails disabled - skipping")
        return {
            "sent": False,
            "reason": "daily_emails_disabled",
            "summary": None
        }
    
    # Generate summary
    logger.info("Generating daily pilot summary...")
    summary = await generate_daily_pilot_summary(db)
    
    # Generate HTML
    html_body = generate_summary_html(summary)
    
    # Send email
    subject = f"[GPI Hub] Daily Pilot Summary – {summary.report_date}"
    
    result = await email_service.send_email(
        to=PILOT_SUMMARY_RECIPIENTS,
        subject=subject,
        html_body=html_body
    )
    
    logger.info(f"Daily pilot summary email sent: {result.success} (ID: {result.message_id})")
    
    return {
        "sent": result.success,
        "message_id": result.message_id,
        "recipients": PILOT_SUMMARY_RECIPIENTS,
        "summary": summary.to_dict(),
        "email_result": result.to_dict()
    }
