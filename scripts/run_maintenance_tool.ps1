[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("MaterialCache", "ContactCache", "WarehouseCache", "AllCaches", "ValidateCaches", "FeishuSmokeTest", "WakeStreamlit", "SyncAllRuntimes", "RefreshCommitRestartApp")]
    [string]$Tool,

    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$SecretsPath = "",

    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,

    [switch]$MutexAlreadyHeld,

    [switch]$SkipLivePublication
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$RepoPath = [IO.Path]::GetFullPath($RepoPath)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$LogPath = Join-Path $LogDirectory ("manual-{0}-{1}.log" -f $Tool, (Get-Date -Format "yyyyMMdd-HHmmss"))
$Mutex = $null
$HasMutex = $false

function Write-ToolLog([string]$Message, [string]$Level = "INFO") {
    $Line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    Write-Output $Line
}

function Invoke-Checked([string]$FilePath, [string[]]$Arguments) {
    Write-ToolLog ("> {0} {1}" -f (Split-Path -Leaf $FilePath), ($Arguments -join " "))
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Output = @(& $FilePath @Arguments 2>&1)
        $Code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
    foreach ($Line in $Output) { Write-ToolLog ([string]$Line) }
    if ($Code -ne 0) { throw "Command failed with exit code ${Code}: $FilePath" }
}

function Ensure-PythonRuntime {
    $script:Python = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $script:Python)) {
        $Bootstrap = (Get-Command python.exe -ErrorAction Stop).Source
        Write-ToolLog "Creating project Python environment."
        Invoke-Checked $Bootstrap @("-m", "venv", (Join-Path $RepoPath ".venv"))
    }
    $Requirements = Join-Path $RepoPath "requirements.txt"
    $Stamp = Join-Path $RepoPath ".venv\requirements.sha256"
    $RequiredHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $InstalledHash = if (Test-Path -LiteralPath $Stamp) { (Get-Content -LiteralPath $Stamp -Raw).Trim() } else { "" }
    if ($RequiredHash -ne $InstalledHash) {
        Write-ToolLog "Installing or updating Python dependencies."
        Invoke-Checked $script:Python @("-m", "pip", "install", "--disable-pip-version-check", "-r", $Requirements)
        Set-Content -LiteralPath $Stamp -Value $RequiredHash -Encoding ASCII
    }
}

function Invoke-MaterialCache {
    Invoke-Checked $script:Python @("scripts/sync_new_request_models.py")
    Invoke-Checked $script:Python @("scripts/generate_page_data_cache.py")
    Invoke-Checked $script:Python @("scripts/generate_request_form_cache.py")
    Invoke-Checked $script:Python @("scripts/preserve_unchanged_cache_files.py", "data/page_data_cache.json", "data/request_form_cache.json")
    Invoke-Checked $script:Python @("scripts/validate_release_consistency.py")
    Invoke-Checked $script:Python @("scripts/validate_page_data_cache.py")
    Invoke-Checked $script:Python @("scripts/validate_request_form_cache.py")
}

function Invoke-ContactCache {
    Invoke-Checked $script:Python @("scripts/generate_contact_departments_cache.py")
    Invoke-Checked $script:Python @("scripts/preserve_unchanged_cache_files.py", "data/contact_departments_cache.json")
}

function Invoke-WarehouseCache {
    Invoke-Checked $script:Python @("scripts/generate_warehouse_location_cache.py")
    Invoke-Checked $script:Python @("scripts/preserve_unchanged_cache_files.py", "data/warehouse_location_cache.json")
    Invoke-Checked $script:Python @("scripts/validate_warehouse_location_cache.py")
}

try {
    Write-ToolLog "Starting manual tool: $Tool"
    Push-Location -LiteralPath $RepoPath
    if ($Tool -in @("MaterialCache", "ContactCache", "WarehouseCache", "AllCaches")) {
        if (-not $MutexAlreadyHeld) {
            $Mutex = [Threading.Mutex]::new($false, "Local\PuduMaterialCacheRefresh")
            $HasMutex = $Mutex.WaitOne(0)
            if (-not $HasMutex) { throw "Another cache refresh is already running." }
        }
    }
    if ($Tool -ne "WakeStreamlit") { Ensure-PythonRuntime }
    if ($Tool -in @("MaterialCache", "ContactCache", "WarehouseCache", "AllCaches", "FeishuSmokeTest") -and -not (Test-Path -LiteralPath $SecretsPath)) {
        throw "Secrets file is missing: $SecretsPath"
    }

    switch ($Tool) {
        "MaterialCache" { Invoke-MaterialCache }
        "ContactCache" { Invoke-ContactCache }
        "WarehouseCache" { Invoke-WarehouseCache }
        "AllCaches" { Invoke-MaterialCache; Invoke-ContactCache; Invoke-WarehouseCache }
        "ValidateCaches" {
            Invoke-Checked $script:Python @("scripts/validate_release_consistency.py")
            Invoke-Checked $script:Python @("scripts/validate_page_data_cache.py")
            Invoke-Checked $script:Python @("scripts/validate_request_form_cache.py")
            Invoke-Checked $script:Python @("scripts/validate_warehouse_location_cache.py")
        }
        "FeishuSmokeTest" { Invoke-Checked $script:Python @("scripts/full_feishu_smoke_test.py") }
        "WakeStreamlit" {
            $Node = "C:\Program Files\nodejs\node.exe"
            if (-not (Test-Path -LiteralPath $Node)) { $Node = (Get-Command node.exe -ErrorAction Stop).Source }
            Invoke-Checked $Node @("scripts/wake_streamlit_app.mjs", "--url", "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/", "--log", "work/streamlit-wake.log", "--profile", "work/streamlit-wake-edge-profile", "--timeout-ms", "150000")
        }
        "SyncAllRuntimes" {
            $SyncCode = "from pathlib import Path; from deployment_launcher.runtime import synchronize_current_runtimes; synchronize_current_runtimes(Path.cwd())"
            Invoke-Checked $script:Python @("-c", $SyncCode)
        }
    }
    if (-not $SkipLivePublication -and $Tool -in @("MaterialCache", "ContactCache", "WarehouseCache", "AllCaches")) {
        $Scope = switch ($Tool) {
            "MaterialCache" { "Material" }
            "ContactCache" { "Contacts" }
            "WarehouseCache" { "Warehouse" }
            "AllCaches" { "All" }
        }
        Write-ToolLog "Publishing validated cache to the running local application."
        Invoke-Checked $script:Python @("scripts/publish_live_cache.py", "--scope", $Scope, "--freshly-generated")
    }
    Write-ToolLog "Manual tool completed successfully: $Tool"
    Copy-Item -LiteralPath $LogPath -Destination (Join-Path $LogDirectory "latest.log") -Force
    exit 0
} catch {
    Write-ToolLog $_.Exception.Message "ERROR"
    Copy-Item -LiteralPath $LogPath -Destination (Join-Path $LogDirectory "latest.log") -Force
    exit 1
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    if ($null -ne $Mutex) { $Mutex.Dispose() }
}
