[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$SpiroClientId = "",
    [int]$QuoteEntryNo = 0,
    [switch]$Apply,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SpiroApiBase = 'https://api.spiro.ai/api/v1'
$SpiroTokenUrl = 'https://engine.spiro.ai/oauth/token'
$ProtectedQuoteEntryNo = 67

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)

    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Get-PropertyValue {
    param(
        [AllowNull()]$Object,
        [Parameter(Mandatory)][string[]]$Names
    )

    if ($null -eq $Object) {
        return $null
    }

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $name } |
            Select-Object -First 1

        if ($property) {
            return $property.Value
        }
    }

    return $null
}

function Convert-SecretValueToText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [System.Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        try {
            return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }

    return [string]$Value
}

function Get-TokenContainer {
    param([Parameter(Mandatory)]$Root)

    $accessAliases = @('AccessToken', 'access_token', 'Token', 'accessToken')
    if ($null -ne (Get-PropertyValue -Object $Root -Names $accessAliases)) {
        return $Root
    }

    foreach ($containerName in @('Tokens', 'TokenData', 'OAuth', 'OAuthTokens', 'SpiroTokens')) {
        $candidate = Get-PropertyValue -Object $Root -Names @($containerName)
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue -Object $candidate -Names $accessAliases)) {
            return $candidate
        }
    }

    return $Root
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string[]]$Aliases,
        [Parameter(Mandatory)][string]$PreferredName,
        [AllowNull()]$Value,
        [switch]$Secure
    )

    $property = $null
    foreach ($alias in $Aliases) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $alias } |
            Select-Object -First 1
        if ($property) {
            break
        }
    }

    $storedValue = $Value
    if ($Secure -and $null -ne $Value) {
        $storedValue = ConvertTo-SecureString -String ([string]$Value) -AsPlainText -Force
    }

    if ($property) {
        $property.Value = $storedValue
    }
    else {
        $Object | Add-Member -NotePropertyName $PreferredName -NotePropertyValue $storedValue
    }
}

function Convert-ToUtcDateTime {
    param([AllowNull()]$Value)

    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [datetime]) {
        return ([datetime]$Value).ToUniversalTime()
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse(
        $text,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal,
        [ref]$parsed
    )) {
        return $parsed.ToUniversalTime()
    }

    return $null
}

