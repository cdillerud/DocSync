#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TargetPath = 'scripts/Discover-GPIOrderIntakeBernerHerdezCurrentLinkage-PRE.ps1'
$ExpectedBlob = '51e981a7508b25c62ce16dc8145daebdf6dde6cd'

Push-Location $RepoRoot
try {
    $blob = (& git rev-parse "HEAD:$TargetPath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) {
        throw "Could not resolve committed target at HEAD:$TargetPath"
    }
    if ($blob -ne $ExpectedBlob) {
        throw "Committed Berner/Herdez linkage target changed. Expected $ExpectedBlob; got $blob."
    }

    $source = (& git show "HEAD:$TargetPath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) { throw 'Committed target was empty.' }

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) {
            Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red
        }
        throw "Target source has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    $badVariables = @($ast.FindAll({
        param($node)
        if ($node -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $false }
        $name = [string]$node.VariablePath.UserPath
        return $name.EndsWith('?') -or $name.EndsWith(':')
    }, $true))
    if ($badVariables.Count -gt 0) {
        foreach ($v in $badVariables) {
            Write-Host ("STRICTMODE_BAD_VARIABLE|name={0}|text={1}" -f $v.VariablePath.UserPath,$v.Extent.Text) -ForegroundColor Red
        }
        throw "StrictMode interpolation scan found $($badVariables.Count) suspicious variable token(s). BC was not contacted."
    }

    $forbidden = [ordered]@{
        'POST request' = '(?i)-Method\s+Post\b'
        'PATCH request' = '(?i)-Method\s+Patch\b'
        'PUT request' = '(?i)-Method\s+Put\b'
        'DELETE request' = '(?i)-Method\s+Delete\b'
        'Invoke-WebRequest' = '(?i)Invoke-WebRequest\b'
        'Extension upload' = '(?i)extensionUpload'
        'Order create action' = '(?i)createValidatedDraft'
        'Release action' = '(?i)(/|\.)release\b'
        'Ship action' = '(?i)(/|\.)ship\b'
        'Post action' = '(?i)(/|\.)post\b'
    }
    foreach ($entry in $forbidden.GetEnumerator()) {
        if ($source -match $entry.Value) { throw "Forbidden behavior found before execution: $($entry.Key)" }
    }

    foreach ($required in @(
        "`$ExpectedVersion   = '0.1.0.10'",
        "`$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'",
        "`$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'",
        "`$BernerSourceAlias     = '21579-858231'",
        "`$BernerBcItem          = '21759-858231'",
        "`$HerdezSourcePo        = '4500063632'",
        "`$HerdezBcItem          = '20113526'",
        'HTTP methods         : GET ONLY',
        'Extension mutation   : NONE',
        'Business-data writes : NONE',
        'Sales-order action   : NOT CALLED / NOT PRESENT',
        'Write authorization     : NOT GRANTED'
    )) {
        if ($source.IndexOf($required,[StringComparison]::Ordinal) -lt 0) {
            throw "Required safety/evidence marker missing: $required"
        }
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - BERNER/HERDEZ CURRENT LINKAGE GUARDED LAUNCH' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed target blob     : $ExpectedBlob"
    Write-Host 'PowerShell syntax gate    : PASS' -ForegroundColor Green
    Write-Host 'StrictMode variable gate  : PASS' -ForegroundColor Green
    Write-Host 'Mutation/action scan      : PASS / GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation        : NONE' -ForegroundColor Green
    Write-Host 'Business-data writes      : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action        : NOT PRESENT' -ForegroundColor Green
    Write-Host 'Target                    : PRE_GAMERDOCS_CUTOVER_20260831 / Gamer Packaging'
    Write-Host 'Installed app required    : GPI Order Intake 0.1.0.10'
    Write-Host 'Production                : HARD BLOCKED by target script' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $target = Join-Path $RepoRoot $TargetPath
    & $target
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "Berner/Herdez linkage target exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
