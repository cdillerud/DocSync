#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$Base = Join-Path $ToolRoot 'Invoke-GPIHub-AP-Top10-Legacy-Inventory-AI.ps1'
if (-not (Test-Path -LiteralPath $Base -PathType Leaf)) { throw "AP Top-10 base phase missing: $Base" }

$Raw = Get-Content -LiteralPath $Base -Raw

$ClassificationNeedle = "classification=extract_field(ai,['document_type','classification','doc_type','type'])"
$ClassificationReplacement = "classification=extract_field(ai,['suggested_job_type','document_type','classification','doc_type','type'])"
if (-not $Raw.Contains($ClassificationNeedle)) { throw 'AP REV2 classification extraction anchor not found; refusing broad patch.' }
$Patched = $Raw.Replace($ClassificationNeedle,$ClassificationReplacement)

$AggregationNeedle = @'
        raw_folder=Counter(display_vendor(r['folder_vendor']) for r in raw_records)
        unique_folder=Counter(display_vendor(r['folder_vendor']) for r in unique)
        unique_norm=Counter(display_vendor(r['normalized_vendor']) for r in unique)
        print(f'AP_TOP10_PURCHASE_FILES_RAW={len(raw_records)}')
        print(f'AP_TOP10_PURCHASE_FILES_DEDUP={len(unique)}')
        print('AP_TOP10_LIBRARY_STATS='+json.dumps(stats,sort_keys=True))

        ranking=[]
        for vendor,count in unique_norm.most_common():
            ranking.append({
                'rank':len(ranking)+1,
                'vendor':vendor,
                'dedup_document_count':count,
                'raw_folder_document_count':raw_folder.get(vendor,0),
                'dedup_folder_document_count':unique_folder.get(vendor,0),
                'named_seed_override_count':sum(1 for r in unique if r['normalized_vendor']==vendor and r['folder_vendor']!=vendor),
            })
'@

$AggregationReplacement = @'
        raw_folder_by_key=Counter(normalize_vendor_key(r['folder_vendor']) for r in raw_records)
        unique_folder_by_key=Counter(normalize_vendor_key(r['folder_vendor']) for r in unique)
        key_counts=Counter(normalize_vendor_key(r['normalized_vendor']) for r in unique)
        label_votes=defaultdict(Counter)
        for r in unique:
            key=normalize_vendor_key(r['normalized_vendor'])
            label_votes[key][display_vendor(r['normalized_vendor'])]+=1
        normalized_labels={}
        mandatory_key=normalize_vendor_key(MANDATORY_VENDOR)
        for key in key_counts:
            if key==mandatory_key:
                normalized_labels[key]=MANDATORY_VENDOR
            else:
                normalized_labels[key]=label_votes[key].most_common(1)[0][0]
        for r in unique:
            r['normalized_vendor']=normalized_labels[normalize_vendor_key(r['normalized_vendor'])]
        unique_norm=Counter(r['normalized_vendor'] for r in unique)
        print(f'AP_TOP10_PURCHASE_FILES_RAW={len(raw_records)}')
        print(f'AP_TOP10_PURCHASE_FILES_DEDUP={len(unique)}')
        print('AP_TOP10_LIBRARY_STATS='+json.dumps(stats,sort_keys=True))

        ranking=[]
        for vendor,count in unique_norm.most_common():
            vendor_key=normalize_vendor_key(vendor)
            ranking.append({
                'rank':len(ranking)+1,
                'vendor':vendor,
                'dedup_document_count':count,
                'raw_folder_document_count':raw_folder_by_key.get(vendor_key,0),
                'dedup_folder_document_count':unique_folder_by_key.get(vendor_key,0),
                'named_seed_override_count':sum(1 for r in unique if r['normalized_vendor']==vendor and normalize_vendor_key(r['folder_vendor'])!=vendor_key),
            })
'@

if (-not $Patched.Contains($AggregationNeedle.Trim())) { throw 'AP REV2 normalized vendor aggregation anchor not found; refusing broad patch.' }
$Patched = $Patched.Replace($AggregationNeedle.Trim(),$AggregationReplacement.Trim())

$Generated = Join-Path $ToolRoot 'Invoke-GPIHub-AP-Top10-Legacy-Inventory-AI-REV2.generated.ps1'
Set-Content -LiteralPath $Generated -Value $Patched -Encoding utf8
$Tokens = $null
$Errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Generated,[ref]$Tokens,[ref]$Errors)
if (@($Errors).Count -gt 0) {
    throw ('AP REV2 generated parser failed: ' + ((@($Errors) | ForEach-Object { $_.Message }) -join '; '))
}

Write-Host 'AP_TOP10_REV2_SUGGESTED_JOB_TYPE_EXTRACTION=PASS' -ForegroundColor Green
Write-Host 'AP_TOP10_REV2_VENDOR_ALIAS_NORMALIZATION=PASS' -ForegroundColor Green
Write-Host 'AP_TOP10_REV2_GENERATED_PARSER=PASS' -ForegroundColor Green
Write-Host 'AP_TOP10_REV2_ENTRY=PASS' -ForegroundColor Cyan
& $Generated
