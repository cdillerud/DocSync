"""Mexican CFDI e-invoices (XML) as exact invoice data.

Mexican vendors (Fevisa) email each invoice twice: the PDF and its CFDI
XML (SAT format 3.3/4.0, e.g. "F-ML184308.xml" next to "F-ML184308.pdf").
The XML carries the invoice exactly: Serie+Folio (the number AP enters in
BC, "ML184308"), Total, Moneda, Fecha, TipoDeComprobante (I = invoice,
E = credit note) and the SAT UUID. AI extraction read nothing from the XML
and often missed the number/amount on the PDF (26 of 79 PDFs unlinked to
BC, 2026-10-06).

For each recent CFDI XML document:
* the companion PDF (same email, same file stem) gets the invoice number,
  amount, currency and CFDI data where it has none; where it has different
  values they are kept and the difference recorded (cfdi_mismatch);
* the XML itself is marked a duplicate of the PDF (duplicate_reason
  "cfdi_xml_companion"), so one invoice is not counted or filed twice;
* an XML with no PDF gets the fields itself and stays active.
Idempotent; runs hourly in the learning cycle, before BC reconciliation.
"""
import base64
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def parse_cfdi(raw: bytes) -> Optional[Dict[str, Any]]:
    """The invoice fields of a CFDI XML, or None when it is not one."""
    try:
        text = raw.decode("utf-8-sig", "replace")
        if "Comprobante" not in text[:4000]:
            return None
        root = ET.fromstring(text.lstrip("﻿").encode("utf-8"))
    except Exception:
        return None
    if not root.tag.endswith("Comprobante"):
        return None
    a = root.attrib

    def child(name):
        for el in root.iter():
            if el.tag.endswith("}" + name) or el.tag == name:
                return el.attrib
        return {}

    try:
        total = float(a.get("Total") or a.get("total"))
    except (TypeError, ValueError):
        return None
    serie, folio = (a.get("Serie") or "").strip(), (a.get("Folio") or "").strip()
    kind = (a.get("TipoDeComprobante") or "").strip().upper()
    emisor, timbre = child("Emisor"), child("TimbreFiscalDigital")
    return {
        "invoice_number": f"{serie}{folio}".upper() if folio else "",
        "serie": serie, "folio": folio,
        "total": total, "subtotal": a.get("SubTotal"),
        "currency": (a.get("Moneda") or "").upper(),
        "date": (a.get("Fecha") or "")[:10],
        "type": kind,  # I ingreso (invoice), E egreso (credit note), P pago, T traslado
        "issuer_name": emisor.get("Nombre"), "issuer_rfc": emisor.get("Rfc"),
        "uuid": (timbre.get("UUID") or "").upper(),
        "version": a.get("Version"),
    }


def _unpad(n: Any) -> str:
    """MO006984 (PDF) and MO + folio 6984 (CFDI) are the same number."""
    return re.sub(r"(?<=[A-Z])0+(?=[0-9])", "", re.sub(r"[^A-Z0-9]", "", str(n or "").upper()))


def _fields_from(c: Dict[str, Any]) -> Dict[str, Any]:
    amount = -abs(c["total"]) if c["type"] == "E" else c["total"]
    out = {"amount_float": amount, "cfdi": c}
    if c["invoice_number"]:
        out["invoice_number_clean"] = c["invoice_number"]
    if c["currency"]:
        out["currency"] = c["currency"]
    return out


