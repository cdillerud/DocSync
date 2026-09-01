#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$BaseSourcePath = Join-Path $ToolRoot 'Invoke-GPIHub-V116-AP-Routing-Heldout-Evaluation.ps1'
$EntrySourcePath = Join-Path $ToolRoot 'Invoke-GPIHub-V117-Entry.ps1'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Replace-Required {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Marker
    )
    Require ($Text.Contains($Old)) "V117 REV2 patch anchor missing: $Marker"
    return $Text.Replace($Old,$New)
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "State missing: $StatePath"
Require (Test-Path -LiteralPath $BaseSourcePath -PathType Leaf) "Base V116 controller missing: $BaseSourcePath"
Require (Test-Path -LiteralPath $EntrySourcePath -PathType Leaf) "V117 entry missing: $EntrySourcePath"

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
$PatchRoot = Join-Path $OperationalRoot '.gpi-diagnostics\v117-rev2-detached-controller'
$PatchedBasePath = Join-Path $PatchRoot 'Invoke-GPIHub-V116-AP-Routing-Heldout-Evaluation.ps1'
$PatchedEntryPath = Join-Path $PatchRoot 'Invoke-GPIHub-V117-Entry.ps1'
$PatchedStatePath = Join-Path $PatchRoot 'state.json'

New-Item -ItemType Directory -Path $PatchRoot -Force | Out-Null

$BaseRaw = (Get-Content -LiteralPath $BaseSourcePath -Raw) -replace "`r",''
$EntryRaw = (Get-Content -LiteralPath $EntrySourcePath -Raw) -replace "`r",''

$BaseRaw = $BaseRaw.Replace(
    "        '-o','ConnectTimeout=20',",
    "        '-o','ConnectTimeout=20',`n        '-o','ServerAliveInterval=30',`n        '-o','ServerAliveCountMax=6',`n        '-o','TCPKeepAlive=yes',"
)

$BaseRaw = Replace-Required -Text $BaseRaw `
    -Old "        concurrency=2,`n        persist=False," `
    -New "        concurrency=4,`n        persist=False," `
    -Marker 'base corpus concurrency 4'

$DetachedFunction = @'
function Invoke-SshScriptDetachedPolled {
    param(
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )

    $runId = [guid]::NewGuid().ToString('N')
    $remoteScript = "/tmp/gpi-v117-$runId.sh"
    $remoteRunner = "/tmp/gpi-v117-$runId-runner.sh"
    $remoteLog = "/tmp/gpi-v117-$runId.log"
    $remoteExit = "/tmp/gpi-v117-$runId.exit"
    $remotePid = "/tmp/gpi-v117-$runId.pid"
    $normalized = $ScriptText -replace "`r",''
    $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))

    $statusPath = Join-Path $DiagDir 'V117-Detached-Remote.txt'
    @(
        "run_id=$runId",
        "script=$remoteScript",
        "runner=$remoteRunner",
        "log=$remoteLog",
        "exit=$remoteExit",
        "pid=$remotePid"
    ) | Set-Content -LiteralPath $statusPath -Encoding utf8

    $launcher = @"
