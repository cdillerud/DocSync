"""
Sales Pipeline Demo — End-to-End Document Flow

Generates a realistic PO as a PDF, feeds it through the full intake pipeline,
and returns a step-by-step trace of every stage:
  1. Document Generation
  2. Ingestion (hash, store)
  3. AI Classification & Field Extraction
  4. Vendor Resolution
  5. BC Validation / Preflight
  6. Sales Rep Auto-Assignment
  7. Final status → My Queue or Triage
"""

import io
import logging
import hashlib
import uuid
import random
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, BackgroundTasks
from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales-dashboard/demo", tags=["Sales Pipeline Demo"])

# ── Sample PO scenarios for the demo ──
DEMO_SCENARIOS = [
    {
        "id": "bragg-rush",
        "label": "Bragg Live Foods — Rush PO",
        "customer": "Bragg Live Food Products, LLC",
        "customer_no": "C-10147",
        "buyer": "Sarah Johnson",
        "buyer_email": "sjohnson@bragg.com",
        "sender_email": "purchasing@bragg.com",
        "po_number": f"PO-2026-{random.randint(5000,9999)}",
        "ship_to": "Bragg Live Food Products\n2360 Alamo Pintado Rd\nLos Olivos, CA 93441",
        "ship_method": "Drop Ship",
        "notes": "RUSH — Need delivery by end of week. Call warehouse to confirm stock.",
        "items": [
            {"sku": "PKG-1001", "desc": "32oz HDPE Amber Bottle", "qty": 15000, "price": 0.42},
            {"sku": "PKG-1002", "desc": "Tamper-Evident Cap 38mm Black", "qty": 15000, "price": 0.08},
            {"sku": "PKG-1015", "desc": "Shrink Sleeve Label 4-Color (ACV)", "qty": 15000, "price": 0.15},
            {"sku": "PKG-1020", "desc": "Corrugated Shipper 12-ct", "qty": 1250, "price": 1.85},
        ],
    },
    {
        "id": "huy-fong-large",
        "label": "Huy Fong Foods — Large Order",
        "customer": "Huy Fong Foods Inc.",
        "customer_no": "C-10734",
        "buyer": "David Park",
        "buyer_email": "dpark@huyfong.com",
        "sender_email": "orders@huyfong.com",
        "po_number": f"HFF-SO-2026-{random.randint(200,499)}",
        "ship_to": "Huy Fong Foods Inc.\n1755 Brewery Park Blvd\nIrwindale, CA 91706",
        "ship_method": "Warehouse",
        "notes": "",
        "items": [
            {"sku": "PKG-2010", "desc": "17oz Sriracha Squeeze Bottle (PET)", "qty": 50000, "price": 0.38},
            {"sku": "PKG-2011", "desc": "Green Cap 28mm w/ Liner", "qty": 50000, "price": 0.06},
            {"sku": "PKG-2012", "desc": "Wrap-Around Label 6-Color", "qty": 50000, "price": 0.12},
            {"sku": "PKG-2015", "desc": "Corrugated Shipper 24-ct", "qty": 2084, "price": 2.10},
            {"sku": "PKG-2016", "desc": "Divider Insert 24-ct", "qty": 2084, "price": 0.45},
            {"sku": "PKG-2020", "desc": "Pallet Stretch Wrap", "qty": 88, "price": 8.50},
        ],
    },
    {
        "id": "unknown-new",
        "label": "Unknown Customer — New Account",
        "customer": "Summit Ridge Naturals",
        "customer_no": "",
        "buyer": "Alex Torres",
        "buyer_email": "atorres@summitridge.com",
        "sender_email": "procurement@summitridge.com",
        "po_number": f"SRN-{random.randint(1000,9999)}",
        "ship_to": "Summit Ridge Naturals\n4200 Commerce Way\nBend, OR 97702",
        "ship_method": "Drop Ship",
        "notes": "First order — new customer. Please set up vendor account.",
        "items": [
            {"sku": "PKG-3001", "desc": "8oz Stand-Up Pouch Kraft", "qty": 10000, "price": 0.22},
            {"sku": "PKG-3002", "desc": "Resealable Zipper Top", "qty": 10000, "price": 0.03},
            {"sku": "PKG-3010", "desc": "Printed Film Roll (Granola)", "qty": 5000, "price": 0.18},
        ],
    },
    {
        "id": "giovanni-glass",
        "label": "Giovanni Food Co. — Glass Jars (Real PO Style)",
        "customer": "Giovanni Food Co., Inc.",
        "customer_no": "C-10250",
        "buyer": "Purchasing Dept.",
        "buyer_email": "purchasing@giovannifoods.com",
        "sender_email": "purchasing@giovannifoods.com",
        "po_number": "PO-61312",
        "ship_to": "Giovanni Foods\n8800 Sixty Road\nBaldwinsville, NY 13027\nUSA",
        "ship_method": "Outbound Freight",
        "notes": "Batch PO 61312-61361. First PO correlates to BC SO/PO 112115. Glass, 24oz, Bulk, 2821/Plt.",
        "items": [
            {"sku": "GLS-24OZ-BLK", "desc": "Glass, 24oz, Bulk, 2821/Plt", "qty": 62062, "price": 0.23474},
        ],
    },
]


