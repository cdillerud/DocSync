[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Scheduled task '$TaskName' is not installed." -ForegroundColor Yellow
    return
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
$action = @($task.Actions) | Select-Object -First 1
$trigger = @($task.Triggers) | Select-Object -First 1

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH WORKER UNATTENDED TASK STATUS UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name       : $TaskName"
Write-Host "State           : $($task.State)"
Write-Host "Run As          : $($task.Principal.UserId)"
Write-Host "Logon Type      : $($task.Principal.LogonType)"
Write-Host "Run Level       : $($task.Principal.RunLevel)"
Write-Host "Last Run Time   : $($info.LastRunTime)"
Write-Host "Last Result     : $($info.LastTaskResult)"
Write-Host "Next Run Time   : $($info.NextRunTime)"
Write-Host "Execute         : $($action.Execute)"
Write-Host "Arguments       : $($action.Arguments)"
Write-Host "Working Dir     : $($action.WorkingDirectory)"
if ($trigger -and $trigger.Repetition) {
    Write-Host "Repeat Interval : $($trigger.Repetition.Interval)"
}