[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.3"
$ExpectedTestVersion = "0.8.0.3"
$NewProductionVersion = "0.27.0.4"
$NewTestVersion = "0.8.0.4"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProductionRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

$SalesOrderPageExt = Join-Path $ProductionRoot "src\pageextension\GPISalesOrder.PageExt.al"
$PostedSalesInvoicesPageExt = Join-Path $ProductionRoot "src\pageextension\GPIPostedSalesInvoices.PageExt.al"
$DropShipPOEmail = Join-Path $ProductionRoot "src\codeunit\GPIDropShipPurchaseOrderEmail.Codeunit.al"
$WarehousePOEmail = Join-Path $ProductionRoot "src\codeunit\GPIWarehousePurchaseOrderEmail.Codeunit.al"
$WarehouseReceivingEmail = Join-Path $ProductionRoot "src\codeunit\GPIWarehouseReceivingEmail.Codeunit.al"
$RecordDocumentMgt = Join-Path $ProductionRoot "src\codeunit\GPIRecordDocumentMgt.Codeunit.al"
$RecordDocumentControlAddIn = Join-Path $ProductionRoot "src\controladdin\GPIRecordDocumentDropzone.ControlAddIn.al"
$RecordDocumentsJs = Join-Path $ProductionRoot "src\controladdin\recorddocuments\recordDocuments.js"
$RecordDocumentsCss = Join-Path $ProductionRoot "src\controladdin\recorddocuments\recordDocuments.css"
$RecordDocumentsFactBox = Join-Path $ProductionRoot "src\page\GPIRecordDocumentsFactBox.Page.al"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $SalesOrderPageExt,
    $PostedSalesInvoicesPageExt,
    $DropShipPOEmail,
    $WarehousePOEmail,
    $WarehouseReceivingEmail,
    $RecordDocumentMgt,
    $RecordDocumentControlAddIn,
    $RecordDocumentsJs,
    $RecordDocumentsCss,
    $RecordDocumentsFactBox
)

foreach ($RequiredPath in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

function Assert-FileHash {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ExpectedHash
    )

    $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($ActualHash -ne $ExpectedHash.ToUpperInvariant()) {
        throw "Source file changed unexpectedly: $Path`nExpected SHA256: $ExpectedHash`nActual SHA256:   $ActualHash`nNo files were changed."
    }
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$Description
    )

    $Count = ([regex]::Matches($Content, [regex]::Escape($OldText))).Count
    if ($Count -ne 1) {
        throw "Expected exactly one match for $Description, but found $Count. No files were changed."
    }

    return $Content.Replace($OldText, $NewText)
}

function Add-OutsideSalespersonHelper {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$FileDescription
    )

    $Marker = '    local procedure GetInsideSalespersonCode(PurchaseHeader: Record "Purchase Header"): Code[20]'
    $Helper = @'
    local procedure GetOutsideSalespersonCode(PurchaseHeader: Record "Purchase Header"): Code[20]
    var
        PurchaseHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        for FieldIndex := 1 to PurchaseHeaderRef.FieldCount do begin
            CandidateField := PurchaseHeaderRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if IsOutsideSalespersonField(CandidateIdentity) then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
                    exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;

        exit(PurchaseHeader."Purchaser Code");
    end;

    local procedure IsOutsideSalespersonField(FieldIdentity: Text): Boolean
    begin
        exit(
            (StrPos(FieldIdentity, 'salesperson') > 0) and
            (StrPos(FieldIdentity, 'inside') = 0) and
            (StrPos(FieldIdentity, 'backup') = 0) and
            (StrPos(FieldIdentity, 'purchaser') = 0));
    end;


'@

    return Replace-Once `
        -Content $Content `
        -OldText $Marker `
        -NewText ($Helper + $Marker) `
        -Description "$FileDescription outside-salesperson helper insertion point"
}

Assert-FileHash -Path $ProductionAppJson -ExpectedHash "A115AEAAB7298975158B4E61FDA02A579A3902DC1563C69A708681C1AE351D69"
Assert-FileHash -Path $TestAppJson -ExpectedHash "B2BC2C62EC6589F0A83EC93E0595B418AE9D6AB3F8AE0C754126B67E6C030F0A"
Assert-FileHash -Path $ChangeLog -ExpectedHash "186142C3E231DF087A68B2B86FCB773DC35F9605F29C09B2FDB0F8A1D287EDE9"

