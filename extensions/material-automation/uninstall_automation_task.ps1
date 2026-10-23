param([string]$TaskName = "PUDU Global Journey Material Automation")
$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) { Write-Host "Scheduled task not found: $TaskName"; exit 0 }
if ($task.State -eq "Running") { Stop-ScheduledTask -TaskName $TaskName }
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