function Save-RefreshedTokenStore {
    param(
        [Parameter(Mandatory)]$Root,
        [Parameter(Mandatory)]$Container,
        [Parameter(Mandatory)][string]$AccessToken,
        [AllowNull()][string]$RefreshToken,
        [Parameter(Mandatory)][datetime]$ExpiresAtUtc,
        [Parameter(Mandatory)][string]$Path
    )

    $backupPath = "$Path.bak"
    Copy-Item -LiteralPath $Path -Destination $backupPath -Force

    Set-ObjectProperty -Object $Container `
        -Aliases @('AccessToken', 'access_token', 'accessToken', 'Token') `
        -PreferredName 'AccessToken' `
        -Value $AccessToken `
        -Secure

    if (-not [string]::IsNullOrWhiteSpace($RefreshToken)) {
        Set-ObjectProperty -Object $Container `
            -Aliases @('RefreshToken', 'refresh_token', 'refreshToken') `
            -PreferredName 'RefreshToken' `
            -Value $RefreshToken `
            -Secure
    }

    Set-ObjectProperty -Object $Container `
        -Aliases @('ExpiresAtUtc', 'expires_at', 'ExpiresAt', 'ExpirationUtc') `
        -PreferredName 'ExpiresAtUtc' `
        -Value $ExpiresAtUtc

    $Root | Export-Clixml -LiteralPath $Path -Force

    Write-Host "Refreshed token store saved. Backup: $backupPath" -ForegroundColor DarkGreen
}

function Get-SpiroAccessToken {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Spiro protected token store was not found: $Path"
    }

    $root = Import-Clixml -LiteralPath $Path
    if ($null -eq $root) {
        throw "Spiro token store could not be loaded: $Path"
    }

    $container = Get-TokenContainer -Root $root

    $accessValue = Get-PropertyValue -Object $container -Names @('AccessToken', 'access_token', 'accessToken', 'Token')
    $refreshValue = Get-PropertyValue -Object $container -Names @('RefreshToken', 'refresh_token', 'refreshToken')
    $expiresValue = Get-PropertyValue -Object $container -Names @('ExpiresAtUtc', 'expires_at', 'ExpiresAt', 'ExpirationUtc')

    $accessToken = Convert-SecretValueToText -Value $accessValue
    $refreshToken = Convert-SecretValueToText -Value $refreshValue
    $expiresAtUtc = Convert-ToUtcDateTime -Value $expiresValue

    Write-Host "Token store           : $Path"
    Write-Host "Access token present  : $(-not [string]::IsNullOrWhiteSpace($accessToken))"
    Write-Host "Refresh token present : $(-not [string]::IsNullOrWhiteSpace($refreshToken))"
    Write-Host "Expiration available  : $($null -ne $expiresAtUtc)"
    if ($null -ne $expiresAtUtc) {
        Write-Host "Expires at UTC        : $($expiresAtUtc.ToString('u'))"
    }

    if (-not [string]::IsNullOrWhiteSpace($accessToken)) {
        if ($null -eq $expiresAtUtc -or $expiresAtUtc -gt [datetime]::UtcNow.AddMinutes(2)) {
            return [pscustomobject]@{
                AccessToken = $accessToken
                Root = $root
                Container = $container
                Refreshed = $false
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($refreshToken)) {
        throw 'The access token is expired and no refresh token is available. Reauthorize Spiro before continuing.'
    }

    $resolvedClientId = $SpiroClientId
    if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
        $resolvedClientId = [string](Get-PropertyValue -Object $root -Names @('ClientId', 'client_id', 'SpiroClientId'))
    }
    if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
        $resolvedClientId = [string]$env:SPIRO_CLIENT_ID
    }
    if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
        $resolvedClientId = Read-Host 'Spiro OAuth client ID'
    }
    if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
        throw 'Spiro OAuth client ID is required to refresh the token.'
    }

    $secretValue = Get-PropertyValue -Object $root -Names @('ClientSecret', 'client_secret', 'SpiroClientSecret')
    $resolvedClientSecret = Convert-SecretValueToText -Value $secretValue
    if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
        $resolvedClientSecret = [string]$env:SPIRO_CLIENT_SECRET
    }
    if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
        $secureClientSecret = Read-Host 'Spiro OAuth client secret' -AsSecureString
        $resolvedClientSecret = Convert-SecretValueToText -Value $secureClientSecret
    }
    if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
        throw 'Spiro OAuth client secret is required to refresh the token.'
    }

    Write-Host 'Refreshing Spiro access token...' -ForegroundColor Yellow

    try {
        $refreshResponse = Invoke-RestMethod `
            -Method POST `
            -Uri $SpiroTokenUrl `
            -ContentType 'application/json' `
            -Body (@{
                client_id = $resolvedClientId
                client_secret = $resolvedClientSecret
                refresh_token = $refreshToken
                grant_type = 'refresh_token'
            } | ConvertTo-Json -Compress) `
            -TimeoutSec $TimeoutSeconds
    }
    finally {
        $resolvedClientSecret = $null
    }

    $newAccessToken = [string]$refreshResponse.access_token
    if ([string]::IsNullOrWhiteSpace($newAccessToken)) {
        throw 'Spiro token refresh did not return an access token.'
    }

    $newRefreshToken = [string]$refreshResponse.refresh_token
    if ([string]::IsNullOrWhiteSpace($newRefreshToken)) {
        $newRefreshToken = $refreshToken
    }

    $expiresIn = 3600
    if ($refreshResponse.PSObject.Properties.Name -contains 'expires_in') {
        $expiresIn = [int]$refreshResponse.expires_in
    }
    $newExpiresAtUtc = [datetime]::UtcNow.AddSeconds($expiresIn)

    Save-RefreshedTokenStore `
        -Root $root `
        -Container $container `
        -AccessToken $newAccessToken `
        -RefreshToken $newRefreshToken `
        -ExpiresAtUtc $newExpiresAtUtc `
        -Path $Path

    return [pscustomobject]@{
        AccessToken = $newAccessToken
        Root = $root
        Container = $container
        Refreshed = $true
    }
}

function Invoke-SpiroGet {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$AccessToken
    )

    $headers = @{
        Authorization = "Bearer $AccessToken"
        Accept = 'application/json'
        'X-Api-Version' = '1'
    }

    return Invoke-RestMethod `
        -Method GET `
        -Uri $Uri `
        -Headers $headers `
        -TimeoutSec $TimeoutSeconds
}

function Get-SpiroAttribute {
    param(
        [AllowNull()]$Record,
        [Parameter(Mandatory)][string[]]$Names
    )

    if ($null -eq $Record) {
        return $null
    }

    $attributes = Get-PropertyValue -Object $Record -Names @('attributes')
    if ($null -ne $attributes) {
        $value = Get-PropertyValue -Object $attributes -Names $Names
        if ($null -ne $value) {
            return $value
        }
    }

    return Get-PropertyValue -Object $Record -Names $Names
}

