#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$BaseScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100.ps1'
$GeneratedScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV2.generated.ps1'

if (-not (Test-Path -LiteralPath $BaseScript -PathType Leaf)) {
    throw "Base V100 script not found: $BaseScript"
}

$source = Get-Content -LiteralPath $BaseScript -Raw
$startMarker = "    `$SourceDiscovery = @'"
$endMarker = "'@`n`n    `$src = Invoke-SshScript"

$start = $source.IndexOf($startMarker, [System.StringComparison]::Ordinal)
if ($start -lt 0) {
    throw 'Could not locate V100 SourceDiscovery start marker.'
}

$end = $source.IndexOf($endMarker, $start, [System.StringComparison]::Ordinal)
if ($end -lt 0) {
    $endMarker = "'@`r`n`r`n    `$src = Invoke-SshScript"
    $end = $source.IndexOf($endMarker, $start, [System.StringComparison]::Ordinal)
}
if ($end -lt 0) {
    throw 'Could not locate V100 SourceDiscovery end marker.'
}

$replacement = @'
    $SourceDiscovery = @'
set -euo pipefail
project=gpi-hub

command -v python3 >/dev/null 2>&1 || {
  echo 'ERROR=python3_not_found'
  exit 22
}

mapfile -t containers < <(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.Names}}')
if [ ${#containers[@]} -eq 0 ]; then
  echo 'ERROR=no_compose_containers'
  exit 21
fi

docker inspect "${containers[@]}" | python3 -c '
import json, socket, sys
items = json.load(sys.stdin)
if not items:
    print("ERROR=no_inspect_records")
    raise SystemExit(23)

labels = ((items[0].get("Config") or {}).get("Labels") or {})
print("HOST=" + socket.gethostname())
print("PROJECT=gpi-hub")
print("WORKDIR=" + (labels.get("com.docker.compose.project.working_dir") or ""))
print("CONFIG_FILES=" + (labels.get("com.docker.compose.project.config_files") or ""))

for item in items:
    cfg = item.get("Config") or {}
    labels = cfg.get("Labels") or {}
    service = labels.get("com.docker.compose.service") or ""
    name = (item.get("Name") or "").lstrip("/")
    image = cfg.get("Image") or ""
    image_id = item.get("Image") or ""
    print(f"C|{name}|{service}|{image}|{image_id}")

    for mount in item.get("Mounts") or []:
        mtype = mount.get("Type") or ""
        mname = mount.get("Name") or ""
        source = mount.get("Source") or ""
        destination = mount.get("Destination") or ""
        print(f"M|{service}|{mtype}|{mname}|{source}|{destination}")

    bindings = ((item.get("HostConfig") or {}).get("PortBindings") or {})
    for container_port, host_bindings in bindings.items():
        for binding in host_bindings or []:
            host_ip = binding.get("HostIp") or ""
            host_port = binding.get("HostPort") or ""
            print(f"P|{service}|{container_port}|{host_ip}|{host_port}")

print(f"RUNNING_COUNT={len(items)}")
'
'@

    $src = Invoke-SshScript
'@

$prefix = $source.Substring(0, $start)
$suffixStart = $end + $endMarker.Length
$suffix = $source.Substring($suffixStart)
$patched = $prefix + $replacement + $suffix

# Validate parser before execution so a generated syntax issue fails locally and clearly.
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($patched, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {
    $detail = ($errors | ForEach-Object { "Line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n"
    throw "Generated V100 REV2 failed PowerShell parser validation:`n$detail"
}

Set-Content -LiteralPath $GeneratedScript -Value $patched -Encoding utf8 -NoNewline
Write-Host 'V100_REV2_SOURCE_DISCOVERY_PATCH=PASS' -ForegroundColor Green
Write-Host "Generated script: $GeneratedScript"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedScript
exit $LASTEXITCODE