set -euo pipefail
rm -f '$remoteScript' '$remoteRunner' '$remoteLog' '$remoteExit' '$remotePid'
printf '%s' '$payload' | base64 -di > '$remoteScript'
chmod 700 '$remoteScript'
cat > '$remoteRunner' <<'GPI_RUNNER'
#!/usr/bin/env bash
set +e
bash '$remoteScript' > '$remoteLog' 2>&1
rc=$?
printf '%s\n' "$rc" > '$remoteExit'
exit 0
GPI_RUNNER
chmod 700 '$remoteRunner'
nohup bash '$remoteRunner' >/dev/null 2>&1 < /dev/null &
printf '%s\n' "$!" > '$remotePid'
echo "V117_DETACHED_REMOTE_PID=$!"
echo "V117_DETACHED_REMOTE_LOG=$remoteLog"
echo "V117_DETACHED_REMOTE_EXIT_FILE=$remoteExit"
"@

    $start = Invoke-SshScript -KnownHosts $KnownHosts -ScriptText $launcher
    Require ($start.ExitCode -eq 0) "Could not start detached V117 remote evaluator: $($start.StdErr)"
    if (-not [string]::IsNullOrWhiteSpace($start.StdOut)) { Write-Host $start.StdOut }
    Write-Host 'V117_DETACHED_REMOTE_START=PASS' -ForegroundColor Green
    Write-Host "V117_DETACHED_STATUS_FILE=$statusPath"

    $seenLines = 0
    $remoteCode = $null
    $consecutivePollFailures = 0

    while ($null -eq $remoteCode) {
        $pollScript = @"
set -u
if [ -f '$remoteLog' ]; then
    cat '$remoteLog'
fi
if [ -f '$remoteExit' ]; then
    printf '__GPI_REMOTE_EXIT__=%s\n' "$(cat '$remoteExit')"
fi
"@
        $poll = Invoke-SshScript -KnownHosts $KnownHosts -ScriptText $pollScript

        if ($poll.ExitCode -ne 0) {
            $consecutivePollFailures++
            Write-Host "V117_MONITOR_SSH_RETRY=$consecutivePollFailures;exit=$($poll.ExitCode)" -ForegroundColor DarkYellow
            if ($consecutivePollFailures -ge 120) {
                throw "V117 detached evaluator may still be running, but polling failed 120 consecutive times. Recovery metadata: $statusPath"
            }
            Start-Sleep -Seconds 15
            continue
        }

        $consecutivePollFailures = 0
        $lines = @()
        if (-not [string]::IsNullOrWhiteSpace($poll.StdOut)) {
            $lines = @($poll.StdOut -split "`n")
        }

        $exitLine = $lines | Where-Object { $_ -like '__GPI_REMOTE_EXIT__=*' } | Select-Object -Last 1
        $logLines = @($lines | Where-Object { $_ -notlike '__GPI_REMOTE_EXIT__=*' })

        if ($logLines.Count -lt $seenLines) { $seenLines = 0 }
        if ($logLines.Count -gt $seenLines) {
            for ($i = $seenLines; $i -lt $logLines.Count; $i++) {
                Write-Host ([string]$logLines[$i])
            }
            $seenLines = $logLines.Count
        }

        if ($exitLine) {
            $value = ([string]$exitLine).Substring('__GPI_REMOTE_EXIT__='.Length).Trim()
            $parsed = 0
            Require ([int]::TryParse($value,[ref]$parsed)) "Invalid detached V117 exit marker: $exitLine"
            $remoteCode = $parsed
            break
        }

        Start-Sleep -Seconds 15
    }

    Write-Host "V117_DETACHED_REMOTE_EXIT=$remoteCode"
    Write-Host "V117_DETACHED_REMOTE_LOG_PRESERVED=$remoteLog"

    $cleanupScript = @"
rm -f '$remoteScript' '$remoteRunner' '$remoteExit' '$remotePid'
"@
    $null = Invoke-SshScript -KnownHosts $KnownHosts -ScriptText $cleanupScript

    return [pscustomobject]@{
        ExitCode = [int]$remoteCode
        StdOut = ''
        StdErr = ''
    }
}

'@

$BaseRaw = Replace-Required -Text $BaseRaw `
    -Old 'function Materialize-GitTextFile {' `
    -New ($DetachedFunction + 'function Materialize-GitTextFile {') `
    -Marker 'detached polling function insertion'

$OldProbeInvocation = @'
    $probe = Invoke-SshScript -KnownHosts $Known -ScriptText $Remote
    if (-not [string]::IsNullOrWhiteSpace($probe.StdOut)) { Write-Host $probe.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($probe.StdErr)) { Write-Host $probe.StdErr -ForegroundColor DarkYellow }
    Write-Host "V116_REMOTE_EXIT=$($probe.ExitCode)"
    Require ($probe.ExitCode -eq 0) "V116 held-out evaluation gate failed with exit code $($probe.ExitCode)."
'@
$NewProbeInvocation = @'
    $probe = Invoke-SshScriptDetachedPolled -KnownHosts $Known -ScriptText $Remote
    Write-Host "V116_REMOTE_EXIT=$($probe.ExitCode)"
    Require ($probe.ExitCode -eq 0) "V116 held-out evaluation gate failed with exit code $($probe.ExitCode)."
'@
$BaseRaw = Replace-Required -Text $BaseRaw -Old $OldProbeInvocation -New $NewProbeInvocation -Marker 'detached long-running remote invocation'

$EntryRaw = Replace-Required -Text $EntryRaw `
    -Old "        concurrency=2,`n        retry_count=3,`n        progress_callback=expansion_progress," `
    -New "        concurrency=4,`n        retry_count=3,`n        progress_callback=expansion_progress," `
    -Marker 'targeted expansion concurrency 4'

