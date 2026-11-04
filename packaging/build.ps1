param(
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$BuildRoot = (Join-Path $env:SystemDrive 'StudyTimerBuild'),
    [string]$TestResultsDir = (Join-Path $PSScriptRoot '..\reports\raw\package'),
    [switch]$DesktopTests
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$previousBuildDir = $env:STUDYTIMER_BUILD_DIR
$previousPyInstallerConfig = $env:PYINSTALLER_CONFIG_DIR
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousNativeUi = $env:STUDYTIMER_NATIVE_UI
$previousDesktopUi = $env:STUDYTIMER_DESKTOP_E2E
$previousEvidenceDir = $env:STUDYTIMER_EVIDENCE_DIR

function Invoke-CheckedPython {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Comando Python falhou: $Arguments"
    }
}

Push-Location -LiteralPath $projectRoot
try {
    Invoke-CheckedPython -Arguments @('-c', "import sys, struct; assert sys.platform == 'win32' and sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, 'Build requer Python 3.12 x64 no Windows'")
    $Python = (Resolve-Path -LiteralPath $Python).Path
    $resultsRoot = [System.IO.Path]::GetFullPath($TestResultsDir)
    New-Item -ItemType Directory -Path $resultsRoot -Force | Out-Null
    $neutralRoot = [System.IO.Path]::GetFullPath($BuildRoot)
    if ($neutralRoot -match '(?i)[\\/]Users[\\/]|[\\/]OneDrive([\\/]|$)') {
        throw 'BuildRoot deve ser uma pasta neutra fora do perfil e do OneDrive.'
    }
    $stage = Join-Path $neutralRoot ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach ($folder in @('app', 'assets', 'packaging', 'tests')) {
        $source = Join-Path $projectRoot $folder
        foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse) {
            if ($file.Extension -notin @('.py', '.sql', '.ico', '.spec', '.ps1')) { continue }
            $relative = $file.FullName.Substring($projectRoot.Length + 1)
            $target = Join-Path $stage $relative
            New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target
        }
    }
    foreach ($file in @('main.py', 'pyproject.toml', 'requirements.txt', 'requirements-dev.txt', '.gitignore')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $stage
    }
    Invoke-CheckedPython -Arguments @('-m', 'venv', (Join-Path $stage '.venv'))
    $Python = Join-Path $stage '.venv\Scripts\python.exe'
    Set-Location -LiteralPath $stage
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $stage 'pyinstaller-cache'
    $env:TEMP = Join-Path $stage 'temp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    Invoke-CheckedPython -Arguments @('-m', 'pip', '--isolated', 'install', '--index-url', 'https://pypi.org/simple', '--require-hashes', '--only-binary=:all:', '-r', 'requirements-dev.txt')
    Invoke-CheckedPython -Arguments @('-m', 'pip', 'check')
    Invoke-CheckedPython -Arguments @('-m', 'ruff', 'check', '.')
    Invoke-CheckedPython -Arguments @('-m', 'ruff', 'format', '--check', '.')
    Invoke-CheckedPython -Arguments @('-m', 'mypy')
    Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'preflight', '--kind', 'quality', '--output', (Join-Path $resultsRoot 'preflight.json'))
    Invoke-CheckedPython -Arguments @('-m', 'pytest', '-m', 'not build and not native_ui', '--basetemp', (Join-Path $stage 'test-temp-quality'), '--junitxml', (Join-Path $resultsRoot 'quality.xml'))
    Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'verify', (Join-Path $resultsRoot 'quality.xml'), '--group', 'quality')
    $env:STUDYTIMER_NATIVE_UI = '1'
    $env:STUDYTIMER_EVIDENCE_DIR = Join-Path $resultsRoot 'native'
    Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'preflight', '--kind', 'native')
    Invoke-CheckedPython -Arguments @('-m', 'pytest', '-m', 'native_ui and not build', '--basetemp', (Join-Path $stage 'test-temp-native'), '--junitxml', (Join-Path $resultsRoot 'native.xml'))
    Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'verify', (Join-Path $resultsRoot 'native.xml'), '--group', 'native')
    if ($DesktopTests) {
        $env:STUDYTIMER_DESKTOP_E2E = '1'
        Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'preflight', '--kind', 'desktop')
    }
    Invoke-CheckedPython -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', 'packaging/StudyTimer.spec')

    $env:STUDYTIMER_BUILD_DIR = Join-Path $stage 'dist\StudyTimer'
    Invoke-CheckedPython -Arguments @('packaging/check_bundle.py', $env:STUDYTIMER_BUILD_DIR)
    $env:STUDYTIMER_EVIDENCE_DIR = Join-Path $resultsRoot 'desktop'
    $buildSelection = if ($DesktopTests) { 'build' } else { 'build and not desktop_ui' }
    $buildGroup = if ($DesktopTests) { 'build' } else { 'smoke' }
    Invoke-CheckedPython -Arguments @('-m', 'pytest', '-m', $buildSelection, '--basetemp', (Join-Path $stage 'test-temp-build'), '--junitxml', (Join-Path $resultsRoot 'build.xml'))
    Invoke-CheckedPython -Arguments @('packaging/ci_checks.py', 'verify', (Join-Path $resultsRoot 'build.xml'), '--group', $buildGroup)
    Invoke-CheckedPython -Arguments @('packaging/check_bundle.py', $env:STUDYTIMER_BUILD_DIR)
    $version = (& $Python -c 'from app import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao ler versão.' }
    $archive = Join-Path $projectRoot "dist\StudyTimer-Windows-v$version.zip"
    New-Item -ItemType Directory -Path (Split-Path $archive -Parent) -Force | Out-Null
    $candidateArchive = Join-Path $stage "StudyTimer-Windows-v$version.zip"
    Compress-Archive -LiteralPath $env:STUDYTIMER_BUILD_DIR -DestinationPath $candidateArchive
    # Verificar também o conteúdo efetivamente entregue no ZIP.
    $zipCheck = Join-Path $stage 'zip-check'
    Expand-Archive -LiteralPath $candidateArchive -DestinationPath $zipCheck
    Invoke-CheckedPython -Arguments @('packaging/check_bundle.py', (Join-Path $zipCheck 'StudyTimer'))
    Copy-Item -LiteralPath $candidateArchive -Destination $archive -Force
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $(Split-Path $archive -Leaf)" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
    Write-Output "Pacote criado: $archive"
}
finally {
    $env:STUDYTIMER_BUILD_DIR = $previousBuildDir
    $env:PYINSTALLER_CONFIG_DIR = $previousPyInstallerConfig
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:STUDYTIMER_NATIVE_UI = $previousNativeUi
    $env:STUDYTIMER_DESKTOP_E2E = $previousDesktopUi
    $env:STUDYTIMER_EVIDENCE_DIR = $previousEvidenceDir
    Pop-Location
}