Assert-FileHash -Path $SalesOrderPageExt -ExpectedHash "0C9D701EDA24B5F86CD9BB3FDBF7FEB5408E15BC9C65CCC7AFF6A46CE282D17D"
Assert-FileHash -Path $PostedSalesInvoicesPageExt -ExpectedHash "9CD3758DC354F41E46487B671DFD3985E3CF92E3553DDD7B1591BDF639BC6F64"
Assert-FileHash -Path $DropShipPOEmail -ExpectedHash "E650468978EA79AA21D717CE1CDDC70A9DE3CB86CAB97645CD641BBF85BD46DE"
Assert-FileHash -Path $WarehousePOEmail -ExpectedHash "5887282858F9B897C293FCBD9CD942A6A67F06EBA06303B9D763D2CEF9E07CB3"
Assert-FileHash -Path $WarehouseReceivingEmail -ExpectedHash "3C532AF5BB9697D9512114AC9080EE2163CC9B6407C15751C8C8D2F9057A3A0F"
Assert-FileHash -Path $RecordDocumentMgt -ExpectedHash "A2CF8C673E3099DCF6C4C3F2E730233CB7EA3E819E5BC2470F279296A70E8945"
Assert-FileHash -Path $RecordDocumentControlAddIn -ExpectedHash "523846A34475C820612B6B02DA32531553EC9ED3010868A9946E9963FE27EB55"
Assert-FileHash -Path $RecordDocumentsJs -ExpectedHash "4DC7E3560946A1A5BC4A04863B9BDDBB92D65046A40B1286813997B4A4350B4B"
Assert-FileHash -Path $RecordDocumentsCss -ExpectedHash "2F57821CFE7338261CAE49D9943F2BCD6A3B6DCD9F603494B4F38AE03FA72B6E"
Assert-FileHash -Path $RecordDocumentsFactBox -ExpectedHash "B2753644C64781B5C877F50F4E28537039B6B7E16A5C5A21F739E07141FBDB3D"

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$Originals = @{}
foreach ($Path in $RequiredPaths | Where-Object { $_ -ne $BuildScript }) {
    $Originals[$Path] = Get-Content -LiteralPath $Path -Raw
}

$UpdatedSalesOrder = $Originals[$SalesOrderPageExt]
$UpdatedSalesOrder = Replace-Once `
    -Content $UpdatedSalesOrder `
    -OldText @'
                action(GPIEmailPickTicket)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Pick Ticket';
'@ `
    -NewText @'
                action(GPIEmailPickTicket)
                {
                    ApplicationArea = All;
                    Enabled = IsPickTicketAvailable;
                    Caption = 'Gamer Email Pick Ticket';
'@ `
    -Description "Sales Order Email Pick Ticket enabled flag"

$UpdatedSalesOrder = Replace-Once `
    -Content $UpdatedSalesOrder `
    -OldText @'
                action(GPIPreviewOwnedPickTicket)
                {

                    PromotedIsBig = true;
'@ `
    -NewText @'
                action(GPIPreviewOwnedPickTicket)
                {
                    Enabled = IsPickTicketAvailable;

                    PromotedIsBig = true;
'@ `
    -Description "Sales Order Preview Pick Ticket enabled flag"

$UpdatedSalesOrder = Replace-Once `
    -Content $UpdatedSalesOrder `
    -OldText @'
    }
}
'@ `
    -NewText @'
    }

    trigger OnAfterGetRecord()
    begin
        SetPickTicketActionState();
    end;

    trigger OnAfterGetCurrRecord()
    begin
        SetPickTicketActionState();
    end;

    local procedure SetPickTicketActionState()
    begin
        IsPickTicketAvailable := Rec."Location Code" <> '00';
    end;

    var
        IsPickTicketAvailable: Boolean;
}
'@ `
    -Description "Sales Order action-state trigger insertion"

$UpdatedPostedSalesInvoices = Replace-Once `
    -Content $Originals[$PostedSalesInvoicesPageExt] `
    -OldText @'
            action(GPIOpenInvoiceQueue)
            {
                ApplicationArea = All;
                Caption = 'Gamer Invoice Delivery Queue';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                RunObject = page "GPI Posted Invoice Queue";
                ToolTip = 'Opens the Gamer filterable end-of-day posted sales invoice email queue.';
            }
