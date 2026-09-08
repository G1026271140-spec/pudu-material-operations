param(
    [string]$TaskName = "PUDU Global Journey Material Automation",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PythonPath) {
    $PythonPath = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE "Desktop") -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -like "*\.venv\Scripts\python.exe" -and
            (Test-Path -LiteralPath (Join-Path $_.Directory.Parent.Parent.FullName "feishu_bitable.py"))
        } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { throw "Compatible Python runtime not found." }
$PythonwPath = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonwPath)) { throw "Python windowless runtime not found: $PythonwPath" }

New-Item -ItemType Directory -Force -Path (Join-Path $RepoPath "logs"), (Join-Path $RepoPath "state") | Out-Null
& $PythonPath (Join-Path $RepoPath "material_automation.py") --check
if ($LASTEXITCODE -ne 0) { throw "Automation validation failed." }
& $PythonPath (Join-Path $RepoPath "material_automation.py") --initialize
if ($LASTEXITCODE -ne 0) { throw "Automation baseline initialization failed." }

$action = New-ScheduledTaskAction -Execute $PythonwPath -Argument 'material_automation.py --watch' -WorkingDirectory $RepoPath
$TaskUser = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $TaskUser
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.State -eq "Running") { Stop-ScheduledTask -TaskName $TaskName }
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Downloads new Global Journey material packages, extracts them, and uploads images/videos to Base." -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started scheduled task: $TaskName"
