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