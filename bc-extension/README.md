# GPI Document Links - Business Central Extension

## Overview

This extension adds a "GPI Documents" factbox to Purchase Invoice pages in Business Central, showing SharePoint document links created by the GPI Document Hub.

## Features

- **GPI Documents Factbox**: Shows on Purchase Invoice pages
- **SharePoint Link**: Click to open the linked document in SharePoint
- **API Endpoint**: Allows GPI Hub to write document links via REST API

## Objects

| Object Type | ID | Name | Description |
|-------------|-----|------|-------------|
| Enum | 50100 | GPI Doc Link Type | Document type enumeration |
| Enum | 50101 | GPI Doc Link Source | Source of link (GPIHub/Manual) |
| Table | 50100 | GPI Document Link | Stores document links |
| Page | 50100 | GPI Document Link Factbox | CardPart factbox for Purchase Invoice |
| Page | 50101 | GPI Document Link List | List view of all links |
| Page | 50102 | GPI Document Link Card | Card view for single link |
| Page | 50110 | GPI Document Link API | REST API endpoint |
| PageExt | 50100 | GPI Purch Invoice Extension | Adds factbox to Purchase Invoice |
| PageExt | 50101 | GPI Posted Purch Inv Extension | Adds factbox to Posted Purchase Invoice |

## API Endpoint

**Base URL**: `https://api.businesscentral.dynamics.com/v2.0/{tenantId}/{environment}/api/gpi/documents/v1.0/companies({companyId})/documentLinks`

### Create Document Link (POST)

```json
{
  "documentType": "Purchase Invoice",
  "targetSystemId": "guid-of-purchase-invoice",
  "bcDocumentNo": "72520",
  "sharePointUrl": "https://tenant.sharepoint.com/sites/...",
  "sharePointDriveId": "drive-id",
  "sharePointItemId": "item-id",
  "uploadedAt": "2026-02-25T18:30:00Z",
  "uploadedBy": "GPI Hub",
  "source": "GPIHub"
}
```

### Query by Target SystemId (GET with filter)

```
GET .../documentLinks?$filter=documentType eq 'Purchase Invoice' and targetSystemId eq {guid}
```

### Update Existing Link (PATCH)

```
PATCH .../documentLinks({systemId})
```

## Installation

1. Download the `.app` package
2. In BC, go to Extension Management
3. Upload the extension
4. Sync and install

## Permissions

The API requires:
- D365 AUTOMATION permission set on the app registration
- API.ReadWrite.All permission granted in Azure AD

## Version History

- 1.0.0.0 - Initial release with Purchase Invoice factbox and API
