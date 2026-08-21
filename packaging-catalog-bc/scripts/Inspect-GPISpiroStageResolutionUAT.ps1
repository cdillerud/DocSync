[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$OpportunityId = '3463019',
    [string]$StageId = '58573',
    [string]$PipelineId = '7528',
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

    if ($null -eq $Object) { return $null }

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $name } |
            Select-Object -First 1
        if ($property) { return $property.Value }
    }

    return $null
}

function Convert-SecretValueToText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }

    return [string]$Value
}

function Get-TokenContainer {
    param([Parameter(Mandatory)]$Root)

    $aliases = @('AccessToken', 'access_token', 'accessToken', 'Token')
    if ($null -ne (Get-PropertyValue -Object $Root -Names $aliases)) { return $Root }

    foreach ($name in @('Tokens', 'TokenData', 'OAuth', 'OAuthTokens', 'SpiroTokens')) {
        $candidate = Get-PropertyValue -Object $Root -Names @($name)
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue -Object $candidate -Names $aliases)) {
            return $candidate
        }
    }

    return $Root
}

function Get-RecordId {
    param([AllowNull()]$Record)
    return [string](Get-PropertyValue -Object $Record -Names @('id','Id'))
}

function Get-RecordName {
    param([AllowNull()]$Record)

    if ($null -eq $Record) { return '' }
    $attributes = Get-PropertyValue -Object $Record -Names @('attributes')
    if ($null -eq $attributes) { $attributes = $Record }

    return [string](Get-PropertyValue -Object $attributes -Names @('name','label','title','stage_name','display_name'))
}

function Invoke-SpiroGetSafe {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][hashtable]$Headers
    )

    $uri = "$SpiroApiBase/$RelativePath"
    try {
        $response = Invoke-RestMethod -Method GET -Uri $uri -Headers $Headers -TimeoutSec $TimeoutSeconds
        return [pscustomobject]@{
            Path = $RelativePath
            Success = $true
            Status = 200
            Response = $response
            Detail = ''
        }
    }
    catch {
        $status = ''
        if ($null -ne $_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = '' }
        }

        $detail = [string]$_.ErrorDetails.Message
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = $_.Exception.Message }
        if ($detail.Length -gt 500) { $detail = $detail.Substring(0, 500) }

        return [pscustomobject]@{
            Path = $RelativePath
            Success = $false
            Status = $status
            Response = $null
            Detail = $detail
        }
    }
}

function Get-ResponseRecords {
    param([AllowNull()]$Response)

    if ($null -eq $Response) { return @() }
    if ($Response.PSObject.Properties.Name -contains 'data') { return @($Response.data) }
    return @($Response)
}

function Find-StageRecord {
    param([AllowNull()]$Response)

    $candidates = [System.Collections.Generic.List[object]]::new()
    foreach ($record in (Get-ResponseRecords -Response $Response)) { $candidates.Add($record) }

    if ($null -ne $Response -and $Response.PSObject.Properties.Name -contains 'included') {
        foreach ($record in @($Response.included)) { $candidates.Add($record) }
    }

    foreach ($record in $candidates) {
        if ((Get-RecordId -Record $record) -eq $StageId) { return $record }
    }

    return $null
}

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro protected token store was not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
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

Write-Section 'GPI SPIRO STAGE RESOLUTION UAT INSPECTOR'
Write-Host "Opportunity ID  : $OpportunityId"
Write-Host "Stage ID        : $StageId"
Write-Host "Pipeline ID     : $PipelineId"
Write-Host 'Business Central: no calls or writes' -ForegroundColor Green
Write-Host 'Spiro           : GET only' -ForegroundColor Green

$probePaths = @(
    "opportunities/${OpportunityId}?include=opportunity_stage",
    "pipelines?include=opportunity_stage",
    "pipelines?include=opportunity_stages",
    "pipelines?include=stages",
    'opportunity_stages',
    'opportunity-stages',
    'stages',
    'pipeline_stages',
    'pipeline-stages',
    'sales_stages',
    'sales-stages',
    "pipelines/${PipelineId}/opportunity_stages",
    "pipelines/${PipelineId}/stages",
    "opportunities/${OpportunityId}/opportunity_stage",
    "opportunities/${OpportunityId}/relationships/opportunity_stage"
)

$resolved = $null
$successful = [System.Collections.Generic.List[string]]::new()

Write-Section 'PROBES'
foreach ($path in $probePaths) {
    $result = Invoke-SpiroGetSafe -RelativePath $path -Headers $headers
    Write-Host ''
    Write-Host "GET     : $($result.Path)"
    Write-Host "Success : $($result.Success)"
    Write-Host "HTTP    : $($result.Status)"

    if ($result.Success) {
        $successful.Add($result.Path)
        $records = Get-ResponseRecords -Response $result.Response
        Write-Host "Rows    : $($records.Count)"

        if ($null -ne $result.Response -and $result.Response.PSObject.Properties.Name -contains 'included') {
            Write-Host "Included: $(@($result.Response.included).Count)"
        }

        $match = Find-StageRecord -Response $result.Response
        if ($null -ne $match) {
            $resolved = $match
            Write-Host "MATCH   : $(Get-RecordName -Record $match) [$StageId]" -ForegroundColor Green
        }
    }
    else {
        Write-Host "Detail  : $($result.Detail)"
    }
}

Write-Section 'PIPELINE RECORD DETAIL'
$pipelineResult = Invoke-SpiroGetSafe -RelativePath 'pipelines' -Headers $headers
if ($pipelineResult.Success) {
    $pipelineRecord = @(Get-ResponseRecords -Response $pipelineResult.Response | Where-Object { (Get-RecordId -Record $_) -eq $PipelineId }) | Select-Object -First 1
    if ($null -eq $pipelineRecord) {
        Write-Host "Pipeline $PipelineId was not found."
    }
    else {
        Write-Host "Pipeline: $(Get-RecordName -Record $pipelineRecord) [$PipelineId]"
        $relationships = Get-PropertyValue -Object $pipelineRecord -Names @('relationships')
        if ($null -eq $relationships) {
            Write-Host 'Relationships: <none>'
        }
        else {
            Write-Host 'Relationships:'
            foreach ($property in $relationships.PSObject.Properties | Sort-Object Name) {
                $safeJson = $property.Value | ConvertTo-Json -Depth 8 -Compress
                Write-Host "  $($property.Name) = $safeJson"
            }
        }
    }
}
else {
    Write-Host "Pipeline collection failed: $($pipelineResult.Detail)"
}

Write-Section 'SUMMARY'
if ($null -ne $resolved) {
    Write-Host "Stage resolved : $(Get-RecordName -Record $resolved) [$StageId]" -ForegroundColor Green
}
else {
    Write-Host "Stage unresolved: $StageId" -ForegroundColor Yellow
}

Write-Host "Successful probe count: $($successful.Count)"
foreach ($path in $successful) { Write-Host "  $path" }

Write-Host ''
Write-Host 'This inspector makes no Business Central changes.' -ForegroundColor Green
$accessToken = $null
