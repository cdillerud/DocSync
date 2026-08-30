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
$ToolPrefix = 'tools/gpi-hub-migration/'
$ManifestRepoPath = "${ToolPrefix}control-files.txt"
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"

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

function Get-State {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    return (Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50)
}

function Update-ControlFolder {
    $CurrentState = Get-State
    $SourceRepo = [string]$CurrentState.local.operational_root

    Require (Test-Path -LiteralPath $SourceRepo -PathType Container) "Operational repo missing: $SourceRepo"
    Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
    Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

    $StageRoot = Join-Path $env:TEMP ("gpi-hub-control-stage-" + [guid]::NewGuid().ToString('N'))
    $StageToolRoot = Join-Path $StageRoot 'tools\gpi-hub-migration'

    Write-Host 'Updating migration controller using explicit git show file reads...' -ForegroundColor Cyan

    try {
        $null = Invoke-NativeText -FilePath 'git.exe' -Arguments @(
            '-C',$SourceRepo,'fetch','--prune','origin',$FetchRefspec
        )

        $verify = Invoke-NativeText -FilePath 'git.exe' -Arguments @(
            '-C',$SourceRepo,'rev-parse','--verify',$RemoteTrackingRef
        )
        Require (-not [string]::IsNullOrWhiteSpace($verify.StdOut)) `
            "Migration remote-tracking ref unavailable: $RemoteTrackingRef"

        $manifestText = Get-GitFileText -Repo $SourceRepo -Ref $RemoteTrackingRef -RepoPath $ManifestRepoPath
        $controlFiles = @(
            ($manifestText -replace "`r",'') -split "`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        Require ($controlFiles.Count -gt 0) 'Migration control manifest is empty.'
        Require ($controlFiles -contains $ManifestRepoPath) 'Migration control manifest must include itself.'

        New-Item -ItemType Directory -Path $StageToolRoot -Force | Out-Null

        foreach ($repoPath in $controlFiles) {
            Require ($repoPath.StartsWith($ToolPrefix,[System.StringComparison]::Ordinal)) "Manifest path escapes control subtree: $repoPath"
            Require ($repoPath -notmatch '(^|/)\.\.(/|$)') "Manifest path contains parent traversal: $repoPath"

            $relative = $repoPath.Substring($ToolPrefix.Length).Replace('/','\')
            $destination = Join-Path $StageToolRoot $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null

            $content = Get-GitFileText -Repo $SourceRepo -Ref $RemoteTrackingRef -RepoPath $repoPath
            Set-Content -LiteralPath $destination -Value $content -Encoding utf8 -NoNewline
        }

        Require (Test-Path -LiteralPath (Join-Path $StageToolRoot 'Invoke-GPIHubMigration.ps1') -PathType Leaf) 'Staged runner missing.'
        Require (Test-Path -LiteralPath (Join-Path $StageToolRoot 'state.json') -PathType Leaf) 'Staged state missing.'

        Get-ChildItem -LiteralPath $StageToolRoot -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $ToolRoot -Recurse -Force
        }

        Write-Host "Control ref : $($verify.StdOut.Trim())"
        Write-Host "Files       : $($controlFiles.Count)"
        Write-Host 'GPI_MIGRATION_GIT_SHOW_SELF_UPDATE=PASS' -ForegroundColor Green
    }
    finally {
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
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }

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
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }

        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @sshArgs 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
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
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-TargetStatus {
    param([Parameter(Mandatory)]$State)

    $OperationalRoot = [string]$State.local.operational_root
    $KeyPath = [string]$State.local.ssh_key
    $TargetIp = [string]$State.target.public_ip
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
else
  echo 'SUMMARY='
fi

df -B1 --output=size,used,avail,pcent /gpi-hub-data | tail -n 1 | awk '{print "DISK_SIZE=" $1 "\nDISK_USED=" $2 "\nDISK_AVAIL=" $3 "\nDISK_PCT=" $4}'
'@

    $probe = Invoke-SshScript `
        -KeyPath $KeyPath `
        -KnownHosts $KnownHosts `
        -Target "azureuser@$TargetIp" `
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
    } else {
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
            exit $LASTEXITCODE
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

Write-Host 'GPI_MIGRATION_GIT_SHOW_TRANSPORT=PASS' -ForegroundColor Green

if (-not $NoSelfUpdate) {
    Update-ControlFolder
}

$State = Get-State
Invoke-ConfiguredPhase -State $State
