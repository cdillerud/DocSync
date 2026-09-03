#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY SYMBOL GET + LOCAL COMPILE. NO EXTENSION UPLOAD/INSTALL. NO BUSINESS-DATA READ/WRITE.
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'

$GpiAppId      = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$GpiAppName    = 'GPI Order Intake'
$GpiPublisher  = 'Gamer Packaging Inc'
$TargetVersion = '0.1.0.7'

$BoyerAppId     = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName   = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion   = '25.0.0.13'
$BoyerSha256    = '3B514699E7DA387B480436C850652555D8BC5E6564A47DA7A1690B59D93EF7E5'

$RepoRoot    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath = (Resolve-Path (Join-Path $RepoRoot 'order-intake-bc')).Path
$AppJsonPath = Join-Path $ProjectPath 'app.json'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) { return [System.Net.NetworkCredential]::new('', $TokenValue).Password }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is required.' }
    Import-Module Az.Accounts -ErrorAction Stop
    try {
        $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $t = Convert-TokenToString $r.Token
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    catch {}

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $t = Convert-TokenToString $r.Token
    if ([string]::IsNullOrWhiteSpace($t)) { throw 'Could not acquire Business Central token.' }
    return $t
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $u = [Uri]$Uri
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') { throw "Unexpected BC URI blocked: $Uri" }
    if ($Uri.IndexOf($ForbiddenEnv, [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Forbidden legacy sandbox URI blocked.' }
    if ($Uri.IndexOf('/Production/', [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Production URI blocked.' }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Get-InstalledVersionString {
    param([Parameter(Mandatory)]$Extension)
    "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Get-SymbolMajorVersion {
    param([Parameter(Mandatory)][string]$Directory,[Parameter(Mandatory)][string]$PackageStem)
    $matches = @(Get-ChildItem $Directory -Filter "Microsoft_${PackageStem}_*.app" -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match '^Microsoft_.+?_(\d+)\.(\d+)(?:\.|_)') {
            [pscustomobject]@{File=$_.FullName;Major=[int]$Matches[1];Minor=[int]$Matches[2]}
        }
    } | Sort-Object @{Expression='Major';Descending=$true}, @{Expression='Minor';Descending=$true})
    if ($matches.Length -eq 0) { return $null }
    return $matches[0]
}

function Test-CompatibleMicrosoftCache {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path -PathType Container)) { return $false }
    $application = Get-SymbolMajorVersion $Path 'Application'
    $baseApp = Get-SymbolMajorVersion $Path 'Base Application'
    $systemApp = Get-SymbolMajorVersion $Path 'System Application'
    $system = Get-SymbolMajorVersion $Path 'System'
    if ($null -eq $application -or $null -eq $baseApp -or $null -eq $systemApp -or $null -eq $system) { return $false }
    return ($application.Major -ge 24 -and $baseApp.Major -ge 24 -and $systemApp.Major -ge 24 -and $system.Major -ge 24)
}

# ---------------------------------------------------------------------------------------------------------------------
# Local source gate before any BC call.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831' -or $Environment -match '(?i)prod|production') { throw 'Environment pin changed/forbidden.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company pin changed.' }
if (-not (Test-Path $AppJsonPath)) { throw "Missing app.json: $AppJsonPath" }

$app = Get-Content $AppJsonPath -Raw | ConvertFrom-Json
if ([string]$app.id -ne $GpiAppId -or [string]$app.name -ne $GpiAppName -or [string]$app.publisher -ne $GpiPublisher -or [string]$app.version -ne $TargetVersion) {
    throw 'GPI Order Intake app identity/version gate failed.'
}
if (@($app.dependencies).Length -ne 1) { throw 'Expected exactly one dependency.' }
$dep = $app.dependencies[0]
if ([string]$dep.id -ne $BoyerAppId -or [string]$dep.name -ne $BoyerAppName -or [string]$dep.publisher -ne $BoyerPublisher -or [string]$dep.version -ne $BoyerVersion) {
    throw 'Boyer dependency hard pin changed.'
}
if (@($app.idRanges).Length -ne 1 -or [int]$app.idRanges[0].from -ne 71200 -or [int]$app.idRanges[0].to -ne 71299) {
    throw 'Unexpected object range. Expected exactly 71200..71299.'
}

$sourceFiles = @(Get-ChildItem (Join-Path $ProjectPath 'src') -Filter '*.al' -File -Recurse)
if ($sourceFiles.Length -lt 11) { throw "Expected at least 11 AL source files; found $($sourceFiles.Length)." }
$sourceText = ($sourceFiles | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"

$requiredMarkers = @(
    'PRE_GAMERDOCS_CUTOVER_20260831',
    'AITEST-',
    'IsSandbox()',
    'GetEnvironmentName()',
    'GPI Order Intake Resolver',
    'ResolveGiovanniUnitPrice',
    'Sales Invoice Line',
    'Customer Item Sales',
    'two most recent exact-context posted invoices disagree',
    'C-9874-10001833',
    'C-8682-12013925'
)
foreach ($marker in $requiredMarkers) {
    if ($sourceText.IndexOf($marker,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw "Required resolver/safety marker missing: $marker" }
}

$forbiddenPatterns = [ordered]@{
    'Explicit COMMIT'='(?im)^\s*COMMIT\s*;'
    'Standard UpdateUnitPrice call'='\.UpdateUnitPrice\s*\('
    'Sales posting codeunit'='Codeunit::\s*"?Sales-Post"?'
    'SendToPosting'='\.SendToPosting\s*\('
    'Ship flag assignment'='\.Ship\s*:=\s*true'
    'Invoice flag assignment'='\.Invoice\s*:=\s*true'
    'Release Sales Document'='Release Sales Document'
}
foreach ($entry in $forbiddenPatterns.GetEnumerator()) {
    if ($sourceText -match $entry.Value) { throw "Forbidden Phase-0 behavior detected: $($entry.Key)" }
}

# Locate compiler and Microsoft symbols locally.
$vscodeRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
$alc = $null
if (Test-Path $vscodeRoot) {
    $alc = Get-ChildItem $vscodeRoot -Directory -Filter 'ms-dynamics-smb.al-*' -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem $_.FullName -Filter 'alc.exe' -File -Recurse -ErrorAction SilentlyContinue } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}
if ($null -eq $alc) { throw 'Could not locate alc.exe.' }

$documents = [Environment]::GetFolderPath('MyDocuments')
$candidates = @(
    (Join-Path $ProjectPath '.alpackages'),
    (Join-Path $RepoRoot 'bc-extension\.alpackages'),
    (Join-Path $RepoRoot 'packaging-catalog-bc\.alpackages'),
    (Join-Path $documents 'AL\MappingProj\.alpackages'),
    (Join-Path $documents 'DocSync-V69-CommercialFederation\packaging-catalog-bc\.alpackages'),
    (Join-Path $documents 'DocSync-PackagingCatalog\packaging-catalog-bc\.alpackages'),
    (Join-Path $documents 'DocSync-Zetadocs\bc-extension\zetadocs-replacement\.alpackages')
)
$msCache = $null
foreach ($candidate in $candidates) {
    if (Test-CompatibleMicrosoftCache $candidate) { $msCache=(Resolve-Path $candidate).Path; break }
}
if ([string]::IsNullOrWhiteSpace($msCache)) { throw 'Could not locate a complete Microsoft 24.x-or-newer symbol cache.' }

# Verify exact PRE sandbox and installed Boyer dependency using GET only.
$token = Get-BcToken
$headers = @{Authorization="Bearer $token";Accept='application/json'}
$envs = Invoke-BcGet 'https://api.businesscentral.dynamics.com/environments/v1.2' $headers
$envMatch = @($envs.value | Where-Object {[string]$_.name -eq $Environment})
if ($envMatch.Length -ne 1 -or [string]$envMatch[0].type -ine 'sandbox') { throw 'Exact PRE sandbox verification failed.' }
$envEncoded=[Uri]::EscapeDataString($Environment)
$standardRoot="https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies=Invoke-BcGet "$standardRoot/companies" $headers
$companyMatch=@($companies.value | Where-Object {[string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))})
if ($companyMatch.Length -ne 1) { throw 'Exact Gamer Packaging company verification failed.' }
$automationRoot="https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$extensions=Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
$installed=@($extensions.value | Where-Object {$_.isInstalled -eq $true})
$boyer=@($installed | Where-Object {[string]$_.id -eq $BoyerAppId -and [string]$_.displayName -eq $BoyerAppName -and [string]$_.publisher -eq $BoyerPublisher -and (Get-InstalledVersionString $_) -eq $BoyerVersion})
if ($boyer.Length -ne 1) { throw 'Exact Boyer dependency is not installed.' }

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.7 RESOLVER - PRE SYMBOL GET + LOCAL COMPILE ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $($envMatch[0].type)"
Write-Host "Company            : $CompanyName"
Write-Host "Target app         : $GpiAppName $TargetVersion"
Write-Host "Boyer dependency   : $BoyerAppName $BoyerVersion"
Write-Host "AL compiler        : $($alc.FullName)"
Write-Host "Microsoft symbols  : $msCache"
Write-Host 'BC operations      : GET ENV/COMPANY/EXTENSION/SYMBOL PACKAGE ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data read : NONE' -ForegroundColor Green
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('GPIOrderIntake-ResolverBuild-' + [guid]::NewGuid().ToString('N'))
$tempCache=Join-Path $tempRoot 'alpackages'
[IO.Directory]::CreateDirectory($tempCache) | Out-Null
try {
    foreach ($file in @(Get-ChildItem $msCache -Filter '*.app' -File)) { Copy-Item $file.FullName (Join-Path $tempCache $file.Name) -Force }

    $boyerPath=Join-Path $tempCache 'Boyer And Associates_Boyer And Associates Custom Package_25.0.0.13.app'
    $symbolUri="https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion"
    Assert-BcUri $symbolUri
    Invoke-WebRequest -Method Get -Uri $symbolUri -Headers @{Authorization="Bearer $token"} -OutFile $boyerPath -TimeoutSec 120
    if (-not (Test-Path $boyerPath) -or (Get-Item $boyerPath).Length -le 0) { throw 'Boyer symbol package download failed.' }
    $boyerHash=(Get-FileHash $boyerPath -Algorithm SHA256).Hash
    if ($boyerHash -ne $BoyerSha256) { throw "Boyer package SHA changed: $boyerHash" }

    $outputDir=Join-Path $ProjectPath '.output'
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    $outFile=Join-Path $outputDir 'Gamer Packaging Inc_GPI Order Intake_0.1.0.7.app'
    if (Test-Path $outFile) { Remove-Item $outFile -Force }

    & $alc.FullName "/project:$ProjectPath" "/packagecachepath:$tempCache" "/out:$outFile" '/GenerateReportLayout-'
    if ($LASTEXITCODE -ne 0) { throw "AL compile failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path $outFile)) { throw 'Compiler returned success but package was not created.' }
    $hash=(Get-FileHash $outFile -Algorithm SHA256).Hash

    Write-Host ''
    Write-Host ('='*120) -ForegroundColor Green
    Write-Host 'GPI ORDER INTAKE 0.1.0.7 RESOLVER COMPILE PASSED' -ForegroundColor Green
    Write-Host ('='*120) -ForegroundColor Green
    Write-Host "Package : $outFile"
    Write-Host "SHA256  : $hash"
    Write-Host 'Publish  : NONE'
    Write-Host 'Install  : NONE'
    Write-Host 'BC writes: NONE'
    Write-Host 'Production: NO'
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
