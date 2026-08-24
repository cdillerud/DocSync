[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$BcCustomerNo = "WAT",
    [switch]$AllMappings,
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$SpiroClientId = "",
    [switch]$Apply,
    [int]$PageSize = 100,
    [int]$MaxPages = 500,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SpiroApiBase = 'https://api.spiro.ai/api/v1'
$SpiroTokenUrl = 'https://engine.spiro.ai/oauth/token'

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
    $accessToken = Convert-SecretValueToText -Value (Get-PropertyValue -Object $container -Names @('AccessToken', 'access_token', 'accessToken', 'Token'))
    $refreshToken = Convert-SecretValueToText -Value (Get-PropertyValue -Object $container -Names @('RefreshToken', 'refresh_token', 'refreshToken'))
    $expiresAtUtc = Convert-ToUtcDateTime -Value (Get-PropertyValue -Object $container -Names @('ExpiresAtUtc', 'expires_at', 'ExpiresAt', 'ExpirationUtc'))

    Write-Host "Token store           : $Path"
    Write-Host "Access token present  : $(-not [string]::IsNullOrWhiteSpace($accessToken))"
    Write-Host "Refresh token present : $(-not [string]::IsNullOrWhiteSpace($refreshToken))"
    Write-Host "Expiration available  : $($null -ne $expiresAtUtc)"
    if ($null -ne $expiresAtUtc) {
        Write-Host "Expires at UTC        : $($expiresAtUtc.ToString('u'))"
    }

    if (-not [string]::IsNullOrWhiteSpace($accessToken)) {
        if ($null -eq $expiresAtUtc -or $expiresAtUtc -gt [datetime]::UtcNow.AddMinutes(2)) {
            return $accessToken
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

    $resolvedClientSecret = Convert-SecretValueToText -Value (Get-PropertyValue -Object $root -Names @('ClientSecret', 'client_secret', 'SpiroClientSecret'))
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

    return $newAccessToken
}

function Invoke-SpiroGet {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$AccessToken
    )

    return Invoke-RestMethod `
        -Method GET `
        -Uri $Uri `
        -Headers @{
            Authorization = "Bearer $AccessToken"
            Accept = 'application/json'
            'X-Api-Version' = '1'
        } `
        -TimeoutSec $TimeoutSeconds
}

function Get-SpiroAllRecords {
    param(
        [Parameter(Mandatory)][ValidateSet('opportunities')][string]$Resource,
        [Parameter(Mandatory)][string]$AccessToken
    )

    $rows = [System.Collections.Generic.List[object]]::new()

    for ($page = 1; $page -le $MaxPages; $page++) {
        $uri = "$SpiroApiBase/${Resource}?page%5Bnumber%5D=$page&page%5Bsize%5D=$PageSize"
        $response = Invoke-SpiroGet -Uri $uri -AccessToken $AccessToken

        $data = @()
        if ($response.PSObject.Properties.Name -contains 'data') {
            $data = @($response.data)
        }
        else {
            $data = @($response)
        }

        foreach ($row in $data) {
            $rows.Add($row)
        }

        $currentPage = $page
        $totalPages = $null
        if ($response.PSObject.Properties.Name -contains 'meta') {
            $pagination = Get-PropertyValue -Object $response.meta -Names @('pagination')
            if ($null -ne $pagination) {
                $currentPageValue = Get-PropertyValue -Object $pagination -Names @('current_page', 'currentPage')
                $totalPagesValue = Get-PropertyValue -Object $pagination -Names @('total_pages', 'totalPages')
                if ($null -ne $currentPageValue) {
                    $currentPage = [int]$currentPageValue
                }
                if ($null -ne $totalPagesValue) {
                    $totalPages = [int]$totalPagesValue
                }
            }
        }

        if ($null -ne $totalPages) {
            if ($totalPages -gt $MaxPages) {
                throw "Spiro $Resource requires $totalPages pages, which exceeds MaxPages $MaxPages."
            }
            if ($currentPage -ge $totalPages) {
                break
            }
        }
        elseif ($data.Count -lt $PageSize) {
            break
        }
    }

    return @($rows)
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
                    return Get-SpiroRecordId -Record $data[0]
                }
            }
            else {
                return Get-SpiroRecordId -Record $data
            }
        }
    }

    return [string](Get-SpiroAttribute -Record $Record -Names $AttributeNames)
}

