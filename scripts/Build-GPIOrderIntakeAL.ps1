#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$ProjectPath,
    [string]$PackageCachePath,
    [string]$AlcPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($ProjectPath)) {
    $ProjectPath = Join-Path $RepoRoot 'order-intake-bc'
}
$ProjectPath = (Resolve-Path $ProjectPath).Path

$AppJsonPath = Join-Path $ProjectPath 'app.json'
if (-not (Test-Path $AppJsonPath)) {
    throw "Missing app.json: $AppJsonPath"
}

$app = Get-Content $AppJsonPath -Raw | ConvertFrom-Json

$ExpectedAppId = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedName = 'GPI Order Intake'
$ExpectedPublisher = 'Gamer Packaging Inc'
$ExpectedVersion = '0.1.0.0'

if ([string]$app.id -ne $ExpectedAppId) { throw "Unexpected app id: $($app.id)" }
if ([string]$app.name -ne $ExpectedName) { throw "Unexpected app name: $($app.name)" }
if ([string]$app.publisher -ne $ExpectedPublisher) { throw "Unexpected publisher: $($app.publisher)" }
if ([string]$app.version -ne $ExpectedVersion) { throw "Unexpected version: $($app.version)" }
if ($app.idRanges.Count -ne 1 -or [int]$app.idRanges[0].from -ne 71200 -or [int]$app.idRanges[0].to -ne 71299) {
    throw 'Unexpected Order Intake object range. Expected exactly 71200..71299.'
}

$sourceFiles = @(Get-ChildItem (Join-Path $ProjectPath 'src') -Filter '*.al' -File -Recurse)
if ($sourceFiles.Count -lt 5) {
    throw "Expected at least 5 AL source files; found $($sourceFiles.Count)."
}

$sourceText = ($sourceFiles | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"

$requiredMarkers = @(
    'PRE_GAMERDOCS_CUTOVER_20260831',
    'AITEST-',
    'IsSandbox()',
    'GetEnvironmentName()',
    'UpdateUnitPrice',
    'Unit Price',
    'GPI Order Intake Authority'
)
foreach ($marker in $requiredMarkers) {
    if ($sourceText.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Required Phase-0 safety/authority marker is missing: $marker"
    }
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
    if ($sourceText -match $entry.Value) {
        throw "Forbidden Phase-0 AL behavior detected: $($entry.Key)"
    }
}

if ([string]::IsNullOrWhiteSpace($AlcPath)) {
    $vscodeRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
    if (Test-Path $vscodeRoot) {
        $alcCandidate = Get-ChildItem $vscodeRoot -Directory -Filter 'ms-dynamics-smb.al-*' -ErrorAction SilentlyContinue |
            ForEach-Object {
                Get-ChildItem $_.FullName -Filter 'alc.exe' -File -Recurse -ErrorAction SilentlyContinue
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($alcCandidate) {
            $AlcPath = $alcCandidate.FullName
        }
    }
}

if ([string]::IsNullOrWhiteSpace($AlcPath) -or -not (Test-Path $AlcPath)) {
    throw 'Could not locate alc.exe. Pass -AlcPath explicitly or install/enable the Microsoft AL Language VS Code extension.'
}

if ([string]::IsNullOrWhiteSpace($PackageCachePath)) {
    $knownCandidates = @(
        (Join-Path $ProjectPath '.alpackages'),
        (Join-Path $RepoRoot 'bc-extension\.alpackages'),
        (Join-Path $RepoRoot 'packaging-catalog-bc\.alpackages'),
        (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DocSync-V69-CommercialFederation\packaging-catalog-bc\.alpackages'),
        (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DocSync-PackagingCatalog\packaging-catalog-bc\.alpackages'),
        (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DocSync-Zetadocs\bc-extension\zetadocs-replacement\.alpackages')
    )

    foreach ($candidate in $knownCandidates) {
        if ((Test-Path $candidate) -and @(Get-ChildItem $candidate -Filter '*.app' -File -ErrorAction SilentlyContinue).Count -gt 0) {
            $PackageCachePath = (Resolve-Path $candidate).Path
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($PackageCachePath) -or -not (Test-Path $PackageCachePath)) {
    throw @'
Could not locate an AL .alpackages symbol cache.
Pass -PackageCachePath explicitly, pointing to a symbol cache from a current Business Central extension worktree.
This build script does not download symbols and does not connect to Business Central.
'@
}

$outputDir = Join-Path $ProjectPath '.output'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$outFile = Join-Path $outputDir 'Gamer Packaging Inc_GPI Order Intake_0.1.0.0.app'
if (Test-Path $outFile) {
    Remove-Item $outFile -Force
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE AL - COMPILE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Project           : $ProjectPath"
Write-Host "App               : $ExpectedName $ExpectedVersion"
Write-Host "App ID            : $ExpectedAppId"
Write-Host 'Object range      : 71200..71299'
Write-Host "AL compiler       : $AlcPath"
Write-Host "Package cache     : $PackageCachePath"
Write-Host "Output            : $outFile"
Write-Host 'Business Central  : NOT CONTACTED' -ForegroundColor Green
Write-Host 'Publish / install : NONE' -ForegroundColor Green
Write-Host 'Production        : NOT TOUCHED' -ForegroundColor Green
Write-Host 'Release/Ship/Post : SOURCE HARD GATE PASS' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

& $AlcPath "/project:$ProjectPath" "/packagecachepath:$PackageCachePath" "/out:$outFile" '/GenerateReportLayout-'
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "AL compile failed with exit code $exitCode."
}
if (-not (Test-Path $outFile)) {
    throw 'AL compiler returned success but output app was not created.'
}

$hash = (Get-FileHash $outFile -Algorithm SHA256).Hash

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE AL COMPILE PASSED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Green
Write-Host "App package : $outFile"
Write-Host "SHA256      : $hash"
Write-Host 'Publish      : NONE'
Write-Host 'BC writes    : NONE'
Write-Host 'Production   : NO'
