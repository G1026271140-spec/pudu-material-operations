[CmdletBinding()]
param(
    [string]$ShortcutName = "Marketing materials Control.lnk"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LauncherPath = Join-Path $PSScriptRoot "run_control_center.ps1"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath $ShortcutName

if (-not (Test-Path -LiteralPath $LauncherPath)) {
    throw "Control center launcher was not found: $LauncherPath"
}

$PowerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShellPath
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LauncherPath`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Open Marketing materials Control"
$Shortcut.IconLocation = "$(Join-Path $ProjectRoot 'Marketing materials Control.exe'),0"
$Shortcut.Save()

Write-Output $ShortcutPath
