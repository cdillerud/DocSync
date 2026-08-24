[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Save-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

$appJson = Join-Path $ProjectPath 'app.json'
$opsWorker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
$singleWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueUAT.ps1'
$installer = Join-Path $ProjectPath 'scripts\Install-GPISpiroPushWorkerTaskUnattendedUAT.ps1'
$statusScript = Join-Path $ProjectPath 'scripts\Get-GPISpiroPushWorkerTaskUnattendedUAT.ps1'
$verifyScript = Join-Path $ProjectPath 'scripts\Test-GPISpiroPushWorkerTaskUnattendedUAT.ps1'
$uninstallScript = Join-Path $ProjectPath 'scripts\Uninstall-GPISpiroPushWorkerTaskUnattendedUAT.ps1'

foreach ($file in @($appJson, $opsWorker, $singleWorker)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.28 file not found: $file"
    }
}

Write-Host "`n== PRECHECK 0.28 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.28.0.0') {
    throw "Expected local app version 0.28.0.0. Found $($app.version)."
}
$opsRaw = Get-Content -LiteralPath $opsWorker -Raw
$singleRaw = Get-Content -LiteralPath $singleWorker -Raw
foreach ($marker in @('SPIRO KEY VAULT TOKEN LIFECYCLE','Update-GPISpiroKeyVaultTokenUAT.ps1')) {
    if (-not $opsRaw.Contains($marker)) {
        throw "0.28 operational worker marker not found: $marker"
    }
}
if (-not $singleRaw.Contains("spiro-oauth-access-token")) {
    throw '0.28 single worker Key Vault access-token marker not found.'
}
if ($singleRaw.Contains('Import-Clixml -LiteralPath $TokenStorePath')) {
    throw '0.28 single worker still imports the DPAPI token store.'
}
Write-Host '0.28 Key Vault worker decoupling confirmed.' -ForegroundColor Green

Write-Host "`n== BUMP APP VERSION TO 0.29.0.0 ==" -ForegroundColor Cyan
$appText = Get-Content -LiteralPath $appJson -Raw
$oldVersion = '"version": "0.28.0.0"'
$newVersion = '"version": "0.29.0.0"'
if (-not $appText.Contains($oldVersion)) {
    throw '0.28 app version text was not found in app.json.'
}
$appText = $appText.Replace($oldVersion, $newVersion)
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Host "`n== CREATE UNATTENDED TASK INSTALLER ==" -ForegroundColor Cyan
$installerText = @'
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Enable,
    [int]$IntervalMinutes = 5,
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended',
    [string]$LegacyTaskName = 'GPI Spiro Push Worker UAT',
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [PSCredential]$Credential
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

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = [Security.Principal.WindowsPrincipal]$currentIdentity
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Install -and -not $isAdmin) {
    throw 'Run PowerShell 7 as Administrator to install the unattended task.'
}

$worker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
if (-not (Test-Path -LiteralPath $worker)) {
    throw "Operational worker not found: $worker"
}

$pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($pwsh)) {
    throw 'PowerShell 7 (pwsh.exe) is required.'
}

$legacy = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
if ($legacy -and $legacy.State -ne 'Disabled') {
    throw "Legacy task '$LegacyTaskName' must be Disabled before installing the unattended task. Current state: $($legacy.State)"
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

$previewUser = if ($Credential) { $Credential.UserName } else { $currentIdentity.Name }
$principal = New-ScheduledTaskPrincipal -UserId $previewUser -LogonType Password -RunLevel Highest
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Processes the Business Central Spiro quote-link queue in UAT using Key Vault credentials. Password logon allows execution without an interactive Windows session.'

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH WORKER UNATTENDED SCHEDULE UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Task Name         : $TaskName"
Write-Host "Legacy Task       : $LegacyTaskName"
Write-Host "Run As            : $previewUser"
Write-Host 'Logon Type        : Password'
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
Write-Host "Elevated           : $isAdmin"

if (-not $Install) {
    Write-Host ''
    Write-Host 'PREVIEW ONLY. No scheduled task was created or changed.' -ForegroundColor Green
    Write-Host 'The unattended task uses Password logon so it can run while the user is signed out.' -ForegroundColor Cyan
    Write-Host 'No Windows password is stored by this script or written to output.' -ForegroundColor Green
    return
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    throw "Scheduled task '$TaskName' already exists. Remove it first or choose another TaskName."
}

if (-not $Credential) {
    $Credential = Get-Credential -UserName $currentIdentity.Name -Message 'Enter the Windows credentials for the unattended GPI Spiro worker task.'
}
if (-not $Credential) {
    throw 'A Windows credential is required to register a Password-logon scheduled task.'
}

$userName = $Credential.UserName
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $principal = New-ScheduledTaskPrincipal -UserId $userName -LogonType Password -RunLevel Highest
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Processes the Business Central Spiro quote-link queue in UAT using Key Vault credentials. Password logon allows execution without an interactive Windows session.'
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -User $userName -Password $plainPassword -Force | Out-Null
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainPassword = $null
}

Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($registered.State -ne 'Disabled') {
    throw "Task '$TaskName' was expected to be Disabled after registration. Current state: $($registered.State)"
}
if ([string]$registered.Principal.LogonType -ne 'Password') {
    throw "Task '$TaskName' was expected to use Password logon. Actual: $($registered.Principal.LogonType)"
}

