[CmdletBinding()]
param(
    [string]$LinkerPath = (Join-Path $PSScriptRoot 'Link-GPISpiroUATContext.ps1')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $LinkerPath)) {
    throw "Spiro UAT linker was not found: $LinkerPath"
}

$content = Get-Content -LiteralPath $LinkerPath -Raw

if ($content -match "SPIRO OPPORTUNITY ENRICHMENT") {
    Write-Host 'Spiro opportunity enrichment is already present. No changes made.' -ForegroundColor Green
    exit 0
}

$oldOpportunityObject = @'
            [pscustomobject]@{
                Id = Get-SpiroRecordId -Record $opportunity
                Name = Get-SpiroDisplayName -Record $opportunity -Kind opportunity
                Stage = [string](Get-SpiroAttribute -Record $opportunity -Names @('stage_name', 'stage', 'status', 'sales_stage'))
                Owner = [string](Get-SpiroAttribute -Record $opportunity -Names @('owner_name', 'owner', 'assigned_to_name', 'sales_rep_name'))
                Url = Get-SpiroBrowserUrl -Record $opportunity
                Raw = $opportunity
            }
'@

$newOpportunityObject = @'
            [pscustomobject]@{
                Id = Get-SpiroRecordId -Record $opportunity
                Name = Get-SpiroDisplayName -Record $opportunity -Kind opportunity
                Stage = [string](Get-SpiroAttribute -Record $opportunity -Names @('stage_name', 'stage', 'status', 'sales_stage'))
                Owner = [string](Get-SpiroAttribute -Record $opportunity -Names @('owner_name', 'owner', 'assigned_to_name', 'sales_rep_name'))
                StageId = [string](Get-SpiroRelationshipId -Record $opportunity -RelationshipNames @('opportunity_stage') -AttributeNames @('opportunity_stage_id', 'opportunityStageId'))
                OwnerUserId = [string](Get-SpiroRelationshipId -Record $opportunity -RelationshipNames @('user', 'owner') -AttributeNames @('user_id', 'userId', 'owner_id', 'ownerId'))
                PipelineId = [string](Get-SpiroRelationshipId -Record $opportunity -RelationshipNames @('pipeline') -AttributeNames @('pipeline_id', 'pipelineId'))
                Url = Get-SpiroBrowserUrl -Record $opportunity
                Raw = $opportunity
            }
'@

if (-not $content.Contains($oldOpportunityObject)) {
    throw 'Could not find the expected opportunity projection block. The linker may have changed since this patch was authored.'
}

$content = $content.Replace($oldOpportunityObject, $newOpportunityObject)

$contactMarker = "Write-Section 'SPIRO CONTACT DISCOVERY'"
if (-not $content.Contains($contactMarker)) {
    throw 'Could not find the Spiro contact discovery marker.'
}

$enrichmentBlock = @'
Write-Section 'SPIRO OPPORTUNITY ENRICHMENT'
if ($null -eq $selectedOpportunity) {
    Write-Host 'No opportunity selected. Stage and owner enrichment skipped.' -ForegroundColor Yellow
}
else {
    Write-Host "Stage relationship ID : $($selectedOpportunity.StageId)"
    Write-Host "Owner user ID         : $($selectedOpportunity.OwnerUserId)"
    Write-Host "Pipeline ID           : $($selectedOpportunity.PipelineId)"

    if (-not [string]::IsNullOrWhiteSpace($selectedOpportunity.OwnerUserId)) {
        $detailUri = "$SpiroApiBase/opportunities/$($selectedOpportunity.Id)?include=user"
        $detailResponse = Invoke-SpiroGet -Uri $detailUri -AccessToken $spiroAccessToken
        $includedRecords = @()
        if ($detailResponse.PSObject.Properties.Name -contains 'included') {
            $includedRecords = @($detailResponse.included)
        }

        $ownerRecord = @(
            $includedRecords |
                Where-Object { (Get-SpiroRecordId -Record $_) -eq $selectedOpportunity.OwnerUserId }
        ) | Select-Object -First 1

        if ($ownerRecord) {
            $ownerFirst = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('first_name', 'firstName'))
            $ownerLast = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('last_name', 'lastName'))
            $ownerName = (($ownerFirst, $ownerLast | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' ').Trim()

            if ([string]::IsNullOrWhiteSpace($ownerName)) {
                $ownerName = [string](Get-SpiroAttribute -Record $ownerRecord -Names @('name', 'display_name', 'email'))
            }

            if (-not [string]::IsNullOrWhiteSpace($ownerName)) {
                $selectedOpportunity.Owner = $ownerName
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($selectedOpportunity.StageId) -and
        -not [string]::IsNullOrWhiteSpace($selectedOpportunity.PipelineId)) {
        $stageUri = "$SpiroApiBase/pipelines/$($selectedOpportunity.PipelineId)/opportunity_stages"
        $stageResponse = Invoke-SpiroGet -Uri $stageUri -AccessToken $spiroAccessToken
        $stageRecords = @()
        if ($stageResponse.PSObject.Properties.Name -contains 'data') {
            $stageRecords = @($stageResponse.data)
        }
        else {
            $stageRecords = @($stageResponse)
        }

        $stageRecord = @(
            $stageRecords |
                Where-Object { (Get-SpiroRecordId -Record $_) -eq $selectedOpportunity.StageId }
        ) | Select-Object -First 1

        if ($stageRecord) {
            $stageName = [string](Get-SpiroAttribute -Record $stageRecord -Names @('name', 'label', 'title', 'stage_name'))
            if (-not [string]::IsNullOrWhiteSpace($stageName)) {
                $selectedOpportunity.Stage = $stageName
            }
        }
    }

    Write-Host "Resolved stage       : $($selectedOpportunity.Stage)" -ForegroundColor Green
    Write-Host "Resolved owner       : $($selectedOpportunity.Owner)" -ForegroundColor Green
}

'@

$content = $content.Replace($contactMarker, $enrichmentBlock + $contactMarker)

try {
    [void][scriptblock]::Create($content)
}
catch {
    throw "Patched linker failed PowerShell syntax validation: $($_.Exception.Message)"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = "$LinkerPath.before-opportunity-enrichment-$stamp"
Copy-Item -LiteralPath $LinkerPath -Destination $backupPath -Force
Set-Content -LiteralPath $LinkerPath -Value $content -Encoding utf8

Write-Host ''
Write-Host 'GPI Spiro UAT opportunity enrichment patch complete.' -ForegroundColor Green
Write-Host "Linker : $LinkerPath"
Write-Host "Backup : $backupPath"
Write-Host 'Syntax : PASSED' -ForegroundColor Green
Write-Host ''
Write-Host 'New behavior:'
Write-Host '  Resolves owner from the Spiro opportunity user relationship.'
Write-Host '  Resolves stage from the opportunity pipeline stage collection.'
Write-Host '  Leaves contact selection and opportunity URL behavior unchanged.'
