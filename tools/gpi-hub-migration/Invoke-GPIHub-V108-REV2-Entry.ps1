#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedName = 'W117105_Strategic Warehousing_122625_.pdf'
$ExpectedSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$Downloads = Join-Path $env:USERPROFILE 'Downloads'
$Exact = Join-Path $Downloads $ExpectedName

function Test-And-NormalizeCandidate {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $sha = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    catch {
        return $false
    }
    if ($sha -ne $ExpectedSha) { return $false }
    if ((Resolve-Path -LiteralPath $Path).Path -ne (Resolve-Path -LiteralPath (Split-Path -Parent $Exact)).Path + '\' + (Split-Path -Leaf $Exact)) {
        Copy-Item -LiteralPath $Path -Destination $Exact -Force
        Write-Host "V108_REV2_NORMALIZED_CORPUS_FILENAME=$(Split-Path -Leaf $Path) -> $ExpectedName" -ForegroundColor Cyan
    }
    return $true
}

$found = $false
if (Test-Path -LiteralPath $Exact -PathType Leaf) {
    $found = Test-And-NormalizeCandidate -Path $Exact
}

if (-not $found) {
    $candidates = @(Get-ChildItem -LiteralPath $Downloads -File -Filter 'W117105*.pdf' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    foreach ($m in $candidates) {
        if (Test-And-NormalizeCandidate -Path $m.FullName) {
            $found = $true
            break
        }
    }
}

if (-not $found) {
    # Final bounded fallback for browsers that rename the download unexpectedly.
    $recentPdfs = @(Get-ChildItem -LiteralPath $Downloads -File -Filter '*.pdf' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-6) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 50)
    foreach ($m in $recentPdfs) {
        if (Test-And-NormalizeCandidate -Path $m.FullName) {
            $found = $true
            break
        }
    }
}

if ($found) {
    Write-Host 'V108_REV2_CORPUS_SHA_MATCH=PASS' -ForegroundColor Green
}
else {
    Write-Host 'V108_REV2_CORPUS_SHA_MATCH=NOT_FOUND' -ForegroundColor Yellow
}

Write-Host 'V108_REV2_ENTRY_WRAPPER=PASS' -ForegroundColor Cyan
$Main = Join-Path $PSScriptRoot 'Invoke-GPIHub-V108-Durable-Warehouse-Strategic-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Main -PathType Leaf)) { throw "V108 main script missing: $Main" }
& $Main
