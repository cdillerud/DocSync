#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$BaseScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100.ps1'
$Rev2Script = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV2.ps1'
$GeneratedScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV4.generated.ps1'
$RunLog = Join-Path $ToolRoot 'last-v100-run.log'
$ErrorLog = Join-Path $ToolRoot 'last-v100-error.txt'

function Require([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Decode-B64([string]$Value) {
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    $first = $Text.IndexOf($Old,[System.StringComparison]::Ordinal)
    Require ($first -ge 0) "V100 REV4 patch anchor missing: $Label"
    $second = $Text.IndexOf($Old,$first + $Old.Length,[System.StringComparison]::Ordinal)
    Require ($second -lt 0) "V100 REV4 patch anchor is not unique: $Label"
    return $Text.Substring(0,$first) + $New + $Text.Substring($first + $Old.Length)
}

function Show-LatestV100DiagnosticTail {
    param([string]$OperationalRoot)

    if ([string]::IsNullOrWhiteSpace($OperationalRoot)) { return }
    $diagRoot = Join-Path $OperationalRoot '.gpi-diagnostics\migration-v100-target-runtime'
    if (-not (Test-Path -LiteralPath $diagRoot -PathType Container)) { return }

    $candidate = Get-ChildItem -LiteralPath $diagRoot -Filter 'Invoke-GPIHub-V100.txt' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) { return }

    Write-Host ''
    Write-Host 'Latest V100 diagnostic transcript tail:' -ForegroundColor Yellow
    Write-Host "  $($candidate.FullName)" -ForegroundColor DarkYellow
    Write-Host ('-' * 96) -ForegroundColor DarkGray
    Get-Content -LiteralPath $candidate.FullName -Tail 100 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    Write-Host ('-' * 96) -ForegroundColor DarkGray
}

$State = $null
try {
    Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "Migration state file missing: $StatePath"
    Require (Test-Path -LiteralPath $BaseScript -PathType Leaf) "Base V100 script missing: $BaseScript"
    Require (Test-Path -LiteralPath $Rev2Script -PathType Leaf) "V100 REV2 script missing: $Rev2Script"

    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 50
    $OperationalRoot = [string]$State.local.operational_root

    $source = (Get-Content -LiteralPath $BaseScript -Raw) -replace "`r`n","`n"
    $rev2Text = Get-Content -LiteralPath $Rev2Script -Raw

    # Reuse the already-proven REV2 JSON/python source-discovery replacement without duplicating it here.
    $b64Match = [regex]::Match($rev2Text, '\$replacementB64\s*=\s*''([^'']+)''')
    Require ($b64Match.Success) 'Could not extract the REV2 source-discovery payload.'
    $sourceDiscoveryReplacement = Decode-B64 $b64Match.Groups[1].Value

    $startMarker = "    `$SourceDiscovery = @'"
    $endMarker = "'@`n`n    `$src = Invoke-SshScript"
    $start = $source.IndexOf($startMarker,[System.StringComparison]::Ordinal)
    Require ($start -ge 0) 'Could not locate V100 SourceDiscovery start marker.'
    $end = $source.IndexOf($endMarker,$start,[System.StringComparison]::Ordinal)
    Require ($end -ge 0) 'Could not locate V100 SourceDiscovery end marker.'
    $source = $source.Substring(0,$start) + $sourceDiscoveryReplacement + $source.Substring($end + $endMarker.Length)

    # Dedicated target path for Mongo's anonymous /data/configdb mount.
    $source = Replace-ExactOnce -Text $source `
        -Old (Decode-B64 'JFRhcmdldE1vbmdvID0gJy9ncGktaHViLWRhdGEvdm9sdW1lcy9tb25nb2RiJwokVGFyZ2V0VXBsb2FkcyA9ICcvZ3BpLWh1Yi1kYXRhL3ZvbHVtZXMvdXBsb2FkcycK') `
        -New (Decode-B64 'JFRhcmdldE1vbmdvID0gJy9ncGktaHViLWRhdGEvdm9sdW1lcy9tb25nb2RiJwokVGFyZ2V0TW9uZ29Db25maWcgPSAnL2dwaS1odWItZGF0YS92b2x1bWVzL21vbmdvZGItY29uZmlnZGInCiRUYXJnZXRVcGxvYWRzID0gJy9ncGktaHViLWRhdGEvdm9sdW1lcy91cGxvYWRzJwo=') `
        -Label 'target Mongo configdb path'

    # Insert a read-only source probe before target override construction. Only an empty anonymous /data/configdb is allowed.
    $configProbeBlock = Decode-B64 'ICAgICRtb25nb0NvbmZpZ0RiTW91bnRzID0gQCgKICAgICAgICAkbW91bnRzIHwgV2hlcmUtT2JqZWN0IHsKICAgICAgICAgICAgJF8uU2VydmljZSAtZXEgJG1vbmdvLlNlcnZpY2UgLWFuZCAkXy5EZXN0aW5hdGlvbiAtZXEgJy9kYXRhL2NvbmZpZ2RiJwogICAgICAgIH0KICAgICkKICAgIFJlcXVpcmUgKCRtb25nb0NvbmZpZ0RiTW91bnRzLkNvdW50IC1sZSAxKSAiTXVsdGlwbGUgTW9uZ28gL2RhdGEvY29uZmlnZGIgbW91bnRzIGRpc2NvdmVyZWQ7IFYxMDAgcmVmdXNlcyBhbWJpZ3VvdXMgc3RhdGUuIgogICAgJG1vbmdvQ29uZmlnRGJNb3VudCA9ICRtb25nb0NvbmZpZ0RiTW91bnRzIHwgU2VsZWN0LU9iamVjdCAtRmlyc3QgMQoKICAgIGlmICgkbnVsbCAtbmUgJG1vbmdvQ29uZmlnRGJNb3VudCkgewogICAgICAgIFJlcXVpcmUgKCRtb25nb0NvbmZpZ0RiTW91bnQuVHlwZSAtZXEgJ3ZvbHVtZScpICJNb25nbyAvZGF0YS9jb25maWdkYiBpcyBub3QgYSBEb2NrZXIgdm9sdW1lLiIKICAgICAgICBSZXF1aXJlICgkbW9uZ29Db25maWdEYk1vdW50Lk5hbWUgLW1hdGNoICdeWzAtOWEtZl17NjR9JCcpICJNb25nbyAvZGF0YS9jb25maWdkYiB2b2x1bWUgaXMgbm90IGFuIGFub255bW91cyA2NC1oZXggRG9ja2VyIHZvbHVtZTogJCgkbW9uZ29Db25maWdEYk1vdW50Lk5hbWUpIgogICAgICAgICRleHBlY3RlZENvbmZpZ0RiU291cmNlID0gIi9kYXRhL2RvY2tlci92b2x1bWVzLyQoJG1vbmdvQ29uZmlnRGJNb3VudC5OYW1lKS9fZGF0YSIKICAgICAgICBSZXF1aXJlICgkbW9uZ29Db25maWdEYk1vdW50LlNvdXJjZSAtZXEgJGV4cGVjdGVkQ29uZmlnRGJTb3VyY2UpICJVbmV4cGVjdGVkIE1vbmdvIC9kYXRhL2NvbmZpZ2RiIHNvdXJjZSBwYXRoOiAkKCRtb25nb0NvbmZpZ0RiTW91bnQuU291cmNlKSIKCiAgICAgICAgJGNvbmZpZ1Byb2JlVGVtcGxhdGUgPSBAJwpzZXQgLWV1byBwaXBlZmFpbApwPV9fQ09ORklHREJfU09VUkNFX18Kc3VkbyB0ZXN0IC1kICIkcCIKYnl0ZXM9JChzdWRvIGR1IC1zYiAiJHAiIHwgY3V0IC1mMSkKZW50cmllcz0kKHN1ZG8gZmluZCAiJHAiIC1taW5kZXB0aCAxIC1tYXhkZXB0aCAxIC1wcmludCB8IHdjIC1sIHwgeGFyZ3MpCmZpbGVzPSQoc3VkbyBmaW5kICIkcCIgLXR5cGUgZiAtcHJpbnQgfCB3YyAtbCB8IHhhcmdzKQplY2hvICJDT05GSUdEQl9CWVRFUz0kYnl0ZXMiCmVjaG8gIkNPTkZJR0RCX0VOVFJJRVM9JGVudHJpZXMiCmVjaG8gIkNPTkZJR0RCX0ZJTEVTPSRmaWxlcyIKJ0AKICAgICAgICAkY29uZmlnUHJvYmVTY3JpcHQgPSAkY29uZmlnUHJvYmVUZW1wbGF0ZS5SZXBsYWNlKCdfX0NPTkZJR0RCX1NPVVJDRV9fJywoQmFzaFF1b3RlICRtb25nb0NvbmZpZ0RiTW91bnQuU291cmNlKSkKICAgICAgICAkY29uZmlnUHJvYmUgPSBJbnZva2UtU3NoU2NyaXB0IC1JcCAkU291cmNlSXAgLUtub3duSG9zdHMgJFNvdXJjZUtub3duSG9zdHMgLVNjcmlwdFRleHQgJGNvbmZpZ1Byb2JlU2NyaXB0CiAgICAgICAgUmVxdWlyZSAoJGNvbmZpZ1Byb2JlLkV4aXRDb2RlIC1lcSAwKSAiTW9uZ28gL2RhdGEvY29uZmlnZGIgc291cmNlIHByb2JlIGZhaWxlZC5gbiQoJGNvbmZpZ1Byb2JlLlN0ZE91dClgbiQoJGNvbmZpZ1Byb2JlLlN0ZEVycikiCgogICAgICAgICRjb25maWdWYWx1ZXMgPSBAe30KICAgICAgICBmb3JlYWNoICgkY29uZmlnTGluZSBpbiAoKCRjb25maWdQcm9iZS5TdGRPdXQgLXJlcGxhY2UgImByIiwnJykgLXNwbGl0ICJgbiIpKSB7CiAgICAgICAgICAgIGlmICgkY29uZmlnTGluZSAtbWF0Y2ggJ14oW0EtWl9dKyk9KC4qKSQnKSB7CiAgICAgICAgICAgICAgICAkY29uZmlnVmFsdWVzWyRNYXRjaGVzWzFdXSA9ICRNYXRjaGVzWzJdCiAgICAgICAgICAgIH0KICAgICAgICB9CiAgICAgICAgZm9yZWFjaCAoJHJlcXVpcmVkQ29uZmlnS2V5IGluIEAoJ0NPTkZJR0RCX0JZVEVTJywnQ09ORklHREJfRU5UUklFUycsJ0NPTkZJR0RCX0ZJTEVTJykpIHsKICAgICAgICAgICAgUmVxdWlyZSAoJGNvbmZpZ1ZhbHVlcy5Db250YWluc0tleSgkcmVxdWlyZWRDb25maWdLZXkpKSAiTW9uZ28gL2RhdGEvY29uZmlnZGIgcHJvYmUgbWlzc2luZyAkcmVxdWlyZWRDb25maWdLZXkuIgogICAgICAgIH0KCiAgICAgICAgJGNvbmZpZ0VudHJpZXMgPSBbaW50NjRdJGNvbmZpZ1ZhbHVlcy5DT05GSUdEQl9FTlRSSUVTCiAgICAgICAgJGNvbmZpZ0ZpbGVzID0gW2ludDY0XSRjb25maWdWYWx1ZXMuQ09ORklHREJfRklMRVMKICAgICAgICBXcml0ZS1Ib3N0ICJNb25nbyBjb25maWdkYiAgICAgIDogJCgkbW9uZ29Db25maWdEYk1vdW50Lk5hbWUpIgogICAgICAgIFdyaXRlLUhvc3QgIkNvbmZpZ2RiIHNvdXJjZSAgICAgOiAkKCRtb25nb0NvbmZpZ0RiTW91bnQuU291cmNlKSIKICAgICAgICBXcml0ZS1Ib3N0ICJDb25maWdkYiBieXRlcyAgICAgIDogJCgkY29uZmlnVmFsdWVzLkNPTkZJR0RCX0JZVEVTKSIKICAgICAgICBXcml0ZS1Ib3N0ICJDb25maWdkYiBlbnRyaWVzICAgIDogJGNvbmZpZ0VudHJpZXMiCiAgICAgICAgV3JpdGUtSG9zdCAiQ29uZmlnZGIgZmlsZXMgICAgICA6ICRjb25maWdGaWxlcyIKICAgICAgICBSZXF1aXJlICgkY29uZmlnRW50cmllcyAtZXEgMCAtYW5kICRjb25maWdGaWxlcyAtZXEgMCkgIk1vbmdvIC9kYXRhL2NvbmZpZ2RiIGNvbnRhaW5zIHNvdXJjZSBkYXRhLiBWMTAwIHJlZnVzZXMgdG8gZGlzY2FyZCBvciBpbnZlbnQgaXQ7IGV4cGxpY2l0IG1pZ3JhdGlvbiBpcyByZXF1aXJlZC4iCiAgICAgICAgV3JpdGUtSG9zdCAnVjEwMF9NT05HT19DT05GSUdEQl9FTVBUWV9TT1VSQ0U9UEFTUycgLUZvcmVncm91bmRDb2xvciBHcmVlbgogICAgfQogICAgZWxzZSB7CiAgICAgICAgV3JpdGUtSG9zdCAnTW9uZ28gY29uZmlnZGIgICAgICA6IG5vIGFjdGl2ZSAvZGF0YS9jb25maWdkYiBtb3VudCcKICAgICAgICBXcml0ZS1Ib3N0ICdWMTAwX01PTkdPX0NPTkZJR0RCX05PVF9QUkVTRU5UPVBBU1MnIC1Gb3JlZ3JvdW5kQ29sb3IgR3JlZW4KICAgIH0KCg=='
    $probeAnchor = '    Write-Host "Backend service     : $($backend.Service) -> $backendContainerPort/tcp"'
    $source = Replace-ExactOnce -Text $source -Old $probeAnchor -New ($configProbeBlock + $probeAnchor) -Label 'Mongo configdb source probe insertion'

    # Allow only the exact, already-probed empty anonymous Mongo /data/configdb mount to map to dedicated target disk storage.
    $source = Replace-ExactOnce -Text $source `
        -Old (Decode-B64 'ICAgICAgICBlbHNlaWYgKCRtLk5hbWUgLWVxICdncGktaHViX3VwbG9hZHNfZGF0YScpIHsKICAgICAgICAgICAgJG1hcHBlZFNvdXJjZSA9ICRUYXJnZXRVcGxvYWRzCiAgICAgICAgfQogICAgICAgIGVsc2VpZiAoJG0uVHlwZSAtZXEgJ2JpbmQnIC1hbmQgJG0uU291cmNlLlN0YXJ0c1dpdGgoJFNvdXJjZUFwcCxbU3lzdGVtLlN0cmluZ0NvbXBhcmlzb25dOjpPcmRpbmFsKSkgewo=') `
        -New (Decode-B64 'ICAgICAgICBlbHNlaWYgKCRtLk5hbWUgLWVxICdncGktaHViX3VwbG9hZHNfZGF0YScpIHsKICAgICAgICAgICAgJG1hcHBlZFNvdXJjZSA9ICRUYXJnZXRVcGxvYWRzCiAgICAgICAgfQogICAgICAgIGVsc2VpZiAoCiAgICAgICAgICAgICRudWxsIC1uZSAkbW9uZ29Db25maWdEYk1vdW50IC1hbmQKICAgICAgICAgICAgJG0uU2VydmljZSAtZXEgJG1vbmdvLlNlcnZpY2UgLWFuZAogICAgICAgICAgICAkbS5UeXBlIC1lcSAndm9sdW1lJyAtYW5kCiAgICAgICAgICAgICRtLk5hbWUgLWVxICRtb25nb0NvbmZpZ0RiTW91bnQuTmFtZSAtYW5kCiAgICAgICAgICAgICRtLkRlc3RpbmF0aW9uIC1lcSAnL2RhdGEvY29uZmlnZGInCiAgICAgICAgKSB7CiAgICAgICAgICAgICRtYXBwZWRTb3VyY2UgPSAkVGFyZ2V0TW9uZ29Db25maWcKICAgICAgICB9CiAgICAgICAgZWxzZWlmICgkbS5UeXBlIC1lcSAnYmluZCcgLWFuZCAkbS5Tb3VyY2UuU3RhcnRzV2l0aCgkU291cmNlQXBwLFtTeXN0ZW0uU3RyaW5nQ29tcGFyaXNvbl06Ok9yZGluYWwpKSB7Cg==') `
        -Label 'Mongo configdb override mapping'

    # Ensure the target directory exists before Compose validates/starts the Mongo service.
    $source = Replace-ExactOnce -Text $source `
        -Old (Decode-B64 'TU9OR09fRElSPV9fVEFSR0VUX01PTkdPX18KVVBMT0FEU19ESVI9X19UQVJHRVRfVVBMT0FEU19fCg==') `
        -New (Decode-B64 'TU9OR09fRElSPV9fVEFSR0VUX01PTkdPX18KTU9OR09fQ09ORklHX0RJUj1fX1RBUkdFVF9NT05HT19DT05GSUdfXwpVUExPQURTX0RJUj1fX1RBUkdFVF9VUExPQURTX18K') `
        -Label 'target template Mongo configdb variable'
    $source = Replace-ExactOnce -Text $source `
        -Old (Decode-B64 'c3VkbyBta2RpciAtcCAiJE1PTkdPX0RJUiIgIiRVUExPQURTX0RJUiIgIiRNSUdfRElSIgo=') `
        -New (Decode-B64 'c3VkbyBta2RpciAtcCAiJE1PTkdPX0RJUiIgIiRNT05HT19DT05GSUdfRElSIiAiJFVQTE9BRFNfRElSIiAiJE1JR19ESVIiCg==') `
        -Label 'target Mongo configdb mkdir'
    $source = Replace-ExactOnce -Text $source `
        -Old (Decode-B64 'ICAgICRUYXJnZXRTY3JpcHQgPSAkVGFyZ2V0U2NyaXB0LlJlcGxhY2UoJ19fVEFSR0VUX01PTkdPX18nLChCYXNoUXVvdGUgJFRhcmdldE1vbmdvKSkKICAgICRUYXJnZXRTY3JpcHQgPSAkVGFyZ2V0U2NyaXB0LlJlcGxhY2UoJ19fVEFSR0VUX1VQTE9BRFNfXycsKEJhc2hRdW90ZSAkVGFyZ2V0VXBsb2FkcykpCg==') `
        -New (Decode-B64 'ICAgICRUYXJnZXRTY3JpcHQgPSAkVGFyZ2V0U2NyaXB0LlJlcGxhY2UoJ19fVEFSR0VUX01PTkdPX18nLChCYXNoUXVvdGUgJFRhcmdldE1vbmdvKSkKICAgICRUYXJnZXRTY3JpcHQgPSAkVGFyZ2V0U2NyaXB0LlJlcGxhY2UoJ19fVEFSR0VUX01PTkdPX0NPTkZJR19fJywoQmFzaFF1b3RlICRUYXJnZXRNb25nb0NvbmZpZykpCiAgICAkVGFyZ2V0U2NyaXB0ID0gJFRhcmdldFNjcmlwdC5SZXBsYWNlKCdfX1RBUkdFVF9VUExPQURTX18nLChCYXNoUXVvdGUgJFRhcmdldFVwbG9hZHMpKQo=') `
        -Label 'target Mongo configdb placeholder substitution'

    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        $detail = ($parseErrors | ForEach-Object { "Line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n"
        throw "Generated V100 REV4 failed PowerShell parser validation:`n$detail"
    }

    Set-Content -LiteralPath $GeneratedScript -Value $source -Encoding utf8 -NoNewline
    Remove-Item -LiteralPath $RunLog,$ErrorLog -Force -ErrorAction SilentlyContinue

    Write-Host ''
    Write-Host ('=' * 104) -ForegroundColor Cyan
    Write-Host 'V100 REV4 - CONFIGDB-GATED CAPTURED EXECUTION' -ForegroundColor Cyan
    Write-Host ('=' * 104) -ForegroundColor Cyan
    Write-Host "Generated phase : $GeneratedScript"
    Write-Host "Run log         : $RunLog"
    Write-Host 'V100_REV4_PATCH_ANCHORS=PASS' -ForegroundColor Green
    Write-Host 'V100_REV4_GENERATED_PARSER=PASS' -ForegroundColor Green
    Write-Host 'V100_REV4_CAPTURE_WRAPPER=PASS' -ForegroundColor Green
    Write-Host ''

    $allOutput = & pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedScript 2>&1
    $exitCode = $LASTEXITCODE
    $text = (@($allOutput) | ForEach-Object { [string]$_ }) -join "`r`n"
    Set-Content -LiteralPath $RunLog -Value $text -Encoding utf8
    if (-not [string]::IsNullOrWhiteSpace($text)) { Write-Host $text }

    if ($exitCode -ne 0) { throw "V100 REV4 generated phase exited with code $exitCode." }

    Write-Host ''
    Write-Host 'V100_REV4_INNER_PHASE=PASS' -ForegroundColor Green
    exit 0
}
catch {
    $message = $_ | Out-String
    Set-Content -LiteralPath $ErrorLog -Value $message -Encoding utf8

    Write-Host ''
    Write-Host ('=' * 104) -ForegroundColor Red
    Write-Host 'V100 REV4 FAILED - WINDOW WILL REMAIN OPEN' -ForegroundColor Red
    Write-Host ('=' * 104) -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host ''
    Write-Host "Full captured run log : $RunLog" -ForegroundColor Yellow
    Write-Host "Error file            : $ErrorLog" -ForegroundColor Yellow

    if ($null -ne $State) {
        Show-LatestV100DiagnosticTail -OperationalRoot ([string]$State.local.operational_root)
    }

    Write-Host ''
    Write-Host 'REV4 never stops the source VM, changes traffic, or enables Production writes.' -ForegroundColor Yellow
    Write-Host 'If configdb contains anything, REV4 fails closed before target reconstruction.' -ForegroundColor Yellow
    [void](Read-Host 'Press Enter when you are ready to close this window')
    exit 1
}