def _generate_po_pdf(scenario: dict) -> bytes:
    """Generate a realistic-looking Purchase Order PDF."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    # Title style
    title_style = ParagraphStyle('POTitle', parent=styles['Title'], fontSize=18, spaceAfter=6)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=10, spaceAfter=2)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold')
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.grey)

    # Header
    elements.append(Paragraph("PURCHASE ORDER", title_style))
    elements.append(Spacer(1, 4))

    now = datetime.now(timezone.utc)
    po_date = now.strftime("%m/%d/%Y")
    due_date = (now + timedelta(days=30)).strftime("%m/%d/%Y")

    # PO Info table
    info_data = [
        ["PO Number:", scenario["po_number"], "Date:", po_date],
        ["Customer:", scenario["customer"], "Due Date:", due_date],
        ["Customer No:", scenario["customer_no"] or "NEW", "Ship Method:", scenario["ship_method"]],
        ["Buyer:", scenario["buyer"], "Buyer Email:", scenario["buyer_email"]],
    ]
    info_table = Table(info_data, colWidths=[80, 200, 80, 180])
    info_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # Ship To
    elements.append(Paragraph("Ship To:", bold_style))
    for line in scenario["ship_to"].split("\n"):
        elements.append(Paragraph(line, header_style))
    elements.append(Spacer(1, 12))

    # Line items
    headers = ["Line", "Item No", "Description", "Qty", "Unit Price", "Amount"]
    table_data = [headers]
    total = 0.0
    for i, item in enumerate(scenario["items"], 1):
        line_total = item["qty"] * item["price"]
        total += line_total
        table_data.append([
            str(i),
            item["sku"],
            item["desc"],
            f"{item['qty']:,}",
            f"${item['price']:.4f}",
            f"${line_total:,.2f}",
        ])

    # Total row
    table_data.append(["", "", "", "", "TOTAL:", f"${total:,.2f}"])

    col_widths = [35, 70, 180, 60, 70, 80]
    line_table = Table(table_data, colWidths=col_widths)
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('LINEBELOW', (0, -1), (-1, -1), 1.5, colors.HexColor('#1a365d')),
        ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f7fafc')]),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 16))

    # Notes
    if scenario.get("notes"):
        elements.append(Paragraph("Notes:", bold_style))
        elements.append(Paragraph(scenario["notes"], header_style))
        elements.append(Spacer(1, 12))

    # Footer
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"Sent from: {scenario['sender_email']}  |  Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        small_style
    ))

    doc.build(elements)
    return buf.getvalue()


@router.get("/scenarios")
async def list_scenarios():
    """List available demo scenarios for the pipeline demo.
    Also ensures demo data (overrides) exist — auto-seeds if empty.
    """
    db = get_db()
    # Auto-seed overrides if none exist (ensures demo works first time)
    override_count = await db.customer_rep_overrides.count_documents({"active": True})
    if override_count == 0:
        logger.info("[PipelineDemo] No overrides found — auto-seeding demo data")
        # Import and call seed endpoint logic inline
        from routers.sales_dashboard import seed_review_data
        await seed_review_data()

    return {
        "scenarios": [
            {
                "id": s["id"],
                "label": s["label"],
                "customer": s["customer"],
                "po_number": s["po_number"],
                "item_count": len(s["items"]),
                "total": round(sum(i["qty"] * i["price"] for i in s["items"]), 2),
                "will_auto_assign": bool(s.get("customer_no")),
            }
            for s in DEMO_SCENARIOS
        ]
    }


@router.post("/run")
async def run_pipeline_demo(scenario_id: str = Query("bragg-rush")):
    """Run the full intake pipeline on a generated PO document.
    Returns detailed step-by-step trace of every pipeline stage.
    """
    db = get_db()

    # Find scenario
    scenario = next((s for s in DEMO_SCENARIOS if s["id"] == scenario_id), None)
    if not scenario:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}")

    steps = []
    start_time = time.time()

    # ── STEP 1: Generate PDF ──
    t0 = time.time()
    pdf_bytes = _generate_po_pdf(scenario)
    filename = f"{scenario['po_number']}.pdf"
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    steps.append({
        "step": 1,
        "name": "Document Generation",
        "status": "completed",
        "duration_ms": round((time.time() - t0) * 1000),
        "details": {
            "filename": filename,
            "file_size": len(pdf_bytes),
            "file_hash": file_hash[:16] + "...",
            "customer": scenario["customer"],
            "po_number": scenario["po_number"],
            "line_items": len(scenario["items"]),
            "total_amount": round(sum(i["qty"] * i["price"] for i in scenario["items"]), 2),
        },
    })

    # ── STEP 2: Ingest via internal pipeline ──
    t0 = time.time()
    try:
        # Remove any existing doc with same hash to allow re-demos
        await db.hub_documents.delete_many({"sha256_hash": file_hash})

        from server import _internal_intake_document
        result = await _internal_intake_document(
            file_content=pdf_bytes,
            filename=filename,
            content_type="application/pdf",
            source="demo_pipeline",
            sender=scenario["sender_email"],
            subject=f"PO {scenario['po_number']} from {scenario['customer']}",
            email_id=f"demo-{uuid.uuid4().hex[:8]}",
            mailbox_category="Sales",
        )
        # Handle both return formats
        doc_id = (
            result.get("document_id")
            or (result.get("document") or {}).get("id")
            or ""
        )
        ingest_duration = round((time.time() - t0) * 1000)

        steps.append({
            "step": 2,
            "name": "Ingestion & Processing",
            "status": "completed",
            "duration_ms": ingest_duration,
            "details": {
                "document_id": doc_id,
                "source": "demo_pipeline",
                "sender": scenario["sender_email"],
                "subject": f"PO {scenario['po_number']} from {scenario['customer']}",
            },
        })
    except Exception as e:
        steps.append({
            "step": 2,
            "name": "Ingestion & Processing",
            "status": "error",
            "duration_ms": round((time.time() - t0) * 1000),
            "error": str(e),
        })
        return {"steps": steps, "total_duration_ms": round((time.time() - start_time) * 1000), "status": "error"}

    # ── STEP 3-7: Read the processed document and extract stage results ──
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        steps.append({"step": 3, "name": "Document Retrieval", "status": "error", "error": "Document not found after intake"})
        return {"steps": steps, "total_duration_ms": round((time.time() - start_time) * 1000), "status": "error"}

    # STEP 3: Classification
    ef = doc.get("extracted_fields") or {}
    steps.append({
        "step": 3,
        "name": "AI Classification & Extraction",
        "status": "completed",
        "details": {
            "document_type": doc.get("document_type", "Unknown"),
            "classification_method": doc.get("classification_method", "unknown"),
            "ai_confidence": doc.get("ai_confidence", 0),
            "extracted_customer": ef.get("customer_name") or ef.get("company_name") or "",
            "extracted_po": ef.get("po_number") or "",
            "extracted_amount": ef.get("amount") or ef.get("total_amount") or "",
            "extracted_line_count": len(ef.get("line_items") or []),
            "extracted_ship_method": ef.get("shipping_method") or ef.get("ship_method") or "",
            "extracted_buyer": ef.get("buyer_name") or ef.get("buyer") or "",
        },
    })

    # STEP 4: Vendor / Customer Resolution
    vr = doc.get("vendor_resolution") or {}
    steps.append({
        "step": 4,
        "name": "Vendor / Customer Resolution",
        "status": "completed",
        "details": {
            "vendor_canonical": doc.get("vendor_canonical") or "",
            "vendor_match_method": doc.get("vendor_match_method") or "none",
            "vendor_raw": doc.get("vendor_raw") or "",
            "customer_no_resolved": (doc.get("normalized_fields") or {}).get("bc_customer_no") or "",
            "customer_name_resolved": (doc.get("normalized_fields") or {}).get("customer_name") or doc.get("vendor_name") or "",
        },
    })

    # STEP 5: BC Validation
    vr_results = doc.get("validation_results") or {}
    steps.append({
        "step": 5,
        "name": "Business Central Validation",
        "status": "completed",
        "details": {
            "all_passed": vr_results.get("all_passed", False),
            "match_method": vr_results.get("match_method", "none"),
            "match_score": vr_results.get("match_score", 0),
            "checks_run": len(vr_results.get("checks") or []),
            "warnings": vr_results.get("warnings") or [],
            "automation_decision": doc.get("automation_decision", ""),
            "draft_candidate": doc.get("draft_candidate", False),
        },
    })

    # STEP 6: Sales Rep Auto-Assignment
    review_history = doc.get("sales_review_history") or []
    auto_assign_entry = next((h for h in review_history if h.get("action") == "auto_assigned"), None)
    triage_entry = next((h for h in review_history if h.get("action") == "routed_to_triage"), None)

    if auto_assign_entry:
        assign_details = {
            "assigned": True,
            "rep_email": auto_assign_entry.get("rep_email", ""),
            "rep_name": auto_assign_entry.get("rep_name", ""),
            "assignment_source": auto_assign_entry.get("source", ""),
            "review_status": doc.get("sales_review_status", ""),
        }
    elif triage_entry:
        assign_details = {
            "assigned": False,
            "routed_to": "triage",
            "reason": triage_entry.get("reason", ""),
            "review_status": doc.get("sales_review_status", "triage"),
        }
    else:
        assign_details = {
            "assigned": False,
            "routed_to": "not_sales_eligible" if doc.get("document_type") not in ("Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder") else "unknown",
            "document_type": doc.get("document_type", ""),
            "review_status": doc.get("sales_review_status", ""),
        }

    steps.append({
        "step": 6,
        "name": "Sales Rep Auto-Assignment",
        "status": "completed",
        "details": assign_details,
    })

    # STEP 7: Final Status
    steps.append({
        "step": 7,
        "name": "Final Status",
        "status": "completed",
        "details": {
            "document_status": doc.get("status", ""),
            "workflow_status": doc.get("workflow_status", ""),
            "sales_review_status": doc.get("sales_review_status", ""),
            "assigned_rep": doc.get("assigned_rep_name") or "Unassigned",
            "assigned_rep_email": doc.get("assigned_rep_email") or "",
            "queue_destination": "My Queue" if doc.get("assigned_rep_email") else "Triage Queue",
            "ready_for_review": doc.get("sales_review_status") in ("pending_rep_review", "triage"),
        },
    })

    total_ms = round((time.time() - start_time) * 1000)
    return {
        "status": "success",
        "document_id": doc_id,
        "scenario": scenario["label"],
        "total_duration_ms": total_ms,
        "steps": steps,
    }


# ═══════════════════════════════════════════════════════════════════
# BATCH PO DEMO — Generate a multi-page PO PDF and show splitting
# ═══════════════════════════════════════════════════════════════════

BATCH_PO_DATA = [
    {
        "po": "61312", "bc_so": "112115",
        "customer": "Giovanni Food Company., Inc.", "customer_no": "C-10250",
        "contact": "Michelle Cavalier",
        "salesperson_code": "NHANN", "backup_isr": "JWITT",
        "industry_code": "FOOD", "location_code": "00",
        "fob": "Auburn", "from_state": "TX", "to_state": "NY",
        "order_date": "3/18/2026", "requested_delivery": "4/2/2026",
        "shipment_date": "4/1/2026", "due_date": "5/17/2026",
        "ship_to": "Giovanni Food Company., Inc.\n8800 Sixty Road\nBaldwinsville, NY 13027",
        "ship_to_phone": "315-457-2373",
        "status": "Open",
        "items": [
            {"no": "C-9874-10001833", "desc": "24oz, 63-2030, Lug, Flint, Glass, Pasta, Jar, FH", "qty": 62062, "uom": "M", "unit_cost": 222.61, "price": 234.74, "vendor": "OWENS"},
        ],
        "subtotal": 14568.43,
    },
    {
        "po": "61313", "bc_so": "112116",
        "customer": "Giovanni Food Company., Inc.", "customer_no": "C-10250",
        "contact": "Michelle Cavalier",
        "salesperson_code": "NHANN", "backup_isr": "JWITT",
        "industry_code": "FOOD", "location_code": "00",
        "fob": "Auburn", "from_state": "TX", "to_state": "NY",
        "order_date": "3/18/2026", "requested_delivery": "4/2/2026",
        "shipment_date": "4/1/2026", "due_date": "5/17/2026",
        "ship_to": "Giovanni Food Company., Inc.\n8800 Sixty Road\nBaldwinsville, NY 13027",
        "ship_to_phone": "315-457-2373",
        "status": "Open",
        "items": [
            {"no": "C-9874-10001290", "desc": "16oz, 63-2030, Lug, Flint, Glass, Pasta, Jar, FH", "qty": 43200, "uom": "M", "unit_cost": 178.92, "price": 189.20, "vendor": "OWENS"},
        ],
        "subtotal": 8173.44,
    },
    {
        "po": "61314", "bc_so": "112117",
        "customer": "Giovanni Food Company., Inc.", "customer_no": "C-10250",
        "contact": "Michelle Cavalier",
        "salesperson_code": "NHANN", "backup_isr": "JWITT",
        "industry_code": "FOOD", "location_code": "00",
        "fob": "Auburn", "from_state": "TX", "to_state": "NY",
        "order_date": "3/18/2026", "requested_delivery": "4/2/2026",
        "shipment_date": "4/1/2026", "due_date": "5/17/2026",
        "ship_to": "Giovanni Food Company., Inc.\n8800 Sixty Road\nBaldwinsville, NY 13027",
        "ship_to_phone": "315-457-2373",
        "status": "Open",
        "items": [
            {"no": "C-9874-10001840", "desc": "12oz, 63-2030, Lug, Flint, Glass, Pasta, Jar, FH", "qty": 80640, "uom": "M", "unit_cost": 134.40, "price": 142.25, "vendor": "OWENS"},
        ],
        "subtotal": 11471.10,
    },
    {
        "po": "61315", "bc_so": "112118",
        "customer": "Giovanni Food Company., Inc.", "customer_no": "C-10250",
        "contact": "Michelle Cavalier",
        "salesperson_code": "NHANN", "backup_isr": "JWITT",
        "industry_code": "FOOD", "location_code": "00",
        "fob": "Auburn", "from_state": "OH", "to_state": "NY",
        "order_date": "3/18/2026", "requested_delivery": "4/2/2026",
        "shipment_date": "4/1/2026", "due_date": "5/17/2026",
        "ship_to": "Giovanni Food Company., Inc.\n8800 Sixty Road\nBaldwinsville, NY 13027",
        "ship_to_phone": "315-457-2373",
        "status": "Open",
        "items": [
            {"no": "C-63-2030-GOLD", "desc": "Metal Cap 63mm Gold Lug", "qty": 185000, "uom": "M", "unit_cost": 45.82, "price": 48.50, "vendor": "SILGAN"},
        ],
        "subtotal": 8972.50,
    },
    {
        "po": "61316", "bc_so": "112119",
        "customer": "Giovanni Food Company., Inc.", "customer_no": "C-10250",
        "contact": "Michelle Cavalier",
        "salesperson_code": "NHANN", "backup_isr": "JWITT",
        "industry_code": "FOOD", "location_code": "00",
        "fob": "GPI-York", "from_state": "PA", "to_state": "NY",
        "order_date": "3/18/2026", "requested_delivery": "4/2/2026",
        "shipment_date": "4/1/2026", "due_date": "5/17/2026",
        "ship_to": "Giovanni Food Company., Inc.\n8800 Sixty Road\nBaldwinsville, NY 13027",
        "ship_to_phone": "315-457-2373",
        "status": "Open",
        "items": [
            {"no": "L-GIOV-MAR24", "desc": "Label, Marinara 24oz, 4-Color", "qty": 65000, "uom": "M", "unit_cost": 59.85, "price": 63.00, "vendor": "YORK-PRINT"},
        ],
        "subtotal": 4095.00,
    },
]


def _generate_batch_po_pdf(po_data: list) -> bytes:
    """Generate a multi-page PDF with one PO per page — realistic BC-style layout."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('POTitle', parent=styles['Title'], fontSize=16, spaceAfter=4)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=9, spaceAfter=2)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Bold')
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, textColor=colors.grey)
    comment_style = ParagraphStyle('Comment', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#555555'), leftIndent=20)

    for i, po in enumerate(po_data):
        if i > 0:
            elements.append(PageBreak())

        elements.append(Paragraph("PURCHASE ORDER", title_style))
        elements.append(Spacer(1, 4))

        # Header info — matches BC layout
        info_data = [
            ["PO Number:", po["po"], "BC Sales Order:", po.get("bc_so", "")],
            ["Customer:", po["customer"], "Order Date:", po.get("order_date", "")],
            ["Customer No:", po.get("customer_no", ""), "Req. Delivery:", po.get("requested_delivery", "")],
            ["Contact:", po.get("contact", ""), "Shipment Date:", po.get("shipment_date", "")],
            ["Salesperson:", po.get("salesperson_code", ""), "Due Date:", po.get("due_date", "")],
            ["FOB:", po.get("fob", ""), "Status:", po.get("status", "")],
        ]
        info_table = Table(info_data, colWidths=[80, 200, 90, 170])
        info_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 8))

        # Ship to
        elements.append(Paragraph("Ship To:", bold_style))
        for line in po.get("ship_to", "").split("\n"):
            elements.append(Paragraph(line, header_style))
        if po.get("ship_to_phone"):
            elements.append(Paragraph(f"Phone: {po['ship_to_phone']}", header_style))
        elements.append(Spacer(1, 10))

        # Line items
        headers = ["Line", "Item No.", "Description", "Qty", "UOM", "Unit Price", "Amount"]
        table_data = [headers]
        for li, item in enumerate(po.get("items", []), 1):
            line_amount = round(item["qty"] * item["price"] / (1000 if item.get("uom") == "M" else 1), 2) if item["price"] else 0
            qty_display = f"{item['qty']:,}" if item.get("uom") != "M" else f"{item['qty']/1000:,.3f}"
            table_data.append([
                str(li), item.get("no", ""), item["desc"],
                qty_display, item.get("uom", "EA"),
                f"${item['price']:,.2f}" if item["price"] else "",
                f"${line_amount:,.2f}" if line_amount else "",
            ])

        subtotal = po.get("subtotal", sum(
            round(it["qty"] * it["price"] / (1000 if it.get("uom") == "M" else 1), 2)
            for it in po.get("items", []) if it["price"]
        ))
        table_data.append(["", "", "", "", "", "TOTAL:", f"${subtotal:,.2f}"])

        line_table = Table(table_data, colWidths=[30, 90, 165, 55, 30, 60, 65])
        line_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('LINEBELOW', (0, -1), (-1, -1), 1.5, colors.HexColor('#1a365d')),
            ('FONTNAME', (5, -1), (-1, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f7fafc')]),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 8))

        # Comments from line items
        for item in po.get("items", []):
            for comment in item.get("comments", []):
                elements.append(Paragraph(f"• {comment}", comment_style))

        elements.append(Spacer(1, 12))
        elements.append(Paragraph(
            f"Page {i + 1} of {len(po_data)}  |  Batch POs {po_data[0]['po']} – {po_data[-1]['po']}  |  "
            f"ISR: {po.get('salesperson_code','')}  |  Industry: {po.get('industry_code','')}",
            small_style,
        ))

    doc.build(elements)
    return buf.getvalue()


@router.post("/run-batch")
async def run_batch_demo(background_tasks: BackgroundTasks):
    """Demo: Generate a multi-page batch PO PDF, ingest it, then split each page.
    Returns immediately with job_id. Poll /demo/batch-status/{job_id} for results.
    """
    db = get_db()
    job_id = uuid.uuid4().hex[:12]

    # Store initial status in DB
    await db.demo_batch_jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "job_id": job_id,
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_pages": len(BATCH_PO_DATA),
            "steps": [],
            "children": [],
        }},
        upsert=True,
    )

    background_tasks.add_task(_run_batch_demo_bg, db, job_id)

    return {
        "status": "started",
        "job_id": job_id,
        "total_pages": len(BATCH_PO_DATA),
        "message": f"Batch split started — {len(BATCH_PO_DATA)} pages will be processed. Poll /demo/batch-status/{job_id}",
    }


