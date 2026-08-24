[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$SubscriptionId = '4e083304-514c-4751-855e-c38a1740a924',
    [string]$ResourceGroupName = 'rg-gamer-bc-activity-sandbox',
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$ServicePrincipalObjectId = '8026150a-fcf9-40da-81cd-da4d9333c6da',
    [string]$RoleName = 'Key Vault Secrets Officer'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI KEY VAULT SERVICE PRINCIPAL RBAC UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Subscription ID : $SubscriptionId"
Write-Host "Resource Group  : $ResourceGroupName"
Write-Host "Key Vault       : $KeyVaultName"
Write-Host "Principal OID   : $ServicePrincipalObjectId"
Write-Host "Role            : $RoleName"
Write-Host "Apply           : $($Apply.IsPresent)"

$account = & az account show --output json --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($account)) {
    throw 'No active Azure CLI session. Run az login first.'
}

& az account set --subscription $SubscriptionId --only-show-errors
if ($LASTEXITCODE -ne 0) {
    throw "Could not select subscription $SubscriptionId."
}

$scope = (& az keyvault show --name $KeyVaultName --resource-group $ResourceGroupName --query id --output tsv --only-show-errors)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($scope)) {
    throw "Could not resolve Key Vault resource ID for $KeyVaultName."
}
$scope = $scope.Trim()

Write-Host "Scope           : $scope"

$existing = & az role assignment list `
    --assignee-object-id $ServicePrincipalObjectId `
    --scope $scope `
    --query "[?roleDefinitionName=='$RoleName'].{role:roleDefinitionName,principalId:principalId,scope:scope}" `
    --output json `
    --only-show-errors

if ($LASTEXITCODE -ne 0) {
    throw 'Could not inspect existing role assignments.'
}

$existingObj = $existing | ConvertFrom-Json
if (@($existingObj).Count -gt 0) {
    Write-Host 'PASS: required Key Vault role assignment already exists.' -ForegroundColor Green
    return
}

if (-not $Apply) {
    Write-Host ''
    Write-Host 'PREVIEW ONLY. No RBAC assignment was created.' -ForegroundColor Yellow
    Write-Host "Would assign '$RoleName' to service principal object $ServicePrincipalObjectId at the Key Vault scope." -ForegroundColor Cyan
    return
}

& az role assignment create `
    --assignee-object-id $ServicePrincipalObjectId `
    --assignee-principal-type ServicePrincipal `
    --role $RoleName `
    --scope $scope `
    --output none `
    --only-show-errors

if ($LASTEXITCODE -ne 0) {
    throw "Failed to assign '$RoleName' at Key Vault scope."
}

Write-Host "PASS: assigned '$RoleName' to the service principal at Key Vault scope." -ForegroundColor Green
Write-Host 'Azure RBAC propagation can take a few minutes before data-plane secret access succeeds.' -ForegroundColor Yellow
