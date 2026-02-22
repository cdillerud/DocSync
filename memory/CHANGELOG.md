# GPI Document Hub - Changelog

## February 22, 2026

### AI-Assisted Document Classification
- **NEW:** Deterministic-first classification pipeline
  - Priority order: Zetadocs set codes → Square9 workflows → Mailbox category → Legacy AI extraction → AI fallback
- **NEW:** AI fallback classifier using EMERGENT_LLM_KEY (GPT-5.2)
  - Only invoked when deterministic rules return OTHER
  - Confidence threshold of 0.8 for accepting AI classification
- **NEW:** AI classification audit trail (`ai_classification` field)
  - Records: proposed_doc_type, confidence, model_name, timestamp
  - Saved only when AI classifier is invoked
- **NEW:** Classification method tracking (`classification_method` field)
  - Examples: `legacy_ai:AP_Invoice`, `ai:gpt-5.2:0.91`, `zetadocs:ZD00015`, `default`
- **NEW:** AI classifier service at `/app/backend/services/ai_classifier.py`
- **TESTS:** 29 automated tests (16 unit + 13 integration)

### Document Type Dashboard
- Backend API: GET /api/dashboard/document-types
- CSV Export: GET /api/dashboard/document-types/export
- Frontend page at `/doc-types` with filters and metrics

### Multi-Document Type Classification
- 10 document types: AP_INVOICE, SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER
- Type-aware workflow engine with different state machines per doc_type
- Generic queue APIs for all doc_types

### AP Invoice Workflow Engine
- Pure state machine implementation
- 12 workflow statuses with full history tracking
- Queue and mutation APIs for exception handling
- Frontend workflow page with action dialogs

## February 21, 2026

### Email Ingestion Infrastructure
- Microsoft Graph API integration for email polling
- Dynamic mailbox source configuration via UI
- Attachment extraction and deduplication
- Read-only polling (doesn't change email status)

### Core Platform
- FastAPI backend with MongoDB
- React frontend with Shadcn/UI
- SharePoint integration for document storage
- JWT authentication (mock for POC)
