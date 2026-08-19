[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [Parameter(Mandatory = $true)]
    [string]$SecretsPath,

    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,

    [string]$BootstrapPython = "",

    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Mutex = [Threading.Mutex]::new($false, "Local\PuduSubmissionWorkerBootstrap")
$HasMutex = $false
$ExitCode = 0
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
}

try {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $LogPath = Join-Path $LogDirectory "bootstrap.log"
    if (-not (Test-Path -LiteralPath $LogPath)) {
        New-Item -ItemType File -Path $LogPath -Force | Out-Null
    }

    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        Write-RunnerLog "Another submission worker bootstrap is already active; exiting." "WARN"
        exit 0
    }

    $RepoPath = [IO.Path]::GetFullPath($RepoPath)
    $SecretsPath = [IO.Path]::GetFullPath($SecretsPath)
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) {
        throw "Submission worker repository is missing: $RepoPath"
    }
    if (-not (Test-Path -LiteralPath $SecretsPath)) {
        throw "Submission worker secrets are missing: $SecretsPath"
    }

    $git = (Get-Command git -ErrorAction Stop).Source
    $statusOutput = @(& $git -C $RepoPath status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the submission worker repository."
    }
    if ($statusOutput.Count -gt 0) {
        throw "Submission worker repository has local changes and was not updated."
    }

    try {
        Invoke-CheckedCommand $git @("-C", $RepoPath, "fetch", "origin", "master")
        Invoke-CheckedCommand $git @("-C", $RepoPath, "switch", "master")
        Invoke-CheckedCommand $git @("-C", $RepoPath, "pull", "--ff-only", "origin", "master")
    } catch {
        Write-RunnerLog (
            "GitHub update was unavailable; continuing with the existing clean worker copy: {0}" `
                -f $_.Exception.Message
        ) "WARN"
    }

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
        Write-RunnerLog "Creating the dedicated submission worker Python environment."
        Invoke-CheckedCommand $BootstrapPython @("-m", "venv", (Join-Path $RepoPath ".venv"))
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
        Write-RunnerLog "Installing or updating submission worker dependencies."
        Invoke-CheckedCommand $venvPython @(
            "-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath
        )
        Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
    }

    $env:PUDU_SUBMISSION_WORKER_LOG_DIR = $LogDirectory
    $workerScriptPath = Join-Path $RepoPath "scripts\submission_worker.py"
    if (-not (Test-Path -LiteralPath $workerScriptPath)) {
        throw "Submission worker script was not found: $workerScriptPath"
    }
    $workerArguments = @($workerScriptPath)
    if ($SetupOnly) {
        $workerArguments += "--setup"
        Write-RunnerLog "Creating or repairing the Feishu submission queue table."
    } else {
        Write-RunnerLog "Starting the recoverable submission worker."
    }
    Push-Location -LiteralPath $RepoPath
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        do {
            & $venvPython @workerArguments 2>&1 |
                ForEach-Object { Write-RunnerLog ([string]$_) }
            $ExitCode = $LASTEXITCODE
            if ($ExitCode -eq 75 -and -not $SetupOnly) {
                Write-RunnerLog "Worker detected a new repository revision; restarting with the updated code."
                Start-Sleep -Seconds 2
            } elseif ($ExitCode -eq 76 -and -not $SetupOnly) {
                Write-RunnerLog "Another worker still owns the instance lock; waiting to take over."
                Start-Sleep -Seconds 2
            } elseif ($ExitCode -eq 76 -and $SetupOnly) {
                Write-RunnerLog "An active worker already owns the queue; setup verification was skipped."
                $ExitCode = 0
            }
        } while (($ExitCode -eq 75 -or $ExitCode -eq 76) -and -not $SetupOnly)
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    if ($ExitCode -ne 0) {
        throw "Submission worker exited with code $ExitCode."
    }
} catch {
    $ExitCode = 1
    if ($LogPath) {
        Write-RunnerLog $_.Exception.Message "ERROR"
    }
} finally {
    if ($HasMutex) {
        $Mutex.ReleaseMutex()
    }
    $Mutex.Dispose()
}

exit $ExitCode
