#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$StatePath = Join-Path $ToolRoot 'state.json'
$LegacyControlCommit = 'b45ae78800b8f6666a6a105318cf0b7bf6fe6648'
$LegacyRepoPath = 'tools/gpi-hub-migration/Invoke-GPIHub-V117-REV2-Detached-Entry.ps1'
$ExpectedFeatureCommit = '830bc9611f3e6c7bef12c66215ddd070214c593f'

function Require {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

Require (Test-Path -LiteralPath $StatePath -PathType Leaf) "V117 REV3 state missing: $StatePath"
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -Depth 80
$OperationalRoot = [string]$State.local.operational_root
Require (Test-Path -LiteralPath $OperationalRoot -PathType Container) "V117 REV3 operational repo missing: $OperationalRoot"
Require ($null -ne (Get-Command git.exe -ErrorAction SilentlyContinue)) 'git.exe unavailable.'
Require ($null -ne (Get-Command pwsh.exe -ErrorAction SilentlyContinue)) 'pwsh.exe unavailable.'

$spec = "{0}:{1}" -f $LegacyControlCommit,$LegacyRepoPath
$legacyLines = & git.exe -C $OperationalRoot show $spec
$gitExit = $LASTEXITCODE
Require ($gitExit -eq 0) "Could not load immutable V117 REV2 controller from $LegacyControlCommit."
$LegacyRaw = ((@($legacyLines) | ForEach-Object { [string]$_ }) -join "`n") -replace "`r",''

$EntryReadAnchor = @'
$EntryRaw = (Get-Content -LiteralPath $EntrySourcePath -Raw) -replace "`r",''
'@
Require ($LegacyRaw.Contains($EntryReadAnchor)) 'V117 REV3 legacy entry-read anchor missing.'
$EntryPatch = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('IyAtLS0tIFYxMTcgUkVWMyBmYXN0IGh1bWFuLWV2aWRlbmNlIHJlcGxheSBvdmVybGF5IC0tLS0KJEVudHJ5UmF3ID0gUmVwbGFjZS1SZXF1aXJlZCAtVGV4dCAkRW50cnlSYXcgYAogICAgLU9sZCAnJEV4cGVjdGVkRmVhdHVyZUNvbW1pdCA9ICcnYTcyOGViYTRkZDkwMTRhOTFlNDc5NDcyOTJkMDQ2ZTU5OTI0ZjNjNycnJyBgCiAgICAtTmV3ICckRXhwZWN0ZWRGZWF0dXJlQ29tbWl0ID0gJyczMGJjOTYxMWYzZTZjN2JlZjEyYzY2MjE1ZGRkMDcwMjE0YzU5M2YnJycgYAogICAgLU1hcmtlciAnUkVWMyBsZWFybmVkIGZlYXR1cmUgcGluJwoKJEVudHJ5UmF3ID0gUmVwbGFjZS1SZXF1aXJlZCAtVGV4dCAkRW50cnlSYXcgYAogICAgLU9sZCAiICAgICAgICAnYmFja2VuZC9zZXJ2aWNlcy9hcF9yb3V0aW5nX2xlYXJuZWRfZXZhbHVhdGlvbl9zZXJ2aWNlLnB5JywiIGAKICAgIC1OZXcgIiAgICAgICAgJ2JhY2tlbmQvc2VydmljZXMvYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZS5weScsYG4gICAgICAgICdiYWNrZW5kL3NlcnZpY2VzL2FwX3JvdXRpbmdfZXZpZGVuY2Vfc25hcHNob3Rfc2VydmljZS5weScsIiBgCiAgICAtTWFya2VyICdSRVYzIGV2aWRlbmNlIHNuYXBzaG90IHNlcnZpY2UgbWF0ZXJpYWxpemF0aW9uJwoKJEVudHJ5UmF3ID0gUmVwbGFjZS1SZXF1aXJlZCAtVGV4dCAkRW50cnlSYXcgYAogICAgLU9sZCAiICAgICAgICAnYmFja2VuZC90ZXN0cy90ZXN0X2FwX3JvdXRpbmdfdjExN19sZWFybmVkX3Byb21wdF9hbmRfc2FmZXR5LnB5JywiIGAKICAgIC1OZXcgIiAgICAgICAgJ2JhY2tlbmQvdGVzdHMvdGVzdF9hcF9yb3V0aW5nX3YxMTdfbGVhcm5lZF9wcm9tcHRfYW5kX3NhZmV0eS5weScsYG4gICAgICAgICdiYWNrZW5kL3Rlc3RzL3Rlc3RfYXBfcm91dGluZ192MTE3X2V2aWRlbmNlX3NuYXBzaG90LnB5JywiIGAKICAgIC1NYXJrZXIgJ1JFVjMgZXZpZGVuY2Ugc25hcHNob3QgcmVncmVzc2lvbiBtYXRlcmlhbGl6YXRpb24nCgokQ29tcGlsZVNlcnZpY2VPbGQgPSBAJwogIiRDT05UQUlORVJfU1RBR0Uvc2VydmljZXMvYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZS5weSIgXAonQAokQ29tcGlsZVNlcnZpY2VOZXcgPSBAJwogIiRDT05UQUlORVJfU1RBR0Uvc2VydmljZXMvYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZS5weSIgXAogIiRDT05UQUlORVJfU1RBR0Uvc2VydmljZXMvYXBfcm91dGluZ19ldmlkZW5jZV9zbmFwc2hvdF9zZXJ2aWNlLnB5IiBcCidACiRFbnRyeVJhdyA9IFJlcGxhY2UtUmVxdWlyZWQgLVRleHQgJEVudHJ5UmF3IC1PbGQgJENvbXBpbGVTZXJ2aWNlT2xkIC1OZXcgJENvbXBpbGVTZXJ2aWNlTmV3IC1NYXJrZXIgJ1JFVjMgc25hcHNob3Qgc2VydmljZSBweWNvbXBpbGUnCgokU25hcHNob3RUZXN0T2xkID0gQCcKICIkQ09OVEFJTkVSX1NUQUdFL3Rlc3RzL3Rlc3RfYXBfcm91dGluZ192MTE3X2xlYXJuZWRfcHJvbXB0X2FuZF9zYWZldHkucHkiCidACiRTbmFwc2hvdFRlc3ROZXcgPSBAJwogIiRDT05UQUlORVJfU1RBR0UvdGVzdHMvdGVzdF9hcF9yb3V0aW5nX3YxMTdfbGVhcm5lZF9wcm9tcHRfYW5kX3NhZmV0eS5weSIgXAogIiRDT05UQUlORVJfU1RBR0UvdGVzdHMvdGVzdF9hcF9yb3V0aW5nX3YxMTdfZXZpZGVuY2Vfc25hcHNob3QucHkiCidAClJlcXVpcmUgKCRFbnRyeVJhdy5Db250YWlucygkU25hcHNob3RUZXN0T2xkKSkgJ1JFVjMgc25hcHNob3QgdGVzdCBjb21waWxlL3B5dGVzdCBhbmNob3IgbWlzc2luZy4nCiRFbnRyeVJhdyA9ICRFbnRyeVJhdy5SZXBsYWNlKCRTbmFwc2hvdFRlc3RPbGQsJFNuYXBzaG90VGVzdE5ldykKCiRPcmlnaW5PbGQgPSAnc2VydmljZXMuYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZSBhcyBlOyBwYXRocz1bc3RyKHguX19maWxlX18pIGZvciB4IGluIChhLGwscyxwLHYscixtLGYsbixlKV0nCiRPcmlnaW5OZXcgPSAnc2VydmljZXMuYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZSBhcyBlLCBzZXJ2aWNlcy5hcF9yb3V0aW5nX2V2aWRlbmNlX3NuYXBzaG90X3NlcnZpY2UgYXMgcTsgcGF0aHM9W3N0cih4Ll9fZmlsZV9fKSBmb3IgeCBpbiAoYSxsLHMscCx2LHIsbSxmLG4sZSxxKV0nCiRFbnRyeVJhdyA9IFJlcGxhY2UtUmVxdWlyZWQgLVRleHQgJEVudHJ5UmF3IC1PbGQgJE9yaWdpbk9sZCAtTmV3ICRPcmlnaW5OZXcgLU1hcmtlciAnUkVWMyBzbmFwc2hvdCBpbXBvcnQgb3JpZ2luIGdhdGUnCgokRW50cnlSYXcgPSBSZXBsYWNlLVJlcXVpcmVkIC1UZXh0ICRFbnRyeVJhdyBgCiAgICAtT2xkICdlY2hvIFYxMTdfRk9DVVNFRF9SRUdSRVNTSU9OX1RBUkdFVD0xMDcnIGAKICAgIC1OZXcgJ2VjaG8gVjExN19GT0NVU0VEX1JFR1JFU1NJT05fVEFSR0VUPTExNicgYAogICAgLU1hcmtlciAnUkVWMyBmb2N1c2VkIHJlZ3Jlc3Npb24gdGFyZ2V0IDExNicKCiRQcm9iZUltcG9ydE9sZCA9IEAnCmZyb20gc2VydmljZXMuYXBfcm91dGluZ19sZWFybmVkX2V2YWx1YXRpb25fc2VydmljZSBpbXBvcnQgKAogICAgZXZhbHVhdGVfaG9sZG91dF9sZWFybmVkIGFzIF92MTE3X2xlYXJuZWRfZXZhbHVhdGVfaG9sZG91dCwKKQonQAokUHJvYmVJbXBvcnROZXcgPSBAJwpmcm9tIHNlcnZpY2VzLmFwX3JvdXRpbmdfbGVhcm5lZF9ldmFsdWF0aW9uX3NlcnZpY2UgaW1wb3J0ICgKICAgIGV2YWx1YXRlX2hvbGRvdXRfbGVhcm5lZCBhcyBfdjExN19sZWFybmVkX2V2YWx1YXRlX2hvbGRvdXQsCikKZnJvbSBzZXJ2aWNlcy5hcF9yb3V0aW5nX2V2aWRlbmNlX3NuYXBzaG90X3NlcnZpY2UgaW1wb3J0ICgKICAgIGxvYWRfdmFsaWRfZXZpZGVuY2Vfc25hcHNob3QsCiAgICBzbmFwc2hvdF9leGFtcGxlc19zaGEyNTYsCikKCl92MTE3X2xpdmVfZXhwYW5kX2hpZ2hfdmFsdWVfdmVuZG9yX2NvcnB1cz1leHBhbmRfaGlnaF92YWx1ZV92ZW5kb3JfY29ycHVzCl92MTE3X3NuYXBzaG90X3JlcGxheV9hY3RpdmU9RmFsc2UKYXN5bmMgZGVmIF92MTE3X2V4cGFuZF9oaWdoX3ZhbHVlX3ZlbmRvcl9jb3JwdXNfZ3VhcmRlZCgqYXJncywqKmt3YXJncyk6CiAgICBpZiBfdjExN19zbmFwc2hvdF9yZXBsYXlfYWN0aXZlOgogICAgICAgIHByaW50KCdWMTE3X1ZFTkRPUl9FWFBBTlNJT049U0tJUFBFRF9WQUxJREFURURfU05BUFNIT1QnLGZsdXNoPVRydWUpCiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgJ3RhcmdldF92ZW5kb3JzJzpbXSwKICAgICAgICAgICAgJ2NhbmRpZGF0ZV92ZW5kb3JfY291bnRzJzp7fSwKICAgICAgICAgICAgJ3NlbGVjdGVkX2NvdW50JzowLAogICAgICAgICAgICAnaHlkcmF0ZWRfY291bnQnOjAsCiAgICAgICAgICAgICdoeWRyYXRlZF9ieV92ZW5kb3InOnt9LAogICAgICAgICAgICAnZmFpbHVyZV9jb3VudCc6MCwKICAgICAgICAgICAgJ2ZhaWx1cmVzJzpbXSwKICAgICAgICAgICAgJ2V4YW1wbGVzJzpbXSwKICAgICAgICB9CiAgICByZXR1cm4gYXdhaXQgX3YxMTdfbGl2ZV9leHBhbmRfaGlnaF92YWx1ZV92ZW5kb3JfY29ycHVzKCphcmdzLCoqa3dhcmdzKQpleHBhbmRfaGlnaF92YWx1ZV92ZW5kb3JfY29ycHVzPV92MTE3X2V4cGFuZF9oaWdoX3ZhbHVlX3ZlbmRvcl9jb3JwdXNfZ3VhcmRlZAonQAokRW50cnlSYXcgPSBSZXBsYWNlLVJlcXVpcmVkIC1UZXh0ICRFbnRyeVJhdyAtT2xkICRQcm9iZUltcG9ydE9sZCAtTmV3ICRQcm9iZUltcG9ydE5ldyAtTWFya2VyICdSRVYzIHNuYXBzaG90IHJlcGxheSBpbXBvcnRzIGFuZCBleHBhbnNpb24gYnlwYXNzJwoKJEVudHJ5UmF3ID0gUmVwbGFjZS1SZXF1aXJlZCAtVGV4dCAkRW50cnlSYXcgYAogICAgLU9sZCAicHJpbnQoJ1YxMTdfQUlfUFJPUE9TQUxfU0hBRE9XX01FVFJJQ1M9QUNUSVZFJyxmbHVzaD1UcnVlKSIgYAogICAgLU5ldyAicHJpbnQoJ1YxMTdfQUlfUFJPUE9TQUxfU0hBRE9XX01FVFJJQ1M9QUNUSVZFJyxmbHVzaD1UcnVlKWBucHJpbnQoJ1YxMTdfRVZJREVOQ0VfUkVQTEFZX1ZBTElEQVRPUj1BQ1RJVkUnLGZsdXNoPVRydWUpIiBgCiAgICAtTWFya2VyICdSRVYzIHJlcGxheSBydW50aW1lIG1hcmtlcicKCiRSZXBsYXlUcmFuc2Zvcm1BbmNob3IgPSBAJwokUmF3ID0gJFJhdy5SZXBsYWNlKCdWMTE2IGhlbGQtb3V0IGV2YWx1YXRpb24gZ2F0ZSBmYWlsZWQnLCdWMTE3IGxlYXJuZWQtYXV0b25vbXkgaGVsZC1vdXQgZXZhbHVhdGlvbiBnYXRlIGZhaWxlZCcpCidACiRSZXBsYXlUcmFuc2Zvcm1Db2RlID0gW1RleHQuRW5jb2RpbmddOjpVVEY4LkdldFN0cmluZyhbQ29udmVydF06OkZyb21CYXNlNjRTdHJpbmcoJ0pGSmxjR3hoZVUxaGFXNVBiR1FnUFNCQUp3cFljM2x1WXlCa1pXWWdiV0ZwYmlncE9nb2dJQ0FnWTI5dWRISmhZM1E5Ykc5aFpGOWpiMjUwY21GamRDZ3BDaUFnSUNCd2NtbHVkQ2duVmpFeE4xOURUMUpRVlZOZlFsVkpURVJmVTFSQlVsUTlNU2NzWm14MWMyZzlWSEoxWlNrS0lDQWdJR052Y25CMWN6MWhkMkZwZENCaWRXbHNaRjl6ZFhCbGNuWnBjMlZrWDNKdmRYUnBibWRmWTI5eWNIVnpLQW9nSUNBZ0lDQWdJRTV2Ym1Vc0NpQWdJQ0FnSUNBZ1pHbHpZMjkyWlhKNVgyMWhlRjltYVd4bGN6MDFNREF3TUN3S0lDQWdJQ0FnSUNCdFlYaGZjR1Z5WDNKdmRYUmxQVGdzQ2lBZ0lDQWdJQ0FnYldGNFgzUnZkR0ZzUFRFNE1Dd0tJQ0FnSUNBZ0lDQmpiMjVqZFhKeVpXNWplVDB3TEFvZ0lDQWdJQ0FnSUhCbGNuTnBjM1E5Um1Gc2MyVXNDaUFnSUNBZ0lDQWdj m...'))
$EntryRaw = Replace-Required -Text $EntryRaw -Old $ReplayTransformAnchor -New ($ReplayTransformAnchor + "`n" + $ReplayTransformCode) -Marker 'REV3 generated probe replay transforms'

