#requires -Version 7.0
<#
.SYNOPSIS
  Let GPI Hub's mail app read items@gamerpackaging.com and GamerSalesteam@gamerpackaging.com (Exchange Online).

.DESCRIPTION
  Step 1 (anyone with az access to the Hub VM): asks the Hub's mail app, from the VM, to read one message header in
  each mailbox and reports OK / ACCESS_DENIED / NOT_FOUND per mailbox. Prints the app's (client) ID, which is not a
  secret. Nothing is changed. Stops here with -CheckOnly, or when every mailbox is already OK.

  Step 2 (an Exchange admin; signs in to Exchange Online): for each mailbox that isn't OK it shows what the address
  is (a user or shared mailbox can be read; a distribution group has no mailbox of its own) and the app's
  application access policies. When a policy limits the app to the members of a mail-enabled security group, the
  mailbox is added to that group (asks first unless -Confirmation 'GRANT HUB MAILBOX ACCESS'). It never removes a
  policy, never widens the app to all mailboxes, and changes nothing else. Then it tests again.
  Read-only access: the app has Mail.Read; it cannot send, move or delete mail.
.EXAMPLE
  .\scripts\Grant-Hub-Mailbox-Access.ps1 -CheckOnly
  .\scripts\Grant-Hub-Mailbox-Access.ps1
  .\scripts\Grant-Hub-Mailbox-Access.ps1 -Confirmation 'GRANT HUB MAILBOX ACCESS'
#>
[CmdletBinding()]
param(
    [string[]]$Mailbox = @('items@gamerpackaging.com', 'gamersalesteam@gamerpackaging.com'),
    [switch]$CheckOnly,
    [string]$Confirmation = '',
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'

# ---- Step 1: what the Hub's mail app can read today (from the VM) ----------------------------------------------
$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }

function Test-FromVm {
    $list = ($Mailbox | ForEach-Object { $_.Trim().ToLower() }) -join ','
    $py = @"
import asyncio, os, httpx
from services.config_service import get_email_token
async def main():
    print('APP_ID=' + (os.environ.get('EMAIL_CLIENT_ID') or os.environ.get('GRAPH_CLIENT_ID') or ''))
    token = await get_email_token()
    async with httpx.AsyncClient(timeout=60) as c:
        for m in '$list'.split(','):
            r = await c.get(f'https://graph.microsoft.com/v1.0/users/{m}/messages?`$top=1&`$select=id', headers={'Authorization': f'Bearer {token}'})
            state = 'OK' if r.status_code == 200 else 'ACCESS_DENIED' if r.status_code in (401, 403) else 'NOT_FOUND' if r.status_code == 404 else f'HTTP_{r.status_code}'
            print(f'MAILBOX {m} {state}')
asyncio.run(main())
"@
    $pyB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($py))
    $sh = "echo $pyB64 | base64 -d > /tmp/mbx-check.py && docker cp /tmp/mbx-check.py gpi-backend:/tmp/mbx-check.py && docker exec -w /app -e PYTHONPATH=/app gpi-backend python /tmp/mbx-check.py 2>&1 | tail -10"
    $script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
    $out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
        --scripts $script --query 'value[0].message' -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the check on the Hub VM.' }
    $text = (($out -join "`n") -split '\[stderr\]')[0]
    $result = @{ AppId = ''; Mailboxes = [ordered]@{} }
    foreach ($line in ($text -split "`n")) {
        if ($line -match 'APP_ID=(\S*)') { $result.AppId = $Matches[1] }
        if ($line -match 'MAILBOX (\S+) (\S+)') { $result.Mailboxes[$Matches[1]] = $Matches[2] }
    }
    return $result
}

Write-Host "Hub VM: $($vm.name). Checking what the Hub's mail app can read ..."
$check = Test-FromVm
if (-not $check.AppId) { throw 'Could not read the Hub mail app ID from the VM (EMAIL_CLIENT_ID / GRAPH_CLIENT_ID).' }
Write-Host "Hub mail app (client) ID: $($check.AppId)"
foreach ($m in $check.Mailboxes.Keys) {
    $state = $check.Mailboxes[$m]
    Write-Host ("  {0,-40} {1}" -f $m, $state) -ForegroundColor $(if ($state -eq 'OK') { 'Green' } else { 'Yellow' })
}
$blocked = @($check.Mailboxes.Keys | Where-Object { $check.Mailboxes[$_] -ne 'OK' })
if (-not $blocked) { Write-Host 'Every mailbox is readable. Nothing to change.' -ForegroundColor Green; return }
if ($CheckOnly) { Write-Host 'Check only: nothing was changed. An Exchange admin runs this again without -CheckOnly.'; return }

