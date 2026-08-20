[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ItemNo = "FG10900B",
    [int]$MaxGroups = 20
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-BcGetAll {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
    }

    $rows = [System.Collections.Generic.List[object]]::new()
    $nextUri = $Uri

    while (-not [string]::IsNullOrWhiteSpace($nextUri)) {
        $response = Invoke-RestMethod -Method GET -Uri $nextUri -Headers $headers
        foreach ($row in @($response.value)) {
            $rows.Add($row) | Out-Null
        }

        $nextUri = $null
        $nextProperty = $response.PSObject.Properties['@odata.nextLink']
        if ($nextProperty -and -not [string]::IsNullOrWhiteSpace([string]$nextProperty.Value)) {
            $nextUri = [string]$nextProperty.Value
        }
    }

    return @($rows)
}

Write-Host ""
Write-Host "GPI POSTED ITEM COST EVIDENCE" -ForegroundColor Cyan
Write-Host "Environment : $EnvironmentName"
Write-Host "Item        : $ItemNo"
Write-Host ""

if ($EnvironmentName -ne "Sandbox_NoZetadocs_UAT") {
    throw "This inspection script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required."
}

$accountJson = & az account show --output json --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
    & az login --tenant $TenantId --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure login failed."
    }
}

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name "bc-client-secret" --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($secret)) {
    throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
}

try {
    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        grant_type = "client_credentials"
        client_id = $ClientId
        client_secret = $secret
        scope = "https://api.businesscentral.dynamics.com/.default"
    }
}
finally {
    $secret = $null
}

$token = [string]$tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Microsoft identity platform did not return an access token."
}

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcGetAll -Uri "$bcBase/api/v2.0/companies" -Token $token
$company = @($companies | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) {
    throw "Company '$CompanyName' was not returned by the Business Central API."
}

$companyId = [string]$company.id
$apiBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"
$filter = [uri]::EscapeDataString("itemNo eq '$ItemNo'")
$rows = @(Invoke-BcGetAll -Uri "$apiBase/itemValueEvidence?`$filter=$filter" -Token $token)

Write-Host "Company ID  : $companyId"
Write-Host "Rows        : $($rows.Count)"
Write-Host ""

if ($rows.Count -eq 0) {
    Write-Host "No Value Entry rows were returned for $ItemNo." -ForegroundColor Yellow
    Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
    exit 0
}

$positiveRows = @(
    $rows | Where-Object {
        ([decimal]$_.invoicedQuantity -gt 0) -or
        ([decimal]$_.valuedQuantity -gt 0) -or
        (([decimal]$_.costAmountActual -gt 0) -and -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo))
    }
)

Write-Host "LATEST POSITIVE / ITEM-CHARGE VALUE ENTRIES" -ForegroundColor Cyan
$positiveRows |
    Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, @{ Expression = { [int]$_.entryNo }; Descending = $true } |
    Select-Object -First 50 `
        postingDate,
        documentNo,
        documentLineNo,
        itemLedgerEntryNo,
        itemChargeNo,
        valuedQuantity,
        invoicedQuantity,
        costPerUnit,
        costAmountActual,
        costAmountExpected,
        purchaseAmountActual |
    Format-Table -AutoSize

$groups = @(
    $positiveRows |
        Group-Object itemLedgerEntryNo |
        ForEach-Object {
            $groupRows = @($_.Group)
            $qtyCandidates = @(
                $groupRows |
                    ForEach-Object { [math]::Abs([double][decimal]$_.invoicedQuantity) } |
                    Where-Object { $_ -gt 0 }
            )

            if ($qtyCandidates.Count -eq 0) {
                $qtyCandidates = @(
                    $groupRows |
                        ForEach-Object { [math]::Abs([double][decimal]$_.valuedQuantity) } |
                        Where-Object { $_ -gt 0 }
                )
            }

            $quantity = if ($qtyCandidates.Count -gt 0) { [decimal](($qtyCandidates | Measure-Object -Maximum).Maximum) } else { [decimal]0 }
            $directActual = [decimal](($groupRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) } | Measure-Object -Property costAmountActual -Sum).Sum)
            $chargeActual = [decimal](($groupRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) } | Measure-Object -Property costAmountActual -Sum).Sum)
            $expected = [decimal](($groupRows | Measure-Object -Property costAmountExpected -Sum).Sum)
            $totalActual = $directActual + $chargeActual
            $chargeCodes = @($groupRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) } | ForEach-Object { [string]$_.itemChargeNo } | Sort-Object -Unique)
            $postingDate = @($groupRows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true } | Select-Object -First 1)[0].postingDate
            $documentNo = @($groupRows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true } | Select-Object -First 1)[0].documentNo

            [pscustomobject]@{
                PostingDate = $postingDate
                DocumentNo = $documentNo
                ItemLedgerEntryNo = [int]$_.Name
                Quantity = $quantity
                DirectActual = $directActual
                ItemChargeActual = $chargeActual
                ExpectedCost = $expected
                TotalActual = $totalActual
                ActualCostPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($totalActual / $quantity), 5) } else { [decimal]0 }
                ItemChargeCodes = ($chargeCodes -join ', ')
            }
        } |
        Sort-Object @{ Expression = { [datetime]$_.PostingDate }; Descending = $true }, @{ Expression = { [int]$_.ItemLedgerEntryNo }; Descending = $true } |
        Select-Object -First $MaxGroups
)

Write-Host ""
Write-Host "POSTED COST BY ITEM LEDGER ENTRY" -ForegroundColor Cyan
$groups | Format-Table PostingDate, DocumentNo, ItemLedgerEntryNo, Quantity, DirectActual, ItemChargeActual, ExpectedCost, TotalActual, ActualCostPerEA, ItemChargeCodes -AutoSize

$withCharges = @($groups | Where-Object { [decimal]$_.ItemChargeActual -ne 0 -or -not [string]::IsNullOrWhiteSpace([string]$_.ItemChargeCodes) })

Write-Host ""
Write-Host "LANDED-COST EVIDENCE SUMMARY" -ForegroundColor Cyan
if ($withCharges.Count -gt 0) {
    $latest = $withCharges | Select-Object -First 1
    Write-Host "Posted entries with item charges : $($withCharges.Count)"
    Write-Host "Latest charged document          : $($latest.DocumentNo)"
    Write-Host "Latest direct actual cost        : $($latest.DirectActual)"
    Write-Host "Latest item-charge actual cost   : $($latest.ItemChargeActual)"
    Write-Host "Latest total actual cost         : $($latest.TotalActual)"
    Write-Host "Latest actual cost / EA          : $($latest.ActualCostPerEA)"
    Write-Host "Latest actual cost / M           : $([decimal][math]::Round([double]($latest.ActualCostPerEA * 1000), 5))"
    Write-Host "Item charge codes                : $($latest.ItemChargeCodes)"
    Write-Host ""
    Write-Host "This gives us posted Business Central evidence for costs beyond the supplier product line." -ForegroundColor Green
}
else {
    Write-Host "No positive posted item-charge cost was found in the recent Value Entry groups for $ItemNo." -ForegroundColor Yellow
    Write-Host "Do not manufacture a freight amount for the demo. We need another authoritative freight source or a clearly labeled UAT-only illustrative rate." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
