[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [int]$QuoteEntryNo = 55,
    [string]$BcCustomerNo = "WAT",
    [string]$CompanySearch = "Watkins",
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$SpiroClientId = "",
    [switch]$Apply,
    [int]$PageSize = 100,
    [int]$MaxPages = 100,
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

function Get-SpiroAllRecords {
    param(
        [Parameter(Mandatory)][ValidateSet('companies','opportunities','contacts')][string]$Resource,
        [Parameter(Mandatory)][string]$AccessToken
    )

    $rows = [System.Collections.Generic.List[object]]::new()

    for ($page = 1; $page -le $MaxPages; $page++) {
        $uri = "$SpiroApiBase/$Resource?page[number]=$page&page[size]=$PageSize"
        $response = Invoke-SpiroGet -Uri $uri -AccessToken $AccessToken

        $data = @()
        if ($response.PSObject.Properties.Name -contains 'data') {
            $data = @($response.data)
        }
        elseif ($response.PSObject.Properties.Name -contains $Resource) {
            $data = @($response.$Resource)
        }
        else {
            $data = @($response)
        }

        foreach ($row in $data) {
            $rows.Add($row)
        }

        if ($data.Count -lt $PageSize) {
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
        [Parameter(Mandatory)][ValidateSet('company','opportunity','contact')][string]$Kind
    )

    switch ($Kind) {
        'company' {
            return [string](Get-SpiroAttribute -Record $Record -Names @('name', 'company_name', 'display_name'))
        }
        'opportunity' {
            return [string](Get-SpiroAttribute -Record $Record -Names @('name', 'title', 'opportunity_name', 'description'))
        }
        'contact' {
            $name = [string](Get-SpiroAttribute -Record $Record -Names @('name', 'full_name', 'display_name'))
            if (-not [string]::IsNullOrWhiteSpace($name)) {
                return $name
            }

            $first = [string](Get-SpiroAttribute -Record $Record -Names @('first_name', 'firstName'))
            $last = [string](Get-SpiroAttribute -Record $Record -Names @('last_name', 'lastName'))
            return (($first, $last | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' ').Trim()
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

function Select-RecordInteractively {
    param(
        [Parameter(Mandatory)][object[]]$Rows,
        [Parameter(Mandatory)][string]$Label,
        [switch]$AllowNone
    )

    if ($Rows.Count -eq 0) {
        return $null
    }

    if ($Rows.Count -eq 1 -and -not $AllowNone) {
        return $Rows[0]
    }

    for ($i = 0; $i -lt $Rows.Count; $i++) {
        $row = $Rows[$i]
        Write-Host ("[{0}] {1} | {2}" -f ($i + 1), $row.Name, $row.Id)
    }

    if ($AllowNone) {
        Write-Host '[0] None'
    }

    while ($true) {
        $choiceText = Read-Host "Select $Label"
        $choice = 0
        if ([int]::TryParse($choiceText, [ref]$choice)) {
            if ($AllowNone -and $choice -eq 0) {
                return $null
            }
            if ($choice -ge 1 -and $choice -le $Rows.Count) {
                return $Rows[$choice - 1]
            }
        }

        Write-Host 'Enter one of the displayed numbers.' -ForegroundColor Yellow
    }
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
        [Parameter(Mandatory)][ValidateSet('GET','POST','PATCH')][string]$Method,
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

function Escape-ODataStringLiteral {
    param([Parameter(Mandatory)][string]$Value)

    return $Value.Replace("'", "''")
}

Write-Section 'GPI SPIRO TO BUSINESS CENTRAL UAT LINK'

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if ($QuoteEntryNo -eq 67) {
    throw 'Quote 67 is the pristine Charlie demo quote and is blocked from this script.'
}

Write-Host "Environment       : $EnvironmentName"
Write-Host "BC customer       : $BcCustomerNo"
Write-Host "Packaging quote   : $QuoteEntryNo"
Write-Host "Company search    : $CompanySearch"
Write-Host "Write mode        : $($Apply.IsPresent)"

Write-Section 'SPIRO TOKEN PREFLIGHT'
$spiroTokenState = Get-SpiroAccessToken -Path $TokenStorePath
$spiroAccessToken = [string]$spiroTokenState.AccessToken

Write-Section 'SPIRO COMPANY DISCOVERY'
$companies = Get-SpiroAllRecords -Resource companies -AccessToken $spiroAccessToken

$companyCandidates = @(
    foreach ($company in $companies) {
        $name = Get-SpiroDisplayName -Record $company -Kind company
        if ($name -and $name.IndexOf($CompanySearch, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            [pscustomobject]@{
                Id = Get-SpiroRecordId -Record $company
                Name = $name
                Url = Get-SpiroBrowserUrl -Record $company
                Raw = $company
            }
        }
    }
)

if ($companyCandidates.Count -eq 0) {
    throw "No Spiro companies matched '$CompanySearch'."
}

$selectedCompany = Select-RecordInteractively -Rows $companyCandidates -Label 'Spiro company'
Write-Host "Selected company  : $($selectedCompany.Name) [$($selectedCompany.Id)]" -ForegroundColor Green

Write-Section 'SPIRO OPPORTUNITY DISCOVERY'
$allOpportunities = Get-SpiroAllRecords -Resource opportunities -AccessToken $spiroAccessToken
$opportunityRows = @(
    foreach ($opportunity in $allOpportunities) {
        $companyId = Get-SpiroRelationshipId `
            -Record $opportunity `
            -RelationshipNames @('company', 'account') `
            -AttributeNames @('company_id', 'companyId', 'account_id', 'accountId')

        if ($companyId -eq $selectedCompany.Id) {
            [pscustomobject]@{
                Id = Get-SpiroRecordId -Record $opportunity
                Name = Get-SpiroDisplayName -Record $opportunity -Kind opportunity
                Stage = [string](Get-SpiroAttribute -Record $opportunity -Names @('stage_name', 'stage', 'status', 'sales_stage'))
                Owner = [string](Get-SpiroAttribute -Record $opportunity -Names @('owner_name', 'owner', 'assigned_to_name', 'sales_rep_name'))
                Url = Get-SpiroBrowserUrl -Record $opportunity
                Raw = $opportunity
            }
        }
    }
)

if ($opportunityRows.Count -eq 0) {
    Write-Host 'No Spiro opportunities were returned for the selected company.' -ForegroundColor Yellow
    $selectedOpportunity = $null
}
else {
    $opportunityRows |
        Select-Object Id, Name, Stage, Owner |
        Format-Table -AutoSize
    $selectedOpportunity = Select-RecordInteractively -Rows $opportunityRows -Label 'Spiro opportunity' -AllowNone
}

Write-Section 'SPIRO CONTACT DISCOVERY'
$allContacts = Get-SpiroAllRecords -Resource contacts -AccessToken $spiroAccessToken
$contactRows = @(
    foreach ($contact in $allContacts) {
        $companyId = Get-SpiroRelationshipId `
            -Record $contact `
            -RelationshipNames @('company', 'account') `
            -AttributeNames @('company_id', 'companyId', 'account_id', 'accountId')

        if ($companyId -eq $selectedCompany.Id) {
            [pscustomobject]@{
                Id = Get-SpiroRecordId -Record $contact
                Name = Get-SpiroDisplayName -Record $contact -Kind contact
                Email = [string](Get-SpiroAttribute -Record $contact -Names @('email', 'email_address', 'emailAddress'))
                Raw = $contact
            }
        }
    }
)

if ($contactRows.Count -eq 0) {
    Write-Host 'No Spiro contacts were returned for the selected company.' -ForegroundColor Yellow
    $selectedContact = $null
}
else {
    $contactRows |
        Select-Object Id, Name, Email |
        Format-Table -AutoSize
    $selectedContact = Select-RecordInteractively -Rows $contactRows -Label 'Spiro contact' -AllowNone
}

Write-Section 'SELECTED SPIRO CONTEXT'
Write-Host "Company           : $($selectedCompany.Name) [$($selectedCompany.Id)]"
Write-Host "Opportunity       : $(if ($selectedOpportunity) { "$($selectedOpportunity.Name) [$($selectedOpportunity.Id)]" } else { '(none)' })"
Write-Host "Opportunity stage : $(if ($selectedOpportunity) { $selectedOpportunity.Stage } else { '' })"
Write-Host "Opportunity owner : $(if ($selectedOpportunity) { $selectedOpportunity.Owner } else { '' })"
Write-Host "Contact           : $(if ($selectedContact) { "$($selectedContact.Name) [$($selectedContact.Id)]" } else { '(none)' })"

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

$customerFilterText = "bcCustomerNo eq '$(Escape-ODataStringLiteral -Value $BcCustomerNo)'"
$customerFilter = [uri]::EscapeDataString($customerFilterText)
$mappingResponse = Invoke-BcRequest `
    -Method GET `
    -Uri "$spiroBase/spiroCustomerMaps?`$filter=$customerFilter" `
    -Token $bcToken `
    -Body $null
$currentMapping = @($mappingResponse.value) | Select-Object -First 1

$quoteFilter = [uri]::EscapeDataString("quoteNo eq $QuoteEntryNo")
$quoteResponse = Invoke-BcRequest `
    -Method GET `
    -Uri "$spiroBase/spiroQuoteLinks?`$filter=$quoteFilter" `
    -Token $bcToken `
    -Body $null
$currentQuote = @($quoteResponse.value) | Select-Object -First 1

if (-not $currentQuote) {
    throw "Packaging quote $QuoteEntryNo was not returned by the Spiro quote-link API."
}

if ([string]$currentQuote.customerNo -ne $BcCustomerNo) {
    throw "Quote $QuoteEntryNo belongs to customer '$($currentQuote.customerNo)', not '$BcCustomerNo'. No write will be performed."
}

Write-Host "BC company        : $($bcCompany.name) [$bcCompanyId]"
Write-Host "Quote             : $($currentQuote.quoteNo)"
Write-Host "Quote customer    : $($currentQuote.customerNo) | $($currentQuote.customerName)"
Write-Host "Quote status      : $($currentQuote.status)"
Write-Host "Existing mapping  : $($null -ne $currentMapping)"
Write-Host "Existing Spiro opp: $($currentQuote.spiroOpportunityId)"

if (-not $Apply) {
    Write-Section 'DISCOVERY COMPLETE'
    Write-Host 'No Business Central records were changed.' -ForegroundColor Green
    Write-Host 'Re-run this script with -Apply to write the selected customer mapping and quote CRM context.'
    return
}

Write-Section 'WRITE CONFIRMATION'
Write-Host 'This write is limited to:'
Write-Host "  BC customer mapping for $BcCustomerNo"
Write-Host "  Spiro context fields on packaging quote $QuoteEntryNo"
Write-Host 'It does not change quote pricing, UOM, status, guardrail, approval, decision, or audit fields.'

$confirmation = Read-Host 'Type LINK to continue'
if ($confirmation -cne 'LINK') {
    throw 'Write cancelled. No Business Central records were changed.'
}

$syncAt = [datetime]::UtcNow.ToString('o')
$syncBy = [Environment]::UserName

$mappingBody = [ordered]@{
    bcCustomerNo = $BcCustomerNo
    spiroCompanyId = [string]$selectedCompany.Id
    spiroCompanyName = [string]$selectedCompany.Name
    spiroCompanyUrl = [string]$selectedCompany.Url
}

if ($currentMapping) {
    $mappingId = [string]$currentMapping.id
    $updatedMapping = Invoke-BcRequest `
        -Method PATCH `
        -Uri "$spiroBase/spiroCustomerMaps($mappingId)" `
        -Token $bcToken `
        -Body $mappingBody `
        -IfMatch '*'
}
else {
    $updatedMapping = Invoke-BcRequest `
        -Method POST `
        -Uri "$spiroBase/spiroCustomerMaps" `
        -Token $bcToken `
        -Body $mappingBody
}

$quoteBody = [ordered]@{
    spiroOpportunityId = $(if ($selectedOpportunity) { [string]$selectedOpportunity.Id } else { '' })
    spiroOpportunityName = $(if ($selectedOpportunity) { [string]$selectedOpportunity.Name } else { '' })
    spiroContactId = $(if ($selectedContact) { [string]$selectedContact.Id } else { '' })
    spiroContactName = $(if ($selectedContact) { [string]$selectedContact.Name } else { '' })
    spiroStage = $(if ($selectedOpportunity) { [string]$selectedOpportunity.Stage } else { '' })
    spiroOwner = $(if ($selectedOpportunity) { [string]$selectedOpportunity.Owner } else { '' })
    spiroOpportunityUrl = $(if ($selectedOpportunity) { [string]$selectedOpportunity.Url } else { '' })
    spiroLastSyncedAt = $syncAt
    spiroLastSyncedBy = $syncBy
}

$quoteId = [string]$currentQuote.id
$updatedQuote = Invoke-BcRequest `
    -Method PATCH `
    -Uri "$spiroBase/spiroQuoteLinks($quoteId)" `
    -Token $bcToken `
    -Body $quoteBody `
    -IfMatch '*'

$verifiedMappingResponse = Invoke-BcRequest `
    -Method GET `
    -Uri "$spiroBase/spiroCustomerMaps?`$filter=$customerFilter" `
    -Token $bcToken `
    -Body $null
$verifiedMapping = @($verifiedMappingResponse.value) | Select-Object -First 1

$verifiedQuoteResponse = Invoke-BcRequest `
    -Method GET `
    -Uri "$spiroBase/spiroQuoteLinks?`$filter=$quoteFilter" `
    -Token $bcToken `
    -Body $null
$verifiedQuote = @($verifiedQuoteResponse.value) | Select-Object -First 1

Write-Section 'LINK VERIFIED'
Write-Host "BC customer       : $($verifiedMapping.bcCustomerNo) | $($verifiedMapping.bcCustomerName)" -ForegroundColor Green
Write-Host "Spiro company     : $($verifiedMapping.spiroCompanyName) [$($verifiedMapping.spiroCompanyId)]"
Write-Host "Quote             : $($verifiedQuote.quoteNo) | $($verifiedQuote.status)"
Write-Host "Spiro opportunity : $($verifiedQuote.spiroOpportunityName) [$($verifiedQuote.spiroOpportunityId)]"
Write-Host "Spiro contact     : $($verifiedQuote.spiroContactName) [$($verifiedQuote.spiroContactId)]"
Write-Host "Spiro stage       : $($verifiedQuote.spiroStage)"
Write-Host "Spiro owner       : $($verifiedQuote.spiroOwner)"
Write-Host "Spiro synced at   : $($verifiedQuote.spiroLastSyncedAt)"
Write-Host ''
Write-Host 'SUCCESS: Spiro CRM context was linked to Business Central UAT.' -ForegroundColor Green
Write-Host 'Refresh the packaging quote card to display the Spiro CRM Context section.'