@router.get("/batch-status/{job_id}")
async def batch_status(job_id: str):
    """Poll for batch demo results."""
    db = get_db()
    job = await db.demo_batch_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_batch_demo_bg(db, job_id: str):
    """Background: generate batch PDF, split pages, save each as a document, auto-assign."""
    start_time = time.time()
    steps = []

    async def _update_job(**kwargs):
        await db.demo_batch_jobs.update_one({"job_id": job_id}, {"$set": kwargs})

    try:
        # Step 1: Generate multi-page PDF
        t0 = time.time()
        pdf_bytes = _generate_batch_po_pdf(BATCH_PO_DATA)
        filename = f"Purchase_Orders_{BATCH_PO_DATA[0]['po']}-{BATCH_PO_DATA[-1]['po']}.pdf"
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)

        steps.append({
            "step": 1, "name": "Batch PO Generation", "status": "completed",
            "duration_ms": round((time.time() - t0) * 1000),
            "details": {
                "filename": filename, "pages": page_count,
                "po_range": f"{BATCH_PO_DATA[0]['po']} – {BATCH_PO_DATA[-1]['po']}",
                "customer": BATCH_PO_DATA[0]["customer"],
                "total_value": round(sum(p.get("subtotal", 0) for p in BATCH_PO_DATA), 2),
            },
        })
        await _update_job(steps=steps, status="ingesting")

        # Step 2: Store parent record
        t0 = time.time()
        await db.hub_documents.delete_many({"sha256_hash": file_hash})
        await db.hub_documents.delete_many({"batch_source_filename": filename})

        parent_doc_id = f"batch-parent-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.insert_one({
            "id": parent_doc_id,
            "filename": filename,
            "document_type": "PurchaseOrder",
            "status": "batch_parent",
            "source": "batch_demo",
            "sender": "purchasing@giovannifoods.com",
            "subject": f"Batch POs {BATCH_PO_DATA[0]['po']}-{BATCH_PO_DATA[-1]['po']} from Giovanni Food Co.",
            "sha256_hash": file_hash,
            "file_size": len(pdf_bytes),
            "batch_detected": True,
            "batch_page_count": page_count,
            "ai_confidence": 1.0,
            "classification_method": "batch_demo",
            "created_utc": now_iso,
            "updated_utc": now_iso,
        })
        steps.append({
            "step": 2, "name": "Parent Document Stored", "status": "completed",
            "duration_ms": round((time.time() - t0) * 1000),
            "details": {"parent_doc_id": parent_doc_id, "filename": filename, "pages_detected": page_count},
        })
        await _update_job(steps=steps, status="detecting", parent_doc_id=parent_doc_id)

        # Step 3: Batch detection
        steps.append({
            "step": 3, "name": "Batch PO Detection", "status": "completed",
            "details": {
                "batch_detected": True,
                "batch_page_count": page_count,
                "document_type": "PurchaseOrder",
                "classification_confidence": 1.0,
            },
        })
        await _update_job(steps=steps, status="splitting")

        # Step 4: Split pages → save each as a real document with file on disk
        t0 = time.time()
        import base64 as b64mod
        from pathlib import Path
        from services.batch_po_splitter import split_pdf_pages
        from services.sales_auto_assign import auto_assign_sales_rep

        UPLOAD_DIR = Path("/app/backend/uploads")
        UPLOAD_DIR.mkdir(exist_ok=True)
        pages = split_pdf_pages(pdf_bytes)

        # Also save parent PDF to disk
        parent_file_path = UPLOAD_DIR / parent_doc_id
        parent_file_path.write_bytes(pdf_bytes)
        parent_b64 = b64mod.b64encode(pdf_bytes).decode("ascii")
        await db.hub_documents.update_one(
            {"id": parent_doc_id},
            {"$set": {
                "content_type": "application/pdf",
                "file_name": filename,
                "file_content_b64": parent_b64,
            }},
        )

        children_summary = []
        child_ids = []
        for i, page_info in enumerate(pages):
            po = BATCH_PO_DATA[i] if i < len(BATCH_PO_DATA) else BATCH_PO_DATA[-1]
            page_num = page_info["page_num"]
            child_id = f"batch-child-{uuid.uuid4().hex[:12]}"
            child_filename = f"{filename.rsplit('.', 1)[0]}_p{page_num}.pdf"
            subtotal = po.get("subtotal", round(po.get("primary_qty", 0) * po.get("primary_price", 0), 2))

            # Save PDF to disk
            child_file_path = UPLOAD_DIR / child_id
            child_file_path.write_bytes(page_info["pdf_bytes"])
            child_b64 = b64mod.b64encode(page_info["pdf_bytes"]).decode("ascii")

            # Build rich extracted_fields from real BC data
            line_items = []
            for item in po.get("items", []):
                # Convert to BC UOM: if UOM is "M" (per 1000), qty is qty/1000
                raw_qty = item["qty"]
                uom = item.get("uom", "EA")
                bc_qty = raw_qty / 1000 if uom == "M" else raw_qty
                li = {"item_no": item.get("no", ""), "description": item["desc"],
                      "quantity": bc_qty, "uom": uom,
                      "unit_price": item["price"]}
                if item.get("vendor"):
                    li["vendor"] = item["vendor"]
                if item.get("comments"):
                    li["comments"] = item["comments"]
                line_items.append(li)

            child_doc = {
                "id": child_id,
                "file_name": child_filename,
                "filename": child_filename,
                "document_type": "PurchaseOrder",
                "status": "processed",
                "source": "batch_split_demo",
                "content_type": "application/pdf",
                "file_content_b64": child_b64,
                "email_sender": "purchasing@giovannifoods.com",
                "sender": "purchasing@giovannifoods.com",
                "email_subject": f"PO {po['po']} — {po['customer']}",
                "sha256_hash": page_info["page_hash"],
                "file_size": page_info["page_size"],
                "ai_confidence": 0.97,
                "classification_method": "batch_split",
                "batch_parent_id": parent_doc_id,
                "batch_page_num": page_num,
                "batch_total_pages": len(pages),
                "batch_source_filename": filename,
                "created_utc": now_iso,
                "updated_utc": now_iso,
                "extracted_fields": {
                    "po_number": po["po"],
                    "bc_sales_order": po.get("bc_so", ""),
                    "customer_name": po["customer"],
                    "customer_no": po.get("customer_no", ""),
                    "contact": po.get("contact", ""),
                    "salesperson_code": po.get("salesperson_code", ""),
                    "backup_isr": po.get("backup_isr", ""),
                    "industry_code": po.get("industry_code", ""),
                    "order_date": po.get("order_date", ""),
                    "requested_delivery": po.get("requested_delivery", ""),
                    "shipment_date": po.get("shipment_date", ""),
                    "due_date": po.get("due_date", ""),
                    "fob": po.get("fob", ""),
                    "from_state": po.get("from_state", ""),
                    "to_state": po.get("to_state", ""),
                    "location_code": po.get("location_code", ""),
                    "line_items": line_items,
                    "amount": subtotal,
                    "total_amount": subtotal,
                    "ship_to_name": po["customer"],
                    "ship_to_address": po.get("ship_to", "").replace("\n", ", "),
                    "ship_to_phone": po.get("ship_to_phone", ""),
                },
                "normalized_fields": {
                    "customer_name": po["customer"],
                    "bc_customer_no": po.get("customer_no", ""),
                    "po_number": po["po"],
                    "bc_sales_order_no": po.get("bc_so", ""),
                },
                "vendor_canonical": po["customer"],
                "vendor_name": po["customer"],
                "sharepoint_drive_id": None,
                "sharepoint_item_id": None,
                "category": "Sales",
                "workflow_status": "processed",
                "automation_decision": "assisted",
            }

            await db.hub_documents.delete_many({"sha256_hash": page_info["page_hash"]})
            await db.hub_documents.insert_one(child_doc)
            child_ids.append(child_id)

            # Add workflow events so document detail page shows history
            correlation_id = str(uuid.uuid4())
            primary_item_desc = po.get("items", [{}])[0].get("desc", po.get("primary_item", ""))
            events = [
                {"event_type": "intake.received", "stage": "intake", "detail": f"Split from batch {filename} (page {page_num}/{len(pages)})"},
                {"event_type": "classification.completed", "stage": "classification", "detail": f"PurchaseOrder (batch_split, 97% confidence)"},
                {"event_type": "extraction.completed", "stage": "extraction", "detail": f"PO {po['po']} → BC SO {po.get('bc_so','')}, {po['customer']}, ${subtotal:,.2f}",
                 "extra_payload": {"completeness_score": 1.0, "fields_extracted": len([k for k in ["po_number", "customer_name", "amount", "line_items", "ship_to_address", "contact"] if True])}},
                {"event_type": "vendor.resolved", "stage": "vendor_match", "detail": f"Customer: {po['customer']} ({po.get('customer_no','')})"},
                {"event_type": "bc.validation.completed", "stage": "bc_validation", "detail": f"Matched BC SO {po.get('bc_so','')}, ISR: {po.get('salesperson_code','')}, Status: {po.get('status','')}"},
            ]
            for evt in events:
                payload = {"detail": evt["detail"]}
                if "extra_payload" in evt:
                    payload.update(evt["extra_payload"])
                await db.workflow_events.insert_one({
                    "event_id": str(uuid.uuid4()),
                    "document_id": child_id,
                    "correlation_id": correlation_id,
                    "event_type": evt["event_type"],
                    "status": "completed",
                    "source_service": "batch_split_demo",
                    "timestamp": now_iso,
                    "payload": payload,
                    "payload_summary": evt["detail"],
                })

            # Auto-assign sales rep
            assign_result = await auto_assign_sales_rep(db, child_id, child_doc)

            # Re-read for assignment results
            saved = await db.hub_documents.find_one({"id": child_id}, {"_id": 0})
            rep_name = (saved or {}).get("assigned_rep_name", "Unassigned")
            rep_email = (saved or {}).get("assigned_rep_email", "")
            review_status = (saved or {}).get("sales_review_status", "")

            children_summary.append({
                "page": page_num,
                "doc_id": child_id[:12] + "...",
                "type": "PurchaseOrder",
                "po_number": po["po"],
                "bc_so": po.get("bc_so", ""),
                "customer": po["customer"],
                "amount": subtotal,
                "confidence": 0.97,
                "assigned_rep": rep_name,
                "review_status": review_status,
                "queue": "My Queue" if rep_email else "Triage",
            })

        # Update parent with children links
        await db.hub_documents.update_one(
            {"id": parent_doc_id},
            {"$set": {
                "batch_split": True,
                "batch_split_at": now_iso,
                "batch_children_count": len(children_summary),
                "batch_children_ids": child_ids,
            }},
        )

        steps.append({
            "step": 4, "name": "Page Split & Document Creation", "status": "completed",
            "duration_ms": round((time.time() - t0) * 1000),
            "details": {
                "pages_split": len(pages),
                "children_created": len(children_summary),
                "errors": 0,
            },
        })
        await _update_job(steps=steps, status="summarizing")

        # Seed learned dunnage patterns for the demo
        # (In production, these would be learned from historical BC orders)
        # NOTE: qty_ratio values are calibrated for M UOM (qty/1000) since BC quantities use M
        _GLASS_JAR_DUNNAGE = [
            {"line_type": "Comment", "item_no": "", "description": "2,821/plt, 22 plt/TL, 62,062/TL",
             "qty_ratio": None, "fixed_qty": None, "unit_price": 0, "occurrences": 15, "frequency": 1.0},
            {"line_type": "Comment", "item_no": "", "description": '56x44x89", 2,199 lbs/plt, 14 ts/plt',
             "qty_ratio": None, "fixed_qty": None, "unit_price": 0, "occurrences": 15, "frequency": 1.0},
            {"line_type": "Item", "item_no": "OIPALLET", "description": "OI Pallet - RETURN REQUIRED",
             "qty_ratio": 0.3546, "fixed_qty": None, "unit_price": 0, "occurrences": 15, "frequency": 1.0},
            {"line_type": "Item", "item_no": "OITIERSHEET", "description": "OI Tier Sheet - RETURN REQUIRED",
             "qty_ratio": 4.963, "fixed_qty": None, "unit_price": 0, "occurrences": 15, "frequency": 1.0},
            {"line_type": "Item", "item_no": "OITOPFRAME", "description": "OI Top Frame - RETURN REQUIRED",
             "qty_ratio": 0.3546, "fixed_qty": None, "unit_price": 0, "occurrences": 15, "frequency": 1.0},
        ]
        for po_data_item in BATCH_PO_DATA:
            for item in po_data_item.get("items", []):
                await db.order_line_patterns.update_one(
                    {"customer_no": "C-10250", "trigger_item_no": item["no"]},
                    {"$set": {
                        "customer_no": "C-10250",
                        "trigger_item_no": item["no"],
                        "trigger_item_pattern": f"{item['no'].split('-')[0]}-{item['no'].split('-')[1]}-*" if '-' in item["no"] else f"{item['no'][:4]}*",
                        "associated_lines": _GLASS_JAR_DUNNAGE if item["no"].startswith("C-9874") else [],
                        "total_orders_analyzed": 15,
                        "confidence": 1.0,
                        "last_updated": now_iso,
                    }},
                    upsert=True,
                )

        # Seed customer-level pattern: Energy Surcharge
        # (In production, learn_from_bc_posted_orders() would discover this from BC history)
        _ENERGY_SURCHARGE = {
            "customer_no": "C-10250",
            "trigger_item_no": "*",
            "trigger_item_pattern": "*",
            "associated_lines": [
                {
                    "line_type": "Item",
                    "item_no": "ENERGY",
                    "description": "Energy Surcharge",
                    "qty_ratio": None,
                    "fixed_qty": 1,
                    "unit_price": 497.36,
                    "occurrences": 8,
                    "frequency": 0.80,
                },
            ],
            "total_orders_analyzed": 10,
            "confidence": 0.80,
            "last_updated": now_iso,
        }
        await db.order_line_patterns.update_one(
            {"customer_no": "C-10250", "trigger_item_no": "*"},
            {"$set": _ENERGY_SURCHARGE},
            upsert=True,
        )

        # Step 5: Summary
        steps.append({
            "step": 5, "name": "Child Documents Summary", "status": "completed",
            "details": {
                "children": children_summary,
                "assigned_count": sum(1 for c in children_summary if c["queue"] == "My Queue"),
                "triage_count": sum(1 for c in children_summary if c["queue"] == "Triage"),
            },
        })

        total_ms = round((time.time() - start_time) * 1000)
        await _update_job(
            steps=steps, status="completed",
            parent_doc_id=parent_doc_id,
            total_pages=page_count,
            children_created=len(children_summary),
            children=children_summary,
            total_duration_ms=total_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("[BatchDemo] Complete: %d pages → %d children in %dms", page_count, len(children_summary), total_ms)

    except Exception as e:
        logger.error("[BatchDemo] Failed: %s", str(e))
        await _update_job(status="error", error=str(e), steps=steps)
