[CmdletBinding()]
param(
    [Parameter()]
    [string]$AppPath = (Split-Path -Parent $PSScriptRoot),

    [Parameter()]
    [int]$ObjectFrom = 71000,

    [Parameter()]
    [int]$ObjectTo = 71199
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $AppPath)) {
    throw "App path does not exist: $AppPath"
}

$AppJsonPath = Join-Path $AppPath 'app.json'
$LaunchJsonPath = Join-Path $AppPath '.vscode\launch.json'

$AppJson = Get-Content -LiteralPath $AppJsonPath -Raw | ConvertFrom-Json
$LaunchJson = Get-Content -LiteralPath $LaunchJsonPath -Raw | ConvertFrom-Json

$Errors = [System.Collections.Generic.List[string]]::new()

if ($AppJson.name -ne 'GPI Packaging Catalog') {
    $Errors.Add("Unexpected app name: $($AppJson.name)")
}

$Range = $AppJson.idRanges | Select-Object -First 1
if (($Range.from -ne $ObjectFrom) -or ($Range.to -ne $ObjectTo)) {
    $Errors.Add("Unexpected object range: $($Range.from)..$($Range.to)")
}

$Launch = $LaunchJson.configurations | Select-Object -First 1
if ($Launch.environmentName -ne 'Sandbox_NoZetadocs_UAT') {
    $Errors.Add("Unexpected launch environment: $($Launch.environmentName)")
}

$ObjectPattern = '^\s*(table|page|codeunit|enum|permissionset)\s+(\d+)\s+"([^\"]+)"'
$Seen = @{}
$Objects = @()

Get-ChildItem -LiteralPath (Join-Path $AppPath 'src') -Filter '*.al' -File -Recurse | ForEach-Object {
    $Text = Get-Content -LiteralPath $_.FullName -Raw

    if ($Text -match [char]0x2014) {
        $Errors.Add("Em dash found: $($_.FullName)")
    }

    $Match = [regex]::Match($Text, $ObjectPattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $Match.Success) {
        $Errors.Add("Could not parse AL object header: $($_.FullName)")
        return
    }

    $Type = $Match.Groups[1].Value.ToLowerInvariant()
    $Id = [int]$Match.Groups[2].Value
    $Name = $Match.Groups[3].Value
    $Key = "$Type/$Id"

    if (($Id -lt $ObjectFrom) -or ($Id -gt $ObjectTo)) {
        $Errors.Add("Object is outside $ObjectFrom..${ObjectTo}: $Key $Name")
    }

    if ($Seen.ContainsKey($Key)) {
        $Errors.Add("Duplicate object ID/type $Key in $($_.FullName) and $($Seen[$Key])")
    }
    else {
        $Seen[$Key] = $_.FullName
    }

    $Objects += [pscustomobject]@{
        Type = $Type
        Id = $Id
        Name = $Name
        File = $_.FullName
    }
}

if ($Errors.Count -gt 0) {
    Write-Host 'GPI Packaging Catalog scaffold validation FAILED.' -ForegroundColor Red
    $Errors | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}

Write-Host 'GPI Packaging Catalog scaffold validation PASSED.' -ForegroundColor Green
Write-Host "Environment : $($Launch.environmentName)"
Write-Host "Object range : $ObjectFrom..$ObjectTo"
Write-Host "AL objects   : $($Objects.Count)"
$Objects | Sort-Object Id, Type | Format-Table Type, Id, Name -AutoSize
