#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRepo = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs',
    [string]$MigrationWorktree = 'C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration',
    [string]$ControlBranch = 'migration/gpi-hub-dedicated-vm'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Source repo not found: $SourceRepo"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe is not available.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe is not available.'

Write-Host 'GPI Hub migration bootstrap' -ForegroundColor Cyan
Write-Host "Source worktree    : $SourceRepo"
Write-Host "Control worktree   : $MigrationWorktree"
Write-Host "Control branch     : $ControlBranch"
Write-Host ''
Write-Host 'The existing DocSync-Zetadocs working tree will NOT be checked out, reset, cleaned, or modified.' -ForegroundColor Yellow

& git.exe -C $SourceRepo rev-parse --is-inside-work-tree | Out-Null
Require ($LASTEXITCODE -eq 0) 'Source path is not a Git working tree.'

Write-Host 'Fetching migration control branch...' -ForegroundColor Cyan
& git.exe -C $SourceRepo fetch --prune origin $ControlBranch
Require ($LASTEXITCODE -eq 0) 'Could not fetch migration control branch.'

if (-not (Test-Path -LiteralPath $MigrationWorktree -PathType Container)) {
    Write-Host 'Creating dedicated migration worktree...' -ForegroundColor Cyan
    & git.exe -C $SourceRepo worktree add -B gpi-hub-migration $MigrationWorktree "origin/$ControlBranch"
    Require ($LASTEXITCODE -eq 0) 'Could not create migration worktree.'
}
else {
    Write-Host 'Dedicated migration worktree already exists; leaving its directory in place.' -ForegroundColor Cyan
    & git.exe -C $MigrationWorktree rev-parse --is-inside-work-tree | Out-Null
    Require ($LASTEXITCODE -eq 0) 'Existing migration worktree path is not a Git worktree.'

    $Status = (& git.exe -C $MigrationWorktree status --porcelain | Out-String).Trim()
    Require ([string]::IsNullOrWhiteSpace($Status)) `
        "Migration worktree has local changes and will not be reset:`n$Status"

    & git.exe -C $MigrationWorktree fetch --prune origin $ControlBranch
    Require ($LASTEXITCODE -eq 0) 'Could not refresh migration worktree.'

    & git.exe -C $MigrationWorktree reset --hard "origin/$ControlBranch"
    Require ($LASTEXITCODE -eq 0) 'Could not update migration worktree.'
}

$Runner = Join-Path $MigrationWorktree 'tools\gpi-hub-migration\Invoke-GPIHubMigration.ps1'
Require (Test-Path -LiteralPath $Runner -PathType Leaf) "Repo runner not found: $Runner"

Write-Host ''
Write-Host 'GPI_HUB_MIGRATION_BOOTSTRAP=PASS' -ForegroundColor Green
Write-Host "Runner: $Runner"
Write-Host ''

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $Runner
exit $LASTEXITCODE
