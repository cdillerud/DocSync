#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub VM: every night, send new supplier dunnage reports from OneGamer to the assistants' dunnage report
  (or remove that job).

.DESCRIPTION
  Reads the files (PDF, xlsx) in each supplier's dunnage folders on OneGamer (General/Manufacturers - Vendors/
  <supplier>/<...Dunnage...>/**, e.g. Ball/Dunnage/Dunnage Reports, Anchor Glass/Dunnage/Dunnage Reports-GAMER-235,
  CanPack/Dunnage/Dunnage Reports) modified since -Since (default: 1 January of last year), and sends each one not
  sent before, or changed since, to /api/v70/catalog/intake/dunnage-reports. The service keeps the ones it can read
  (Ball tracking reports, Anchor dunnage statements, CanPack returns logs) and ignores the rest (SOPs, BOLs).
  Read only on SharePoint. The files already sent are remembered in /opt/gpi-jobs/dunnage-reports-sent.json, so a night
  only sends what is new. Each run's counts go to /var/log/gpi-dunnage-reports.log (last 30 runs); no quantities.
  The reader is copied from the branch into /opt/gpi-jobs when you install: no Hub code or setting changes.

  -Preview lists what it would send and sends nothing (no confirmation needed).
  -RunNow also runs it once now (the first run sends the backlog: a few minutes per hundred files).
  -Resend forgets what was sent and sends everything again (with -RunNow). -Remove takes the job off.
.EXAMPLE
  .\scripts\Install-Hub-Dunnage-Reports-Nightly.ps1 -Preview
  .\scripts\Install-Hub-Dunnage-Reports-Nightly.ps1 -Confirmation 'INSTALL NIGHTLY DUNNAGE REPORTS' -RunNow
  .\scripts\Install-Hub-Dunnage-Reports-Nightly.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Confirmation = '',
    [switch]$Preview,
    [switch]$RunNow,
    [switch]$Resend,
    [switch]$Remove,
    [string]$Since = '',             # YYYY-MM-DD; default 1 January of last year
    [string]$Time = '55 8',          # minute hour, UTC: 8:55 UTC = 3:55 AM Central (CDT), after the price-list job
    [string]$Branch = 'feature/hub-new-item-requests-live',
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'
if (-not ($Remove -or $Preview) -and $Confirmation -ne 'INSTALL NIGHTLY DUNNAGE REPORTS') {
    throw "Add -Confirmation 'INSTALL NIGHTLY DUNNAGE REPORTS' (or -Preview, or -Remove)."
}
if ($Since -and $Since -notmatch '^\d{4}-\d{2}-\d{2}$') { throw '-Since is YYYY-MM-DD.' }
if ($Time -notmatch '^\d{1,2} \d{1,2}$') { throw "-Time is 'minute hour' in UTC, e.g. '35 8'." }

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

function Invoke-OnVm([string]$sh) {
    $script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
    $out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
        --scripts $script --query 'value[0].message' -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the command on the VM.' }
    return ((($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', '').Trim()
}

if ($Remove) {
    $text = Invoke-OnVm 'rm -f /etc/cron.d/gpi-dunnage-reports && echo REMOVED'
    Write-Host $text
    if ($text -notmatch 'REMOVED') { throw 'Could not remove the job.' }
    Write-Host 'Nightly dunnage-report job removed (the list of files already sent is kept in /opt/gpi-jobs).'
    return
}

# The runner: sends (or previews) inside gpi-backend; the sent-files list is copied in and back out around it.
$runner = @"
import asyncio, json, os, sys, importlib.util
spec = importlib.util.spec_from_file_location("dunnage_index_job", "/tmp/dunnage_list_index.py")
pl = importlib.util.module_from_spec(spec)
sys.modules["dunnage_index_job"] = pl
spec.loader.exec_module(pl)
since = os.environ.get("GPI_PRICE_LIST_SINCE", "")
resend = os.environ.get("GPI_PRICE_LIST_RESEND") == "1"
send_it = os.environ.get("GPI_PRICE_LIST_PREVIEW") != "1"
print(json.dumps(asyncio.run(pl.run(send_it=send_it, since=since, resend=resend, state_path="/tmp/dunnage-reports-sent.json", kind="dunnage"))))
"@
$job = @'
#!/bin/bash
# GPI Hub: nightly OneGamer supplier dunnage reports -> assistants' dunnage report
# (installed by Install-Hub-Dunnage-Reports-Nightly.ps1). Env: GPI_PRICE_LIST_SINCE, GPI_PRICE_LIST_RESEND, GPI_PRICE_LIST_PREVIEW.
log=/var/log/gpi-dunnage-reports.log
state=/opt/gpi-jobs/dunnage-reports-sent.json
[ -f $state ] || echo '{}' > $state
out=$( { docker cp /opt/gpi-jobs/price_list_index.py gpi-backend:/tmp/dunnage_list_index.py &&
         docker cp /opt/gpi-jobs/dunnage-reports-run.py gpi-backend:/tmp/dunnage-reports-run.py &&
         docker cp $state gpi-backend:/tmp/dunnage-reports-sent.json &&
         docker exec -w /app -e PYTHONPATH=/app -e GPI_PRICE_LIST_SINCE="$GPI_PRICE_LIST_SINCE" \
             -e GPI_PRICE_LIST_RESEND="$GPI_PRICE_LIST_RESEND" -e GPI_PRICE_LIST_PREVIEW="$GPI_PRICE_LIST_PREVIEW" \
             gpi-backend python /tmp/dunnage-reports-run.py; } 2>&1 | tail -1 )
if [ "$GPI_PRICE_LIST_PREVIEW" != "1" ]; then
  docker cp gpi-backend:/tmp/dunnage-reports-sent.json $state.new 2>/dev/null && mv $state.new $state
  echo "$(date -u +%FT%TZ) $out" >> $log
  tail -30 $log > $log.tmp && mv $log.tmp $log
fi
echo "$out"
'@
$envs = "GPI_PRICE_LIST_SINCE='$Since' GPI_PRICE_LIST_RESEND='$(if ($Resend) { 1 } else { 0 })' GPI_PRICE_LIST_PREVIEW='$(if ($Preview) { 1 } else { 0 })'"
$install = "set -e; mkdir -p /opt/gpi-jobs; cd /opt/gpi-hub; o=`$(stat -c %U .git); sudo -u `$o git fetch -q origin '$Branch'; " +
           "sudo -u `$o git show FETCH_HEAD:backend/services/price_list_index.py > /opt/gpi-jobs/price_list_index.py; " +
           "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($runner))) | base64 -d > /opt/gpi-jobs/dunnage-reports-run.py; " +
           "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($job))) | base64 -d > /opt/gpi-jobs/dunnage-reports-nightly.sh; " +
           "chmod 755 /opt/gpi-jobs/dunnage-reports-nightly.sh; "
if ($Preview) {
    $sh = $install + "echo PREVIEW; env $envs /opt/gpi-jobs/dunnage-reports-nightly.sh"
} else {
    $sh = $install +
          "printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n$Time * * * root /opt/gpi-jobs/dunnage-reports-nightly.sh\n' > /etc/cron.d/gpi-dunnage-reports; " +
          "chmod 644 /etc/cron.d/gpi-dunnage-reports; echo INSTALLED; tail -1 /etc/cron.d/gpi-dunnage-reports; " +
          $(if ($RunNow) { "echo RUN_NOW; env $envs /opt/gpi-jobs/dunnage-reports-nightly.sh; " } else { "" }) +
          "echo LAST_RUNS; tail -3 /var/log/gpi-dunnage-reports.log 2>/dev/null | cut -c1-160 || echo none; " +
          "test -f /etc/cron.d/gpi-dunnage-reports && echo INSTALLED"  # last: Azure returns only the end of long output
}
Write-Host $(if ($Preview) { 'Listing the dunnage files on OneGamer (nothing is sent) ...' } elseif ($RunNow) { 'Installing and running once now (the first run can take several minutes) ...' } else { 'Installing ...' })
$text = Invoke-OnVm $sh
$json = ($text -split "`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
if ($json) {
    try { $r = $json | ConvertFrom-Json } catch { $r = $null }
    if ($r) {
        Write-Host ''
        Write-Host ("Status: {0}   files in dunnage folders since {1}: {2}   new or changed: {3}" -f $r.status, $r.since, $r.pdfs, $r.new_or_changed)
        if ($r.by_supplier) { $r.by_supplier.PSObject.Properties | ForEach-Object { Write-Host ("  {0,-40} {1}" -f $_.Name, $_.Value) } }
        if ($r.would_send) { Write-Host 'Would send (newest 25):'; $r.would_send | ForEach-Object { Write-Host "  $_" } }
        if ($null -ne $r.files_read) {
            Write-Host ("Sent: {0} read as dunnage reports, {2} not a report the service reads (SOPs, BOLs), {3} failed." -f `
                $r.files_read, $r.lists_kept, $r.not_a_price_list_it_reads, $r.failed)
            if ($r.unread_examples) { Write-Host 'Not read (examples):'; $r.unread_examples | ForEach-Object { Write-Host "  $_" } }
        }
        if ($r.reason) { Write-Host "Reason: $($r.reason)" -ForegroundColor Yellow }
    }
} else {
    Write-Host $text
}
if ($Preview) { Write-Host ''; Write-Host 'Preview only: nothing was sent and no job was installed.'; return }
if ($text -notmatch 'INSTALLED') { Write-Host $text; throw 'The job was not installed; see the lines above.' }
Write-Host ''
Write-Host "Installed: new supplier dunnage reports on OneGamer go to the dunnage report every night at $Time (minute hour, UTC)." -ForegroundColor Green
Write-Host 'The status page shows the counts under catalog_intake.supplier_dunnage.'