$SnapshotOld = @'
    examples=list(merged.values())
    merged_route_counts=Counter(str(e.get('route_path') or '') for e in examples)
'@
$SnapshotNew = @'
    examples=list(merged.values())
    snapshot_path=Path('/tmp/gpi-ap-routing-v117-evidence-snapshot.json')
    snapshot_path.write_text(
        json.dumps(
            {
                'schema_version':'1.0',
                'feature_commit':FEATURE_COMMIT,
                'authority':authority,
                'example_count':len(examples),
                'examples':examples,
            },
            sort_keys=True,
            default=str,
        ),
        encoding='utf-8',
    )
    print('V117_EVIDENCE_SNAPSHOT='+str(snapshot_path),flush=True)
    print('V117_EVIDENCE_SNAPSHOT_COUNT='+str(len(examples)),flush=True)
    merged_route_counts=Counter(str(e.get('route_path') or '') for e in examples)
'@
$EntryRaw = Replace-Required -Text $EntryRaw -Old $SnapshotOld -New $SnapshotNew -Marker 'reusable evidence snapshot'

$EntryRaw = Replace-Required -Text $EntryRaw `
    -Old "& `$GeneratedPath`nexit `$LASTEXITCODE" `
    -New "& `$GeneratedPath`nif (`$LASTEXITCODE -ne 0) { throw \"V117 generated controller returned exit code `$LASTEXITCODE.\" }" `
    -Marker 'propagate failure without closing host'

Set-Content -LiteralPath $PatchedBasePath -Value $BaseRaw -Encoding utf8 -NoNewline
Set-Content -LiteralPath $PatchedEntryPath -Value $EntryRaw -Encoding utf8 -NoNewline
Copy-Item -LiteralPath $StatePath -Destination $PatchedStatePath -Force

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($PatchedBasePath,[ref]$tokens,[ref]$errors)
Require (@($errors).Count -eq 0) ('V117 REV2 patched base parse failed: ' + ((@($errors) | ForEach-Object Message) -join '; '))
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($PatchedEntryPath,[ref]$tokens,[ref]$errors)
Require (@($errors).Count -eq 0) ('V117 REV2 patched entry parse failed: ' + ((@($errors) | ForEach-Object Message) -join '; '))

Write-Host 'V117_REV2_DETACHED_SSH_EXECUTION_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_REV2_SHORT_POLL_STREAMING_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_REV2_BASE_CONCURRENCY_4_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_REV2_EXPANSION_CONCURRENCY_4_CONFIGURED=PASS' -ForegroundColor Green
Write-Host 'V117_REV2_EVIDENCE_SNAPSHOT_CONFIGURED=PASS' -ForegroundColor Green
Write-Host "V117_REV2_PATCH_ROOT=$PatchRoot"

try {
    & $PatchedEntryPath
    if ($LASTEXITCODE -ne 0) {
        throw "V117 REV2 detached entry returned exit code $LASTEXITCODE."
    }
}
catch {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Red
    Write-Host 'V117 REV2 FAILED - WINDOW PRESERVED' -ForegroundColor Red
    Write-Host ('=' * 120) -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Patch root : $PatchRoot"
    Write-Host 'The remote detached log path is recorded in the latest V117-Detached-Remote.txt diagnostic file when remote execution started.'
    [void](Read-Host 'Press Enter to close this window')
    exit 1
}
