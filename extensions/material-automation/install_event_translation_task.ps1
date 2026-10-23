param([string]$TaskName = "PUDU Global Events English Sync")

$ErrorActionPreference = "Stop"
$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = (Get-Command python -ErrorAction Stop).Source
$PythonwPath = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonwPath)) { throw "Python windowless runtime not found: $PythonwPath" }
if (-not (Test-Path -LiteralPath $PythonPath) -or -not (Test-Path -LiteralPath $PythonwPath)) { throw "Project Python runtime not found." }

New-Item -ItemType Directory -Force -Path (Join-Path $RepoPath "logs"), (Join-Path $RepoPath "state") | Out-Null
$action = New-ScheduledTaskAction -Execute $PythonwPath -Argument 'event_translation_sync.py --once' -WorkingDirectory $RepoPath
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "11:00"),
    (New-ScheduledTaskTrigger -Daily -At "17:30")
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromMinutes(30)) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -StartWhenAvailable
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing -and $existing.State -eq "Running") { Stop-ScheduledTask -TaskName $TaskName }
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Description "Synchronizes Americas, Australia/New Zealand and Latin America event records into the English Base table at 11:00 and 17:30 daily." -Force | Out-Null

$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "PUDU Global Events English Sync (Manual).lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $RepoPath "run_event_translation_sync_manual.ps1") + '"'
$shortcut.WorkingDirectory = $RepoPath
$shortcut.Description = "Run the Global Events English sync immediately."
$shortcut.Save()

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Created manual shortcut: $shortcutPath"
