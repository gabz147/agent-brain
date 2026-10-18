# Agent Brain v2 setup for Windows PowerShell: download the pinned release bundle, check it
# against the release's SHA256SUMS, then run guided setup. No permanent execution-policy change:
#   & ([scriptblock]::Create((Invoke-RestMethod https://raw.githubusercontent.com/gabz147/agent-brain/main/get.ps1)))
# The checksum proves the download is intact, not who published it: both files come from the
# same GitHub release. Set $env:AGENT_BRAIN_VERSION to pick another release tag.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$version = if ($env:AGENT_BRAIN_VERSION) { $env:AGENT_BRAIN_VERSION } else { 'v2.0.0' }
$base = "https://github.com/gabz147/agent-brain/releases/download/$version"
$brainPython = $null
$brainPythonArgs = @()
foreach ($candidate in @('py', 'python', 'python3')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    $candidateArgs = @()
    if ($candidate -eq 'py') { $candidateArgs = @('-3') }
    & $candidate @candidateArgs -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $brainPython = $candidate
        $brainPythonArgs = $candidateArgs
        break
    }
}
if (-not $brainPython) {
    throw 'Install Python 3.10+ from https://www.python.org/downloads/windows/ with Add Python to PATH enabled, reopen PowerShell, and rerun setup.'
}
$brainDir = Join-Path ([IO.Path]::GetTempPath()) ('agent-brain-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $brainDir | Out-Null
try {
    $bundle = Join-Path $brainDir 'brain.pyz'
    $sums = Join-Path $brainDir 'SHA256SUMS'
    Invoke-WebRequest -UseBasicParsing "$base/brain.pyz" -OutFile $bundle
    Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS" -OutFile $sums
    $expected = $null
    foreach ($line in Get-Content -LiteralPath $sums) {
        $parts = $line -split '\s+', 2
        if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq 'brain.pyz') { $expected = $parts[0].ToLowerInvariant() }
    }
    $stream = [IO.File]::OpenRead($bundle)
    try { $actual = -join ([Security.Cryptography.SHA256]::Create().ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) }
    finally { $stream.Dispose() }
    if (-not $expected -or $expected -ne $actual) {
        throw "brain.pyz does not match the SHA-256 in $version's SHA256SUMS; nothing was installed."
    }
    $setupArgs = if ($args.Count -gt 0) { $args } else { @('--wizard') }
    & $brainPython @brainPythonArgs $bundle setup @setupArgs
    if ($LASTEXITCODE -ne 0) { throw "Agent Brain setup exited with code $LASTEXITCODE. See the message above." }
} finally {
    Remove-Item -LiteralPath $brainDir -Recurse -Force -ErrorAction SilentlyContinue
}
