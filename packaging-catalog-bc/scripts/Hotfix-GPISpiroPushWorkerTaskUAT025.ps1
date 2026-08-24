[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$appJson = Join-Path $ProjectPath 'app.json'
$installer = Join-Path $ProjectPath 'scripts\Install-GPISpiroPushWorkerTaskUAT.ps1'

foreach ($file in @($appJson, $installer)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.25 file not found: $file"
    }
}

$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.25.0.0') {
    throw "Expected local app version 0.25.0.0. Found $($app.version)."
}

Write-Host "`n== FIX SCHEDULED TASK LOGON TYPE ==" -ForegroundColor Cyan
$text = Get-Content -LiteralPath $installer -Raw

$old = 'New-ScheduledTaskPrincipal -UserId $currentIdentity -LogonType InteractiveToken -RunLevel Highest'
$new = 'New-ScheduledTaskPrincipal -UserId $currentIdentity -LogonType Interactive -RunLevel Highest'

if ($text.Contains($old)) {
    $text = $text.Replace($old, $new)
}
elseif ($text.Contains('-LogonType Interactive -RunLevel Highest')) {
    Write-Host 'Already present: valid Interactive logon type.' -ForegroundColor DarkYellow
}
else {
    throw 'Scheduled task principal anchor not found.'
}

$text = $text.Replace('Write-Host "Logon Type        : InteractiveToken"', 'Write-Host "Logon Type        : Interactive"')

[System.IO.File]::WriteAllText($installer, $text, [System.Text.UTF8Encoding]::new($false))
Write-Host "Patched: $installer" -ForegroundColor DarkGreen

Write-Host "`n== VALIDATE 0.25 TASK HOTFIX ==" -ForegroundColor Cyan
$raw = Get-Content -LiteralPath $installer -Raw
$checks = @(
    @{ Passed = $raw.Contains('-LogonType Interactive -RunLevel Highest'); Label = 'valid ScheduledTasks logon type' },
    @{ Passed = -not $raw.Contains('-LogonType InteractiveToken'); Label = 'invalid InteractiveToken removed' },
    @{ Passed = $raw.Contains('Logon Type        : Interactive'); Label = 'preview output corrected' },
    @{ Passed = $raw.Contains('PREVIEW ONLY. No scheduled task was created or changed.'); Label = 'preview-only default preserved' },
    @{ Passed = $raw.Contains('Disable-ScheduledTask'); Label = 'disabled-by-default install preserved' }
)

foreach ($check in $checks) {
    if (-not $check.Passed) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.25 scheduled-task logon-type hotfix applied successfully." -ForegroundColor Green
Write-Host 'No scheduled task was created or changed.' -ForegroundColor Yellow
Write-Host 'Re-run the installer with no switches to preview the task definition.' -ForegroundColor Cyan
