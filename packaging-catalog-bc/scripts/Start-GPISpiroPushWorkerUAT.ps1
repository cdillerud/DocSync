[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$MaxItems = 25,
    [int]$MaxAttempts = 3,
    [int]$RetryDelayMinutes = 5,
    [int]$StaleProcessingMinutes = 15,
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$LogDirectory = "$env:LOCALAPPDATA\GPI\SpiroPushWorker\Logs",
    [string]$StateDirectory = "$env:LOCALAPPDATA\GPI\SpiroPushWorker\State",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This operational worker is restricted to Sandbox_NoZetadocs_UAT. Requested: $EnvironmentName"
}
if ($StaleProcessingMinutes -lt 5 -or $StaleProcessingMinutes -gt 1440) {
    throw 'StaleProcessingMinutes must be between 5 and 1440.'
}
if ($MaxItems -lt 1 -or $MaxItems -gt 100) {
    throw 'MaxItems must be between 1 and 100.'
}
if ($MaxAttempts -lt 1 -or $MaxAttempts -gt 10) {
    throw 'MaxAttempts must be between 1 and 10.'
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

$batchWorker = Join-Path $PSScriptRoot 'Process-GPISpiroPushQueueBatchUAT.ps1'
if (-not (Test-Path -LiteralPath $batchWorker)) {
    throw "Batch worker not found: $batchWorker"
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null

$runId = [guid]::NewGuid().ToString('N')
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $LogDirectory "SpiroPushWorker-$timestamp-$runId.log"
$lockPath = Join-Path $StateDirectory 'SpiroPushWorker-UAT.lock'
$lockStream = $null
$transcriptStarted = $false

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','PATCH')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [AllowNull()]$Body,
        [string]$IfMatch = ''
    )
    $headers = @{ Authorization = "Bearer $Token"; Accept = 'application/json' }
    if (-not [string]::IsNullOrWhiteSpace($IfMatch)) {
        $headers['If-Match'] = $IfMatch
    }
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds
    }
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
}

