# nightly-audit.ps1 - shared guarded audit entry point.
param([switch]$DryRun, [switch]$Force)
& (Join-Path $PSScriptRoot 'invoke-vault-job.ps1') -Kind 'audit' -DryRun:$DryRun -Force:$Force
