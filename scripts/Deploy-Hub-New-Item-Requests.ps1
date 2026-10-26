#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub: check, then deploy, the New Item Requests reader (items@gamerpackaging.com -> Packaging Catalog).

.DESCRIPTION
  Without -Deploy (the default) it only looks: which branch and commit the Hub VM runs (/opt/gpi-hub), whether that
  checkout has uncommitted changes, whether feature/hub-new-item-requests can be applied as a fast-forward (so
  nothing the VM runs today is dropped), and whether the catalog settings are in backend/.env. Nothing is changed.

  With -Deploy -Confirmation 'DEPLOY HUB NEW ITEM REQUESTS' it fast-forwards the checkout, adds
  NEW_ITEM_REQUESTS_ENABLED=true and NEW_ITEM_REQUESTS_DRY_RUN=true to backend/.env (dry run: forms are read and
  recorded, nothing is sent), and rebuilds the backend container. It stops without changing anything when the
  checkout isn't a clean git checkout or the branch isn't a fast-forward.

  The intake URL and key: the catalog forward settings in backend/.env when they are there; otherwise the deploy
  adds NEW_ITEM_REQUESTS_URL and copies the intake key (GPI_CATALOG_INTAKE_KEY on the Commercial AI web app) to
  NEW_ITEM_REQUESTS_KEY over SSH, so it is never on a command line, in a log or on screen.

  Reaches the VM through Azure (az vm run-command, with your az login); the key alone goes over SSH.
.EXAMPLE
  .\scripts\Deploy-Hub-New-Item-Requests.ps1
  .\scripts\Deploy-Hub-New-Item-Requests.ps1 -Deploy -Confirmation 'DEPLOY HUB NEW ITEM REQUESTS'
#>
[CmdletBinding()]
param(
    [switch]$Deploy,
    [string]$Confirmation = '',
    [string]$VmHost = 'azureuser@4.204.41.190',
    [string]$Branch = 'feature/hub-new-item-requests-live',
    [string]$IntakeUrl = 'https://gpi-commercial-ai-v62-uat-4e0833.azurewebsites.net/api/v70/catalog/intake/new-items',
    [string]$HubDir = '/opt/gpi-hub'
)
$ErrorActionPreference = 'Stop'
if ($Deploy -and $Confirmation -ne 'DEPLOY HUB NEW ITEM REQUESTS') {
    throw "To deploy, add -Confirmation 'DEPLOY HUB NEW ITEM REQUESTS'."
}

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

