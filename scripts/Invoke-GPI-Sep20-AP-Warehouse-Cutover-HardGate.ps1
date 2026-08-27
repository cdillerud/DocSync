#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$Environment = 'Sandbox_08142026_GamerDocs'
$MainRoot = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$ReportRoot = Join-Path $RepoRoot '.gpi-diagnostics\sep20-ap-warehouse-cutover'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Add-LedgerRow {
    param(
        [Parameter(Mandatory)][string]$Area,
        [Parameter(Mandatory)][string]$Gate,
        [Parameter(Mandatory)][ValidateSet('PARITY BLOCKER','PARITY RISK','VALIDATED PARITY','POST-PARITY ENHANCEMENT')][string]$Classification,
        [Parameter(Mandatory)][string]$Evidence,
        [string]$NextAction = ''
    )

    $script:Ledger.Add([pscustomobject]@{
        Area = $Area
        Gate = $Gate
        Classification = $Classification
        Evidence = $Evidence
        NextAction = $NextAction
    }) | Out-Null
}

function Find-Script([string[]]$Names) {
    foreach ($Name in $Names) {
        $Candidates = @(
            Join-Path $RepoRoot $Name
            Join-Path (Join-Path $RepoRoot 'scripts') $Name
            Join-Path $env:USERPROFILE "Downloads\$Name"
        )

        foreach ($Candidate in $Candidates) {
            if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                return $Candidate
            }
        }
    }

    return $null
}

function Get-LatestRecipientAuthorityCsv {
    $Root = Join-Path $RepoRoot '.gpi-diagnostics\recipient-authority-audit'
    if (-not (Test-Path -LiteralPath $Root)) { return $null }

    return Get-ChildItem -LiteralPath $Root -Recurse -File -Filter 'Recipient_Authority_Audit.csv' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
}

function ContainsAny([string]$Text,[string[]]$Patterns) {
    foreach ($Pattern in $Patterns) {
        if ($Text -match $Pattern) { return $true }
    }
    return $false
}

Section '1. HARD SAFETY / SCOPE'

if ($Environment -ne 'Sandbox_08142026_GamerDocs' -or $Environment -match '(?i)prod') {
    throw "SAFETY STOP: unexpected or Production-like environment '$Environment'."
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repo not found: $RepoRoot"
}

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine current Git branch.' }
if ($Branch -ne $ExpectedBranch) {
    throw "Wrong branch. Expected '$ExpectedBranch', found '$Branch'."
}

Write-Host "Repo        : $RepoRoot"
Write-Host "Branch      : $Branch"
Write-Host "Environment : $Environment"
Write-Host 'Mode        : READ ONLY'
Write-Host 'Production  : HARD BLOCKED' -ForegroundColor Green

$Ledger = [System.Collections.Generic.List[object]]::new()

Section '2. MAIN APP DELIVERY BASELINE'

$MainAppJson = Join-Path $MainRoot 'app.json'
if (-not (Test-Path -LiteralPath $MainAppJson)) {
    Add-LedgerRow 'Deployment' 'Main app source baseline' 'PARITY BLOCKER' 'Main app app.json not found.' 'Restore/resolve local delivery worktree.'
}
else {
    $Main = Get-Content -LiteralPath $MainAppJson -Raw | ConvertFrom-Json
    $Version = [version][string]$Main.version
    Write-Host "Main app version : $Version"

    if ($Version -lt [version]'0.27.0.183') {
        Add-LedgerRow 'Deployment' 'Main app source baseline' 'PARITY BLOCKER' "Local main app is $Version; expected at least 0.27.0.183 delivery baseline." 'Reconcile current delivery source before cutover.'
    }
    else {
        Add-LedgerRow 'Deployment' 'Main app source baseline' 'VALIDATED PARITY' "Local main app version is $Version, at/above 0.27.0.183 baseline."
    }

    $Packages = @(Get-ChildItem -LiteralPath $MainRoot -File -Filter '*.app' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'GPI Sales Document Email' } |
        Sort-Object LastWriteTimeUtc -Descending)

    if ($Packages.Count -eq 0) {
        Add-LedgerRow 'Deployment' 'Compiled main package present' 'PARITY RISK' 'No compiled GPI Sales Document Email .app package found in app root.' 'Compile final cutover package before Production authorization.'
    }
    else {
        $Pkg = $Packages[0]
        $Hash = (Get-FileHash -LiteralPath $Pkg.FullName -Algorithm SHA256).Hash
        Add-LedgerRow 'Deployment' 'Compiled main package present' 'VALIDATED PARITY' "Latest package $($Pkg.Name); SHA256=$Hash"
    }
}