async def process_recent(db, days: int = 120, apply: bool = True) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"xml": 0, "not_cfdi": 0, "pdf_filled": 0, "pdf_mismatch": 0, "xml_marked_companion": 0,
             "xml_standalone_filled": 0, "credit_notes": 0}
    async for x in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "file_name": {"$regex": r"\.xml$", "$options": "i"},
             "file_content_b64": {"$exists": True, "$ne": None}},
            {"_id": 1, "id": 1, "file_name": 1, "email_id": 1, "file_content_b64": 1, "is_duplicate": 1,
             "vendor_canonical": 1, "cfdi": 1, "amount_float": 1, "invoice_number_clean": 1}):
        stats["xml"] += 1
        try:
            c = parse_cfdi(base64.b64decode(x["file_content_b64"]))
        except Exception:
            c = None
        if not c:
            stats["not_cfdi"] += 1
            continue
        if c["type"] == "E":
            stats["credit_notes"] += 1
        fields = _fields_from(c)
        stem = re.sub(r"\.xml$", "", x["file_name"], flags=re.I)
        pdf = None
        if x.get("email_id"):
            pdf = await db.hub_documents.find_one(
                {"email_id": x["email_id"], "id": {"$ne": x.get("id")},
                 "file_name": {"$regex": "^" + re.escape(stem) + r"\.pdf$", "$options": "i"}},
                {"_id": 1, "id": 1, "amount_float": 1, "invoice_number_clean": 1, "currency": 1, "vendor_canonical": 1,
                 "document_type": 1})
        if pdf:
            upd: Dict[str, Any] = {"cfdi": c, "cfdi_from_document_id": x.get("id")}
            mismatch = {}
            if pdf.get("amount_float") in (None, 0, 0.0):
                upd["amount_float"] = fields["amount_float"]
                upd["amount_from_cfdi"] = {"at": now, "previous": pdf.get("amount_float")}
            elif abs(abs(float(pdf["amount_float"])) - abs(c["total"])) >= 0.02:
                mismatch["amount"] = {"pdf": pdf["amount_float"], "cfdi": c["total"]}
            if c["invoice_number"]:
                if not pdf.get("invoice_number_clean"):
                    upd["invoice_number_clean"] = c["invoice_number"]
                    upd["invoice_number_from_cfdi"] = {"at": now, "previous": pdf.get("invoice_number_clean")}
                elif _unpad(pdf["invoice_number_clean"]) != _unpad(c["invoice_number"]):
                    mismatch["invoice_number"] = {"pdf": pdf["invoice_number_clean"], "cfdi": c["invoice_number"]}
            if not pdf.get("currency") and c["currency"]:
                upd["currency"] = c["currency"]
            if not pdf.get("vendor_canonical") and x.get("vendor_canonical"):
                upd["vendor_canonical"] = x["vendor_canonical"]
            if c["type"] == "E" and pdf.get("document_type") != "Credit_Memo":
                upd.update({"document_type": "Credit_Memo", "suggested_job_type": "Credit_Memo",
                            "document_type_previous": pdf.get("document_type")})
            unset = {} if mismatch else {"cfdi_mismatch": ""}
            if mismatch:
                upd["cfdi_mismatch"] = mismatch
                stats["pdf_mismatch"] += 1
            if "amount_float" in upd or "invoice_number_clean" in upd:
                stats["pdf_filled"] += 1
            xml_upd = {"cfdi": c}
            if not x.get("is_duplicate"):
                xml_upd.update({"is_duplicate": True, "duplicate_reason": "cfdi_xml_companion",
                                "duplicate_of_document_id": pdf.get("id"), "updated_utc": now})
                stats["xml_marked_companion"] += 1
            if apply:
                await db.hub_documents.update_one({"_id": pdf["_id"]}, {"$set": upd, **({"$unset": unset} if unset else {})})
                await db.hub_documents.update_one({"_id": x["_id"]}, {"$set": xml_upd})
        else:
            upd = {"cfdi": c}
            if x.get("amount_float") in (None, 0, 0.0):
                upd["amount_float"] = fields["amount_float"]
            if not x.get("invoice_number_clean") and c["invoice_number"]:
                upd["invoice_number_clean"] = c["invoice_number"]
            if c["currency"]:
                upd["currency"] = c["currency"]
            if c["type"] == "E":
                upd.update({"document_type": "Credit_Memo", "suggested_job_type": "Credit_Memo"})
            elif c["type"] == "I":
                upd.update({"document_type": "AP_Invoice", "suggested_job_type": "AP_Invoice"})
            stats["xml_standalone_filled"] += 1
            if apply:
                await db.hub_documents.update_one({"_id": x["_id"]}, {"$set": upd})
    logger.info("[CFDI] %s", stats)
    return stats
