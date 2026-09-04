#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TargetPath = 'scripts/Discover-GPIOrderIntakeCustomerPdfPriceDateAuthority-PRE.ps1'
$ExpectedBlob = '929ce46214422a1d71078610d0143a7ddc62f5e2'

Push-Location $RepoRoot
try {
    $blob = (& git rev-parse "HEAD:$TargetPath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) { throw "Could not resolve committed target at HEAD:$TargetPath" }
    if ($blob -ne $ExpectedBlob) { throw "Committed price/date authority target changed. Expected $ExpectedBlob; got $blob." }

    $source = (& git show "HEAD:$TargetPath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) { throw 'Committed price/date authority target was empty.' }

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) { Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red }
        throw "Price/date authority source has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    $badVariables = @($ast.FindAll({
        param($node)
        if ($node -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $false }
        $name = $node.VariablePath.UserPath
        return $name.EndsWith('?') -or $name.EndsWith(':')
    }, $true))
    if ($badVariables.Count -ne 0) {
        foreach ($node in $badVariables) { Write-Host ("STRICTMODE_VARIABLE_ERROR|token={0}" -f $node.Extent.Text) -ForegroundColor Red }
        throw "Price/date authority source contains $($badVariables.Count) suspicious StrictMode variable token(s). BC was not contacted."
    }

    $forbidden = [ordered]@{
        'POST request' = '(?i)-Method\s+Post\b'
        'PATCH request' = '(?i)-Method\s+Patch\b'
        'PUT request' = '(?i)-Method\s+Put\b'
        'DELETE request' = '(?i)-Method\s+Delete\b'
        'Order Intake create action' = '(?i)createValidatedDraft'
        'Release action' = '(?i)\brelease\s*\('
        'Ship action' = '(?i)\bship\s*\('
        'Invoice action' = '(?i)\binvoice\s*\('
        'Post action' = '(?i)\bpost\s*\('
    }
    foreach ($entry in $forbidden.GetEnumerator()) {
        if ($source -match $entry.Value) { throw "Forbidden behavior found before execution: $($entry.Key)" }
    }

    foreach ($required in @(
        "`$ExpectedVersion   = '0.1.0.10'",
        "`$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'",
        "`$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'",
        "`$BernerSourcePrice = [decimal]243.43",
        "`$HerdezSourcePrice = [decimal]225.75",
        'HTTP methods         : GET ONLY',
        'Extension mutation   : NONE',
        'Business-data writes : NONE',
        'Sales-order action   : NOT CALLED / NOT PRESENT',
        'Write authorization    : NOT GRANTED'
    )) {
        if ($source.IndexOf($required,[StringComparison]::Ordinal) -lt 0) { throw "Required safety/evidence marker missing: $required" }
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF PRICE + DATE AUTHORITY GUARDED LAUNCH' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed target blob    : $ExpectedBlob"
    Write-Host 'PowerShell syntax gate   : PASS' -ForegroundColor Green
    Write-Host 'StrictMode variable gate : PASS' -ForegroundColor Green
    Write-Host 'Mutation/action scan     : PASS / GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation       : NONE' -ForegroundColor Green
    Write-Host 'Business-data writes     : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action       : NOT PRESENT' -ForegroundColor Green
    Write-Host 'Installed app required   : GPI Order Intake 0.1.0.10'
    Write-Host 'Target                   : PRE_GAMERDOCS_CUTOVER_20260831 / Gamer Packaging'
    Write-Host 'Production               : HARD BLOCKED by target script' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $target = Join-Path $RepoRoot $TargetPath
    & $target
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Price/date authority target exited with code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
