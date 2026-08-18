[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoPath = "$env:USERPROFILE\Documents\DocSync",

    [Parameter()]
    [string]$WorktreePath = "$env:USERPROFILE\Documents\DocSync-PackagingCatalog",

    [Parameter()]
    [string]$Branch = "agent/gpi-packaging-catalog"
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & git -C $RepoPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is not installed or is not on PATH.'
}

if (-not (Test-Path -LiteralPath $RepoPath)) {
    throw "Repository path does not exist: $RepoPath"
}

& git -C $RepoPath rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Not a Git repository: $RepoPath"
}

if (Test-Path -LiteralPath $WorktreePath) {
    throw "Worktree path already exists: $WorktreePath"
}

Write-Host "Fetching origin..." -ForegroundColor Cyan
Invoke-Git -Arguments @('fetch', 'origin', '--prune')

Write-Host "Verifying remote branch origin/$Branch..." -ForegroundColor Cyan
& git -C $RepoPath show-ref --verify --quiet "refs/remotes/origin/$Branch"
if ($LASTEXITCODE -ne 0) {
    throw "Remote branch origin/$Branch was not found."
}

& git -C $RepoPath show-ref --verify --quiet "refs/heads/$Branch"
$LocalBranchExists = $LASTEXITCODE -eq 0

Write-Host "Creating isolated worktree at $WorktreePath..." -ForegroundColor Cyan
if ($LocalBranchExists) {
    & git -C $RepoPath worktree add $WorktreePath $Branch
}
else {
    & git -C $RepoPath worktree add -b $Branch $WorktreePath "origin/$Branch"
}
if ($LASTEXITCODE -ne 0) {
    throw 'git worktree add failed.'
}

Push-Location $WorktreePath
try {
    Write-Host ''
    Write-Host 'Packaging worktree created successfully.' -ForegroundColor Green
    Write-Host "Path   : $WorktreePath"
    Write-Host "Branch : $(& git branch --show-current)"
    Write-Host "BC app : $(Join-Path $WorktreePath 'packaging-catalog-bc')"
    Write-Host ''
    & git status -sb
}
finally {
    Pop-Location
}
