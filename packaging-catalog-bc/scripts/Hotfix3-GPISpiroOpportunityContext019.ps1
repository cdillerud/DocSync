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

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw "Hotfix anchor not found: $Label"
    }

    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) {
        throw "Hotfix anchor is not unique: $Label"
    }

    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

$refreshScript = Join-Path $ProjectPath 'scripts\Refresh-GPISpiroOpportunityCacheUAT.ps1'
$appJson = Join-Path $ProjectPath 'app.json'

if (-not (Test-Path -LiteralPath $refreshScript)) {
    throw "Refresh script not found: $refreshScript"
}
if (-not (Test-Path -LiteralPath $appJson)) {
    throw "app.json not found: $appJson"
}

Write-Step 'PRECHECK 0.19'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.19.0.0') {
    throw "Expected app version 0.19.0.0. Found $($app.version)."
}

$text = Get-Content -LiteralPath $refreshScript -Raw
if ($text -notmatch 'function Convert-ToSpiroDisplayText') {
    throw 'The first 0.19 context hotfix does not appear to be present.'
}
if ($text -notmatch 'forecast_close_date') {
    throw 'The second 0.19 context hotfix does not appear to be present.'
}
if ($text -match "'close_at'") {
    throw 'The close_at hotfix already appears to be applied.'
}

$backup = "$refreshScript.pre-0.19-context-hotfix3.bak"
Copy-Item -LiteralPath $refreshScript -Destination $backup -Force
Write-Host "Backup: $backup" -ForegroundColor DarkGray

Write-Step 'ADD ACTUAL SPIRO CLOSE DATE FIELD'
$oldLine = '        $closeDate = Convert-ToBcDateText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''close_date'', ''closeDate'', ''expected_close_date'', ''expectedCloseDate'', ''estimated_close_date'', ''estimatedCloseDate'', ''estimated_close'', ''estimatedClose'', ''forecast_close_date'', ''forecastCloseDate'', ''expected_close'', ''expectedClose''))'
$newLine = '        $closeDate = Convert-ToBcDateText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''close_at'', ''closeAt'', ''close_date'', ''closeDate'', ''expected_close_date'', ''expectedCloseDate'', ''estimated_close_date'', ''estimatedCloseDate'', ''estimated_close'', ''estimatedClose'', ''forecast_close_date'', ''forecastCloseDate'', ''expected_close'', ''expectedClose''))'
$text = Replace-Once -Text $text -Old $oldLine -New $newLine -Label 'Spiro close_at field'

[System.IO.File]::WriteAllText($refreshScript, $text, [System.Text.UTF8Encoding]::new($false))

Write-Step 'VALIDATE HOTFIX'
$patched = Get-Content -LiteralPath $refreshScript -Raw
if (-not $patched.Contains("'close_at'")) {
    throw "Validation failed: close_at was not added."
}
if (-not $patched.Contains("Get-PropertyValue -Object `$existing -Names @('assignedIsr')")) {
    throw 'Validation failed: first-hotfix null-safe comparison marker is missing.'
}
if (-not $patched.Contains("'forecast_close_date'")) {
    throw 'Validation failed: second-hotfix close-date alias marker is missing.'
}

Write-Host 'PASS: actual Spiro close_at field added' -ForegroundColor Green
Write-Host 'PASS: prior null-safe comparison retained' -ForegroundColor Green
Write-Host 'PASS: prior close-date fallbacks retained' -ForegroundColor Green

Write-Host "`nThird 0.19 Spiro opportunity-context hotfix applied successfully." -ForegroundColor Green
Write-Host 'No AL objects were changed. No rebuild or BC republish is required.' -ForegroundColor Green
Write-Host 'Next: rerun WAT without -Apply and confirm Close Date before writing the cache.' -ForegroundColor Cyan
