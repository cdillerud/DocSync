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
$backupPath = "$SyncScriptPath.before-empty-change-fix-$timestamp"
Copy-Item -LiteralPath $SyncScriptPath -Destination $backupPath -Force

$text = Get-Content -LiteralPath $SyncScriptPath -Raw

$oldParameter = '[Parameter(Mandatory)][System.Collections.Generic.List[string]]$Changes,'
$newParameter = '[Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$Changes,'

if ($text.Contains($oldParameter)) {
    $text = $text.Replace($oldParameter, $newParameter)
}
elseif (-not $text.Contains($newParameter)) {
    throw 'Could not find the Add-TextChange Changes parameter. Original file was not modified.'
}

$text = $text.TrimEnd()
$text = $text + [Environment]::NewLine

[System.IO.File]::WriteAllText(
    $SyncScriptPath,
    $text,
    [System.Text.UTF8Encoding]::new($false)
)

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
    throw 'Empty-change-list fix produced a syntax error. Original file restored.'
}

Write-Host ''
Write-Host 'GPI Spiro sync empty-change-list fix complete.' -ForegroundColor Green
Write-Host "Sync script : $SyncScriptPath"
Write-Host "Backup      : $backupPath"
Write-Host 'Syntax      : PASSED' -ForegroundColor Green
Write-Host 'Empty change collections are now accepted.' -ForegroundColor Green
Write-Host 'EOF whitespace normalized.' -ForegroundColor Green
