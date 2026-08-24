[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Add-AfterOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Anchor,
        [Parameter(Mandatory)][string]$Addition,
        [Parameter(Mandatory)][string]$Marker,
        [Parameter(Mandatory)][string]$Label
    )

    if ($Text.Contains($Marker)) {
        Write-Host "Already present: $Label" -ForegroundColor DarkYellow
        return $Text
    }

    $first = $Text.IndexOf($Anchor, [System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw "0.22 permission hotfix anchor not found: $Label" }
    $second = $Text.IndexOf($Anchor, $first + $Anchor.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw "0.22 permission hotfix anchor is not unique: $Label" }

    return $Text.Substring(0, $first + $Anchor.Length) + $Addition + $Text.Substring($first + $Anchor.Length)
}

$appJson = Join-Path $ProjectPath 'app.json'
$permissionSet = Join-Path $ProjectPath 'src\PermissionSets\GPIPackagingCatalog.PermissionSet.al'
$queueTable = Join-Path $ProjectPath 'src\Tables\GPISpiroPushQueue.Table.al'
$queueMgt = Join-Path $ProjectPath 'src\Codeunits\GPISpiroPushMgt.Codeunit.al'
$queueApi = Join-Path $ProjectPath 'src\Pages\GPISpiroPushQueueAPI.Page.al'

foreach ($file in @($appJson, $permissionSet, $queueTable, $queueMgt, $queueApi)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required 0.22 file not found: $file" }
}

Write-Step 'PRECHECK PARTIAL 0.22'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.22.0.0') {
    throw "Expected local app version 0.22.0.0. Found $($app.version)."
}

Write-Host '0.22 version and queue objects are present.' -ForegroundColor Green

Write-Step 'REPAIR 0.22 PERMISSIONS'
$text = Get-Content -LiteralPath $permissionSet -Raw

$anchor = '        tabledata "GPI Spiro Opp Cache" = RIMD,'
$addition = "`r`n" + '        tabledata "GPI Spiro Push Queue" = RIMD,'
$text = Add-AfterOnce -Text $text -Anchor $anchor -Addition $addition -Marker 'tabledata "GPI Spiro Push Queue" = RIMD' -Label 'queue tabledata permission'

$anchor = '        table "GPI Spiro Opp Cache" = X,'
$addition = "`r`n" + '        table "GPI Spiro Push Queue" = X,'
$text = Add-AfterOnce -Text $text -Anchor $anchor -Addition $addition -Marker 'table "GPI Spiro Push Queue" = X' -Label 'queue table permission'

$anchor = '        page "GPI Spiro Opp API" = X,'
$addition = "`r`n" + '        page "GPI Spiro Push Q API" = X,'
$text = Add-AfterOnce -Text $text -Anchor $anchor -Addition $addition -Marker 'page "GPI Spiro Push Q API" = X' -Label 'queue API permission'

$anchor = '        codeunit "GPI Spiro Link Mgt" = X;'
$replacement = @'
        codeunit "GPI Spiro Link Mgt" = X,
        codeunit "GPI Spiro Push Mgt" = X;
'@
if (-not $text.Contains('codeunit "GPI Spiro Push Mgt" = X')) {
    $first = $text.IndexOf($anchor, [System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw '0.22 permission hotfix anchor not found: queue codeunit permission' }
    $text = $text.Substring(0, $first) + $replacement + $text.Substring($first + $anchor.Length)
}
else {
    Write-Host 'Already present: queue codeunit permission' -ForegroundColor DarkYellow
}

[System.IO.File]::WriteAllText($permissionSet, $text, [System.Text.UTF8Encoding]::new($false))
Write-Host "Patched: $permissionSet" -ForegroundColor DarkGreen

Write-Step 'VALIDATE 0.22 PERMISSIONS'
$checks = @(
    @{ Pattern = 'tabledata "GPI Spiro Push Queue" = RIMD'; Label = 'queue tabledata permission' },
    @{ Pattern = 'table "GPI Spiro Push Queue" = X'; Label = 'queue table permission' },
    @{ Pattern = 'page "GPI Spiro Push Q API" = X'; Label = 'queue API permission' },
    @{ Pattern = 'codeunit "GPI Spiro Push Mgt" = X'; Label = 'queue codeunit permission' }
)

$raw = Get-Content -LiteralPath $permissionSet -Raw
foreach ($check in $checks) {
    if (-not $raw.Contains($check.Pattern)) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.22 permission hotfix applied successfully." -ForegroundColor Green
Write-Host 'Run the normal Packaging Catalog build again before publishing.' -ForegroundColor Cyan