Section '3. BRIDGE SEMANTIC RECIPIENT CORRECTION'

$BridgeAppJson = Join-Path $BridgeRoot 'app.json'
$BridgeMgt = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsRoutingParity.Codeunit.al'

if (-not (Test-Path -LiteralPath $BridgeAppJson) -or -not (Test-Path -LiteralPath $BridgeMgt)) {
    Add-LedgerRow 'Routing' 'Semantic effective-recipient bridge' 'PARITY RISK' 'Bridge source not found locally.' 'Retain verified .20 bridge artifact/evidence for cutover rollback package.'
}
else {
    $Bridge = Get-Content -LiteralPath $BridgeAppJson -Raw | ConvertFrom-Json
    $Mgt = Get-Content -LiteralPath $BridgeMgt -Raw

    $Semantic = $Mgt.Contains('ResolveUniqueLiveWarehouseRule(')
    $OldGuard = $Mgt.Contains('AssertLiveWarehouseRule(')
    $ZeroGuard = $Mgt.Contains('if MatchCount = 0 then')
    $MultiGuard = $Mgt.Contains('if MatchCount > 1 then')
    $Evidence = $Mgt.Contains('re3uoffice@reiles.com;re4uoffice@reiles.com;transportation@reiles.com') -and
                $Mgt.Contains('everyone-bsw@trilliantfood.com') -and
                $Mgt.Contains('evermansiteleaders@buske.com') -and
                $Mgt.Contains('jmartinez_contractor@gamerpackaging.com')

    if ([version][string]$Bridge.version -ge [version]'0.1.0.20' -and $Semantic -and -not $OldGuard -and $ZeroGuard -and $MultiGuard -and $Evidence) {
        Add-LedgerRow 'Routing' 'Semantic effective-recipient bridge' 'VALIDATED PARITY' "Bridge $($Bridge.version) contains semantic unique-match resolver, zero/multiple guards, and retained ANCH/BALLCOR/HWAHSIA evidence."
    }
    else {
        Add-LedgerRow 'Routing' 'Semantic effective-recipient bridge' 'PARITY BLOCKER' "Bridge $($Bridge.version): Semantic=$Semantic OldEntryNoGuard=$OldGuard ZeroGuard=$ZeroGuard MultiGuard=$MultiGuard Evidence=$Evidence" 'Repair bridge semantic targeting before cutover.'
    }
}

Section '4. CROSS-DOCUMENT RECIPIENT AUTHORITY'

$AuthorityScript = Find-Script @('Audit-GPI-All-Document-Recipient-Authority.ps1')
if ($null -ne $AuthorityScript) {
    Write-Host "Running read-only authority audit: $AuthorityScript"
    & $AuthorityScript
    if ($LASTEXITCODE -ne 0) {
        Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'PARITY BLOCKER' "Recipient authority audit exited $LASTEXITCODE." 'Resolve authority audit failure.'
    }
}
else {
    Write-Host 'Recipient authority audit script not found; using latest existing artifact if present.' -ForegroundColor Yellow
}

