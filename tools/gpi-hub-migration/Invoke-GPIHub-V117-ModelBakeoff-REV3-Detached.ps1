#requires -Version 7.0
[CmdletBinding()]
param(
    [int]$PilotSize = 24,
    [int]$ValidationSize = 100,
    [int]$ConcurrencyPerModel = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$BaseControllerCommit = 'd3f5fba30e711b876b713990ac9b15c51828943d'
$BaseControllerRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-ModelBakeoff-REV2.ps1'
$ExpectedBaseControllerBlob = '29b2105cd5eb461320c798879af3a722e97ac040'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-GitText {
    param([string]$Repo,[string]$Ref,[string]$RepoPath)
    $spec = "{0}:{1}" -f $Ref,$RepoPath
    $lines = & git.exe -C $Repo show $spec
    $code = $LASTEXITCODE
    Require ($code -eq 0) "Could not read $RepoPath from $Ref."
    return ((@($lines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Bakeoff REV3 state missing: $StatePath"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "Operational repo missing: $OperationalRoot"

$baseSpec = "{0}:{1}" -f $BaseControllerCommit,$BaseControllerRepoPath
$baseBlob = (& git.exe -C $OperationalRoot rev-parse $baseSpec).Trim()
Require ($LASTEXITCODE -eq 0) 'Could not resolve bakeoff REV2 controller blob.'
Require ($baseBlob -ceq $ExpectedBaseControllerBlob) "Bakeoff REV2 controller blob drift: $baseBlob"

$Raw = Get-GitText -Repo $OperationalRoot -Ref $BaseControllerCommit -RepoPath $BaseControllerRepoPath

$InvokeOld = @'
& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

$InvokeNew = @'
$GeneratedRaw = Get-Content -LiteralPath $GeneratedController -Raw

$AttachedOld = @'
    $probe = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText $Remote
    if (-not [string]::IsNullOrWhiteSpace($probe.StdOut)) { Write-Host $probe.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($probe.StdErr)) { Write-Host $probe.StdErr -ForegroundColor DarkYellow }
    Write-Host "V117_BAKEOFF_REMOTE_EXIT=$($probe.ExitCode)"
'@

$DetachedNew = @'
    $DetachedToken = [guid]::NewGuid().ToString('N')
    $RemoteRunPath = "/tmp/gpi-v117-model-bakeoff-$DetachedToken.sh"
    $RemoteLogPath = "/tmp/gpi-v117-model-bakeoff-$DetachedToken.log"
    $RemoteExitPath = "/tmp/gpi-v117-model-bakeoff-$DetachedToken.exit"
    $RemotePidPath = "/tmp/gpi-v117-model-bakeoff-$DetachedToken.pid"

    $orphanCheck = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText @'
set -euo pipefail
matches="$(ps -eo pid=,args= | grep '[g]pi-v117-model-bakeoff-probe.py' || true)"
if [ -n "$matches" ]; then
  echo V117_BAKEOFF_EXISTING_REMOTE_PROCESS=YES
  printf '%s\n' "$matches"
  exit 98
fi
echo V117_BAKEOFF_EXISTING_REMOTE_PROCESS=NO
'@
    if (-not [string]::IsNullOrWhiteSpace($orphanCheck.StdOut)) { Write-Host $orphanCheck.StdOut }
    Require ($orphanCheck.ExitCode -eq 0) 'A prior V117 bakeoff process is still active; refusing to overlap runs.'

    $RemotePayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Remote -replace "`r",'')))
    $LaunchText = @'
set -euo pipefail
RUN='__RUN__'
LOG='__LOG__'
EXITF='__EXIT__'
PIDF='__PID__'
printf '%s' '__PAYLOAD__' | base64 -d > "$RUN"
chmod 700 "$RUN"
rm -f "$LOG" "$EXITF" "$PIDF"
nohup bash -c 'bash "$1" > "$2" 2>&1; rc=$?; printf "%s\n" "$rc" > "$3"' _ "$RUN" "$LOG" "$EXITF" >/dev/null 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$PIDF"
echo "V117_BAKEOFF_DETACHED_REMOTE_PID=$pid"
echo "V117_BAKEOFF_DETACHED_REMOTE_LOG=$LOG"
echo "V117_BAKEOFF_DETACHED_REMOTE_EXIT_FILE=$EXITF"
'@
    $LaunchText = $LaunchText.Replace('__RUN__',$RemoteRunPath).Replace('__LOG__',$RemoteLogPath).Replace('__EXIT__',$RemoteExitPath).Replace('__PID__',$RemotePidPath).Replace('__PAYLOAD__',$RemotePayload)
    $launch = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText $LaunchText
    if (-not [string]::IsNullOrWhiteSpace($launch.StdOut)) { Write-Host $launch.StdOut }
    if (-not [string]::IsNullOrWhiteSpace($launch.StdErr)) { Write-Host $launch.StdErr -ForegroundColor DarkYellow }
    Require ($launch.ExitCode -eq 0) 'Could not start detached V117 bakeoff process.'
    Write-Host 'V117_BAKEOFF_DETACHED_REMOTE_START=PASS' -ForegroundColor Green

    $RemoteExit = $null
    $LastPollText = ''
    $ConsecutivePollFailures = 0
    $MaxPolls = 2880
    for ($pollIndex = 1; $pollIndex -le $MaxPolls; $pollIndex++) {
        $PollText = @'
set -euo pipefail
LOG='__LOG__'
EXITF='__EXIT__'
PIDF='__PID__'
if [ -f "$EXITF" ]; then
  echo V117_BAKEOFF_DETACHED_STATUS=EXIT
  printf 'V117_BAKEOFF_DETACHED_EXIT_CODE='
  cat "$EXITF"
elif [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  echo V117_BAKEOFF_DETACHED_STATUS=RUNNING
else
  echo V117_BAKEOFF_DETACHED_STATUS=LOST
fi
echo V117_BAKEOFF_DETACHED_LOG_TAIL_BEGIN
if [ -f "$LOG" ]; then tail -n 12 "$LOG"; fi
echo V117_BAKEOFF_DETACHED_LOG_TAIL_END
'@
        $PollText = $PollText.Replace('__LOG__',$RemoteLogPath).Replace('__EXIT__',$RemoteExitPath).Replace('__PID__',$RemotePidPath)
        $poll = Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText $PollText
        if ($poll.ExitCode -ne 0) {
            $ConsecutivePollFailures++
            Write-Host "V117_BAKEOFF_DETACHED_POLL_TRANSPORT_FAILURE=$ConsecutivePollFailures;ssh_exit=$($poll.ExitCode)" -ForegroundColor Yellow
            if ($ConsecutivePollFailures -ge 6) {
                throw 'Detached bakeoff polling failed six consecutive times; remote process state is intentionally left untouched.'
            }
            Start-Sleep -Seconds 20
            continue
        }
        $ConsecutivePollFailures = 0
        $pollTextOut = [string]$poll.StdOut
        if ($pollTextOut -ne $LastPollText) {
            Write-Host $pollTextOut
            $LastPollText = $pollTextOut
        }
        if ($pollTextOut -match 'V117_BAKEOFF_DETACHED_STATUS=EXIT') {
            if ($pollTextOut -match 'V117_BAKEOFF_DETACHED_EXIT_CODE=([0-9]+)') {
                $RemoteExit = [int]$Matches[1]
            } else {
                throw 'Detached bakeoff exit file existed but exit code could not be parsed.'
            }
            break
        }
        if ($pollTextOut -match 'V117_BAKEOFF_DETACHED_STATUS=LOST') {
            $RemoteExit = 255
            Write-Host 'V117_BAKEOFF_DETACHED_PROCESS_LOST=YES' -ForegroundColor Red
            break
        }
        Start-Sleep -Seconds 20
    }
    if ($null -eq $RemoteExit) {
        throw 'Detached bakeoff exceeded the 16-hour polling envelope; remote process state is intentionally left untouched.'
    }

    $RemoteLogLocal = Join-Path $DiagDir 'gpi-v117-model-bakeoff-detached-remote.log'
    $getLog = Invoke-NativeText -FilePath 'scp.exe' -Arguments @(
        '-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$Known",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',
        "azureuser@$SourceIp`:$RemoteLogPath",$RemoteLogLocal
    ) -AllowFailure
    if ($getLog.ExitCode -eq 0 -and (Test-Path -LiteralPath $RemoteLogLocal -PathType Leaf)) {
        Write-Host "V117_BAKEOFF_DETACHED_REMOTE_LOG_LOCAL=$RemoteLogLocal" -ForegroundColor Green
    }

    $CleanupDetached = @'
set -euo pipefail
rm -f '__RUN__' '__LOG__' '__EXIT__' '__PID__'
'@
    $CleanupDetached = $CleanupDetached.Replace('__RUN__',$RemoteRunPath).Replace('__LOG__',$RemoteLogPath).Replace('__EXIT__',$RemoteExitPath).Replace('__PID__',$RemotePidPath)
    [void](Invoke-SshScript -KnownHosts $Known -KeyPath $KeyPath -SourceIp $SourceIp -ScriptText $CleanupDetached)

    $probe = [pscustomobject]@{ ExitCode=[int]$RemoteExit; StdOut=''; StdErr='' }
    Write-Host "V117_BAKEOFF_REMOTE_EXIT=$($probe.ExitCode)"
'@

Require ($GeneratedRaw.Contains($AttachedOld)) 'Bakeoff REV3 attached-SSH execution anchor missing.'
$GeneratedRaw = $GeneratedRaw.Replace($AttachedOld,$DetachedNew)
Set-Content -LiteralPath $GeneratedController -Value $GeneratedRaw -Encoding utf8 -NoNewline

$tokens2 = $null
$errors2 = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedController,[ref]$tokens2,[ref]$errors2)
if (@($errors2).Count -gt 0) {
    $text2 = (@($errors2) | ForEach-Object { $_.Message }) -join '; '
    throw "Bakeoff REV3 detached generated controller parse failed: $text2"
}

Write-Host 'V117_BAKEOFF_REV3_DETACHED_SSH_EXECUTION=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_SHORT_POLL_STREAMING=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_ORPHAN_PROCESS_GUARD=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_REMOTE_LOG_CAPTURE=PASS' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_FEATURE_LOGIC=REV2_UNCHANGED' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_FROZEN_HOLDOUT_EVALUATION=NONE' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedController `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
'@

Require ($Raw.Contains($InvokeOld)) 'Bakeoff REV3 REV2-invocation anchor missing.'
$Raw = $Raw.Replace($InvokeOld,$InvokeNew)

$GeneratedWrapper = Join-Path $ToolRoot 'Invoke-GPIHub-V117-ModelBakeoff-REV3-Generated.ps1'
Set-Content -LiteralPath $GeneratedWrapper -Value $Raw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedWrapper,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "Bakeoff REV3 generated wrapper parse failed: $text"
}

Write-Host 'V117_BAKEOFF_REV3_CONTROLLER_PATCH=PASS' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV3_BASE_CONTROLLER=$BaseControllerCommit"
Write-Host "V117_BAKEOFF_REV3_BASE_CONTROLLER_BLOB=$ExpectedBaseControllerBlob"
Write-Host 'V117_BAKEOFF_REV3_EXECUTION_MODE=DETACHED_REMOTE_WITH_SHORT_POLLING' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_PROVIDER_AND_SELECTION_LOGIC=REV2_PRESERVED' -ForegroundColor Green
Write-Host 'V117_BAKEOFF_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_BAKEOFF_REV3_GENERATED_WRAPPER=$GeneratedWrapper"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedWrapper `
    -PilotSize $PilotSize `
    -ValidationSize $ValidationSize `
    -ConcurrencyPerModel $ConcurrencyPerModel
exit $LASTEXITCODE
