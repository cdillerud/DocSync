#requires -Version 7.0
<#
.SYNOPSIS
  Read-only: lists documents GPI Hub received recently that look like supplier price lists, inventory or
  availability reports, RFQs, quotes or spec sheets, so they can be sent through the Packaging Catalog inbox
  (catalog@gamerpackaging.com).

.DESCRIPTION
  Runs one MongoDB find on the Hub VM (hub_documents) and writes a CSV with date, type, vendor, sender, subject,
  file name and SharePoint link. Nothing is changed in the Hub.
  Reaches the VM over SSH when this computer has the VM's key (-KeyFile), otherwise through Azure
  (az vm run-command, with your az login), which needs no SSH key.
.EXAMPLE
  .\scripts\Find-Catalog-Lists-In-Hub.ps1 -Days 120
#>
[CmdletBinding()]
param(
    [int]$Days = 120,
    [string]$VmHost = 'azureuser@4.204.41.190',
    [string]$OutCsv = '.\hub-catalog-candidates.csv',
    [string]$KeyFile = ''
)
$ErrorActionPreference = 'Stop'

$js = @"
const since = new Date(Date.now() - $Days * 864e5).toISOString();
const looks = /price|pricing|inventory|availab|stock|rfq|quote|quotation|spec|catalog|open inv|shelf|packout|pallet/i;
const supplier = /glass|\bo-?i\b|owens|anchor|ardagh|arkansas|pgp|piramal|sgc|verallia|vitro|estal|saverglass|bormioli|hwa hsia|jopack|fevisa|arglass|silgan|berlin|tricorbraun|mold.?rite|phoenix|ball corp|canpack|crown|happyann|xilong|waterloo|nbc packaging|stoelzle|vidrala|mulia|gerresheimer/i;
const notAp = { doc_type: { `$nin: ['AP_Invoice', 'ap_invoice', 'Invoice', 'invoice', 'Statement', 'statement', 'Remittance', 'remittance'] } };
const q = { `$and: [
  { `$or: [ { created_utc: { `$gte: since } }, { received_utc: { `$gte: since } } ] },
  notAp,
  { `$or: [ { file_name: looks }, { email_subject: looks }, { subject: looks }, { doc_type: looks }, { category: looks } ] }
] };
const cols = ['created_utc','doc_type','category','extracted_vendor','sender','subject','file_name','sharepoint_web_url'];
if (__SKIP__ === 0) print(cols.join('\t'));
db.hub_documents.find(q, { _id: 0 }).sort({ created_utc: -1 }).skip(__SKIP__).limit(__LIMIT__).forEach(d => {
  const row = {
    created_utc: d.created_utc || d.received_utc || '',
    doc_type: d.doc_type || '', category: d.category || '',
    extracted_vendor: d.extracted_vendor || '',
    sender: d.email_sender || d.sender || d.email_from || '',
    subject: d.email_subject || d.subject || '',
    file_name: d.file_name || '',
    sharepoint_web_url: d.sharepoint_web_url || d.sharepoint_url || ''
  };
  const s = [row.extracted_vendor, row.sender, row.subject, row.file_name].join(' ');
  row.category = row.category + (supplier.test(s) ? ' [supplier]' : '');
  print(cols.map(c => String(row[c]).replace(/[\t\r\n]+/g, ' ')).join('\t'));
});
"@

Write-Host "Searching GPI Hub documents from the last $Days days (read-only) ..." -ForegroundColor Cyan
$remote = 'docker exec -i gpi-mongodb mongosh --quiet gpi_document_hub'
$lines = $null
$sshArgs = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15')
if ($KeyFile) { $sshArgs += @('-i', $KeyFile) }
$lines = ($js -replace '__SKIP__', '0' -replace '__LIMIT__', '500') | ssh @sshArgs $VmHost $remote 2>$null
if ($LASTEXITCODE -ne 0 -or -not $lines) {
    # No SSH key here: run the same read-only query on the VM through Azure instead.
    Write-Host 'SSH not available from this computer; using Azure (az vm run-command) instead ...' -ForegroundColor Yellow
    $ip = ($VmHost -split '@')[-1]
    $vm = $null
    foreach ($sub in @(az account list --query '[].id' -o tsv)) {
        $found = az vm list -d --subscription $sub --query "[?publicIps=='$ip'].{name:name, group:resourceGroup}" -o json 2>$null | ConvertFrom-Json
        if ($found) { $vm = $found[0]; $vm | Add-Member subscription $sub; break }
    }
    if (-not $vm) { throw "No Azure VM with public IP $ip in the subscriptions this login can see. Run 'az login', or pass -KeyFile <path to the VM's SSH key>." }
    Write-Host "  VM: $($vm.name) ($($vm.group))"
    # Azure returns at most ~4 KB of output per run, so each page is gzipped and base64-encoded on the VM.
    $lines = @()
    for ($page = 0; $page -lt 20; $page++) {
        $chunk = $js -replace '__SKIP__', [string]($page * 40) -replace '__LIMIT__', '40'
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($chunk))
        $script = "echo $b64 | base64 -d | sudo $remote | gzip -c | base64 -w0"
        $out = az vm run-command invoke --subscription $vm.subscription -g $vm.group -n $vm.name --command-id RunShellScript --scripts $script --query 'value[0].message' -o tsv
        if ($LASTEXITCODE -ne 0) { throw 'Azure could not run the search on the VM (needs Virtual Machine Contributor on it).' }
        $text = ($out -join "`n")
        $packed = (($text -split '\[stdout\]')[-1] -split '\[stderr\]')[0].Trim()
        if (-not $packed) { break }
        $gz = [IO.Compression.GZipStream]::new([IO.MemoryStream]::new([Convert]::FromBase64String($packed)), [IO.Compression.CompressionMode]::Decompress)
        $reader = [IO.StreamReader]::new($gz, [Text.Encoding]::UTF8)
        $got = @($reader.ReadToEnd() -split "`n" | Where-Object { $_ -match "`t" })
        $reader.Dispose()
        $lines += $got
        $data = @($got | Where-Object { $_ -notmatch '^created_utc\t' })
        Write-Host "  page $($page + 1): $($data.Count) documents"
        if ($data.Count -lt 40) { break }
    }
}
$rows = @($lines | Where-Object { $_ -match "`t" } | ConvertFrom-Csv -Delimiter "`t")
$rows | Export-Csv -Path $OutCsv -NoTypeInformation -Encoding UTF8
$supplierRows = @($rows | Where-Object { $_.category -match '\[supplier\]' })
Write-Host ("Found {0} documents that look like price lists, inventory, RFQs, quotes or specs; {1} name a packaging supplier." -f $rows.Count, $supplierRows.Count) -ForegroundColor Green
$supplierRows | Select-Object -First 25 created_utc, extracted_vendor, subject, file_name | Format-Table -AutoSize -Wrap
Write-Host "Full list: $OutCsv. Nothing was changed in GPI Hub." -ForegroundColor Green
