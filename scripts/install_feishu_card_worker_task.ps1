param(
    [string]$TaskName = "PUDU Feishu Card Worker"
)

$ErrorActionPreference = "Stop"
$RepoPath = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $RepoPath ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python runtime not found: $PythonPath"
}

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "scripts\feishu_card_worker.py" `
    -WorkingDirectory $RepoPath
$TaskUser = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $TaskUser
$settings = New-ScheduledTaskSettingsSet `
	-Hidden `
	-AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Keeps the PUDU Feishu inventory text and screenshot bot online." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started scheduled task: $TaskName"
