"""
GPI Document Hub — Spiro ↔ BC Cross-Reference Dashboard Service

Read-only analysis comparing Spiro CRM customers/opportunities
against Business Central customers/orders to surface:
  - Customers in Spiro but not BC (pipeline leakage)
  - Customers in BC but not Spiro (CRM gap)
  - Matched customers with opportunity ↔ order alignment
  - ISR coverage and assignment gaps
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from deps import get_db
from services.spiro_service import SPIRO_ENABLED, search_company, get_company_opportunities

logger = logging.getLogger(__name__)


async def build_cross_reference_dashboard(db) -> Dict[str, Any]:
    """
    Build the Spiro ↔ BC cross-reference dashboard from pilot data.

    Uses already-stored spiro_match and bc_prod_validation results
    on pilot documents to compute cross-reference metrics.
    """

    # ── Pilot docs with Spiro matches ──
    spiro_matched = await db.hub_documents.find(
        {
            "inside_sales_pilot": True,
            "spiro_match": {"$exists": True, "$ne": None},
        },
        {"_id": 0, "id": 1, "spiro_match": 1, "bc_prod_validation": 1,
         "sales_pilot_extraction": 1, "doc_type": 1, "file_name": 1,
         "email_sender": 1, "pilot_mailbox": 1},
    ).to_list(500)

    # ── Aggregate unique companies from Spiro matches ──
    spiro_companies: Dict[str, Dict[str, Any]] = {}
    bc_customers: Dict[str, Dict[str, Any]] = {}
    cross_matches = []  # noqa: F841
    spiro_only = []
    bc_only = []
    both = []

    for doc in spiro_matched:
        sm = doc.get("spiro_match") or {}
        bv = doc.get("bc_prod_validation") or {}

        # Spiro side
        cm = sm.get("company_match") or {}
        spiro_id = cm.get("spiro_id")
        spiro_name = cm.get("name")
        if spiro_id and spiro_name:
            if spiro_id not in spiro_companies:
                spiro_companies[spiro_id] = {
                    "spiro_id": spiro_id,
                    "name": spiro_name,
                    "relationship_type": cm.get("relationship_type"),
                    "external_id": cm.get("external_id"),
                    "assigned_isr": cm.get("assigned_isr"),
                    "industries_served": cm.get("industries_served"),
                    "doc_count": 0,
                    "opportunities": len(sm.get("opportunities", [])),
                    "bc_customer_no": None,
                    "bc_customer_name": None,
                }
            spiro_companies[spiro_id]["doc_count"] += 1

        # BC side
        bc_cm = (bv.get("customer_match") or {})
        bc_no = bc_cm.get("bc_customer_no")
        bc_name = bc_cm.get("bc_customer_name")
        if bc_no:
            if bc_no not in bc_customers:
                bc_customers[bc_no] = {
                    "bc_customer_no": bc_no,
                    "bc_customer_name": bc_name,
                    "doc_count": 0,
                    "spiro_id": None,
                    "spiro_name": None,
                }
            bc_customers[bc_no]["doc_count"] += 1

        # Cross-reference
        if spiro_id and bc_no:
            if spiro_id in spiro_companies:
                spiro_companies[spiro_id]["bc_customer_no"] = bc_no
                spiro_companies[spiro_id]["bc_customer_name"] = bc_name
            if bc_no in bc_customers:
                bc_customers[bc_no]["spiro_id"] = spiro_id
                bc_customers[bc_no]["spiro_name"] = spiro_name

    # Classify each Spiro company
    for sid, sc in spiro_companies.items():
        if sc.get("bc_customer_no"):
            both.append(sc)
        else:
            spiro_only.append(sc)

    # Classify each BC customer
    for bno, bc in bc_customers.items():
        if not bc.get("spiro_id"):
            bc_only.append(bc)

    # ── ISR coverage ──
    isr_stats: Dict[str, Dict[str, Any]] = {}
    for sc in spiro_companies.values():
        isr = sc.get("assigned_isr") or "Unassigned"
        if isr not in isr_stats:
            isr_stats[isr] = {"companies": 0, "docs": 0, "with_bc": 0, "opportunities": 0}
        isr_stats[isr]["companies"] += 1
        isr_stats[isr]["docs"] += sc["doc_count"]
        isr_stats[isr]["opportunities"] += sc.get("opportunities", 0)
        if sc.get("bc_customer_no"):
            isr_stats[isr]["with_bc"] += 1

    # ── Opportunity pipeline value ──
    total_opp_value = 0
    opp_count = 0
    for doc in spiro_matched:
        sm = doc.get("spiro_match") or {}
        for opp in sm.get("opportunities", []):
            amt = float(opp.get("amount") or 0)
            if amt > 0:
                total_opp_value += amt
                opp_count += 1

    # ── Documents without any match ──
    no_match_docs = []
    for doc in spiro_matched:
        sm = doc.get("spiro_match") or {}
        bv = doc.get("bc_prod_validation") or {}
        cm = sm.get("company_match") or {}
        bc_cm = bv.get("customer_match") or {}
        if not cm.get("spiro_id") and not bc_cm.get("found"):
            no_match_docs.append({
                "doc_id": doc["id"],
                "file_name": doc.get("file_name"),
                "sender": doc.get("email_sender"),
                "customer": (doc.get("sales_pilot_extraction") or {}).get("customer_name"),
                "mailbox": doc.get("pilot_mailbox"),
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_pilot_docs": len(spiro_matched),
            "unique_spiro_companies": len(spiro_companies),
            "unique_bc_customers": len(bc_customers),
            "in_both": len(both),
            "spiro_only": len(spiro_only),
            "bc_only": len(bc_only),
            "no_match_either": len(no_match_docs),
            "spiro_match_rate": f"{round(len(spiro_companies) / len(spiro_matched) * 100) if spiro_matched else 0}%",
        },
        "pipeline": {
            "total_opportunities": opp_count,
            "total_pipeline_value": round(total_opp_value, 2),
            "avg_opportunity_value": round(total_opp_value / opp_count, 2) if opp_count else 0,
        },
        "cross_reference": {
            "matched_both_systems": sorted(both, key=lambda x: x["doc_count"], reverse=True),
            "spiro_only_no_bc": sorted(spiro_only, key=lambda x: x["doc_count"], reverse=True),
            "bc_only_no_spiro": sorted(bc_only, key=lambda x: x["doc_count"], reverse=True),
        },
        "isr_coverage": sorted(
            [{"isr": k, **v} for k, v in isr_stats.items()],
            key=lambda x: x["docs"], reverse=True,
        ),
        "unmatched_documents": no_match_docs[:20],
    }
