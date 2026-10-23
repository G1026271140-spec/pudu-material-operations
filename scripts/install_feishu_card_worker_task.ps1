param(
    [string]$TaskName = "PUDU Feishu Card Worker"
)

$ErrorActionPreference = "Stop"
$RepoPath = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $RepoPath ".venv\Scripts\pythonw.exe"
$WorkerScript = Join-Path $RepoPath "scripts\feishu_card_worker.py"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python runtime not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath $WorkerScript)) {
    throw "Card worker script not found: $WorkerScript"
}

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument ('"{0}"' -f $WorkerScript) `
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

$escapedWorker = [Regex]::Escape([IO.Path]::GetFullPath($WorkerScript))
$relativeWorker = 'scripts[\\/]feishu_card_worker\.py'
$staleWorkers = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -match $escapedWorker -or $_.CommandLine -match $relativeWorker) }
foreach ($process in $staleWorkers) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
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
