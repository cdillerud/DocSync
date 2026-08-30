#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedName = 'W117105_Strategic Warehousing_122625_.pdf'
$ExpectedSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$Downloads = Join-Path $env:USERPROFILE 'Downloads'
$Exact = Join-Path $Downloads $ExpectedName

if (-not (Test-Path -LiteralPath $Exact -PathType Leaf)) {
    $matches = @(Get-ChildItem -LiteralPath $Downloads -File -Filter 'W117105_Strategic Warehousing_122625_*.pdf' -ErrorAction SilentlyContinue)
    foreach ($m in $matches) {
        $sha = (Get-FileHash -LiteralPath $m.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sha -eq $ExpectedSha) {
            Copy-Item -LiteralPath $m.FullName -Destination $Exact -Force
            Write-Host "V108_REV2_NORMALIZED_CORPUS_FILENAME=$($m.Name) -> $ExpectedName" -ForegroundColor Cyan
            break
        }
    }
}

Write-Host 'V108_REV2_ENTRY_WRAPPER=PASS' -ForegroundColor Cyan
$Main = Join-Path $PSScriptRoot 'Invoke-GPIHub-V108-Durable-Warehouse-Strategic-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Main -PathType Leaf)) { throw "V108 main script missing: $Main" }
& $Main
