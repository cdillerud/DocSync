# Spiro CRM Integration

## Overview

The Spiro integration adds CRM context to GPI Document Hub's document validation pipeline. It syncs data from Spiro (companies, contacts, opportunities) to local MongoDB collections and generates `SpiroContext` for each document to improve AI classification and validation accuracy.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GPI Document Hub                         │
├─────────────────────────────────────────────────────────────────┤
│  Document Validation Pipeline                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ BC Context  │  │ Alias Layer │  │Spiro Context│ ← NEW       │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│         │               │                │                      │
│         └───────────────┴────────────────┘                      │
│                         │                                       │
│                   ┌─────▼─────┐                                 │
│                   │ AI Model  │                                 │
│                   └───────────┘                                 │
├─────────────────────────────────────────────────────────────────┤
│  Spiro Integration Layer (services/spiro/)                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ SpiroClient    │  │ SpiroSync      │  │ SpiroContext   │    │
│  │ (OAuth + API)  │  │ (Data Sync)    │  │ (Matching)     │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  MongoDB Collections                                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │spiro_contacts  │  │spiro_companies │  │spiro_opportun..│    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   Spiro API     │
                    │ api.spiro.ai    │
                    └─────────────────┘
```

## Configuration

### Environment Variables

Add these to your `backend/.env` file:

```bash
# Feature flags
SPIRO_INTEGRATION_ENABLED=true    # Master switch for Spiro integration
SPIRO_CONTEXT_ENABLED=true        # Enable SpiroContext in validation

# OAuth credentials (REQUIRED)
SPIRO_CLIENT_ID=your_client_id
SPIRO_CLIENT_SECRET=your_client_secret
SPIRO_REDIRECT_URI=https://your-domain.com/api/spiro/callback

# Optional: Token storage location (defaults to /app/backend/data/spiro_token.json)
SPIRO_TOKEN_FILE=/app/backend/data/spiro_token.json
```

### Initial OAuth Setup

1. **Get authorization URL:**
   ```bash
   curl https://your-domain.com/api/spiro/auth-url
   ```

2. **Visit the URL in browser** and authorize the app

3. **Exchange the code** (Spiro redirects to callback with `?code=...`):
   ```bash
   curl -X POST https://your-domain.com/api/spiro/callback \
     -H "Content-Type: application/json" \
     -d '{"code": "authorization_code_from_redirect"}'
   ```

4. **Verify configuration:**
   ```bash
   curl https://your-domain.com/api/spiro/status
   ```

## Data Sync

### Manual Sync

```bash
# Sync all data
curl -X POST https://your-domain.com/api/spiro/sync/all

# Sync only contacts
curl -X POST https://your-domain.com/api/spiro/sync/contacts

# Force full sync (ignore last sync timestamp)
curl -X POST https://your-domain.com/api/spiro/sync \
  -H "Content-Type: application/json" \
  -d '{"force_full": true}'
```

### Sync Status

```bash
curl https://your-domain.com/api/spiro/status
```

Response:
```json
{
  "enabled": true,
  "configured": true,
  "has_token": true,
  "sync_status": {
    "collection_counts": {
      "contacts": 1500,
      "companies": 450,
      "opportunities": 120
    },
    "sync_statuses": {
      "contacts": {
        "last_sync_success": "2026-02-27T10:00:00Z",
        "records_synced": 1500
      }
    }
  }
}
```

### Scheduled Sync

To add scheduled sync, register the sync function with APScheduler in `server.py`:

```python
from services.spiro import sync_all_spiro_data

# Add to scheduler setup
scheduler.add_job(
    lambda: asyncio.create_task(sync_all_spiro_data()),
    'interval',
    hours=6,  # Sync every 6 hours
    id='spiro_sync',
    name='Spiro Data Sync'
)
```

## SpiroContext

### What it Contains

For each document, SpiroContext provides:

```json
{
  "matched_companies": [
    {
      "spiro_id": "999",
      "name": "ACME Corporation",
      "match_score": 0.95,
      "match_reasons": ["name_similarity:0.95", "email_domain_match"],
      "assigned_isr": "Joey Smith",
      "assigned_osr": "Sarah Johnson"
    }
  ],
  "matched_contacts": [...],
  "matched_opportunities": [...],
  "confidence_signals": {
    "has_company_match": true,
    "best_company_score": 0.95,
    "email_domain_match": true,
    "matched_isr": "Joey Smith",
    "matched_osr": "Sarah Johnson"
  }
}
```

### Matching Strategies

1. **Company name similarity** - Normalized fuzzy matching (threshold: 0.75)
2. **Email domain matching** - Exact match on email domain
3. **Phone number matching** - Last 10 digits comparison
4. **Location matching** - City/state boost to score

### Usage in Code

```python
from services.spiro import get_spiro_context_for_document

# Get context for a document
doc = await db.hub_documents.find_one({"id": doc_id})
context = await get_spiro_context_for_document(doc)

