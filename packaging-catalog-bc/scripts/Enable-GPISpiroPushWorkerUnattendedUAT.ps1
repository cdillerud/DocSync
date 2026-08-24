[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended',
    [string]$LegacyTaskName = 'GPI Spiro Push Worker UAT'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'ENABLE GPI SPIRO UNATTENDED WORKER UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan

$legacy = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
if ($legacy -and $legacy.State -ne 'Disabled') {
    throw "Legacy task '$LegacyTaskName' must remain Disabled. Current state: $($legacy.State)"
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $TaskName

if ($task.Principal.LogonType -ne 'Password') {
    throw "Expected Password logon type. Found: $($task.Principal.LogonType)"
}
if ($info.LastTaskResult -ne 0) {
    throw "Refusing to enable because the most recent controlled run did not return 0. LastTaskResult=$($info.LastTaskResult)"
}

Write-Host "Task Name        : $TaskName"
Write-Host "Current State    : $($task.State)"
Write-Host "Run As           : $($task.Principal.UserId)"
Write-Host "Logon Type       : $($task.Principal.LogonType)"
Write-Host "Last Run Time    : $($info.LastRunTime)"
Write-Host "Last Task Result : $($info.LastTaskResult)"
if ($legacy) { Write-Host "Legacy Task      : $($legacy.State)" }

if ($task.State -ne 'Disabled') {
    Write-Host 'Task is already enabled or active. No change made.' -ForegroundColor Yellow
} else {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    Start-Sleep -Seconds 2
}

$taskAfter = Get-ScheduledTask -TaskName $TaskName
$infoAfter = Get-ScheduledTaskInfo -TaskName $TaskName
$legacyAfter = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue

if ($taskAfter.State -eq 'Disabled') {
    throw 'Task is still Disabled after enable attempt.'
}
if ($legacyAfter -and $legacyAfter.State -ne 'Disabled') {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    throw "Safety rollback: legacy task '$LegacyTaskName' is not Disabled. New unattended task was disabled again."
}

Write-Host ''
Write-Host 'PASS: unattended worker task is enabled.' -ForegroundColor Green
Write-Host "State            : $($taskAfter.State)"
Write-Host "Next Run Time    : $($infoAfter.NextRunTime)"
Write-Host "Last Task Result : $($infoAfter.LastTaskResult)"
if ($legacyAfter) { Write-Host "Legacy Task      : $($legacyAfter.State)" }
Write-Host 'The task will now run on its configured recurring schedule.' -ForegroundColor Green