Write-Host ''
Write-Host "REGISTERED: $TaskName" -ForegroundColor Green
Write-Host 'Initial State: Disabled' -ForegroundColor Green
Write-Host "Run As       : $($registered.Principal.UserId)" -ForegroundColor Green
Write-Host "Logon Type   : $($registered.Principal.LogonType)" -ForegroundColor Green

if ($Enable) {
    Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    $registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host "Enabled State: $($registered.State)" -ForegroundColor Green
}
else {
    Write-Host 'The task remains disabled for controlled validation.' -ForegroundColor Yellow
}
'@
Save-Utf8NoBom -Path $installer -Content $installerText
Write-Host "Created: $installer" -ForegroundColor DarkGreen

Write-Host "`n== CREATE UNATTENDED TASK STATUS SCRIPT ==" -ForegroundColor Cyan
$statusText = @'
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
'@
Save-Utf8NoBom -Path $statusScript -Content $statusText
Write-Host "Created: $statusScript" -ForegroundColor DarkGreen

Write-Host "`n== CREATE CONTROLLED UNATTENDED TASK TEST ==" -ForegroundColor Cyan
$verifyText = @'
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
'@
Save-Utf8NoBom -Path $verifyScript -Content $verifyText
Write-Host "Created: $verifyScript" -ForegroundColor DarkGreen

Write-Host "`n== CREATE UNATTENDED TASK UNINSTALLER ==" -ForegroundColor Cyan
$uninstallText = @'
[CmdletBinding()]
param(
    [string]$TaskName = 'GPI Spiro Push Worker UAT Unattended',
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
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
'@
Save-Utf8NoBom -Path $uninstallScript -Content $uninstallText
Write-Host "Created: $uninstallScript" -ForegroundColor DarkGreen

Write-Host "`n== VALIDATE 0.29 UNATTENDED SCHEDULING FOUNDATION ==" -ForegroundColor Cyan
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.29.0.0"'; Label='0.29 app version' },
    @{ Path=$installer; Pattern="LogonType Password"; Label='Password logon principal' },
    @{ Path=$installer; Pattern='Legacy task'; Label='legacy-task safety guard' },
    @{ Path=$installer; Pattern='must be Disabled'; Label='legacy task disabled requirement' },
    @{ Path=$installer; Pattern='PREVIEW ONLY. No scheduled task was created or changed.'; Label='safe preview default' },
    @{ Path=$installer; Pattern='Get-Credential'; Label='secure credential prompt' },
    @{ Path=$installer; Pattern='ZeroFreeBSTR'; Label='password memory cleanup' },
    @{ Path=$installer; Pattern='Disable-ScheduledTask'; Label='disabled-by-default install' },
    @{ Path=$verifyScript; Pattern='Start-ScheduledTask'; Label='controlled execution test' },
    @{ Path=$verifyScript; Pattern='LastTaskResult -ne 0'; Label='exit-code verification' },
    @{ Path=$verifyScript; Pattern='Task returned to Disabled state'; Label='controlled-test rollback' },
    @{ Path=$statusScript; Pattern='Logon Type'; Label='status logon inspection' },
    @{ Path=$uninstallScript; Pattern='Type REMOVE'; Label='guarded uninstall' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host ''
Write-Host '0.29 unattended scheduling foundation applied successfully.' -ForegroundColor Green
Write-Host 'No scheduled task was created or changed by this upgrade helper.' -ForegroundColor Yellow
Write-Host 'The existing legacy task should remain Disabled while the new unattended task is validated.' -ForegroundColor Yellow
Write-Host 'Next: build 0.29, preview the unattended installer, then register it disabled with an explicit Windows credential.' -ForegroundColor Cyan
