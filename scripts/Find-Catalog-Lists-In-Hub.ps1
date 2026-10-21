#requires -Version 7.0
<#
.SYNOPSIS
  Read-only: lists documents GPI Hub received recently that look like supplier price lists, inventory or
  availability reports, RFQs, quotes or spec sheets, so they can be sent through the Packaging Catalog inbox
  (catalog@gamerpackaging.com).

.DESCRIPTION
  Runs one MongoDB find on the Hub VM (hub_documents), over SSH, and writes a CSV with date, type, vendor,
  sender, subject, file name and SharePoint link. Nothing is changed in the Hub.
.EXAMPLE
  .\scripts\Find-Catalog-Lists-In-Hub.ps1 -Days 120
#>
[CmdletBinding()]
param(
    [int]$Days = 120,
    [string]$VmHost = 'azureuser@4.204.41.190',
    [string]$OutCsv = '.\hub-catalog-candidates.csv'
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
print(cols.join('\t'));
db.hub_documents.find(q, { _id: 0 }).sort({ created_utc: -1 }).limit(500).forEach(d => {
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
$lines = $js | ssh $VmHost 'docker exec -i gpi-mongodb mongosh --quiet gpi_document_hub'
if ($LASTEXITCODE -ne 0) { throw 'The search on the Hub VM failed (SSH or MongoDB).' }
$rows = @($lines | Where-Object { $_ -match "`t" } | ConvertFrom-Csv -Delimiter "`t")
$rows | Export-Csv -Path $OutCsv -NoTypeInformation -Encoding UTF8
$supplierRows = @($rows | Where-Object { $_.category -match '\[supplier\]' })
Write-Host ("Found {0} documents that look like price lists, inventory, RFQs, quotes or specs; {1} name a packaging supplier." -f $rows.Count, $supplierRows.Count) -ForegroundColor Green
$supplierRows | Select-Object -First 25 created_utc, extracted_vendor, subject, file_name | Format-Table -AutoSize -Wrap
Write-Host "Full list: $OutCsv. Nothing was changed in GPI Hub." -ForegroundColor Green
