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
    throw 'The first 0.19 context hotfix does not appear to be present in the local refresh script.'
}
if ($text -match "forecast_close_date") {
    throw 'The second 0.19 context hotfix already appears to be applied.'
}

$backup = "$refreshScript.pre-0.19-context-hotfix2.bak"
Copy-Item -LiteralPath $refreshScript -Destination $backup -Force
Write-Host "Backup: $backup" -ForegroundColor DarkGray

Write-Step 'NORMALIZE SPIRO DATE VALUES'
$old = @'
function Convert-ToBcDateText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return '' }
    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return '' }

    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AllowWhiteSpaces,
        [ref]$parsed
    )) {
        return $parsed.ToString('yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
    }

    return ''
}
'@
$new = @'
function Convert-ToBcDateText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return '' }

    $candidate = $Value
    if (-not ($Value -is [string]) -and -not $Value.GetType().IsPrimitive) {
        foreach ($name in @('value', 'date', 'date_value', 'dateValue', 'label')) {
            $nested = Get-PropertyValue -Object $Value -Names @($name)
            if ($null -ne $nested -and -not [string]::IsNullOrWhiteSpace([string]$nested)) {
                $candidate = $nested
                break
            }
        }
    }

    $text = ([string]$candidate).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return '' }

    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AllowWhiteSpaces,
        [ref]$parsed
    )) {
        return $parsed.ToString('yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
    }

    if ([datetime]::TryParse($text, [ref]$parsed)) {
        return $parsed.ToString('yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
    }

    return ''
}
'@
$text = Replace-Once -Text $text -Old $old -New $new -Label 'BC date conversion helper'

Write-Step 'EXPAND CLOSE DATE ALIASES'
$oldLine = '        $closeDate = Convert-ToBcDateText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''close_date'', ''closeDate'', ''expected_close_date'', ''expectedCloseDate''))'
$newLine = '        $closeDate = Convert-ToBcDateText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''close_date'', ''closeDate'', ''expected_close_date'', ''expectedCloseDate'', ''estimated_close_date'', ''estimatedCloseDate'', ''estimated_close'', ''estimatedClose'', ''forecast_close_date'', ''forecastCloseDate'', ''expected_close'', ''expectedClose''))'
$text = Replace-Once -Text $text -Old $oldLine -New $newLine -Label 'Close Date aliases'

[System.IO.File]::WriteAllText($refreshScript, $text, [System.Text.UTF8Encoding]::new($false))

Write-Step 'VALIDATE HOTFIX'
$patched = Get-Content -LiteralPath $refreshScript -Raw
$requiredMarkers = @(
    'function Convert-ToSpiroDisplayText',
    "Get-PropertyValue -Object `$existing -Names @('assignedIsr')",
    "Get-PropertyValue -Object `$verified -Names @('assignedIsr')",
    "'forecast_close_date'",
    "'estimated_close_date'",
    "foreach (`$name in @('value', 'date', 'date_value', 'dateValue', 'label'))"
)

foreach ($marker in $requiredMarkers) {
    if (-not $patched.Contains($marker)) {
        throw "Validation failed. Missing marker: $marker"
    }
}

Write-Host 'PASS: first hotfix comparison remains null-safe' -ForegroundColor Green
Write-Host 'PASS: first hotfix verification remains null-safe' -ForegroundColor Green
Write-Host 'PASS: Spiro object-style date values are normalized' -ForegroundColor Green
Write-Host 'PASS: Close Date aliases expanded' -ForegroundColor Green

Write-Host "`nSecond 0.19 Spiro opportunity-context hotfix applied successfully." -ForegroundColor Green
Write-Host 'No AL objects were changed. No rebuild or BC republish is required.' -ForegroundColor Green
Write-Host 'Next: rerun WAT without -Apply and confirm Close Date is populated before writing the cache.' -ForegroundColor Cyan
