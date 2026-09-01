#requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$CustomerNumber,

    [Parameter(Mandatory)]
    [string]$ItemNumber,

    [ValidateRange(1, 1000)]
    [int]$MaxInvoicesToScan = 250,

    [ValidateRange(1, 200)]
    [int]$MaxMatches = 50,

    [switch]$IncludeOpenOrders
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED ORDER-INTAKE READ-ONLY TARGET ONLY
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$ExpectedCompanyId = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)

    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) {
        return [System.Net.NetworkCredential]::new('', $TokenValue).Password
    }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is required. Install-Module Az.Accounts -Scope CurrentUser'
    }

    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken `
            -TenantId $TenantId `
            -ResourceUrl 'https://api.businesscentral.dynamics.com' `
            -ErrorAction Stop

        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
        # Fall through to isolated interactive BC-scoped authentication.
    }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null

    Connect-AzAccount `
        -Tenant $TenantId `
        -AuthScope 'https://api.businesscentral.dynamics.com' `
        -Scope Process `
        -ErrorAction Stop | Out-Null

    $tokenResult = Get-AzAccessToken `
        -TenantId $TenantId `
        -ResourceUrl 'https://api.businesscentral.dynamics.com' `
        -ErrorAction Stop

    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Could not acquire Business Central access token.'
    }

    return $token
}

function Assert-CertifiedConfiguration {
    if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') {
        throw 'Tenant hard pin changed. Execution blocked.'
    }
    if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') {
        throw "Unauthorized Business Central environment '$Environment'. Execution blocked."
    }
    if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') {
        throw "Forbidden Business Central environment '$Environment'. Execution blocked."
    }
    if ($CompanyName -ne 'Gamer Packaging') {
        throw 'Company-name hard pin changed. Execution blocked.'
    }
    if ($ExpectedCompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') {
        throw 'Company-ID hard pin changed. Execution blocked.'
    }
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)

    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
    }
}

function Invoke-BcGet {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers
    )

    Assert-BcUri -Uri $Uri
    return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

function Get-NextLink {
    param([Parameter(Mandatory)]$Response)

    $prop = $Response.PSObject.Properties['@odata.nextLink']
    if ($null -eq $prop) { return $null }
    if ([string]::IsNullOrWhiteSpace([string]$prop.Value)) { return $null }
    return [string]$prop.Value
}

function New-HistoryRow {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)]$Header,
        [Parameter(Mandatory)]$Line
    )

    if ($Source -eq 'PostedSalesInvoice') {
        return [pscustomobject][ordered]@{
            source                         = $Source
            documentNumber                 = [string]$Header.number
            status                         = [string]$Header.status
            documentDate                   = [string]$Header.postingDate
            orderDate                      = $null
            requestedDeliveryDate          = $null
            externalDocumentNumber         = [string]$Header.externalDocumentNumber
            customerPurchaseOrderReference = [string]$Header.customerPurchaseOrderReference
            customerNumber                 = [string]$Header.customerNumber
            itemNumber                     = [string]$Line.lineObjectNumber
            description                    = [string]$Line.description
            quantity                       = [decimal]$Line.quantity
            unitOfMeasureCode              = [string]$Line.unitOfMeasureCode
            unitPrice                      = [decimal]$Line.unitPrice
            discountPercent                = [decimal]$Line.discountPercent
            discountAmount                 = [decimal]$Line.discountAmount
            amountExcludingTax             = [decimal]$Line.amountExcludingTax
            shipmentDate                   = [string]$Line.shipmentDate
            locationId                     = [string]$Line.locationId
        }
    }

    return [pscustomobject][ordered]@{
        source                         = $Source
        documentNumber                 = [string]$Header.number
        status                         = [string]$Header.status
        documentDate                   = $null
        orderDate                      = [string]$Header.orderDate
        requestedDeliveryDate          = [string]$Header.requestedDeliveryDate
        externalDocumentNumber         = [string]$Header.externalDocumentNumber
        customerPurchaseOrderReference = $null
        customerNumber                 = [string]$Header.customerNumber
        itemNumber                     = [string]$Line.lineObjectNumber
        description                    = [string]$Line.description
        quantity                       = [decimal]$Line.quantity
        unitOfMeasureCode              = [string]$Line.unitOfMeasureCode
        unitPrice                      = [decimal]$Line.unitPrice
        discountPercent                = [decimal]$Line.discountPercent
        discountAmount                 = [decimal]$Line.discountAmount
        amountExcludingTax             = [decimal]$Line.amountExcludingTax
        shipmentDate                   = [string]$Line.shipmentDate
        locationId                     = [string]$Line.locationId
    }
}