function Get-SpiroDisplayName {
    param([AllowNull()]$Record)
    return [string](Get-SpiroAttribute -Record $Record -Names @('name', 'title', 'opportunity_name', 'description'))
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

function Find-IncludedRecord {
    param(
        [AllowNull()]$Response,
        [Parameter(Mandatory)][string]$Id,
        [string]$Type = ''
    )

    $included = Get-PropertyValue -Object $Response -Names @('included')
    if ($null -eq $included) {
        return $null
    }

    foreach ($record in @($included)) {
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
        return ''
    }

    $first = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('first_name', 'firstName'))
    $last = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('last_name', 'lastName'))
    $name = (($first, $last | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' ').Trim()
    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('name', 'display_name', 'email'))
    }

    return $name
}

function Get-StageName {
    param(
        [string]$StageId,
        [string]$PipelineId,
        [Parameter(Mandatory)][string]$AccessToken,
        [Parameter(Mandatory)][hashtable]$Cache
    )

    if ([string]::IsNullOrWhiteSpace($StageId) -or [string]::IsNullOrWhiteSpace($PipelineId)) {
        return ''
    }

    if (-not $Cache.ContainsKey($PipelineId)) {
        $response = Invoke-SpiroGet -Uri "$SpiroApiBase/pipelines/$PipelineId/opportunity_stages" -AccessToken $AccessToken
        $data = Get-PropertyValue -Object $response -Names @('data')
        if ($null -eq $data) {
            $Cache[$PipelineId] = @($response)
        }
        else {
            $Cache[$PipelineId] = @($data)
        }
    }

    $stageRecord = @(
        $Cache[$PipelineId] |
            Where-Object { (Get-SpiroRecordId -Record $_) -eq $StageId }
    ) | Select-Object -First 1

    if ($null -eq $stageRecord) {
        return ''
    }

    return [string](Get-SpiroAttribute -Record $stageRecord -Names @('name', 'label', 'title', 'stage_name'))
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
        [Parameter(Mandatory)][ValidateSet('GET','POST','PATCH','DELETE')][string]$Method,
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
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds
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

        $next = Get-PropertyValue -Object $response -Names @('@odata.nextLink', 'odata.nextLink')
        if ($null -eq $next) {
            $nextUri = ''
        }
        else {
            $nextUri = [string]$next
        }
    }

    return @($rows)
}

function Normalize-Text {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return '' }
    return ([string]$Value).Trim()
}

function Test-TextEqual {
    param([AllowNull()]$Left, [AllowNull()]$Right)
    return (Normalize-Text $Left) -ceq (Normalize-Text $Right)
}

Write-Section 'GPI SPIRO OPPORTUNITY CACHE UAT REFRESH'

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if (-not $AllMappings -and [string]::IsNullOrWhiteSpace($BcCustomerNo)) {
    throw 'Specify -BcCustomerNo or use -AllMappings.'
}

Write-Host "Environment      : $EnvironmentName"
Write-Host "BC mapping scope : $(if ($AllMappings) { 'all mapped customers' } else { $BcCustomerNo })"
Write-Host "Write mode       : $($Apply.IsPresent)"
Write-Host 'Quote records    : never modified' -ForegroundColor Green
Write-Host 'Pricing fields   : never accessed for write' -ForegroundColor Green

Write-Section 'AUTHENTICATION PREFLIGHT'
$spiroAccessToken = Get-SpiroAccessToken -Path $TokenStorePath
$bcToken = Get-BcAccessToken

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companiesResponse = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $bcToken -Body $null
$bcCompany = @($companiesResponse.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $bcCompany) {
    throw "Business Central company '$CompanyName' was not returned."
}

$bcCompanyId = [string]$bcCompany.id
$spiroBase = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($bcCompanyId)"
Write-Host "BC company       : $($bcCompany.name) [$bcCompanyId]"

Write-Section 'LOAD BUSINESS CENTRAL MAPPINGS'
$mappings = Get-BcCollection -Uri "$spiroBase/spiroCustomerMaps" -Token $bcToken
if (-not $AllMappings) {
    $mappings = @($mappings | Where-Object { [string]$_.bcCustomerNo -eq $BcCustomerNo })
}

