[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Normalize-Newlines {
    param([Parameter(Mandatory)][string]$Text)
    return ($Text -replace "`r`n?", "`n")
}

function Read-TextFile {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }

    return Normalize-Newlines ([System.IO.File]::ReadAllText($Path))
}

function Write-TextFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, (Normalize-Newlines $Content), $Utf8NoBom)
}

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$Description
    )

    $OldText = Normalize-Newlines $OldText
    $NewText = Normalize-Newlines $NewText

    $First = $Content.IndexOf($OldText, [System.StringComparison]::Ordinal)
    if ($First -lt 0) {
        throw "Could not find the expected text for: $Description"
    }

    $Second = $Content.IndexOf($OldText, $First + $OldText.Length, [System.StringComparison]::Ordinal)
    if ($Second -ge 0) {
        throw "Found the expected text more than once for: $Description"
    }

    return $Content.Substring(0, $First) + $NewText + $Content.Substring($First + $OldText.Length)
}

function Replace-RegexOnce {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Pattern,
        [Parameter(Mandatory)][string]$Replacement,
        [Parameter(Mandatory)][string]$Description
    )

    $Regex = [regex]::new($Pattern, [System.Text.RegularExpressions.RegexOptions]::Singleline)
    $Matches = $Regex.Matches($Content)
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one match for '$Description' but found $($Matches.Count)."
    }

    return $Regex.Replace($Content, (Normalize-Newlines $Replacement), 1)
}

function Get-UpdatedAppJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Version,
        [string]$DependencyVersion
    )

    $Json = (Read-TextFile $Path) | ConvertFrom-Json
    $Json.version = $Version

    if ($DependencyVersion) {
        $Dependency = $Json.dependencies | Where-Object {
            $_.id -eq 'b6eb6cc8-d984-4ab0-bb15-d3569db41171'
        }
        if (-not $Dependency) {
            throw "The production extension dependency was not found in $Path"
        }
        $Dependency.version = $DependencyVersion
    }

    return ($Json | ConvertTo-Json -Depth 30)
}

$ProductionRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$TestRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement-tests'
$CodeunitRoot = Join-Path $ProductionRoot 'src\codeunit'

$SalesReturnPath = Join-Path $CodeunitRoot 'GPISalesReturnEmail.Codeunit.al'
$PurchaseReturnPath = Join-Path $CodeunitRoot 'GPIPurchaseReturnEmail.Codeunit.al'
$TransferPath = Join-Path $CodeunitRoot 'GPITransferEmail.Codeunit.al'
$OpenOrderPath = Join-Path $CodeunitRoot 'GPICustomerOpenOrderEmail.Codeunit.al'
$ProductionAppPath = Join-Path $ProductionRoot 'app.json'
$TestAppPath = Join-Path $TestRoot 'app.json'
$ChangeLogPath = Join-Path $ProductionRoot 'CHANGELOG.md'

$EditorFailureBlock = @'
        if not TryOpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction) then begin
            EmailErrorText := GetLastErrorText();
            if EmailErrorText = '' then
                EmailErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, EmailErrorText);
            Commit();
            Error('%1', EmailErrorText);
        end;
'@

$TransportEditorBlock = @'
        if not DeliveryTransportMgt.OpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction, EmailErrorText) then begin
            if EmailErrorText = '' then
                EmailErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, EmailErrorText);
            Commit();
            Error('%1', EmailErrorText);
        end;
'@

# Build all four changed codeunits in memory first. Nothing is written unless every
# required replacement succeeds.

