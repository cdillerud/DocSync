[CmdletBinding()]
param(
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$EnvironmentName = 'Sandbox_NoZetadocs_UAT'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI PACKAGING QUOTE WRITE-ACTION DISCOVERY UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Tenant      : $TenantId"
Write-Host "Environment : $EnvironmentName"
Write-Host 'READ ONLY: metadata inspection only. No Business Central records are changed.' -ForegroundColor Green

if (-not (Get-Command Get-AzAccessToken -ErrorAction SilentlyContinue)) {
    throw 'Get-AzAccessToken is not available. Connect with Az.Accounts first.'
}

$tokenResult = Get-AzAccessToken -ResourceUrl 'https://api.businesscentral.dynamics.com'
if ($tokenResult.Token -is [Security.SecureString]) {
    $accessToken = [System.Net.NetworkCredential]::new('', $tokenResult.Token).Password
}
else {
    $accessToken = [string]$tokenResult.Token
}
if ([string]::IsNullOrWhiteSpace($accessToken)) { throw 'Business Central API token was not returned.' }

$headers = @{ Authorization = "Bearer $accessToken"; Accept = 'application/xml' }
$metadataUri = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName/api/gpi/packagingQuotes/v1.0/`$metadata"

Write-Host ''
Write-Host "Metadata URI : $metadataUri" -ForegroundColor DarkGray

$raw = Invoke-WebRequest -Method Get -Uri $metadataUri -Headers $headers -ErrorAction Stop
$xmlText = [string]$raw.Content
if ([string]::IsNullOrWhiteSpace($xmlText)) { throw 'Metadata response was empty.' }

[xml]$xml = $xmlText
$ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$ns.AddNamespace('edmx','http://docs.oasis-open.org/odata/ns/edmx')
$ns.AddNamespace('edm','http://docs.oasis-open.org/odata/ns/edm')

$actions = @($xml.SelectNodes('//edm:Action',$ns))
$functions = @($xml.SelectNodes('//edm:Function',$ns))

$interesting = @()
foreach ($node in @($actions + $functions)) {
    $name = [string]$node.Name
    $isBound = [string]$node.IsBound
    $params = @($node.SelectNodes('./edm:Parameter',$ns))
    $bindingType = if ($params.Count -gt 0) { [string]$params[0].Type } else { '' }
    $allParamText = ($params | ForEach-Object { "$($_.Name):$($_.Type)" }) -join '; '

    if (
        $name -match '(?i)reopen|approve|reject|evaluate|ready' -or
        $bindingType -match '(?i)packagingquote' -or
        $allParamText -match '(?i)packagingquote'
    ) {
        $interesting += [pscustomobject]@{
            Kind        = $node.LocalName
            Name        = $name
            IsBound     = $isBound
            BindingType = $bindingType
            Parameters  = $allParamText
        }
    }
}

Write-Host ''
Write-Host 'DISCOVERED ACTION/FUNCTION CONTRACT' -ForegroundColor Yellow
if ($interesting.Count -eq 0) {
    Write-Warning 'No matching bound actions/functions were found in the metadata.'
}
else {
    $interesting | Sort-Object Kind,Name | Format-Table -AutoSize -Wrap
}

$reopen = @($interesting | Where-Object { $_.Name -match '(?i)reopen' })
Write-Host ''
if ($reopen.Count -eq 0) {
    Write-Host 'RESULT: no Reopen action was discovered. Do not attempt a write yet.' -ForegroundColor Yellow
    exit 2
}

Write-Host "RESULT: discovered $($reopen.Count) Reopen action candidate(s)." -ForegroundColor Green
$reopen | Format-List
Write-Host 'NEXT: use the exact discovered bound-action name to build the controlled Quote 55 reopen execution test.' -ForegroundColor Cyan
