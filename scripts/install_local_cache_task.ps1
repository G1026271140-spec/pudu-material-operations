[CmdletBinding()]
param(
    [string]$SourceRepoPath = "",
    [string]$RunnerRoot = (Join-Path $env:LOCALAPPDATA "PuduMaterialCacheRunner"),
    [string]$RepositoryUrl = "https://github.com/G1026271140-spec/pudu-material-inventory.git",
    [string]$Branch = "master",
    [string]$TaskName = "PUDU Material Cache Refresh",
    [string]$ContactTaskName = "PUDU Contact Cache Refresh",
    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')][string]$MorningTime = "10:30",
    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')][string]$AfternoonTime = "16:30",
    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')][string]$ContactTime = "11:00",
    [string]$ContactDays = "Monday,Wednesday,Friday",
    [switch]$SkipInitialRun
)

$ErrorActionPreference = "Stop"
if (-not $SourceRepoPath) {
    $SourceRepoPath = Split-Path -Parent $PSScriptRoot
}
$SourceRepoPath = [IO.Path]::GetFullPath($SourceRepoPath)
$RunnerRoot = [IO.Path]::GetFullPath($RunnerRoot)
$SourceSecretsPath = Join-Path $SourceRepoPath ".streamlit\secrets.toml"
$SourceRunnerScript = Join-Path $SourceRepoPath "scripts\run_local_cache_refresh.ps1"
$RunnerRepoPath = Join-Path $RunnerRoot "repo"
$RunnerSecretsPath = Join-Path $RunnerRoot "secrets.toml"
$InstalledRunnerScript = Join-Path $RunnerRoot "run_local_cache_refresh.ps1"
$LogDirectory = Join-Path $RunnerRoot "logs"

if (-not (Test-Path -LiteralPath $SourceSecretsPath)) {
    throw "Local Streamlit secrets were not found: $SourceSecretsPath"
}
if (-not (Test-Path -LiteralPath $SourceRunnerScript)) {
    throw "Cache runner script was not found: $SourceRunnerScript"
}

foreach ($taskName in @($TaskName, $ContactTaskName)) {
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName $taskName
    }
}

function Stop-RunnerPowerShell([string]$RunnerScript, [string]$Scope) {
    $escapedScript = [Regex]::Escape([IO.Path]::GetFullPath($RunnerScript))
    $escapedScope = [Regex]::Escape($Scope)
    $staleShells = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -match $escapedScript -and
            $_.CommandLine -match "-CacheScope\s+$escapedScope" -and
            $_.CommandLine -notmatch "-Interactive"
        }
    foreach ($process in $staleShells) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Stop-RunnerPowerShell $InstalledRunnerScript "Material"
Stop-RunnerPowerShell $InstalledRunnerScript "Contacts"

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
    & $git clone --branch $Branch --single-branch $RepositoryUrl $RunnerRepoPath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to clone the runner repository."
    }
}

& $git -C $RunnerRepoPath config user.name "pudu-cache-runner"
& $git -C $RunnerRepoPath config user.email "pudu-cache-runner@users.noreply.github.com"
& $git -C $RunnerRepoPath fetch origin $Branch
if ($LASTEXITCODE -ne 0) { throw "Unable to fetch the cache runner repository." }
& $git -C $RunnerRepoPath switch $Branch
if ($LASTEXITCODE -ne 0) { throw "Unable to switch the cache runner repository to $Branch." }
& $git -C $RunnerRepoPath pull --ff-only origin $Branch
if ($LASTEXITCODE -ne 0) { throw "Unable to update the cache runner repository." }

$bootstrapPython = Join-Path $SourceRepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $bootstrapPython)) {
    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
}

$powershellPath = (Get-Process -Id $PID).Path
if (-not (Test-Path -LiteralPath $powershellPath)) {
    $powershellPath = Join-Path $PSHOME "pwsh.exe"
}
$taskArguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", ('"{0}"' -f $InstalledRunnerScript),
    "-RepoPath", ('"{0}"' -f $RunnerRepoPath),
    "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath),
    "-LogDirectory", ('"{0}"' -f $LogDirectory),
    "-BootstrapPython", ('"{0}"' -f $bootstrapPython),
    "-CacheScope", "Material"
) -join " "

