[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [int]$ControlCenterPid,

    [string]$CommitMessage = "",

    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,

    [switch]$PreflightOnly,

    [switch]$DoNotReopen
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoPath = [IO.Path]::GetFullPath($RepoPath)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$LogPath = Join-Path $LogDirectory ("release-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$StatusPath = Join-Path $LogDirectory "latest-status.json"
$Mutex = $null
$HasMutex = $false
$NewVersion = ""
$ReleaseStage = "等待控制程序退出"
$ExitCode = 0

function Write-ReleaseLog([string]$Message, [string]$Level = "INFO") {
    $Line = "{0} [{1}] [{2}] {3}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $script:ReleaseStage, $Message
    Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    Copy-Item -LiteralPath $LogPath -Destination (Join-Path $LogDirectory "latest.log") -Force
}

function Set-ReleaseStatus([string]$State, [string]$Message) {
    [ordered]@{
        state = $State
        stage = $script:ReleaseStage
        version = $script:NewVersion
        message = $Message
        updated_at = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        log_path = $script:LogPath
    } | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding UTF8
}

function Set-Stage([string]$Stage) {
    $script:ReleaseStage = $Stage
    Write-ReleaseLog "Stage started."
    Set-ReleaseStatus "running" "正在执行：$Stage"
}

function Invoke-Checked([string]$FilePath, [string[]]$Arguments) {
    Write-ReleaseLog ("> {0} {1}" -f (Split-Path -Leaf $FilePath), ($Arguments -join " "))
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Output = @(& $FilePath @Arguments 2>&1)
        $Code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
    foreach ($Line in $Output) { Write-ReleaseLog ([string]$Line) }
    if ($Code -ne 0) { throw "Command failed with exit code ${Code}: $FilePath" }
    return $Output
}

function Wait-HttpHealth([string]$Url, [int]$Attempts = 60) {
    $LastError = ""
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 8
            if ($Response.StatusCode -eq 200) {
                Write-ReleaseLog "Health check passed: $Url"
                return
            }
            $LastError = "HTTP $($Response.StatusCode)"
        } catch {
            $LastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "Health check failed: $Url; $LastError"
}

function Stop-And-Wait-For-ControlCenter {
    $Process = Get-Process -Id $ControlCenterPid -ErrorAction SilentlyContinue
    if ($null -ne $Process) {
        Write-ReleaseLog "Waiting for control center process $ControlCenterPid to close."
        $Process.WaitForExit(30000) | Out-Null
    }
    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
        $Remaining = @(Get-Process -Name "Marketing materials Control" -ErrorAction SilentlyContinue)
        if ($Remaining.Count -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "Marketing materials Control did not close; release cannot replace the EXE."
}

try {
    New-Item -ItemType File -Force -Path $LogPath | Out-Null
    Set-ReleaseStatus "running" "版本刷新任务已启动。"
    if (-not $PreflightOnly) { Stop-And-Wait-For-ControlCenter }
    Push-Location -LiteralPath $RepoPath

    Set-Stage "发布预检"
    $Git = (Get-Command git.exe -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) { throw "Not a Git repository: $RepoPath" }
    $Branch = (& $Git branch --show-current).Trim()
    if ($Branch -ne "master") { throw "Release is only allowed from master; current branch: $Branch" }
    $Unmerged = @(& $Git diff --name-only --diff-filter=U)
    if ($Unmerged.Count -gt 0) { throw "Resolve merge conflicts before release: $($Unmerged -join ', ')" }
    Invoke-Checked $Git @("fetch", "origin", "master") | Out-Null
    $Counts = ((& $Git rev-list --left-right --count "HEAD...origin/master").Trim() -split "\s+")
    if ([int]$Counts[0] -ne 0 -or [int]$Counts[1] -ne 0) {
        throw "Local master must match origin/master before release; ahead=$($Counts[0]), behind=$($Counts[1])."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".streamlit\secrets.toml"))) {
        throw "Local .streamlit/secrets.toml is required."
    }
    $Mutex = [Threading.Mutex]::new($false, "Local\PuduMaterialCacheRefresh")
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) { throw "Another cache refresh is running; try again after it finishes." }

    $Python = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
    if ($PreflightOnly) {
        Set-ReleaseStatus "success" "发布预检通过；未修改文件、未推送、未重启。"
        Write-ReleaseLog "Preflight-only check completed successfully."
        return
    }

    Set-Stage "递增应用版本"
    $VersionOutput = @(Invoke-Checked $Python @("scripts/bump_release_version.py", "--root", $RepoPath))
    $VersionInfo = $VersionOutput[-1] | ConvertFrom-Json
    $CurrentVersion = [string]$VersionInfo.current_version
    $NewVersion = [string]$VersionInfo.new_version
    Write-ReleaseLog "Version changed: $CurrentVersion -> $NewVersion"

    Set-Stage "刷新全部页面缓存"
    Invoke-Checked "powershell.exe" @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $RepoPath "scripts\run_control_center_manual_tool.ps1"),
        "-Tool", "AllCaches", "-RepoPath", $RepoPath,
        "-SecretsPath", (Join-Path $RepoPath ".streamlit\secrets.toml"),
        "-LogDirectory", (Join-Path $RepoPath "work\control_center\manual-tools"),
        "-MutexAlreadyHeld", "-SkipLivePublication"
    ) | Out-Null
    $Python = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { throw "Project Python runtime was not created: $Python" }

    Set-Stage "完整测试与发布校验"
    Invoke-Checked $Python @("-m", "pytest", "-q") | Out-Null
    Invoke-Checked $Python @("scripts/validate_release_consistency.py") | Out-Null
    Invoke-Checked $Python @("scripts/validate_page_data_cache.py") | Out-Null
    Invoke-Checked $Python @("scripts/validate_request_form_cache.py") | Out-Null
    Invoke-Checked $Python @("scripts/validate_warehouse_location_cache.py") | Out-Null

    Set-Stage "重新打包控制程序"
    Invoke-Checked "powershell.exe" @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $RepoPath "scripts\build_control_center_app.ps1")) | Out-Null
    $ExeVersion = (Get-Item -LiteralPath (Join-Path $RepoPath "Marketing materials Control.exe")).VersionInfo.ProductVersion
    if ($ExeVersion -ne $NewVersion) { throw "Packaged EXE version mismatch: expected $NewVersion, got $ExeVersion" }

    Set-Stage "提交并推送 GitHub"
    Invoke-Checked $Git @("add", "-A") | Out-Null
    $StagedPaths = @(& $Git diff --cached --name-only)
    $SensitivePaths = @($StagedPaths | Where-Object { $_ -match '(?i)(^|/)(\.env($|\.)|secrets?\.toml$|credentials?\.json$|[^/]+\.(pem|key|pfx|p12)$)' })
    if ($SensitivePaths.Count -gt 0) { throw "Sensitive files cannot be committed: $($SensitivePaths -join ', ')" }
    & $Git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { throw "No changes are available to release." }
    if ([string]::IsNullOrWhiteSpace($CommitMessage)) { $CommitMessage = "Release $NewVersion" }
    if ($CommitMessage -match "[\r\n]") { throw "Commit message cannot contain a newline." }
    Invoke-Checked $Git @("commit", "-m", $CommitMessage, "--no-gpg-sign") | Out-Null
    Invoke-Checked $Git @("push", "origin", "master") | Out-Null
    $ExpectedRevision = (& $Git rev-parse --short HEAD).Trim()
    Write-ReleaseLog "Pushed $NewVersion at revision $ExpectedRevision."

    Set-Stage "同步并重启运行组件"
    Invoke-Checked "powershell.exe" @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $RepoPath "scripts\run_control_center_manual_tool.ps1"),
        "-Tool", "SyncAllRuntimes", "-RepoPath", $RepoPath,
        "-SecretsPath", (Join-Path $RepoPath ".streamlit\secrets.toml"),
        "-LogDirectory", (Join-Path $RepoPath "work\control_center\manual-tools")
    ) | Out-Null

    Set-Stage "运行状态与健康验证"
    $Config = Get-Content -LiteralPath (Join-Path $RepoPath "config\project_config.json") -Raw | ConvertFrom-Json
    $Port = [int]$Config.deployment.local_web.port
    Wait-HttpHealth "http://127.0.0.1:$Port/api/health"
    Wait-HttpHealth "$($Config.deployment.custom_domain.TrimEnd('/'))/api/health"
    foreach ($TaskName in @(
        $Config.deployment.local_web.web_task_name,
        $Config.deployment.local_web.tunnel_task_name,
        $Config.submission_worker.task_name,
        $Config.card_worker.task_name,
        $Config.cache_runner.task_name,
        $Config.cache_runner.contact_task_name
    )) {
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $Info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-ReleaseLog ("Task {0}: state={1}; lastResult={2}; lastRun={3}" -f $TaskName, $Task.State, $Info.LastTaskResult, $Info.LastRunTime)
    }
    foreach ($RunnerRoot in @(
        [Environment]::ExpandEnvironmentVariables([string]$Config.deployment.local_web.runner_root),
        [Environment]::ExpandEnvironmentVariables([string]$Config.submission_worker.runner_root),
        [Environment]::ExpandEnvironmentVariables([string]$Config.cache_runner.runner_root)
    )) {
        $RunnerRepo = Join-Path $RunnerRoot "repo"
        $RunnerRevision = (& $Git -C $RunnerRepo rev-parse --short HEAD).Trim()
        $RunnerStatus = @(& $Git -C $RunnerRepo status --porcelain)
        if ($RunnerRevision -ne $ExpectedRevision -or $RunnerStatus.Count -gt 0) {
            throw "Runner verification failed: $RunnerRepo revision=$RunnerRevision dirty=$($RunnerStatus.Count) expected=$ExpectedRevision"
        }
        Write-ReleaseLog "Runner verified: $RunnerRepo @ $RunnerRevision"
    }
    Set-ReleaseStatus "success" "$NewVersion 已刷新、推送并完成运行验证。"
    Write-ReleaseLog "Release completed successfully."
} catch {
    $ExitCode = 1
    Write-ReleaseLog $_.Exception.Message "ERROR"
    Set-ReleaseStatus "failed" $_.Exception.Message
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    if ($null -ne $Mutex) { $Mutex.Dispose() }
    $ControlCenter = Join-Path $RepoPath "Marketing materials Control.exe"
    if ((-not $DoNotReopen) -and (Test-Path -LiteralPath $ControlCenter)) {
        Start-Process -FilePath $ControlCenter -WorkingDirectory $RepoPath
    }
}

exit $ExitCode
