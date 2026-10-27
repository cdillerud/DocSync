#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub VM: every hour, send new supplier price letters / price books from GamerSalesteam@ to the sales assistant's
  price-list history (or remove that job).

.DESCRIPTION
  Installs /etc/cron.d/gpi-price-lists on the Hub VM. Each run (inside gpi-backend, with the Hub's mail app and intake
  settings) reads the mailbox's messages with attachments from the last 2 days, read only, and sends each PDF not
  sent before to /api/v70/catalog/intake/price-lists. The service keeps Berry letters and Amcor price books and
  ignores other PDFs. Attachments already sent are remembered in /opt/gpi-jobs/price-lists-seen.json. Counts only in
  /var/log/gpi-price-lists.log (last 50 runs); no subjects, senders or file names are logged.
  The reader is copied from the branch into /opt/gpi-jobs when you install: no Hub code, setting or mail processing
  changes. Needs the Hub's mail app to be allowed to read the mailbox (Grant-Hub-Mailbox-Access.ps1).
  -RunNow -Days 365 also runs it once now over that many days (a backfill). -Check reads the mailbox and counts PDFs
  without sending anything. -Remove takes the job off.
.EXAMPLE
  .\scripts\Install-Hub-Price-Lists-Job.ps1 -Check -Days 30
  .\scripts\Install-Hub-Price-Lists-Job.ps1 -Confirmation 'INSTALL PRICE LIST JOB' -RunNow -Days 365
  .\scripts\Install-Hub-Price-Lists-Job.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Confirmation = '',
    [switch]$Check,
    [switch]$RunNow,
    [int]$Days = 2,
    [switch]$Remove,
    [string]$Mailbox = 'gamersalesteam@gamerpackaging.com',
    [string]$Branch = 'feature/hub-new-item-requests-live',
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'
if (-not ($Remove -or $Check) -and $Confirmation -ne 'INSTALL PRICE LIST JOB') {
    throw "Add -Confirmation 'INSTALL PRICE LIST JOB' (or -Check, or -Remove)."
}
if ($Days -lt 1 -or $Days -gt 730) { throw '-Days is 1 to 730.' }
if ($Mailbox -notmatch '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$') { throw '-Mailbox is an email address.' }

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

$runner = @'
import asyncio, json, os, sys, importlib.util
spec = importlib.util.spec_from_file_location("price_list_mail_job", "/tmp/price_list_mail.py")
m = importlib.util.module_from_spec(spec)
sys.modules["price_list_mail_job"] = m
spec.loader.exec_module(m)
days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
dry = len(sys.argv) > 2 and sys.argv[2] == "dry"
print(json.dumps(asyncio.run(m.run(days=days, state_path="/tmp/price-lists-seen.json", dry_run=dry))))
'@
$job = @'
#!/bin/bash
# GPI Hub: hourly GamerSalesteam@ price letters -> sales assistant (installed by Install-Hub-Price-Lists-Job.ps1).
# Usage: price-lists-job.sh [days] [dry]
days=${1:-2}; mode=${2:-send}
log=/var/log/gpi-price-lists.log
state=/opt/gpi-jobs/price-lists-seen.json
[ -f $state ] || echo '{}' > $state
mbx=$(cat /opt/gpi-jobs/price-lists-mailbox 2>/dev/null || echo gamersalesteam@gamerpackaging.com)
out=$( { docker cp /opt/gpi-jobs/price_list_mail.py gpi-backend:/tmp/price_list_mail.py &&
         docker cp /opt/gpi-jobs/price-lists-run.py gpi-backend:/tmp/price-lists-run.py &&
         docker cp $state gpi-backend:/tmp/price-lists-seen.json &&
         docker exec -w /app -e PYTHONPATH=/app -e PRICE_LIST_MAILBOX=$mbx gpi-backend python /tmp/price-lists-run.py $days $mode &&
         { [ "$mode" = dry ] || docker cp gpi-backend:/tmp/price-lists-seen.json $state; }; } 2>&1 | tail -1 )
[ "$mode" = dry ] || { echo "$(date -u +%FT%TZ) $out" >> $log; tail -50 $log > $log.tmp && mv $log.tmp $log; }
echo "$out"
'@
$copy = "mkdir -p /opt/gpi-jobs; cd /opt/gpi-hub; o=`$(stat -c %U .git); sudo -u `$o git fetch -q origin '$Branch'; " +
        "sudo -u `$o git show FETCH_HEAD:backend/services/price_list_mail.py > /opt/gpi-jobs/price_list_mail.py; " +
        "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($runner))) | base64 -d > /opt/gpi-jobs/price-lists-run.py; " +
        "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($job))) | base64 -d > /opt/gpi-jobs/price-lists-job.sh; " +
        "chmod 755 /opt/gpi-jobs/price-lists-job.sh; echo '$Mailbox' > /opt/gpi-jobs/price-lists-mailbox; "
if ($Remove) {
    $sh = "rm -f /etc/cron.d/gpi-price-lists && echo REMOVED"
} elseif ($Check) {
    $sh = "set -e; $copy echo CHECK; /opt/gpi-jobs/price-lists-job.sh $Days dry"
} else {
    $sh = "set -e; $copy" +
          "printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n25 * * * * root /opt/gpi-jobs/price-lists-job.sh 2\n' > /etc/cron.d/gpi-price-lists; " +
          "chmod 644 /etc/cron.d/gpi-price-lists; echo INSTALLED; tail -1 /etc/cron.d/gpi-price-lists; " +
          $(if ($RunNow) { "echo RUN_NOW; /opt/gpi-jobs/price-lists-job.sh $Days; " } else { "" }) + "true"
}
$script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
Write-Host $(if ($Check) { "Reading $Mailbox (last $Days days) without sending anything ..." }
             elseif ($Remove) { 'Removing the job ...' } else { 'Installing the hourly job ...' })
$out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
    --scripts $script --query 'value[0].message' -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the command on the VM.' }
$text = (($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', ''
Write-Host $text
if ($text -match 'ACCESS_DENIED') {
    Write-Host "The Hub's mail app can't read $Mailbox yet: an Exchange admin runs .\scripts\Grant-Hub-Mailbox-Access.ps1." -ForegroundColor Yellow
}
if ($Remove) { if ($text -notmatch 'REMOVED') { throw 'Could not remove the job.' }; Write-Host 'Price-list job removed.'; return }
if ($Check) { return }
if ($text -notmatch 'INSTALLED') { throw 'The job was not installed; see the lines above.' }
Write-Host "Installed: every hour at :25, new PDFs in $Mailbox go to the price-list history." -ForegroundColor Green
Write-Host 'The sales assistant''s status page shows the count under catalog_intake.price_lists.'
