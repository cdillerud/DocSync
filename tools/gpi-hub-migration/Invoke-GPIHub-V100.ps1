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
$SourceApp = [string]$State.source.app_path
$TargetApp = '/gpi-hub-data/apps/gpi-hub'
$TargetMongo = '/gpi-hub-data/volumes/mongodb'
$TargetUploads = '/gpi-hub-data/volumes/uploads'
$TargetMigration = '/gpi-hub-data/migration'
$ProjectName = 'gpi-hub-v100'
$BackendHostPort = 18005
$FrontendHostPort = 18080

$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$DiagDir = Join-Path $OperationalRoot ".gpi-diagnostics\migration-v100-target-runtime\$Stamp"
New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null
$TranscriptPath = Join-Path $DiagDir 'Invoke-GPIHub-V100.txt'
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-$token.err.txt"
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
        $result = [pscustomobject]@{ ExitCode = [int]$code; StdOut = [string]$stdout; StdErr = [string]$stderr }
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
        if ($probe.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.StdOut)) {
            return $file.FullName
        }
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
    $stderrFile = Join-Path $env:TEMP "gpi-v100-ssh-$token.err.txt"
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
        $stderr = if (Test-Path -LiteralPath $stderrFile) {
            Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
        } else { '' }
        return [pscustomobject]@{ ExitCode = [int]$code; StdOut = [string]$stdout; StdErr = [string]$stderr }
    }
    finally {
        $ErrorActionPreference = $oldEap
        if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function BashQuote([string]$Value) {
    Require ($Value -notmatch "'") "Unsupported single quote in shell value: $Value"
    return ("'{0}'" -f $Value)
}

function Write-Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

try {
    Write-Section 'V100 TARGET RUNTIME RECONSTRUCTION + ISOLATED START'
    Write-Host "Source VM          : $SourceIp"
    Write-Host "Target VM          : $TargetIp"
    Write-Host "Target project     : $ProjectName"
    Write-Host "Target backend     : 127.0.0.1:$BackendHostPort"
    Write-Host "Target frontend    : 127.0.0.1:$FrontendHostPort"
    Write-Host 'Production         : NOT TOUCHED'
    Write-Host 'Traffic cutover    : NONE'

    Require (Test-Path -LiteralPath $KeyPath -PathType Leaf) "SSH key missing: $KeyPath"
    Require ($null -ne (Get-Command ssh.exe -ErrorAction SilentlyContinue)) 'ssh.exe is unavailable.'
    Require ($null -ne (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) 'ssh-keygen.exe is unavailable.'

    $V99Summary = Get-ChildItem -LiteralPath (Join-Path $OperationalRoot '.gpi-diagnostics') -Filter 'v99-firstpass-summary.json' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Require ($null -ne $V99Summary) 'V99 first-pass summary was not found locally.'
    Write-Host "V99 summary        : $($V99Summary.FullName)"
    Write-Host 'V100_V99_PREREQUISITE=PASS' -ForegroundColor Green

    $SourceKnownHosts = Get-KnownHostsForIp -Ip $SourceIp
    $TargetKnownHosts = Get-KnownHostsForIp -Ip $TargetIp
    Write-Host "Source known_hosts : $SourceKnownHosts"
    Write-Host "Target known_hosts : $TargetKnownHosts"
    Write-Host 'V100_SSH_TRUST=PASS' -ForegroundColor Green

    Write-Section '1. DISCOVER AUTHORITATIVE SOURCE RUNTIME'

    $SourceDiscovery = @'
set -euo pipefail
project=gpi-hub
first=$(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.Names}}' | head -n 1)
if [ -z "$first" ]; then
  echo 'ERROR=no_compose_containers'
  exit 21
fi

echo "HOST=$(hostname)"
echo "PROJECT=$project"
echo "WORKDIR=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$first")"
echo "CONFIG_FILES=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$first")"

