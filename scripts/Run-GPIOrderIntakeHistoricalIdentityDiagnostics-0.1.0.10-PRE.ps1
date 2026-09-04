#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TargetPath = 'scripts/Publish-Discover-GPIOrderIntakeHistoricalIdentityDiagnostics-0.1.0.10-PRE.ps1'
$ExpectedBlob = '260fe4ca53bdd82b356d2926b49fdc0fe1d0aa70'

Push-Location $RepoRoot
try {
    $blob = (& git rev-parse "HEAD:$TargetPath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) { throw "Could not resolve committed target at HEAD:$TargetPath" }
    if ($blob -ne $ExpectedBlob) { throw "Committed historical diagnostics target changed. Expected $ExpectedBlob; got $blob." }

    $source = (& git show "HEAD:$TargetPath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) { throw 'Committed historical diagnostics target was empty.' }

    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) { Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red }
        throw "Historical diagnostics source has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    $forbidden = [ordered]@{
        'Sales Orders standard endpoint' = '(?i)/salesOrders(?:\?|/|\b)'
        'Order Intake create action' = '(?i)createValidatedDraft'
        'Custom order API entity' = '(?i)orderIntakeOrders'
        'Custom line API entity' = '(?i)orderIntakeLines'
        'DELETE request' = '(?i)-Method\s+Delete\b'
        'PUT request' = '(?i)-Method\s+Put\b'
        'Business-data PATCH via Invoke-RestMethod' = '(?i)Invoke-RestMethod[^\r\n]*-Method\s+Patch\b'
    }
    foreach ($entry in $forbidden.GetEnumerator()) {
        if ($source -match $entry.Value) { throw "Forbidden behavior found before execution: $($entry.Key)" }
    }

    foreach ($required in @(
        "`$ExpectedAppVersion  = '0.1.0.10'",
        "`$ExpectedPackageHash = 'C398F0D44795FCF1111F8E4C32E9B94052CF96BA7900A4990DF91F66845BADB0'",
        "`$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'",
        "`$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'",
        "`$BernerOrder      = '114600'",
        "`$HerdezItem       = '20113526'",
        'Business-data writes : NONE',
        'Sales-order action   : NOT CALLED / NOT PRESENT IN THIS HARNESS',
        'Write authorization     : NOT GRANTED'
    )) {
        if ($source.IndexOf($required,[StringComparison]::Ordinal) -lt 0) { throw "Required safety/evidence marker missing: $required" }
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.10 - HISTORICAL IDENTITY DIAGNOSTICS GUARDED LAUNCH' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed target blob    : $ExpectedBlob"
    Write-Host 'PowerShell syntax gate   : PASS' -ForegroundColor Green
    Write-Host 'Sales-order/action scan  : PASS / NOT PRESENT' -ForegroundColor Green
    Write-Host 'Business mutation scan   : PASS / extension deployment only' -ForegroundColor Green
    Write-Host 'Package SHA              : C398F0D44795FCF1111F8E4C32E9B94052CF96BA7900A4990DF91F66845BADB0'
    Write-Host 'Target                    : PRE_GAMERDOCS_CUTOVER_20260831 / Gamer Packaging'
    Write-Host 'Historical reads         : GET ONLY after install'
    Write-Host 'Production               : HARD BLOCKED by target script' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $target = Join-Path $RepoRoot $TargetPath
    & $target -EnableInstall
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Historical identity diagnostics target exited with code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
