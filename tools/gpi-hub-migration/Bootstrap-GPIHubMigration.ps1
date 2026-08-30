#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$SourceRepo = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs',
    [string]$MigrationControlRoot = 'C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration',
    [string]$ControlBranch = 'migration/gpi-hub-dedicated-vm'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    foreach ($arg in $Arguments) {
        [void]$psi.ArgumentList.Add($arg)
    }

    $p = [System.Diagnostics.Process]::new()
    $p.StartInfo = $psi
    Require ($p.Start()) "Could not start $FilePath."

    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()

    $result = [pscustomobject]@{
        ExitCode = $p.ExitCode
        StdOut   = $outTask.GetAwaiter().GetResult()
        StdErr   = $errTask.GetAwaiter().GetResult()
    }

    if (-not $AllowFailure -and $result.ExitCode -ne 0) {
        throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)"
    }

    return $result
}

Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Source repo not found: $SourceRepo"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe is not available.'
Require ($null -ne (Get-Command tar.exe -ErrorAction SilentlyContinue)) 'tar.exe is not available.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe is not available.'
Require ($MigrationControlRoot -ne $SourceRepo) 'Migration control root must be separate from the application working tree.'

$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"
$ScopedPath = 'tools/gpi-hub-migration'
$ArchivePath = Join-Path $env:TEMP ("gpi-hub-control-" + [guid]::NewGuid().ToString('N') + '.tar')

Write-Host 'GPI Hub migration bootstrap' -ForegroundColor Cyan
Write-Host "Source repo        : $SourceRepo"
Write-Host "Control folder     : $MigrationControlRoot"
Write-Host "Control branch     : $ControlBranch"
Write-Host "Materialized path  : $ScopedPath only"
Write-Host ''
Write-Host 'The existing DocSync-Zetadocs working tree will NOT be checked out, reset, cleaned, or modified.' -ForegroundColor Yellow
Write-Host 'No Git worktree/index is used for the migration controller.' -ForegroundColor Yellow

$probe = Invoke-Native -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'rev-parse','--is-inside-work-tree')
Require ($probe.StdOut.Trim() -eq 'true') 'Source path is not a Git working tree.'

Write-Host 'Fetching migration control branch into explicit remote-tracking ref...' -ForegroundColor Cyan
$null = Invoke-Native -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'fetch','--prune','origin',$FetchRefspec)
$verify = Invoke-Native -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'rev-parse','--verify',$RemoteTrackingRef)
Require (-not [string]::IsNullOrWhiteSpace($verify.StdOut)) "Remote-tracking ref unavailable: $RemoteTrackingRef"
Write-Host 'GPI_HUB_MIGRATION_CONTROL_REF=PASS' -ForegroundColor Green

# Recover automatically from failed worktree attempts from earlier bootstrap versions.
Write-Host 'Removing stale migration worktree registration, if present...' -ForegroundColor Cyan
$null = Invoke-Native -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'worktree','remove','--force',$MigrationControlRoot) -AllowFailure
$null = Invoke-Native -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'worktree','prune') -AllowFailure
Write-Host 'GPI_HUB_MIGRATION_WORKTREE_RECOVERY=PASS' -ForegroundColor Green

if (Test-Path -LiteralPath $MigrationControlRoot) {
    Write-Host 'Removing previous non-authoritative migration control folder...' -ForegroundColor Cyan
    Remove-Item -LiteralPath $MigrationControlRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $MigrationControlRoot -Force | Out-Null

try {
    Write-Host 'Archiving ONLY the migration-control subtree from Git...' -ForegroundColor Cyan
    $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$SourceRepo,
        'archive','--format=tar',"--output=$ArchivePath",$RemoteTrackingRef,$ScopedPath
    )
    Require (Test-Path -LiteralPath $ArchivePath -PathType Leaf) 'Scoped migration-control archive was not created.'

    Write-Host 'Extracting migration controller without creating a Git index...' -ForegroundColor Cyan
    $null = Invoke-Native -FilePath 'tar.exe' -Arguments @('-xf',$ArchivePath,'-C',$MigrationControlRoot)
}
finally {
    Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
}

$ToolRoot = Join-Path $MigrationControlRoot 'tools\gpi-hub-migration'
$Runner = Join-Path $ToolRoot 'Invoke-GPIHubMigration.ps1'
$State = Join-Path $ToolRoot 'state.json'

Require (Test-Path -LiteralPath $Runner -PathType Leaf) "Repo runner not found after extraction: $Runner"
Require (Test-Path -LiteralPath $State -PathType Leaf) "Migration state not found after extraction: $State"
Write-Host 'GPI_HUB_MIGRATION_ARCHIVE_MATERIALIZATION=PASS' -ForegroundColor Green

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
Write-Host 'After this bootstrap, use the Desktop launcher. It self-updates by re-archiving only the migration-control subtree.' -ForegroundColor Green
Write-Host ''

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $Runner
exit $LASTEXITCODE
