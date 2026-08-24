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
if ($text -match 'function Convert-ToSpiroDisplayText') {
    throw '0.19 Spiro context hotfix already appears to be applied.'
}
if ($text -notmatch 'AssignedIsr = \$assignedIsr' -or $text -notmatch '\$existing\.assignedIsr') {
    throw 'Expected post-0.19 refresh-script markers were not found.'
}

$backup = "$refreshScript.pre-0.19-context-hotfix.bak"
Copy-Item -LiteralPath $refreshScript -Destination $backup -Force
Write-Host "Backup: $backup" -ForegroundColor DarkGray

Write-Step 'NORMALIZE SPIRO LOOKUP VALUES'
$anchor = @'
function Convert-ToDecimalOrZero {
'@
$replacement = @'
function Convert-ToSpiroDisplayText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return '' }

    if ($Value -is [string] -or $Value.GetType().IsPrimitive -or $Value -is [decimal]) {
        return ([string]$Value).Trim()
    }

    foreach ($name in @('label', 'name', 'display_name', 'displayName', 'title')) {
        $candidate = Get-PropertyValue -Object $Value -Names @($name)
        if ($null -ne $candidate -and -not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            return ([string]$candidate).Trim()
        }
    }

    $fallback = Get-PropertyValue -Object $Value -Names @('value')
    if ($null -ne $fallback) {
        return ([string]$fallback).Trim()
    }

    return ([string]$Value).Trim()
}

