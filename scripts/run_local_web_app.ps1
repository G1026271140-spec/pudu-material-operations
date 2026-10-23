[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [string]$SecretsPath,

    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,

    [string]$BootstrapPython = "",

    [ValidateRange(1, 65535)]
    [int]$Port = 8501,

    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Mutex = [Threading.Mutex]::new($false, "Local\PuduMaterialWebBootstrap")
$HasMutex = $false
$ExitCode = 0
$LogPath = ""

function Write-RunnerLog {
    param([string]$Message, [ValidateSet("INFO", "WARN", "ERROR")][string]$Level = "INFO")
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
}

function Invoke-CheckedCommand {
    param([string]$FilePath, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $FilePath @Arguments 2>&1)
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    foreach ($line in $output) { Write-RunnerLog ([string]$line) }
    if ($code -ne 0) { throw "Command failed with exit code ${code}: $FilePath" }
}

try {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $LogPath = Join-Path $LogDirectory "web.log"
    if (-not (Test-Path -LiteralPath $LogPath)) { New-Item -ItemType File -Path $LogPath -Force | Out-Null }

    try { $HasMutex = $Mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $HasMutex = $true }
    if (-not $HasMutex) { Write-RunnerLog "Another web bootstrap is active; exiting." "WARN"; exit 0 }

    $RepoPath = [IO.Path]::GetFullPath($RepoPath)
    $SecretsPath = [IO.Path]::GetFullPath($SecretsPath)
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) { throw "Web repository is missing: $RepoPath" }
    if (-not (Test-Path -LiteralPath $SecretsPath)) { throw "Web secrets are missing: $SecretsPath" }

    $git = (Get-Command git -ErrorAction Stop).Source
    $status = @(& $git -C $RepoPath status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the web repository." }
    if ($status.Count -gt 0) { throw "Web repository has local changes and was not updated." }
    try {
        Invoke-CheckedCommand $git @("-C", $RepoPath, "fetch", "origin", "master")
        Invoke-CheckedCommand $git @("-C", $RepoPath, "switch", "master")
        Invoke-CheckedCommand $git @("-C", $RepoPath, "pull", "--ff-only", "origin", "master")
    } catch {
        Write-RunnerLog ("GitHub update unavailable; using existing clean copy: {0}" -f $_.Exception.Message) "WARN"
    }

    $secretsDirectory = Join-Path $RepoPath ".streamlit"
    New-Item -ItemType Directory -Path $secretsDirectory -Force | Out-Null
    Copy-Item -LiteralPath $SecretsPath -Destination (Join-Path $secretsDirectory "secrets.toml") -Force

    $venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (-not $BootstrapPython) { $BootstrapPython = (Get-Command python -ErrorAction Stop).Source }
        if (-not (Test-Path -LiteralPath $BootstrapPython)) { throw "Bootstrap Python was not found: $BootstrapPython" }
        Write-RunnerLog "Creating the dedicated web Python environment."
        Invoke-CheckedCommand $BootstrapPython @("-m", "venv", (Join-Path $RepoPath ".venv"))
    }

    $requirementsPath = Join-Path $RepoPath "requirements.txt"
    $stampPath = Join-Path $RepoPath ".venv\requirements.sha256"
    $requiredHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
    $installedHash = if (Test-Path -LiteralPath $stampPath) { (Get-Content -LiteralPath $stampPath -Raw).Trim() } else { "" }
    if ($requiredHash -ne $installedHash) {
        Write-RunnerLog "Installing or updating web dependencies."
        Invoke-CheckedCommand $venvPython @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath)
        Set-Content -LiteralPath $stampPath -Value $requiredHash -Encoding ASCII
    }

    if ($SetupOnly) { Write-RunnerLog "Web runner setup completed."; exit 0 }
    Write-RunnerLog "Starting PUDU Material Operations API and React frontend on 127.0.0.1:${Port}."
    Push-Location -LiteralPath $RepoPath
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $venvPython -m uvicorn request_web.api:api `
            --host 127.0.0.1 `
            --port $Port 2>&1 | ForEach-Object { Write-RunnerLog ([string]$_) }
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    if ($ExitCode -ne 0) { throw "PUDU Material Operations web app exited with code $ExitCode." }
} catch {
    $ExitCode = 1
    if ($LogPath) { Write-RunnerLog $_.Exception.Message "ERROR" }
} finally {
    if ($HasMutex) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}
exit $ExitCode
