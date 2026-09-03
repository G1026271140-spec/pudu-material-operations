[CmdletBinding()]
param(
    [string[]]$TaskName = @(
        "PUDU Material Web App",
        "PUDU Material Cloudflare Tunnel",
        "PUDU Submission Worker"
    ),
    [string]$LogDirectory = "$env:LOCALAPPDATA\PuduRuntimeWatchdog"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$logPath = Join-Path $LogDirectory "watchdog.log"
function Write-WatchdogLog([string]$Message, [string]$Level = "INFO") {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ("{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message)
}

foreach ($name in $TaskName) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-WatchdogLog "Task not found: $name" "WARN"
        continue
    }
    if ([string]$task.State -eq "Running") { continue }
    try {
        Start-ScheduledTask -TaskName $name -ErrorAction Stop
        Write-WatchdogLog "Restarted task: $name (previous state: $($task.State))" "WARN"
    } catch {
        Write-WatchdogLog "Unable to restart task: $name; $($_.Exception.Message)" "ERROR"
    }
}
