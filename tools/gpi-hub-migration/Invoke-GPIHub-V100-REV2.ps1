#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$BaseScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100.ps1'
$GeneratedScript = Join-Path $ToolRoot 'Invoke-GPIHub-V100-REV2.generated.ps1'

if (-not (Test-Path -LiteralPath $BaseScript -PathType Leaf)) {
    throw "Base V100 script not found: $BaseScript"
}

$source = Get-Content -LiteralPath $BaseScript -Raw
$startMarker = "    `$SourceDiscovery = @'"
$endMarker = "'@`n`n    `$src = Invoke-SshScript"

$start = $source.IndexOf($startMarker, [System.StringComparison]::Ordinal)
if ($start -lt 0) {
    throw 'Could not locate V100 SourceDiscovery start marker.'
}

$end = $source.IndexOf($endMarker, $start, [System.StringComparison]::Ordinal)
if ($end -lt 0) {
    $endMarker = "'@`r`n`r`n    `$src = Invoke-SshScript"
    $end = $source.IndexOf($endMarker, $start, [System.StringComparison]::Ordinal)
}
if ($end -lt 0) {
    throw 'Could not locate V100 SourceDiscovery end marker.'
}

$replacementB64 = 'ICAgICRTb3VyY2VEaXNjb3ZlcnkgPSBAJwpzZXQgLWV1byBwaXBlZmFpbApwcm9qZWN0PWdwaS1odWIKCmNvbW1hbmQgLXYgcHl0aG9uMyA+L2Rldi9udWxsIDI+JjEgfHwgewogIGVjaG8gJ0VSUk9SPXB5dGhvbjNfbm90X2ZvdW5kJwogIGV4aXQgMjIKfQoKbWFwZmlsZSAtdCBjb250YWluZXJzIDwgPChkb2NrZXIgcHMgLS1maWx0ZXIgImxhYmVsPWNvbS5kb2NrZXIuY29tcG9zZS5wcm9qZWN0PSRwcm9qZWN0IiAtLWZvcm1hdCAne3suTmFtZXN9fScpCmlmIFsgJHsjY29udGFpbmVyc1tAXX0gLWVxIDAgXTsgdGhlbgogIGVjaG8gJ0VSUk9SPW5vX2NvbXBvc2VfY29udGFpbmVycycKICBleGl0IDIxCmZpCgpkb2NrZXIgaW5zcGVjdCAiJHtjb250YWluZXJzW0BdfSIgfCBweXRob24zIC1jICcKaW1wb3J0IGpzb24sIHNvY2tldCwgc3lzCml0ZW1zID0ganNvbi5sb2FkKHN5cy5zdGRpbikKaWYgbm90IGl0ZW1zOgogICAgcHJpbnQoIkVSUk9SPW5vX2luc3BlY3RfcmVjb3JkcyIpCiAgICByYWlzZSBTeXN0ZW1FeGl0KDIzKQoKbGFiZWxzID0gKChpdGVtc1swXS5nZXQoIkNvbmZpZyIpIG9yIHt9KS5nZXQoIkxhYmVscyIpIG9yIHt9KQpwcmludCgiSE9TVD0iICsgc29ja2V0LmdldGhvc3RuYW1lKCkpCnByaW50KCJQUk9KRUNUPWdwaS1odWIiKQpwcmludCgiV09SS0RJUj0iICsgKGxhYmVscy5nZXQoImNvbS5kb2NrZXIuY29tcG9zZS5wcm9qZWN0LndvcmtpbmdfZGlyIikgb3IgIiIpKQpwcmludCgiQ09ORklHX0ZJTEVTPSIgKyAobGFiZWxzLmdldCgiY29tLmRvY2tlci5jb21wb3NlLnByb2plY3QuY29uZmlnX2ZpbGVzIikgb3IgIiIpKQoKZm9yIGl0ZW0gaW4gaXRlbXM6CiAgICBjZmcgPSBpdGVtLmdldCgiQ29uZmlnIikgb3Ige30KICAgIGxhYmVscyA9IGNmZy5nZXQoIkxhYmVscyIpIG9yIHt9CiAgICBzZXJ2aWNlID0gbGFiZWxzLmdldCgiY29tLmRvY2tlci5jb21wb3NlLnNlcnZpY2UiKSBvciAiIgogICAgbmFtZSA9IChpdGVtLmdldCgiTmFtZSIpIG9yICIiKS5sc3RyaXAoIi8iKQogICAgaW1hZ2UgPSBjZmcuZ2V0KCJJbWFnZSIpIG9yICIiCiAgICBpbWFnZV9pZCA9IGl0ZW0uZ2V0KCJJbWFnZSIpIG9yICIiCiAgICBwcmludChmIkN8e25hbWV9fHtzZXJ2aWNlfXx7aW1hZ2V9fHtpbWFnZV9pZH0iKQoKICAgIGZvciBtb3VudCBpbiBpdGVtLmdldCgiTW91bnRzIikgb3IgW106CiAgICAgICAgbXR5cGUgPSBtb3VudC5nZXQoIlR5cGUiKSBvciAiIgogICAgICAgIG1uYW1lID0gbW91bnQuZ2V0KCJOYW1lIikgb3IgIiIKICAgICAgICBzb3VyY2UgPSBtb3VudC5nZXQoIlNvdXJjZSIpIG9yICIiCiAgICAgICAgZGVzdGluYXRpb24gPSBtb3VudC5nZXQoIkRlc3RpbmF0aW9uIikgb3IgIiIKICAgICAgICBwcmludChmIk18e3NlcnZpY2V9fHttdHlwZX18e21uYW1lfXx7c291cmNlfXx7ZGVzdGluYXRpb259IikKCiAgICBiaW5kaW5ncyA9ICgoaXRlbS5nZXQoIkhvc3RDb25maWciKSBvciB7fSkuZ2V0KCJQb3J0QmluZGluZ3MiKSBvciB7fSkKICAgIGZvciBjb250YWluZXJfcG9ydCwgaG9zdF9iaW5kaW5ncyBpbiBiaW5kaW5ncy5pdGVtcygpOgogICAgICAgIGZvciBiaW5kaW5nIGluIGhvc3RfYmluZGluZ3Mgb3IgW106CiAgICAgICAgICAgIGhvc3RfaXAgPSBiaW5kaW5nLmdldCgiSG9zdElwIikgb3IgIiIKICAgICAgICAgICAgaG9zdF9wb3J0ID0gYmluZGluZy5nZXQoIkhvc3RQb3J0Iikgb3IgIiIKICAgICAgICAgICAgcHJpbnQoZiJQfHtzZXJ2aWNlfXx7Y29udGFpbmVyX3BvcnR9fHtob3N0X2lwfXx7aG9zdF9wb3J0fSIpCgpwcmludChmIlJVTk5JTkdfQ09VTlQ9e2xlbihpdGVtcyl9IikKJwonQAoKICAgICRzcmMgPSBJbnZva2UtU3NoU2NyaXB0'
$replacement = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($replacementB64))

$prefix = $source.Substring(0, $start)
$suffixStart = $end + $endMarker.Length
$suffix = $source.Substring($suffixStart)
$patched = $prefix + $replacement + $suffix

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($patched, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) {
    $detail = ($errors | ForEach-Object { "Line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "`n"
    throw "Generated V100 REV2 failed PowerShell parser validation:`n$detail"
}

Set-Content -LiteralPath $GeneratedScript -Value $patched -Encoding utf8 -NoNewline
Write-Host 'V100_REV2_SOURCE_DISCOVERY_PATCH=PASS' -ForegroundColor Green
Write-Host 'V100_REV2_GENERATED_PARSER=PASS' -ForegroundColor Green
Write-Host "Generated script: $GeneratedScript"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $GeneratedScript
exit $LASTEXITCODE
