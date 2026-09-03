[CmdletBinding()]
param(
    [string]$WatchdogScript = "",
    [string]$TaskName = "PUDU Runtime Watchdog",
    [string]$LogDirectory = "$env:LOCALAPPDATA\PuduRuntimeWatchdog"
)

$ErrorActionPreference = "Stop"
if (-not $WatchdogScript) { $WatchdogScript = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\run_runtime_watchdog.ps1" }
$WatchdogScript = [IO.Path]::GetFullPath($WatchdogScript)
if (-not (Test-Path -LiteralPath $WatchdogScript)) { throw "Watchdog script not found: $WatchdogScript" }
$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = @(
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", ('"{0}"' -f $WatchdogScript), "-LogDirectory", ('"{0}"' -f $LogDirectory)
) -join " "
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments -WorkingDirectory (Split-Path -Parent $WatchdogScript)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(10) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -InputObject (New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Restarts critical PUDU runtime tasks when stopped.") -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed hidden runtime watchdog: $TaskName" -ForegroundColor Green
