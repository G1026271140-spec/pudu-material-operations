[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonwPath = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

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
