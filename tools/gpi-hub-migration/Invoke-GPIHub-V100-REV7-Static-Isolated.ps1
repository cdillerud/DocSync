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
$BackendHostPort = 18005
$FrontendHostPort = 18080

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v100-rev7-static-isolated\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V100-REV7-Static-Isolated.txt'
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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev7-$token.err.txt"
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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-rev7-ssh-$token.err.txt"
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
    Write-Section 'V100 REV7 - STATIC ISOLATED TARGET RUNTIME'
    Write-Host "Target VM          : $TargetIp"
    Write-Host "Source rollback    : $SourceIp"
    Write-Host "Target project     : $ProjectName"
    Write-Host 'Background workers : SUPPRESSED BY TARGET-ONLY SERVER OVERLAY'
    Write-Host 'Container egress   : BLOCKED BY INTERNAL-ONLY DOCKER NETWORK'
    Write-Host 'Mongo restore      : PRESERVED'
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
APP='/gpi-hub-data/apps/gpi-hub'
MIG='/gpi-hub-data/migration'
BASE="$APP/docker-compose.yml"
V100_OVERRIDE="$MIG/v100-target-override.yml"
STATIC_OVERRIDE="$MIG/v100-static-isolation.yml"
OVERLAY_DIR="$MIG/v100-static-overlay"
STATIC_NET='gpi-hub-v100-static-net'
BACKEND_PORT=18005
FRONTEND_PORT=18080

EXPECTED_BACKEND='sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'
EXPECTED_FRONTEND='sha256:c83e4895cc96670e037a4e89e8b58ff3166c98a5bf2e49ce713b71115bac0acb'
EXPECTED_MONGO='sha256:8b6d8f5bbedb25cb73517b65cf99f13aeb75ad5b157a56c479287a840bbad3ac'

[ -f "$BASE" ] || { echo "Base compose file missing: $BASE" >&2; exit 41; }
[ -f "$V100_OVERRIDE" ] || { echo "V100 target override missing: $V100_OVERRIDE" >&2; exit 42; }

# Safety first: target app must be stopped while overlay is prepared.
for svc in backend frontend; do
  ids=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc")
  if [ -n "$ids" ]; then docker stop $ids >/dev/null; fi
done
for svc in backend frontend; do
  docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" | grep -q . && { echo "Target $svc still running before REV7 patch." >&2; exit 43; }
done
echo V100_REV7_PRESTART_QUIESCE=PASS

# Exact images must still be present; never rebuild or substitute them.
[ "$(docker image inspect gpi-hub-backend -f '{{.Id}}')" = "$EXPECTED_BACKEND" ] || { echo 'Backend image ID drift.' >&2; exit 44; }
[ "$(docker image inspect gpi-hub-frontend -f '{{.Id}}')" = "$EXPECTED_FRONTEND" ] || { echo 'Frontend image ID drift.' >&2; exit 45; }
[ "$(docker image inspect mongo:6.0 -f '{{.Id}}')" = "$EXPECTED_MONGO" ] || { echo 'Mongo image ID drift.' >&2; exit 46; }
echo V100_REV7_IMAGE_IDS=PASS

mkdir -p "$OVERLAY_DIR"
rm -f "$OVERLAY_DIR/server.py.image" "$OVERLAY_DIR/server.py"
probe="gpi-v100-rev7-probe-$$"
docker rm -f "$probe" >/dev/null 2>&1 || true
docker create --name "$probe" gpi-hub-backend >/dev/null
cleanup_probe() { docker rm -f "$probe" >/dev/null 2>&1 || true; }
trap cleanup_probe EXIT

server_path=''
for candidate in /app/backend/server.py /app/server.py; do
  if docker cp "$probe:$candidate" "$OVERLAY_DIR/server.py.image" >/dev/null 2>&1; then
    server_path="$candidate"
    break
  fi
done
[ -n "$server_path" ] || { echo 'Could not extract server.py from exact backend image.' >&2; exit 47; }

