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
    {"po": "PO-61312", "customer": "Giovanni Food Co., Inc.", "item": "Glass, 24oz, Bulk, 2821/Plt", "qty": 62062, "price": 0.23474},
    {"po": "PO-61313", "customer": "Giovanni Food Co., Inc.", "item": "Glass, 16oz, Bulk, 3600/Plt", "qty": 43200, "price": 0.18920},
    {"po": "PO-61314", "customer": "Giovanni Food Co., Inc.", "item": "Glass, 12oz, Flint, 4032/Plt", "qty": 80640, "price": 0.14225},
    {"po": "PO-61315", "customer": "Giovanni Food Co., Inc.", "item": "Metal Cap 63mm Gold Lug", "qty": 185000, "price": 0.04850},
    {"po": "PO-61316", "customer": "Giovanni Food Co., Inc.", "item": "Label, Marinara 24oz, 4-Color", "qty": 65000, "price": 0.06300},
]


def _generate_batch_po_pdf(po_data: list) -> bytes:
    """Generate a multi-page PDF with one PO per page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('POTitle', parent=styles['Title'], fontSize=18, spaceAfter=6)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=10, spaceAfter=2)
    bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold')
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.grey)

    now = datetime.now(timezone.utc)

    for i, po in enumerate(po_data):
        if i > 0:
            elements.append(PageBreak())

        total = round(po["qty"] * po["price"], 2)

        elements.append(Paragraph("PURCHASE ORDER", title_style))
        elements.append(Spacer(1, 4))

        info_data = [
            ["PO Number:", po["po"], "Date:", now.strftime("%m/%d/%Y")],
            ["Customer:", po["customer"], "Due Date:", (now + timedelta(days=30)).strftime("%m/%d/%Y")],
            ["Ship To:", "Giovanni Foods, 8800 Sixty Road, Baldwinsville, NY 13027", "", ""],
        ]
        info_table = Table(info_data, colWidths=[80, 220, 80, 160])
        info_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 16))

        # Line item table
        headers = ["Line", "Description", "Qty", "Unit Price", "Amount"]
        table_data = [headers]
        table_data.append(["1", po["item"], f"{po['qty']:,}", f"${po['price']:.5f}", f"${total:,.2f}"])
        table_data.append(["", "", "", "TOTAL:", f"${total:,.2f}"])

        line_table = Table(table_data, colWidths=[35, 240, 70, 70, 80])
        line_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('LINEBELOW', (0, -1), (-1, -1), 1.5, colors.HexColor('#1a365d')),
            ('FONTNAME', (3, -1), (-1, -1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 16))

        elements.append(Paragraph(
            f"Page {i + 1} of {len(po_data)}  |  Batch POs {po_data[0]['po']} – {po_data[-1]['po']}",
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
                "total_value": round(sum(p["qty"] * p["price"] for p in BATCH_PO_DATA), 2),
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

        # Step 4: Split pages → save each as its own document (no AI needed — fields from BATCH_PO_DATA)
        t0 = time.time()
        from services.batch_po_splitter import split_pdf_pages
        from services.sales_auto_assign import auto_assign_sales_rep
        pages = split_pdf_pages(pdf_bytes)

        children_summary = []
        child_ids = []
        for i, page_info in enumerate(pages):
            po = BATCH_PO_DATA[i] if i < len(BATCH_PO_DATA) else BATCH_PO_DATA[-1]
            page_num = page_info["page_num"]
            child_id = f"batch-child-{uuid.uuid4().hex[:12]}"
            child_filename = f"{filename.rsplit('.', 1)[0]}_p{page_num}.pdf"
            total_amount = round(po["qty"] * po["price"], 2)

            child_doc = {
                "id": child_id,
                "filename": child_filename,
                "document_type": "PurchaseOrder",
                "status": "processed",
                "source": "batch_split_demo",
                "sender": "purchasing@giovannifoods.com",
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
                    "customer_name": po["customer"],
                    "line_items": [{"description": po["item"], "quantity": po["qty"], "unit_price": po["price"]}],
                    "amount": total_amount,
                    "total_amount": total_amount,
                    "ship_to_name": "Giovanni Foods",
                    "ship_to_address": "8800 Sixty Road, Baldwinsville, NY 13027",
                },
                "normalized_fields": {
                    "customer_name": po["customer"],
                    "po_number": po["po"],
                },
                "vendor_canonical": po["customer"],
                "vendor_name": po["customer"],
            }

            await db.hub_documents.delete_many({"sha256_hash": page_info["page_hash"]})
            await db.hub_documents.insert_one(child_doc)
            child_ids.append(child_id)

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
                "customer": po["customer"],
                "amount": total_amount,
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