function Invoke-OnVm([string]$Script) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
        --scripts "echo $b64 | base64 -d | sudo bash" --query 'value[0].message' -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the command on the VM (needs Virtual Machine Contributor on it).' }
    return (($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', ''
}

$check = @"
set -u
cd '$HubDir' 2>/dev/null || { echo 'STATE=NO_DIR'; exit 0; }
if [ ! -d .git ]; then echo 'STATE=NOT_GIT'; exit 0; fi
owner=`$(stat -c %U .git)
g() { sudo -u "`$owner" git "`$@"; }
echo "OWNER=`$owner"
echo "BRANCH=`$(g rev-parse --abbrev-ref HEAD)"
echo "HEAD=`$(g log -1 --format='%h %s' | cut -c1-90)"
echo "DIRTY=`$(g status --porcelain --untracked-files=no | wc -l)"
if g fetch -q origin '$Branch' 2>/tmp/nir-fetch.txt; then
  echo "TARGET=`$(g log -1 --format='%h %s' FETCH_HEAD | cut -c1-90)"
  if g merge-base --is-ancestor HEAD FETCH_HEAD; then echo 'FASTFORWARD=yes'; else echo 'FASTFORWARD=no'; fi
  echo "BEHIND=`$(g rev-list --count HEAD..FETCH_HEAD)"
else
  echo "FETCH=failed: `$(tail -1 /tmp/nir-fetch.txt)"
fi
for k in CATALOG_FORWARD_URL CATALOG_FORWARD_KEY NEW_ITEM_REQUESTS_URL NEW_ITEM_REQUESTS_KEY NEW_ITEM_REQUESTS_ENABLED NEW_ITEM_REQUESTS_DRY_RUN; do
  if grep -q "^`$k=." backend/.env 2>/dev/null; then echo "ENV_`$k=set"; else echo "ENV_`$k=missing"; fi
done
"@
$state = Invoke-OnVm $check
$info = @{}
foreach ($line in ($state -split "`n")) { if ($line -match '^\s*([A-Z_]+)=(.*)$') { $info[$Matches[1]] = $Matches[2].Trim() } }
Write-Host ''
Write-Host "Running now : $($info.BRANCH) @ $($info.HEAD)"
Write-Host "Uncommitted : $($info.DIRTY) changed tracked files"
if ($info.FETCH) { Write-Host "Fetch       : $($info.FETCH)" -ForegroundColor Red }
else {
    Write-Host "New code    : $Branch @ $($info.TARGET) ($($info.BEHIND) commits ahead)"
    Write-Host "Fast-forward: $($info.FASTFORWARD)"
}
foreach ($k in 'CATALOG_FORWARD_URL', 'CATALOG_FORWARD_KEY', 'NEW_ITEM_REQUESTS_URL', 'NEW_ITEM_REQUESTS_KEY', 'NEW_ITEM_REQUESTS_ENABLED', 'NEW_ITEM_REQUESTS_DRY_RUN') {
    Write-Host ("{0,-26}: {1}" -f $k, $info["ENV_$k"])
}
if ($info.STATE) { throw "The Hub folder $HubDir is $($info.STATE); deploy by hand (DEPLOYMENT.md)." }

$problems = @()
if ($info.FETCH) { $problems += 'the VM could not fetch the branch from GitHub' }
if ($info.FASTFORWARD -ne 'yes') { $problems += "the VM's branch has commits the new branch doesn't (not a fast-forward); merge them first" }
if ([int]($info.DIRTY) -gt 0) { $problems += 'the VM checkout has uncommitted changes' }
$needKey = $info.ENV_CATALOG_FORWARD_KEY -ne 'set' -and $info.ENV_NEW_ITEM_REQUESTS_KEY -ne 'set'
$needUrl = $info.ENV_CATALOG_FORWARD_URL -ne 'set' -and $info.ENV_NEW_ITEM_REQUESTS_URL -ne 'set'
if ($needKey) { Write-Host 'Intake key  : not on the VM yet; the deploy copies it from the web app over SSH (never shown)' }
if (-not $Deploy) {
    Write-Host ''
    if ($problems) { Write-Host ('Not ready to deploy: ' + ($problems -join '; ') + '.') -ForegroundColor Yellow }
    else { Write-Host "Ready. Deploy with: -Deploy -Confirmation 'DEPLOY HUB NEW ITEM REQUESTS'" -ForegroundColor Green }
    Write-Host 'Nothing was changed.'
    return
}
if ($problems) { throw ('Not deployed: ' + ($problems -join '; ') + '. Nothing was changed.') }

if ($needKey) {
    # The intake key goes from the web app's settings to the VM over SSH (stdin): never on a command line, in a
    # log, in Azure's run-command history or on screen.
    $key = az webapp config appsettings list -g rg-gpi-commercial-ai-v62-uat -n gpi-commercial-ai-v62-uat-4e0833 `
        --subscription 4e083304-514c-4751-855e-c38a1740a924 --query "[?name=='GPI_CATALOG_INTAKE_KEY'].value | [0]" -o tsv 2>$null
    if (-not $key) {
        $env:AZURE_CONFIG_DIR = Join-Path $env:LOCALAPPDATA 'GPI\AccountingDeployment\AzureCLI'
        $key = az webapp config appsettings list -g rg-gpi-commercial-ai-v62-uat -n gpi-commercial-ai-v62-uat-4e0833 `
            --subscription 4e083304-514c-4751-855e-c38a1740a924 --query "[?name=='GPI_CATALOG_INTAKE_KEY'].value | [0]" -o tsv 2>$null
        Remove-Item Env:\AZURE_CONFIG_DIR -ErrorAction SilentlyContinue
    }
    if (-not $key) { throw 'Could not read GPI_CATALOG_INTAKE_KEY from the Commercial AI web app (az login to that subscription). Nothing was changed.' }
    $remote = 'sudo bash -c ''read -r k; k=$(printf %s "$k" | tr -d "\r"); f={0}/backend/.env; [ -n "$(tail -c1 $f)" ] && echo >> $f; grep -q ^NEW_ITEM_REQUESTS_KEY= $f || echo "NEW_ITEM_REQUESTS_KEY=$k" >> $f; echo KEY_SET''' -f $HubDir
    $answer = $key | ssh -o BatchMode=yes -o ConnectTimeout=15 $VmHost $remote 2>$null
    $key = $null
    if ("$answer" -notmatch 'KEY_SET') { throw "Could not reach $VmHost over SSH to store the intake key (the deploy needs the same SSH access you use to log in to the VM). Nothing was deployed." }
    Write-Host 'Intake key stored on the VM.'
}
$urlLine = if ($needUrl) { "NEW_ITEM_REQUESTS_URL=$IntakeUrl" } else { '' }

$apply = @"
set -e
cd '$HubDir'
owner=`$(stat -c %U .git)
g() { sudo -u "`$owner" git "`$@"; }
g fetch -q origin '$Branch'
g merge --ff-only -q FETCH_HEAD
[ -n "`$(tail -c1 backend/.env)" ] && echo >> backend/.env
for kv in NEW_ITEM_REQUESTS_ENABLED=true NEW_ITEM_REQUESTS_DRY_RUN=true $urlLine; do
  k=`${kv%%=*}
  if ! grep -q "^`$k=" backend/.env; then echo "`$kv" >> backend/.env; fi
done
docker compose up -d --build backend >/tmp/nir-build.txt 2>&1 || { tail -5 /tmp/nir-build.txt; exit 1; }
echo "DEPLOYED=`$(g log -1 --format='%h %s' | cut -c1-90)"
docker compose ps backend --format '{{.Name}} {{.Status}}' 2>/dev/null | head -2
"@
Write-Host ''
Write-Host 'Deploying (fast-forward, dry run on, backend rebuild: a few minutes) ...'
$result = Invoke-OnVm $apply
Write-Host $result
if ($result -notmatch 'DEPLOYED=') { throw 'The deploy did not finish; see the lines above.' }
Write-Host ''
Write-Host 'Deployed with NEW_ITEM_REQUESTS_DRY_RUN=true: request forms are read and recorded, nothing is sent yet.' -ForegroundColor Green
Write-Host 'Check: GET /api/admin/new-item-requests/status (admin). Backfill preview: POST /api/admin/new-item-requests/backfill?dry_run=true'