echo "BACKEND_SERVER_PATH=$server_path"
image_sha=$(sha256sum "$OVERLAY_DIR/server.py.image" | cut -d' ' -f1)
echo "BACKEND_SERVER_IMAGE_SHA256=$image_sha"

python3 - "$OVERLAY_DIR/server.py.image" "$OVERLAY_DIR/server.py" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding='utf-8')
anchor = '# Start dynamic mailbox polling worker (polls mailboxes configured via UI)'
count = text.count(anchor)
if count != 1:
    raise SystemExit(f'Expected exactly one static-runtime patch anchor; found {count}')
line = next(x for x in text.splitlines() if anchor in x)
indent = line[:len(line)-len(line.lstrip())]
block = (
    f'{indent}if os.environ.get("GPI_MIGRATION_STATIC_RUNTIME", "false").lower() == "true":\n'
    f'{indent}    logger.warning("GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed")\n'
    f'{indent}    return\n\n'
)
patched = text.replace(line + '\n', block + line + '\n', 1)
dst.write_text(patched, encoding='utf-8')
PY

python3 -m py_compile "$OVERLAY_DIR/server.py"
patched_sha=$(sha256sum "$OVERLAY_DIR/server.py" | cut -d' ' -f1)
[ "$patched_sha" != "$image_sha" ] || { echo 'Static server overlay did not change.' >&2; exit 48; }
grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' "$OVERLAY_DIR/server.py"
echo "BACKEND_SERVER_OVERLAY_SHA256=$patched_sha"
echo V100_REV7_SERVER_OVERLAY=PASS

cat > "$STATIC_OVERRIDE" <<YAML
services:
  backend:
    environment:
      GPI_MIGRATION_STATIC_RUNTIME: "true"
      SHAREPOINT_TARGET: "test"
      BC_WRITE_ENABLED: "false"
      BC_BLOCK_PRODUCTION_WRITES: "true"
      EMAIL_POLLING_ENABLED: "false"
      SALES_EMAIL_POLLING_ENABLED: "false"
      INSIDE_SALES_PILOT_ENABLED: "false"
      AUTO_POST_ENABLED: "false"
      AUTO_CREATE_SALES_ORDER_ENABLED: "false"
      PILOT_MODE_ENABLED: "false"
      BC_CACHE_ALERT_EMAIL_ENABLED: "false"
      DRIFT_WATCHLIST_ENABLED: "false"
    volumes:
      - type: bind
        source: $OVERLAY_DIR/server.py
        target: $server_path
        read_only: true
    networks: !override
      - gpi_static
  frontend:
    networks: !override
      - gpi_static
  mongodb:
    networks: !override
      - gpi_static
networks:
  gpi_static:
    name: $STATIC_NET
    internal: true
YAML

COMPOSE=(docker compose -p "$PROJECT" -f "$BASE" -f "$V100_OVERRIDE" -f "$STATIC_OVERRIDE")
"${COMPOSE[@]}" config --quiet
echo V100_REV7_COMPOSE_CONFIG=PASS

# Recreate only the isolated target stack. Mongo data remains on dedicated bind mounts.
"${COMPOSE[@]}" up -d --no-build mongodb backend frontend

echo '--- WAIT FOR REQUIRED SERVICES ---'
for i in $(seq 1 90); do
  ok=1
  for svc in mongodb backend frontend; do
    cid=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" | head -n 1)
    [ -n "$cid" ] || ok=0
  done
  [ "$ok" = 1 ] && break
  sleep 2
done
for svc in mongodb backend frontend; do
  cid=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" | head -n 1)
  [ -n "$cid" ] || { echo "Required service not running: $svc" >&2; "${COMPOSE[@]}" ps >&2; exit 49; }
  echo "SERVICE_RUNNING=$svc|$cid"
done

