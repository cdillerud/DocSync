#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TargetPath = 'scripts/Discover-GPIOrderIntakeIdentityDiagnostics-0.1.0.9-PRE-REV3.ps1'
$ExpectedBlob = '4aee8fa393f40a09bfab74a99e4518978b8446c9'

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$TargetPath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed REV3 diagnostics script at HEAD:$TargetPath"
    }
    if ($headBlob -ne $ExpectedBlob) {
        throw "Committed REV3 diagnostics blob changed. Expected $ExpectedBlob; got $headBlob."
    }

    $source = (& git show "HEAD:$TargetPath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) { throw 'Committed REV3 diagnostics script is empty.' }

    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) {
            Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red
        }
        throw "REV3 diagnostics script has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    $forbidden = @(
        '(?i)Invoke-RestMethod\s+-Method\s+(Post|Patch|Put|Delete)',
        '(?i)Invoke-WebRequest\s+-Method\s+(Post|Patch|Put|Delete)',
        '(?i)createValidatedDraft',
        '(?i)/salesOrders',
        '(?i)extensionUpload',
        '(?i)Microsoft\.NAV\.upload'
    )
    foreach ($pattern in $forbidden) {
        if ($source -match $pattern) { throw "Forbidden mutation/action marker found in REV3 diagnostics source: $pattern" }
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.9 - IDENTITY DIAGNOSTICS REV3 GUARDED LAUNCH' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed REV3 blob   : $ExpectedBlob"
    Write-Host 'PowerShell syntax gate : PASS' -ForegroundColor Green
    Write-Host 'Mutation/action scan   : PASS / GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation     : NONE' -ForegroundColor Green
    Write-Host 'Business-data writes   : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action     : NOT PRESENT' -ForegroundColor Green
    Write-Host 'Production             : HARD BLOCKED by target script' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    & (Join-Path $RepoRoot $TargetPath)
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "REV3 diagnostics script exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
