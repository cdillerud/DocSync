#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedName = 'W117105_Strategic Warehousing_122625_.pdf'
$ExpectedSha = '48410cadceaa411d65e51bd266be5c5942b4431cdede9e7a05b871e75a3a2c25'
$LegacyDriveId = 'b!sGwtDnGpU0SknFYQW3UCWWUMVN5OAqNNqrsMXnSKBw-YAHZMq-H6QZCZOp4jgXfD'
$LegacyItemId = '016AISIVQOXIJJ434KU5H2PFEZHHZFGQ23'
$ExpectedBackendImage = 'sha256:646051f6b0434b20ad429dec18c5f7b2a7d017c0fdec94f4bd77eaa7375fabb3'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { throw "Migration state missing: $StatePath" }
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50
$OperationalRoot = [string]$State.local.operational_root
$KeyPath = [string]$State.local.ssh_key
$SourceIp = [string]$State.source.public_ip

$Downloads = Join-Path $env:USERPROFILE 'Downloads'
$Exact = Join-Path $Downloads $ExpectedName
New-Item -ItemType Directory -Path $Downloads -Force | Out-Null

function Get-Sha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Find-VerifiedLocalCorpus {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $Exact -PathType Leaf) { $candidates.Add($Exact) }
    foreach ($f in @(Get-ChildItem -LiteralPath $Downloads -File -Filter 'W117105*.pdf' -ErrorAction SilentlyContinue)) { $candidates.Add($f.FullName) }
    foreach ($f in @(Get-ChildItem -LiteralPath $Downloads -File -Filter '*.pdf' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 100)) { $candidates.Add($f.FullName) }
    foreach ($path in @($candidates | Select-Object -Unique)) {
        try {
            if ((Get-Sha $path) -eq $ExpectedSha) { return $path }
        } catch {}
    }
    return $null
}

function Get-KnownHostsForIp([string]$Ip) {
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics'
    foreach ($file in @(Get-ChildItem -LiteralPath $diagRoot -Filter '*known_hosts*' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
        $out = & ssh-keygen.exe -F $Ip -f $file.FullName 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace((@($out) -join "`n"))) { return $file.FullName }
    }
    throw "No Azure-verified known_hosts file found for source $Ip."
}

function Invoke-SourceScript([string]$KnownHosts,[string]$ScriptText) {
    $stderrFile = Join-Path $env:TEMP ("v108-entry-ssh-{0}.err" -f [guid]::NewGuid().ToString('N'))
    try {
        $args = @(
            '-i',$KeyPath,
            '-o','BatchMode=yes',
            '-o','StrictHostKeyChecking=yes',
            '-o',"UserKnownHostsFile=$KnownHosts",
            '-o','GlobalKnownHostsFile=NUL',
            '-o','ConnectTimeout=20',
            "azureuser@$SourceIp",
            'bash -s'
        )
        $oldEap = $ErrorActionPreference
        $nativeVar = Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
        $oldNative = if ($null -ne $nativeVar) { $nativeVar.Value } else { $null }
        try {
            $ErrorActionPreference = 'Continue'
            if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $false }
            $output = (($ScriptText -replace "`r`n","`n") | & ssh.exe @args 2> $stderrFile)
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $oldEap
            if ($null -ne $nativeVar) { $PSNativeCommandUseErrorActionPreference = $oldNative }
        }
        $stdout = (@($output) | ForEach-Object { [string]$_ }) -join "`n"
        $stderr = if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode=[int]$code; StdOut=$stdout; StdErr=$stderr }
    }
    finally { Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue }
}

$Verified = Find-VerifiedLocalCorpus
if ($Verified) {
    if ($Verified -ne $Exact) { Copy-Item -LiteralPath $Verified -Destination $Exact -Force }
    Write-Host "V108_ENTRY_LOCAL_CORPUS=$Verified" -ForegroundColor Cyan
    Write-Host 'V108_ENTRY_CORPUS_SHA_MATCH=PASS' -ForegroundColor Green
}
else {
    Write-Host 'V108_ENTRY_LOCAL_CORPUS=NOT_FOUND; retrieving exact legacy SharePoint item read-only via source backend...' -ForegroundColor Yellow
    if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) { throw "SSH key missing: $KeyPath" }
    if ($null -eq (Get-Command ssh.exe -ErrorAction SilentlyContinue)) { throw 'ssh.exe unavailable.' }
    if ($null -eq (Get-Command scp.exe -ErrorAction SilentlyContinue)) { throw 'scp.exe unavailable.' }
    if ($null -eq (Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue)) { throw 'ssh-keygen.exe unavailable.' }
    $KnownHosts = Get-KnownHostsForIp $SourceIp

    $Remote = @"
