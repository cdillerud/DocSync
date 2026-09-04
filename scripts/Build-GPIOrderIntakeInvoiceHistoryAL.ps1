#requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackageCachePath,
    [string]$ProjectPath,
    [string]$AlcPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($ProjectPath)) { $ProjectPath = Join-Path $RepoRoot 'order-intake-bc' }
$ProjectPath = (Resolve-Path $ProjectPath).Path
$PackageCachePath = (Resolve-Path $PackageCachePath).Path
$AppJsonPath = Join-Path $ProjectPath 'app.json'

$app = Get-Content $AppJsonPath -Raw | ConvertFrom-Json
$ExpectedAppId = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedName = 'GPI Order Intake'
$ExpectedPublisher = 'Gamer Packaging Inc'
$ExpectedVersion = '0.1.0.5'
$BoyerAppId = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerName = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion = '25.0.0.13'

if ([string]$app.id -ne $ExpectedAppId) { throw 'Unexpected app id.' }
if ([string]$app.name -ne $ExpectedName) { throw 'Unexpected app name.' }
if ([string]$app.publisher -ne $ExpectedPublisher) { throw 'Unexpected app publisher.' }
if ([string]$app.version -ne $ExpectedVersion) { throw "Unexpected app version: $($app.version)" }
if ($app.idRanges.Count -ne 1 -or [int]$app.idRanges[0].from -ne 71200 -or [int]$app.idRanges[0].to -ne 71299) { throw 'Unexpected object range.' }

$deps = @($app.dependencies)
$boyerDeps = @($deps | Where-Object {
    [string]$_.id -eq $BoyerAppId -and [string]$_.name -eq $BoyerName -and [string]$_.publisher -eq $BoyerPublisher -and [string]$_.version -eq $BoyerVersion
})
if ($boyerDeps.Length -ne 1) { throw 'Exact Boyer 25.0.0.13 dependency is required.' }

$sourceFiles = @(Get-ChildItem (Join-Path $ProjectPath 'src') -Filter '*.al' -File -Recurse)
$sourceText = ($sourceFiles | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"
foreach ($marker in @(
    'PRE_GAMERDOCS_CUTOVER_20260831',
    'AITEST-',
    'IsSandbox()',
    'UpdateUnitPrice',
    'Customer Item Sales',
    'Sales Invoice Line',
    'GPI Order Intake InvLine Hist'
)) {
    if ($sourceText.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { throw "Required marker missing: $marker" }
}

$forbiddenPatterns = [ordered]@{
    'Explicit COMMIT' = '(?im)^\s*COMMIT\s*;'
    'Sales posting codeunit' = 'Codeunit::\s*"?Sales-Post"?'
    'SendToPosting' = '\.SendToPosting\s*\('
    'Ship flag assignment' = '\.Ship\s*:=\s*true'
    'Invoice flag assignment' = '\.Invoice\s*:=\s*true'
    'Release Sales Document codeunit' = 'Release Sales Document'
}
foreach ($entry in $forbiddenPatterns.GetEnumerator()) {
    if ($sourceText -match $entry.Value) { throw "Forbidden Phase-0 AL behavior detected: $($entry.Key)" }
}

if ([string]::IsNullOrWhiteSpace($AlcPath)) {
    $vscodeRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
    $candidate = Get-ChildItem $vscodeRoot -Directory -Filter 'ms-dynamics-smb.al-*' -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem $_.FullName -Filter 'alc.exe' -File -Recurse -ErrorAction SilentlyContinue } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($candidate) { $AlcPath = $candidate.FullName }
}
if ([string]::IsNullOrWhiteSpace($AlcPath) -or -not (Test-Path $AlcPath)) { throw 'Could not locate alc.exe.' }

$boyerSymbols = @(Get-ChildItem $PackageCachePath -Filter '*.app' -File | Where-Object { $_.Name -match 'Boyer.*25\.0\.0\.13' })
if ($boyerSymbols.Length -lt 1) { throw 'Package cache does not contain Boyer 25.0.0.13 symbols.' }

$outputDir = Join-Path $ProjectPath '.output'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$outFile = Join-Path $outputDir 'Gamer Packaging Inc_GPI Order Intake_0.1.0.5.app'
Remove-Item $outFile -Force -ErrorAction SilentlyContinue

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.5 - INVOICE HISTORY DIAGNOSTIC COMPILE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Project          : $ProjectPath"
Write-Host "Package cache    : $PackageCachePath"
Write-Host "Output           : $outFile"
Write-Host 'Business Central : NOT CONTACTED' -ForegroundColor Green
Write-Host 'Publish/install  : NONE' -ForegroundColor Green
Write-Host 'Production       : NOT TOUCHED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

& $AlcPath "/project:$ProjectPath" "/packagecachepath:$PackageCachePath" "/out:$outFile" '/GenerateReportLayout-'
if ($LASTEXITCODE -ne 0) { throw "AL compile failed with exit code $LASTEXITCODE." }
if (-not (Test-Path $outFile)) { throw 'Compiler returned success but package was not created.' }
$hash = (Get-FileHash $outFile -Algorithm SHA256).Hash

Write-Host ''
Write-Host 'GPI ORDER INTAKE 0.1.0.5 COMPILE: PASS' -ForegroundColor Green
Write-Host "Package : $outFile"
Write-Host "SHA256  : $hash"
Write-Host 'BC writes: NONE'