$AuthorityCsv = Get-LatestRecipientAuthorityCsv
if ($null -eq $AuthorityCsv) {
    Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'PARITY RISK' 'No Recipient_Authority_Audit.csv artifact found.' 'Run recipient authority audit before cutover.'
}
else {
    $Rows = @(Import-Csv -LiteralPath $AuthorityCsv.FullName)
    $InScopePatterns = @(
        'Purchase Order - Warehouse',
        'Purchase Order - Drop Ship',
        'Warehouse Receiving Notice',
        'Purchase Credit Memo',
        'Purchase Return Order',
        'Purchase Return Pick Ticket',
        'Pick Ticket',
        'Transfer Pick List',
        'Transfer Receipt Notice',
        'Transfer Shipment'
    )

    $InScope = @($Rows | Where-Object {
        $Doc = [string]$_.DocumentType
        $Matched = $false
        foreach ($P in $InScopePatterns) {
            if ($Doc -like "*$P*") { $Matched = $true; break }
        }
        $Matched
    })

    $Blockers = @($InScope | Where-Object { $_.Classification -eq 'PARITY BLOCKER' })
    $Risks = @($InScope | Where-Object { $_.Classification -eq 'PARITY RISK' })
    $Validated = @($InScope | Where-Object { $_.Classification -eq 'VALIDATED PARITY' })

    $Evidence = "Artifact=$($AuthorityCsv.FullName); InScope=$($InScope.Count); Validated=$($Validated.Count); Risks=$($Risks.Count); Blockers=$($Blockers.Count)"

    if ($Blockers.Count -gt 0) {
        Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'PARITY BLOCKER' $Evidence 'Resolve every in-scope recipient-authority blocker.'
    }
    elseif ($Risks.Count -gt 0) {
        Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'PARITY RISK' $Evidence 'Close or explicitly accept remaining in-scope recipient-authority risks.'
    }
    elseif ($InScope.Count -gt 0) {
        Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'VALIDATED PARITY' $Evidence
    }
    else {
        Add-LedgerRow 'Recipients' 'AP/Warehouse send-path recipient authority' 'PARITY RISK' $Evidence 'Audit did not discover any in-scope AP/Warehouse send paths.'
    }
}

Section '5. EXACT PO BUCKET EVIDENCE SOURCE'

$POAuditMgt = Join-Path $MainRoot 'src\codeunit\GPIPOBucketEvidenceAuditMgt.Codeunit.al'
if (-not (Test-Path -LiteralPath $POAuditMgt)) {
    Add-LedgerRow 'Recipients' 'Exact PO To/CC/BCC evidence gate' 'PARITY RISK' 'PO bucket evidence management codeunit not found.' 'Retain or restore exact Production-evidence audit before cutover.'
}
else {
    $POText = Get-Content -LiteralPath $POAuditMgt -Raw
    $Required = @(
        "TempAudit.Result := 'MATCH';",
        "TempAudit.Result := 'PARITY BLOCKER';",
        "TempAudit.Result := 'SOURCE NOT FOUND';",
        'WarehouseEmail.ResolveDraftRecipients(',
        'DropShipEmail.ResolveDraftRecipients(',
        'evermansiteleaders@buske.com',
        're3uoffice@reiles.com',
        'everyone-bsw@trilliantfood.com'
    )

    $Missing = @($Required | Where-Object { -not $POText.Contains($_) })
    if ($Missing.Count -eq 0) {
        Add-LedgerRow 'Recipients' 'Exact PO To/CC/BCC evidence gate' 'VALIDATED PARITY' 'Exact retained Production bucket evidence audit and both PO resolvers are present in current source.'
    }
    else {
        Add-LedgerRow 'Recipients' 'Exact PO To/CC/BCC evidence gate' 'PARITY BLOCKER' ('Missing required audit markers: ' + ($Missing -join '; ')) 'Restore exact PO bucket evidence gate.'
    }
}

Section '6. DOCUMENT STORAGE / SENT-DOCUMENT EXPOSURE'

