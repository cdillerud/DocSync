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
$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$ToolPrefix = 'tools/gpi-hub-migration/'
$ManifestRepoPath = "${ToolPrefix}control-files.txt"
$RemoteTrackingRef = "refs/remotes/origin/$ControlBranch"
$FetchRefspec = "+refs/heads/$ControlBranch`:$RemoteTrackingRef"

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $stderrFile = Join-Path $env:TEMP ("gpi-native-" + [guid]::NewGuid().ToString('N') + '.err.txt')
    $oldEap = $ErrorActionPreference
    $nativePreference = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNativePreference = if ($null -ne $nativePreference) { $nativePreference.Value } else { $null }

    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativePreference) { $PSNativeCommandUseErrorActionPreference = $false }

        $output = & $FilePath @Arguments 2> $stderrFile
        $exitCode = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        } else {
            ''
        }

        $result = [pscustomobject]@{
            ExitCode = [int]$exitCode
            StdOut = [string]$stdout
            StdErr = [string]$stderr
        }

        if (-not $AllowFailure -and $result.ExitCode -ne 0) {
            throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)"
        }

        return $result
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativePreference) { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
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
    $result = Invoke-NativeText -FilePath 'git.exe' -Arguments @('-C',$Repo,'show',$spec)
    Require ($result.ExitCode -eq 0) "Could not read $RepoPath from $Ref."
    return [string]$result.StdOut
}

function Get-State {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    return (Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50)
}

