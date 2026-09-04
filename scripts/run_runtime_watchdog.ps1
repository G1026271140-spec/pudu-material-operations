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

function Test-RuntimeProcess([string]$Name) {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    switch ($Name) {
        "PUDU Material Web App" {
            return @($processes | Where-Object {
                $_.Name -in @("python.exe", "pythonw.exe") -and
                $_.CommandLine -match "streamlit\s+run\s+app\.py"
            }).Count -gt 0
        }
        "PUDU Material Cloudflare Tunnel" {
            return @($processes | Where-Object {
                $_.Name -eq "cloudflared.exe" -and
                $_.CommandLine -match "tunnel\s+--"
            }).Count -gt 0
        }
        "PUDU Submission Worker" {
            return @($processes | Where-Object {
                $_.Name -in @("powershell.exe", "pwsh.exe") -and
                $_.CommandLine -match "run_submission_worker\.ps1"
            }).Count -gt 0
        }
        default { return $false }
    }
}

foreach ($name in $TaskName) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-WatchdogLog "Task not found: $name" "WARN"
        continue
    }
    if (Test-RuntimeProcess $name) { continue }
    try {
        Start-ScheduledTask -TaskName $name -ErrorAction Stop
        Write-WatchdogLog "Restarted task: $name (previous state: $($task.State))" "WARN"
    } catch {
        Write-WatchdogLog "Unable to restart task: $name; $($_.Exception.Message)" "ERROR"
    }
}