$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $taskArguments -WorkingDirectory $RunnerRoot
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At $MorningTime)
    (New-ScheduledTaskTrigger -Daily -At $AfternoonTime)
)
$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

$contactLogDirectory = Join-Path $LogDirectory "contacts"
New-Item -ItemType Directory -Path $contactLogDirectory -Force | Out-Null
$contactArguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", ('"{0}"' -f $InstalledRunnerScript),
    "-RepoPath", ('"{0}"' -f $RunnerRepoPath),
    "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath),
    "-LogDirectory", ('"{0}"' -f $contactLogDirectory),
    "-BootstrapPython", ('"{0}"' -f $bootstrapPython),
    "-CacheScope", "Contacts"
) -join " "
$contactAction = New-ScheduledTaskAction -Execute $powershellPath -Argument $contactArguments -WorkingDirectory $RunnerRoot
$contactDayValues = @($ContactDays -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$allowedContactDays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
foreach ($contactDay in $contactDayValues) {
    if ($contactDay -notin $allowedContactDays) { throw "Invalid contact cache weekday: $contactDay" }
}
if ($contactDayValues.Count -eq 0) { throw "At least one contact cache weekday is required." }
$contactTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $contactDayValues -At $ContactTime
$contactTask = New-ScheduledTask -Action $contactAction -Trigger $contactTrigger -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $ContactTaskName -InputObject $contactTask -Force | Out-Null

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Update PUDU Static Cache.lnk"
$shortcutArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $InstalledRunnerScript),
    "-RepoPath", ('"{0}"' -f $RunnerRepoPath),
    "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath),
    "-LogDirectory", ('"{0}"' -f $LogDirectory),
    "-BootstrapPython", ('"{0}"' -f $bootstrapPython),
    "-CacheScope", "Material",
    "-Interactive"
) -join " "
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = $shortcutArguments
$shortcut.WorkingDirectory = $RunnerRoot
$shortcut.Description = "Refresh PUDU material cache from Feishu and push it to GitHub"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
$shortcut.Save()

$warehouseLogDirectory = Join-Path $LogDirectory "warehouse"
New-Item -ItemType Directory -Path $warehouseLogDirectory -Force | Out-Null
$warehouseShortcutPath = Join-Path $desktop "Update PUDU Image Cache.lnk"
$warehouseArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $InstalledRunnerScript),
    "-RepoPath", ('"{0}"' -f $RunnerRepoPath),
    "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath),
    "-LogDirectory", ('"{0}"' -f $warehouseLogDirectory),
    "-BootstrapPython", ('"{0}"' -f $bootstrapPython),
    "-CacheScope", "Warehouse",
    "-Interactive"
) -join " "
$warehouseShortcut = $shell.CreateShortcut($warehouseShortcutPath)
$warehouseShortcut.TargetPath = $powershellPath
$warehouseShortcut.Arguments = $warehouseArguments
$warehouseShortcut.WorkingDirectory = $RunnerRoot
$warehouseShortcut.Description = "Refresh PUDU warehouse location, warehouse images, and request category images"
$warehouseShortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
$warehouseShortcut.Save()

Write-Host "Local cache runner installed." -ForegroundColor Green
Write-Host "Task: $TaskName (daily at $MorningTime and $AfternoonTime)"
Write-Host "Contact task: $ContactTaskName ($($contactDayValues -join ', ') at $ContactTime)"
Write-Host "Runner: $RunnerRoot"
Write-Host "Manual shortcut: $shortcutPath"
Write-Host "Warehouse shortcut: $warehouseShortcutPath"
Write-Host "Logs: $LogDirectory"

if (-not $SkipInitialRun) {
    Write-Host "Running the first cache refresh now..." -ForegroundColor Cyan
    & $InstalledRunnerScript `
        -RepoPath $RunnerRepoPath `
        -SecretsPath $RunnerSecretsPath `
        -LogDirectory $LogDirectory `
        -BootstrapPython $bootstrapPython `
        -CacheScope Material
    if ($LASTEXITCODE -ne 0) {
        throw "Initial cache refresh failed. Check $LogDirectory\latest.log"
    }
}
