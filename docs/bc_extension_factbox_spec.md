# BC AL Extension — GPI Documents Factbox Spec

## Overview

This document specifies the changes needed in the BC AL extension to make 
the GPI Documents factbox a full Zetadocs replacement. The factbox currently 
shows SharePoint links on Purchase Invoice pages. These changes extend it to 
Purchase Orders and Sales Orders, and add file upload capability.

---

## API Endpoints

All endpoints are served from the GPI Hub backend. Base URL is configured 
in the AL extension as `GPIHubBaseUrl` (e.g. `https://gpi-hub.company.com/api`).

### 1. GET Document Links

**Purpose**: Retrieve all documents linked to a BC record.

```
GET {GPIHubBaseUrl}/gpi-integration/document-links/{bc_entity}/{bc_document_no}
```

**Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `bc_entity` | path | `purchaseOrders`, `purchaseInvoices`, or `salesOrders` |
| `bc_document_no` | path | The BC document number (e.g. `PI-00145`) |

**Response** (200):
```json
{
  "bc_entity": "purchaseInvoices",
  "bc_document_no": "PI-00145",
  "documents": [
    {
      "doc_id": "abc-123",
      "file_name": "Invoice_March_2026.pdf",
      "sharepoint_web_url": "https://company.sharepoint.com/sites/.../Invoice_March_2026.pdf",
      "sharepoint_folder_path": "AP/VendorName/2026",
      "uploaded_by": "Jane Smith",
      "created_utc": "2026-03-21T18:30:00Z",
      "file_size_bytes": 245000,
      "document_type": "AP_Invoice",
      "source": "hub"
    },
    {
      "doc_id": "bc-link-guid",
      "file_name": "OldDoc.pdf",
      "sharepoint_web_url": "https://company.sharepoint.com/...",
      "sharepoint_folder_path": "",
      "uploaded_by": "Zetadocs",
      "created_utc": "2025-11-15T10:00:00Z",
      "file_size_bytes": null,
      "document_type": "Purchase Invoice",
      "source": "zetadocs_legacy"
    }
  ],
  "total": 2
}
```

**Source values**:
- `"hub"` — Filed by GPI Hub pipeline
- `"bc_drop"` — Uploaded via BC factbox
- `"zetadocs_legacy"` — Pre-existing Zetadocs link

---

### 2. POST Upload File

**Purpose**: Upload a file to SharePoint and create a GPI Document Link.

```
POST {GPIHubBaseUrl}/gpi-integration/document-links/{bc_entity}/{bc_document_no}/upload
Content-Type: multipart/form-data
```

**Form fields**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | The document file (max 25 MB) |
| `uploaded_by` | string | No | User name (default: "BC Drop") |
| `vendor_context` | string | No | Vendor name hint for folder routing fallback |

**Response** (200):
```json
{
  "success": true,
  "doc_id": "new-uuid",
  "file_name": "Receipt.pdf",
  "sharepoint_url": "https://company.sharepoint.com/sites/.../Receipt.pdf",
  "folder_path": "AP/VendorName/2026",
  "folder_source": "matched",
  "bc_link_created": true
}
```

**Error responses**:
| Status | Meaning |
|--------|---------|
| 413 | File exceeds 25 MB limit |
| 502 | SharePoint upload failed |

---

### 3. DELETE Document Link

**Purpose**: Remove a document link (soft delete — SP file preserved).

```
DELETE {GPIHubBaseUrl}/gpi-integration/document-links/{bc_entity}/{bc_document_no}/{doc_id}
```

**Response** (200):
```json
{
  "success": true,
  "message": "Link removed for Receipt.pdf. SharePoint file preserved."
}
```

---

## AL Page Extension Changes

### 4a. Extend Factbox to All Three Page Types

The GPI Documents factbox currently exists on:
- **Purchase Invoice** page (Page 51 / Purchase Invoice Card)

Extend the same factbox part to:
- **Purchase Order** page (Page 50 / Purchase Order Card)
- **Sales Order** page (Page 42 / Sales Order Card)

The factbox should derive `bc_entity` from the page context:
- Purchase Invoice → `purchaseInvoices`
- Purchase Order → `purchaseOrders`
- Sales Order → `salesOrders`

And use `"Document No."` from the current record as `bc_document_no`.

### 4b. Factbox UI Changes

#### Document List

For each linked document, show:
- **File name** as a hyperlink → opens `sharepoint_web_url` in browser
- **Uploaded by** — text
- **Date** — `created_utc` formatted as date only
- **Source badge** — display based on `source` field:
  - `"hub"` → "GPI Hub" (blue)
  - `"bc_drop"` → "BC Drop" (green)
  - `"zetadocs_legacy"` → "Legacy" (gray)

