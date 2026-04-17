"""
GPI Document Hub — Customer Alias Service

Builds and maintains a learned mapping of email sender domains to BC customer numbers.
Similar to the vendor alias system but for the sales pipeline.

Example mappings:
  giovannifoods.com → GIOVANN
  comar.com → (learned from extraction + BC match)
  ompimail.com → (learned from extraction + BC match)

The alias table is built from:
  1. Existing pilot docs where customer was successfully resolved
  2. BC reference cache (email addresses on customer records)
  3. Manual overrides

Used by: entity_resolution_service.resolve_customer() to improve first-pass matching.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

COLLECTION = "customer_aliases"


async def build_aliases_from_pilot_docs() -> Dict[str, Any]:
    """
    Scan all pilot docs where customer was successfully resolved.
    Build domain → customer_no mappings from the email_sender + resolved customer.
    """
    db = get_db()

    # Find pilot docs with resolved customers (bc_prod_validation or spiro match)
    docs = await db.hub_documents.find(
        {
            "inside_sales_pilot": True,
            "email_sender": {"$exists": True, "$ne": None},
        },
        {
            "_id": 0, "id": 1, "email_sender": 1,
            "vendor_canonical": 1, "matched_customer_no": 1,
            "bc_prod_validation": 1, "spiro_match": 1,
            "sales_pilot_extraction": 1,
        },
    ).to_list(1000)

    domain_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "customer_nos": defaultdict(int),
        "customer_names": defaultdict(int),
        "doc_count": 0,
    })

    for doc in docs:
        sender = doc.get("email_sender") or ""
        if not sender or "@" not in sender:
            continue

        domain = sender.split("@")[1].lower()
        # Skip generic domains
        if domain in ("gmail.com", "outlook.com", "hotmail.com", "yahoo.com",
                       "gamerpackaging.com", "gamer.com"):
            continue

        # Get resolved customer_no from all sources
        bc_val = doc.get("bc_prod_validation") or {}
        bc_cm = bc_val.get("customer_match") or {}
        spiro = doc.get("spiro_match") or {}
        spiro_cm = spiro.get("company_match") or {}
        ext = doc.get("sales_pilot_extraction") or {}

        customer_no = (
            doc.get("matched_customer_no")
            or (bc_cm.get("bc_customer_no") if bc_cm.get("found") else None)
            or spiro_cm.get("external_id")
        )
        customer_name = (
            ext.get("customer_name")
            or (bc_cm.get("bc_customer_name") if bc_cm.get("found") else None)
            or spiro_cm.get("name")
            or doc.get("vendor_canonical")
        )

        # Skip Gamer
        if customer_no and customer_no.upper() in ("GAMER", "GAMERPA", "GAMER1"):
            continue
        if customer_name and "gamer" in customer_name.lower():
            continue

        domain_map[domain]["doc_count"] += 1
        if customer_no:
            domain_map[domain]["customer_nos"][customer_no] += 1
        if customer_name:
            domain_map[domain]["customer_names"][customer_name] += 1

    # Build aliases: use majority vote for domains with resolved customers
    created = 0
    updated = 0
    coll = db[COLLECTION]

    for domain, data in domain_map.items():
        if not data["customer_nos"]:
            continue

        # Pick the most common customer_no for this domain
        best_no = max(data["customer_nos"].items(), key=lambda x: x[1])
        best_name = max(data["customer_names"].items(), key=lambda x: x[1]) if data["customer_names"] else ("", 0)

        confidence = best_no[1] / data["doc_count"]  # How consistent is this mapping?
        if confidence < 0.3:
            continue  # Too inconsistent — skip

        alias = {
            "domain": domain,
            "customer_no": best_no[0],
            "customer_name": best_name[0],
            "confidence": round(confidence, 2),
            "doc_count": data["doc_count"],
            "evidence_count": best_no[1],
            "source": "pilot_learned",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        result = await coll.update_one(
            {"domain": domain},
            {"$set": alias},
            upsert=True,
        )
        if result.upserted_id:
            created += 1
        elif result.modified_count:
            updated += 1

    logger.info(
        "[CustomerAliases] Built aliases from %d docs: %d domains, %d created, %d updated",
        len(docs), len(domain_map), created, updated,
    )

    return {
        "docs_scanned": len(docs),
        "domains_found": len(domain_map),
        "aliases_created": created,
        "aliases_updated": updated,
        "total_aliases": await coll.count_documents({}),
    }


async def lookup_by_domain(domain: str) -> Optional[Dict[str, Any]]:
    """Look up a customer alias by email domain."""
    db = get_db()
    return await db[COLLECTION].find_one(
        {"domain": domain.lower()}, {"_id": 0}
    )


async def lookup_by_sender(email_sender: str) -> Optional[Dict[str, Any]]:
    """Look up a customer alias by full email address (extracts domain)."""
    if not email_sender or "@" not in email_sender:
        return None
    domain = email_sender.split("@")[1].lower()
    return await lookup_by_domain(domain)


async def get_all_aliases(limit: int = 200) -> List[Dict[str, Any]]:
    """Get all customer aliases, sorted by confidence."""
    db = get_db()
    return await db[COLLECTION].find(
        {}, {"_id": 0}
    ).sort("confidence", -1).limit(limit).to_list(limit)


async def add_manual_alias(
    domain: str, customer_no: str, customer_name: str = "",
) -> Dict[str, Any]:
    """Add or override a customer alias manually."""
    db = get_db()
    alias = {
        "domain": domain.lower(),
        "customer_no": customer_no,
        "customer_name": customer_name,
        "confidence": 1.0,
        "source": "manual",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[COLLECTION].update_one(
        {"domain": domain.lower()}, {"$set": alias}, upsert=True,
    )
    return alias
