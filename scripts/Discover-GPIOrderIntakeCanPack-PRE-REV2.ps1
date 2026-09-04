#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# PRE-only / GET-only wrapper over the committed CanPack discovery script.
# Fixes StrictMode handling when an OData response has no @odata.nextLink property (last page).
$ExpectedBaseBlob = '95fb245d484d7f5b2e1b8ecd866db934e524ed69'
$BasePath = 'scripts/Discover-GPIOrderIntakeCanPack-PRE.ps1'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Name
    )

    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    Write-Host ("Patch target {0,-28}: {1} / 1" -f $Name, $count)
    if ($count -ne 1) { throw "Expected exactly one $Name patch target; found $count." }
    return $Text.Replace($Old, $New)
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base script at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed CanPack discovery script changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed CanPack discovery script was empty.' }

    $old = '$next = [string]$r.''@odata.nextLink'''
    $new = @'
$nextLinkProperty = $r.PSObject.Properties['@odata.nextLink']
        if ($null -eq $nextLinkProperty) {
            $next = $null
        }
        else {
            $next = [string]$nextLinkProperty.Value
        }
'@.TrimEnd("`r","`n")

    $patched = Replace-ExactOnce $base $old $new 'safe OData nextLink'

    if ($patched -match '(?i)Invoke-RestMethod\s+-Method\s+(Post|Patch|Put|Delete)') {
        throw 'REV2 source unexpectedly contains a mutating REST method.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - CANPACK DISCOVERY REV2 / STRICTMODE PAGINATION FIX' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host 'Correction           : missing @odata.nextLink means final page; no StrictMode property exception'
    Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
    Write-Host 'Business data write  : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action   : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-CanPackDiscoveryREV2-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "CanPack discovery REV2 exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
