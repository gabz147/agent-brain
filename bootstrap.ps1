# Invoke in a normal PowerShell terminal; no permanent execution-policy changes.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$brainPython = $null
$brainPythonArgs = @()
foreach ($candidate in @('python', 'python3', 'py')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    $candidateArgs = @()
    if ($candidate -eq 'py') { $candidateArgs = @('-3') }
    & $candidate @candidateArgs -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $brainPython = $candidate
        $brainPythonArgs = $candidateArgs
        break
    }
}
if (-not $brainPython) {
    throw 'Install Python 3.11+ from https://www.python.org/downloads/windows/ with Add Python to PATH enabled, reopen PowerShell, and rerun setup.'
}
$brainScript = Join-Path ([IO.Path]::GetTempPath()) ('agent-brain-' + [guid]::NewGuid() + '.py')
try {
    Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/gabz147/agent-brain/main/bootstrap.py' -OutFile $brainScript
    & $brainPython @brainPythonArgs $brainScript @args
    if ($LASTEXITCODE -ne 0) { throw "Agent Brain setup exited with code $LASTEXITCODE. See the message above." }
} finally {
    Remove-Item -LiteralPath $brainScript -Force -ErrorAction SilentlyContinue
}