try {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "Another GPI Spiro push worker instance appears to be running. Lock file: $lockPath"
    }

    Start-Transcript -LiteralPath $logPath -Force | Out-Null
    $transcriptStarted = $true

    Write-Section 'GPI SPIRO PUSH WORKER OPERATIONS UAT'
    Write-Host "Run ID                   : $runId"
    Write-Host "Apply                    : $($Apply.IsPresent)"
    Write-Host "Max Items                : $MaxItems"
    Write-Host "Max Attempts             : $MaxAttempts"
    Write-Host "Retry Delay Minutes      : $RetryDelayMinutes"
    Write-Host "Stale Processing Minutes : $StaleProcessingMinutes"
    Write-Host "Log                      : $logPath"
    Write-Host "Lock                     : $lockPath"

    Write-Section 'AZURE SERVICE PRINCIPAL BOOTSTRAP LOGIN'
    $bootstrapPath = "$env:LOCALAPPDATA\GPI\AzureBootstrap\gpi-azure-sp-uat.clixml"
    if (-not (Test-Path -LiteralPath $bootstrapPath)) { throw "Azure service-principal bootstrap not found: $bootstrapPath" }
    $bootstrap = Import-Clixml -LiteralPath $bootstrapPath
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($bootstrap.ClientSecret)
    try {
        $bootstrapSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $loginOutput = & az login --service-principal --username $bootstrap.ClientId --password $bootstrapSecret --tenant $bootstrap.TenantId --allow-no-subscriptions --output none --only-show-errors 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Azure service-principal login failed. $(@($loginOutput)-join [Environment]::NewLine)" }
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        $bootstrapSecret = $null
    }
    Write-Host 'PASS: noninteractive Azure service-principal login succeeded.' -ForegroundColor Green

    Write-Section 'SPIRO KEY VAULT TOKEN LIFECYCLE'
    $refreshHelper = Join-Path $PSScriptRoot 'Update-GPISpiroKeyVaultTokenUAT.ps1'
    if (-not (Test-Path -LiteralPath $refreshHelper)) {
        throw "Spiro Key Vault lifecycle helper not found: $refreshHelper"
    }
    $refreshArgs = @{
        RefreshWithinMinutes = 120
        KeyVaultName         = $KeyVaultName
        TimeoutSeconds       = $TimeoutSeconds
    }
    if ($Apply) { $refreshArgs.Apply = $true }
    & $refreshHelper @refreshArgs

    Write-Section 'AUTHENTICATE TO BUSINESS CENTRAL'
    $secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
    if ([string]::IsNullOrWhiteSpace($secret)) {
        throw 'Could not retrieve BC client secret.'
    }
    try {
        $auth = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
            grant_type    = 'client_credentials'
            client_id     = $BcClientId
            client_secret = $secret
            scope         = 'https://api.businesscentral.dynamics.com/.default'
        } -TimeoutSec $TimeoutSeconds
    }
    finally {
        $secret = $null
    }

    $token = [string]$auth.access_token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'BC authentication did not return an access token.'
    }

    $bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
    $companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $token -Body $null
    $company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
    if (-not $company) {
        throw "BC company '$CompanyName' not found."
    }
    $base = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($($company.id))"

    Write-Section 'STALE PROCESSING RECOVERY'
    $processingUri = "$base/spiroPushRequests?`$filter=status eq 'Processing'&`$orderby=entryNo asc&`$top=100"
    $processingResponse = Invoke-BcRequest -Method GET -Uri $processingUri -Token $token -Body $null
    $processingRows = @($processingResponse.value)
    $cutoff = [datetime]::UtcNow.AddMinutes(-1 * $StaleProcessingMinutes)
    $staleRows = @($processingRows | Where-Object {
        if ([string]::IsNullOrWhiteSpace([string]$_.lastAttemptAt)) {
            return $true
        }
        try {
            ([datetime]$_.lastAttemptAt).ToUniversalTime() -le $cutoff
        }
        catch {
            $true
        }
    })

    Write-Host "Processing rows returned : $($processingRows.Count)"
    Write-Host "Stale rows detected      : $($staleRows.Count)"

    foreach ($row in $staleRows) {
        $entryNo = [int]$row.entryNo
        $message = "Recovered stale Processing request after $StaleProcessingMinutes minute threshold."
        if (-not $Apply) {
            Write-Host "Would recover Queue Entry $entryNo to Retry." -ForegroundColor Yellow
            continue
        }

        $queueId = [string]$row.id
        if ([string]::IsNullOrWhiteSpace($queueId)) {
            throw "Queue Entry $entryNo did not include a SystemId."
        }
        Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body ([ordered]@{
            status        = 'Retry'
            nextAttemptAt = [datetime]::UtcNow.ToString('o')
            lastError     = $message
            message       = $message
        }) | Out-Null
        Write-Host "Recovered Queue Entry $entryNo to Retry." -ForegroundColor Green
    }

    Write-Section 'RUN BATCH PROCESSOR'
    $batchArgs = @{
        MaxItems          = $MaxItems
        MaxAttempts       = $MaxAttempts
        RetryDelayMinutes = $RetryDelayMinutes
        ProjectPath       = $ProjectPath
        TenantId          = $TenantId
        BcClientId        = $BcClientId
        EnvironmentName   = $EnvironmentName
        CompanyName       = $CompanyName
        KeyVaultName      = $KeyVaultName
        TimeoutSeconds    = $TimeoutSeconds
    }
    if ($Apply) {
        $batchArgs.Apply = $true
    }

    & $batchWorker @batchArgs

    Write-Section 'OPERATIONAL WORKER COMPLETE'
    Write-Host "Run ID : $runId" -ForegroundColor Green
    Write-Host "Log    : $logPath" -ForegroundColor Green
    if ($Apply) {
        Write-Host 'Mode   : APPLY' -ForegroundColor Green
    }
    else {
        Write-Host 'Mode   : DRY RUN, no records changed' -ForegroundColor Green
    }
}
catch {
    Write-Host "WORKER FAILED: $($_.Exception.Message)" -ForegroundColor Red
    throw
}
finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}