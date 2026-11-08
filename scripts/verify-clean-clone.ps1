$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$clonePath = Join-Path $tempRoot ("nl-test-runner-clean-" + [guid]::NewGuid().ToString('N'))
$pythonLauncher = (Get-Command py -ErrorAction Stop).Source

try {
    git clone --no-hardlinks $repositoryRoot $clonePath
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }
    Push-Location $clonePath
    try {
        & $pythonLauncher -3 -m venv '.venv'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone virtual environment creation failed.' }
        . .\.venv\Scripts\Activate.ps1
        if ($env:VIRTUAL_ENV -ne (Join-Path $clonePath '.venv')) {
            throw 'Clean-clone virtual environment activation failed.'
        }
        python --version
        python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone pip upgrade failed.' }
        pip install -e '.[dev,web]'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone dependency installation failed.' }
        playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone Chromium install failed.' }
        Copy-Item '.env.example' '.env'
        python -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone lint failed.' }
        python -m pytest -m 'not live'
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone offline tests failed.' }
        nlqa --help
        if ($LASTEXITCODE -ne 0) { throw 'Clean-clone CLI help failed.' }
        deactivate
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
