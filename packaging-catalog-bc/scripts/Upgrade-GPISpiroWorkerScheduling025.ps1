[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Save-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

$appJson = Join-Path $ProjectPath 'app.json'
$opsWorker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
$installer = Join-Path $ProjectPath 'scripts\Install-GPISpiroPushWorkerTaskUAT.ps1'
$statusScript = Join-Path $ProjectPath 'scripts\Get-GPISpiroPushWorkerTaskUAT.ps1'
$uninstaller = Join-Path $ProjectPath 'scripts\Uninstall-GPISpiroPushWorkerTaskUAT.ps1'

foreach ($file in @($appJson, $opsWorker)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.24 file not found: $file"
    }
}

Write-Step 'PRECHECK 0.24'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.24.0.0') {
    throw "Expected local app version 0.24.0.0. Found $($app.version)."
}
$opsRaw = Get-Content -LiteralPath $opsWorker -Raw
foreach ($marker in @('STALE PROCESSING RECOVERY','Start-Transcript','[System.IO.FileShare]::None')) {
    if (-not $opsRaw.Contains($marker)) {
        throw "0.24 operational worker marker not found: $marker"
    }
}
Write-Host '0.24 operational worker confirmed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.25.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$oldVersion = '"version": "0.24.0.0"'
$newVersion = '"version": "0.25.0.0"'
if (-not $appText.Contains($oldVersion)) {
    throw '0.24 app version text was not found in app.json.'
}
$appText = $appText.Replace($oldVersion, $newVersion)
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Step 'CREATE UAT TASK INSTALLER'
$installerText = @'
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
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration ([TimeSpan]::MaxValue)

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
$principal = New-ScheduledTaskPrincipal -UserId $currentIdentity -LogonType InteractiveToken -RunLevel Highest
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Processes Business Central Spiro quote-link writeback queue in UAT. Uses the current user DPAPI-bound Spiro OAuth token store.'

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH WORKER SCHEDULE UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name         : $TaskName"
Write-Host "Run As            : $currentIdentity"
Write-Host "Logon Type        : InteractiveToken"
Write-Host "PowerShell         : $pwsh"
Write-Host "Worker             : $worker"
Write-Host "Arguments          : $arguments"
Write-Host "Interval Minutes   : $IntervalMinutes"
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

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null
Disable-ScheduledTask -TaskName $TaskName | Out-Null

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
'@
Save-Utf8NoBom -Path $installer -Content $installerText
Write-Host "Created: $installer" -ForegroundColor DarkGreen

Write-Step 'CREATE UAT TASK STATUS SCRIPT'
$statusText = @'
[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT'
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
Write-Host 'GPI SPIRO PUSH WORKER TASK STATUS UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name       : $TaskName"
Write-Host "State           : $($task.State)"
Write-Host "Run As          : $($task.Principal.UserId)"
Write-Host "Logon Type      : $($task.Principal.LogonType)"
Write-Host "Last Run Time   : $($info.LastRunTime)"
Write-Host "Last Result     : $($info.LastTaskResult)"
Write-Host "Next Run Time   : $($info.NextRunTime)"
Write-Host "Execute         : $($action.Execute)"
Write-Host "Arguments       : $($action.Arguments)"
Write-Host "Working Dir     : $($action.WorkingDirectory)"
if ($trigger -and $trigger.Repetition) {
    Write-Host "Repeat Interval : $($trigger.Repetition.Interval)"
}
'@
Save-Utf8NoBom -Path $statusScript -Content $statusText
Write-Host "Created: $statusScript" -ForegroundColor DarkGreen

Write-Step 'CREATE UAT TASK UNINSTALLER'
$uninstallerText = @'
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Scheduled task '$TaskName' is not installed." -ForegroundColor Yellow
    return
}

if (-not $Force) {
    $answer = Read-Host "Type REMOVE to unregister scheduled task '$TaskName'"
    if ($answer -cne 'REMOVE') {
        Write-Host 'Uninstall cancelled. No changes made.' -ForegroundColor Yellow
        return
    }
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
'@
Save-Utf8NoBom -Path $uninstaller -Content $uninstallerText
Write-Host "Created: $uninstaller" -ForegroundColor DarkGreen

Write-Step 'VALIDATE 0.25 SCHEDULING TOOLING'
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.25.0.0"'; Label='0.25 app version' },
    @{ Path=$installer; Pattern='PREVIEW ONLY. No scheduled task was created or changed.'; Label='safe preview default' },
    @{ Path=$installer; Pattern='Disable-ScheduledTask'; Label='disabled-by-default install' },
    @{ Path=$installer; Pattern='InteractiveToken'; Label='DPAPI-compatible UAT principal' },
    @{ Path=$installer; Pattern='-MultipleInstances IgnoreNew'; Label='duplicate-run protection' },
    @{ Path=$installer; Pattern='-RunOnlyIfNetworkAvailable'; Label='network requirement' },
    @{ Path=$installer; Pattern='-RestartCount 2'; Label='restart policy' },
    @{ Path=$statusScript; Pattern='Get-ScheduledTaskInfo'; Label='status inspection' },
    @{ Path=$uninstaller; Pattern="Type REMOVE"; Label='guarded uninstall' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.25 Spiro worker scheduling tooling applied successfully." -ForegroundColor Green
Write-Host 'No scheduled task was created by this upgrade helper.' -ForegroundColor Yellow
Write-Host 'Next: build 0.25, then run the installer with no switches to preview the task definition.' -ForegroundColor Cyan