$EntryRaw = Replace-Required -Text $EntryRaw `
    -Old "Require (`$Raw.Contains('V117_AI_PROPOSAL_SHADOW_METRICS=ACTIVE')) 'V117 generated script lacks AI shadow metric activation.'" `
    -New "Require (`$Raw.Contains('V117_AI_PROPOSAL_SHADOW_METRICS=ACTIVE')) 'V117 generated script lacks AI shadow metric activation.'`nRequire (`$Raw.Contains('V117_EVIDENCE_REPLAY_VALIDATOR=ACTIVE')) 'V117 generated script lacks evidence replay validator.'`nRequire (`$Raw.Contains('V117_EVIDENCE_REPLAY=VALIDATED')) 'V117 generated script lacks validated replay path.'`nRequire (`$Raw.Contains('V117_LIVE_CORPUS_REBUILD=USED')) 'V117 generated script lacks live rebuild fallback.'" `
    -Marker 'REV3 generated replay assertions'

$EntryRaw = Replace-Required -Text $EntryRaw `
    -Old "Write-Host 'V117_AI_PROPOSAL_SHADOW_METRICS_CONFIGURED=PASS' -ForegroundColor Green" `
    -New "Write-Host 'V117_AI_PROPOSAL_SHADOW_METRICS_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_EVIDENCE_REPLAY_VALIDATOR_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_FAST_EVIDENCE_REPLAY_CONFIGURED=PASS' -ForegroundColor Green" `
    -Marker 'REV3 replay configured markers'
