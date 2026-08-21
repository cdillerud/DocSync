[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$OpportunityId = '3463019',
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SpiroApiBase = 'https://api.spiro.ai/api/v1'

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

    $aliases = @('AccessToken', 'access_token', 'accessToken', 'Token')
    if ($null -ne (Get-PropertyValue -Object $Root -Names $aliases)) {
        return $Root
    }

    foreach ($name in @('Tokens', 'TokenData', 'OAuth', 'OAuthTokens', 'SpiroTokens')) {
        $candidate = Get-PropertyValue -Object $Root -Names @($name)
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue -Object $candidate -Names $aliases)) {
            return $candidate
        }
    }

    return $Root
}

function Test-SensitivePropertyName {
    param([Parameter(Mandatory)][string]$Name)

    return $Name -match '(?i)token|secret|password|credential|api[_-]?key|authorization'
}

function Format-SafeValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [AllowNull()]$Value
    )

    if (Test-SensitivePropertyName -Name $Name) {
        return '<redacted>'
    }

    if ($null -eq $Value) {
        return '<null>'
    }

    if ($Value -is [string] -or $Value.GetType().IsPrimitive -or $Value -is [datetime]) {
        return [string]$Value
    }

    return ($Value | ConvertTo-Json -Depth 8 -Compress)
}

function Get-RecordFromResponse {
    param([AllowNull()]$Response)

    if ($null -eq $Response) {
        return $null
    }

    if ($Response.PSObject.Properties.Name -contains 'data') {
        return $Response.data
    }

    return $Response
}

function Show-Record {
    param(
        [Parameter(Mandatory)][string]$Label,
        [AllowNull()]$Response
    )

    Write-Host ''
    Write-Host $Label -ForegroundColor Cyan

    $record = Get-RecordFromResponse -Response $Response
    if ($null -eq $record) {
        Write-Host '<no record>'
        return
    }

    Write-Host "ID   : $([string](Get-PropertyValue -Object $record -Names @('id','Id')))"
    Write-Host "Type : $([string](Get-PropertyValue -Object $record -Names @('type','Type')))"

    $attributes = Get-PropertyValue -Object $record -Names @('attributes')
    if ($null -eq $attributes) {
        Write-Host 'Attributes: <none>'
        return
    }

    Write-Host 'Attributes:'
    foreach ($property in $attributes.PSObject.Properties | Sort-Object Name) {
        Write-Host ("  {0} = {1}" -f $property.Name, (Format-SafeValue -Name $property.Name -Value $property.Value))
    }
}

function Invoke-SpiroGetSafe {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][hashtable]$Headers
    )

    $uri = "$SpiroApiBase/$RelativePath"

    try {
        $response = Invoke-RestMethod `
            -Method GET `
            -Uri $uri `
            -Headers $Headers `
            -TimeoutSec $TimeoutSeconds

        return [pscustomobject]@{
            Path = $RelativePath
            Success = $true
            Status = 200
            Response = $response
            Error = ''
        }
    }
    catch {
        $status = ''
        if ($null -ne $_.Exception.Response) {
            try {
                $status = [int]$_.Exception.Response.StatusCode
            }
            catch {
                $status = ''
            }
        }

        return [pscustomobject]@{
            Path = $RelativePath
            Success = $false
            Status = $status
            Response = $null
            Error = $_.Exception.Message
        }
    }
}

function Get-RelationshipDescriptor {
    param(
        [AllowNull()]$Relationships,
        [Parameter(Mandatory)][string]$Name
    )

    if ($null -eq $Relationships) {
        return $null
    }

    $relationship = Get-PropertyValue -Object $Relationships -Names @($Name)
    if ($null -eq $relationship) {
        return $null
    }

    $data = Get-PropertyValue -Object $relationship -Names @('data')
    if ($null -eq $data) {
        return $null
    }

    return [pscustomobject]@{
        Name = $Name
        Id = [string](Get-PropertyValue -Object $data -Names @('id','Id'))
        Type = [string](Get-PropertyValue -Object $data -Names @('type','Type'))
    }
}

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro protected token store was not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
if ($null -eq $root) {
    throw "Spiro token store could not be loaded: $TokenStorePath"
}

$container = Get-TokenContainer -Root $root
$accessValue = Get-PropertyValue -Object $container -Names @('AccessToken', 'access_token', 'accessToken', 'Token')
$accessToken = Convert-SecretValueToText -Value $accessValue

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'No Spiro access token was found in the protected token store.'
}

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept = 'application/json'
    'X-Api-Version' = '1'
}

