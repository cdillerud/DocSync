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

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-native-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }

    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }

        $output = & $FilePath @Arguments 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        } else { '' }

        $result = [pscustomobject]@{
            ExitCode = [int]$code
            StdOut   = [string]$stdout
            StdErr   = [string]$stderr
        }

        if (-not $AllowFailure -and $result.ExitCode -ne 0) {
            throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)"
        }

        return $result
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-GitFileText {
    param(
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$Ref,
        [Parameter(Mandatory)][string]$RepoPath
    )

    $spec = '{0}:{1}' -f $Ref,$RepoPath
    $r = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$Repo,'show',$spec)
    Require ($r.ExitCode -eq 0) "Could not read $RepoPath from $Ref."
    return [string]$r.StdOut
}

Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Source repo not found: $SourceRepo"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe is not available.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe is not available.'
Require ($MigrationControlRoot -ne $SourceRepo) 'Migration control root must be separate from application working tree.'

$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"
$ToolPrefix = 'tools/gpi-hub-migration/'
$ManifestRepoPath = "${ToolPrefix}control-files.txt"

Write-Host 'GPI Hub migration bootstrap' -ForegroundColor Cyan
Write-Host "Source repo        : $SourceRepo"
Write-Host "Control folder     : $MigrationControlRoot"
Write-Host "Control branch     : $ControlBranch"
Write-Host 'Materialization    : per-file git show manifest'
Write-Host ''
Write-Host 'The existing DocSync-Zetadocs working tree will NOT be checked out, reset, cleaned, archived, or modified.' -ForegroundColor Yellow
Write-Host 'No Git worktree, index, tree traversal, archive, or checkout is used for the migration controller.' -ForegroundColor Yellow

$probe = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'rev-parse','--is-inside-work-tree')
Require ($probe.StdOut.Trim() -eq 'true') 'Source path is not a Git working tree.'
Write-Host 'GPI_HUB_NATIVE_COMPATIBILITY=PASS' -ForegroundColor Green

Write-Host 'Fetching migration control branch into explicit remote-tracking ref...' -ForegroundColor Cyan
$null = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'fetch','--prune','origin',$FetchRefspec)
$verify = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'rev-parse','--verify',$RemoteTrackingRef)
Require (-not [string]::IsNullOrWhiteSpace($verify.StdOut)) "Remote-tracking ref unavailable: $RemoteTrackingRef"
Write-Host 'GPI_HUB_MIGRATION_CONTROL_REF=PASS' -ForegroundColor Green

# Clean stale registration from earlier abandoned worktree attempts. Failure is harmless.
$null = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'worktree','remove','--force',$MigrationControlRoot) -AllowFailure
$null = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$SourceRepo,'worktree','prune') -AllowFailure
Write-Host 'GPI_HUB_MIGRATION_WORKTREE_RECOVERY=PASS' -ForegroundColor Green

$manifestText = Get-GitFileText -Repo $SourceRepo -Ref $RemoteTrackingRef -RepoPath $ManifestRepoPath
$controlFiles = @(
    ($manifestText -replace "`r",'') -split "`n" |
    ForEach-Object { $_.Trim() } |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
Require ($controlFiles.Count -gt 0) 'Migration control manifest is empty.'
Require ($controlFiles -contains $ManifestRepoPath) 'Migration control manifest must include itself.'

if (Test-Path -LiteralPath $MigrationControlRoot) {
    Remove-Item -LiteralPath $MigrationControlRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $MigrationControlRoot -Force | Out-Null

Write-Host "Materializing $($controlFiles.Count) explicit control files with git show..." -ForegroundColor Cyan
foreach ($repoPath in $controlFiles) {
    Require ($repoPath.StartsWith($ToolPrefix,[System.StringComparison]::Ordinal)) "Manifest path escapes control subtree: $repoPath"
    Require ($repoPath -notmatch '(^|/)\.\.(/|$)') "Manifest path contains parent traversal: $repoPath"

    $relative = $repoPath.Substring($ToolPrefix.Length).Replace('/','\')
    Require (-not [string]::IsNullOrWhiteSpace($relative)) "Invalid manifest path: $repoPath"

    $destination = Join-Path (Join-Path $MigrationControlRoot 'tools\gpi-hub-migration') $relative
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null

    $content = Get-GitFileText -Repo $SourceRepo -Ref $RemoteTrackingRef -RepoPath $repoPath
    Set-Content -LiteralPath $destination -Value $content -Encoding utf8 -NoNewline
    Write-Host "  $repoPath"
}

$ToolRoot = Join-Path $MigrationControlRoot 'tools\gpi-hub-migration'
$Runner = Join-Path $ToolRoot 'Invoke-GPIHubMigration.ps1'
$State = Join-Path $ToolRoot 'state.json'
$ManifestLocal = Join-Path $ToolRoot 'control-files.txt'

Require (Test-Path -LiteralPath $Runner -PathType Leaf) "Repo runner missing after materialization: $Runner"
Require (Test-Path -LiteralPath $State -PathType Leaf) "Migration state missing after materialization: $State"
Require (Test-Path -LiteralPath $ManifestLocal -PathType Leaf) "Migration manifest missing after materialization: $ManifestLocal"
Write-Host 'GPI_HUB_MIGRATION_GIT_SHOW_MATERIALIZATION=PASS' -ForegroundColor Green

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
Write-Host 'After this bootstrap, use the Desktop launcher. It self-updates using only explicit git show file reads.' -ForegroundColor Green
Write-Host ''

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $Runner
exit $LASTEXITCODE