backend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
frontend=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=frontend' --format '{{.Names}}' | head -n 1)
mongo=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=mongodb' --format '{{.Names}}' | head -n 1)

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
  docker inspect "$backend" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected" || { echo "Missing isolated safety env: $expected" >&2; exit 50; }
  echo "STATIC_ENV_OK=$expected"
done
echo V100_REV7_STATIC_ENV=PASS

# Every target container must be attached only to the internal migration network.
internal=$(docker network inspect "$STATIC_NET" -f '{{.Internal}}')
[ "$internal" = 'true' ] || { echo 'Static network is not internal.' >&2; exit 51; }
for c in "$backend" "$frontend" "$mongo"; do
  nets=$(docker inspect "$c" -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | xargs)
  [ "$nets" = "$STATIC_NET" ] || { echo "Unexpected network membership for $c: $nets" >&2; exit 52; }
  echo "STATIC_NETWORK_OK=$c|$nets"
done
echo V100_REV7_INTERNAL_NETWORK=PASS

# Wait for application readiness instead of probing immediately after container start.
backend_ok=0
backend_path=''
backend_code=''
for i in $(seq 1 120); do
  for path in /health /api/health /docs /; do
    code=$(curl -sS -o /tmp/v100-rev7-backend.out -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT$path" || true)
    if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null; then
      backend_ok=1
      backend_path="$path"
      backend_code="$code"
      break 2
    fi
  done
  sleep 2
done
if [ "$backend_ok" != 1 ]; then
  echo 'Static isolated backend did not become HTTP-ready.' >&2
  docker logs --tail 180 "$backend" >&2 || true
  exit 53
fi
echo "BACKEND_HTTP=$backend_path|$backend_code"
echo V100_REV7_BACKEND_HEALTH=PASS

frontend_ok=0
frontend_code=''
for i in $(seq 1 90); do
  code=$(curl -sS -o /tmp/v100-rev7-frontend.out -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" || true)
  if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null; then
    frontend_ok=1
    frontend_code="$code"
    break
  fi
  sleep 2
done
[ "$frontend_ok" = 1 ] || { echo 'Static isolated frontend did not become HTTP-ready.' >&2; docker logs --tail 120 "$frontend" >&2 || true; exit 54; }
echo "FRONTEND_HTTP=/|$frontend_code"
echo V100_REV7_FRONTEND_HEALTH=PASS

logs=$(docker logs "$backend" 2>&1 || true)
echo "$logs" | grep -Fq 'GPI_MIGRATION_STATIC_RUNTIME=ACTIVE - background workers and schedulers suppressed' || { echo 'Static-runtime startup marker missing.' >&2; exit 55; }
for forbidden in \
  'Dynamic mailbox polling worker started' \
  'AP email polling worker started' \
  'Sales email polling worker started' \
  'BC Catalog Sync scheduler started' \
  'Periodic sync-readiness-to-status scheduler started' \
  'ReadyToPost Auto-Post scheduler started'; do
  if echo "$logs" | grep -Fq "$forbidden"; then
    echo "Forbidden background worker/scheduler started: $forbidden" >&2
    exit 56
  fi
done
echo V100_REV7_BACKGROUND_WORKERS_SUPPRESSED=PASS

# Defense in depth: even a mistakenly-started task must not have external egress.
if docker exec "$backend" python -c 'import socket; s=socket.create_connection(("graph.microsoft.com",443),3); s.close()' >/dev/null 2>&1; then
  echo 'Backend unexpectedly has external network egress.' >&2
  exit 57
fi
echo V100_REV7_EXTERNAL_EGRESS_BLOCKED=PASS

# Confirm restored Mongo remains populated.
db_names=$(docker exec "$mongo" sh -lc 'if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; else mongosh --quiet --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; fi')
echo "MONGO_DATABASES=$db_names"
echo "$db_names" | grep -Fq 'gpi_document_hub' || { echo 'Restored gpi_document_hub database missing.' >&2; exit 58; }
echo V100_REV7_MONGO_PRESERVED=PASS

cat > "$MIG/v100-static-runtime-summary.txt" <<EOF
completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
project=$PROJECT
backend=http://127.0.0.1:$BACKEND_PORT
frontend=http://127.0.0.1:$FRONTEND_PORT
static_runtime=true
background_workers=false
external_egress=false
sharepoint_target=test
bc_write_enabled=false
bc_block_production_writes=true
traffic_cutover=none
production_touched=false
server_image_sha256=$image_sha
server_overlay_sha256=$patched_sha
EOF

echo V100_REV7_TARGET_STATIC_RUNTIME=PASS
'@

    $result = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $Remote
    $evidencePath = Join-Path $DiagDir 'target-rev7-static-runtime.txt'
    Set-Content -LiteralPath $evidencePath -Value ($result.StdOut + "`n" + $result.StdErr) -Encoding utf8
    Write-Host $result.StdOut
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr -ForegroundColor DarkYellow }
    Require ($result.ExitCode -eq 0) "REV7 target static runtime failed. See $evidencePath"

    foreach ($marker in @(
        'V100_REV7_PRESTART_QUIESCE=PASS',
        'V100_REV7_IMAGE_IDS=PASS',
        'V100_REV7_SERVER_OVERLAY=PASS',
        'V100_REV7_COMPOSE_CONFIG=PASS',
        'V100_REV7_STATIC_ENV=PASS',
        'V100_REV7_INTERNAL_NETWORK=PASS',
        'V100_REV7_BACKEND_HEALTH=PASS',
        'V100_REV7_FRONTEND_HEALTH=PASS',
        'V100_REV7_BACKGROUND_WORKERS_SUPPRESSED=PASS',
        'V100_REV7_EXTERNAL_EGRESS_BLOCKED=PASS',
        'V100_REV7_MONGO_PRESERVED=PASS',
        'V100_REV7_TARGET_STATIC_RUNTIME=PASS'
    )) {
        Require ($result.StdOut -match [regex]::Escape($marker)) "Required REV7 marker missing: $marker"
    }

    Write-Section 'VERIFY SOURCE ROLLBACK CHECKPOINT'
    $SourceProbe = @'
set -euo pipefail
count=$(docker ps --filter 'label=com.docker.compose.project=gpi-hub' --format '{{.Names}}' | wc -l | xargs)
echo "SOURCE_RUNNING_COUNT=$count"
[ "$count" -eq 3 ]
echo V100_REV7_SOURCE_ROLLBACK=PASS
'@
    $src = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceProbe
    Write-Host $src.StdOut
    Require ($src.ExitCode -eq 0) "Source rollback verification failed.`n$($src.StdOut)`n$($src.StdErr)"
    Require ($src.StdOut -match 'V100_REV7_SOURCE_ROLLBACK=PASS') 'Source rollback PASS marker missing.'

    Write-Section 'V100 REV7 FINAL RESULT'
    Write-Host 'TARGET BACKEND         : RUNNING / STATIC ISOLATED'
    Write-Host 'TARGET FRONTEND        : RUNNING / STATIC ISOLATED'
    Write-Host 'TARGET MONGO           : RUNNING / RESTORE PRESERVED'
    Write-Host 'BACKGROUND WORKERS     : SUPPRESSED'
    Write-Host 'EXTERNAL EGRESS        : BLOCKED'
    Write-Host 'SOURCE                 : RUNNING / ROLLBACK PRESERVED'
    Write-Host 'TRAFFIC CUTOVER        : NONE'
    Write-Host 'PRODUCTION             : NOT TOUCHED'
    Write-Host "DIAGNOSTICS            : $DiagDir"
    Write-Host ''
    Write-Host 'V100_TARGET_RUNTIME_RECONSTRUCTION=PASS' -ForegroundColor Green
    Write-Host 'V100_REV7_STATIC_ISOLATED_RUNTIME=PASS' -ForegroundColor Green
    Write-Host 'NEXT: V101 TARGET PARITY PRESERVATION VALIDATION.' -ForegroundColor Cyan
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