# ---- end V117 REV3 overlay ----'))
$LegacyRaw = $LegacyRaw.Replace($EntryReadAnchor,$EntryReadAnchor + "`n" + $EntryPatch)

$SnapshotDigestOld = @'
                'example_count':len(examples),
                'examples':examples,
'@
$SnapshotDigestNew = @'
                'example_count':len(examples),
                'examples_sha256':snapshot_examples_sha256(examples),
                'examples':examples,
'@
Require ($LegacyRaw.Contains($SnapshotDigestOld)) 'V117 REV3 snapshot digest anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($SnapshotDigestOld,$SnapshotDigestNew)

$Rev3MarkerOld = "Write-Host 'V117_REV2_EVIDENCE_SNAPSHOT_CONFIGURED=PASS' -ForegroundColor Green"
$Rev3MarkerNew = $Rev3MarkerOld + "`nWrite-Host 'V117_REV3_VALIDATED_EVIDENCE_REPLAY_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_INVALID_SNAPSHOT_LIVE_REBUILD_FALLBACK_CONFIGURED=PASS' -ForegroundColor Green`nWrite-Host 'V117_REV3_FOCUSED_REGRESSION_TARGET_CONFIGURED=116' -ForegroundColor Green"
Require ($LegacyRaw.Contains($Rev3MarkerOld)) 'V117 REV3 marker anchor missing.'
$LegacyRaw = $LegacyRaw.Replace($Rev3MarkerOld,$Rev3MarkerNew)

$OverlayPath = Join-Path $ToolRoot 'Invoke-GPIHub-V117-REV3-Replay-Generated.ps1'
Set-Content -LiteralPath $OverlayPath -Value $LegacyRaw -Encoding utf8 -NoNewline

$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($OverlayPath,[ref]$tokens,[ref]$errors)
if (@($errors).Count -gt 0) {
    $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
    throw "V117 REV3 overlay parse failed: $text"
}

Write-Host 'V117_REV3_RESTARTED_SPRINT=PASS' -ForegroundColor Green
Write-Host "V117_REV3_LEGACY_CONTROL_BASE=$LegacyControlCommit"
Write-Host "V117_REV3_FEATURE_COMMIT=$ExpectedFeatureCommit"
Write-Host 'V117_REV3_SNAPSHOT_MAX_AGE_HOURS=24'
Write-Host 'V117_REV3_SNAPSHOT_FAILS_CLOSED_TO_LIVE_REBUILD=PASS' -ForegroundColor Green
Write-Host 'V117_REV3_PRODUCTION_MUTATION=NONE' -ForegroundColor Green
Write-Host "V117_REV3_GENERATED_CONTROLLER=$OverlayPath"

& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $OverlayPath
exit $LASTEXITCODE