function Get-SpiroRecordId {
    param([AllowNull()]$Record)

    return [string](Get-PropertyValue -Object $Record -Names @('id', 'Id', '_id'))
}

function Get-SpiroRelationshipId {
    param(
        [AllowNull()]$Record,
        [Parameter(Mandatory)][string[]]$RelationshipNames,
        [Parameter(Mandatory)][string[]]$AttributeNames
    )

    if ($null -eq $Record) {
        return ''
    }

    $relationships = Get-PropertyValue -Object $Record -Names @('relationships')
    if ($null -ne $relationships) {
        foreach ($relationshipName in $RelationshipNames) {
            $relationship = Get-PropertyValue -Object $relationships -Names @($relationshipName)
            if ($null -eq $relationship) {
                continue
            }

            $data = Get-PropertyValue -Object $relationship -Names @('data')
            if ($null -eq $data) {
                continue
            }

            if ($data -is [System.Array]) {
                if ($data.Count -gt 0) {
                    return [string](Get-SpiroRecordId -Record $data[0])
                }
            }
            else {
                return [string](Get-SpiroRecordId -Record $data)
            }
        }
    }

    return [string](Get-SpiroAttribute -Record $Record -Names $AttributeNames)
}

function Get-SpiroDisplayName {
    param(
        [AllowNull()]$Record,
        [Parameter(Mandatory)][ValidateSet('company','opportunity')][string]$Kind
    )

    switch ($Kind) {
        'company' {
            return [string](Get-SpiroAttribute -Record $Record -Names @('name', 'company_name', 'display_name'))
        }
        'opportunity' {
            return [string](Get-SpiroAttribute -Record $Record -Names @('name', 'title', 'opportunity_name', 'description'))
        }
    }
}

function Get-SpiroBrowserUrl {
    param([AllowNull()]$Record)

    $url = [string](Get-SpiroAttribute -Record $Record -Names @('web_url', 'webUrl', 'browser_url', 'browserUrl', 'app_url', 'appUrl'))
    if (-not [string]::IsNullOrWhiteSpace($url)) {
        return $url
    }

    $links = Get-PropertyValue -Object $Record -Names @('links')
    if ($null -ne $links) {
        foreach ($name in @('html', 'web', 'browser', 'app')) {
            $candidate = [string](Get-PropertyValue -Object $links -Names @($name))
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                return $candidate
            }
        }
    }

    return ''
}

function Get-ResponseDataRecord {
    param([AllowNull()]$Response)

    if ($null -eq $Response) {
        return $null
    }

    $data = Get-PropertyValue -Object $Response -Names @('data')
    if ($null -eq $data) {
        return $Response
    }

    $rows = @($data)
    if ($rows.Count -eq 0) {
        return $null
    }

    return $rows[0]
}

function Find-IncludedRecord {
    param(
        [AllowNull()]$Response,
        [Parameter(Mandatory)][string]$Id,
        [string]$Type = ''
    )

    if ($null -eq $Response -or [string]::IsNullOrWhiteSpace($Id)) {
        return $null
    }

    $includedValue = Get-PropertyValue -Object $Response -Names @('included')
    if ($null -eq $includedValue) {
        return $null
    }

    foreach ($record in @($includedValue)) {
        if ((Get-SpiroRecordId -Record $record) -ne $Id) {
            continue
        }

        if ([string]::IsNullOrWhiteSpace($Type)) {
            return $record
        }

        $recordType = [string](Get-PropertyValue -Object $record -Names @('type'))
        if ($recordType -ieq $Type) {
            return $record
        }
    }

    return $null
}

function Get-OwnerDisplayName {
    param(
        [AllowNull()]$OpportunityResponse,
        [string]$OwnerUserId
    )

    if ([string]::IsNullOrWhiteSpace($OwnerUserId)) {
        return ''
    }

    $ownerRecord = Find-IncludedRecord -Response $OpportunityResponse -Id $OwnerUserId -Type 'user'
    if ($null -eq $ownerRecord) {
        throw "Spiro owner user $OwnerUserId was not returned in the opportunity include response."
    }

    $first = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('first_name', 'firstName'))
    $last = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('last_name', 'lastName'))
    $name = (($first, $last | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' ').Trim()

    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('name', 'display_name', 'email'))
    }

    if ([string]::IsNullOrWhiteSpace($name)) {
        throw "Spiro owner user $OwnerUserId did not provide a usable display name."
    }

    return $name
}