# Access matches
if context.matched_companies:
    best_match = context.matched_companies[0]
    print(f"Best match: {best_match.name} (score: {best_match.match_score})")
    print(f"ISR: {best_match.data.get('assigned_isr')}")

# Use in AI decision
if context.confidence_signals.get("has_company_match"):
    # Higher confidence in vendor identification
    pass
```

### Debug Endpoint

```bash
# Get SpiroContext for a specific document
curl https://your-domain.com/api/spiro/context/{doc_id}

# Test context generation with arbitrary input
curl "https://your-domain.com/api/spiro/context/test?vendor_name=ACME%20Corp&vendor_email=billing@acme.com"
```

## Shadow Mode

The integration is designed for gradual rollout:

### Phase 1: Logging Only (Current)
- SpiroContext is generated and logged
- No automatic changes to BC or workflows
- View recommendations in debug endpoints

### Phase 2: AI Signal Integration
- SpiroContext passed to AI model as additional features
- Model can use ISR/OSR context for routing suggestions
- Still no automatic actions

### Phase 3: Automated Decisions (Future)
- After reviewing Phase 1-2 results
- Enable automatic vendor matching from Spiro
- Enable automatic ISR/OSR assignment

## API Reference

### Configuration
- `GET /api/spiro/status` - Integration status
- `GET /api/spiro/config` - Configuration (sanitized)
- `GET /api/spiro/auth-url` - Get OAuth authorization URL
- `POST /api/spiro/callback` - Exchange auth code for tokens
- `GET /api/spiro/callback?code=...` - OAuth redirect handler

### Sync
- `POST /api/spiro/sync` - Sync with options
- `POST /api/spiro/sync/all` - Sync all entity types
- `POST /api/spiro/sync/contacts` - Sync contacts only

### Data Inspection
- `GET /api/spiro/companies?search=...&limit=50` - List companies
- `GET /api/spiro/contacts?search=...&company_id=...&limit=50` - List contacts
- `GET /api/spiro/opportunities?company_id=...&limit=50` - List opportunities

### Context
- `GET /api/spiro/context/{doc_id}` - Get SpiroContext for document
- `POST /api/spiro/context/test?vendor_name=...` - Test context generation

## MongoDB Collections

### spiro_contacts
```javascript
{
  "spiro_id": "12345",
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  "email": "john@acme.com",
  "email_domain": "acme.com",
  "phone": "555-123-4567",
  "company_id": "999",
  "assigned_isr": "Joey Smith",
  "assigned_osr": "Sarah Johnson",
  "status": "Active",
  "city": "Portland",
  "state": "OR",
  "synced_at": "2026-02-27T10:00:00Z"
}
```

### spiro_companies
```javascript
{
  "spiro_id": "999",
  "name": "ACME Corporation",
  "name_normalized": "ACME CORPORATION",
  "email_domain": "acme.com",
  "phone": "555-987-6543",
  "website": "https://www.acme.com",
  "industry": "Manufacturing",
  "assigned_isr": "Joey Smith",
  "status": "Active",
  "city": "Portland",
  "state": "OR",
  "synced_at": "2026-02-27T10:00:00Z"
}
```

### spiro_opportunities
```javascript
{
  "spiro_id": "5678",
  "name": "Q1 2026 Order",
  "company_id": "999",
  "contact_id": "12345",
  "stage": "Negotiation",
  "value": 50000,
  "close_date": "2026-03-31",
  "owner": "Joey Smith",
  "synced_at": "2026-02-27T10:00:00Z"
}
```

### spiro_sync_status
```javascript
{
  "entity_type": "contacts",
  "last_sync_success": "2026-02-27T10:00:00Z",
  "last_sync_attempt": "2026-02-27T10:00:00Z",
  "records_synced": 1500,
  "last_error": null
}
```

## Current Limitations

1. **Contacts/Companies only** - Opportunities sync is implemented but not fully tested
2. **No real-time updates** - Data is synced periodically, not via webhooks
3. **Basic matching** - Name similarity is basic; could add ML-based matching
4. **No write-back** - We only read from Spiro, never write

## Future Extensions

1. **Webhook support** - Real-time updates from Spiro
2. **ML matching** - Train a model on historical matches
3. **Write-back** - Update Spiro with document associations
4. **Custom objects** - Sync Spiro custom object types
5. **Activity logging** - Log document processing as Spiro activities

## Troubleshooting

### Token Refresh Fails
```bash
# Check token status
curl https://your-domain.com/api/spiro/status

# Re-authorize if needed
curl https://your-domain.com/api/spiro/auth-url
```

### Sync Returns 0 Records
- Verify Spiro has data for the entity type
- Check API rate limits
- Review backend logs for errors

### No Matches Found
- Ensure data is synced (check collection counts)
- Lower match thresholds if needed (in spiro_context.py)
- Test with known company name via debug endpoint

---

*Last updated: February 27, 2026*
