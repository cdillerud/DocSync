[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended',
    [string]$LegacyTaskName = 'GPI Spiro Push Worker UAT',
    [int]$WaitMinutes = 7,
    [string]$LogDirectory = "$env:LOCALAPPDATA\GPI\SpiroPushWorker\Logs"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($WaitMinutes -lt 1 -or $WaitMinutes -gt 30) {
    throw 'WaitMinutes must be between 1 and 30.'
}

$legacy = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
if ($legacy -and $legacy.State -ne 'Disabled') {
    throw "Legacy task '$LegacyTaskName' must remain Disabled. Current state: $($legacy.State)"
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$before = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
$beforeRun = $before.LastRunTime

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH WORKER SCHEDULED RUN VERIFICATION UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name       : $TaskName"
Write-Host "State           : $($task.State)"
Write-Host "Last Run Before : $beforeRun"
Write-Host "Last Result     : $($before.LastTaskResult)"
Write-Host "Next Run Time   : $($before.NextRunTime)"
Write-Host "Wait Minutes    : $WaitMinutes"
if ($legacy) { Write-Host "Legacy Task     : $($legacy.State)" }

if ($task.State -eq 'Disabled') {
    throw "Scheduled task '$TaskName' is disabled. Enable it before running unattended verification."
}

$deadline = (Get-Date).AddMinutes($WaitMinutes)
$advanced = $false

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $current = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    if ($current.LastRunTime -gt $beforeRun) {
        $advanced = $true
        break
    }
    Write-Host "Waiting... next scheduled run is $($current.NextRunTime)" -ForegroundColor DarkGray
}

if (-not $advanced) {
    throw "The scheduled task did not record a new run within $WaitMinutes minute(s)."
}

# Allow the run a short period to finish if LastRunTime advanced while still running.
$finishDeadline = (Get-Date).AddMinutes(2)
do {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($task.State -ne 'Running') { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $finishDeadline)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$after = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'SCHEDULED RUN RESULT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "State          : $($task.State)"
Write-Host "Last Run After : $($after.LastRunTime)"
Write-Host "Last Result    : $($after.LastTaskResult)"
Write-Host "Next Run Time  : $($after.NextRunTime)"

if ($after.LastRunTime -le $beforeRun) {
    throw 'LastRunTime did not advance.'
}
if ($after.LastTaskResult -ne 0) {
    throw "Scheduled worker returned non-zero result: $($after.LastTaskResult)"
}
if ($task.State -notin @('Ready','Running')) {
    throw "Unexpected scheduled task state after run: $($task.State)"
}

if (-not (Test-Path -LiteralPath $LogDirectory)) {
    throw "Worker log directory not found: $LogDirectory"
}

$latestLog = Get-ChildItem -LiteralPath $LogDirectory -Filter 'SpiroPushWorker-*.log' -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $latestLog) {
    throw 'No Spiro worker transcript log was found.'
}

Write-Host "Latest Log     : $($latestLog.FullName)"
Write-Host "Log Modified   : $($latestLog.LastWriteTime)"

if ($latestLog.LastWriteTime -lt $after.LastRunTime.AddMinutes(-1)) {
    throw 'Latest worker log is not fresh enough to correspond to the scheduled run.'
}

$tail = Get-Content -LiteralPath $latestLog.FullName -Tail 80
$tailText = $tail -join "`n"
if (-not $tailText.Contains('OPERATIONAL WORKER COMPLETE')) {
    throw 'Latest worker log does not contain OPERATIONAL WORKER COMPLETE.'
}
if (-not $tailText.Contains('Mode   : APPLY')) {
    throw 'Latest worker log does not show APPLY mode.'
}

Write-Host ''
Write-Host '================ LATEST LOG TAIL ============================' -ForegroundColor Cyan
$tail

Write-Host ''
Write-Host 'PASS: unattended scheduled worker executed successfully.' -ForegroundColor Green

