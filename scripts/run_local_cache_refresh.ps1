[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [string]$SecretsPath,

    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,

    [string]$BootstrapPython = "",

    [switch]$Interactive
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$CacheFiles = @(
    "data/page_data_cache.json",
    "data/request_form_cache.json",
    "data/contact_departments_cache.json",
    "data/warehouse_location_cache.json"
)
$CacheDirectories = @(
    "assets/gift_projects",
    "assets/warehouse_locations"
)
$CachePaths = $CacheFiles + $CacheDirectories
$MutexName = "Local\PuduMaterialCacheRefresh"
$Mutex = [Threading.Mutex]::new($false, $MutexName)
$HasMutex = $false
$ExitCode = 0
$FinalMessage = ""
$LogPath = ""

function Write-RunnerLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level = "INFO"
    )

    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
    if ($Interactive) {
        $color = switch ($Level) {
            "ERROR" { "Red" }
            "WARN" { "Yellow" }
            default { "Gray" }
        }
        Write-Host $line -ForegroundColor $color
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-RunnerLog ("> {0} {1}" -f (Split-Path -Leaf $FilePath), ($Arguments -join " "))
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $FilePath @Arguments 2>&1)
        $commandExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    foreach ($line in $output) {
        Write-RunnerLog ([string]$line)
    }
    if ($commandExitCode -ne 0) {
        throw "Command failed with exit code ${commandExitCode}: $FilePath"
    }
    return $output
}

function Write-RunnerStatus {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Success,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $status = [ordered]@{
        success = $Success
        finished_at = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        message = $Message
        log_path = $script:LogPath
    }
    $status | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "latest-status.json") -Encoding UTF8
    Copy-Item -LiteralPath $script:LogPath -Destination (Join-Path $LogDirectory "latest.log") -Force
}