$mappings = @(
    $mappings |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.spiroCompanyId) }
)

if ($mappings.Count -eq 0) {
    throw 'No qualifying Business Central to Spiro customer mappings were found for the requested scope.'
}

$mappings |
    Select-Object bcCustomerNo, bcCustomerName, spiroCompanyId, spiroCompanyName |
    Format-Table -AutoSize

$companyById = @{}
foreach ($mapping in $mappings) {
    $companyById[[string]$mapping.spiroCompanyId] = $mapping
}

Write-Section 'LOAD SPIRO OPPORTUNITIES'
$allOpportunities = Get-SpiroAllRecords -Resource opportunities -AccessToken $spiroAccessToken
Write-Host "Spiro opportunities retrieved: $($allOpportunities.Count)"

$baseCandidates = @(
    foreach ($opportunity in $allOpportunities) {
        $companyId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('company', 'account') `
            -AttributeNames @('company_id', 'companyId', 'account_id', 'accountId')

        if ($companyById.ContainsKey($companyId)) {
            [pscustomobject]@{
                OpportunityId = Get-SpiroRecordId -Record $opportunity
                CompanyId = $companyId
                Raw = $opportunity
            }
        }
    }
)

Write-Host "Mapped opportunities found: $($baseCandidates.Count)"
if ($baseCandidates.Count -eq 0) {
    throw 'No Spiro opportunities matched the selected mapped company scope.'
}

Write-Section 'ENRICH LIVE SPIRO CANDIDATES'
$stageCache = @{}
$liveCandidates = [System.Collections.Generic.List[object]]::new()

foreach ($candidate in $baseCandidates) {
    $opportunityId = [string]$candidate.OpportunityId
    try {
        $detailResponse = Invoke-SpiroGet `
            -Uri "$SpiroApiBase/opportunities/${opportunityId}?include=user" `
            -AccessToken $spiroAccessToken

        $detail = Get-PropertyValue -Object $detailResponse -Names @('data')
        if ($detail -is [System.Array]) {
            $detail = @($detail) | Select-Object -First 1
        }
        if ($null -eq $detail) {
            $detail = $candidate.Raw
        }

        $stageId = Get-SpiroRelationshipId `
            -Record $detail `
            -RelationshipNames @('opportunity_stage') `
            -AttributeNames @('opportunity_stage_id', 'opportunityStageId')
        $pipelineId = Get-SpiroRelationshipId `
            -Record $detail `
            -RelationshipNames @('pipeline') `
            -AttributeNames @('pipeline_id', 'pipelineId')
        $ownerId = Get-SpiroRelationshipId `
            -Record $detail `
            -RelationshipNames @('user', 'owner') `
            -AttributeNames @('user_id', 'userId', 'owner_id', 'ownerId')

        $stageName = Get-StageName -StageId $stageId -PipelineId $pipelineId -AccessToken $spiroAccessToken -Cache $stageCache
        $ownerName = Get-OwnerDisplayName -OpportunityResponse $detailResponse -OwnerUserId $ownerId
        $opportunityName = Get-SpiroDisplayName -Record $detail
        if ([string]::IsNullOrWhiteSpace($opportunityName)) {
            $opportunityName = Get-SpiroDisplayName -Record $candidate.Raw
        }

        $browserUrl = Get-SpiroBrowserUrl -Record $detail
        if ([string]::IsNullOrWhiteSpace($browserUrl)) {
            $browserUrl = "https://app.spiro.ai/opportunities/$opportunityId"
        }

        $mapping = $companyById[[string]$candidate.CompanyId]
        $liveCandidates.Add([pscustomobject]@{
            OpportunityId = $opportunityId
            CompanyId = [string]$candidate.CompanyId
            CompanyName = [string]$mapping.spiroCompanyName
            OpportunityName = $opportunityName
            Stage = $stageName
            Owner = $ownerName
            BrowserUrl = $browserUrl
        })
    }
    catch {
        Write-Host "Opportunity $opportunityId enrichment failed: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

$liveCandidates |
    Sort-Object CompanyName, OpportunityName |
    Select-Object OpportunityId, CompanyName, OpportunityName, Stage, Owner |
    Format-Table -AutoSize -Wrap

Write-Section 'COMPARE WITH BUSINESS CENTRAL CACHE'
$existingCache = Get-BcCollection -Uri "$spiroBase/spiroOpportunityCandidates" -Token $bcToken
$targetCompanyIds = @($companyById.Keys)
$existingTarget = @($existingCache | Where-Object { $targetCompanyIds -contains [string]$_.spiroCompanyId })

$existingByOpportunityId = @{}
foreach ($row in $existingTarget) {
    $existingByOpportunityId[[string]$row.spiroOpportunityId] = $row
}

$liveByOpportunityId = @{}
foreach ($row in $liveCandidates) {
    $liveByOpportunityId[[string]$row.OpportunityId] = $row
}

$plan = [System.Collections.Generic.List[object]]::new()
foreach ($live in $liveCandidates) {
    $existing = $null
    if ($existingByOpportunityId.ContainsKey($live.OpportunityId)) {
        $existing = $existingByOpportunityId[$live.OpportunityId]
    }

    $changes = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $existing) {
        $status = 'Add'
        $changes.Add('New cached opportunity')
    }
    else {
        foreach ($comparison in @(
            @{ Label = 'Company Name'; Current = $existing.spiroCompanyName; Desired = $live.CompanyName },
            @{ Label = 'Opportunity Name'; Current = $existing.opportunityName; Desired = $live.OpportunityName },
            @{ Label = 'Stage'; Current = $existing.stage; Desired = $live.Stage },
            @{ Label = 'Owner'; Current = $existing.owner; Desired = $live.Owner },
            @{ Label = 'Browser URL'; Current = $existing.browserUrl; Desired = $live.BrowserUrl }
        )) {
            if (-not (Test-TextEqual $comparison.Current $comparison.Desired)) {
                $changes.Add("$($comparison.Label): '$($comparison.Current)' -> '$($comparison.Desired)'")
            }
        }

        if ($changes.Count -eq 0) {
            $status = 'Unchanged'
        }
        else {
            $status = 'Change'
        }
    }

    $plan.Add([pscustomobject]@{
        OpportunityId = $live.OpportunityId
        CompanyId = $live.CompanyId
        CompanyName = $live.CompanyName
        OpportunityName = $live.OpportunityName
        Stage = $live.Stage
        Owner = $live.Owner
        BrowserUrl = $live.BrowserUrl
        Status = $status
        Changes = if ($changes.Count -eq 0) { '(none)' } else { $changes -join '; ' }
        BcId = if ($null -eq $existing) { '' } else { [string]$existing.id }
    })
}

foreach ($existing in $existingTarget) {
    $opportunityId = [string]$existing.spiroOpportunityId
    if (-not $liveByOpportunityId.ContainsKey($opportunityId)) {
        $plan.Add([pscustomobject]@{
            OpportunityId = $opportunityId
            CompanyId = [string]$existing.spiroCompanyId
            CompanyName = [string]$existing.spiroCompanyName
            OpportunityName = [string]$existing.opportunityName
            Stage = [string]$existing.stage
            Owner = [string]$existing.owner
            BrowserUrl = [string]$existing.browserUrl
            Status = 'Remove'
            Changes = 'Opportunity no longer returned for the mapped company scope'
            BcId = [string]$existing.id
        })
    }
}

$plan |
    Sort-Object CompanyName, OpportunityName |
    Select-Object OpportunityId, CompanyName, OpportunityName, Status, Changes |
    Format-Table -AutoSize -Wrap

$addCount = @($plan | Where-Object { $_.Status -eq 'Add' }).Count
$changeCount = @($plan | Where-Object { $_.Status -eq 'Change' }).Count
$unchangedCount = @($plan | Where-Object { $_.Status -eq 'Unchanged' }).Count
$removeCount = @($plan | Where-Object { $_.Status -eq 'Remove' }).Count

Write-Host ''
Write-Host "Add       : $addCount"
Write-Host "Change    : $changeCount"
Write-Host "Unchanged : $unchangedCount"
Write-Host "Remove    : $removeCount"

if (-not $Apply) {
    Write-Section 'DRY RUN COMPLETE'
    Write-Host 'No Business Central opportunity-cache records were changed.' -ForegroundColor Green
    Write-Host 'Re-run with -Apply after reviewing the candidate plan.'
    return
}

if (($addCount + $changeCount + $removeCount) -eq 0) {
    Write-Section 'NO CACHE CHANGES REQUIRED'
    Write-Host 'Business Central opportunity cache already matches live Spiro.' -ForegroundColor Green
    return
}

Write-Section 'WRITE CONFIRMATION'
Write-Host 'This write is limited to the GPI Spiro opportunity cache.'
Write-Host 'No packaging quote, pricing, UOM, approval, guardrail, audit, or contact data will be modified.' -ForegroundColor Green
$confirmation = Read-Host 'Type CACHE to continue'
if ($confirmation -cne 'CACHE') {
    throw 'Cache refresh cancelled. No Business Central cache records were changed.'
}

Write-Section 'APPLY OPPORTUNITY CACHE REFRESH'
$refreshTime = [datetime]::UtcNow.ToString('o')
$refreshBy = [Environment]::UserName

foreach ($item in $plan) {
    if ($item.Status -eq 'Unchanged') {
        continue
    }

    if ($item.Status -eq 'Remove') {
        Invoke-BcRequest `
            -Method DELETE `
            -Uri "$spiroBase/spiroOpportunityCandidates($($item.BcId))" `
            -Token $bcToken `
            -Body $null `
            -IfMatch '*' | Out-Null
        Write-Host "Removed $($item.OpportunityId) | $($item.OpportunityName)" -ForegroundColor Yellow
        continue
    }

    $body = [ordered]@{
        spiroOpportunityId = $item.OpportunityId
        spiroCompanyId = $item.CompanyId
        spiroCompanyName = $item.CompanyName
        opportunityName = $item.OpportunityName
        stage = $item.Stage
        owner = $item.Owner
        browserUrl = $item.BrowserUrl
        refreshedAt = $refreshTime
        refreshedBy = $refreshBy
    }

    if ($item.Status -eq 'Add') {
        Invoke-BcRequest `
            -Method POST `
            -Uri "$spiroBase/spiroOpportunityCandidates" `
            -Token $bcToken `
            -Body $body | Out-Null
        Write-Host "Added $($item.OpportunityId) | $($item.OpportunityName)" -ForegroundColor Green
    }
    elseif ($item.Status -eq 'Change') {
        Invoke-BcRequest `
            -Method PATCH `
            -Uri "$spiroBase/spiroOpportunityCandidates($($item.BcId))" `
            -Token $bcToken `
            -Body $body `
            -IfMatch '*' | Out-Null
        Write-Host "Updated $($item.OpportunityId) | $($item.OpportunityName)" -ForegroundColor Green
    }
}

Write-Section 'VERIFY BUSINESS CENTRAL CACHE'
$verifiedCache = Get-BcCollection -Uri "$spiroBase/spiroOpportunityCandidates" -Token $bcToken
$verifiedTarget = @($verifiedCache | Where-Object { $targetCompanyIds -contains [string]$_.spiroCompanyId })

$verificationFailures = [System.Collections.Generic.List[string]]::new()
foreach ($live in $liveCandidates) {
    $verified = @($verifiedTarget | Where-Object { [string]$_.spiroOpportunityId -eq $live.OpportunityId }) | Select-Object -First 1
    if ($null -eq $verified) {
        $verificationFailures.Add("Missing opportunity $($live.OpportunityId)")
        continue
    }

    if (-not (Test-TextEqual $verified.opportunityName $live.OpportunityName)) {
        $verificationFailures.Add("Name mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.stage $live.Stage)) {
        $verificationFailures.Add("Stage mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.owner $live.Owner)) {
        $verificationFailures.Add("Owner mismatch for $($live.OpportunityId)")
    }
    if (-not (Test-TextEqual $verified.browserUrl $live.BrowserUrl)) {
        $verificationFailures.Add("URL mismatch for $($live.OpportunityId)")
    }
}

if ($verificationFailures.Count -gt 0) {
    $verificationFailures | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "$($verificationFailures.Count) opportunity-cache verification failure(s) occurred."
}

Write-Host "Verified cached opportunities: $($liveCandidates.Count)" -ForegroundColor Green
Write-Host 'SUCCESS: Business Central Spiro opportunity cache matches live Spiro for the selected mapping scope.' -ForegroundColor Green
