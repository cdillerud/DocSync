[CmdletBinding()]
param(
    [string]$SyncScriptPath = "$PSScriptRoot\Sync-GPISpiroUATContext.ps1"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $SyncScriptPath)) {
    throw "Sync script not found: $SyncScriptPath"
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = "$SyncScriptPath.before-sync-hardening-$timestamp"
Copy-Item -LiteralPath $SyncScriptPath -Destination $backupPath -Force

$text = Get-Content -LiteralPath $SyncScriptPath -Raw

$oldLabel = @'
        $Changes.Add("$Label: '$(Convert-ToCompareText -Value $Current)' -> '$(Convert-ToCompareText -Value $Desired)'")
'@
$newLabel = @'
        $Changes.Add("${Label}: '$(Convert-ToCompareText -Value $Current)' -> '$(Convert-ToCompareText -Value $Desired)'")
'@

if (-not $text.Contains($oldLabel.TrimEnd("`r", "`n"))) {
    throw 'Could not find the change-label interpolation anchor. No file changes were made.'
}
$text = $text.Replace($oldLabel.TrimEnd("`r", "`n"), $newLabel.TrimEnd("`r", "`n"))

$oldFilter = @'
if ($QuoteEntryNo -gt 0) {
    $quoteLinks = @($quoteLinks | Where-Object { [int](Get-PropertyValue -Object $_ -Names @('quoteNo')) -eq $QuoteEntryNo })
}
'@
$newFilter = @'
if ($QuoteEntryNo -gt 0) {
    $quoteLinks = @($quoteLinks | Where-Object { [int](Get-PropertyValue -Object $_ -Names @('quoteNo')) -eq $QuoteEntryNo })
}
else {
    $quoteLinks = @(
        $quoteLinks |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace(
                    [string](Get-PropertyValue -Object $_ -Names @('spiroOpportunityId'))
                )
            }
    )
}
'@

if (-not $text.Contains($oldFilter.TrimEnd("`r", "`n"))) {
    throw 'Could not find the quote-filter anchor. No file changes were made.'
}
$text = $text.Replace($oldFilter.TrimEnd("`r", "`n"), $newFilter.TrimEnd("`r", "`n"))

Set-Content -LiteralPath $SyncScriptPath -Value $text -Encoding utf8NoBOM

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $SyncScriptPath,
    [ref]$tokens,
    [ref]$parseErrors
) | Out-Null

if (@($parseErrors).Count -gt 0) {
    Write-Host ''
    Write-Host 'PowerShell parse errors:' -ForegroundColor Red
    @($parseErrors) | ForEach-Object { Write-Host "  $($_.Message)" -ForegroundColor Red }
    Copy-Item -LiteralPath $backupPath -Destination $SyncScriptPath -Force
    throw 'Sync hardening produced a syntax error. Original file restored.'
}

Write-Host ''
Write-Host 'GPI Spiro sync engine hardening complete.' -ForegroundColor Green
Write-Host "Sync script : $SyncScriptPath"
Write-Host "Backup      : $backupPath"
Write-Host 'Syntax      : PASSED' -ForegroundColor Green
Write-Host 'Default run : linked quotes only' -ForegroundColor Green
Write-Host 'Write mode  : still requires -Apply and exact SYNC confirmation' -ForegroundColor Green