'@ `
    -NewText @'
            action(GPIOpenInvoiceQueue)
            {
                ApplicationArea = All;
                Caption = 'Gamer Invoice Delivery Queue';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                RunObject = page "GPI Posted Invoice Queue";
                ToolTip = 'Opens the Gamer filterable end-of-day posted sales invoice email queue.';
            }

            action(GPIOpenEndOfDayInvoiceBatch)
            {
                ApplicationArea = All;
                Caption = 'Gamer EOD Invoice Batch';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Opens the Gamer posted invoice queue filtered to invoices posted today with Amount not equal to zero, matching the end-of-day Zetadocs send procedure.';

                trigger OnAction()
                var
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                begin
                    SalesInvoiceHeader.SetRange("Posting Date", Today);
                    SalesInvoiceHeader.SetFilter(Amount, '<>0');
                    Page.Run(Page::"GPI Posted Invoice Queue", SalesInvoiceHeader);
                end;
            }
'@ `
    -Description "Posted Sales Invoices EOD action"

$UpdatedDropShip = $Originals[$DropShipPOEmail]
$UpdatedDropShip = Replace-Once `
    -Content $UpdatedDropShip `
    -OldText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text])
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(PurchaseHeader."Purchaser Code"), ToRecipients, UserId());
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, UserId());
    end;
'@ `
    -NewText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text])
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetOutsideSalespersonCode(PurchaseHeader)), ToRecipients, UserId());
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, UserId());
    end;
'@ `
    -Description "Drop Ship PO OSR CC source"
$UpdatedDropShip = Add-OutsideSalespersonHelper -Content $UpdatedDropShip -FileDescription "Drop Ship PO"

$UpdatedWarehousePO = $Originals[$WarehousePOEmail]
$UpdatedWarehousePO = Replace-Once `
    -Content $UpdatedWarehousePO `
    -OldText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(PurchaseHeader."Purchaser Code"), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
    end;
'@ `
    -NewText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetOutsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
    end;
'@ `
    -Description "Warehouse PO OSR CC source"
$UpdatedWarehousePO = Add-OutsideSalespersonHelper -Content $UpdatedWarehousePO -FileDescription "Warehouse PO"

$UpdatedWarehouseReceiving = $Originals[$WarehouseReceivingEmail]
$UpdatedWarehouseReceiving = Replace-Once `
    -Content $UpdatedWarehouseReceiving `
    -OldText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(PurchaseHeader."Purchaser Code"), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
    end;
'@ `
    -NewText @'
    local procedure AddDefaultCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetOutsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(PurchaseHeader)), ToRecipients, SenderEmailAddress);
    end;
'@ `
    -Description "Warehouse Receiving Notice OSR CC source"
$UpdatedWarehouseReceiving = Add-OutsideSalespersonHelper -Content $UpdatedWarehouseReceiving -FileDescription "Warehouse Receiving Notice"

$UpdatedRecordDocumentMgt = Replace-Once `
    -Content $Originals[$RecordDocumentMgt] `
    -OldText @'
    procedure OpenSentDocument(DeliveryLogEntryNo: Integer)
'@ `
    -NewText @'
    procedure DeleteDocumentReference(EntryReference: Integer)
    var
        Document: Record "GPI Record Document";
    begin
        if EntryReference = 0 then
            Error('The selected document does not have a valid document reference.');

        if EntryReference < 0 then
            Error('Sent document history cannot be deleted from the Gamer Documents FactBox. Open the Delivery Log to review sent-document history.');

        Document.Get(EntryReference);
        if Document.Status = Document.Status::Deleted then
            exit;

        Document.Status := Document.Status::Deleted;
        Document."Last Error" := CopyStr(
            StrSubstNo(
                'Deleted from Gamer Documents by %1 on %2.',
                UserId(),
                Format(CurrentDateTime(), 0, '<Month,2>/<Day,2>/<Year4> <Hours24,2>:<Minutes,2>')),
            1,
            MaxStrLen(Document."Last Error"));
        Document.Modify(true);
    end;

    procedure OpenSentDocument(DeliveryLogEntryNo: Integer)
'@ `
    -Description "Record document delete procedure"

$UpdatedControlAddIn = Replace-Once `
    -Content $Originals[$RecordDocumentControlAddIn] `
    -OldText @'
    event DocumentOpenRequested(EntryNo: Integer);
    event RefreshRequested();
'@ `
    -NewText @'
    event DocumentOpenRequested(EntryNo: Integer);
    event DocumentDeleteRequested(EntryNo: Integer);
    event RefreshRequested();
'@ `
    -Description "record document delete event"

