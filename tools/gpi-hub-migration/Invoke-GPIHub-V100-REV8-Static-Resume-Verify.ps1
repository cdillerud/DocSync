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
$ProjectName = 'gpi-hub-v100'

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v100-rev8-static-resume\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V100-REV8-Static-Resume-Verify.txt'
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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev8-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev8-ssh-$token.err.txt"
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
    Write-Section 'V100 REV8 - STATIC ISOLATED RUNTIME RESUME / VERIFY'
    Write-Host "Target VM          : $TargetIp"
    Write-Host "Source rollback    : $SourceIp"
    Write-Host "Target project     : $ProjectName"
    Write-Host 'Action             : VERIFY EXISTING REV7 STATIC RUNTIME; NO REBUILD'
    Write-Host 'Background workers : MUST REMAIN SUPPRESSED'
    Write-Host 'External egress    : MUST REMAIN BLOCKED'
    Write-Host 'Mongo restore      : PRESERVED / NOT RE-RUN'
    Write-Host 'Traffic cutover    : NONE'
    Write-Host 'Production writes  : NONE'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe unavailable.'

    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp
    $SourceKnownHosts = Get-KnownHostsForIp -Ip $SourceIp

    $Remote = @'
set -euo pipefail
PROJECT='gpi-hub-v100'
STATIC_NET='gpi-hub-v100-static-net'
MIG='/gpi-hub-data/migration'
EXPECTED_BACKEND='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_FRONTEND='sha256:c83e4895cc96670e037a4e89e8b58ff3166c98a5bf2e49ce713b71115bac0acb'
EXPECTED_MONGO='sha256:8b6d8f5bbedb25cb73517b65cf99f13aeb75ad5b157a56c479287a840bbad3ac'

get_container() {
  docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n 1
}

backend=$(get_container backend)
frontend=$(get_container frontend)
mongo=$(get_container mongodb)
[ -n "$backend" ] || { echo 'Static backend is not running.' >&2; exit 41; }
[ -n "$frontend" ] || { echo 'Static frontend is not running.' >&2; exit 42; }
[ -n "$mongo" ] || { echo 'Static Mongo is not running.' >&2; exit 43; }
echo "SERVICE_RUNNING=backend|$backend"
echo "SERVICE_RUNNING=frontend|$frontend"
echo "SERVICE_RUNNING=mongodb|$mongo"
echo V100_REV8_REQUIRED_SERVICES=PASS

[ "$(docker inspect "$backend" -f '{{.Image}}')" = "$EXPECTED_BACKEND" ] || { echo 'Backend image ID drift.' >&2; exit 44; }
[ "$(docker inspect "$frontend" -f '{{.Image}}')" = "$EXPECTED_FRONTEND" ] || { echo 'Frontend image ID drift.' >&2; exit 45; }
[ "$(docker inspect "$mongo" -f '{{.Image}}')" = "$EXPECTED_MONGO" ] || { echo 'Mongo image ID drift.' >&2; exit 46; }
echo V100_REV8_IMAGE_IDS=PASS

for expected in \
  'GPI_MIGRATION_STATIC_RUNTIME=true' \
  'SHAREPOINT_TARGET=test' \
  'BC_WRITE_ENABLED=false' \
  'BC_BLOCK_PRODUCTION_WRITES=true' \
  'EMAIL_POLLING_ENABLED=false' \
  'SALES_EMAIL_POLLING_ENABLED=false' \
  'INSIDE_SALES_PILOT_ENABLED=false' \
  'AUTO_POST_ENABLED=false' \
  'AUTO_CREATE_SALES_ORDER_ENABLED=false' \
  'PILOT_MODE_ENABLED=false'; do
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Missing static safety env: $expected" >&2; exit 47; }
  echo "STATIC_ENV_OK=$expected"
done
echo V100_REV8_STATIC_ENV=PASS

internal=$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')
[ "$internal" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 48; }
for c in "$backend" "$frontend" "$mongo"; do
  nets=$(docker inspect "$c" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | xargs)
  [ "$nets" = "$STATIC_NET" ] || { echo "Unexpected network membership for $c: $nets" >&2; exit 49; }
  echo "STATIC_NETWORK_OK=$c|$nets"
done
echo V100_REV8_INTERNAL_NETWORK=PASS