#### Upload Control

Add to the bottom of the factbox:
- A `FileUpload` control (AL 2025 Wave 1+) or Action button
- "Upload" action button
- The upload calls POST `.../upload` with:
  - `file` = selected file
  - `uploaded_by` = current user name (`UserId`)
  - `vendor_context` = vendor name from the current record (if available)

#### Client-side validations:
- File size < 25 MB — show error before calling API
- After upload: refresh the document list by re-calling GET

#### Error handling:
- Show inline error message for:
  - HTTP 413 → "File exceeds 25 MB limit"
  - HTTP 502 → "SharePoint upload failed — please try again"
  - Other errors → show response detail text

#### Refresh behavior:
- Call GET `.../document-links/{entity}/{no}` on:
  - Page open (OnAfterGetCurrRecord)
  - After each successful upload
  - After delete action

---

### 4c. Required AL HTTP Calls

#### GET Document List

```al
procedure GetDocumentLinks(BCEntity: Text; BCDocumentNo: Text)
var
    Client: HttpClient;
    Response: HttpResponseMessage;
    Content: HttpContent;
    ResponseText: Text;
    RequestUrl: Text;
begin
    RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' + BCEntity + '/' + BCDocumentNo;
    Client.Get(RequestUrl, Response);
    Response.Content.ReadAs(ResponseText);
    // Parse JSON: ResponseText contains { documents: [...], total: N }
end;
```

#### POST File Upload (Multipart)

```al
procedure UploadDocument(BCEntity: Text; BCDocumentNo: Text; FileName: Text; FileStream: InStream)
var
    Client: HttpClient;
    MultipartContent: HttpContent;
    Response: HttpResponseMessage;
    RequestUrl: Text;
    ContentHeaders: HttpHeaders;
    FileContent: HttpContent;
    FormContent: HttpContent;
    Boundary: Text;
begin
    Boundary := '--GPIUpload' + Format(CurrentDateTime, 0, '<Year4><Month,2><Day,2><Hours24,2><Minutes,2>');
    RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' + BCEntity + '/' + BCDocumentNo + '/upload';

    // Build multipart/form-data body
    // Part 1: file
    FileContent.WriteFrom(FileStream);
    FileContent.GetHeaders(ContentHeaders);
    ContentHeaders.Remove('Content-Type');
    ContentHeaders.Add('Content-Type', 'application/octet-stream');
    ContentHeaders.Add('Content-Disposition', 'form-data; name="file"; filename="' + FileName + '"');

    // Part 2: uploaded_by
    FormContent.WriteFrom(UserId);
    FormContent.GetHeaders(ContentHeaders);
    ContentHeaders.Add('Content-Disposition', 'form-data; name="uploaded_by"');

    // Combine and send
    MultipartContent.GetHeaders(ContentHeaders);
    ContentHeaders.Remove('Content-Type');
    ContentHeaders.Add('Content-Type', 'multipart/form-data; boundary=' + Boundary);

    Client.Post(RequestUrl, MultipartContent, Response);

    if Response.HttpStatusCode = 413 then
        Error('File exceeds 25 MB limit.');
    if Response.HttpStatusCode = 502 then
        Error('SharePoint upload failed. Please try again.');
    if not Response.IsSuccessStatusCode then
        Error('Upload failed: ' + Format(Response.HttpStatusCode));
end;
```

#### DELETE Document Link

```al
procedure DeleteDocumentLink(BCEntity: Text; BCDocumentNo: Text; DocId: Text)
var
    Client: HttpClient;
    Response: HttpResponseMessage;
    RequestUrl: Text;
begin
    RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' + BCEntity + '/' + BCDocumentNo + '/' + DocId;
    Client.Delete(RequestUrl, Response);
    if not Response.IsSuccessStatusCode then
        Error('Failed to remove link.');
end;
```

---

## Migration (One-Time)

To import existing Zetadocs links into the hub for a unified view:

```
POST {GPIHubBaseUrl}/gpi-integration/document-links/migrate-from-zetadocs
```

This is idempotent — safe to run multiple times. It:
1. Reads all documentLinks from BC where source is not BCDrop/GPIHub
2. Creates hub_documents stub records for each
3. Skips records that already exist (by sharepoint_item_id or sharepoint_web_url)

Returns: `{ migrated: N, skipped: N, errors: [] }`

---

## Notes

- Files are **never deleted** from SharePoint. The DELETE endpoint only removes the 
  link record.
- Folder resolution uses the "match existing" strategy first (finding the SP folder 
  from previously linked documents), then falls back to routing rules. This preserves 
  Zetadocs-era folder conventions.
- The `vendor_context` field on upload is optional but improves folder routing accuracy 
  when no prior documents exist for the BC record.