$OldJsBlock = @'
            state.documents.forEach(function (documentItem) {
                var entryNo = Number(documentItem.entryNo);
                var statusText = documentItem.status || "";
                var isSentDocument = statusText.indexOf("Sent") === 0;
                var isOpenable =
                    entryNo !== 0 &&
                    (statusText === "Uploaded" || isSentDocument);

                var row = makeElement(
                    "button",
                    "gpi-rd-document" + (isOpenable ? "" : " unavailable")
                );
                row.type = "button";
                row.disabled = !isOpenable;
                row.addEventListener("click", function () {
                    if (isOpenable) {
                        invoke("DocumentOpenRequested", [entryNo]);
                    }
                });

                row.appendChild(
                    makeElement("div", "gpi-rd-document-name", documentItem.fileName)
                );

                var metaParts = [];
                if (documentItem.category) {
                    metaParts.push(documentItem.category);
                }
                if (documentItem.uploadedAt) {
                    metaParts.push(documentItem.uploadedAt);
                }
                if (documentItem.size) {
                    metaParts.push(formatBytes(documentItem.size));
                }
                if (documentItem.status && documentItem.status !== "Uploaded") {
                    metaParts.push(documentItem.status);
                }

                row.appendChild(
                    makeElement("div", "gpi-rd-document-meta", metaParts.join(" \u2022 "))
                );
                list.appendChild(row);
            });
'@

$NewJsBlock = @'
            state.documents.forEach(function (documentItem) {
                var entryNo = Number(documentItem.entryNo);
                var statusText = documentItem.status || "";
                var isSentDocument = statusText.indexOf("Sent") === 0;
                var isOpenable =
                    entryNo !== 0 &&
                    (statusText === "Uploaded" || isSentDocument);
                var isDeleteable =
                    entryNo > 0 &&
                    statusText === "Uploaded";

                var rowContainer = makeElement(
                    "div",
                    "gpi-rd-document-row" + (isOpenable ? "" : " unavailable")
                );

                var row = makeElement(
                    "button",
                    "gpi-rd-document" + (isOpenable ? "" : " unavailable")
                );
                row.type = "button";
                row.disabled = !isOpenable;
                row.addEventListener("click", function () {
                    if (isOpenable) {
                        invoke("DocumentOpenRequested", [entryNo]);
                    }
                });

                row.appendChild(
                    makeElement("div", "gpi-rd-document-name", documentItem.fileName)
                );

                var metaParts = [];
                if (documentItem.category) {
                    metaParts.push(documentItem.category);
                }
                if (documentItem.uploadedAt) {
                    metaParts.push(documentItem.uploadedAt);
                }
                if (documentItem.size) {
                    metaParts.push(formatBytes(documentItem.size));
                }
                if (documentItem.status && documentItem.status !== "Uploaded") {
                    metaParts.push(documentItem.status);
                }

                row.appendChild(
                    makeElement("div", "gpi-rd-document-meta", metaParts.join(" \u2022 "))
                );
                rowContainer.appendChild(row);

                if (isDeleteable) {
                    var deleteButton = makeElement("button", "gpi-rd-delete", "Delete");
                    deleteButton.type = "button";
                    deleteButton.title = "Delete this uploaded document";
                    deleteButton.setAttribute("aria-label", "Delete " + documentItem.fileName);
                    deleteButton.addEventListener("click", function (event) {
                        event.preventDefault();
                        event.stopPropagation();

                        if (!confirm("Delete " + documentItem.fileName + " from Gamer Documents?")) {
                            return;
                        }

                        invoke("DocumentDeleteRequested", [entryNo]).catch(function (error) {
                            setStatus(
                                error && error.message
                                    ? error.message
                                    : "The document could not be deleted.",
                                true
                            );
                        });
                    });
                    rowContainer.appendChild(deleteButton);
                }

                list.appendChild(rowContainer);
            });
'@

$UpdatedJs = Replace-Once `
    -Content $Originals[$RecordDocumentsJs] `
    -OldText $OldJsBlock `
    -NewText $NewJsBlock `
    -Description "record document JavaScript row rendering"

