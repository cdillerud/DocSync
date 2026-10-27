#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub: list the supplier drawings on OneGamer (Manufacturers - Vendors/<supplier>/Drawings) and, with -Send,
  send the list to the sales assistant so its options link each item's drawing.

.DESCRIPTION
  Runs inside the Hub's backend container with the Hub's Microsoft Graph app token. Only names and links are read and
  sent (supplier folder, file name, link, modified date); no file is downloaded or changed. Without -Send it only
  lists and prints counts. The reader is loaded for this run from the branch (git on the VM), so the running Hub is
  unchanged. Reaches the VM through Azure (az vm run-command, with your az login).
.EXAMPLE
  .\scripts\Sync-Hub-Drawings.ps1
  .\scripts\Sync-Hub-Drawings.ps1 -Send -Confirmation 'SEND DRAWINGS'
#>
[CmdletBinding()]
param(
    [switch]$Send,
    [string]$Confirmation = '',
    [string]$Branch = 'feature/hub-new-item-requests-live',
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'
if ($Send -and $Confirmation -ne 'SEND DRAWINGS') { throw "-Send needs -Confirmation 'SEND DRAWINGS'." }

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

$sendIt = if ($Send) { 'True' } else { 'False' }
$py = @"
import asyncio, json, sys, importlib.util
spec = importlib.util.spec_from_file_location("drawing_index_branch", "/tmp/drawing_index.py")
di = importlib.util.module_from_spec(spec)
sys.modules["drawing_index_branch"] = di
spec.loader.exec_module(di)
print(json.dumps(asyncio.run(di.run(send_it=$sendIt)), indent=1))
"@
$pyB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($py))
# az on Windows is a .cmd wrapper that garbles quotes and redirections: the shell steps travel base64-encoded.
$sh = "cd /opt/gpi-hub && o=`$(stat -c %U .git) && sudo -u `$o git fetch -q origin '$Branch' && " +
      "sudo -u `$o git show FETCH_HEAD:backend/services/drawing_index.py > /tmp/drawing_index.py && " +
      "docker cp /tmp/drawing_index.py gpi-backend:/tmp/drawing_index.py && " +
      "echo $pyB64 | base64 -d > /tmp/drawings-run.py && docker cp /tmp/drawings-run.py gpi-backend:/tmp/drawings-run.py && " +
      "docker exec -w /app -e PYTHONPATH=/app gpi-backend python /tmp/drawings-run.py 2>&1 | tail -40"
$script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
Write-Host $(if ($Send) { 'Listing the OneGamer drawings and sending them to the sales assistant ...' }
             else { 'Listing the OneGamer drawings (nothing is sent) ...' })
$out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
    --scripts $script --query 'value[0].message' -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the drawing listing on the VM.' }
Write-Host ((($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', '')
