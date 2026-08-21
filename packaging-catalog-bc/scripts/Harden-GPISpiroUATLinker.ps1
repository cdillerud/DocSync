[CmdletBinding()]
param(
    [string]$LinkerPath = "$PSScriptRoot\Link-GPISpiroUATContext.ps1"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $LinkerPath)) {
    throw "Linker script not found: $LinkerPath"
}

$backupPath = "$LinkerPath.before-pagination-hardening-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $LinkerPath -Destination $backupPath -Force

$text = Get-Content -LiteralPath $LinkerPath -Raw
$changed = $false

if ($text.Contains('[int]$MaxPages = 100,')) {
    $text = $text.Replace('[int]$MaxPages = 100,', '[int]$MaxPages = 500,')
    $changed = $true
}

$oldUri1 = '$uri = "$SpiroApiBase/$Resource?page[number]=$page&page[size]=$PageSize"'
$oldUri2 = '$uri = "$SpiroApiBase/${Resource}?page[number]=$page&page[size]=$PageSize"'
$newUri = '$uri = "$SpiroApiBase/${Resource}?page%5Bnumber%5D=$page&page%5Bsize%5D=$PageSize"'

if ($text.Contains($oldUri1)) {
    $text = $text.Replace($oldUri1, $newUri)
    $changed = $true
}
elseif ($text.Contains($oldUri2)) {
    $text = $text.Replace($oldUri2, $newUri)
    $changed = $true
}

$oldPaging = @'
        if ($data.Count -lt $PageSize) {
            break
        }
'@

$newPaging = @'
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
                throw "Spiro $Resource requires $totalPages pages, which exceeds MaxPages $MaxPages. Increase MaxPages explicitly."
            }

            if ($currentPage -ge $totalPages) {
                break
            }
        }
        elseif ($data.Count -lt $PageSize) {
            break
        }
'@

if ($text.Contains($oldPaging)) {
    $text = $text.Replace($oldPaging, $newPaging)
    $changed = $true
}
elseif (-not $text.Contains('$totalPagesValue = Get-PropertyValue')) {
    throw 'Expected paging block was not found and hardened paging logic is not already present.'
}

$companyLine = '$companies = Get-SpiroAllRecords -Resource companies -AccessToken $spiroAccessToken'
$countLine = 'Write-Host "Spiro companies retrieved: $($companies.Count)"'
if ($text.Contains($companyLine) -and -not $text.Contains($countLine)) {
    $text = $text.Replace($companyLine, "$companyLine`r`n$countLine")
    $changed = $true
}

Set-Content -LiteralPath $LinkerPath -Value $text -Encoding utf8 -NoNewline

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $LinkerPath,
    [ref]$tokens,
    [ref]$parseErrors
)

if ($parseErrors.Count -gt 0) {
    Copy-Item -LiteralPath $backupPath -Destination $LinkerPath -Force
    $messages = $parseErrors | ForEach-Object { $_.Message }
    throw "PowerShell syntax validation failed. Original restored. Errors: $($messages -join '; ')"
}

Write-Host ''
Write-Host 'GPI Spiro UAT linker hardening complete.' -ForegroundColor Green
Write-Host "Linker : $LinkerPath"
Write-Host "Backup : $backupPath"
Write-Host "Changed: $changed"
Write-Host 'Syntax : PASSED'
Write-Host ''
Write-Host 'Key settings:' -ForegroundColor Cyan
Select-String -LiteralPath $LinkerPath -Pattern 'MaxPages =|page%5Bnumber%5D|total_pages|Spiro companies retrieved' |
    ForEach-Object { Write-Host ("Line {0}: {1}" -f $_.LineNumber, $_.Line.Trim()) }
