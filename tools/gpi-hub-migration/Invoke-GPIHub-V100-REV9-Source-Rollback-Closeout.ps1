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
$SourceIp = [string]$State.source.public_ip
$TargetIp = [string]$State.target.public_ip

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v100-rev9-source-closeout\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V100-REV9-Source-Rollback-Closeout.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeText {
    param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)][string[]]$Arguments,[switch]$AllowFailure)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev9-$token.err.txt"
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
        if (-not $AllowFailure -and $result.ExitCode -ne 0) { throw "$FilePath failed ($($result.ExitCode)).`n$($result.StdOut)`n$($result.StdErr)" }
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
    param([Parameter(Mandatory)][string]$Ip,[Parameter(Mandatory)][string]$KnownHosts,[Parameter(Mandatory)][string]$ScriptText)
    $token = [guid]::NewGuid().ToString('N')
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev9-ssh-$token.err.txt"
    $oldEap = $ErrorActionPreference
    $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
    $args = @('-i',$KeyPath,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',"UserKnownHostsFile=$KnownHosts",'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=20',"azureuser@$Ip",'bash -s')
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
    Write-Section 'V100 REV9 - SOURCE ROLLBACK CLOSEOUT'
    Write-Host 'Action             : READ-ONLY CLOSEOUT; NO TARGET REBUILD / NO SOURCE CHANGE'
    Write-Host 'Target             : VERIFY STATIC SAFETY STILL IN FORCE'
    Write-Host 'Source             : VERIFY COMPOSE SERVICES + INTERNAL /api/health'
    Write-Host 'Traffic cutover    : NONE'
    Write-Host 'Production writes  : NONE'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp
    $SourceKnownHosts = Get-KnownHostsForIp -Ip $SourceIp

    $TargetProbe = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
frontend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=frontend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] && [ -n "$frontend" ] && [ -n "$mongo" ] || { echo TARGET_REQUIRED_SERVICE_MISSING >&2; exit 41; }
for expected in 'GPI_MIGRATION_STATIC_RUNTIME=true' 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true' 'EMAIL_POLLING_ENABLED=false' 'AUTO_POST_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "TARGET_SAFETY_ENV_MISSING=$expected" >&2; exit 42; }
done
[ "$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')" = 'true' ] || { echo TARGET_STATIC_NETWORK_NOT_INTERNAL >&2; exit 43; }
for c in "$backend" "$frontend" "$mongo"; do
  nets=$(docker inspect "$c" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | xargs)
  [ "$nets" = "$STATIC_NET" ] || { echo "TARGET_UNEXPECTED_NETWORK=$c|$nets" >&2; exit 44; }
done
code=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=5); print(r.status)' | tail -n 1 | xargs)
[ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null || { echo "TARGET_BACKEND_INTERNAL_HTTP=$code" >&2; exit 45; }
logs=$(docker logs "$backend" 2>&1 || true)
echo "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' || { echo TARGET_STATIC_SUPPRESSION_MARKER_MISSING >&2; exit 46; }
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo TARGET_EXTERNAL_EGRESS_PRESENT >&2
  exit 47
fi
echo "TARGET_BACKEND_INTERNAL_HTTP=/api/health|$code"
echo V100_REV9_TARGET_RUNTIME_STILL_VALID=PASS
'@
    $t = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $TargetProbe
    Write-Host $t.StdOut
    Require ($t.ExitCode -eq 0) "Target closeout verification failed.`n$($t.StdOut)`n$($t.StdErr)"
    Require ($t.StdOut -match 'V100_REV9_TARGET_RUNTIME_STILL_VALID=PASS') 'Target closeout PASS marker missing.'

    Write-Section 'VERIFY SOURCE ROLLBACK CHECKPOINT USING CONTAINER-INTERNAL HEALTH'
    $SourceProbe = @'
set -euo pipefail
PROJECT='gpi-hub'
count=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | wc -l | xargs)
echo "SOURCE_RUNNING_COUNT=$count"
[ "$count" -ge 3 ] || { echo 'Source compose project has fewer than three running services.' >&2; exit 61; }
backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
frontend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=frontend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)
[ -n "$backend" ] || { echo SOURCE_BACKEND_MISSING >&2; exit 62; }
[ -n "$frontend" ] || { echo SOURCE_FRONTEND_MISSING >&2; exit 63; }
[ -n "$mongo" ] || { echo SOURCE_MONGO_MISSING >&2; exit 64; }
echo "SOURCE_SERVICE=backend|$backend"
echo "SOURCE_SERVICE=frontend|$frontend"
echo "SOURCE_SERVICE=mongodb|$mongo"
code=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=5); print(r.status)' | tail -n 1 | xargs)
[ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null || { echo "SOURCE_BACKEND_INTERNAL_HTTP=$code" >&2; exit 65; }
echo "SOURCE_BACKEND_INTERNAL_HTTP=/api/health|$code"
echo V100_REV9_SOURCE_ROLLBACK=PASS
'@
    $s = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceProbe
    Write-Host $s.StdOut
    Require ($s.ExitCode -eq 0) "Source rollback closeout failed.`n$($s.StdOut)`n$($s.StdErr)"
    Require ($s.StdOut -match 'V100_REV9_SOURCE_ROLLBACK=PASS') 'Source rollback PASS marker missing.'

    Write-Section 'V100 FINAL RESULT'
    Write-Host 'TARGET BACKEND         : RUNNING / STATIC ISOLATED'
    Write-Host 'TARGET FRONTEND        : RUNNING / STATIC ISOLATED'
    Write-Host 'TARGET MONGO           : RUNNING / RESTORE PRESERVED'
    Write-Host 'BACKGROUND WORKERS     : SUPPRESSED'
    Write-Host 'EXTERNAL EGRESS        : BLOCKED'
    Write-Host 'SOURCE ROLLBACK        : HEALTHY / 3 SERVICES / INTERNAL API HEALTHY'
    Write-Host 'TRAFFIC CUTOVER        : NONE'
    Write-Host 'PRODUCTION             : NOT TOUCHED'
    Write-Host "DIAGNOSTICS            : $DiagDir"
    Write-Host ''
    Write-Host 'V100_TARGET_RUNTIME_RECONSTRUCTION=PASS' -ForegroundColor Green
    Write-Host 'V100_REV9_SOURCE_ROLLBACK_CLOSEOUT=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V101 REV3 TARGET PARITY PRESERVATION VALIDATION.' -ForegroundColor Cyan
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
