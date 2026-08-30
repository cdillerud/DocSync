#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ToolRoot = Split-Path -Parent $PSCommandPath
$MainPath = Join-Path $ToolRoot 'Invoke-GPIHub-V115-AP-AI-Routing-Learning-Golden.ps1'
$GeneratedPath = Join-Path $ToolRoot '.Invoke-GPIHub-V115-REV2.generated.ps1'
$ExpectedCommit = '30f53b9f087a5a7c4d9033a904b0826c7a19de17'

if (-not (Test-Path -LiteralPath $MainPath -PathType Leaf)) {
    throw "V115 main script missing: $MainPath"
}

$script = Get-Content -LiteralPath $MainPath -Raw

# Repair 1: pin the exact currently approved AI-routing feature commit.
$commitPattern = '\$ExpectedFeatureCommit = ''[0-9a-f]{40}'''
$commitReplacement = '$ExpectedFeatureCommit = ''' + $ExpectedCommit + ''''
$script = $script -replace $commitPattern, $commitReplacement

# Repair 2: copy the candidate directory as one recursive SCP object. Do not rely
# on Windows wildcard expansion.
$script = $script.Replace(
@'
rm -rf /tmp/gpi-ap-routing-v115-host
mkdir -p /tmp/gpi-ap-routing-v115-host
chmod 700 /tmp/gpi-ap-routing-v115-host
'@,
@'
rm -rf /tmp/gpi-ap-routing-v115-host /tmp/gpi-ap-routing-v115-stage
mkdir -p /tmp/gpi-ap-routing-v115-stage
chmod 700 /tmp/gpi-ap-routing-v115-stage
'@
)
$script = $script.Replace('"$CandidateRoot\*",','"$CandidateRoot",')
$script = $script.Replace('"azureuser@$SourceIp`:/tmp/gpi-ap-routing-v115-host/"','"azureuser@$SourceIp`:/tmp/gpi-ap-routing-v115-stage/"')
$script = $script.Replace("HOST_STAGE='/tmp/gpi-ap-routing-v115-host'","HOST_STAGE='/tmp/gpi-ap-routing-v115-stage/candidate'")

# Repair 3: remove text-mode SSH script transport completely. PowerShell on
# Windows can reintroduce CRLF while piping a string to a native process even
# after the string itself was normalized. Encode the bash script to Base64 and
# let Linux decode it. The -i switch makes any transport whitespace harmless.
$script = $script.Replace("        'bash -s'","        'base64 -di | bash'")
$oldTransport = @'
        $normalized = $ScriptText -replace "`r`n","`n"
        $output = $normalized | & ssh.exe @args 2> $stderrFile
'@
$newTransport = @'
        $normalized = $ScriptText -replace "`r",""
        $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
        $output = $payload | & ssh.exe @args 2> $stderrFile
'@
if (-not $script.Contains($oldTransport)) {
    throw 'V115 REV2 repair failed: expected original SSH text transport block not found.'
}
$script = $script.Replace($oldTransport,$newTransport)

# Repair 4: keep result evidence pinned to the exact feature code actually run.
$script = $script.Replace(
    "'feature_commit':'cd4eece7f10c825bb7382e22a789c0ea0f19dcd5'",
    "'feature_commit':'$ExpectedCommit'"
)

# Repair 5: V115 executes its golden Python probe as a standalone process inside
# the already-running backend container. That intentionally bypasses FastAPI /
# server.startup(), which is where deps.set_db(database.db) is normally wired.
# The existing PO resolver is read-only on this path but requires get_db().
# Bootstrap only that existing dependency in the probe; do not start the full
# application lifecycle and do not alter /app or the feature candidate.
$probeDbAnchor = @'
from services.ap_bc_routing_context_service import resolve_ap_routing_context
from services.folder_routing_service import determine_ap_routing_decision

HOST='gamerpackaging1.sharepoint.com'
'@
$probeDbReplacement = @'
from services.ap_bc_routing_context_service import resolve_ap_routing_context
from services.folder_routing_service import determine_ap_routing_decision
from database import db as _v115_source_db
from deps import get_db as _v115_get_db, set_db as _v115_set_db

_v115_set_db(_v115_source_db)
if _v115_get_db() is not _v115_source_db:
    raise RuntimeError('V115 read-only DB dependency bootstrap verification failed')
print('V115_READONLY_DB_BOOTSTRAP=PASS',flush=True)

HOST='gamerpackaging1.sharepoint.com'
'@
if (-not $script.Contains($probeDbAnchor)) {
    throw 'V115 REV2 repair failed: golden probe DB bootstrap anchor not found.'
}
$script = $script.Replace($probeDbAnchor,$probeDbReplacement)

# Repair 6: surface generalized supervised support in each golden result row.
$supportAnchor = @'
                'candidate_reason':candidate.get('reason'),
                'prediction_match':proposed==expected,
'@
$supportReplacement = @'
                'candidate_reason':candidate.get('reason'),
                'supervised_route_support':candidate.get('supervised_route_support'),
                'prediction_match':proposed==expected,
'@
if (-not $script.Contains($supportAnchor)) {
    throw 'V115 REV2 repair failed: supervised-support result anchor not found.'
}
$script = $script.Replace($supportAnchor,$supportReplacement)

# Repair 7: surface the ensemble decision that reconciles Gemini with repeated
# same-vendor Accounting evidence. This preserves the original model dissent
# while proving whether supervised learning actually selected the final route.
$ensembleAnchor = @'
                'supervised_route_support':candidate.get('supervised_route_support'),
                'prediction_match':proposed==expected,
'@
$ensembleReplacement = @'
                'supervised_route_support':candidate.get('supervised_route_support'),
                'ensemble_reconciliation':candidate.get('ensemble_reconciliation'),
                'prediction_match':proposed==expected,
'@
if (-not $script.Contains($ensembleAnchor)) {
    throw 'V115 REV2 repair failed: ensemble result anchor not found.'
}
$script = $script.Replace($ensembleAnchor,$ensembleReplacement)

$expectedPinText = '$ExpectedFeatureCommit = ''' + $ExpectedCommit + ''''
if ($script.Contains('"$CandidateRoot\*",')) {
    throw 'V115 REV2 repair failed: wildcard SCP source remains.'
}
if (-not $script.Contains("HOST_STAGE='/tmp/gpi-ap-routing-v115-stage/candidate'")) {
    throw 'V115 REV2 repair failed: robust remote staging path not installed.'
}
if (-not $script.Contains($expectedPinText)) {
    throw 'V115 REV2 repair failed: exact feature commit pin not installed.'
}
if (-not $script.Contains("'base64 -di | bash'")) {
    throw 'V115 REV2 repair failed: Base64 SSH decoder command not installed.'
}
if (-not $script.Contains('$payload = [Convert]::ToBase64String')) {
    throw 'V115 REV2 repair failed: Base64 SSH payload encoder not installed.'
}
if ($script.Contains('$output = $normalized | & ssh.exe')) {
    throw 'V115 REV2 repair failed: legacy text-mode SSH transport remains.'
}
if (-not $script.Contains("'feature_commit':'$ExpectedCommit'")) {
    throw 'V115 REV2 repair failed: result commit evidence not updated.'
}
if (-not $script.Contains('from database import db as _v115_source_db')) {
    throw 'V115 REV2 repair failed: read-only DB handle import not installed.'
}
if (-not $script.Contains('_v115_set_db(_v115_source_db)')) {
    throw 'V115 REV2 repair failed: read-only DB dependency bootstrap not installed.'
}
if (-not $script.Contains("print('V115_READONLY_DB_BOOTSTRAP=PASS',flush=True)")) {
    throw 'V115 REV2 repair failed: DB bootstrap runtime evidence marker not installed.'
}
if (-not $script.Contains("'supervised_route_support':candidate.get('supervised_route_support')")) {
    throw 'V115 REV2 repair failed: supervised-support result evidence not installed.'
}
if (-not $script.Contains("'ensemble_reconciliation':candidate.get('ensemble_reconciliation')")) {
    throw 'V115 REV2 repair failed: ensemble result evidence not installed.'
}

Set-Content -LiteralPath $GeneratedPath -Value $script -Encoding utf8 -NoNewline

try {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($GeneratedPath,[ref]$tokens,[ref]$errors)
    if (@($errors).Count -gt 0) {
        $text = (@($errors) | ForEach-Object { $_.Message }) -join '; '
        throw "V115 REV2 generated script parse failed: $text"
    }

    Write-Host 'V115_REV2_FEATURE_COMMIT_PIN=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_SCP_DIRECTORY_STAGE=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_SSH_BASE64_TRANSPORT=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_RESULT_COMMIT_EVIDENCE=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_READONLY_DB_BOOTSTRAP=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_SUPERVISED_SUPPORT_EVIDENCE=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_ENSEMBLE_EVIDENCE=PASS' -ForegroundColor Green
    Write-Host 'V115_REV2_GENERATED_PARSE=PASS' -ForegroundColor Green

    & $GeneratedPath
    if (-not $?) {
        throw 'V115 main phase returned failure.'
    }

    Write-Host 'V115_REV2_ENTRY=PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $GeneratedPath -Force -ErrorAction SilentlyContinue
}