# The internal network intentionally blocks the host-published NAT path. Validate from inside the isolated runtime instead.
backend_code=$(docker exec "$backend" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/api/health",timeout=5); print(r.status)' | tail -n 1 | xargs)
[ "$backend_code" -ge 200 ] 2>/dev/null && [ "$backend_code" -lt 400 ] 2>/dev/null || { echo "BACKEND_INTERNAL_HTTP=$backend_code" >&2; exit 50; }
echo "BACKEND_INTERNAL_HTTP=/api/health|$backend_code"
echo V100_REV8_BACKEND_HEALTH=PASS

frontend_ip=$(docker inspect "$frontend" -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
[ -n "$frontend_ip" ] || { echo 'Frontend internal IP unavailable.' >&2; exit 51; }
frontend_code=$(docker exec "$backend" python -c "import urllib.request; r=urllib.request.urlopen('http://$frontend_ip:3000/',timeout=5); print(r.status)" | tail -n 1 | xargs)
[ "$frontend_code" -ge 200 ] 2>/dev/null && [ "$frontend_code" -lt 400 ] 2>/dev/null || { echo "FRONTEND_INTERNAL_HTTP=$frontend_code" >&2; exit 52; }
echo "FRONTEND_INTERNAL_HTTP=/|$frontend_code"
echo V100_REV8_FRONTEND_HEALTH=PASS

logs=$(docker logs "$backend" 2>&1 || true)
echo "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' || { echo 'Static-runtime suppression marker missing.' >&2; exit 53; }
for forbidden in \
  'Dynamic mailbox polling worker started' \
  'AP email polling worker started' \
  'Sales email polling worker started' \
  'BC Catalog Sync scheduler started' \
  'Periodic sync-readiness-to-status scheduler started' \
  'ReadyToPost Auto-Post scheduler started'; do
  if echo "$logs" | grep -Fq "$forbidden"; then
    echo "Forbidden worker/scheduler started: $forbidden" >&2
    exit 54
  fi
done
echo V100_REV8_BACKGROUND_WORKERS_SUPPRESSED=PASS

if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Backend unexpectedly has external network egress.' >&2
  exit 55
fi
echo V100_REV8_EXTERNAL_EGRESS_BLOCKED=PASS

db_names=$(docker exec "$mongo" sh -lc 'if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; else mongosh --quiet --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; fi')
echo "$db_names" | grep -Fq 'gpi_document_hub' || { echo 'Restored gpi_document_hub database missing.' >&2; exit 56; }
echo "MONGO_DATABASES=$db_names"
echo V100_REV8_MONGO_PRESERVED=PASS

cat > "$MIG/v100-static-runtime-summary.txt" <<EOF
completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
project=$PROJECT
validation_path=internal_container_network
static_runtime=true
background_workers=false
external_egress=false
sharepoint_target=test
bc_write_enabled=false
bc_block_production_writes=true
traffic_cutover=none
production_touched=false
EOF

echo V100_REV8_TARGET_STATIC_RUNTIME=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $Remote
    $evidencePath = Join-Path $DiagDir 'target-rev8-static-resume.txt'
    Set-Content -LiteralPath $evidencePath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "REV8 static runtime verification failed. See $evidencePath"

    foreach ($marker in @(
        'V100_REV8_REQUIRED_SERVICES=PASS',
        'V100_REV8_IMAGE_IDS=PASS',
        'V100_REV8_STATIC_ENV=PASS',
        'V100_REV8_INTERNAL_NETWORK=PASS',
        'V100_REV8_BACKEND_HEALTH=PASS',
        'V100_REV8_FRONTEND_HEALTH=PASS',
        'V100_REV8_BACKGROUND_WORKERS_SUPPRESSED=PASS',
        'V100_REV8_EXTERNAL_EGRESS_BLOCKED=PASS',
        'V100_REV8_MONGO_PRESERVED=PASS',
        'V100_REV8_TARGET_STATIC_RUNTIME=PASS'
    )) {
        Require ($result.StdOut -match [regex]::Escape($marker)) "Required REV8 marker missing: $marker"
    }

    Write-Section 'VERIFY SOURCE ROLLBACK CHECKPOINT'
    $SourceProbe = @'
set -euo pipefail
count=$(docker ps --filter 'label=com.docker.compose.project=gpi-hub' --format '{{.Names}}' | wc -l | xargs)
echo "SOURCE_RUNNING_COUNT=$count"
[ "$count" -ge 3 ] || exit 61
code=$(curl -sS -o /tmp/v100-rev8-source.out -w '%{http_code}' http://127.0.0.1:8005/health || true)
if [ "$code" -lt 200 ] 2>/dev/null || [ "$code" -ge 400 ] 2>/dev/null; then
  code=$(curl -sS -o /tmp/v100-rev8-source.out -w '%{http_code}' http://127.0.0.1:8005/ || true)
fi
[ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null || { echo "SOURCE_HTTP=$code" >&2; exit 62; }
echo "SOURCE_HTTP=$code"
echo V100_REV8_SOURCE_ROLLBACK=PASS
'@
    $src = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceProbe
    Write-Host $src.StdOut
    Require ($src.ExitCode -eq 0) "Source rollback verification failed.`n$($src.StdOut)`n$($src.StdErr)"
    Require ($src.StdOut -match 'V100_REV8_SOURCE_ROLLBACK=PASS') 'Source rollback PASS marker missing.'

    Write-Section 'V100 REV8 FINAL RESULT'
    Write-Host 'TARGET BACKEND         : RUNNING / STATIC ISOLATED / HEALTHY'
    Write-Host 'TARGET FRONTEND        : RUNNING / STATIC ISOLATED / HEALTHY'
    Write-Host 'TARGET MONGO           : RUNNING / RESTORE PRESERVED'
    Write-Host 'BACKGROUND WORKERS     : SUPPRESSED'
    Write-Host 'EXTERNAL EGRESS        : BLOCKED'
    Write-Host 'SOURCE                 : RUNNING / ROLLBACK HEALTHY'
    Write-Host 'TRAFFIC CUTOVER        : NONE'
    Write-Host 'PRODUCTION             : NOT TOUCHED'
    Write-Host "DIAGNOSTICS            : $DiagDir"
    Write-Host ''
    Write-Host 'V100_TARGET_RUNTIME_RECONSTRUCTION=PASS' -ForegroundColor Green
    Write-Host 'V100_REV8_STATIC_ISOLATED_RUNTIME=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V101 TARGET PARITY PRESERVATION VALIDATION.' -ForegroundColor Cyan
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
