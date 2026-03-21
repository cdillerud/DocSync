export const APP_VERSION = "1.6.0";

export const CHANGELOG = [
  {
    version: "1.6.0",
    date: "2026-03-21",
    title: "Bake-Off: GPI Hub vs Square 9 Comparison",
    changes: [
      { type: "feature", text: "Bake-Off workspace for side-by-side document processing comparison" },
      { type: "feature", text: "Run management: create, complete, archive bake-off runs" },
      { type: "feature", text: "Per-document scoring with truth values, GPI auto-population, and Square 9 manual entry" },
      { type: "feature", text: "Auto-scoring with normalization (case-insensitive, PO prefix removal, amount tolerance)" },
      { type: "feature", text: "Results dashboard with KPI comparison, breakdowns, and key insights" },
      { type: "feature", text: "Excel export with Documents + Summary sheets" },
      { type: "feature", text: "CSV import for bulk document seeding" },
    ],
  },
  {
    version: "1.5.0",
    date: "2026-03-21",
    title: "Frontend Consolidation & Platform Hardening",
    changes: [
      { type: "feature", text: "Unified Queue Page with workflow category filters (AP, Sales, Operations) and date range picker" },
      { type: "feature", text: "Vendor Intelligence & Stable Vendors moved into Settings hub" },
      { type: "feature", text: "Document Types dashboard tab on main Dashboard" },
      { type: "improvement", text: "Navigation consolidated from 8 to 7 items for cleaner UX" },
      { type: "improvement", text: "Deleted 9 orphaned page files reducing frontend complexity" },
      { type: "feature", text: "App versioning system with changelog" },
    ],
  },
  {
    version: "1.4.0",
    date: "2026-03-20",
    title: "BC Shipments, Rep Assignment & Server Extraction",
    changes: [
      { type: "feature", text: "BC Sales Order shipment events synced into Inventory Ledger as outbound movements" },
      { type: "feature", text: "Customer & salesperson sync from Business Central with rep assignment service" },
      { type: "improvement", text: "Extracted 600+ lines from server.py into dedicated domain services" },
    ],
  },
  {
    version: "1.3.0",
    date: "2026-03-19",
    title: "SO Routing & Warehouse Notifications",
    changes: [
      { type: "feature", text: "Drop-Ship vs Warehouse SO type routing with automatic field mapping" },
      { type: "feature", text: "Automated warehouse receiving notifications when WH SO is booked" },
      { type: "feature", text: "SO confirmation emails to customers" },
    ],
  },
  {
    version: "1.2.0",
    date: "2026-03-18",
    title: "BC Catalog Sync & Square9 Decommission",
    changes: [
      { type: "feature", text: "BC catalog sync scheduling with health monitoring" },
      { type: "feature", text: "Square9 decommission tooling and cutover dashboard" },
      { type: "improvement", text: "Freight GL routing extensions (storage handling, international dropship)" },
    ],
  },
  {
    version: "1.1.0",
    date: "2026-03-17",
    title: "AP Automation & AI Classification",
    changes: [
      { type: "feature", text: "Auto-post AP invoices for stable vendors" },
      { type: "feature", text: "Azure OpenAI fallback classifier when Gemini confidence is low" },
      { type: "fix", text: "FastAPI dependency injection cleanup" },
    ],
  },
  {
    version: "1.0.0",
    date: "2026-03-16",
    title: "Initial Release",
    changes: [
      { type: "feature", text: "Document classification and workflow pipeline" },
      { type: "feature", text: "PO extraction from multiple document fields" },
      { type: "feature", text: "Business Central and SharePoint integration" },
      { type: "feature", text: "Vendor matching with multi-source intelligence" },
    ],
  },
];
