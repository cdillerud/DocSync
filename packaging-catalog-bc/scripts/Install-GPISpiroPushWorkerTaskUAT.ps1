[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Enable,
    [int]$IntervalMinutes = 5,
    [string]$TaskName = 'GPI Spiro Push Worker UAT',
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($IntervalMinutes -lt 1 -or $IntervalMinutes -gt 1440) {
    throw 'IntervalMinutes must be between 1 and 1440.'
}
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
if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw 'Windows ScheduledTasks module is required.'
}

$worker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
if (-not (Test-Path -LiteralPath $worker)) {
    throw "Operational worker not found: $worker"
}

$pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($pwsh)) {
    throw 'PowerShell 7 (pwsh.exe) is required.'
}

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($currentIdentity)) {
    throw 'Could not determine the current Windows identity.'
}

$arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $worker + '" -Apply'
$action = New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $ProjectPath

$start = (Get-Date).AddMinutes(2)
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# UAT deliberately uses the current interactive user because the existing Spiro OAuth
# token store is DPAPI-protected to that user. This avoids storing a Windows password.
# Production should move to a dedicated non-interactive credential design before using
# RunWhetherUserIsLoggedOn or a service identity.
$principal = New-ScheduledTaskPrincipal -UserId $currentIdentity -LogonType Interactive -RunLevel Highest
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Processes Business Central Spiro quote-link writeback queue in UAT. Uses the current user DPAPI-bound Spiro OAuth token store.'

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH WORKER SCHEDULE UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name         : $TaskName"
Write-Host "Run As            : $currentIdentity"
Write-Host "Logon Type        : Interactive"
Write-Host "PowerShell         : $pwsh"
Write-Host "Worker             : $worker"
Write-Host "Arguments          : $arguments"
Write-Host "Interval Minutes   : $IntervalMinutes"
Write-Host 'Repetition Window  : 3650 days'
Write-Host "First Start        : $start"
Write-Host 'Multiple Instances : IgnoreNew'
Write-Host 'Network Required   : True'
Write-Host 'Execution Limit    : 10 minutes'
Write-Host 'Restart Policy     : 2 retries, 1 minute apart'
Write-Host "Install Requested  : $($Install.IsPresent)"
Write-Host "Enable Requested   : $($Enable.IsPresent)"

if (-not $Install) {
    Write-Host ''
    Write-Host 'PREVIEW ONLY. No scheduled task was created or changed.' -ForegroundColor Green
    Write-Host 'Review this definition, then rerun with -Install to register it disabled.' -ForegroundColor Cyan
    Write-Host 'Use -Install -Enable only after disabled-task validation is complete.' -ForegroundColor Yellow
    return
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    throw "Scheduled task '$TaskName' already exists. Uninstall it first or choose a different TaskName."
}

Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop | Out-Null
Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($registered.State -ne 'Disabled') {
    throw "Task '$TaskName' was expected to be Disabled immediately after registration. Current state: $($registered.State)"
}

Write-Host ''
Write-Host "REGISTERED: $TaskName" -ForegroundColor Green
Write-Host 'Initial State: Disabled' -ForegroundColor Green

if ($Enable) {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    $registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host "Enabled State: $($registered.State)" -ForegroundColor Green
}
else {
    Write-Host 'The task remains disabled for validation.' -ForegroundColor Yellow
}