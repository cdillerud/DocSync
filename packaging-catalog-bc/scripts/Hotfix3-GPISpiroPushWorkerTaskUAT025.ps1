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

Write-Host "`n== HARDEN SCHEDULED TASK INSTALLER ELEVATION CHECK ==" -ForegroundColor Cyan
$text = Get-Content -LiteralPath $installer -Raw

$anchor = "if (`$Enable -and -not `$Install) {`r`n    throw '-Enable may only be used together with -Install.'`r`n}`r`n"
$insert = @'
if ($Enable -and -not $Install) {
    throw '-Enable may only be used together with -Install.'
}

if ($Install) {
    $currentWindowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $currentWindowsPrincipal = [Security.Principal.WindowsPrincipal]$currentWindowsIdentity
    $isAdministrator = $currentWindowsPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdministrator) {
        throw 'Task registration requires an elevated PowerShell session because the task uses RunLevel Highest. Re-run PowerShell 7 as Administrator.'
    }
}
'@

if ($text.Contains($anchor)) {
    $text = $text.Replace($anchor, ($insert -replace "`n", "`r`n") + "`r`n")
}
elseif ($text.Contains("Task registration requires an elevated PowerShell session")) {
    Write-Host 'Already present: elevation precheck.' -ForegroundColor DarkYellow
}
else {
    throw 'Installer parameter-validation anchor not found.'
}

[System.IO.File]::WriteAllText($installer, $text, [System.Text.UTF8Encoding]::new($false))
Write-Host "Patched: $installer" -ForegroundColor DarkGreen

Write-Host "`n== VALIDATE 0.25 INSTALLER HARDENING ==" -ForegroundColor Cyan
$raw = Get-Content -LiteralPath $installer -Raw
$checks = @(
    @{ Passed = $raw.Contains("if (`$Install) {"); Label = 'install-only elevation check' },
    @{ Passed = $raw.Contains('[Security.Principal.WindowsBuiltInRole]::Administrator'); Label = 'administrator role detection' },
    @{ Passed = $raw.Contains('Task registration requires an elevated PowerShell session'); Label = 'clear elevation failure message' },
    @{ Passed = $raw.Contains('Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop'); Label = 'fail-fast registration preserved' },
    @{ Passed = $raw.Contains('-RepetitionDuration (New-TimeSpan -Days 3650)'); Label = 'bounded repetition duration preserved' },
    @{ Passed = $raw.Contains('-LogonType Interactive -RunLevel Highest'); Label = 'interactive highest principal preserved' },
    @{ Passed = $raw.Contains('PREVIEW ONLY. No scheduled task was created or changed.'); Label = 'preview-only default preserved' }
)

foreach ($check in $checks) {
    if (-not $check.Passed) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.25 scheduled-task installer elevation hardening applied successfully." -ForegroundColor Green
Write-Host 'Existing registered task was not changed.' -ForegroundColor Yellow