for c in $(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.Names}}'); do
  service=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$c")
  image=$(docker inspect -f '{{.Config.Image}}' "$c")
  imageid=$(docker inspect -f '{{.Image}}' "$c")
  echo "C|$c|$service|$image|$imageid"

  docker inspect -f '{{range .Mounts}}{{println .Type "|" .Name "|" .Source "|" .Destination}}{{end}}' "$c" |
  while IFS='|' read -r t n s d; do
    t=$(echo "$t" | xargs)
    n=$(echo "$n" | xargs)
    s=$(echo "$s" | xargs)
    d=$(echo "$d" | xargs)
    [ -n "$t" ] && echo "M|$service|$t|$n|$s|$d"
  done

  docker inspect -f '{{range $p,$b := .HostConfig.PortBindings}}{{if $b}}{{range $b}}{{println $p "|" .HostIp "|" .HostPort}}{{end}}{{end}}{{end}}' "$c" |
  while IFS='|' read -r cp hip hp; do
    cp=$(echo "$cp" | xargs)
    hip=$(echo "$hip" | xargs)
    hp=$(echo "$hp" | xargs)
    [ -n "$cp" ] && echo "P|$service|$cp|$hip|$hp"
  done
done

count=$(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.Names}}' | wc -l | xargs)
echo "RUNNING_COUNT=$count"
'@

    $src = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourceDiscovery
    Require ($src.ExitCode -eq 0) "Source runtime discovery failed.`n$($src.StdOut)`n$($src.StdErr)"
    Set-Content -LiteralPath (Join-Path $DiagDir 'source-runtime.txt') -Value $src.StdOut -Encoding utf8

    $kv = @{}
    $containers = @()
    $mounts = @()
    $ports = @()
    foreach ($line in (($src.StdOut -replace "`r",'') -split "`n")) {
        if ($line -match '^([A-Z_]+)=(.*)$') {
            $kv[$Matches[1]] = $Matches[2]
            continue
        }
        $parts = $line -split '\|',6
        if ($parts.Count -ge 5 -and $parts[0] -eq 'C') {
            $containers += [pscustomobject]@{ Container=$parts[1]; Service=$parts[2]; Image=$parts[3]; ImageId=$parts[4] }
        }
        elseif ($parts.Count -ge 6 -and $parts[0] -eq 'M') {
            $mounts += [pscustomobject]@{ Service=$parts[1]; Type=$parts[2]; Name=$parts[3]; Source=$parts[4]; Destination=$parts[5] }
        }
        elseif ($parts.Count -ge 5 -and $parts[0] -eq 'P') {
            $ports += [pscustomobject]@{ Service=$parts[1]; ContainerPort=$parts[2]; HostIp=$parts[3]; HostPort=$parts[4] }
        }
    }

    Require ($containers.Count -ge 3) "Expected at least three active source compose containers; found $($containers.Count)."
    Require ($kv.ContainsKey('RUNNING_COUNT')) 'Source running-container count was not captured.'

    $backend = $containers | Where-Object { $_.Service -match 'backend|api' -or $_.Container -match 'backend' } | Select-Object -First 1
    $frontend = $containers | Where-Object { $_.Service -match 'frontend|web' -or $_.Container -match 'frontend' } | Select-Object -First 1
    $mongoMount = $mounts | Where-Object { $_.Name -eq 'gpi-hub_mongodb_data' } | Select-Object -First 1
    $uploadMounts = @($mounts | Where-Object { $_.Name -eq 'gpi-hub_uploads_data' })
    $mongo = if ($null -ne $mongoMount) {
        $containers | Where-Object { $_.Service -eq $mongoMount.Service } | Select-Object -First 1
    } else {
        $containers | Where-Object { $_.Service -match 'mongo' -or $_.Container -match 'mongo' } | Select-Object -First 1
    }

    Require ($null -ne $backend) 'Could not identify source backend service.'
    Require ($null -ne $frontend) 'Could not identify source frontend service.'
    Require ($null -ne $mongo) 'Could not identify source Mongo service.'
    Require ($null -ne $mongoMount) 'Could not identify source Mongo volume destination.'
    Require ($uploadMounts.Count -gt 0) 'Could not identify source uploads volume destination.'

    $backendPort = $ports | Where-Object { $_.Service -eq $backend.Service -and $_.HostPort -eq '8005' } | Select-Object -First 1
    if ($null -eq $backendPort) { $backendPort = $ports | Where-Object { $_.Service -eq $backend.Service } | Select-Object -First 1 }
    $frontendPort = $ports | Where-Object { $_.Service -eq $frontend.Service -and $_.HostPort -eq '8080' } | Select-Object -First 1
    if ($null -eq $frontendPort) { $frontendPort = $ports | Where-Object { $_.Service -eq $frontend.Service } | Select-Object -First 1 }
    Require ($null -ne $backendPort) 'Could not identify backend container port.'
    Require ($null -ne $frontendPort) 'Could not identify frontend container port.'

    $backendContainerPort = ($backendPort.ContainerPort -replace '/tcp$','')
    $frontendContainerPort = ($frontendPort.ContainerPort -replace '/tcp$','')

    Write-Host "Backend service     : $($backend.Service) -> $backendContainerPort/tcp"
    Write-Host "Frontend service    : $($frontend.Service) -> $frontendContainerPort/tcp"
    Write-Host "Mongo service       : $($mongo.Service) -> $($mongoMount.Destination)"
    Write-Host "Uploads mount count : $($uploadMounts.Count)"
    Write-Host "Source running      : $($kv.RUNNING_COUNT)"
    Write-Host 'V100_SOURCE_RUNTIME_DISCOVERY=PASS' -ForegroundColor Green

    Write-Section '2. BUILD TARGET-ONLY COMPOSE OVERRIDE'

    $serviceCfg = @{}
    function Ensure-ServiceCfg([string]$Name) {
        if (-not $serviceCfg.ContainsKey($Name)) {
            $serviceCfg[$Name] = [ordered]@{ Environment = $false; Port = $null; Volumes = @() }
        }
    }

    foreach ($p in $ports) {
        Ensure-ServiceCfg $p.Service
        $serviceCfg[$p.Service].Port = 'none'
    }
    Ensure-ServiceCfg $backend.Service
    Ensure-ServiceCfg $frontend.Service
    Ensure-ServiceCfg $mongo.Service
    $serviceCfg[$backend.Service].Environment = $true
    $serviceCfg[$backend.Service].Port = "127.0.0.1:${BackendHostPort}:${backendContainerPort}"
    $serviceCfg[$frontend.Service].Port = "127.0.0.1:${FrontendHostPort}:${frontendContainerPort}"

    foreach ($m in $mounts) {
        $mappedSource = $null
        if ($m.Name -eq 'gpi-hub_mongodb_data') {
            $mappedSource = $TargetMongo
        }
        elseif ($m.Name -eq 'gpi-hub_uploads_data') {
            $mappedSource = $TargetUploads
        }
        elseif ($m.Type -eq 'bind' -and $m.Source.StartsWith($SourceApp,[System.StringComparison]::Ordinal)) {
            $suffix = $m.Source.Substring($SourceApp.Length).TrimStart('/')
            $mappedSource = if ([string]::IsNullOrWhiteSpace($suffix)) { $TargetApp } else { "$TargetApp/$suffix" }
        }
        elseif ($m.Type -eq 'bind' -and $m.Source -eq '/var/run/docker.sock') {
            $mappedSource = '/var/run/docker.sock'
        }

        if ($null -ne $mappedSource) {
            Ensure-ServiceCfg $m.Service
            $serviceCfg[$m.Service].Volumes += [pscustomobject]@{ Source=$mappedSource; Destination=$m.Destination }
        }
        elseif ($m.Type -eq 'volume' -and -not [string]::IsNullOrWhiteSpace($m.Name)) {
            throw "Unmapped active named volume '$($m.Name)' on service '$($m.Service)' destination '$($m.Destination)'. V100 refuses to invent target state."
        }
    }

    $yaml = [System.Collections.Generic.List[string]]::new()
    $yaml.Add('services:')
    foreach ($serviceName in ($serviceCfg.Keys | Sort-Object)) {
        Require ($serviceName -match '^[A-Za-z0-9_.-]+$') "Unsafe compose service name: $serviceName"
        $cfg = $serviceCfg[$serviceName]
        $yaml.Add("  ${serviceName}:")
        if ($cfg.Environment) {
            $yaml.Add('    environment:')
            $yaml.Add('      SHAREPOINT_TARGET: "test"')
            $yaml.Add('      BC_WRITE_ENABLED: "false"')
            $yaml.Add('      BC_BLOCK_PRODUCTION_WRITES: "true"')
        }
        if ($null -ne $cfg.Port) {
            if ($cfg.Port -eq 'none') {
                $yaml.Add('    ports: !override []')
            } else {
                $yaml.Add('    ports: !override')
                $yaml.Add(('      - "{0}"' -f $cfg.Port))
            }
        }
        if ($cfg.Volumes.Count -gt 0) {
            $yaml.Add('    volumes:')
            foreach ($v in $cfg.Volumes) {
                $yaml.Add('      - type: bind')
                $yaml.Add("        source: $($v.Source)")
                $yaml.Add("        target: $($v.Destination)")
            }
        }
    }
    $OverrideYaml = $yaml -join "`n"
    Set-Content -LiteralPath (Join-Path $DiagDir 'v100-target-override.yml') -Value $OverrideYaml -Encoding utf8
    Write-Host $OverrideYaml
    Write-Host 'V100_TARGET_OVERRIDE_BUILT=PASS' -ForegroundColor Green

    Write-Section '3. MAP SOURCE COMPOSE FILES TO TARGET'

    $SourceConfigFiles = @()
    if ($kv.ContainsKey('CONFIG_FILES') -and -not [string]::IsNullOrWhiteSpace($kv.CONFIG_FILES)) {
        $SourceConfigFiles = @($kv.CONFIG_FILES -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    $TargetConfigFiles = @()
    foreach ($file in $SourceConfigFiles) {
        Require ($file.StartsWith($SourceApp,[System.StringComparison]::Ordinal)) "Source compose file is outside app root: $file"
        $suffix = $file.Substring($SourceApp.Length).TrimStart('/')
        $TargetConfigFiles += "$TargetApp/$suffix"
    }

    $SourceWorkDir = if ($kv.ContainsKey('WORKDIR')) { [string]$kv.WORKDIR } else { $SourceApp }
    $TargetWorkDir = $TargetApp
    if (-not [string]::IsNullOrWhiteSpace($SourceWorkDir) -and $SourceWorkDir.StartsWith($SourceApp,[System.StringComparison]::Ordinal)) {
        $workSuffix = $SourceWorkDir.Substring($SourceApp.Length).TrimStart('/')
        if (-not [string]::IsNullOrWhiteSpace($workSuffix)) { $TargetWorkDir = "$TargetApp/$workSuffix" }
    }

    $ComposeArray = if ($TargetConfigFiles.Count -gt 0) {
        ($TargetConfigFiles | ForEach-Object { BashQuote $_ }) -join ' '
    } else { '' }

    $ImagePairs = ($containers | ForEach-Object { "$($_.Image)|$($_.ImageId)" }) -join "`n"
    $OverrideB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($OverrideYaml))

    Write-Host "Target workdir      : $TargetWorkDir"
    Write-Host "Compose file count  : $($TargetConfigFiles.Count)"
    Write-Host 'V100_COMPOSE_MAPPING=PASS' -ForegroundColor Green

    Write-Section '4. RECONSTRUCT TARGET RUNTIME, RESTORE MONGO, START ISOLATED STACK'

    $TargetTemplate = @'
set -euo pipefail

APP=__TARGET_APP__
WORKDIR=__TARGET_WORKDIR__
MONGO_DIR=__TARGET_MONGO__
UPLOADS_DIR=__TARGET_UPLOADS__
MIG_DIR=__TARGET_MIGRATION__
PROJECT=__PROJECT__
BACKEND_SERVICE=__BACKEND_SERVICE__
FRONTEND_SERVICE=__FRONTEND_SERVICE__
MONGO_SERVICE=__MONGO_SERVICE__
BACKEND_PORT=__BACKEND_PORT__
FRONTEND_PORT=__FRONTEND_PORT__
OVERRIDE="$MIG_DIR/v100-target-override.yml"
RESTORE_MARKER="$MIG_DIR/v100-mongo-restored.marker"
RUNTIME_SUMMARY="$MIG_DIR/v100-runtime-summary.txt"

sudo mkdir -p "$MONGO_DIR" "$UPLOADS_DIR" "$MIG_DIR"
sudo chown -R azureuser:azureuser "$MIG_DIR"

echo '__OVERRIDE_B64__' | base64 -d > "$OVERRIDE"

if [ ! -d "$WORKDIR" ]; then
  echo "Target workdir missing: $WORKDIR" >&2
  exit 31
fi
cd "$WORKDIR"

COMPOSE_FILES=( __COMPOSE_FILES__ )
if [ ${#COMPOSE_FILES[@]} -eq 0 ]; then
  for c in "$APP/docker-compose.yml" "$APP/docker-compose.yaml" "$APP/compose.yml" "$APP/compose.yaml"; do
    if [ -f "$c" ]; then COMPOSE_FILES=( "$c" ); break; fi
  done
fi
if [ ${#COMPOSE_FILES[@]} -eq 0 ]; then
  echo 'No target compose file found.' >&2
  exit 32
fi

COMPOSE_ARGS=()
for f in "${COMPOSE_FILES[@]}"; do
  [ -f "$f" ] || { echo "Compose file missing: $f" >&2; exit 33; }
  COMPOSE_ARGS+=( -f "$f" )
done
COMPOSE_ARGS+=( -f "$OVERRIDE" )

echo '--- COMPOSE VERSION ---'
docker compose version

echo '--- COMPOSE CONFIG VALIDATION ---'
docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" config --quiet
echo V100_COMPOSE_CONFIG=PASS

echo '--- IMAGE ID VERIFICATION ---'
while IFS='|' read -r ref expected; do
  [ -n "$ref" ] || continue
  actual=$(docker image inspect "$ref" -f '{{.Id}}')
  if [ "$actual" != "$expected" ]; then
    echo "Image mismatch for $ref" >&2
    echo "expected=$expected" >&2
    echo "actual=$actual" >&2
    exit 34
  fi
  echo "IMAGE_OK=$ref|$actual"
done <<'IMAGE_EOF'
__IMAGE_PAIRS__
IMAGE_EOF
echo V100_IMAGE_IDS=PASS

archive=$(ls -1t "$MIG_DIR"/mongo-firstpass-*.archive.gz 2>/dev/null | head -n 1 || true)
[ -n "$archive" ] || { echo 'V99 Mongo archive missing.' >&2; exit 35; }
archive_sha=$(sha256sum "$archive" | cut -d' ' -f1)
archive_bytes=$(stat -c %s "$archive")
echo "MONGO_ARCHIVE=$archive"
echo "MONGO_ARCHIVE_BYTES=$archive_bytes"
echo "MONGO_ARCHIVE_SHA256=$archive_sha"

if [ -f "$RESTORE_MARKER" ] && [ -f "$MONGO_DIR/WiredTiger" ] && grep -q "$archive_sha" "$RESTORE_MARKER"; then
  echo V100_MONGO_RESTORE_ALREADY_COMPLETE=PASS
else
  echo '--- CLEAN TARGET-ONLY MONGO DATA FOR CONTROLLED RESTORE ---'
  docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" stop "$MONGO_SERVICE" >/dev/null 2>&1 || true
  docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" rm -f "$MONGO_SERVICE" >/dev/null 2>&1 || true
  sudo find "$MONGO_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

  echo '--- START TARGET MONGO ---'
  docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" up -d --no-build "$MONGO_SERVICE"
  mongo_container=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$MONGO_SERVICE" --format '{{.Names}}' | head -n 1)
  [ -n "$mongo_container" ] || { echo 'Target Mongo container not running.' >&2; exit 36; }

  ready=0
  for i in $(seq 1 90); do
    if docker exec "$mongo_container" sh -lc 'if command -v mongosh >/dev/null 2>&1; then if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({ping:1}).ok"; else mongosh --quiet --eval "db.adminCommand({ping:1}).ok"; fi; else exit 1; fi' >/dev/null 2>&1; then
      ready=1; break
    fi
    sleep 2
  done
  [ "$ready" = 1 ] || { echo 'Target Mongo did not become ready.' >&2; docker logs --tail 100 "$mongo_container" >&2 || true; exit 37; }
  echo V100_TARGET_MONGO_READY=PASS

  echo '--- RESTORE V99 MONGO ARCHIVE ---'
  cat "$archive" | docker exec -i "$mongo_container" sh -lc '
    set -e
    command -v mongorestore >/dev/null 2>&1
    args="--archive --gzip --drop --nsExclude=admin.* --nsExclude=config.* --nsExclude=local.*"
    if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then
      exec mongorestore $args --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin
    else
      exec mongorestore $args
    fi
  '
  printf 'archive_sha256=%s\nrestored_utc=%s\n' "$archive_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RESTORE_MARKER"
  echo V100_MONGO_RESTORE=PASS
fi

docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" up -d --no-build

echo '--- REQUIRED SERVICE STATUS ---'
for svc in "$MONGO_SERVICE" "$BACKEND_SERVICE" "$FRONTEND_SERVICE"; do
  cid=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$svc" --format '{{.ID}}' | head -n 1)
  [ -n "$cid" ] || { echo "Required service not running: $svc" >&2; docker compose -p "$PROJECT" "${COMPOSE_ARGS[@]}" ps >&2; exit 38; }
  echo "SERVICE_RUNNING=$svc|$cid"
done

echo '--- SAFETY ENVIRONMENT ---'
backend_container=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$BACKEND_SERVICE" --format '{{.Names}}' | head -n 1)
[ -n "$backend_container" ] || { echo 'Backend container not found.' >&2; exit 39; }
for expected in 'SHAREPOINT_TARGET=test' 'BC_WRITE_ENABLED=false' 'BC_BLOCK_PRODUCTION_WRITES=true'; do
  if ! docker inspect "$backend_container" -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq "$expected"; then
    echo "Safety environment mismatch: $expected" >&2
    exit 40
  fi
  echo "SAFETY_ENV_OK=$expected"
done
echo V100_SAFETY_ENV=PASS

echo '--- BACKEND HEALTH ---'
backend_ok=0
for path in /health /api/health /docs /; do
  code=$(curl -sS -o /tmp/v100-backend.out -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT$path" || true)
  if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null; then
    echo "BACKEND_HTTP=$path|$code"
    backend_ok=1
    break
  fi
  sleep 2
done
[ "$backend_ok" = 1 ] || { echo 'Backend did not return a successful HTTP response.' >&2; docker logs --tail 120 "$backend_container" >&2 || true; exit 41; }
echo V100_BACKEND_HEALTH=PASS

echo '--- FRONTEND HEALTH ---'
frontend_ok=0
for i in $(seq 1 60); do
  code=$(curl -sS -o /tmp/v100-frontend.out -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" || true)
  if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null; then frontend_ok=1; break; fi
  sleep 2
done
[ "$frontend_ok" = 1 ] || { echo 'Frontend did not return a successful HTTP response.' >&2; exit 42; }
echo "FRONTEND_HTTP=/|$code"
echo V100_FRONTEND_HEALTH=PASS

echo '--- DATA PRESENCE ---'
upload_bytes=$(du -sb "$UPLOADS_DIR" | cut -f1)
upload_files=$(find "$UPLOADS_DIR" -type f | wc -l | xargs)
[ "$upload_bytes" -gt 30000000000 ] || { echo "Uploads unexpectedly small: $upload_bytes" >&2; exit 43; }
[ "$upload_files" -gt 80000 ] || { echo "Uploads file count unexpectedly small: $upload_files" >&2; exit 44; }
echo "UPLOAD_BYTES=$upload_bytes"
echo "UPLOAD_FILES=$upload_files"
echo V100_UPLOADS_PRESENCE=PASS

mongo_container=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$MONGO_SERVICE" --format '{{.Names}}' | head -n 1)
db_names=$(docker exec "$mongo_container" sh -lc 'if [ -n "${MONGO_INITDB_ROOT_USERNAME:-}" ] && [ -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]; then mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; else mongosh --quiet --eval "db.adminCommand({listDatabases:1}).databases.map(d=>d.name).join(\",\")"; fi')
echo "MONGO_DATABASES=$db_names"
[ -n "$db_names" ] || { echo 'Mongo database list is empty.' >&2; exit 45; }
echo V100_MONGO_DATA=PASS

{
  echo "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "project=$PROJECT"
  echo "backend=http://127.0.0.1:$BACKEND_PORT"
  echo "frontend=http://127.0.0.1:$FRONTEND_PORT"
  echo "mongo_archive_sha256=$archive_sha"
  echo 'sharepoint_target=test'
  echo 'bc_write_enabled=false'
  echo 'bc_block_production_writes=true'
  echo 'traffic_cutover=none'
  echo 'production_touched=false'
} > "$RUNTIME_SUMMARY"

echo "RUNTIME_SUMMARY=$RUNTIME_SUMMARY"
echo V100_TARGET_RUNTIME=PASS
'@

    $TargetScript = $TargetTemplate
    $TargetScript = $TargetScript.Replace('__TARGET_APP__',(BashQuote $TargetApp))
    $TargetScript = $TargetScript.Replace('__TARGET_WORKDIR__',(BashQuote $TargetWorkDir))
    $TargetScript = $TargetScript.Replace('__TARGET_MONGO__',(BashQuote $TargetMongo))
    $TargetScript = $TargetScript.Replace('__TARGET_UPLOADS__',(BashQuote $TargetUploads))
    $TargetScript = $TargetScript.Replace('__TARGET_MIGRATION__',(BashQuote $TargetMigration))
    $TargetScript = $TargetScript.Replace('__PROJECT__',(BashQuote $ProjectName))
    $TargetScript = $TargetScript.Replace('__BACKEND_SERVICE__',(BashQuote $backend.Service))
    $TargetScript = $TargetScript.Replace('__FRONTEND_SERVICE__',(BashQuote $frontend.Service))
    $TargetScript = $TargetScript.Replace('__MONGO_SERVICE__',(BashQuote $mongo.Service))
    $TargetScript = $TargetScript.Replace('__BACKEND_PORT__',[string]$BackendHostPort)
    $TargetScript = $TargetScript.Replace('__FRONTEND_PORT__',[string]$FrontendHostPort)
    $TargetScript = $TargetScript.Replace('__OVERRIDE_B64__',$OverrideB64)
    $TargetScript = $TargetScript.Replace('__COMPOSE_FILES__',$ComposeArray)
    $TargetScript = $TargetScript.Replace('__IMAGE_PAIRS__',$ImagePairs)

    Set-Content -LiteralPath (Join-Path $DiagDir 'target-v100-script.sh') -Value $TargetScript -Encoding utf8
    $target = Invoke-SshScript -Ip $TargetIp -KnownHosts $TargetKnownHosts -ScriptText $TargetScript
    Set-Content -LiteralPath (Join-Path $DiagDir 'target-v100-output.txt') -Value ($target.StdOut + "`n" + $target.StdErr) -Encoding utf8
    Write-Host $target.StdOut
    if (-not [string]::IsNullOrWhiteSpace($target.StdErr)) { Write-Host $target.StdErr -ForegroundColor DarkYellow }
    Require ($target.ExitCode -eq 0) "V100 target reconstruction failed with exit code $($target.ExitCode)."
    foreach ($marker in @(
        'V100_COMPOSE_CONFIG=PASS',
        'V100_IMAGE_IDS=PASS',
        'V100_SAFETY_ENV=PASS',
        'V100_BACKEND_HEALTH=PASS',
        'V100_FRONTEND_HEALTH=PASS',
        'V100_UPLOADS_PRESENCE=PASS',
        'V100_MONGO_DATA=PASS',
        'V100_TARGET_RUNTIME=PASS'
    )) {
        Require ($target.StdOut -match [regex]::Escape($marker)) "Required V100 marker missing: $marker"
    }

    Write-Section '5. VERIFY SOURCE REMAINS RUNNING AND UNCHANGED'

    $ExpectedSourceCount = [int]$kv.RUNNING_COUNT
    $SourcePostTemplate = @'
set -euo pipefail
count=$(docker ps --filter 'label=com.docker.compose.project=gpi-hub' --format '{{.Names}}' | wc -l | xargs)
echo "RUNNING_COUNT=$count"
[ "$count" -eq __EXPECTED__ ]
echo V100_SOURCE_STILL_RUNNING=PASS
'@
    $SourcePost = $SourcePostTemplate.Replace('__EXPECTED__',[string]$ExpectedSourceCount)
    $srcPost = Invoke-SshScript -Ip $SourceIp -KnownHosts $SourceKnownHosts -ScriptText $SourcePost
    Write-Host $srcPost.StdOut
    Require ($srcPost.ExitCode -eq 0) 'Source running-container verification failed after V100.'
    Require ($srcPost.StdOut -match 'V100_SOURCE_STILL_RUNNING=PASS') 'Source-running PASS marker missing.'

    Write-Section 'V100 FINAL RESULT'
    Write-Host 'V99 PREREQUISITE       : PASS'
    Write-Host 'SOURCE RUNTIME         : DISCOVERED / UNCHANGED'
    Write-Host 'TARGET IMAGES          : EXACT SOURCE IMAGE IDs VERIFIED'
    Write-Host 'TARGET DATA MOUNTS     : DEDICATED DISK BIND MOUNTS'
    Write-Host 'MONGO                  : V99 ARCHIVE RESTORED'
    Write-Host 'TARGET HUB             : RUNNING / ISOLATED'
    Write-Host "BACKEND                : 127.0.0.1:$BackendHostPort"
    Write-Host "FRONTEND               : 127.0.0.1:$FrontendHostPort"
    Write-Host 'SHAREPOINT_TARGET      : test'
    Write-Host 'BC_WRITE_ENABLED       : false'
    Write-Host 'BC_BLOCK_PROD_WRITES   : true'
    Write-Host 'SOURCE                 : RUNNING / UNCHANGED'
    Write-Host 'TRAFFIC CUTOVER        : NONE'
    Write-Host 'PRODUCTION             : NOT TOUCHED'
    Write-Host "DIAGNOSTICS            : $DiagDir"
    Write-Host ''
    Write-Host 'NEXT                    : V101 TARGET PARITY VALIDATION (WAREHOUSE + AP + DUPLICATE/IDEMPOTENCY)' -ForegroundColor Cyan
    Write-Host 'V100_TARGET_RUNTIME_RECONSTRUCTION=PASS' -ForegroundColor Green
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