function Get-BcAccessToken {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw 'Azure CLI (az) is required for Business Central authentication.'
    }

    $accountJson = & az account show --output json --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
        & az login --tenant $TenantId --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Azure login failed.'
        }
    }

    $secret = (& az keyvault secret show `
        --vault-name $KeyVaultName `
        --name 'bc-client-secret' `
        --query value `
        --output tsv `
        --only-show-errors).Trim()

    if ([string]::IsNullOrWhiteSpace($secret)) {
        throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
    }

    try {
        $response = Invoke-RestMethod `
            -Method POST `
            -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
            -ContentType 'application/x-www-form-urlencoded' `
            -Body @{
                grant_type = 'client_credentials'
                client_id = $BcClientId
                client_secret = $secret
                scope = 'https://api.businesscentral.dynamics.com/.default'
            } `
            -TimeoutSec $TimeoutSeconds
    }
    finally {
        $secret = $null
    }

    $token = [string]$response.access_token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Microsoft identity platform did not return a Business Central access token.'
    }

    return $token
}

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','PATCH')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [AllowNull()]$Body,
        [string]$IfMatch = ''
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }

    if (-not [string]::IsNullOrWhiteSpace($IfMatch)) {
        $headers['If-Match'] = $IfMatch
    }

    if ($null -eq $Body) {
        return Invoke-RestMethod `
            -Method $Method `
            -Uri $Uri `
            -Headers $headers `
            -TimeoutSec $TimeoutSeconds
    }

    return Invoke-RestMethod `
        -Method $Method `
        -Uri $Uri `
        -Headers $headers `
        -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Depth 20 -Compress) `
        -TimeoutSec $TimeoutSeconds
}

function Get-BcCollection {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    $rows = @()
    $nextUri = $Uri

    while (-not [string]::IsNullOrWhiteSpace($nextUri)) {
        $response = Invoke-BcRequest -Method GET -Uri $nextUri -Token $Token -Body $null
        $value = Get-PropertyValue -Object $response -Names @('value')
        if ($null -ne $value) {
            $rows += @($value)
        }

        $nextValue = Get-PropertyValue -Object $response -Names @('@odata.nextLink', 'odata.nextLink')
        if ($null -eq $nextValue) {
            $nextUri = ''
        }
        else {
            $nextUri = [string]$nextValue
        }
    }

    return @($rows)
}

function Convert-ToCompareText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) {
        return ''
    }

    return ([string]$Value).Trim()
}

function Test-TextEqual {
    param(
        [AllowNull()]$Left,
        [AllowNull()]$Right
    )

    return (Convert-ToCompareText -Value $Left) -ceq (Convert-ToCompareText -Value $Right)
}

function Add-TextChange {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$Changes,
        [Parameter(Mandatory)][string]$Label,
        [AllowNull()]$Current,
        [AllowNull()]$Desired
    )

    if (-not (Test-TextEqual -Left $Current -Right $Desired)) {
        $Changes.Add("${Label}: '$(Convert-ToCompareText -Value $Current)' -> '$(Convert-ToCompareText -Value $Desired)'")
        return $true
    }

    return $false
}

function Get-StageName {
    param(
        [Parameter(Mandatory)][string]$StageId,
        [Parameter(Mandatory)][string]$PipelineId,
        [Parameter(Mandatory)][string]$AccessToken,
        [Parameter(Mandatory)][hashtable]$Cache
    )

    if (-not $Cache.ContainsKey($PipelineId)) {
        $stageUri = "$SpiroApiBase/pipelines/$PipelineId/opportunity_stages"
        $stageResponse = Invoke-SpiroGet -Uri $stageUri -AccessToken $AccessToken
        $stageData = Get-PropertyValue -Object $stageResponse -Names @('data')
        if ($null -eq $stageData) {
            $Cache[$PipelineId] = @($stageResponse)
        }
        else {
            $Cache[$PipelineId] = @($stageData)
        }
    }

    $stageRecord = @(
        $Cache[$PipelineId] |
            Where-Object { (Get-SpiroRecordId -Record $_) -eq $StageId }
    ) | Select-Object -First 1

    if ($null -eq $stageRecord) {
        throw "Spiro stage $StageId was not found in pipeline $PipelineId."
    }

    $stageName = [string](Get-SpiroAttribute -Record $stageRecord -Names @('name', 'label', 'title', 'stage_name'))
    if ([string]::IsNullOrWhiteSpace($stageName)) {
        throw "Spiro stage $StageId did not provide a usable name."
    }

    return $stageName
}

