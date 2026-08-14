[CmdletBinding()]
param(
    [string]$SourceRepoPath = "",
    [string]$RunnerRoot = (Join-Path $env:LOCALAPPDATA "PuduSubmissionWorker"),
    [string]$RepositoryUrl = "https://github.com/G1026271140-spec/pudu-material-inventory.git",
    [string]$TaskName = "PUDU Submission Worker"
)

$ErrorActionPreference = "Stop"
if (-not $SourceRepoPath) {
    $SourceRepoPath = Split-Path -Parent $PSScriptRoot
}
$SourceRepoPath = [IO.Path]::GetFullPath($SourceRepoPath)
$RunnerRoot = [IO.Path]::GetFullPath($RunnerRoot)
$SourceSecretsPath = Join-Path $SourceRepoPath ".streamlit\secrets.toml"
$SourceRunnerScript = Join-Path $SourceRepoPath "scripts\run_submission_worker.ps1"
$RunnerRepoPath = Join-Path $RunnerRoot "repo"
$RunnerSecretsPath = Join-Path $RunnerRoot "secrets.toml"
$InstalledRunnerScript = Join-Path $RunnerRoot "run_submission_worker.ps1"
$LogDirectory = Join-Path $RunnerRoot "logs"

if (-not (Test-Path -LiteralPath $SourceSecretsPath)) {
    throw "Local Streamlit secrets were not found: $SourceSecretsPath"
}
if (-not (Test-Path -LiteralPath $SourceRunnerScript)) {
    throw "Submission worker runner script was not found: $SourceRunnerScript"
}

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    do {
        Start-Sleep -Milliseconds 250
        $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } while ($null -ne $existingTask -and $existingTask.State -eq "Running")
}

New-Item -ItemType Directory -Path $RunnerRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Copy-Item -LiteralPath $SourceSecretsPath -Destination $RunnerSecretsPath -Force
Copy-Item -LiteralPath $SourceRunnerScript -Destination $InstalledRunnerScript -Force

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = Get-Acl -LiteralPath $RunnerSecretsPath
$acl.SetAccessRuleProtection($true, $false)
$acl.SetAccessRule(
    [Security.AccessControl.FileSystemAccessRule]::new(
        $identity,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
)
Set-Acl -LiteralPath $RunnerSecretsPath -AclObject $acl

$git = (Get-Command git -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $RunnerRepoPath ".git"))) {
    if (Test-Path -LiteralPath $RunnerRepoPath) {
        throw "Runner repository path exists but is not a Git repository: $RunnerRepoPath"
    }
    & $git clone --branch master --single-branch $RepositoryUrl $RunnerRepoPath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to clone the submission worker repository."
    }
}

$bootstrapPython = Join-Path $SourceRepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $bootstrapPython)) {
    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
}

& $InstalledRunnerScript `
    -RepoPath $RunnerRepoPath `
    -SecretsPath $RunnerSecretsPath `
    -LogDirectory $LogDirectory `
    -BootstrapPython $bootstrapPython `
    -SetupOnly
if ($LASTEXITCODE -ne 0) {
    throw "Submission queue setup failed. Check $LogDirectory\bootstrap.log"
}

$powershellPath = Join-Path $PSHOME "powershell.exe"
$taskArguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", ('"{0}"' -f $InstalledRunnerScript),
    "-RepoPath", ('"{0}"' -f $RunnerRepoPath),
    "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath),
    "-LogDirectory", ('"{0}"' -f $LogDirectory),
    "-BootstrapPython", ('"{0}"' -f $bootstrapPython)
) -join " "

$action = New-ScheduledTaskAction `
    -Execute $powershellPath `
    -Argument $taskArguments `
    -WorkingDirectory $RunnerRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Processes recoverable PUDU application submissions from Feishu Base."
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$running = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    $state = (Get-ScheduledTask -TaskName $TaskName).State
    if ($state -eq "Running") {
        $running = $true
        break
    }
}
if (-not $running) {
    throw "The submission worker task did not remain running. Check $LogDirectory"
}

Write-Host "Installed and started scheduled task: $TaskName" -ForegroundColor Green
Write-Host "Runner: $RunnerRoot"
Write-Host "Queue and worker log: $LogDirectory\worker.log"
Write-Host "Bootstrap log: $LogDirectory\bootstrap.log"
