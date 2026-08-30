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
$ScopedPath = 'tools/gpi-hub-migration'
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"

function Require([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $token = [guid]::NewGuid().ToString('N')
    $stdoutFile = Join-Path $env:TEMP "gpi-native-$token.out.txt"
    $stderrFile = Join-Path $env:TEMP "gpi-native-$token.err.txt"

    try {
        & $FilePath @Arguments 1> $stdoutFile 2> $stderrFile
        $code = $LASTEXITCODE

        $stdout = if (Test-Path -LiteralPath $stdoutFile) {
            Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue
        } else { '' }

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
        Remove-Item -LiteralPath $stdoutFile,$stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-State {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    return (Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50)
}

function Update-ControlFolder {
    $CurrentState = Get-State
    $SourceRepo = [string]$CurrentState.local.operational_root

    Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Operational repo missing: $SourceRepo"
    Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
    Require ($null -ne (Get-Command tar.exe -ErrorAction SilentlyContinue)) 'tar.exe unavailable.'
    Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

    $ControlRoot = Split-Path -Parent (Split-Path -Parent $ToolRoot)
    $ArchivePath = Join-Path $env:TEMP ("gpi-hub-control-update-" + [guid]::NewGuid().ToString('N') + '.tar')
    $StageRoot = Join-Path $env:TEMP ("gpi-hub-control-stage-" + [guid]::NewGuid().ToString('N'))

    Write-Host 'Updating migration controller from GitHub using scoped git archive...' -ForegroundColor Cyan

    try {
        $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
            '-C',$SourceRepo,'fetch','--prune','origin',$FetchRefspec
        )

        $verify = Invoke-Native -FilePath 'git.exe' -Arguments @(
            '-C',$SourceRepo,'rev-parse','--verify',$RemoteTrackingRef
        )
        Require (-not [string]::IsNullOrWhiteSpace($verify.StdOut)) `
            "Migration remote-tracking ref unavailable: $RemoteTrackingRef"

        New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null

        $null = Invoke-Native -FilePath 'git.exe' -Arguments @(
            '-C',$SourceRepo,
            'archive','--format=tar',"--output=$ArchivePath",$RemoteTrackingRef,$ScopedPath
        )
        Require (Test-Path -LiteralPath $ArchivePath -PathType Leaf) 'Controller update archive was not created.'

        $null = Invoke-Native -FilePath 'tar.exe' -Arguments @('-xf',$ArchivePath,'-C',$StageRoot)

        $StageToolRoot = Join-Path $StageRoot 'tools\gpi-hub-migration'
        $StageRunner = Join-Path $StageToolRoot 'Invoke-GPIHubMigration.ps1'
        $StageState = Join-Path $StageToolRoot 'state.json'
        Require (Test-Path -LiteralPath $StageRunner -PathType Leaf) 'Staged runner missing.'
        Require (Test-Path -LiteralPath $StageState -PathType Leaf) 'Staged state missing.'

        Get-ChildItem -LiteralPath $StageToolRoot -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $ToolRoot -Recurse -Force
        }

        Write-Host "Control root : $ControlRoot"
        Write-Host "Control ref  : $($verify.StdOut.Trim())"
        Write-Host 'GPI_MIGRATION_ARCHIVE_SELF_UPDATE=PASS' -ForegroundColor Green
    }
    finally {
        Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    $ChildArgs = @(
        '-NoProfile','-ExecutionPolicy','Bypass',
        '-File',$ScriptPath,
        '-NoSelfUpdate',
        '-WatchSeconds',"$WatchSeconds"
    )
    if ($Once) { $ChildArgs += '-Once' }

    & pwsh.exe @ChildArgs
    exit $LASTEXITCODE
}

function Get-LatestKnownHosts {
    param([Parameter(Mandatory)][string]$OperationalRoot)

    $DiagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    Require (Test-Path -LiteralPath $DiagRoot -PathType Container) "Diagnostics root not found: $DiagRoot"

    $candidates = @(
        Get-ChildItem -LiteralPath $DiagRoot -Filter 'target-known_hosts' -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'migration-v99' } |
        Sort-Object LastWriteTime -Descending
    )

    Require ($candidates.Count -gt 0) 'No V99 target-known_hosts file was found.'
    return $candidates[0].FullName
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$KeyPath,
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$ScriptText
    )

    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-ssh-$token.err.txt"

    $sshArgs = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        $Target,
        'bash -s'
    )

    try {
        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @sshArgs 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = @($output) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        } else { '' }

        return [pscustomobject]@{
            ExitCode = [int]$code
            StdOut   = [string]$stdout
            StdErr   = [string]$stderr
        }
    }
    finally {
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-TargetStatus {
    param([Parameter(Mandatory)]$State)

    $OperationalRoot = [string]$State.local.operational_root
    $KeyPath = [string]$State.local.ssh_key
    $TargetIp = [string]$State.target.public_ip
    $TargetUser = 'azureuser'
    $KnownHosts = Get-LatestKnownHosts -OperationalRoot $OperationalRoot

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key not found: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'

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

    $probe = Invoke-SshScript `
        -KeyPath $KeyPath `
        -KnownHosts $KnownHosts `
        -Target "$TargetUser@$TargetIp" `
        -ScriptText $RemoteScript

    Require ($probe.ExitCode -eq 0) "Target status probe failed.`n$($probe.StdOut)`n$($probe.StdErr)"

    $stdout = $probe.StdOut
    $values = @{}
    foreach ($line in (($stdout -replace "`r",'') -split "`n")) {
        if ($line -match '^([A-Z_]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    foreach ($requiredKey in @('UTC','APP_BYTES','UPLOAD_BYTES','MIG_BYTES','MONGO_BYTES','DISK_AVAIL')) {
        Require ($values.ContainsKey($requiredKey)) "Target status response is missing $requiredKey."
    }

    $baseline = [double]$State.source.uploads_bytes_baseline
    $current = [double]$values.UPLOAD_BYTES
    $pct = if ($baseline -gt 0) {
        [Math]::Min(100,[Math]::Round(($current / $baseline) * 100,1))
    } else { 0 }

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
    Write-Host ("App copied         : {0:N2} GiB" -f (([double]$values.APP_BYTES / 1GB))
    Write-Host ("Uploads copied     : {0:N2} / {1:N2} GiB ({2}%)" -f ($current/1GB),($baseline/1GB),$pct)
    Write-Host ("Migration staging  : {0:N2} GiB" -f (([double]$values.MIG_BYTES / 1GB))
    Write-Host "Mongo archive      : $($values.MONGO_ARCHIVE)"
    Write-Host ("Mongo bytes        : {0:N2} GiB" -f (([double]$values.MONGO_BYTES / 1GB))
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

Write-Host 'GPI_MIGRATION_NATIVE_COMPATIBILITY=PASS' -ForegroundColor Green

if (-not $NoSelfUpdate) {
    Update-ControlFolder
}

$State = Get-State
Invoke-ConfiguredPhase -State $State
