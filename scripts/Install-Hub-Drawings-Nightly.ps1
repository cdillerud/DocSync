#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub VM: send the OneGamer supplier drawing list to the sales assistant every night (or remove that job).

.DESCRIPTION
  Installs a nightly job on the Hub VM (/etc/cron.d/gpi-drawings) that runs the same listing as
  Sync-Hub-Drawings.ps1 -Send inside the gpi-backend container, with the Hub's Graph token and intake settings. The
  reader is copied from the branch into /opt/gpi-jobs when you install, so the job keeps working through Hub
  rebuilds and does not change the Hub's code or settings. Each run's counts go to /var/log/gpi-drawings.log (last
  20 runs kept). Only names and links travel; no file is downloaded or changed. The sales assistant's status page
  shows when the list last arrived (catalog_intake.drawings.as_of).
  -Remove takes the job off again. Reaches the VM through Azure (az vm run-command, with your az login).
.EXAMPLE
  .\scripts\Install-Hub-Drawings-Nightly.ps1 -Confirmation 'INSTALL NIGHTLY DRAWINGS' -RunNow
  .\scripts\Install-Hub-Drawings-Nightly.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Confirmation = '',
    [switch]$Remove,
    [switch]$RunNow,                 # also run it once now (about 3 minutes) to see it work
    [string]$Time = '15 8',          # minute hour, UTC: 8:15 UTC = 3:15 AM Central (CDT) / 2:15 AM (CST)
    [string]$Branch = 'feature/hub-new-item-requests-live',
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'
if (-not $Remove -and $Confirmation -ne 'INSTALL NIGHTLY DRAWINGS') { throw "Add -Confirmation 'INSTALL NIGHTLY DRAWINGS' (or -Remove)." }
if ($Time -notmatch '^\d{1,2} \d{1,2}$') { throw "-Time is 'minute hour' in UTC, e.g. '15 8'." }

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

$runner = @'
import asyncio, json, sys, importlib.util
spec = importlib.util.spec_from_file_location("drawing_index_job", "/tmp/drawing_index.py")
di = importlib.util.module_from_spec(spec)
sys.modules["drawing_index_job"] = di
spec.loader.exec_module(di)
print(json.dumps(asyncio.run(di.run(send_it=True))))
'@
$job = @'
#!/bin/bash
# GPI Hub: nightly OneGamer drawing list -> sales assistant (installed by Install-Hub-Drawings-Nightly.ps1).
log=/var/log/gpi-drawings.log
out=$( { docker cp /opt/gpi-jobs/drawing_index.py gpi-backend:/tmp/drawing_index.py &&
         docker cp /opt/gpi-jobs/drawings-run.py gpi-backend:/tmp/drawings-run.py &&
         docker exec -w /app -e PYTHONPATH=/app gpi-backend python /tmp/drawings-run.py; } 2>&1 | tail -1 )
echo "$(date -u +%FT%TZ) $out" >> $log
tail -20 $log > $log.tmp && mv $log.tmp $log
'@
if ($Remove) {
    $sh = "rm -f /etc/cron.d/gpi-drawings && echo REMOVED"
} else {
    $sh = "set -e; mkdir -p /opt/gpi-jobs; cd /opt/gpi-hub; o=`$(stat -c %U .git); sudo -u `$o git fetch -q origin '$Branch'; " +
          "sudo -u `$o git show FETCH_HEAD:backend/services/drawing_index.py > /opt/gpi-jobs/drawing_index.py; " +
          "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($runner))) | base64 -d > /opt/gpi-jobs/drawings-run.py; " +
          "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($job))) | base64 -d > /opt/gpi-jobs/drawings-nightly.sh; " +
          "chmod 755 /opt/gpi-jobs/drawings-nightly.sh; " +
          "printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n$Time * * * root /opt/gpi-jobs/drawings-nightly.sh\n' > /etc/cron.d/gpi-drawings; " +
          "chmod 644 /etc/cron.d/gpi-drawings; echo INSTALLED; cat /etc/cron.d/gpi-drawings | tail -1; " +
          $(if ($RunNow) { "/opt/gpi-jobs/drawings-nightly.sh; " } else { "" }) +
          "echo LAST_RUNS; tail -3 /var/log/gpi-drawings.log 2>/dev/null || echo none"
}
$script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
$out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
    --scripts $script --query 'value[0].message' -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the command on the VM.' }
$text = (($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', ''
Write-Host $text
if ($Remove) { if ($text -notmatch 'REMOVED') { throw 'Could not remove the job.' }; Write-Host 'Nightly drawing job removed.'; return }
if ($text -notmatch 'INSTALLED') { throw 'The job was not installed; see the lines above.' }
Write-Host "Installed: the drawing list goes to the sales assistant every night at $Time (minute hour, UTC)." -ForegroundColor Green
Write-Host 'Check the next morning: the status page shows catalog_intake.drawings.as_of with that night''s time.'