$OldCssBlock = @'
.gpi-rd-document { display: block; box-sizing: border-box; width: 100%; padding: 8px 4px; border: 0; border-bottom: 1px solid #edebe9; text-align: left; background: #fff; cursor: pointer; }
.gpi-rd-document:hover { background: #f3f2f1; }
.gpi-rd-document.unavailable { color: #a19f9d; cursor: default; }
'@

$NewCssBlock = @'
.gpi-rd-document-row { display: flex; align-items: stretch; width: 100%; border-bottom: 1px solid #edebe9; background: #fff; }
.gpi-rd-document-row:hover { background: #f3f2f1; }
.gpi-rd-document { display: block; box-sizing: border-box; flex: 1 1 auto; min-width: 0; padding: 8px 4px; border: 0; text-align: left; background: transparent; cursor: pointer; }
.gpi-rd-document:hover { background: transparent; }
.gpi-rd-document.unavailable { color: #a19f9d; cursor: default; }
.gpi-rd-delete { flex: 0 0 auto; border: 0; padding: 0 8px; color: #605e5c; background: transparent; cursor: pointer; font-size: 11px; }
.gpi-rd-delete:hover { color: #a4262c; text-decoration: underline; }
'@

$UpdatedCss = Replace-Once `
    -Content $Originals[$RecordDocumentsCss] `
    -OldText $OldCssBlock `
    -NewText $NewCssBlock `
    -Description "record document CSS row/delete styles"

$UpdatedFactBox = Replace-Once `
    -Content $Originals[$RecordDocumentsFactBox] `
    -OldText @'
                trigger DocumentOpenRequested(EntryNo: Integer)
                begin
                    DocumentMgt.OpenDocumentReference(EntryNo);
                end;

                trigger RefreshRequested()
'@ `
    -NewText @'
                trigger DocumentOpenRequested(EntryNo: Integer)
                begin
                    DocumentMgt.OpenDocumentReference(EntryNo);
                end;

                trigger DocumentDeleteRequested(EntryNo: Integer)
                begin
                    DocumentMgt.DeleteDocumentReference(EntryNo);
                    CurrPage.DocumentDropZone.SetRecordUploadStatus(
                        'Document was removed from Gamer Documents.',
                        false);
                    RefreshDocuments();
                end;

                trigger RefreshRequested()
'@ `
    -Description "Record Documents FactBox delete trigger"

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Disabled Sales Order Pick Ticket email and preview actions when the Sales Order header Location Code is 00.
- Purchase Order document CC resolution now uses the Purchase Header Salesperson Code/OSR when available instead of relying first on the base Purchaser Code.
- Added a Gamer EOD Invoice Batch action that opens the posted invoice queue filtered to today's Posting Date and Amount <> 0.

### Added
- Added a Delete option for manually uploaded Gamer Documents FactBox rows.
- Sent-document history rows remain non-deletable from the FactBox because they are Delivery Log history.

### Safety
- Gamer Documents deletion marks the uploaded record as Deleted so it is removed from the FactBox; sent Delivery Log entries are not deleted.
- No SharePoint file is physically deleted by this change.
- No invoice PDF, routing-rule, sender-account, Delivery Log, or SharePoint archive behavior was otherwise changed.
- No package is published automatically.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

$UpdatedChangeLog = $Originals[$ChangeLog]
if ($UpdatedChangeLog -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $UpdatedChangeLog,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\change-request-027004-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $SalesOrderPageExt,
    $PostedSalesInvoicesPageExt,
    $DropShipPOEmail,
    $WarehousePOEmail,
    $WarehouseReceivingEmail,
    $RecordDocumentMgt,
    $RecordDocumentControlAddIn,
    $RecordDocumentsJs,
    $RecordDocumentsCss,
    $RecordDocumentsFactBox
)

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    Write-Utf8NoBom -Path $SalesOrderPageExt -Content $UpdatedSalesOrder
    Write-Utf8NoBom -Path $PostedSalesInvoicesPageExt -Content $UpdatedPostedSalesInvoices
    Write-Utf8NoBom -Path $DropShipPOEmail -Content $UpdatedDropShip
    Write-Utf8NoBom -Path $WarehousePOEmail -Content $UpdatedWarehousePO
    Write-Utf8NoBom -Path $WarehouseReceivingEmail -Content $UpdatedWarehouseReceiving
    Write-Utf8NoBom -Path $RecordDocumentMgt -Content $UpdatedRecordDocumentMgt
    Write-Utf8NoBom -Path $RecordDocumentControlAddIn -Content $UpdatedControlAddIn
    Write-Utf8NoBom -Path $RecordDocumentsJs -Content $UpdatedJs
    Write-Utf8NoBom -Path $RecordDocumentsCss -Content $UpdatedCss
    Write-Utf8NoBom -Path $RecordDocumentsFactBox -Content $UpdatedFactBox
    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI final change request 0.27.0.4" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""
    Write-Host "Changes included:" -ForegroundColor Cyan
    Write-Host " - Sales Order Pick Ticket disabled when Location Code is 00"
    Write-Host " - PO CC uses OSR/Salesperson Code before Purchaser Code"
    Write-Host " - Gamer Documents manual-upload delete option"
    Write-Host " - Posted Sales Invoices EOD batch entry point"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "The 0.27.0.4 change-request build failed. Restoring all modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path $BackupRoot $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.4 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, refresh the Testing panel, and run the complete test suite." -ForegroundColor Yellow