$RecordDocMgt = Join-Path $MainRoot 'src\codeunit\GPIRecordDocumentMgt.Codeunit.al'
if (-not (Test-Path -LiteralPath $RecordDocMgt)) {
    Add-LedgerRow 'Storage/Traceability' 'Sent document exposure in Gamer Documents' 'PARITY BLOCKER' 'GPIRecordDocumentMgt.Codeunit.al not found.' 'Restore sent-document record exposure before cutover.'
}
else {
    $DocText = Get-Content -LiteralPath $RecordDocMgt -Raw
    $Markers = @(
        'AddSentDocumentsToBuffer(',
        'Record "GPI Document Delivery Log"',
        'Source SystemId',
        'Status::Sent'
    )

    $Missing = @($Markers | Where-Object { -not $DocText.Contains($_) })
    if ($Missing.Count -eq 0) {
        Add-LedgerRow 'Storage/Traceability' 'Sent document exposure in Gamer Documents' 'VALIDATED PARITY' 'Record-document manager exposes sent delivery-log records by source SystemId.'
    }
    else {
        Add-LedgerRow 'Storage/Traceability' 'Sent document exposure in Gamer Documents' 'PARITY BLOCKER' ('Missing source markers: ' + ($Missing -join '; ')) 'Repair sent-document exposure.'
    }
}

Section '7. MIGRATION / RECOVERABILITY AUDIT AVAILABILITY'

$MigrationAudit = Find-Script @('Audit-GPI-Zetadocs-Migration-Speed-Stability.ps1')
if ($null -eq $MigrationAudit) {
    Add-LedgerRow 'Migration/Recoverability' 'Migration stability diagnostic available' 'PARITY RISK' 'Migration speed/stability audit script not found.' 'Restore migration stability audit and run before cutover.'
}
else {
    Add-LedgerRow 'Migration/Recoverability' 'Migration stability diagnostic available' 'VALIDATED PARITY' "Read-only migration diagnostic available: $MigrationAudit"
}

Section '8. WRITE SEP 20 PARITY LEDGER'

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutDir = Join-Path $ReportRoot $Stamp
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$Csv = Join-Path $OutDir 'Sep20_AP_Warehouse_Parity_Ledger.csv'
$Txt = Join-Path $OutDir 'Sep20_AP_Warehouse_Parity_Summary.txt'

$Ledger | Export-Csv -LiteralPath $Csv -NoTypeInformation -Encoding UTF8

$BlockerCount = @($Ledger | Where-Object { $_.Classification -eq 'PARITY BLOCKER' }).Count
$RiskCount = @($Ledger | Where-Object { $_.Classification -eq 'PARITY RISK' }).Count
$ValidatedCount = @($Ledger | Where-Object { $_.Classification -eq 'VALIDATED PARITY' }).Count

$Summary = @(
    'GPI September 20 AP/Warehouse Cutover Hard Gate',
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Environment: $Environment",
    "Branch: $Branch",
    '',
    "Parity blockers: $BlockerCount",
    "Parity risks: $RiskCount",
    "Validated parity: $ValidatedCount",
    '',
    'GATES'
)

foreach ($Row in $Ledger) {
    $Summary += "[$($Row.Classification)] $($Row.Area) :: $($Row.Gate) :: $($Row.Evidence)"
    if (-not [string]::IsNullOrWhiteSpace($Row.NextAction)) {
        $Summary += "  NEXT: $($Row.NextAction)"
    }
}

$Summary | Set-Content -LiteralPath $Txt -Encoding UTF8

$Ledger | Format-Table Area,Gate,Classification,Evidence -AutoSize -Wrap

Write-Host ''
Write-Host "Ledger  : $Csv"
Write-Host "Summary : $Txt"
Write-Host ''

if ($BlockerCount -gt 0) {
    Write-Host "CUTOVER HARD GATE: FAIL ($BlockerCount PARITY BLOCKER(S))" -ForegroundColor Red
    exit 2
}

if ($RiskCount -gt 0) {
    Write-Host "CUTOVER HARD GATE: NO BLOCKERS, BUT $RiskCount PARITY RISK(S) REMAIN" -ForegroundColor Yellow
    exit 1
}

Write-Host 'CUTOVER HARD GATE: PASS - ALL CHECKED AP/WAREHOUSE GATES VALIDATED' -ForegroundColor Green
exit 0
