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

function Get-DecimalSum {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Rows,
        [Parameter(Mandatory)][string]$PropertyName
    )

    [decimal]$total = 0
    foreach ($row in @($Rows)) {
        if ($null -eq $row) {
            continue
        }

        $property = $row.PSObject.Properties[$PropertyName]
        if ($null -eq $property -or $null -eq $property.Value) {
            continue
        }

        [decimal]$value = 0
        if ([decimal]::TryParse([string]$property.Value, [ref]$value)) {
            $total += $value
        }
    }

    return $total
}

Write-Host ""
Write-Host "GPI CHARGED LANDED-COST GROUPS" -ForegroundColor Cyan
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

$itemChargeRows = @($rows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
if ($itemChargeRows.Count -eq 0) {
    Write-Host "No posted item-charge rows were found for $ItemNo." -ForegroundColor Yellow
    Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
    exit 0
}

$chargedLedgerNos = @(
    $itemChargeRows |
        ForEach-Object { [int]$_.itemLedgerEntryNo } |
        Sort-Object -Unique
)

$chargedGroups = @(
    foreach ($ledgerNo in $chargedLedgerNos) {
        $groupRows = @($rows | Where-Object { [int]$_.itemLedgerEntryNo -eq $ledgerNo })
        $chargeRows = @($groupRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
        $directRows = @($groupRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })

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

        [decimal]$quantity = 0
        if ($qtyCandidates.Count -gt 0) {
            $quantity = [decimal](($qtyCandidates | Measure-Object -Maximum).Maximum)
        }

        $directActual = Get-DecimalSum -Rows $directRows -PropertyName 'costAmountActual'
        $chargeActual = Get-DecimalSum -Rows $chargeRows -PropertyName 'costAmountActual'
        $totalActual = $directActual + $chargeActual

        $freightActual = Get-DecimalSum -Rows @($chargeRows | Where-Object { [string]$_.itemChargeNo -eq 'FREIGHT' }) -PropertyName 'costAmountActual'
        $customsActual = Get-DecimalSum -Rows @($chargeRows | Where-Object { [string]$_.itemChargeNo -eq 'CUSTOMS' }) -PropertyName 'costAmountActual'
        $drayageActual = Get-DecimalSum -Rows @($chargeRows | Where-Object { [string]$_.itemChargeNo -eq 'DRAYAGE' }) -PropertyName 'costAmountActual'
        $otherActual = $chargeActual - $freightActual - $customsActual - $drayageActual

        $latestRow = @(
            $groupRows |
                Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, @{ Expression = { [int]$_.entryNo }; Descending = $true } |
                Select-Object -First 1
        )[0]

        [pscustomobject]@{
            PostingDate = [datetime]$latestRow.postingDate
            ItemLedgerEntryNo = $ledgerNo
            QuantityEA = $quantity
            DirectActual = [decimal][math]::Round([double]$directActual, 2)
            Freight = [decimal][math]::Round([double]$freightActual, 2)
            Customs = [decimal][math]::Round([double]$customsActual, 2)
            Drayage = [decimal][math]::Round([double]$drayageActual, 2)
            OtherCharges = [decimal][math]::Round([double]$otherActual, 2)
            TotalCharges = [decimal][math]::Round([double]$chargeActual, 2)
            TotalActual = [decimal][math]::Round([double]$totalActual, 2)
            DirectPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($directActual / $quantity), 5) } else { [decimal]0 }
            ChargesPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($chargeActual / $quantity), 5) } else { [decimal]0 }
            LandedPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($totalActual / $quantity), 5) } else { [decimal]0 }
            LandedPerM = if ($quantity -gt 0) { [decimal][math]::Round([double](($totalActual / $quantity) * 1000), 2) } else { [decimal]0 }
            ChargeCodes = (@($chargeRows | ForEach-Object { [string]$_.itemChargeNo } | Sort-Object -Unique) -join ', ')
        }
    }
)

$chargedGroups = @(
    $chargedGroups |
        Sort-Object @{ Expression = { $_.PostingDate }; Descending = $true }, @{ Expression = { $_.ItemLedgerEntryNo }; Descending = $true }
)

Write-Host "Company ID              : $companyId"
Write-Host "Value Entry rows        : $($rows.Count)"
Write-Host "Item-charge rows        : $($itemChargeRows.Count)"
Write-Host "Charged ledger entries  : $($chargedGroups.Count)"
Write-Host ""

Write-Host "MOST RECENT CHARGED RECEIPTS" -ForegroundColor Cyan
$chargedGroups |
    Select-Object -First $MaxGroups |
    Format-Table PostingDate, ItemLedgerEntryNo, QuantityEA, DirectActual, Freight, Customs, Drayage, OtherCharges, TotalCharges, TotalActual, DirectPerEA, ChargesPerEA, LandedPerEA, LandedPerM, ChargeCodes -AutoSize

$latest = $chargedGroups | Select-Object -First 1
Write-Host ""
Write-Host "LATEST HISTORICAL LANDED-COST EVIDENCE" -ForegroundColor Cyan
Write-Host "Posting date       : $($latest.PostingDate.ToString('yyyy-MM-dd'))"
Write-Host "Item Ledger Entry  : $($latest.ItemLedgerEntryNo)"
Write-Host "Quantity           : $($latest.QuantityEA) EA"
Write-Host "Direct item cost   : $($latest.DirectActual) total / $($latest.DirectPerEA) per EA"
Write-Host "Freight            : $($latest.Freight)"
Write-Host "Customs            : $($latest.Customs)"
Write-Host "Drayage            : $($latest.Drayage)"
Write-Host "Other item charges : $($latest.OtherCharges)"
Write-Host "Total item charges : $($latest.TotalCharges) / $($latest.ChargesPerEA) per EA"
Write-Host "Historical landed  : $($latest.TotalActual) total / $($latest.LandedPerEA) per EA / $($latest.LandedPerM) per M"
Write-Host "Charge codes       : $($latest.ChargeCodes)"
Write-Host ""
Write-Host "IMPORTANT" -ForegroundColor Yellow
Write-Host "This is historical posted Business Central cost evidence. It is not a current freight quote or current landed-cost rate."
Write-Host "Use it to demonstrate the cost components and validate the model, not as the current 2026 quote cost without a current authoritative freight source."
Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