Assert-CertifiedConfiguration
$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-verify exact named environment and sandbox type on every run.
$environmentResponse = Invoke-BcGet `
    -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' `
    -Headers $headers

$environmentMatches = @(
    $environmentResponse.value |
    Where-Object { [string]$_.name -eq $Environment }
)

if ($environmentMatches.Count -ne 1) {
    throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)."
}

$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') {
    throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox."
}

$environmentEncoded = [Uri]::EscapeDataString($Environment)
$apiRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$environmentEncoded/api/v2.0"

$companies = Invoke-BcGet -Uri "$apiRoot/companies" -Headers $headers
$companyMatches = @(
    $companies.value |
    Where-Object {
        [string]$_.id -eq $ExpectedCompanyId -and
        (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
    }
)

if ($companyMatches.Count -ne 1) {
    throw "Expected exact Gamer Packaging company ID $ExpectedCompanyId; found $($companyMatches.Count)."
}

$companyRoot = "$apiRoot/companies($ExpectedCompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - GET-ONLY SALES HISTORY INSPECTOR' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment      : $Environment"
Write-Host "Environment type : $environmentType"
Write-Host "Company          : $CompanyName"
Write-Host "Company ID       : $ExpectedCompanyId"
Write-Host "Customer         : $CustomerNumber"
Write-Host "Item             : $ItemNumber"
Write-Host "HTTP methods     : GET ONLY" -ForegroundColor Green
Write-Host "Business writes  : NONE" -ForegroundColor Green
Write-Host "Production       : HARD BLOCKED" -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# Resolve the exact customer and item first. Do not infer either identity.
$customerLiteral = Escape-ODataLiteral $CustomerNumber
$customerFilter = [Uri]::EscapeDataString("number eq '$customerLiteral'")
$customerSelect = [Uri]::EscapeDataString('id,number,displayName,blocked')
$customerResponse = Invoke-BcGet `
    -Uri "$companyRoot/customers?`$select=$customerSelect&`$filter=$customerFilter&`$top=2" `
    -Headers $headers
$customers = @($customerResponse.value)
if ($customers.Count -ne 1) {
    throw "Expected exactly one customer '$CustomerNumber'; found $($customers.Count)."
}

$itemLiteral = Escape-ODataLiteral $ItemNumber
$itemFilter = [Uri]::EscapeDataString("number eq '$itemLiteral'")
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
$itemResponse = Invoke-BcGet `
    -Uri "$companyRoot/items?`$select=$itemSelect&`$filter=$itemFilter&`$top=2" `
    -Headers $headers
$items = @($itemResponse.value)
if ($items.Count -ne 1) {
    throw "Expected exactly one item '$ItemNumber'; found $($items.Count)."
}

Write-Host "Resolved customer : $($customers[0].number) / $($customers[0].displayName)"
Write-Host "Resolved item     : $($items[0].number) / $($items[0].displayName)"
Write-Host "Item base UOM     : $($items[0].baseUnitOfMeasureCode)"
Write-Host ''

$matches = [System.Collections.Generic.List[object]]::new()
$scannedInvoices = 0

# Posted invoices are the strongest standard-API evidence of actual transacted quantity/UOM/price.
$invoiceFilter = [Uri]::EscapeDataString("customerNumber eq '$customerLiteral'")
$invoiceSelect = [Uri]::EscapeDataString('id,number,status,postingDate,invoiceDate,externalDocumentNumber,customerPurchaseOrderReference,customerNumber')
$invoiceUri = "$companyRoot/salesInvoices?`$select=$invoiceSelect&`$filter=$invoiceFilter&`$orderby=postingDate desc&`$top=100"

while (-not [string]::IsNullOrWhiteSpace($invoiceUri) -and $scannedInvoices -lt $MaxInvoicesToScan -and $matches.Count -lt $MaxMatches) {
    $invoicePage = Invoke-BcGet -Uri $invoiceUri -Headers $headers

    foreach ($invoice in @($invoicePage.value)) {
        if ($scannedInvoices -ge $MaxInvoicesToScan -or $matches.Count -ge $MaxMatches) { break }
        $scannedInvoices++

        $lineFilter = [Uri]::EscapeDataString("lineObjectNumber eq '$itemLiteral'")
        $lineSelect = [Uri]::EscapeDataString('id,documentId,sequence,lineType,lineObjectNumber,description,unitOfMeasureCode,quantity,unitPrice,discountAmount,discountPercent,amountExcludingTax,shipmentDate,locationId')
        $lineUri = "$companyRoot/salesInvoices($($invoice.id))/salesInvoiceLines?`$select=$lineSelect&`$filter=$lineFilter"
        $lineResponse = Invoke-BcGet -Uri $lineUri -Headers $headers

        foreach ($line in @($lineResponse.value)) {
            if ([string]$line.lineType -ne 'Item') { continue }
            $matches.Add((New-HistoryRow -Source 'PostedSalesInvoice' -Header $invoice -Line $line))
            if ($matches.Count -ge $MaxMatches) { break }
        }
    }

    if ($scannedInvoices -ge $MaxInvoicesToScan -or $matches.Count -ge $MaxMatches) { break }
    $invoiceUri = Get-NextLink -Response $invoicePage
}

$openOrdersScanned = 0
if ($IncludeOpenOrders -and $matches.Count -lt $MaxMatches) {
    $orderFilter = [Uri]::EscapeDataString("customerNumber eq '$customerLiteral'")
    $orderSelect = [Uri]::EscapeDataString('id,number,status,orderDate,requestedDeliveryDate,externalDocumentNumber,customerNumber')
    $orderUri = "$companyRoot/salesOrders?`$select=$orderSelect&`$filter=$orderFilter&`$orderby=orderDate desc&`$top=100"

    while (-not [string]::IsNullOrWhiteSpace($orderUri) -and $openOrdersScanned -lt 250 -and $matches.Count -lt $MaxMatches) {
        $orderPage = Invoke-BcGet -Uri $orderUri -Headers $headers

        foreach ($order in @($orderPage.value)) {
            if ($openOrdersScanned -ge 250 -or $matches.Count -ge $MaxMatches) { break }
            $openOrdersScanned++

            $lineFilter = [Uri]::EscapeDataString("lineObjectNumber eq '$itemLiteral'")
            $lineSelect = [Uri]::EscapeDataString('id,documentId,sequence,lineType,lineObjectNumber,description,unitOfMeasureCode,quantity,unitPrice,discountAmount,discountPercent,amountExcludingTax,shipmentDate,locationId')
            $lineUri = "$companyRoot/salesOrders($($order.id))/salesOrderLines?`$select=$lineSelect&`$filter=$lineFilter"
            $lineResponse = Invoke-BcGet -Uri $lineUri -Headers $headers

            foreach ($line in @($lineResponse.value)) {
                if ([string]$line.lineType -ne 'Item') { continue }
                $matches.Add((New-HistoryRow -Source 'OpenSalesOrder' -Header $order -Line $line))
                if ($matches.Count -ge $MaxMatches) { break }
            }
        }

        if ($openOrdersScanned -ge 250 -or $matches.Count -ge $MaxMatches) { break }
        $orderUri = Get-NextLink -Response $orderPage
    }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Posted invoices scanned : $scannedInvoices"
Write-Host "Open orders scanned      : $openOrdersScanned"
Write-Host "Matching lines found     : $($matches.Count)"
Write-Host ''

$summary = @(
    $matches |
    Group-Object unitOfMeasureCode, quantity |
    ForEach-Object {
        $first = $_.Group[0]
        [pscustomobject][ordered]@{
            unitOfMeasureCode = $first.unitOfMeasureCode
            quantity          = $first.quantity
            occurrences       = $_.Count
            minUnitPrice      = ($_.Group | Measure-Object unitPrice -Minimum).Minimum
            maxUnitPrice      = ($_.Group | Measure-Object unitPrice -Maximum).Maximum
            newestDate        = ($_.Group.documentDate + $_.Group.orderDate | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Descending | Select-Object -First 1)
        }
    } |
    Sort-Object occurrences -Descending
)

[ordered]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    companyId = $ExpectedCompanyId
    customer = $customers[0]
    item = $items[0]
    postedInvoicesScanned = $scannedInvoices
    openOrdersScanned = $openOrdersScanned
    matchingLineCount = $matches.Count
    quantityUomSummary = $summary
    history = @($matches | Sort-Object @{ Expression = { if ($_.documentDate) { $_.documentDate } else { $_.orderDate } }; Descending = $true })
    safety = [ordered]@{
        httpMethods = @('GET')
        businessCentralWrites = 'NONE'
        production = 'HARD BLOCKED'
    }
} | ConvertTo-Json -Depth 30
