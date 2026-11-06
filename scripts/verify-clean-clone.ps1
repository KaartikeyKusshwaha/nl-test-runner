$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$clonePath = Join-Path $tempRoot ("nl-test-runner-clean-" + [guid]::NewGuid().ToString('N'))
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$venvPath = Join-Path $clonePath '.venv\Scripts\python.exe'

try {
    git clone --no-hardlinks $repositoryRoot $clonePath
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }
    Push-Location $clonePath
    try {
        & $pythonPath -m venv '.venv'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone virtual environment creation failed.' }
        & $venvPath -m pip install -e '.[dev]'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone dependency installation failed.' }
        & $venvPath -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone Chromium install failed.' }
        & $venvPath -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone lint failed.' }
        & $venvPath -m pytest -m 'not live'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone offline tests failed.' }
        & $venvPath -m nlqa --help
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
