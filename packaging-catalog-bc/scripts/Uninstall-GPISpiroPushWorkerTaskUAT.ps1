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