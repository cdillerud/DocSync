[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended',
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ([string]$task.Principal.LogonType -ne 'Password') {
    throw "Expected Password logon. Actual: $($task.Principal.LogonType)"
}
if ($task.State -ne 'Disabled') {
    throw "Controlled UAT requires task '$TaskName' to begin Disabled. Current state: $($task.State)"
}

$before = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
$beforeRun = $before.LastRunTime

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO UNATTENDED TASK CONTROLLED TEST UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name      : $TaskName"
Write-Host "Run As         : $($task.Principal.UserId)"
Write-Host "Logon Type     : $($task.Principal.LogonType)"
Write-Host "Initial State  : $($task.State)"
Write-Host "Previous Run   : $beforeRun"

Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Seconds 2
        $taskNow = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $infoNow = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        $ran = $infoNow.LastRunTime -gt $beforeRun
        $finished = $ran -and $taskNow.State -ne 'Running'
    } while (-not $finished -and (Get-Date) -lt $deadline)

    if (-not $finished) {
        throw "Timed out waiting for task '$TaskName' to complete."
    }
    if ($infoNow.LastTaskResult -ne 0) {
        throw "Task '$TaskName' returned non-zero result $($infoNow.LastTaskResult)."
    }

    Write-Host "Last Run Time : $($infoNow.LastRunTime)"
    Write-Host "Last Result   : $($infoNow.LastTaskResult)"
    Write-Host 'PASS: Password-logon unattended task executed successfully.' -ForegroundColor Green
}
finally {
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Write-Host 'Task returned to Disabled state after controlled test.' -ForegroundColor Yellow
}