Write-Section 'GPI SPIRO REPEATABLE UAT SYNC'

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if ($QuoteEntryNo -eq $ProtectedQuoteEntryNo) {
    throw "Quote $ProtectedQuoteEntryNo is protected and cannot be synchronized by this script."
}

Write-Host "Environment        : $EnvironmentName"
Write-Host "Company            : $CompanyName"
Write-Host "Quote filter       : $(if ($QuoteEntryNo -gt 0) { $QuoteEntryNo } else { 'all linked quotes' })"
Write-Host "Write mode         : $($Apply.IsPresent)"
Write-Host "Protected quote    : $ProtectedQuoteEntryNo"
Write-Host 'Pricing fields     : never read for write and never modified' -ForegroundColor Green
Write-Host 'Contact fields     : preserved and never inferred' -ForegroundColor Green

Write-Section 'SPIRO TOKEN PREFLIGHT'
$spiroTokenState = Get-SpiroAccessToken -Path $TokenStorePath
$spiroAccessToken = [string]$spiroTokenState.AccessToken

Write-Section 'BUSINESS CENTRAL PREFLIGHT'
$bcToken = Get-BcAccessToken
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companiesResponse = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $bcToken -Body $null
$bcCompany = @($companiesResponse.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $bcCompany) {
    throw "Business Central company '$CompanyName' was not returned."
}

$bcCompanyId = [string]$bcCompany.id
$spiroBase = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($bcCompanyId)"
Write-Host "BC company         : $($bcCompany.name) [$bcCompanyId]"

Write-Section 'LOAD EXISTING LINKS'
$mappings = Get-BcCollection -Uri "$spiroBase/spiroCustomerMaps" -Token $bcToken
$quoteLinks = Get-BcCollection -Uri "$spiroBase/spiroQuoteLinks" -Token $bcToken

if ($QuoteEntryNo -gt 0) {
    $quoteLinks = @($quoteLinks | Where-Object { [int](Get-PropertyValue -Object $_ -Names @('quoteNo')) -eq $QuoteEntryNo })
}
else {
    $quoteLinks = @(
        $quoteLinks |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace(
                    [string](Get-PropertyValue -Object $_ -Names @('spiroOpportunityId'))
                )
            }
    )
}

Write-Host "Customer mappings  : $($mappings.Count)"
Write-Host "Quote links loaded : $($quoteLinks.Count)"

if ($QuoteEntryNo -gt 0 -and $quoteLinks.Count -eq 0) {
    throw "Packaging quote $QuoteEntryNo was not returned by the Spiro quote-link API."
}

$mappingByCustomer = @{}
foreach ($mapping in $mappings) {
    $customerNo = [string](Get-PropertyValue -Object $mapping -Names @('bcCustomerNo'))
    if (-not [string]::IsNullOrWhiteSpace($customerNo)) {
        $mappingByCustomer[$customerNo] = $mapping
    }
}

$stageCache = @{}
$plans = @()

