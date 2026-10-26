#requires -Version 7.0
<#
.SYNOPSIS
  GPI Hub: dry-run backfill of New Item Template forms the Hub already holds (nothing is sent).

.DESCRIPTION
  Runs the New Item Requests reader inside the Hub's backend container over the workbooks received in the last
  -Days days whose file name looks like a new item request, in dry run: each form is read and its decision recorded
  on its Hub record, nothing goes to the catalog. Prints counts only: forms found, forms that are request forms,
  items read, and the kinds of problems found on the forms (no file names, customers or item numbers).

  Reaches the VM through Azure (az vm run-command, with your az login).
.EXAMPLE
  .\scripts\Preview-Hub-New-Item-Requests.ps1 -Days 120
#>
[CmdletBinding()]
param(
    [int]$Days = 120,
    [int]$Limit = 1000,
    [string]$VmHost = 'azureuser@4.204.41.190'
)
$ErrorActionPreference = 'Stop'

$ip = ($VmHost -split '@')[-1]
$vm = $null
foreach ($sub in @(az account list --query '[].id' -o tsv)) {
    $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
}
if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login' first." }
Write-Host "Hub VM: $($vm.name) ($($vm.group))"

$py = @"
import asyncio, json, os, re, collections
from motor.motor_asyncio import AsyncIOMotorClient
import deps
from services import new_item_requests as n

KINDS = [("description too long", r"^Description is"), ("item no. too long", r"^Item No\. '.*' is \d+ characters"),
         ("classification blank", r"Item Classification is blank"), ("same item on two tabs", r"on two tabs"),
         ("cell shows an Excel error", r"shows #"), ("no item filled in", r"no tab has an Item No"),
         ("workbook unreadable", r"could not open")]

async def main():
    deps.set_db(AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "gpi_document_hub")])
    out = await n.backfill(days=$Days, limit=$Limit, dry_run=True)
    db = deps.get_db()
    since = out.get("since", "")
    rows = await db.hub_documents.find({"new_item_request.decided_utc": {"`$gte": since}, "created_utc": {"`$gte": since}},
                                       {"_id": 0, "new_item_request": 1}).to_list(5000)
    status = collections.Counter(r["new_item_request"].get("status") for r in rows)
    reasons = collections.Counter(r["new_item_request"].get("reason") for r in rows
                                  if r["new_item_request"].get("status") != "dry_run")
    forms = [r["new_item_request"] for r in rows if r["new_item_request"].get("status") == "dry_run"]
    kinds = collections.Counter()
    for f in forms:
        for issue in f.get("issues") or []:
            text = issue.split(": ", 1)[-1]
            kinds[next((k for k, rx in KINDS if re.search(rx, text)), "other")] += 1
    print(json.dumps({"settings": n.get_settings().public() | {"url": bool(n.get_settings().url)},
                      "days": $Days, "candidates": out.get("candidates"), "decisions": dict(status),
                      "not_forms_or_failed": dict(reasons.most_common(8)),
                      "request_forms": len(forms), "items_read": sum(int(f.get("records") or 0) for f in forms),
                      "forms_with_problems": sum(1 for f in forms if f.get("issues")),
                      "problems_by_kind": dict(kinds)}, indent=1))

asyncio.run(main())
"@
$pyB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($py))
# az on Windows is a .cmd wrapper that garbles quotes and redirections: the shell steps travel base64-encoded too.
$sh = "echo $pyB64 | base64 -d > /tmp/nir-preview.py && docker cp /tmp/nir-preview.py gpi-backend:/tmp/nir-preview.py && docker exec -w /app -e PYTHONPATH=/app gpi-backend python /tmp/nir-preview.py 2>&1 | tail -60"
$script = "echo $([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($sh))) | base64 -d | sudo bash"
Write-Host "Reading the request forms of the last $Days days in dry run (nothing is sent) ..."
$out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript `
    --scripts $script --query 'value[0].message' -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the preview on the VM.' }
Write-Host ((($out -join "`n") -split '\[stderr\]')[0] -replace '^\s*Enable succeeded:\s*', '' -replace '\[stdout\]', '')
