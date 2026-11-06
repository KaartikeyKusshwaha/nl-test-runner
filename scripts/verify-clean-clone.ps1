$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$clonePath = Join-Path $tempRoot ("nl-test-runner-clean-" + [guid]::NewGuid().ToString('N'))
$pythonPath = (Get-Command python -ErrorAction Stop).Source

try {
    git clone --no-hardlinks $repositoryRoot $clonePath
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }
    Push-Location $clonePath
    try {
        & $pythonPath -m pip install -e '.[dev]'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone dependency installation failed.' }
        & $pythonPath -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone Chromium install failed.' }
        & $pythonPath -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone lint failed.' }
        & $pythonPath -m pytest -m 'not live'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone offline tests failed.' }
        & $pythonPath -m nlqa --help
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone CLI help failed.' }
    }
    finally { Pop-Location }
    Write-Output 'Clean-clone verification passed.'
}
finally {
    $resolvedClone = [System.IO.Path]::GetFullPath($clonePath)
    $expectedPrefix = Join-Path $tempRoot 'nl-test-runner-clean-'
    if ($resolvedClone.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedClone)) {
        Remove-Item -LiteralPath $resolvedClone -Recurse -Force
    }
}
