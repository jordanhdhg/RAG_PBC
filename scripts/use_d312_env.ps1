# Dot-source this script in the PowerShell session that will run the project:
#   . .\scripts\use_d312_env.ps1
# It does not modify system PATH, the registry, or the legacy .venv.

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $ProjectRoot '.runtime'
$VenvRoot = Join-Path $ProjectRoot '.venv-d312'

if (-not (Test-Path -LiteralPath (Join-Path $VenvRoot 'Scripts\python.exe'))) {
    throw "D-local environment is missing: $VenvRoot"
}

$TempRoot = Join-Path $ProjectRoot 'data\cache\tmp'
$PipCache = Join-Path $ProjectRoot 'data\cache\pip'
$UvCache = Join-Path $ProjectRoot 'data\cache\uv'
$TiktokenCache = Join-Path $ProjectRoot 'data\cache\tiktoken'
$ModelRoot = Join-Path $ProjectRoot 'data\models\bge-m3'
$ManagedPython = Join-Path $RuntimeRoot 'managed-python'
$ManagedPythonBin = Join-Path $RuntimeRoot 'managed-python-bin'

New-Item -ItemType Directory -Force -Path @(
    $TempRoot,
    $PipCache,
    $UvCache,
    $TiktokenCache,
    $ModelRoot,
    (Join-Path $ModelRoot 'hub'),
    (Join-Path $ModelRoot 'xet'),
    $ManagedPythonBin
) | Out-Null

$env:PYTHONIOENCODING = 'utf-8'
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:PIP_CACHE_DIR = $PipCache
$env:UV_CACHE_DIR = $UvCache
$env:UV_PYTHON_INSTALL_DIR = $ManagedPython
$env:UV_PYTHON_BIN_DIR = $ManagedPythonBin
$env:TIKTOKEN_CACHE_DIR = $TiktokenCache
$env:HF_HOME = $ModelRoot
$env:HF_HUB_CACHE = $ModelRoot
$env:HF_XET_CACHE = Join-Path $ModelRoot 'xet'

Write-Host "D-local project environment is ready: $VenvRoot"
Write-Host 'Run: .\.venv-d312\Scripts\python.exe -m pytest -q'