Write-Section 'BUILD SYNC PLAN'
foreach ($quote in $quoteLinks) {
    $quoteNo = [int](Get-PropertyValue -Object $quote -Names @('quoteNo'))
    $customerNo = [string](Get-PropertyValue -Object $quote -Names @('customerNo'))
    $opportunityId = [string](Get-PropertyValue -Object $quote -Names @('spiroOpportunityId'))
    $currentStatus = [string](Get-PropertyValue -Object $quote -Names @('status'))

    $plan = [pscustomobject]@{
        QuoteNo = $quoteNo
        CustomerNo = $customerNo
        OpportunityId = $opportunityId
        Status = 'Pending'
        Changes = ''
        Error = ''
        MappingId = ''
        QuoteId = [string](Get-PropertyValue -Object $quote -Names @('id'))
        CurrentQuoteStatus = $currentStatus
        MappingBody = $null
        QuoteBody = $null
        DesiredCompanyName = ''
        DesiredCompanyUrl = ''
        DesiredOpportunityName = ''
        DesiredStage = ''
        DesiredOwner = ''
        DesiredOpportunityUrl = ''
    }

    if ($quoteNo -eq $ProtectedQuoteEntryNo) {
        $plan.Status = 'Skipped'
        $plan.Error = 'Protected Charlie demo quote.'
        $plans += $plan
        continue
    }

    if ([string]::IsNullOrWhiteSpace($opportunityId)) {
        $plan.Status = 'Skipped'
        $plan.Error = 'No Spiro Opportunity ID is linked.'
        $plans += $plan
        continue
    }

    if (-not $mappingByCustomer.ContainsKey($customerNo)) {
        $plan.Status = 'Skipped'
        $plan.Error = 'No BC customer to Spiro company mapping exists.'
        $plans += $plan
        continue
    }

    $mapping = $mappingByCustomer[$customerNo]
    $plan.MappingId = [string](Get-PropertyValue -Object $mapping -Names @('id'))
    $mappedCompanyId = [string](Get-PropertyValue -Object $mapping -Names @('spiroCompanyId'))

    if ([string]::IsNullOrWhiteSpace($mappedCompanyId)) {
        $plan.Status = 'Skipped'
        $plan.Error = 'Customer mapping has no Spiro Company ID.'
        $plans += $plan
        continue
    }

    try {
        $opportunityUri = "$SpiroApiBase/opportunities/${opportunityId}?include=user,company"
        $opportunityResponse = Invoke-SpiroGet -Uri $opportunityUri -AccessToken $spiroAccessToken
        $opportunity = Get-ResponseDataRecord -Response $opportunityResponse
        if ($null -eq $opportunity) {
            throw "Spiro opportunity $opportunityId returned no data."
        }

        $opportunityCompanyId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('company', 'account') `
            -AttributeNames @('company_id', 'companyId', 'account_id', 'accountId')

        if ([string]::IsNullOrWhiteSpace($opportunityCompanyId)) {
            throw "Spiro opportunity $opportunityId did not provide a company relationship."
        }

        if ($opportunityCompanyId -ne $mappedCompanyId) {
            throw "Spiro opportunity $opportunityId belongs to company $opportunityCompanyId, but BC customer $customerNo maps to company $mappedCompanyId."
        }

        $companyRecord = Find-IncludedRecord -Response $opportunityResponse -Id $mappedCompanyId -Type 'company'
        if ($null -eq $companyRecord) {
            $companyResponse = Invoke-SpiroGet -Uri "$SpiroApiBase/companies/$mappedCompanyId" -AccessToken $spiroAccessToken
            $companyRecord = Get-ResponseDataRecord -Response $companyResponse
        }
        if ($null -eq $companyRecord) {
            throw "Spiro company $mappedCompanyId returned no data."
        }

        $companyName = Get-SpiroDisplayName -Record $companyRecord -Kind company
        if ([string]::IsNullOrWhiteSpace($companyName)) {
            throw "Spiro company $mappedCompanyId did not provide a usable name."
        }

        $companyUrl = Get-SpiroBrowserUrl -Record $companyRecord
        if ([string]::IsNullOrWhiteSpace($companyUrl)) {
            $companyUrl = [string](Get-PropertyValue -Object $mapping -Names @('spiroCompanyUrl'))
        }

        $opportunityName = Get-SpiroDisplayName -Record $opportunity -Kind opportunity
        if ([string]::IsNullOrWhiteSpace($opportunityName)) {
            throw "Spiro opportunity $opportunityId did not provide a usable name."
        }

        $stageId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('opportunity_stage') `
            -AttributeNames @('opportunity_stage_id', 'opportunityStageId')
        $pipelineId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('pipeline') `
            -AttributeNames @('pipeline_id', 'pipelineId')
        $ownerUserId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('user', 'owner') `
            -AttributeNames @('user_id', 'userId', 'owner_id', 'ownerId')

        $stageName = ''
        if (-not [string]::IsNullOrWhiteSpace($stageId)) {
            if ([string]::IsNullOrWhiteSpace($pipelineId)) {
                throw "Spiro opportunity $opportunityId has stage $stageId but no pipeline relationship."
            }
            $stageName = Get-StageName -StageId $stageId -PipelineId $pipelineId -AccessToken $spiroAccessToken -Cache $stageCache
        }

        $ownerName = Get-OwnerDisplayName -OpportunityResponse $opportunityResponse -OwnerUserId $ownerUserId

        $opportunityUrl = Get-SpiroBrowserUrl -Record $opportunity
        if ([string]::IsNullOrWhiteSpace($opportunityUrl)) {
            $opportunityUrl = "https://app.spiro.ai/opportunities/$opportunityId"
        }

        $plan.DesiredCompanyName = $companyName
        $plan.DesiredCompanyUrl = $companyUrl
        $plan.DesiredOpportunityName = $opportunityName
        $plan.DesiredStage = $stageName
        $plan.DesiredOwner = $ownerName
        $plan.DesiredOpportunityUrl = $opportunityUrl

        $changes = [System.Collections.Generic.List[string]]::new()
        $mappingBody = [ordered]@{}
        $quoteBody = [ordered]@{}

        if (Add-TextChange -Changes $changes -Label 'Company Name' `
            -Current (Get-PropertyValue -Object $mapping -Names @('spiroCompanyName')) `
            -Desired $companyName) {
            $mappingBody['spiroCompanyName'] = $companyName
        }

        if (Add-TextChange -Changes $changes -Label 'Company URL' `
            -Current (Get-PropertyValue -Object $mapping -Names @('spiroCompanyUrl')) `
            -Desired $companyUrl) {
            $mappingBody['spiroCompanyUrl'] = $companyUrl
        }

        if (Add-TextChange -Changes $changes -Label 'Opportunity Name' `
            -Current (Get-PropertyValue -Object $quote -Names @('spiroOpportunityName')) `
            -Desired $opportunityName) {
            $quoteBody['spiroOpportunityName'] = $opportunityName
        }

        if (Add-TextChange -Changes $changes -Label 'Stage' `
            -Current (Get-PropertyValue -Object $quote -Names @('spiroStage')) `
            -Desired $stageName) {
            $quoteBody['spiroStage'] = $stageName
        }

        if (Add-TextChange -Changes $changes -Label 'Owner' `
            -Current (Get-PropertyValue -Object $quote -Names @('spiroOwner')) `
            -Desired $ownerName) {
            $quoteBody['spiroOwner'] = $ownerName
        }

        if (Add-TextChange -Changes $changes -Label 'Opportunity URL' `
            -Current (Get-PropertyValue -Object $quote -Names @('spiroOpportunityUrl')) `
            -Desired $opportunityUrl) {
            $quoteBody['spiroOpportunityUrl'] = $opportunityUrl
        }

        $plan.MappingBody = $mappingBody
        $plan.QuoteBody = $quoteBody
        if ($changes.Count -eq 0) {
            $plan.Status = 'Unchanged'
            $plan.Changes = '(none)'
        }
        else {
            $plan.Status = 'Changed'
            $plan.Changes = $changes -join '; '
        }
    }
    catch {
        $plan.Status = 'Failed'
        $plan.Error = $_.Exception.Message
    }

    $plans += $plan
}

