#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TargetPath = Join-Path $PSScriptRoot 'Publish-Discover-GPIOrderIntakeOrderDateDiagnostics-0.1.0.11-PRE.ps1'
$ExpectedTargetBlob = '80888f506acd56b93d979b66f10f4fcc7a6377b6'

if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
    throw "Committed 0.1.0.11 date diagnostics target missing: $TargetPath"
}

$actualBlob = (& git hash-object -- $TargetPath).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git hash-object failed while validating 0.1.0.11 date diagnostics target.' }
if ($actualBlob -ne $ExpectedTargetBlob) {
    throw "Unexpected local 0.1.0.11 diagnostics target blob: $actualBlob. Expected $ExpectedTargetBlob."
}

$source = Get-Content -LiteralPath $TargetPath -Raw
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
$parseErrors = @($parseErrors)
if ($parseErrors.Count -ne 0) {
    foreach ($e in $parseErrors) {
        Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red
    }
    throw "0.1.0.11 diagnostics target has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
}

$suspiciousVars = @($ast.FindAll({
    param($node)
    if ($node -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $false }
    $name = [string]$node.VariablePath.UserPath
    return $name.EndsWith('?',[StringComparison]::Ordinal) -or $name.EndsWith(':',[StringComparison]::Ordinal)
},$true))
if ($suspiciousVars.Count -ne 0) {
    foreach ($v in $suspiciousVars) {
        Write-Host ("STRICTMODE_VARIABLE_REJECT|name={0}|text={1}" -f $v.VariablePath.UserPath,$v.Extent.Text) -ForegroundColor Red
    }
    throw "0.1.0.11 diagnostics target contains $($suspiciousVars.Count) suspicious StrictMode variable token(s). BC was not contacted."
}

foreach ($banned in @('createValidatedDraft','/salesOrders','releaseShipInvoicePost')) {
    if ($source.IndexOf($banned,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden Sales Order/business action token present in 0.1.0.11 diagnostics target: $banned"
    }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.11 - ORDER DATE / SHIPPING DIAGNOSTICS OUTER GUARD' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Committed target blob    : $ExpectedTargetBlob"
Write-Host 'PowerShell syntax gate   : PASS' -ForegroundColor Green
Write-Host 'StrictMode variable gate : PASS' -ForegroundColor Green
Write-Host 'Sales-order action scan  : PASS / NOT PRESENT' -ForegroundColor Green
Write-Host 'Extension mutation       : EXACT PRE 0.1.0.11 upgrade only' -ForegroundColor Yellow
Write-Host 'Business-data reads      : GET ONLY after install' -ForegroundColor Green
Write-Host 'Business-data writes     : NONE' -ForegroundColor Green
Write-Host 'Production               : HARD BLOCKED by target script' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

& $TargetPath
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "0.1.0.11 diagnostics target exited with code $LASTEXITCODE."
}
