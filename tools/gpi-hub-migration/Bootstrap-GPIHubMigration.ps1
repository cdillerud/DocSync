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

function Invoke-Git {
    param(
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    & git.exe -C $WorkingDirectory @Arguments
    $code = $LASTEXITCODE

    if (-not $AllowFailure -and $code -ne 0) {
        throw "git failed ($code): git -C $WorkingDirectory $($Arguments -join ' ')"
    }

    return $code
}

Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Source repo not found: $SourceRepo"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe is not available.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe is not available.'

$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"
$SparsePath = 'tools/gpi-hub-migration'

Write-Host 'GPI Hub migration bootstrap' -ForegroundColor Cyan
Write-Host "Source worktree    : $SourceRepo"
Write-Host "Control worktree   : $MigrationWorktree"
Write-Host "Control branch     : $ControlBranch"
Write-Host "Sparse checkout    : $SparsePath only"
Write-Host ''
Write-Host 'The existing DocSync-Zetadocs working tree will NOT be checked out, reset, cleaned, or modified.' -ForegroundColor Yellow
Write-Host 'The control worktree intentionally does NOT materialize the full DocSync tree on Windows.' -ForegroundColor Yellow

$null = Invoke-Git -WorkingDirectory $SourceRepo -Arguments @('rev-parse','--is-inside-work-tree')

Write-Host 'Fetching migration control branch into an explicit remote-tracking ref...' -ForegroundColor Cyan
$null = Invoke-Git -WorkingDirectory $SourceRepo -Arguments @('fetch','--prune','origin',$FetchRefspec)
$null = Invoke-Git -WorkingDirectory $SourceRepo -Arguments @('rev-parse','--verify',$RemoteTrackingRef)
Write-Host 'GPI_HUB_MIGRATION_CONTROL_REF=PASS' -ForegroundColor Green

# Recover automatically from an earlier failed full checkout. The dedicated
# migration directory contains no authoritative application state.
$WorktreeValid = $false
if (Test-Path -LiteralPath $MigrationWorktree -PathType Container) {
    & git.exe -C $MigrationWorktree rev-parse --is-inside-work-tree *> $null
    $WorktreeValid = ($LASTEXITCODE -eq 0)
}

if (-not $WorktreeValid -and (Test-Path -LiteralPath $MigrationWorktree -PathType Container)) {
    Write-Host 'Recovering failed/partial migration worktree from prior Windows checkout attempt...' -ForegroundColor Yellow

    # Remove stale registration first, if any. Never touch SourceRepo contents.
    & git.exe -C $SourceRepo worktree remove --force $MigrationWorktree 2>$null
    & git.exe -C $SourceRepo worktree prune 2>$null

    if (Test-Path -LiteralPath $MigrationWorktree -PathType Container) {
        Remove-Item -LiteralPath $MigrationWorktree -Recurse -Force
    }

    Write-Host 'GPI_HUB_MIGRATION_PARTIAL_WORKTREE_RECOVERY=PASS' -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $MigrationWorktree -PathType Container)) {
    Write-Host 'Creating sparse dedicated migration worktree with NO initial checkout...' -ForegroundColor Cyan

    & git.exe -C $SourceRepo worktree add --no-checkout -B gpi-hub-migration $MigrationWorktree $RemoteTrackingRef
    Require ($LASTEXITCODE -eq 0) 'Could not create no-checkout migration worktree.'

    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('sparse-checkout','init','--cone')
    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('sparse-checkout','set',$SparsePath)
    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('reset','--hard',$RemoteTrackingRef)
}
else {
    Write-Host 'Dedicated migration worktree already exists; validating sparse control state...' -ForegroundColor Cyan

    $Status = (& git.exe -C $MigrationWorktree status --porcelain | Out-String).Trim()
    Require ([string]::IsNullOrWhiteSpace($Status)) `
        "Migration control worktree has local changes and will not be reset:`n$Status"

    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('fetch','--prune','origin',$FetchRefspec)
    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('sparse-checkout','init','--cone')
    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('sparse-checkout','set',$SparsePath)
    $null = Invoke-Git -WorkingDirectory $MigrationWorktree -Arguments @('reset','--hard',$RemoteTrackingRef)
}

$Runner = Join-Path $MigrationWorktree 'tools\gpi-hub-migration\Invoke-GPIHubMigration.ps1'
Require (Test-Path -LiteralPath $Runner -PathType Leaf) "Repo runner not found: $Runner"

Write-Host 'GPI_HUB_MIGRATION_SPARSE_WORKTREE=PASS' -ForegroundColor Green

$Desktop = [Environment]::GetFolderPath('Desktop')
$Launcher = Join-Path $Desktop 'GPI Hub Migration.cmd'
$LauncherContent = @"
@echo off
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "$Runner"
echo.
pause
"@
Set-Content -LiteralPath $Launcher -Value $LauncherContent -Encoding ascii

Write-Host ''
Write-Host 'GPI_HUB_MIGRATION_BOOTSTRAP=PASS' -ForegroundColor Green
Write-Host "Runner          : $Runner"
Write-Host "Desktop launcher: $Launcher"
Write-Host ''
Write-Host 'After this bootstrap, use the desktop launcher. It self-updates from the repo control branch before each run.' -ForegroundColor Green
Write-Host ''

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $Runner
exit $LASTEXITCODE
