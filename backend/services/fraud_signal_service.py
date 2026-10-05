"""Payment-fraud (business email compromise) signal for incoming documents.

Found 2026-10-05: the AP inbox received a campaign of fake invoices and
payment requests from unrelated or compromised domains impersonating
consultancies and services (Protiviti from a French joinery domain,
"LinkedIn" from lectrosalt.us, Didlake $101,750 and "Della Laira"
$137,500/$275,000, "Executive Coaching Bureau" $75,000, "Vistage
coaching" $9,980 ...). None were in BC. The Hub learned sender mappings
for them and filed them like vendor invoices.

A document is flagged when all three hold:
  * the vendor is not a BC vendor number (unknown to Gamer's books),
  * the sender's domain does not carry the vendor's name,
  * the subject/file name uses service or payment-pressure wording.
A large amount adds to the score. On February-October 2026 history the
rule flagged 21 AP documents, all of the campaign. Flagged documents route
to DO NOT PAY for a person to check; the flag never blocks anything else.
"""
import re
from typing import Any, Dict, Optional

SERVICE_WORDING = re.compile(
    r"advisory|coaching|consult|engagement|payment (?:transfer|filing|status)|not settled|overdue"
    r"|outstanding balance|resilience|leadership|strategic|internal controls|risk structure"
    r"|vendor update|bank(?:ing)? (?:details|information|change)|remittance change|w-?9\b",
    re.I,
)
_GENERIC = {"inc", "llc", "corp", "company", "group", "services", "service", "international",
            "packaging", "solutions", "the", "and", "global", "usa", "america"}
_INTERNAL_DOMAINS = ("gamerpackaging.com",)


def _brand_tokens(name: str):
    return {t for t in re.findall(r"[a-z]{4,}", str(name or "").lower()) if t not in _GENERIC}


async def assess_fraud_risk(db, doc: Dict[str, Any]) -> Dict[str, Any]:
    sender = str(doc.get("email_sender") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    if not domain or domain.endswith(_INTERNAL_DOMAINS):
        return {"flagged": False}
    # Shared billing platforms send on behalf of many companies (a Bill.com
    # W-9 request is routine); their domain never matches a vendor name.
    from services.vendor_matching import SHARED_SENDER_DOMAINS
    if any(domain == d or domain.endswith("." + d) for d in SHARED_SENDER_DOMAINS):
        return {"flagged": False}
    ef = doc.get("extracted_fields") or {}
    vendor_name = ef.get("vendor") or doc.get("vendor_raw") or doc.get("vendor_canonical") or ""
    vendor_no = str(doc.get("vendor_canonical") or "").strip()
    in_bc = bool(vendor_no) and await db.hub_bc_vendors.find_one({"number": vendor_no}, {"_id": 1}) is not None
    domain_flat = domain.replace("-", "")
    domain_matches = any(t in domain_flat for t in _brand_tokens(vendor_name))
    wording = f"{doc.get('email_subject') or ''} {doc.get('file_name') or ''}"
    wording_hit = SERVICE_WORDING.search(wording)
    amount = abs(float(doc.get("amount_float") or 0))
    reasons = []
    if not in_bc:
        reasons.append("vendor not in BC")
    if not domain_matches:
        reasons.append(f"sender domain {domain} does not match vendor {vendor_name!r}" if vendor_name else f"unknown vendor from {domain}")
    if wording_hit:
        reasons.append(f"payment/service wording: {wording_hit.group(0)!r}")
    if amount >= 5000:
        reasons.append(f"amount {amount:,.2f}")
    flagged = (not in_bc) and (not domain_matches) and bool(wording_hit)
    return {"flagged": flagged, "score": len(reasons), "reasons": reasons, "sender_domain": domain}
