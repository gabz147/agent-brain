# drain-queue.ps1 - shared guarded drain entry point.
param([switch]$DryRun, [switch]$Force)
& (Join-Path $PSScriptRoot 'invoke-vault-job.ps1') -Kind 'drain' -DryRun:$DryRun -Force:$Force