$plans |
    Select-Object QuoteNo, CustomerNo, OpportunityId, Status, Changes, Error |
    Format-Table -AutoSize -Wrap

$changedCount = @($plans | Where-Object { $_.Status -eq 'Changed' }).Count
$unchangedCount = @($plans | Where-Object { $_.Status -eq 'Unchanged' }).Count
$skippedCount = @($plans | Where-Object { $_.Status -eq 'Skipped' }).Count
$failedCount = @($plans | Where-Object { $_.Status -eq 'Failed' }).Count

Write-Host ''
Write-Host "Plan changed   : $changedCount"
Write-Host "Plan unchanged : $unchangedCount"
Write-Host "Plan skipped   : $skippedCount"
Write-Host "Plan failed    : $failedCount"

if (-not $Apply) {
    Write-Section 'DRY RUN COMPLETE'
    Write-Host 'No Business Central records were changed.' -ForegroundColor Green
    Write-Host 'Use -Apply only after the plan has been reviewed.'
    $spiroAccessToken = $null
    $bcToken = $null
    return
}

if ($changedCount -eq 0) {
    Write-Section 'NO CHANGES TO APPLY'
    Write-Host 'No Business Central records require an update.' -ForegroundColor Green
    $spiroAccessToken = $null
    $bcToken = $null
    return
}

Write-Section 'WRITE CONFIRMATION'
Write-Host "Quotes with context changes: $changedCount"
Write-Host "Protected quote $ProtectedQuoteEntryNo will not be written."
Write-Host 'Writes are limited to existing Spiro customer mapping and quote CRM context fields.'
Write-Host 'Contact, pricing, UOM, landed cost, GP, guardrail, approval, decision, and audit fields are not modified.'
$confirmation = Read-Host 'Type SYNC to continue'
if ($confirmation -cne 'SYNC') {
    throw 'Write cancelled. No Business Central records were changed.'
}

