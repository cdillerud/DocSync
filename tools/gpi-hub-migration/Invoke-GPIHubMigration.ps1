#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$NoSelfUpdate,
    [switch]$Once,
    [int]$WatchSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ControlBranch = 'migration/gpi-hub-dedicated-vm'
$ScriptPath = $PSCommandPath
$ToolRoot = Split-Path -Parent $ScriptPath
$StatePath = Join-Path $ToolRoot 'state.json'
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"
$SparsePath = 'tools/gpi-hub-migration'

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

    $stdoutTask = $p.StandardOutput.ReadToEndAsync()
    $stderrTask = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()

    $result = [pscustomobject]@{
        ExitCode = $p.ExitCode
        StdOut   = $stdoutTask.GetAwaiter().GetResult()
        StdErr   = $stderrTask.GetAwaiter().GetResult()
    }

    if (-not $AllowFailure -and $result.ExitCode -ne 0) {
        throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)"
    }

    return $result
}

function Get-State {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    return (Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50)
}

function Update-ControlWorktree {
    $RepoRootResult = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$ToolRoot,'rev-parse','--show-toplevel'
    )
    $RepoRoot = $RepoRootResult.StdOut.Trim()
    Require (-not [string]::IsNullOrWhiteSpace($RepoRoot)) 'Could not resolve migration worktree root.'

    $Status = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'status','--porcelain'
    )
    Require ([string]::IsNullOrWhiteSpace($Status.StdOut)) `
        "Migration control worktree has local changes. Refusing self-update:`n$($Status.StdOut)"

    Write-Host 'Updating sparse migration control worktree from GitHub...' -ForegroundColor Cyan

    $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'fetch','--prune','origin',$FetchRefspec
    )

    $Verify = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'rev-parse','--verify',$RemoteTrackingRef
    )
    Require (-not [string]::IsNullOrWhiteSpace($Verify.StdOut)) `
        "Migration remote-tracking ref is unavailable: $RemoteTrackingRef"

    # Keep the control worktree sparse before every reset. This is required on
    # Windows because the full DocSync tree contains at least one path that is
    # legal in Git but cannot be materialized as a normal Windows pathname.
    $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'sparse-checkout','init','--cone'
    )
    $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'sparse-checkout','set',$SparsePath
    )
    $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
        '-C',$RepoRoot,'reset','--hard',$RemoteTrackingRef
    )

    Write-Host 'GPI_MIGRATION_SPARSE_REPO_UPDATE=PASS' -ForegroundColor Green

    $ChildArgs = @(
        '-NoProfile','-ExecutionPolicy','Bypass',
        '-File',$ScriptPath,
        '-NoSelfUpdate',
        '-WatchSeconds',"$WatchSeconds"
    )
    if ($Once) { $ChildArgs += '-Once' }

    $child = Invoke-Native -FilePath 'pwsh.exe' -Arguments $ChildArgs -AllowFailure
    if ($child.StdOut) { Write-Host $child.StdOut }
    if ($child.StdErr) { Write-Host $child.StdErr -ForegroundColor DarkYellow }
    exit $child.ExitCode
}

function Get-LatestKnownHosts {
    param([Parameter(Mandatory)][string]$OperationalRoot)

    $DiagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    Require (Test-Path -LiteralPath $DiagRoot -PathType Container) `
        "Diagnostics root not found: $DiagRoot"

    $candidates = @(
        Get-ChildItem -LiteralPath $DiagRoot -Filter 'target-known_hosts' -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'migration-v99' } |
        Sort-Object LastWriteTime -Descending
    )

    Require ($candidates.Count -gt 0) `
        'No V99 target-known_hosts file was found. Run the current V99 phase once so Azure-verified SSH trust exists.'

    return $candidates[0].FullName
}

function Invoke-TargetStatus {
    param([Parameter(Mandatory)]$State)

    $OperationalRoot = [string]$State.local.operational_root
    $KeyPath = [string]$State.local.ssh_key
    $TargetIp = [string]$State.target.public_ip
    $TargetUser = 'azureuser'
    $KnownHosts = Get-LatestKnownHosts -OperationalRoot $OperationalRoot

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key not found: $KeyPath"

    $RemoteScript = @'
set -euo pipefail

echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

APP=/gpi-hub-data/apps/gpi-hub
UPLOADS=/gpi-hub-data/volumes/uploads
MIG=/gpi-hub-data/migration

app_bytes=$(sudo du -sb "$APP" 2>/dev/null | cut -f1 || echo 0)
upload_bytes=$(sudo du -sb "$UPLOADS" 2>/dev/null | cut -f1 || echo 0)
mig_bytes=$(sudo du -sb "$MIG" 2>/dev/null | cut -f1 || echo 0)

echo "APP_BYTES=$app_bytes"
echo "UPLOAD_BYTES=$upload_bytes"
echo "MIG_BYTES=$mig_bytes"

echo 'PROCESS_BEGIN'
ps -eo pid=,etime=,args= | grep -E '[r]sync|[d]ocker save|[d]ocker load|[m]ongodump|[s]ha256sum.*mongo-firstpass' || true
echo 'PROCESS_END'

archive=$(ls -1t "$MIG"/mongo-firstpass-*.archive.gz 2>/dev/null | head -n 1 || true)
if [ -n "$archive" ]; then
  echo "MONGO_ARCHIVE=$archive"
  echo "MONGO_BYTES=$(stat -c %s "$archive")"
else
  echo 'MONGO_ARCHIVE='
  echo 'MONGO_BYTES=0'
fi

summary=$(ls -1t "$MIG"/v99-firstpass-*.json 2>/dev/null | head -n 1 || true)
if [ -n "$summary" ]; then
  echo "SUMMARY=$summary"
  echo 'SUMMARY_BEGIN'
  cat "$summary"
  echo 'SUMMARY_END'
else
  echo 'SUMMARY='
fi

df -B1 --output=size,used,avail,pcent /gpi-hub-data | tail -n 1 | awk '{print "DISK_SIZE=" $1 "\nDISK_USED=" $2 "\nDISK_AVAIL=" $3 "\nDISK_PCT=" $4}'
'@

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = 'ssh.exe'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    foreach ($arg in @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "$TargetUser@$TargetIp",
        'bash -s'
    )) {
        [void]$psi.ArgumentList.Add($arg)
    }

    $p = [System.Diagnostics.Process]::new()
    $p.StartInfo = $psi
    Require ($p.Start()) 'Could not start target SSH status probe.'

    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.Write(($RemoteScript -replace "`r`n","`n"))
    $p.StandardInput.Close()
    $p.WaitForExit()

    $stdout = $outTask.GetAwaiter().GetResult()
    $stderr = $errTask.GetAwaiter().GetResult()
    Require ($p.ExitCode -eq 0) "Target status probe failed.`n$stdout`n$stderr"

    $values = @{}
    foreach ($line in (($stdout -replace "`r",'') -split "`n")) {
        if ($line -match '^([A-Z_]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    $baseline = [double]$State.source.uploads_bytes_baseline
    $current = if ($values.ContainsKey('UPLOAD_BYTES')) { [double]$values.UPLOAD_BYTES } else { 0 }
    $pct = if ($baseline -gt 0) { [Math]::Min(100,[Math]::Round(($current / $baseline) * 100,1)) } else { 0 }

    $processText = ''
    if ($stdout -match '(?s)PROCESS_BEGIN\s*(.*?)\s*PROCESS_END') {
        $processText = $Matches[1].Trim()
    }

    $summaryPresent = $values.ContainsKey('SUMMARY') -and -not [string]::IsNullOrWhiteSpace([string]$values.SUMMARY)

    Write-Host ''
    Write-Host ('=' * 88) -ForegroundColor Cyan
    Write-Host "GPI HUB MIGRATION — $($State.phase)" -ForegroundColor Cyan
    Write-Host ('=' * 88) -ForegroundColor Cyan
    Write-Host "UTC               : $($values.UTC)"
    Write-Host ("App copied         : {0:N2} GiB" -f (([double]$values.APP_BYTES) / 1GB))
    Write-Host ("Uploads copied     : {0:N2} / {1:N2} GiB ({2}%)" -f ($current/1GB),($baseline/1GB),$pct)
    Write-Host ("Migration staging  : {0:N2} GiB" -f (([double]$values.MIG_BYTES) / 1GB))
    Write-Host "Mongo archive      : $($values.MONGO_ARCHIVE)"
    Write-Host ("Mongo bytes        : {0:N2} GiB" -f (([double]$values.MONGO_BYTES) / 1GB))
    Write-Host "Target disk free   : $([Math]::Round(([double]$values.DISK_AVAIL)/1GB,1)) GiB"
    Write-Host "V99 summary present: $summaryPresent"

    Write-Host ''
    Write-Host 'Active transfer processes:'
    if ([string]::IsNullOrWhiteSpace($processText)) {
        Write-Host '  none detected'
    }
    else {
        $processText -split "`n" | ForEach-Object { Write-Host "  $_" }
    }

    if ($summaryPresent) {
        Write-Host ''
        Write-Host 'V99_FIRST_PASS_REMOTE_SUMMARY=FOUND' -ForegroundColor Green
        return $true
    }

    Write-Host ''
    Write-Host 'V99_FIRST_PASS_REMOTE_SUMMARY=NOT_YET' -ForegroundColor Yellow
    return $false
}

function Invoke-ConfiguredPhase {
    param([Parameter(Mandatory)]$State)

    switch ([string]$State.mode) {
        'monitor-v99' {
            do {
                $complete = Invoke-TargetStatus -State $State
                if ($complete -or $Once) { break }
                Write-Host "`nChecking again in $WatchSeconds seconds. Ctrl+C only stops this monitor; it does not stop V99." -ForegroundColor DarkGray
                Start-Sleep -Seconds $WatchSeconds
            } while ($true)
            return
        }

        'run-script' {
            $Relative = [string]$State.script
            Require (-not [string]::IsNullOrWhiteSpace($Relative)) 'state.json run-script mode has no script path.'
            $PhaseScript = Join-Path $ToolRoot $Relative
            Require (Test-Path -LiteralPath $PhaseScript -PathType Leaf) "Phase script missing: $PhaseScript"

            Write-Host "Running repo-controlled phase: $($State.phase)" -ForegroundColor Cyan
            & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $PhaseScript
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            return
        }

        'hold' {
            Write-Host "Migration control is on HOLD: $($State.phase)" -ForegroundColor Yellow
            Write-Host ([string]$State.notes)
            return
        }

        default {
            throw "Unknown migration mode in state.json: $($State.mode)"
        }
    }
}

if (-not $NoSelfUpdate) {
    Update-ControlWorktree
}

$State = Get-State
Invoke-ConfiguredPhase -State $State
