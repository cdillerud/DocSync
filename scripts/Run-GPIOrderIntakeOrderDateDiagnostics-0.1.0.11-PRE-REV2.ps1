#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TargetRelativePath = 'scripts/Publish-Discover-GPIOrderIntakeOrderDateDiagnostics-0.1.0.11-PRE.ps1'
$TargetPath = Join-Path $PSScriptRoot 'Publish-Discover-GPIOrderIntakeOrderDateDiagnostics-0.1.0.11-PRE.ps1'
$ExpectedTargetBlob = '80888f506acd56b93d979b66f10f4fcc7a6377b6'
$FailedGuardRelativePath = 'scripts/Run-GPIOrderIntakeOrderDateDiagnostics-0.1.0.11-PRE.ps1'
$ExpectedFailedGuardBlob = 'a6f2dd00c6ff825e63557166565ef156025a95a0'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    $committedTargetBlob = (& git rev-parse "HEAD:$TargetRelativePath").Trim()
    if ($LASTEXITCODE -ne 0 -or $committedTargetBlob -ne $ExpectedTargetBlob) {
        throw "Committed 0.1.0.11 diagnostics target changed. Expected $ExpectedTargetBlob; got $committedTargetBlob."
    }

    $committedFailedGuardBlob = (& git rev-parse "HEAD:$FailedGuardRelativePath").Trim()
    if ($LASTEXITCODE -ne 0 -or $committedFailedGuardBlob -ne $ExpectedFailedGuardBlob) {
        throw "Prior failed guard changed. Expected $ExpectedFailedGuardBlob; got $committedFailedGuardBlob."
    }

    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
        throw "Committed 0.1.0.11 date diagnostics target missing: $TargetPath"
    }

    $localTargetBlob = (& git hash-object -- $TargetPath).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'git hash-object failed while validating 0.1.0.11 date diagnostics target.' }
    if ($localTargetBlob -ne $ExpectedTargetBlob) {
        throw "Unexpected local 0.1.0.11 diagnostics target blob: $localTargetBlob. Expected $ExpectedTargetBlob."
    }

    $source = Get-Content -LiteralPath $TargetPath -Raw
    if ([string]::IsNullOrWhiteSpace($source)) { throw '0.1.0.11 diagnostics target is empty.' }

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

    # Block executable Sales Order/business actions, not harmless safety-report labels.
    # The target is allowed to POST/PATCH only to the Microsoft Automation extension-upload API.
    $forbiddenExecutableTokens = @(
        'createValidatedDraft',
        '/salesOrders',
        'Microsoft.NAV.release',
        'Microsoft.NAV.ship',
        'Microsoft.NAV.invoice',
        'Microsoft.NAV.post'
    )
    foreach ($banned in $forbiddenExecutableTokens) {
        if ($source.IndexOf($banned,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Forbidden executable Sales Order/business action token present in 0.1.0.11 diagnostics target: $banned"
        }
    }

    if ($source.IndexOf("releaseShipInvoicePost = 'NOT_CALLED_BLOCKED'",[StringComparison]::Ordinal) -lt 0) {
        throw 'Expected release/ship/invoice/post safety-report marker is missing.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.11 - ORDER DATE / SHIPPING DIAGNOSTICS OUTER GUARD REV2' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed target blob       : $ExpectedTargetBlob"
    Write-Host "Prior failed guard blob     : $ExpectedFailedGuardBlob / PRESERVED"
    Write-Host 'PowerShell syntax gate      : PASS' -ForegroundColor Green
    Write-Host 'StrictMode variable gate    : PASS' -ForegroundColor Green
    Write-Host 'Executable action scan      : PASS / NO SALES-ORDER ACTIONS' -ForegroundColor Green
    Write-Host 'Safety-report label         : releaseShipInvoicePost / ALLOWED AS NON-EXECUTABLE TEXT' -ForegroundColor Green
    Write-Host 'Extension mutation          : EXACT PRE 0.1.0.11 upgrade only' -ForegroundColor Yellow
    Write-Host 'Business-data reads         : GET ONLY after install' -ForegroundColor Green
    Write-Host 'Business-data writes        : NONE' -ForegroundColor Green
    Write-Host 'Production                  : HARD BLOCKED by target script' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    & $TargetPath
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "0.1.0.11 diagnostics target exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
