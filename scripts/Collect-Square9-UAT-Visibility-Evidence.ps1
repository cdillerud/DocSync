[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HubBaseUrl,
    [Parameter(Mandatory)][string]$APDocumentNo,
    [Parameter(Mandatory)][Guid]$APSystemId,
    [Parameter(Mandatory)][string]$WarehouseDocumentNo,
    [Parameter(Mandatory)][Guid]$WarehouseSystemId,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$OutputRoot = (Join-Path $env:USERPROFILE 'Downloads\Square9-UAT-Visibility-Evidence')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    throw "UAT VISIBILITY EVIDENCE FAILED: $Message"
}

function Write-Section {
    param([string]$Title)
    Write-Host "`n================================================================================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "================================================================================================================" -ForegroundColor Cyan
}

function Normalize-HubBaseUrl {
    param([string]$Value)

    $trimmed = $Value.Trim().TrimEnd('/')
    $uri = $null
    if (-not [Uri]::TryCreate($trimmed, [UriKind]::Absolute, [ref]$uri)) {
        Fail "HubBaseUrl is not an absolute URI: $Value"
    }
    if ($uri.Scheme -ne 'https') {
        Fail "HubBaseUrl must use HTTPS. Received scheme '$($uri.Scheme)'."
    }
    if ($uri.Query -or $uri.Fragment) {
        Fail 'HubBaseUrl must not contain a query string or fragment.'
    }
    if ($uri.AbsolutePath.TrimEnd('/') -notmatch '(?i)/api$') {
        Fail "HubBaseUrl must end in /api because Business Central uses that API base. Received '$trimmed'."
    }
    return $trimmed
}