# -----------------------------------------------------------------------------
# Sales Return
# -----------------------------------------------------------------------------
$SalesReturn = Read-TextFile $SalesReturnPath
$SalesReturn = Replace-ExactOnce $SalesReturn @'
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ @'
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ 'Sales Return transport variable'
$SalesReturn = Replace-ExactOnce $SalesReturn $EditorFailureBlock $TransportEditorBlock 'Sales Return email editor transport'
$SalesReturn = Replace-RegexOnce $SalesReturn `
    '    local procedure ApplyCustomerRoutingRules\(.*?(?=\n    local procedure ApplyLocationRoutingRules\()' `
    @'
    local procedure ApplyCustomerRoutingRules(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyCustomerRules(
            DeliveryDocumentType,
            SalesHeader."Sell-to Customer No.",
            SalesHeader."Location Code",
            SpecificCustomerOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Sales Return customer routing resolver'
$SalesReturn = Replace-RegexOnce $SalesReturn `
    '    local procedure ApplyLocationRoutingRules\(.*?(?=\n    local procedure CustomerRuleMatches\()' `
    @'
    local procedure ApplyLocationRoutingRules(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificLocationOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyLocationRules(
            DeliveryDocumentType,
            LocationCode,
            SpecificLocationOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Sales Return location routing resolver'

# -----------------------------------------------------------------------------
# Purchase Return
# -----------------------------------------------------------------------------
$PurchaseReturn = Read-TextFile $PurchaseReturnPath
$PurchaseReturn = Replace-ExactOnce $PurchaseReturn @'
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ @'
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ 'Purchase Return transport variable'
$PurchaseReturn = Replace-ExactOnce $PurchaseReturn $EditorFailureBlock $TransportEditorBlock 'Purchase Return email editor transport'
$PurchaseReturn = Replace-RegexOnce $PurchaseReturn `
    '    local procedure ApplyVendorRoutingRules\(.*?(?=\n    local procedure ApplyLocationRoutingRules\()' `
    @'
    local procedure ApplyVendorRoutingRules(PurchaseHeader: Record "Purchase Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificVendorOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyVendorRules(
            DeliveryDocumentType,
            PurchaseHeader."Buy-from Vendor No.",
            PurchaseHeader."Location Code",
            SpecificVendorOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Purchase Return vendor routing resolver'
$PurchaseReturn = Replace-RegexOnce $PurchaseReturn `
    '    local procedure ApplyLocationRoutingRules\(.*?(?=\n    local procedure VendorRuleMatches\()' `
    @'
    local procedure ApplyLocationRoutingRules(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificLocationOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyLocationRules(
            DeliveryDocumentType,
            LocationCode,
            SpecificLocationOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Purchase Return location routing resolver'

# -----------------------------------------------------------------------------
# Transfer
# -----------------------------------------------------------------------------
$Transfer = Read-TextFile $TransferPath
$Transfer = Replace-ExactOnce $Transfer @'
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ @'
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
'@ 'Transfer transport variable'
$Transfer = Replace-ExactOnce $Transfer $EditorFailureBlock $TransportEditorBlock 'Transfer email editor transport'
$Transfer = Replace-RegexOnce $Transfer `
    '    local procedure ApplyLocationRoutingRules\(.*?(?=\n    local procedure LocationRuleMatches\()' `
    @'
    local procedure ApplyLocationRoutingRules(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificLocationOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyLocationRules(
            DeliveryDocumentType,
            LocationCode,
            SpecificLocationOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Transfer location routing resolver'

# -----------------------------------------------------------------------------
# Customer Open Order
# -----------------------------------------------------------------------------
$OpenOrder = Read-TextFile $OpenOrderPath
$OpenOrder = Replace-ExactOnce $OpenOrder @'
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
'@ @'
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
'@ 'Open Order draft transport variable'
$OpenOrder = Replace-ExactOnce $OpenOrder @'
    local procedure SendOneOpenOrderStatus(var Customer: Record Customer; SenderEmailAccount: Record "Email Account" temporary; SenderEmailAddress: Text): Boolean
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
'@ @'
    local procedure SendOneOpenOrderStatus(var Customer: Record Customer; SenderEmailAccount: Record "Email Account" temporary; SenderEmailAddress: Text): Boolean
    var
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
'@ 'Open Order direct-send transport variable'
$OpenOrder = Replace-ExactOnce $OpenOrder @'
        if not TryOpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            Error('%1', ErrorText);
        end;
'@ @'
        if not DeliveryTransportMgt.OpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction, ErrorText) then begin
            if ErrorText = '' then
                ErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            Error('%1', ErrorText);
        end;
'@ 'Open Order email editor transport'
$OpenOrder = Replace-ExactOnce $OpenOrder @'
        ClearLastError();
        if not TrySendOpenOrderEmail(EmailMessage, SenderEmailAccount, SentSuccessfully) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the Customer Open Order Status email.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;
'@ @'
        if not DeliveryTransportMgt.SendEmail(EmailMessage, SenderEmailAccount, SentSuccessfully, ErrorText) then begin
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the Customer Open Order Status email.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;
'@ 'Open Order direct-send transport'
$OpenOrder = Replace-RegexOnce $OpenOrder `
    '    local procedure ApplyRoutingRules\(.*?(?=\n    local procedure RoutingRuleMatches\()' `
    @'
    local procedure ApplyRoutingRules(Customer: Record Customer; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyCustomerRules(
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            Customer."No.",
            '',
            SpecificCustomerOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            ReplaceApplied));
    end;

'@ `
    'Open Order customer routing resolver'

# Metadata is also built in memory before any files are written.
$ProductionApp = Get-UpdatedAppJson -Path $ProductionAppPath -Version '0.22.0.0'
$TestApp = Get-UpdatedAppJson -Path $TestAppPath -Version '0.3.0.2' -DependencyVersion '0.22.0.0'
$ChangeLog = Read-TextFile $ChangeLogPath
if ($ChangeLog -match '(?m)^## 0\.22\.0\.0$') {
    throw 'CHANGELOG.md already contains version 0.22.0.0. The workflow integration patch may already have been applied.'
}

$ChangeLogEntry = @'
## 0.22.0.0

### Changed
- Routed Sales Return, Purchase Return, Transfer, and Customer Open Order recipient resolution through the shared GPI Routing Rule Resolver.
- Routed all four Phase 2 draft-editor workflows through GPI Delivery Transport Mgt.
- Routed Customer Open Order direct batch sends through GPI Delivery Transport Mgt.
- Preserved existing recipient fallback, sender normalization, Delivery Log, report generation, and live email behavior when no test subscriber is bound.

### Safety
- No report layout files were changed.
- No SharePoint upload implementation was changed in this wiring pass.
- Existing local TryFunction procedures remain temporarily in place but are no longer used by the wired workflows.

'@
$ChangeLog = "# Changelog`n`n$ChangeLogEntry" + ($ChangeLog -replace '^# Changelog\n\n', '')

# Write only after every validation and transformation succeeds.
Write-TextFile $SalesReturnPath $SalesReturn
Write-TextFile $PurchaseReturnPath $PurchaseReturn
Write-TextFile $TransferPath $Transfer
Write-TextFile $OpenOrderPath $OpenOrder
Write-TextFile $ProductionAppPath $ProductionApp
Write-TextFile $TestAppPath $TestApp
Write-TextFile $ChangeLogPath $ChangeLog

Set-Location $RepoRoot

$ChangedFiles = @(git diff --name-only)
$UnexpectedRdl = @($ChangedFiles | Where-Object { $_ -match '\.rdl$' -and $_ -notmatch '^bc-extension/zetadocs-replacement/src/reportlayout/' })
if ($UnexpectedRdl.Count -gt 0) {
    throw "Unexpected RDLC changes were detected: $($UnexpectedRdl -join ', ')"
}

Write-Host ''
Write-Host 'Phase 2 workflow integration patch applied successfully.' -ForegroundColor Green
Write-Host 'Production version: 0.22.0.0' -ForegroundColor Green
Write-Host 'Test version:       0.3.0.2' -ForegroundColor Green
Write-Host ''
Write-Host 'Files changed by this patch:' -ForegroundColor Cyan
$ChangedFiles | Where-Object {
    $_ -in @(
        'bc-extension/zetadocs-replacement/src/codeunit/GPISalesReturnEmail.Codeunit.al',
        'bc-extension/zetadocs-replacement/src/codeunit/GPIPurchaseReturnEmail.Codeunit.al',
        'bc-extension/zetadocs-replacement/src/codeunit/GPITransferEmail.Codeunit.al',
        'bc-extension/zetadocs-replacement/src/codeunit/GPICustomerOpenOrderEmail.Codeunit.al',
        'bc-extension/zetadocs-replacement/app.json',
        'bc-extension/zetadocs-replacement-tests/app.json',
        'bc-extension/zetadocs-replacement/CHANGELOG.md'
    )
} | ForEach-Object { Write-Host "  $_" }

Write-Host ''
Write-Host 'Existing local RDLC modifications were not altered by this script.' -ForegroundColor Yellow
