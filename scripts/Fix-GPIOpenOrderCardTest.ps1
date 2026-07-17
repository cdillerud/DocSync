[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

$ErrorActionPreference = "Stop"

$TestFile = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests\src\codeunit\GPIUATSimulationTests.Codeunit.al"
$AppJson  = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests\app.json"
$Stamp    = Get-Date -Format "yyyyMMdd-HHmmss"

foreach ($Path in @($TestFile, $AppJson)) {
    if (-not (Test-Path $Path)) {
        throw "Required file not found: $Path"
    }

    Copy-Item $Path "$Path.$Stamp.bak" -Force
}

$Content = Get-Content $TestFile -Raw

$OldLine = '        CustomerCard.GoToRecord(Customer);'
$NewLine = '        CustomerCard.GoToKey(Customer."No.");'

$MatchCount = ([regex]::Matches(
    $Content,
    [regex]::Escape($OldLine)
)).Count

if ($MatchCount -ne 1) {
    throw "Expected exactly one matching CustomerCard.GoToRecord line, but found $MatchCount. No source change was made."
}

$UpdatedContent = $Content.Replace($OldLine, $NewLine)
Set-Content -Path $TestFile -Value $UpdatedContent -Encoding utf8

$App = Get-Content $AppJson -Raw | ConvertFrom-Json
$VersionParts = [string]$App.version -split '\.'

if ($VersionParts.Count -ne 4) {
    throw "Unexpected test extension version format: $($App.version)"
}

$OldVersion = [string]$App.version
$VersionParts[3] = ([int]$VersionParts[3] + 1).ToString()
$NewVersion = $VersionParts -join '.'
$App.version = $NewVersion

$App |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -Path $AppJson -Encoding utf8

Write-Host ""
Write-Host "Patched:"
Write-Host "  $TestFile"
Write-Host ""
Write-Host "Changed:"
Write-Host "  CustomerCard.GoToRecord(Customer);"
Write-Host "to:"
Write-Host '  CustomerCard.GoToKey(Customer."No.");'
Write-Host ""
Write-Host "Test extension version:"
Write-Host "  $OldVersion -> $NewVersion"
Write-Host ""
Write-Host "Backups:"
Write-Host "  $TestFile.$Stamp.bak"
Write-Host "  $AppJson.$Stamp.bak"
Write-Host ""
Write-Host "No RDLC files were touched."