function Update-ControlFolder {
    $state = Get-State
    $sourceRepo = [string]$state.local.operational_root

    Require (Test-Path -LiteralPath $sourceRepo -PathType Container) "Operational repo missing: $sourceRepo"
    Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
    Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

    Write-Host 'Updating migration controller using explicit git show file reads...' -ForegroundColor Cyan

    $null = Invoke-NativeText -FilePath 'git.exe' -Arguments @(
        '-C',$sourceRepo,'fetch','--prune','origin',$FetchRefspec
    )

    $verify = Invoke-NativeText -FilePath 'git.exe' -Arguments @(
        '-C',$sourceRepo,'rev-parse','--verify',$RemoteTrackingRef
    )
    Require (-not [string]::IsNullOrWhiteSpace($verify.StdOut)) "Migration ref unavailable: $RemoteTrackingRef"

    $manifestText = Get-GitFileText -Repo $sourceRepo -Ref $RemoteTrackingRef -RepoPath $ManifestRepoPath
    $controlFiles = @(
        ($manifestText -replace "`r",'') -split "`n" |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )

    Require ($controlFiles.Count -gt 0) 'Migration control manifest is empty.'
    Require ($controlFiles -contains $ManifestRepoPath) 'Migration control manifest must include itself.'

    $stageRoot = Join-Path $env:TEMP ("gpi-hub-control-stage-" + [guid]::NewGuid().ToString('N'))
    $stageToolRoot = Join-Path $stageRoot 'tools\gpi-hub-migration'

    try {
        New-Item -ItemType Directory -Path $stageToolRoot -Force | Out-Null

        foreach ($repoPath in $controlFiles) {
            Require ($repoPath.StartsWith($ToolPrefix,[System.StringComparison]::Ordinal)) "Manifest path escapes control subtree: $repoPath"
            Require ($repoPath -notmatch '(^|/)\.\.(/|$)') "Manifest path contains parent traversal: $repoPath"

            $relativePath = $repoPath.Substring($ToolPrefix.Length).Replace('/','\')
            $destination = Join-Path $stageToolRoot $relativePath
            $destinationParent = Split-Path -Parent $destination
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null

            $fileText = Get-GitFileText -Repo $sourceRepo -Ref $RemoteTrackingRef -RepoPath $repoPath
            Set-Content -LiteralPath $destination -Value $fileText -Encoding utf8 -NoNewline
        }

        Require (Test-Path -LiteralPath (Join-Path $stageToolRoot 'Invoke-GPIHubMigration.ps1')) 'Staged runner missing.'
        Require (Test-Path -LiteralPath (Join-Path $stageToolRoot 'state.json')) 'Staged state missing.'

        Get-ChildItem -LiteralPath $stageToolRoot -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $ToolRoot -Recurse -Force
        }
    }
    finally {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Control ref : $($verify.StdOut.Trim())"
    Write-Host "Files       : $($controlFiles.Count)"
    Write-Host 'GPI_MIGRATION_GIT_SHOW_SELF_UPDATE=PASS' -ForegroundColor Green

    $childArgs = @(
        '-NoProfile','-ExecutionPolicy','Bypass',
        '-File',$PSCommandPath,
        '-NoSelfUpdate',
        '-WatchSeconds',"$WatchSeconds"
    )
    if ($Once) { $childArgs += '-Once' }

    & pwsh.exe @childArgs
    exit $LASTEXITCODE
}

function Get-LatestKnownHosts {
    param([Parameter(Mandatory)][string]$OperationalRoot)

    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    Require (Test-Path -LiteralPath $diagRoot -PathType Container) "Diagnostics root not found: $diagRoot"

    $candidates = @(
        Get-ChildItem -LiteralPath $diagRoot -Filter 'target-known_hosts' -File -Recurse -ErrorAction SilentlyContinue |
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

    $stderrFile = Join-Path $env:TEMP ("gpi-ssh-" + [guid]::NewGuid().ToString('N') + '.err.txt')
    $oldEap = $ErrorActionPreference
    $nativePreference = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNativePreference = if ($null -ne $nativePreference) { $nativePreference.Value } else { $null }

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
        if ($null -ne $nativePreference) { $PSNativeCommandUseErrorActionPreference = $false }

        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @sshArgs 2> $stderrFile
        $exitCode = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        } else {
            ''
        }

        return [pscustomobject]@{
            ExitCode = [int]$exitCode
            StdOut = [string]$stdout
            StdErr = [string]$stderr
        }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativePreference) { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-TargetStatus {
    param([Parameter(Mandatory)]$State)

    $operationalRoot = [string]$State.local.operational_root
    $keyPath = [string]$State.local.ssh_key
    $targetIp = [string]$State.target.public_ip
    $knownHosts = Get-LatestKnownHosts -OperationalRoot $operationalRoot

    Require (Test-Path -LiteralPath $keyPath -PathType Leaf) "SSH key not found: $keyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'

    $remoteScript = @'
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

    $probe = Invoke-SshScript -KeyPath $keyPath -KnownHosts $knownHosts -Target "azureuser@$targetIp" -ScriptText $remoteScript
    Require ($probe.ExitCode -eq 0) "Target status probe failed.`n$($probe.StdOut)`n$($probe.StdErr)"

    $values = @{}
    foreach ($line in (($probe.StdOut -replace "`r",'') -split "`n")) {
        if ($line -match '^([A-Z_]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }

    foreach ($requiredKey in @('UTC','APP_BYTES','UPLOAD_BYTES','MIG_BYTES','MONGO_BYTES','DISK_AVAIL')) {
        Require ($values.ContainsKey($requiredKey)) "Target status response is missing $requiredKey."
    }

    $baselineBytes = [double]$State.source.uploads_bytes_baseline
    $uploadBytes = [double]$values.UPLOAD_BYTES
    $appGiB = [double]$values.APP_BYTES / 1GB
    $uploadGiB = $uploadBytes / 1GB
    $baselineGiB = $baselineBytes / 1GB
    $migrationGiB = [double]$values.MIG_BYTES / 1GB
    $mongoGiB = [double]$values.MONGO_BYTES / 1GB
    $freeGiB = [double]$values.DISK_AVAIL / 1GB
    $uploadPct = if ($baselineBytes -gt 0) {
        [Math]::Min(100,[Math]::Round(($uploadBytes / $baselineBytes) * 100,1))
    } else {
        0
    }

    $processText = ''
    if ($probe.StdOut -match '(?s)PROCESS_BEGIN\s*(.*?)\s*PROCESS_END') {
        $processText = $Matches[1].Trim()
    }

    $summaryPresent = $values.ContainsKey('SUMMARY') -and -not [string]::IsNullOrWhiteSpace([string]$values.SUMMARY)

    Write-Host ''
    Write-Host ('=' * 88) -ForegroundColor Cyan
    Write-Host "GPI HUB MIGRATION — $($State.phase)" -ForegroundColor Cyan
    Write-Host ('=' * 88) -ForegroundColor Cyan
    Write-Host "UTC               : $($values.UTC)"
    Write-Host ("App copied         : {0:N2} GiB" -f $appGiB)
    Write-Host ("Uploads copied     : {0:N2} / {1:N2} GiB ({2}%)" -f $uploadGiB,$baselineGiB,$uploadPct)
    Write-Host ("Migration staging  : {0:N2} GiB" -f $migrationGiB)
    Write-Host "Mongo archive      : $($values.MONGO_ARCHIVE)"
    Write-Host ("Mongo bytes        : {0:N2} GiB" -f $mongoGiB)
    Write-Host ("Target disk free   : {0:N1} GiB" -f $freeGiB)
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
            $relativeScript = [string]$State.script
            Require (-not [string]::IsNullOrWhiteSpace($relativeScript)) 'state.json run-script mode has no script path.'
            $phaseScript = Join-Path $ToolRoot $relativeScript
            Require (Test-Path -LiteralPath $phaseScript -PathType Leaf) "Phase script missing: $phaseScript"
            Write-Host "Running repo-controlled phase: $($State.phase)" -ForegroundColor Cyan
            & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $phaseScript
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

Write-Host 'GPI_MIGRATION_RUNNER_PARSE_FIX=PASS' -ForegroundColor Green

if (-not $NoSelfUpdate) {
    Update-ControlFolder
}

$state = Get-State
Invoke-ConfiguredPhase -State $state
