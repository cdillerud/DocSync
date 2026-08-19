[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ProductNo = "FG10900B",
    [string]$ExpectedBCItemNo = "FG10900B"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Token = $null
$Secret = $null
$QuoteBase = $null
$QuoteId = $null
$LineId = $null
$Results = [System.Collections.Generic.List[object]]::new()
$RunId = "QUOTE-UOM-UAT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

function Get-ErrorBody {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    try {
        if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.Content) {
            return $ErrorRecord.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
    }
    catch {
    }

    return $ErrorRecord.Exception.Message
}

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [AllowNull()]$Body,
        [switch]$IfMatch
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
    }

    if ($IfMatch) {
        $headers["If-Match"] = "*"
    }

    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers
        }

        $json = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType "application/json" -Body $json
    }
    catch {
        $detail = Get-ErrorBody -ErrorRecord $_
        throw "Business Central API $Method failed: $Uri`n$detail"
    }
}

function Add-Result {
    param(
        [Parameter(Mandatory)][string]$Check,
        [Parameter(Mandatory)][bool]$Passed,
        [AllowNull()]$Actual,
        [AllowNull()]$Expected
    )

    $Results.Add([pscustomobject]@{
        Check = $Check
        Passed = $Passed
        Actual = [string]$Actual
        Expected = [string]$Expected
    }) | Out-Null
}

function Assert-Equal {
    param([string]$Check, $Actual, $Expected)
    Add-Result -Check $Check -Passed ([string]$Actual -eq [string]$Expected) -Actual $Actual -Expected $Expected
}

function Assert-DecimalNear {
    param(
        [string]$Check,
        [decimal]$Actual,
        [decimal]$Expected,
        [decimal]$Tolerance = 0.0001
    )

    $passed = ([math]::Abs([double]($Actual - $Expected)) -le [double]$Tolerance)
    Add-Result -Check $Check -Passed $passed -Actual $Actual -Expected "$Expected +/- $Tolerance"
}

Write-Host ""
Write-Host "GPI PACKAGING QUOTE UOM NORMALIZATION UAT" -ForegroundColor Cyan
Write-Host "Run ID      : $RunId"
Write-Host "Environment : $EnvironmentName"
Write-Host "Product     : $ProductNo"
Write-Host "BC Item     : $ExpectedBCItemNo"
Write-Host ""

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This UAT script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
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

$Secret = (& az keyvault secret show --vault-name $KeyVaultName --name "bc-client-secret" --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($Secret)) {
    throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
}

try {
    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        grant_type = "client_credentials"
        client_id = $ClientId
        client_secret = $Secret
        scope = "https://api.businesscentral.dynamics.com/.default"
    }
}
finally {
    $Secret = $null
}

$Token = [string]$tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "Microsoft identity platform did not return an access token."
}

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Body $null
$company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) {
    throw "Company '$CompanyName' was not returned by the Business Central API."
}

$companyId = [string]$company.id
$QuoteBase = "$bcBase/api/gpi/packagingQuotes/v1.0/companies($companyId)"

try {
    $quote = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes" -Body @{
        quoteDate = (Get-Date).ToString("yyyy-MM-dd")
        description = "$RunId UOM normalization"
    }
    $QuoteId = [string]$quote.id

    $line = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuoteLines" -Body @{
        quoteEntryNo = [int]$quote.entryNo
        productNo = $ProductNo
        quantity = 10000
        landedCostPerUnit = 0.09192
        proposedSellPrice = 0.14660
        targetGrossMarginPct = 0
    }
    $LineId = [string]$line.id

    $line = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteLines($LineId)" -Body $null
    Assert-Equal "Initial BC item" $line.bcItemNo $ExpectedBCItemNo
    Assert-Equal "Initial UOM" $line.uomCode "EA"
    Assert-DecimalNear "Initial quantity" ([decimal]$line.quantity) 10000 0.00001
    Assert-DecimalNear "Initial landed cost" ([decimal]$line.landedCostPerUnit) 0.09192 0.00001
    Assert-DecimalNear "Initial proposed sell" ([decimal]$line.proposedSellPrice) 0.14660 0.00001
    Assert-DecimalNear "Initial extended landed" ([decimal]$line.extendedLandedCost) 919.20 0.01
    Assert-DecimalNear "Initial extended sell" ([decimal]$line.extendedSell) 1466.00 0.01
    $initialGP = [decimal]$line.calculatedGrossMarginPct

    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($LineId)" -IfMatch -Body @{
        uomCode = "M"
    }

    $lineM = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteLines($LineId)" -Body $null
    Assert-Equal "Converted UOM" $lineM.uomCode "M"
    Assert-DecimalNear "EA to M quantity" ([decimal]$lineM.quantity) 10 0.00001
    Assert-DecimalNear "EA to M landed cost" ([decimal]$lineM.landedCostPerUnit) 91.92 0.00001
    Assert-DecimalNear "EA to M proposed sell" ([decimal]$lineM.proposedSellPrice) 146.60 0.00001
    Assert-DecimalNear "EA to M extended landed preserved" ([decimal]$lineM.extendedLandedCost) 919.20 0.01
    Assert-DecimalNear "EA to M extended sell preserved" ([decimal]$lineM.extendedSell) 1466.00 0.01
    Assert-DecimalNear "EA to M GP preserved" ([decimal]$lineM.calculatedGrossMarginPct) $initialGP 0.00001

    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($LineId)" -IfMatch -Body @{
        uomCode = "EA"
    }

    $lineEA = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteLines($LineId)" -Body $null
    Assert-Equal "Round-trip UOM" $lineEA.uomCode "EA"
    Assert-DecimalNear "Round-trip quantity" ([decimal]$lineEA.quantity) 10000 0.00001
    Assert-DecimalNear "Round-trip landed cost" ([decimal]$lineEA.landedCostPerUnit) 0.09192 0.00001
    Assert-DecimalNear "Round-trip proposed sell" ([decimal]$lineEA.proposedSellPrice) 0.14660 0.00001
    Assert-DecimalNear "Round-trip extended landed" ([decimal]$lineEA.extendedLandedCost) 919.20 0.01
    Assert-DecimalNear "Round-trip extended sell" ([decimal]$lineEA.extendedSell) 1466.00 0.01
    Assert-DecimalNear "Round-trip GP" ([decimal]$lineEA.calculatedGrossMarginPct) $initialGP 0.00001
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($LineId)) {
        try {
            $null = Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuoteLines($LineId)" -Body $null -IfMatch
        }
        catch {
            Write-Warning "Could not delete UAT quote line $LineId. $($_.Exception.Message)"
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($QuoteId)) {
        try {
            $null = Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuotes($QuoteId)" -Body $null -IfMatch
        }
        catch {
            Write-Warning "Could not delete UAT quote $QuoteId. $($_.Exception.Message)"
        }
    }
}

Write-Host ""
$Results | Format-Table Check, Passed, Actual, Expected -AutoSize

$passed = @($Results | Where-Object Passed).Count
$failed = @($Results | Where-Object { -not $_.Passed }).Count
Write-Host ""
Write-Host "Checks passed : $passed / $($Results.Count)"
Write-Host "Checks failed : $failed / $($Results.Count)"

if ($failed -gt 0) {
    throw "GPI Packaging Quote UOM UAT failed $failed check(s)."
}

Write-Host "GPI PACKAGING QUOTE UOM NORMALIZATION UAT PASSED" -ForegroundColor Green
Write-Host "Temporary quote data was removed. The 25-product pilot catalog was not changed." -ForegroundColor DarkGray
