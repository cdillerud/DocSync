#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50

$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$TargetIp = [string]$State.target.public_ip
$ProjectName = 'gpi-hub-v100'
$TargetApp = '/gpi-hub-data/apps/gpi-hub'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v100-rev6-safe-quiesce\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V100-REV6-Safe-Quiesce.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev6-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = & $FilePath @Arguments 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $result = [pscustomobject]@{ ExitCode=[int]$code; StdOut=[string]$stdout; StdErr=[string]$stderr }
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

function Get-KnownHostsForIp {
    param([Parameter(Mandatory)][string]$Ip)
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    $files = @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    foreach ($file in $files) {
        $probe = Invoke-NativeText -FilePath 'ssh-keygen.exe' -Arguments @('-F',$Ip,'-f',$file.FullName) -AllowFailure
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file was found for $Ip."
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory)][string]$Ip,
        [Parameter(Mandatory)][string]$KnownHosts,
        [Parameter(Mandatory)][string]$ScriptText
    )
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev6-ssh-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $args = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "azureuser@$Ip",
        'bash -s'
    )
    try {
        $ErrorActionPreference = 'Continue'
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @args 2> $stderrFile
        $code = $LASTEXITCODE
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode=[int]$code; StdOut=[string]$stdout; StdErr=[string]$stderr }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Write-Section 'V100 REV6 - SAFE QUIESCE + AUTHORITATIVE STARTUP-CONTROL DISCOVERY'
    Write-Host "Target VM          : $TargetIp"
    Write-Host "Target project     : $ProjectName"
    Write-Host 'Action             : STOP TARGET BACKEND/FRONTEND ONLY'
    Write-Host 'Mongo              : LEFT RUNNING / RESTORE PRESERVED'
    Write-Host 'Source             : NOT TOUCHED'
    Write-Host 'Traffic cutover    : NONE'
    Write-Host 'Production writes  : NONE'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe unavailable.'

    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp

    $Remote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
APP='/gpi-hub-data/apps/gpi-hub'

stop_service() {
  svc="$1"
  ids=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc")
  if [ -n "$ids" ]; then
    docker stop $ids >/dev/null
    echo "TARGET_SERVICE_STOPPED=$svc"
  else
    echo "TARGET_SERVICE_ALREADY_STOPPED=$svc"
  fi
}

stop_service backend
stop_service frontend

for svc in backend frontend; do
  if docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" | grep -q .; then
    echo "QUIESCE_FAILED=$svc" >&2
    exit 41
  fi
done

echo V100_REV6_TARGET_APP_QUIESCED=PASS

mongo=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb')
[ -n "$mongo" ] || { echo 'Target Mongo is not running after quiesce.' >&2; exit 42; }
echo V100_REV6_MONGO_PRESERVED=PASS

[ -d "$APP/backend" ] || { echo "Backend source tree missing: $APP/backend" >&2; exit 43; }

echo '--- AUTHORITATIVE STARTUP CONTROL EVIDENCE ---'
# Read source only. Never inspect .env values or print secrets.
find "$APP/backend" -type f -name '*.py' -print0 | xargs -0 grep -nH -E \
  'AP email polling worker started|Dynamic mailbox polling worker started|Email polling worker started|scheduler started|polling worker|POLL[A-Z0-9_]*ENABLED|EMAIL[A-Z0-9_]*ENABLED|MAIL[A-Z0-9_]*ENABLED|SCHEDUL[A-Z0-9_]*ENABLED|AUTO[A-Z0-9_]*ENABLED|os\.getenv\(|os\.environ\.get\(' \
  2>/dev/null | head -n 700 || true

echo '--- EXACT AP/DYNAMIC POLLING CONTEXT ---'
find "$APP/backend" -type f -name '*.py' -print0 | xargs -0 grep -nH -B 12 -A 18 -E \
  'AP email polling worker started|Dynamic mailbox polling worker started|Starting dynamic mailbox polling worker|Starting passive tap' \
  2>/dev/null | head -n 500 || true

echo '--- BACKEND CURRENT SAFETY ENV NAMES ONLY ---'
backend_stopped=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' | head -n 1)
if [ -n "$backend_stopped" ]; then
  docker inspect "$backend_stopped" -f '{{range .Config.Env}}{{println .}}{{end}}' | sed 's/=.*$/=REDACTED/' | sort | grep -E 'POLL|MAIL|EMAIL|SCHED|WORKER|SYNC|BC_|SHAREPOINT|INSIDE_SALES' || true
fi

echo V100_REV6_STARTUP_CONTROL_DISCOVERY=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $Remote
    $evidencePath = Join-Path $DiagDir 'target-startup-control-evidence.txt'
    Set-Content -LiteralPath $evidencePath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }

    Require ($result.ExitCode -eq 0) "REV6 target quiesce/discovery failed. See $evidencePath"
    Require ($result.StdOut -match 'V100_REV6_TARGET_APP_QUIESCED=PASS') 'Target app quiesce PASS marker missing.'
    Require ($result.StdOut -match 'V100_REV6_MONGO_PRESERVED=PASS') 'Mongo-preserved PASS marker missing.'
    Require ($result.StdOut -match 'V100_REV6_STARTUP_CONTROL_DISCOVERY=PASS') 'Startup-control discovery PASS marker missing.'

    Write-Section 'V100 REV6 RESULT'
    Write-Host 'TARGET BACKEND        : STOPPED'
    Write-Host 'TARGET FRONTEND       : STOPPED'
    Write-Host 'TARGET MONGO          : RUNNING / RESTORE PRESERVED'
    Write-Host 'SOURCE                : RUNNING / UNCHANGED'
    Write-Host 'TRAFFIC CUTOVER       : NONE'
    Write-Host 'PRODUCTION WRITES     : NONE'
    Write-Host "EVIDENCE              : $evidencePath"
    Write-Host ''
    Write-Host 'V100_REV6_SAFE_QUIESCE=PASS' -ForegroundColor Green
    Write-Host 'NEXT: PATCH EXACT BACKGROUND-WORKER CONTROLS + READINESS WAIT, THEN RESUME V100.' -ForegroundColor Cyan
    Write-Host ''
    [void](Read-Host 'Copy the visible startup-control evidence to ChatGPT, then press Enter to close this window')
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
