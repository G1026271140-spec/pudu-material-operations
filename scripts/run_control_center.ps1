[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PackagedApp = Join-Path $ProjectRoot "Marketing materials Control.exe"
$PackagedVersionFile = Join-Path $ProjectRoot "Marketing materials Control.version"
$PythonwPath = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if ((Test-Path -LiteralPath $PackagedApp) -and (Test-Path -LiteralPath $PackagedVersionFile)) {
    $SourceVersion = (Select-String -LiteralPath (Join-Path $ProjectRoot "app.py") -Pattern '^APP_VERSION\s*=\s*["'']([^"'']+)' | Select-Object -First 1).Matches.Groups[1].Value
    $PackagedVersion = (Get-Content -LiteralPath $PackagedVersionFile -Raw).Trim()
}

if ((Test-Path -LiteralPath $PackagedApp) -and ($PackagedVersion -eq $SourceVersion)) {
    Start-Process -FilePath $PackagedApp -WorkingDirectory $ProjectRoot
    return
}

if (-not (Test-Path -LiteralPath $PythonwPath)) {
    if (Test-Path -LiteralPath $PythonPath) {
        $PythonwPath = $PythonPath
    } else {
        $command = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($null -eq $command) { $command = Get-Command python.exe -ErrorAction Stop }
        $PythonwPath = $command.Source
    }
}

Start-Process `
    -FilePath $PythonwPath `
    -ArgumentList @("-m", "control_center") `
    -WorkingDirectory $ProjectRoot
