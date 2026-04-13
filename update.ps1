$ErrorActionPreference = "Stop"
. $PSScriptRoot\python_tools.ps1

function Get-GitRoot {
    $root = git rev-parse --show-toplevel 2>$null
    if (-not $root) {
        throw "This folder is not a Git repository."
    }
    return $root.Trim()
}

$repoRoot = Get-GitRoot
Set-Location $repoRoot

$branch = (git branch --show-current).Trim()
if (-not $branch) {
    throw "Unable to detect the current branch."
}

git fetch origin --prune
if ($LASTEXITCODE -ne 0) {
    throw "Failed to fetch remote changes."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupBranch = "backup/$branch/$stamp"
$backupTag = "pre-update-$stamp"

git status --short > $null
$dirty = [bool]((git status --porcelain))

git branch $backupBranch
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create backup branch $backupBranch."
}

git tag $backupTag
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create backup tag $backupTag."
}

if ($dirty) {
    git stash push -u -m "pre-update $stamp"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stash local changes before update."
    }
}

git pull --no-rebase --autostash origin $branch
if ($LASTEXITCODE -ne 0) {
    if ($dirty) {
        git stash pop
    }
    throw "Update failed. Your backup branch is $backupBranch and tag is $backupTag."
}

if ($dirty) {
    git stash pop
}

Write-Host "Update complete."
Write-Host "Backup branch: $backupBranch"
Write-Host "Backup tag: $backupTag"