try {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $LogPath = Join-Path $LogDirectory ("refresh-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    New-Item -ItemType File -Path $LogPath -Force | Out-Null

    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        $FinalMessage = "Another cache refresh is already running; this invocation was skipped."
        Write-RunnerLog $FinalMessage "WARN"
        Write-RunnerStatus $true $FinalMessage
        return
    }

    Write-RunnerLog "Starting local static cache refresh."
    $RepoPath = [IO.Path]::GetFullPath($RepoPath)
    $SecretsPath = [IO.Path]::GetFullPath($SecretsPath)
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) {
        throw "Runner repository is missing: $RepoPath"
    }
    if (-not (Test-Path -LiteralPath $SecretsPath)) {
        throw "Runner secrets file is missing: $SecretsPath"
    }

    $git = (Get-Command git -ErrorAction Stop).Source
    Push-Location -LiteralPath $RepoPath
    try {
        $statusLines = @(Invoke-CheckedCommand $git @("status", "--porcelain", "--untracked-files=no"))
        $unexpectedChanges = @()
        foreach ($statusLine in $statusLines) {
            $statusText = [string]$statusLine
            if ($statusText.Length -lt 4) {
                continue
            }
            $changedPath = $statusText.Substring(3).Replace("\", "/").Trim('"')
            $isCachePath = $changedPath -in $CacheFiles
            foreach ($cacheDirectory in $CacheDirectories) {
                if ($changedPath -eq $cacheDirectory -or $changedPath.StartsWith("$cacheDirectory/")) {
                    $isCachePath = $true
                    break
                }
            }
            if (-not $isCachePath) {
                $unexpectedChanges += $changedPath
            }
        }
        if ($unexpectedChanges.Count -gt 0) {
            throw "Runner repository has unexpected changes: $($unexpectedChanges -join ', ')"
        }
        if ($statusLines.Count -gt 0) {
            Invoke-CheckedCommand $git (@("restore", "--staged", "--worktree", "--") + $CachePaths) | Out-Null
        }

        Invoke-CheckedCommand $git @("fetch", "origin", "master") | Out-Null
        Invoke-CheckedCommand $git @("switch", "master") | Out-Null
        Invoke-CheckedCommand $git @("pull", "--ff-only", "origin", "master") | Out-Null

        $repoSecretsDirectory = Join-Path $RepoPath ".streamlit"
        New-Item -ItemType Directory -Path $repoSecretsDirectory -Force | Out-Null
        Copy-Item -LiteralPath $SecretsPath -Destination (Join-Path $repoSecretsDirectory "secrets.toml") -Force

        $venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            if (-not $BootstrapPython) {
                $BootstrapPython = (Get-Command python -ErrorAction Stop).Source
            }
            if (-not (Test-Path -LiteralPath $BootstrapPython)) {
                throw "Bootstrap Python was not found: $BootstrapPython"
            }
            Write-RunnerLog "Creating the dedicated Python environment."
            Invoke-CheckedCommand $BootstrapPython @("-m", "venv", (Join-Path $RepoPath ".venv")) | Out-Null
        }

        $requirementsPath = Join-Path $RepoPath "requirements.txt"
        $requirementsStamp = Join-Path $RepoPath ".venv\requirements.sha256"
        $requirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
        $installedHash = if (Test-Path -LiteralPath $requirementsStamp) {
            (Get-Content -LiteralPath $requirementsStamp -Raw -Encoding UTF8).Trim()
        } else {
            ""
        }
        if ($requirementsHash -ne $installedHash) {
            Write-RunnerLog "Installing or updating Python dependencies."
            Invoke-CheckedCommand $venvPython @(
                "-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath
            ) | Out-Null
            Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
        }

        Write-RunnerLog "Maintaining inventory row status before refreshing static cache."
        Invoke-CheckedCommand $venvPython @("scripts/maintain_inventory_status.py") | Out-Null

        Write-RunnerLog "Refreshing page data, request options, contact directory, and warehouse location image cache."
        foreach ($generator in @(
            "scripts/generate_page_data_cache.py",
            "scripts/generate_request_form_cache.py",
            "scripts/generate_contact_departments_cache.py",
            "scripts/generate_warehouse_location_cache.py"
        )) {
            Invoke-CheckedCommand $venvPython @($generator) | Out-Null
        }
        Write-RunnerLog "Validating page cache, gift project catalog, and warehouse location cache."
        Invoke-CheckedCommand $venvPython @("scripts/validate_page_data_cache.py") | Out-Null
        Write-RunnerLog "Validating active material combinations in the request cache."
        Invoke-CheckedCommand $venvPython @("scripts/validate_request_form_cache.py") | Out-Null
        Invoke-CheckedCommand $venvPython @("scripts/validate_warehouse_location_cache.py") | Out-Null

        Invoke-CheckedCommand $git (@("add", "--") + $CachePaths) | Out-Null
        & $git diff --cached --quiet -- @CachePaths
        $diffExitCode = $LASTEXITCODE
        if ($diffExitCode -eq 0) {
            $FinalMessage = "Static cache is already current; no Git commit was needed."
            Write-RunnerLog $FinalMessage
        } elseif ($diffExitCode -eq 1) {
            Invoke-CheckedCommand $git @(
                "commit", "-m", "Refresh static data cache", "--no-gpg-sign"
            ) | Out-Null
            Invoke-CheckedCommand $git @("push", "origin", "HEAD:master") | Out-Null
            $FinalMessage = "Static cache was refreshed and pushed to GitHub master."
            Write-RunnerLog $FinalMessage
        } else {
            throw "Unable to inspect the generated cache changes."
        }
    } finally {
        Pop-Location
    }

    Write-RunnerStatus $true $FinalMessage
} catch {
    $ExitCode = 1
    $FinalMessage = $_.Exception.Message
    if ($LogPath) {
        Write-RunnerLog $FinalMessage "ERROR"
        Write-RunnerStatus $false $FinalMessage
    }
} finally {
    if ($HasMutex) {
        $Mutex.ReleaseMutex()
    }
    $Mutex.Dispose()
    if ($LogDirectory -and (Test-Path -LiteralPath $LogDirectory)) {
        Get-ChildItem -LiteralPath $LogDirectory -File -Filter "refresh-*.log" |
            Where-Object LastWriteTime -LT (Get-Date).AddDays(-30) |
            Remove-Item -Force
    }
    if ($Interactive) {
        if ($ExitCode -eq 0) {
            Write-Host "`nCache refresh completed." -ForegroundColor Green
        } else {
            Write-Host "`nCache refresh failed. Review the log: $LogPath" -ForegroundColor Red
        }
        Read-Host "Press Enter to close this window"
    }
}

exit $ExitCode
