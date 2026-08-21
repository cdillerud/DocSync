[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$StageId = '58573',
    [string]$PipelineId = '7528',
    [int]$PageSize = 100,
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

function Get-DataRows {
    param([AllowNull()]$Response)

    if ($null -eq $Response) {
        return @()
    }

    if ($Response.PSObject.Properties.Name -contains 'data') {
        return @($Response.data)
    }

    return @($Response)
}

function Get-RecordId {
    param([AllowNull()]$Record)

    return [string](Get-PropertyValue -Object $Record -Names @('id', 'Id', '_id'))
}

function Get-RecordName {
    param([AllowNull()]$Record)

    if ($null -eq $Record) {
        return ''
    }

    $attributes = Get-PropertyValue -Object $Record -Names @('attributes')
    if ($null -ne $attributes) {
        $name = Get-PropertyValue -Object $attributes -Names @('name', 'stage_name', 'title', 'label')
        if ($null -ne $name) {
            return [string]$name
        }
    }

    return [string](Get-PropertyValue -Object $Record -Names @('name', 'stage_name', 'title', 'label'))
}

function Show-CollectionProbe {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)]$Result,
        [string]$TargetId = ''
    )

    Write-Section $Label
    Write-Host "GET     : $($Result.Path)"
    Write-Host "Success : $($Result.Success)"
    Write-Host "HTTP    : $($Result.Status)"

    if (-not $Result.Success) {
        Write-Host "Error   : $($Result.Error)"
        return
    }

    $rows = @(Get-DataRows -Response $Result.Response)
    Write-Host "Rows    : $($rows.Count)"
    Write-Host "Fields  : $($Result.Response.PSObject.Properties.Name -join ', ')"

    if ($Result.Response.PSObject.Properties.Name -contains 'meta') {
        Write-Host 'Meta:'
        Write-Host ($Result.Response.meta | ConvertTo-Json -Depth 8 -Compress)
    }

    if (-not [string]::IsNullOrWhiteSpace($TargetId)) {
        $match = @($rows | Where-Object { (Get-RecordId -Record $_) -eq $TargetId }) | Select-Object -First 1
        if ($match) {
            Write-Host "MATCH   : $(Get-RecordName -Record $match) [$TargetId]" -ForegroundColor Green
            $attributes = Get-PropertyValue -Object $match -Names @('attributes')
            if ($null -ne $attributes) {
                Write-Host 'Attributes:'
                foreach ($property in $attributes.PSObject.Properties | Sort-Object Name) {
                    $value = if ($null -eq $property.Value) { '<null>' } elseif ($property.Value -is [string] -or $property.Value.GetType().IsPrimitive -or $property.Value -is [datetime]) { [string]$property.Value } else { $property.Value | ConvertTo-Json -Depth 8 -Compress }
                    Write-Host ("  {0} = {1}" -f $property.Name, $value)
                }
            }
        }
        else {
            Write-Host "MATCH   : <target id $TargetId not found on this page>" -ForegroundColor Yellow
        }
    }

    Write-Host 'First 10 records:'
    $rows |
        Select-Object -First 10 |
        ForEach-Object {
            [pscustomobject]@{
                Id = Get-RecordId -Record $_
                Name = Get-RecordName -Record $_
                Type = [string](Get-PropertyValue -Object $_ -Names @('type', 'Type'))
            }
        } |
        Format-Table -AutoSize |
        Out-Host
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

Write-Section 'GPI SPIRO STAGE CATALOG UAT INSPECTOR'
Write-Host "Token store : $TokenStorePath"
Write-Host "Stage ID    : $StageId"
Write-Host "Pipeline ID : $PipelineId"
Write-Host 'Business Central: no calls or writes' -ForegroundColor Green
Write-Host 'Spiro           : GET only' -ForegroundColor Green

$stagePath = "opportunity_stages?page%5Bnumber%5D=1&page%5Bsize%5D=$PageSize"
$pipelinePath = "pipelines?page%5Bnumber%5D=1&page%5Bsize%5D=$PageSize"

$stageResult = Invoke-SpiroGetSafe -RelativePath $stagePath -Headers $headers
$pipelineResult = Invoke-SpiroGetSafe -RelativePath $pipelinePath -Headers $headers

Show-CollectionProbe -Label 'OPPORTUNITY STAGES COLLECTION' -Result $stageResult -TargetId $StageId
Show-CollectionProbe -Label 'PIPELINES COLLECTION' -Result $pipelineResult -TargetId $PipelineId

Write-Section 'SUMMARY'
if ($stageResult.Success) {
    $stageRows = @(Get-DataRows -Response $stageResult.Response)
    $stageMatch = @($stageRows | Where-Object { (Get-RecordId -Record $_) -eq $StageId }) | Select-Object -First 1
    if ($stageMatch) {
        Write-Host "Stage resolved   : $(Get-RecordName -Record $stageMatch) [$StageId]" -ForegroundColor Green
    }
    else {
        Write-Host "Stage unresolved : collection succeeded, target was not on page 1" -ForegroundColor Yellow
    }
}
else {
    Write-Host 'Stage unresolved : opportunity_stages collection endpoint failed' -ForegroundColor Yellow
}

if ($pipelineResult.Success) {
    $pipelineRows = @(Get-DataRows -Response $pipelineResult.Response)
    $pipelineMatch = @($pipelineRows | Where-Object { (Get-RecordId -Record $_) -eq $PipelineId }) | Select-Object -First 1
    if ($pipelineMatch) {
        Write-Host "Pipeline resolved: $(Get-RecordName -Record $pipelineMatch) [$PipelineId]" -ForegroundColor Green
    }
    else {
        Write-Host "Pipeline unresolved: collection succeeded, target was not on page 1" -ForegroundColor Yellow
    }
}
else {
    Write-Host 'Pipeline unresolved: pipelines collection endpoint failed' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Inspection complete.' -ForegroundColor Green
$accessToken = $null
