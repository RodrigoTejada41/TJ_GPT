$ErrorActionPreference = "Stop"

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

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupBranch = "backup/$branch/$stamp"
$backupTag = "checkpoint-$stamp"

$dirty = [bool]((git status --porcelain))
if ($dirty) {
    git stash push -u -m "manual checkpoint $stamp"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stash local changes for backup."
    }
}

git branch $backupBranch
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create backup branch $backupBranch."
}

git tag $backupTag
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create backup tag $backupTag."
}

Write-Host "Backup created."
Write-Host "Backup branch: $backupBranch"
Write-Host "Backup tag: $backupTag"
if ($dirty) {
    Write-Host "Local changes were saved in git stash."
}

