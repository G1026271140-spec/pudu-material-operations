[CmdletBinding()]
param([string]$ShortcutName = "PUDU Material Operations Setup.lnk")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot "run_deployment_launcher.ps1"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop $ShortcutName
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Launcher)
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Install or migrate PUDU Material Operations"
$Icon = Join-Path $ProjectRoot "PUDU Material Operations Setup.exe"
if (Test-Path -LiteralPath $Icon) { $Shortcut.IconLocation = "$Icon,0" }
$Shortcut.Save()
Write-Host "Shortcut installed: $ShortcutPath" -ForegroundColor Green
