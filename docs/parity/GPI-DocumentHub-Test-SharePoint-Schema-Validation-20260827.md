# GPI-DocumentHub-Test SharePoint Schema Validation

Date: 2026-08-27

Classification: **Validated parity**

Target:
- Site: `https://gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test`
- Library: `Documents`
- Production: not touched

Live remediation created the 16 required AP/Warehouse parity metadata columns and post-write verification returned PASS for every required internal name/type:

- `GPI_SourceTableID` — number
- `GPI_SourceSystemId` — text
- `GPI_SourceDocumentType` — text
- `GPI_SourceDocumentNo` — text
- `GPI_SourcePartyType` — text
- `GPI_SourcePartyNo` — text
- `GPI_OriginalFileName` — text
- `GPI_SharePointFileName` — text
- `GPI_SharePointPath` — text
- `GPI_SharePointURL` — text
- `GPI_Status` — text
- `GPI_MatchStatus` — text
- `GPI_MatchMethod` — text
- `GPI_MatchConfidence` — number
- `GPI_Candidates` — text
- `ImportReady` — boolean

Local evidence paths captured by the guarded remediation:

- `.gpi-diagnostics\sharepoint-parity-schema-remediation\GPI-DocumentHub-Test-Schema-Verification-20260827-183929.csv`
- `.gpi-diagnostics\sharepoint-parity-schema-remediation\GPI-DocumentHub-Test-Created-Columns-20260827-183929.csv`

Result:

`VALIDATED PARITY - UAT SHAREPOINT SCHEMA CONTRACT PASS`

No existing columns were altered or deleted. Production was not touched.
