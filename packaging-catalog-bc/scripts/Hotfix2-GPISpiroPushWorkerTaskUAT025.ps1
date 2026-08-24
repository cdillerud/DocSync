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

Write-Host "`n== FIX TASK REPETITION DURATION ==" -ForegroundColor Cyan
$text = Get-Content -LiteralPath $installer -Raw

$oldDuration = '-RepetitionDuration ([TimeSpan]::MaxValue)'
$newDuration = '-RepetitionDuration (New-TimeSpan -Days 3650)'
if ($text.Contains($oldDuration)) {
    $text = $text.Replace($oldDuration, $newDuration)
}
elseif ($text.Contains($newDuration)) {
    Write-Host 'Already present: bounded repetition duration.' -ForegroundColor DarkYellow
}
else {
    throw 'Scheduled task repetition-duration anchor not found.'
}

$oldRegister = 'Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null'
$newRegister = 'Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop | Out-Null'
if ($text.Contains($oldRegister)) {
    $text = $text.Replace($oldRegister, $newRegister)
}
elseif ($text.Contains($newRegister)) {
    Write-Host 'Already present: fail-fast task registration.' -ForegroundColor DarkYellow
}
else {
    throw 'Scheduled task registration anchor not found.'
}

$oldDisable = 'Disable-ScheduledTask -TaskName $TaskName | Out-Null'
$newDisable = 'Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null'
if ($text.Contains($oldDisable)) {
    $text = $text.Replace($oldDisable, $newDisable)
}
elseif ($text.Contains($newDisable)) {
    Write-Host 'Already present: fail-fast task disable.' -ForegroundColor DarkYellow
}
else {
    throw 'Scheduled task disable anchor not found.'
}

$intervalLine = 'Write-Host "Interval Minutes   : $IntervalMinutes"'
$windowLine = "Write-Host 'Repetition Window  : 3650 days'"
if (-not $text.Contains($windowLine)) {
    if (-not $text.Contains($intervalLine)) {
        throw 'Preview interval output anchor not found.'
    }
    $replacement = $intervalLine + [Environment]::NewLine + $windowLine
    $text = $text.Replace($intervalLine, $replacement)
}

[System.IO.File]::WriteAllText($installer, $text, [System.Text.UTF8Encoding]::new($false))
Write-Host "Patched: $installer" -ForegroundColor DarkGreen

Write-Host "`n== VALIDATE 0.25 TASK DURATION HOTFIX ==" -ForegroundColor Cyan
$raw = Get-Content -LiteralPath $installer -Raw
$checks = @(
    @{ Passed = $raw.Contains('-RepetitionDuration (New-TimeSpan -Days 3650)'); Label = 'bounded repetition duration' },
    @{ Passed = -not $raw.Contains('[TimeSpan]::MaxValue'); Label = 'invalid max duration removed' },
    @{ Passed = $raw.Contains('Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop'); Label = 'registration fails fast' },
    @{ Passed = $raw.Contains('Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop'); Label = 'disable fails fast' },
    @{ Passed = $raw.Contains('-LogonType Interactive -RunLevel Highest'); Label = 'Interactive logon type preserved' },
    @{ Passed = $raw.Contains('Repetition Window  : 3650 days'); Label = 'preview shows bounded repetition window' },
    @{ Passed = $raw.Contains('PREVIEW ONLY. No scheduled task was created or changed.'); Label = 'preview-only default preserved' }
)

foreach ($check in $checks) {
    if (-not $check.Passed) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.25 scheduled-task duration hotfix applied successfully." -ForegroundColor Green
Write-Host 'No scheduled task was created or changed.' -ForegroundColor Yellow
Write-Host 'Re-run the installer in preview mode before registering the task.' -ForegroundColor Cyan
