#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BasePath = 'scripts/Publish-Discover-GPIOrderIntakeHistoricalIdentityDiagnostics-0.1.0.10-PRE.ps1'
$ExpectedBaseBlob = '260fe4ca53bdd82b356d2926b49fdc0fe1d0aa70'

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base harness at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed base harness changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    $source = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) {
        throw 'Committed historical diagnostics harness content was empty.'
    }

    $old = 'return "$customRoot/$EntitySet?`$filter=$encoded"'
    $new = 'return "$customRoot/${EntitySet}?`$filter=$encoded"'
    $patchCount = ([regex]::Matches($source,[regex]::Escape($old))).Count

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.10 - HISTORICAL IDENTITY DIAGNOSTICS REV2 / ENTITY-SET INTERPOLATION FIX' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob       : $ExpectedBaseBlob"
    Write-Host "HEAD base blob            : $headBlob"
    Write-Host "EntitySet patch target    : $patchCount / 1"
    Write-Host 'Correction                 : delimit ${EntitySet} before literal ? in OData URI'
    Write-Host 'PowerShell syntax gate     : Parser.ParseInput; zero parse errors required'
    Write-Host 'StrictMode variable gate   : reject variable tokens whose names end in ? or :'
    Write-Host 'Installed target expected  : GPI Order Intake 0.1.0.10 already installed in PRE'
    Write-Host 'Extension mutation expected: NONE / exact version should skip duplicate upload' -ForegroundColor Green
    Write-Host 'Historical reads           : GET ONLY' -ForegroundColor Green
    Write-Host 'Business-data writes       : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action         : NOT CALLED / NOT PRESENT' -ForegroundColor Green
    Write-Host 'Production                 : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    if ($patchCount -ne 1) {
        throw "Expected exactly one EntitySet interpolation patch target; found $patchCount."
    }

    $patched = $source.Replace($old,$new)
    if ($patched.Contains($old)) { throw 'Original EntitySet interpolation remains after patch.' }
    if (-not $patched.Contains($new)) { throw 'Corrected ${EntitySet} interpolation marker missing after patch.' }

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($patched,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) {
            Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red
        }
        throw "Patched historical diagnostics harness still has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
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
        throw "Patched historical diagnostics harness contains $($suspiciousVars.Count) suspicious StrictMode variable token(s). BC was not contacted."
    }

    Write-Host 'Pre-execution PowerShell syntax gate   : PASS' -ForegroundColor Green
    Write-Host 'Pre-execution StrictMode variable gate : PASS' -ForegroundColor Green
    Write-Host ''

    $tempPath = Join-Path $PSScriptRoot ('.GPIOrderIntake-HistoricalIdentity-0.1.0.10-REV2-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempPath -Value $patched -Encoding utf8NoBOM -NoNewline
        & $tempPath -EnableInstall
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Patched historical diagnostics harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