# ---- Step 2: Exchange Online (an Exchange admin) ---------------------------------------------------------------
if (-not (Get-Module -ListAvailable ExchangeOnlineManagement)) {
    Write-Host 'Installing the ExchangeOnlineManagement module for this user ...'
    Install-Module ExchangeOnlineManagement -Scope CurrentUser -Force -AllowClobber
}
Import-Module ExchangeOnlineManagement
Connect-ExchangeOnline -ShowBanner:$false
try {
    $policies = @(Get-ApplicationAccessPolicy | Where-Object { $_.AppId -eq $check.AppId })
    if ($policies) {
        Write-Host "Application access policies for the Hub app:"
        $policies | ForEach-Object { Write-Host ("  {0}: {1} members of {2}" -f $_.Identity, $_.AccessRight, $_.ScopeName) }
    } else {
        Write-Host 'No application access policy names the Hub app.'
    }
    $roleAssignments = @()
    try { $roleAssignments = @(Get-ManagementRoleAssignment -RoleAssignee $check.AppId -ErrorAction Stop) } catch { }
    if ($roleAssignments) {
        Write-Host 'The Hub app also has Exchange RBAC role assignments (newer "RBAC for Applications"):'
        $roleAssignments | ForEach-Object { Write-Host ("  {0} scope {1}" -f $_.Role, $_.CustomResourceScope) }
    }
    $restrict = $policies | Where-Object { $_.AccessRight -eq 'RestrictAccess' } | Select-Object -First 1
    foreach ($m in $blocked) {
        Write-Host ''
        $recipient = Get-Recipient -Identity $m -ErrorAction SilentlyContinue
        if (-not $recipient) { Write-Host "${m}: no such address in Exchange Online." -ForegroundColor Red; continue }
        Write-Host "${m}: $($recipient.RecipientTypeDetails) (primary $($recipient.PrimarySmtpAddress); object $($recipient.ExternalDirectoryObjectId))"
        if ($check.Mailboxes[$m] -eq 'NOT_FOUND' -and $recipient.RecipientTypeDetails -match 'Mailbox' -and
            $recipient.RecipientTypeDetails -ne 'GroupMailbox') {
            $mbxInfo = Get-EXOMailbox -Identity $m -Properties UserPrincipalName -ErrorAction SilentlyContinue
            Write-Host ("  A mailbox, but Graph doesn't find it by this address (it's an alias). Its sign-in name is {0}: " +
                        "run the price-list job with -Mailbox {0} (or -Mailbox {1}).") -f $mbxInfo.UserPrincipalName,
                        $recipient.ExternalDirectoryObjectId -ForegroundColor Yellow
            continue
        }
        if ($recipient.RecipientTypeDetails -eq 'GroupMailbox') {
            Write-Host ("  A Microsoft 365 group (a Team or group inbox). Its mail is read through the group, not as a user mailbox; " +
                        "tell Claude 'GamerSalesteam is an M365 group' so the job reads it that way (needs Group.Read.All for the Hub app).") `
                -ForegroundColor Yellow
            continue
        }
        if ($recipient.RecipientTypeDetails -notmatch 'Mailbox') {
            $members = @(Get-DistributionGroupMember -Identity $m -ResultSize 50 -ErrorAction SilentlyContinue)
            if ($members) { Write-Host ("  Members: " + (($members | ForEach-Object { $_.PrimarySmtpAddress }) -join ', ')) }
            Write-Host ("  This is a {0}, not a mailbox: mail to it lands in its members' inboxes, so there is nothing for the app to read. " +
                        "Make it a shared mailbox (or add a shared mailbox as a member and point the job at that), then run this again.") `
                -f $recipient.RecipientTypeDetails -ForegroundColor Yellow
            continue
        }
        $test = Test-ApplicationAccessPolicy -Identity $m -AppId $check.AppId
        Write-Host "  Exchange says: $($test.AccessCheckResult)"
        if ($test.AccessCheckResult -eq 'Granted') {
            Write-Host '  Exchange already allows it; the block is elsewhere (RBAC for Applications, or the app lacks Mail.Read). See the list above.' -ForegroundColor Yellow
            continue
        }
        if (-not $restrict) {
            Write-Host '  Access is denied but no RestrictAccess policy names a group to add to. An admin should check the policies above by hand.' -ForegroundColor Yellow
            continue
        }
        $group = $restrict.ScopeName
        if ($Confirmation -ne 'GRANT HUB MAILBOX ACCESS') {
            $answer = Read-Host "  Add $m to the group '$group' that the Hub app may read? (y/N)"
            if ($answer -notmatch '^(y|yes)$') { Write-Host '  Skipped.'; continue }
        }
        Add-DistributionGroupMember -Identity $group -Member $m -BypassSecurityGroupManagerCheck
        Write-Host "  Added $m to $group." -ForegroundColor Green
    }
} finally {
    Disconnect-ExchangeOnline -Confirm:$false | Out-Null
}

Write-Host ''
Write-Host 'Exchange can take up to an hour to apply a group change. Checking again from the VM now (run with -CheckOnly later if still denied) ...'
$again = Test-FromVm
foreach ($m in $again.Mailboxes.Keys) {
    $state = $again.Mailboxes[$m]
    Write-Host ("  {0,-40} {1}" -f $m, $state) -ForegroundColor $(if ($state -eq 'OK') { 'Green' } else { 'Yellow' })
}