set -euo pipefail
EXPECTED_IMAGE='$ExpectedBackendImage'
EXPECTED_SHA='$ExpectedSha'
DRIVE_ID='$LegacyDriveId'
ITEM_ID='$LegacyItemId'
HOST_FILE='/tmp/v108-w117105-sharepoint.pdf'
backend=`$(docker ps --filter 'label=com.docker.compose.service=backend' --format '{{.Names}}' | head -n 1)
[ -n "`$backend" ] || { echo 'Source backend not running.' >&2; exit 71; }
[ "`$(docker inspect "`$backend" -f '{{.Image}}')" = "`$EXPECTED_IMAGE" ] || { echo 'Source backend image drift.' >&2; exit 72; }
cat > /tmp/v108-sp-read.py <<'PY'
import asyncio, hashlib, httpx, os
from services.sharepoint_service import _get_graph_token
DRIVE_ID = os.environ['V108_DRIVE_ID']
ITEM_ID = os.environ['V108_ITEM_ID']
EXPECTED = os.environ['V108_EXPECTED_SHA']
async def main():
    token = await _get_graph_token()
    url = f'https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}/content'
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        r = await client.get(url, headers={'Authorization': f'Bearer {token}'})
        r.raise_for_status()
        data = r.content
    sha = hashlib.sha256(data).hexdigest()
    if sha != EXPECTED:
        raise RuntimeError(f'Legacy corpus SHA mismatch: {sha}')
    with open('/tmp/v108-w117105.pdf','wb') as f:
        f.write(data)
    print(f'V108_ENTRY_GRAPH_READ_BYTES={len(data)}')
    print(f'V108_ENTRY_GRAPH_READ_SHA256={sha}')
    print('V108_ENTRY_LEGACY_SHAREPOINT_READ=PASS')
asyncio.run(main())
PY
docker cp /tmp/v108-sp-read.py "`$backend:/tmp/v108-sp-read.py" >/dev/null
rm -f /tmp/v108-sp-read.py
set +x
docker exec -e V108_DRIVE_ID="`$DRIVE_ID" -e V108_ITEM_ID="`$ITEM_ID" -e V108_EXPECTED_SHA="`$EXPECTED_SHA" "`$backend" python /tmp/v108-sp-read.py
docker cp "`$backend:/tmp/v108-w117105.pdf" "`$HOST_FILE" >/dev/null
docker exec "`$backend" rm -f /tmp/v108-sp-read.py /tmp/v108-w117105.pdf >/dev/null 2>&1 || true
[ "`$(sha256sum "`$HOST_FILE" | awk '{print `$1}')" = "`$EXPECTED_SHA" ] || { echo 'Host-staged corpus SHA mismatch.' >&2; rm -f "`$HOST_FILE"; exit 73; }
echo V108_ENTRY_SOURCE_CORPUS_STAGED=PASS
"@
    $r = Invoke-SourceScript -KnownHosts $KnownHosts -ScriptText $Remote
    if ($r.StdOut) { Write-Host $r.StdOut }
    if ($r.StdErr) { Write-Host $r.StdErr -ForegroundColor DarkYellow }
    if ($r.ExitCode -ne 0) { throw "Read-only legacy SharePoint corpus retrieval failed with exit code $($r.ExitCode)." }
    if ($r.StdOut -notmatch 'V108_ENTRY_LEGACY_SHAREPOINT_READ=PASS') { throw 'Legacy SharePoint read marker missing.' }
    if ($r.StdOut -notmatch 'V108_ENTRY_SOURCE_CORPUS_STAGED=PASS') { throw 'Source corpus staging marker missing.' }

    $scpArgs = @(
        '-i',$KeyPath,
        '-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes',
        '-o',"UserKnownHostsFile=$KnownHosts",
        '-o','GlobalKnownHostsFile=NUL',
        '-o','ConnectTimeout=20',
        "azureuser@${SourceIp}:/tmp/v108-w117105-sharepoint.pdf",
        $Exact
    )
    & scp.exe @scpArgs
    if ($LASTEXITCODE -ne 0) { throw "SCP of verified legacy corpus failed with exit code $LASTEXITCODE." }
    $cleanup = Invoke-SourceScript -KnownHosts $KnownHosts -ScriptText "rm -f /tmp/v108-w117105-sharepoint.pdf`necho V108_ENTRY_SOURCE_TEMP_CLEANUP=PASS"
    if ($cleanup.StdOut) { Write-Host $cleanup.StdOut }

    $sha = Get-Sha $Exact
    if ($sha -ne $ExpectedSha) { Remove-Item -LiteralPath $Exact -Force -ErrorAction SilentlyContinue; throw "Retrieved corpus SHA mismatch on controller: $sha" }
    Write-Host 'V108_ENTRY_CORPUS_SELF_RETRIEVAL=PASS' -ForegroundColor Green
    Write-Host 'V108_ENTRY_CORPUS_SHA_MATCH=PASS' -ForegroundColor Green
}

Write-Host 'V108_REV3_ENTRY_WRAPPER=PASS' -ForegroundColor Cyan
$Main = Join-Path $PSScriptRoot 'Invoke-GPIHub-V108-Durable-Warehouse-Strategic-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Main -PathType Leaf)) { throw "V108 main script missing: $Main" }
& $Main