function Convert-ToDecimalOrZero {
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'display-text helper insertion'

$text = Replace-Once -Text $text `
    -Old '        $assignedIsr = [string](Get-SpiroCustomAttribute -Record $detail -Names @(''assigned_isr'', ''assignedISR'', ''assignedIsr'', ''assigned_isr_name'', ''assignedISRName'', ''isr'', ''isr_name''))' `
    -New '        $assignedIsr = Convert-ToSpiroDisplayText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''assigned_isr'', ''assignedISR'', ''assignedIsr'', ''assigned_isr_name'', ''assignedISRName'', ''isr'', ''isr_name''))' `
    -Label 'Assigned ISR normalization'

$text = Replace-Once -Text $text `
    -Old '        $rating = [string](Get-SpiroCustomAttribute -Record $detail -Names @(''rating'', ''opportunity_rating'', ''opportunityRating'', ''temperature''))' `
    -New '        $rating = Convert-ToSpiroDisplayText -Value (Get-SpiroCustomAttribute -Record $detail -Names @(''rating'', ''opportunity_rating'', ''opportunityRating'', ''temperature''))' `
    -Label 'Rating normalization'

Write-Step 'MAKE FIRST 0.19 CACHE COMPARISON NULL-SAFE'
$old = @'
            @{ Label = 'Assigned ISR'; Current = $existing.assignedIsr; Desired = $live.AssignedIsr },
            @{ Label = 'Probability'; Current = $existing.probability; Desired = $live.Probability },
            @{ Label = 'Estimated Annual Volume'; Current = $existing.estimatedAnnualVolume; Desired = $live.EstimatedAnnualVolume },
            @{ Label = 'Close Date'; Current = $existing.closeDate; Desired = $live.CloseDate },
            @{ Label = 'Rating'; Current = $existing.rating; Desired = $live.Rating },
'@
$new = @'
            @{ Label = 'Assigned ISR'; Current = (Get-PropertyValue -Object $existing -Names @('assignedIsr')); Desired = $live.AssignedIsr },
            @{ Label = 'Probability'; Current = (Get-PropertyValue -Object $existing -Names @('probability')); Desired = $live.Probability },
            @{ Label = 'Estimated Annual Volume'; Current = (Get-PropertyValue -Object $existing -Names @('estimatedAnnualVolume')); Desired = $live.EstimatedAnnualVolume },
            @{ Label = 'Close Date'; Current = (Get-PropertyValue -Object $existing -Names @('closeDate')); Desired = $live.CloseDate },
            @{ Label = 'Rating'; Current = (Get-PropertyValue -Object $existing -Names @('rating')); Desired = $live.Rating },
'@
$text = Replace-Once -Text $text -Old $old -New $new -Label 'optional cache comparison fields'

$old = @'
            AssignedIsr = [string]$existing.assignedIsr
            Probability = Convert-ToDecimalOrZero -Value $existing.probability
            EstimatedAnnualVolume = Convert-ToDecimalOrZero -Value $existing.estimatedAnnualVolume
            CloseDate = [string]$existing.closeDate
            Rating = [string]$existing.rating
'@
$new = @'
            AssignedIsr = Convert-ToSpiroDisplayText -Value (Get-PropertyValue -Object $existing -Names @('assignedIsr'))
            Probability = Convert-ToDecimalOrZero -Value (Get-PropertyValue -Object $existing -Names @('probability'))
            EstimatedAnnualVolume = Convert-ToDecimalOrZero -Value (Get-PropertyValue -Object $existing -Names @('estimatedAnnualVolume'))
            CloseDate = [string](Get-PropertyValue -Object $existing -Names @('closeDate'))
            Rating = Convert-ToSpiroDisplayText -Value (Get-PropertyValue -Object $existing -Names @('rating'))
'@
$text = Replace-Once -Text $text -Old $old -New $new -Label 'optional removed-cache fields'

Write-Step 'MAKE VERIFICATION NULL-SAFE'
$old = @'
    if (-not (Test-TextEqual $verified.assignedIsr $live.AssignedIsr)) {
        $verificationFailures.Add("Assigned ISR mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.probability $live.Probability)) {
        $verificationFailures.Add("Probability mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.estimatedAnnualVolume $live.EstimatedAnnualVolume)) {
        $verificationFailures.Add("Estimated annual volume mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.closeDate $live.CloseDate)) {
        $verificationFailures.Add("Close date mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.rating $live.Rating)) {
        $verificationFailures.Add("Rating mismatch for $($live.OpportunityId)")
    }
'@
$new = @'
    if (-not (Test-TextEqual (Get-PropertyValue -Object $verified -Names @('assignedIsr')) $live.AssignedIsr)) {
        $verificationFailures.Add("Assigned ISR mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual (Get-PropertyValue -Object $verified -Names @('probability')) $live.Probability)) {
        $verificationFailures.Add("Probability mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual (Get-PropertyValue -Object $verified -Names @('estimatedAnnualVolume')) $live.EstimatedAnnualVolume)) {
        $verificationFailures.Add("Estimated annual volume mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual (Get-PropertyValue -Object $verified -Names @('closeDate')) $live.CloseDate)) {
        $verificationFailures.Add("Close date mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual (Get-PropertyValue -Object $verified -Names @('rating')) $live.Rating)) {
        $verificationFailures.Add("Rating mismatch for $($live.OpportunityId)")
    }
'@
$text = Replace-Once -Text $text -Old $old -New $new -Label 'optional verification fields'

[System.IO.File]::WriteAllText($refreshScript, $text, [System.Text.UTF8Encoding]::new($false))

Write-Step 'VALIDATE HOTFIX'
$patched = Get-Content -LiteralPath $refreshScript -Raw
$checks = @(
    @{ Pattern = 'function Convert-ToSpiroDisplayText'; Label = 'lookup display normalization helper' },
    @{ Pattern = '\$assignedIsr = Convert-ToSpiroDisplayText'; Label = 'Assigned ISR normalized to label' },
    @{ Pattern = "Current = \(Get-PropertyValue -Object \$existing -Names @\('assignedIsr'\)\)"; Label = 'comparison tolerates pre-0.19 cache rows' },
    @{ Pattern = "Get-PropertyValue -Object \$verified -Names @\('assignedIsr'\)"; Label = 'verification is null-safe' }
)

foreach ($check in $checks) {
    if ($patched -notmatch $check.Pattern) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.19 Spiro opportunity-context refresh hotfix applied successfully." -ForegroundColor Green
Write-Host 'No AL objects were changed, so the already-published 0.19 app does not need to be republished for this script-only fix.' -ForegroundColor Green
Write-Host 'Next: rerun WAT without -Apply and review the normalized dry-run plan.' -ForegroundColor Cyan
