"""
Business Central posting-preview orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative preview implementation and request model directly.
"""

import logging
import os
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)


class DryRunPreviewRequest(BaseModel):
    """Request for dry-run preview with optional BC environment override."""
    use_production_bc: bool = True
    bc_tenant_id: Optional[str] = None
    bc_environment: Optional[str] = None


async def preview_post_to_bc(doc_id: str, request: DryRunPreviewRequest = None):
    """DRY-RUN PREVIEW: Shows what would be posted to BC without writing."""
    import httpx
    db = get_db()

    def _parse_amount(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            cleaned = str(value).replace(",", "").replace("$", "").replace(" ", "").strip()
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    PROD_TENANT_ID = request.bc_tenant_id if request and request.bc_tenant_id else os.environ.get("BC_PROD_TENANT_ID", "")
    PROD_ENVIRONMENT = request.bc_environment if request and request.bc_environment else os.environ.get("BC_PROD_ENVIRONMENT", "Production")
    PROD_CLIENT_ID = os.environ.get("BC_PROD_CLIENT_ID", "")
    PROD_CLIENT_SECRET = os.environ.get("BC_PROD_CLIENT_SECRET", "")

    if not PROD_TENANT_ID or not PROD_CLIENT_ID or not PROD_CLIENT_SECRET:
        return {
            "doc_id": doc_id, "dry_run": True,
            "error": "Production BC credentials not configured.",
            "errors": ["Missing BC_PROD_* environment variables"],
        }

    preview_result = {
        "doc_id": doc_id,
        "file_name": doc.get("file_name"),
        "document_type": doc.get("document_type") or doc.get("suggested_job_type"),
        "dry_run": True, "would_write_to_bc": False,
        "bc_environment_used": f"{PROD_TENANT_ID[:8]}.../{PROD_ENVIRONMENT}",
        "validation": {"passed": False, "checks": [], "warnings": []},
        "extracted_data": {},
        "purchase_invoice_preview": None,
        "sales_order_match": None,
        "folder_routing": None,
        "errors": [],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                f"https://login.microsoftonline.com/{PROD_TENANT_ID}/oauth2/v2.0/token",
                data={
                    "client_id": PROD_CLIENT_ID, "client_secret": PROD_CLIENT_SECRET,
                    "scope": "https://api.businesscentral.dynamics.com/.default",
                    "grant_type": "client_credentials",
                },
            )

            if token_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC token: {token_resp.status_code}")
                return preview_result

            token = token_resp.json().get("access_token")

            companies_resp = await client.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies",
                headers={"Authorization": f"Bearer {token}"},
            )

            if companies_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC companies: {companies_resp.status_code}")
                return preview_result

            companies = companies_resp.json().get("value", [])
            company_id = None
            for c in companies:
                if "Gamer" in c.get("name", ""):
                    company_id = c.get("id")
                    break
            if not company_id and companies:
                company_id = companies[0].get("id")

            if not company_id:
                preview_result["errors"].append("No BC company found")
                return preview_result

            # Extract data
            extracted_fields = doc.get("extracted_fields") or {}
            normalized_fields = doc.get("normalized_fields") or {}
            ai_extraction = doc.get("ai_extraction") or {}

            vendor_name = (doc.get("vendor_canonical") or normalized_fields.get("vendor")
                           or extracted_fields.get("vendor") or ai_extraction.get("vendor"))
            invoice_number = (doc.get("invoice_number_clean") or normalized_fields.get("invoice_number")
                              or extracted_fields.get("invoice_number") or ai_extraction.get("invoice_number"))
            invoice_date = (doc.get("invoice_date") or normalized_fields.get("invoice_date")
                            or extracted_fields.get("invoice_date") or ai_extraction.get("invoice_date"))
            total_amount = (doc.get("amount_float") or normalized_fields.get("amount")
                            or extracted_fields.get("amount") or ai_extraction.get("total_amount"))
            order_reference = (doc.get("bol_number_extracted") or doc.get("po_number_extracted")
                               or normalized_fields.get("bol_number") or normalized_fields.get("po_number")
                               or extracted_fields.get("bol_number") or extracted_fields.get("po_number")
                               or extracted_fields.get("order_number") or ai_extraction.get("bol_number")
                               or ai_extraction.get("po_number"))

            preview_result["extracted_data"] = {
                "vendor": vendor_name, "invoice_number": invoice_number,
                "invoice_date": invoice_date, "total_amount": _parse_amount(total_amount),
                "order_reference": order_reference, "currency": doc.get("currency", "USD"),
            }

            # Vendor validation
            if vendor_name:
                from services.unified_vendor_matcher import match_vendor_unified
                unified_result = await match_vendor_unified(db, vendor_name, min_score=0.7)

                if unified_result.get("matched"):
                    best_match = unified_result.get("best_match", {})
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match", "passed": True,
                        "details": f"Found vendor via {unified_result.get('source')}: {best_match.get('name')} (score: {unified_result.get('score', 0):.0%})",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "is_freight_carrier": unified_result.get("is_freight_carrier", False),
                    })
                    preview_result["extracted_data"]["vendor_number"] = best_match.get("vendor_number") or unified_result.get("bc_vendor_number")
                    preview_result["extracted_data"]["vendor_id"] = best_match.get("vendor_id") or unified_result.get("bc_vendor_id")
                    preview_result["extracted_data"]["vendor_display_name"] = best_match.get("name")
                    preview_result["extracted_data"]["is_freight_carrier"] = unified_result.get("is_freight_carrier", False)
                    preview_result["extracted_data"]["vendor_match_source"] = unified_result.get("source")
                else:
                    all_matches = unified_result.get("all_matches", [])
                    candidate_info = ""
                    if all_matches:
                        top = all_matches[0]
                        candidate_info = f" Best candidate: {top.get('name')} ({top.get('score', 0):.0%}) from {top.get('source')}"
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match", "passed": False,
                        "details": f"No vendor found matching '{vendor_name}' (checked: {', '.join(unified_result.get('sources_checked', []))}).{candidate_info}",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "candidates": [{"name": m.get("name"), "score": m.get("score"), "source": m.get("source")} for m in all_matches[:3]],
                    })

            # Freight direction
            bc_base = f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies({company_id})"
            freight_direction = "unknown"

            if order_reference:
                order_str = str(order_reference).strip()

                order_resp = await client.get(
                    f"{bc_base}/salesOrders",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"number eq '{order_str}'"},
                )
                if order_resp.status_code == 200:
                    orders = order_resp.json().get("value", [])
                    if orders:
                        matched_order = orders[0]
                        freight_direction = "outbound"
                        preview_result["freight_direction"] = "outbound"
                        preview_result["freight_direction_details"] = {
                            "direction": "outbound", "reason": "Order reference matches a Sales Order",
                            "description": "Freight cost for shipping TO customer",
                        }
                        preview_result["sales_order_match"] = {
                            "found": True, "number": matched_order.get("number"),
                            "customer_name": matched_order.get("customerName"),
                            "customer_number": matched_order.get("customerNumber"),
                            "order_date": matched_order.get("orderDate"),
                            "status": matched_order.get("status"),
                            "total_amount": matched_order.get("totalAmountIncludingTax"),
                        }
                        preview_result["validation"]["checks"].append({
                            "check": "freight_direction", "passed": True,
                            "details": f"OUTBOUND freight - Order {order_str} matches Sales Order for {matched_order.get('customerName')}",
                        })

                if freight_direction == "unknown":
                    po_resp = await client.get(
                        f"{bc_base}/purchaseOrders",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"number eq '{order_str}'"},
                    )
                    if po_resp.status_code == 200:
                        pos = po_resp.json().get("value", [])
                        if pos:
                            matched_po = pos[0]
                            freight_direction = "inbound"
                            preview_result["freight_direction"] = "inbound"
                            preview_result["freight_direction_details"] = {
                                "direction": "inbound", "reason": "Order reference matches a Purchase Order",
                                "description": "Freight cost for receiving FROM vendor/supplier",
                            }
                            preview_result["purchase_order_match"] = {
                                "found": True, "number": matched_po.get("number"),
                                "vendor_name": matched_po.get("vendorName"),
                                "vendor_number": matched_po.get("vendorNumber"),
                                "order_date": matched_po.get("orderDate"),
                                "status": matched_po.get("status"),
                                "total_amount": matched_po.get("totalAmountIncludingTax"),
                            }
                            preview_result["validation"]["checks"].append({
                                "check": "freight_direction", "passed": True,
                                "details": f"INBOUND freight - Order {order_str} matches Purchase Order from {matched_po.get('vendorName')}",
                            })

                if freight_direction == "unknown":
                    preview_result["freight_direction"] = "unknown"
                    preview_result["freight_direction_details"] = {
                        "direction": "unknown",
                        "reason": f"Order reference '{order_str}' not found in Sales Orders or Purchase Orders",
                        "description": "Could not determine freight direction - manual review needed",
                    }
                    preview_result["validation"]["warnings"].append({
                        "check": "freight_direction",
                        "details": f"Could not determine freight direction - '{order_str}' not found as Sales Order or Purchase Order",
                    })
            else:
                preview_result["freight_direction"] = "unknown"
                preview_result["freight_direction_details"] = {
                    "direction": "unknown", "reason": "No order reference extracted from document",
                    "description": "Cannot determine freight direction without BOL/Order number",
                }
                preview_result["validation"]["warnings"].append({
                    "check": "freight_direction",
                    "details": "No order reference found - cannot determine if inbound or outbound freight",
                })

            # Duplicate check
            if invoice_number:
                dup_resp = await client.get(
                    f"{bc_base}/purchaseInvoices",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"},
                )
                if dup_resp.status_code == 200:
                    existing = dup_resp.json().get("value", [])
                    if existing:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check", "passed": False,
                            "details": f"DUPLICATE: Invoice {invoice_number} already exists in BC",
                        })
                    else:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check", "passed": True,
                            "details": "No duplicate invoice found",
                        })

            # Build preview
            line_description = order_reference if order_reference else "Freight"
            preview_result["purchase_invoice_preview"] = {
                "header": {
                    "vendorNumber": preview_result["extracted_data"].get("vendor_number", "[VENDOR NOT MATCHED]"),
                    "vendorInvoiceNumber": invoice_number,
                    "invoiceDate": invoice_date,
                    "dueDate": doc.get("due_date_iso"),
                    "currencyCode": doc.get("currency", "USD"),
                },
                "lines": [{
                    "lineType": "Item", "itemNumber": "FREIGHT",
                    "description": str(line_description)[:100],
                    "quantity": 1, "unitCost": _parse_amount(total_amount) or 0,
                }],
                "note": "This is what WOULD be posted. No data was written.",
            }

            # Folder routing
            from services.folder_routing_service import determine_folder_path
            folder_path, routing_reason, routing_details = determine_folder_path(
                doc, freight_direction=preview_result.get("freight_direction"), is_international=False,
            )
            preview_result["folder_routing"] = {
                "folder_path": folder_path, "routing_reason": routing_reason, "routing_details": routing_details,
            }

            all_checks_passed = all(c.get("passed", False) for c in preview_result["validation"]["checks"])
            preview_result["validation"]["passed"] = all_checks_passed

            if all_checks_passed:
                preview_result["would_write_to_bc"] = True
                preview_result["ready_to_post"] = True
            else:
                preview_result["ready_to_post"] = False
                preview_result["blocking_issues"] = [
                    c["details"] for c in preview_result["validation"]["checks"] if not c.get("passed")
                ]

    except Exception as e:
        logger.error("Preview-post error for %s: %s", doc_id, str(e))
        preview_result["errors"].append(str(e))

    return preview_result