function Get-GitEvidence {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $Path '.git'))) {
        Fail "RepoRoot is not a Git working tree: $Path"
    }

    Push-Location $Path
    try {
        $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
        $head = (& git rev-parse HEAD).Trim()
        $dirty = @(& git status --porcelain)
        if ($LASTEXITCODE -ne 0) {
            Fail 'Unable to read Git repository state.'
        }
        if ($branch -ne 'feature/square9-parity-systemid-gate') {
            Fail "Evidence must be collected from feature/square9-parity-systemid-gate. Current branch: $branch"
        }
        if ($dirty.Count -gt 0) {
            Fail 'Working tree is not clean. Commit or stash changes before collecting cutover evidence.'
        }
        return [ordered]@{
            branch = $branch
            head = $head
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-VisibilityRead {
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$Entity,
        [Parameter(Mandatory)][string]$DocumentNo,
        [Parameter(Mandatory)][Guid]$SystemId,
        [Parameter(Mandatory)][string]$EvidencePath,
        [Parameter(Mandatory)][string]$Label
    )

    $encodedEntity = [Uri]::EscapeDataString($Entity)
    $encodedDocumentNo = [Uri]::EscapeDataString($DocumentNo)
    $encodedSystemId = [Uri]::EscapeDataString($SystemId.ToString())
    $url = "$BaseUrl/gpi-integration/document-links/$encodedEntity/$encodedDocumentNo?bc_system_id=$encodedSystemId"

    Write-Host "$Label GET : $url"

    # READ ONLY by design. Do not add POST, PUT, PATCH, or DELETE to this evidence collector.
    $response = Invoke-WebRequest -Uri $url -Method Get -Headers @{ Accept = 'application/json' }
    if ($response.StatusCode -ne 200) {
        Fail "$Label visibility read returned HTTP $($response.StatusCode)."
    }

    [System.IO.File]::WriteAllText($EvidencePath, [string]$response.Content, [System.Text.UTF8Encoding]::new($false))

    try {
        $payload = $response.Content | ConvertFrom-Json
    }
    catch {
        Fail "$Label response was not valid JSON: $($_.Exception.Message)"
    }

    if ($null -eq $payload.documents) {
        Fail "$Label response did not contain a documents collection."
    }

    $documents = @($payload.documents)
    if ($documents.Count -lt 1) {
        Fail "$Label exact-record lookup returned zero linked documents for $Entity / $DocumentNo / $SystemId."
    }

    foreach ($document in $documents) {
        $webUrl = [string]$document.sharepoint_web_url
        if ([string]::IsNullOrWhiteSpace($webUrl)) {
            $webUrl = [string]$document.sharepoint_url
        }
        if ([string]::IsNullOrWhiteSpace($webUrl)) {
            Fail "$Label returned a linked document without a SharePoint URL."
        }
    }

    $hash = (Get-FileHash -LiteralPath $EvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    return [ordered]@{
        label = $Label
        entity = $Entity
        document_no = $DocumentNo
        system_id = $SystemId.ToString()
        request_url = $url
        http_status = [int]$response.StatusCode
        document_count = $documents.Count
        evidence_file = [System.IO.Path]::GetFileName($EvidencePath)
        sha256 = $hash
    }
}

Write-Section '1. SAFETY AND REPOSITORY CHECK'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$HubBaseUrl = Normalize-HubBaseUrl -Value $HubBaseUrl
$git = Get-GitEvidence -Path $RepoRoot
Write-Host "Hub     : $HubBaseUrl"
Write-Host "Branch  : $($git.branch)"
Write-Host "HEAD    : $($git.head)"
Write-Host 'HTTP mode: GET ONLY' -ForegroundColor Green

Write-Section '2. CREATE EVIDENCE PACKAGE'
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
$evidenceDir = Join-Path $OutputRoot "Visibility-$timestamp"
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null

$apFile = Join-Path $evidenceDir 'AP-PurchaseInvoice-FactBox.json'
$warehouseFile = Join-Path $evidenceDir 'Warehouse-PostedSalesShipment-FactBox.json'

Write-Section '3. AP EXACT-RECORD VISIBILITY'
$apResult = Invoke-VisibilityRead `
    -BaseUrl $HubBaseUrl `
    -Entity 'purchaseInvoices' `
    -DocumentNo $APDocumentNo `
    -SystemId $APSystemId `
    -EvidencePath $apFile `
    -Label 'AP Purchase Invoice'
Write-Host "AP linked documents: $($apResult.document_count)" -ForegroundColor Green

Write-Section '4. WAREHOUSE EXACT-RECORD VISIBILITY'
$warehouseResult = Invoke-VisibilityRead `
    -BaseUrl $HubBaseUrl `
    -Entity 'postedSalesShipments' `
    -DocumentNo $WarehouseDocumentNo `
    -SystemId $WarehouseSystemId `
    -EvidencePath $warehouseFile `
    -Label 'Warehouse Posted Sales Shipment'
Write-Host "Warehouse linked documents: $($warehouseResult.document_count)" -ForegroundColor Green

Write-Section '5. WRITE MANIFEST'
$manifest = [ordered]@{
    evidence_type = 'Square9 AP/Warehouse UAT FactBox visibility'
    collected_utc = (Get-Date).ToUniversalTime().ToString('o')
    hub_base_url = $HubBaseUrl
    repository = [ordered]@{
        branch = $git.branch
        head = $git.head
    }
    safety = [ordered]@{
        http_methods_used = @('GET')
        business_central_writes = $false
        sharepoint_writes = $false
        production_activation = $false
    }
    samples = @($apResult, $warehouseResult)
    result = 'PASS'
}

$manifestPath = Join-Path $evidenceDir 'manifest.json'
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $evidenceDir 'manifest.sha256') -Value "$manifestHash  manifest.json" -Encoding ascii

Write-Host "Evidence folder : $evidenceDir"
Write-Host "Manifest SHA256: $manifestHash"
Write-Host 'PASS: AP and Warehouse exact-record FactBox visibility returned linked SharePoint documents.' -ForegroundColor Green