Write-Section 'GPI SPIRO OPPORTUNITY RELATIONSHIP INSPECTOR'
Write-Host "Token store     : $TokenStorePath"
Write-Host "Opportunity ID  : $OpportunityId"
Write-Host 'Business Central: no calls or writes' -ForegroundColor Green
Write-Host 'Spiro           : GET only' -ForegroundColor Green

$opportunityResult = Invoke-SpiroGetSafe -RelativePath "opportunities/$OpportunityId" -Headers $headers
if (-not $opportunityResult.Success) {
    throw "Could not read Spiro opportunity $OpportunityId. HTTP $($opportunityResult.Status): $($opportunityResult.Error)"
}

$opportunityRecord = Get-RecordFromResponse -Response $opportunityResult.Response
$relationships = Get-PropertyValue -Object $opportunityRecord -Names @('relationships')

Write-Section 'RELATIONSHIP IDS'
$stageRel = Get-RelationshipDescriptor -Relationships $relationships -Name 'opportunity_stage'
$userRel = Get-RelationshipDescriptor -Relationships $relationships -Name 'user'
$pipelineRel = Get-RelationshipDescriptor -Relationships $relationships -Name 'pipeline'
$companyRel = Get-RelationshipDescriptor -Relationships $relationships -Name 'company'

foreach ($rel in @($companyRel, $stageRel, $pipelineRel, $userRel)) {
    if ($null -ne $rel) {
        Write-Host ("{0} = {1} [{2}]" -f $rel.Name, $rel.Id, $rel.Type)
    }
}

Write-Section 'INCLUDE PROBE'
$includePath = "opportunities/$OpportunityId?include=opportunity_stage,user,pipeline,company"
$includeResult = Invoke-SpiroGetSafe -RelativePath $includePath -Headers $headers
Write-Host "GET $includePath"
Write-Host "Success : $($includeResult.Success)"
Write-Host "HTTP    : $($includeResult.Status)"
if ($includeResult.Success) {
    $included = Get-PropertyValue -Object $includeResult.Response -Names @('included')
    if ($null -eq $included) {
        Write-Host 'Included: <none>'
    }
    else {
        Write-Host "Included records: $(@($included).Count)"
        foreach ($item in @($included)) {
            Show-Record -Label 'Included record' -Response $item
        }
    }
}
else {
    Write-Host "Error   : $($includeResult.Error)"
}

Write-Section 'DIRECT RELATED RESOURCE PROBES'
$probes = [System.Collections.Generic.List[object]]::new()

if ($null -ne $stageRel -and -not [string]::IsNullOrWhiteSpace($stageRel.Id)) {
    foreach ($path in @(
        "opportunity_stages/$($stageRel.Id)",
        "opportunity-stages/$($stageRel.Id)",
        "stages/$($stageRel.Id)"
    )) {
        $probes.Add((Invoke-SpiroGetSafe -RelativePath $path -Headers $headers))
    }
}

if ($null -ne $userRel -and -not [string]::IsNullOrWhiteSpace($userRel.Id)) {
    foreach ($path in @(
        "users/$($userRel.Id)",
        "user/$($userRel.Id)"
    )) {
        $probes.Add((Invoke-SpiroGetSafe -RelativePath $path -Headers $headers))
    }
}

if ($null -ne $pipelineRel -and -not [string]::IsNullOrWhiteSpace($pipelineRel.Id)) {
    foreach ($path in @(
        "pipelines/$($pipelineRel.Id)",
        "pipeline/$($pipelineRel.Id)"
    )) {
        $probes.Add((Invoke-SpiroGetSafe -RelativePath $path -Headers $headers))
    }
}

foreach ($probe in $probes) {
    Write-Host ''
    Write-Host "GET $($probe.Path)"
    Write-Host "Success : $($probe.Success)"
    Write-Host "HTTP    : $($probe.Status)"

    if ($probe.Success) {
        Show-Record -Label 'Resolved record' -Response $probe.Response
    }
    else {
        Write-Host "Error   : $($probe.Error)"
    }
}

Write-Section 'SUMMARY'
$successfulPaths = @($probes | Where-Object Success | Select-Object -ExpandProperty Path)
if ($successfulPaths.Count -eq 0) {
    Write-Host 'No direct related-resource candidate endpoint succeeded.' -ForegroundColor Yellow
}
else {
    Write-Host 'Successful direct endpoints:' -ForegroundColor Green
    foreach ($path in $successfulPaths) {
        Write-Host "  $path"
    }
}

Write-Host ''
Write-Host 'The opportunity payload has no direct contact relationship and no browser URL.'
Write-Host 'This script makes no Business Central changes.' -ForegroundColor Green

$accessToken = $null
Write-Host ''
Write-Host 'Inspection complete.' -ForegroundColor Green