Write-Section 'APPLY SYNC PLAN'
foreach ($plan in @($plans | Where-Object { $_.Status -eq 'Changed' })) {
    try {
        $mappingBody = $plan.MappingBody
        $quoteBody = $plan.QuoteBody

        if ($null -ne $mappingBody -and $mappingBody.Count -gt 0) {
            if ([string]::IsNullOrWhiteSpace($plan.MappingId)) {
                throw "Quote $($plan.QuoteNo) has mapping changes but no BC mapping ID."
            }

            Invoke-BcRequest `
                -Method PATCH `
                -Uri "$spiroBase/spiroCustomerMaps($($plan.MappingId))" `
                -Token $bcToken `
                -Body $mappingBody `
                -IfMatch '*' | Out-Null
        }

        if ($null -ne $quoteBody -and $quoteBody.Count -gt 0) {
            if ([string]::IsNullOrWhiteSpace($plan.QuoteId)) {
                throw "Quote $($plan.QuoteNo) has context changes but no BC quote-link ID."
            }

            $quoteBody['spiroLastSyncedAt'] = [datetime]::UtcNow.ToString('o')
            $quoteBody['spiroLastSyncedBy'] = [Environment]::UserName

            Invoke-BcRequest `
                -Method PATCH `
                -Uri "$spiroBase/spiroQuoteLinks($($plan.QuoteId))" `
                -Token $bcToken `
                -Body $quoteBody `
                -IfMatch '*' | Out-Null
        }

        if (-not [string]::IsNullOrWhiteSpace($plan.MappingId)) {
            $verifiedMapping = Invoke-BcRequest `
                -Method GET `
                -Uri "$spiroBase/spiroCustomerMaps($($plan.MappingId))" `
                -Token $bcToken `
                -Body $null

            if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedMapping -Names @('spiroCompanyName')) -Right $plan.DesiredCompanyName)) {
                throw "Quote $($plan.QuoteNo) verification failed for Spiro company name."
            }

            if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedMapping -Names @('spiroCompanyUrl')) -Right $plan.DesiredCompanyUrl)) {
                throw "Quote $($plan.QuoteNo) verification failed for Spiro company URL."
            }
        }

        $verifiedQuote = Invoke-BcRequest `
            -Method GET `
            -Uri "$spiroBase/spiroQuoteLinks($($plan.QuoteId))" `
            -Token $bcToken `
            -Body $null

        if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedQuote -Names @('status')) -Right $plan.CurrentQuoteStatus)) {
            throw "Quote $($plan.QuoteNo) status changed unexpectedly during sync."
        }
        if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedQuote -Names @('spiroOpportunityName')) -Right $plan.DesiredOpportunityName)) {
            throw "Quote $($plan.QuoteNo) verification failed for opportunity name."
        }
        if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedQuote -Names @('spiroStage')) -Right $plan.DesiredStage)) {
            throw "Quote $($plan.QuoteNo) verification failed for stage."
        }
        if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedQuote -Names @('spiroOwner')) -Right $plan.DesiredOwner)) {
            throw "Quote $($plan.QuoteNo) verification failed for owner."
        }
        if (-not (Test-TextEqual -Left (Get-PropertyValue -Object $verifiedQuote -Names @('spiroOpportunityUrl')) -Right $plan.DesiredOpportunityUrl)) {
            throw "Quote $($plan.QuoteNo) verification failed for opportunity URL."
        }

        $plan.Status = 'Updated'
        $plan.Error = ''
        Write-Host "Quote $($plan.QuoteNo): UPDATED" -ForegroundColor Green
    }
    catch {
        $plan.Status = 'Failed'
        $plan.Error = $_.Exception.Message
        Write-Host "Quote $($plan.QuoteNo): FAILED - $($plan.Error)" -ForegroundColor Red
    }
}

Write-Section 'SYNC RESULT'
$plans |
    Select-Object QuoteNo, CustomerNo, OpportunityId, Status, Changes, Error |
    Format-Table -AutoSize -Wrap

$updatedCount = @($plans | Where-Object { $_.Status -eq 'Updated' }).Count
$finalUnchangedCount = @($plans | Where-Object { $_.Status -eq 'Unchanged' }).Count
$finalSkippedCount = @($plans | Where-Object { $_.Status -eq 'Skipped' }).Count
$finalFailedCount = @($plans | Where-Object { $_.Status -eq 'Failed' }).Count

Write-Host ''
Write-Host "Updated   : $updatedCount"
Write-Host "Unchanged : $finalUnchangedCount"
Write-Host "Skipped   : $finalSkippedCount"
Write-Host "Failed    : $finalFailedCount"

if ($finalFailedCount -gt 0) {
    throw "$finalFailedCount Spiro sync item(s) failed. Review the result table above."
}

Write-Host ''
Write-Host 'SUCCESS: repeatable Spiro CRM context sync completed in Business Central UAT.' -ForegroundColor Green
$spiroAccessToken = $null
$bcToken = $null
