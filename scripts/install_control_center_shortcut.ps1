[CmdletBinding()]
param(
    [string]$ShortcutName = "PUDU 配置与运行控制台.lnk"
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
$Shortcut.Description = "Open the PUDU configuration and operations control center"
$Shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$Shortcut.Save()

Write-Output $ShortcutPath
