[CmdletBinding()]
param(
    [string]$SourceRepoPath = "",
    [string]$RunnerRoot = (Join-Path $env:USERPROFILE "PuduMaterialWebRunner"),
    [string]$RepositoryUrl = "https://github.com/G1026271140-spec/pudu-material-inventory.git",
    [string]$Branch = "master",
    [string]$WebTaskName = "PUDU Material Web App",
    [string]$TunnelTaskName = "PUDU Material Cloudflare Tunnel",
    [string]$TunnelToken = "",
    [ValidateRange(1, 65535)][int]$Port = 8501,
    [switch]$SkipTunnel
)

$ErrorActionPreference = "Stop"
if (-not $SourceRepoPath) { $SourceRepoPath = Split-Path -Parent $PSScriptRoot }
$SourceRepoPath = [IO.Path]::GetFullPath($SourceRepoPath)
$RunnerRoot = [IO.Path]::GetFullPath($RunnerRoot)
$RunnerRepoPath = Join-Path $RunnerRoot "repo"
$RunnerSecretsPath = Join-Path $RunnerRoot "secrets.toml"
$TokenFile = Join-Path $RunnerRoot "cloudflare-token.txt"
$LogDirectory = Join-Path $RunnerRoot "logs"
$SourceSecretsPath = Join-Path $SourceRepoPath ".streamlit\secrets.toml"
$WebRunner = Join-Path $RunnerRoot "run_local_web_app.ps1"
$TunnelRunner = Join-Path $RunnerRoot "run_cloudflare_named_tunnel.ps1"
$HiddenWrapper = Join-Path $SourceRepoPath "scripts\run_powershell_hidden.vbs"

foreach ($path in @($SourceSecretsPath, (Join-Path $SourceRepoPath "scripts\run_local_web_app.ps1"), (Join-Path $SourceRepoPath "scripts\run_cloudflare_named_tunnel.ps1"))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required installation file is missing: $path" }
}
if (-not (Test-Path -LiteralPath $HiddenWrapper)) { throw "Hidden PowerShell wrapper is missing: $HiddenWrapper" }
if (-not $TunnelToken -and (Test-Path -LiteralPath $SourceSecretsPath)) {
    $tokenLine = Get-Content -LiteralPath $SourceSecretsPath -Encoding UTF8 |
        Where-Object { $_ -match '^\s*CLOUDFLARE_TUNNEL_TOKEN\s*=' } |
        Select-Object -First 1
    if ($tokenLine -match '^\s*CLOUDFLARE_TUNNEL_TOKEN\s*=\s*"(?<token>(?:[^"\\]|\\.)*)"\s*$') {
        $TunnelToken = [regex]::Unescape($Matches.token)
    }
}
New-Item -ItemType Directory -Path $RunnerRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Copy-Item -LiteralPath $SourceSecretsPath -Destination $RunnerSecretsPath -Force
Copy-Item -LiteralPath (Join-Path $SourceRepoPath "scripts\run_local_web_app.ps1") -Destination $WebRunner -Force
Copy-Item -LiteralPath (Join-Path $SourceRepoPath "scripts\run_cloudflare_named_tunnel.ps1") -Destination $TunnelRunner -Force

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
function Protect-PrivateFile([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow))
    Set-Acl -LiteralPath $Path -AclObject $acl
}
Protect-PrivateFile $RunnerSecretsPath
if ($TunnelToken) {
    Set-Content -LiteralPath $TokenFile -Value $TunnelToken.Trim() -Encoding ASCII -NoNewline
    Protect-PrivateFile $TokenFile
}

$git = (Get-Command git -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $RunnerRepoPath ".git"))) {
    if (Test-Path -LiteralPath $RunnerRepoPath) { throw "Runner repository path exists but is not a Git repository: $RunnerRepoPath" }
    & $git clone --branch $Branch --single-branch $RepositoryUrl $RunnerRepoPath
    if ($LASTEXITCODE -ne 0) { throw "Unable to clone the web repository." }
}
$bootstrapPython = Join-Path $SourceRepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $bootstrapPython)) { $bootstrapPython = (Get-Command python -ErrorAction Stop).Source }
& $WebRunner -RepoPath $RunnerRepoPath -SecretsPath $RunnerSecretsPath -LogDirectory $LogDirectory -BootstrapPython $bootstrapPython -Port $Port -SetupOnly
if ($LASTEXITCODE -ne 0) { throw "Web setup failed. Check $LogDirectory\web.log" }

$powershellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
foreach ($taskName in @($TunnelTaskName, $WebTaskName)) {
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName $taskName
        do {
            Start-Sleep -Milliseconds 250
            $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        } while ($null -ne $existingTask -and $existingTask.State -eq "Running")
    }
}
function Stop-RunnerPowerShell([string]$RunnerScript) {
    $escapedScript = [Regex]::Escape([IO.Path]::GetFullPath($RunnerScript))
    $staleShells = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match $escapedScript }
    foreach ($process in $staleShells) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Stop-RunnerPowerShell $WebRunner
Stop-RunnerPowerShell $TunnelRunner
$escapedRunnerRepoPath = [Regex]::Escape($RunnerRepoPath)
$orphanedWebProcesses = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match $escapedRunnerRepoPath -and
        $_.CommandLine -match "streamlit\s+run\s+app\.py"
    }
foreach ($process in $orphanedWebProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
$webArgs = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ('"{0}"' -f $WebRunner), "-RepoPath", ('"{0}"' -f $RunnerRepoPath), "-SecretsPath", ('"{0}"' -f $RunnerSecretsPath), "-LogDirectory", ('"{0}"' -f $LogDirectory), "-BootstrapPython", ('"{0}"' -f $bootstrapPython), "-Port", $Port) -join " "
$webAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('//B //NoLogo "{0}" "{1}" {2}' -f $HiddenWrapper, $WebRunner, $webArgs) -WorkingDirectory $RunnerRoot
Register-ScheduledTask -TaskName $WebTaskName -InputObject (New-ScheduledTask -Action $webAction -Trigger $trigger -Settings $settings -Principal $principal -Description "Runs the PUDU material Streamlit app on localhost only.") -Force | Out-Null
Start-ScheduledTask -TaskName $WebTaskName

if (-not $SkipTunnel) {
    if (-not (Test-Path -LiteralPath $TokenFile)) { throw "Named Tunnel token is required. Re-run with -TunnelToken or use -SkipTunnel." }
    $cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cloudflared) { $cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe" }
    if (-not (Test-Path -LiteralPath $cloudflared)) { throw "cloudflared is not installed." }
    $tunnelArgs = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ('"{0}"' -f $TunnelRunner), "-CloudflaredPath", ('"{0}"' -f $cloudflared), "-TokenFile", ('"{0}"' -f $TokenFile), "-LogDirectory", ('"{0}"' -f $LogDirectory), "-Port", $Port) -join " "
    $tunnelAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('//B //NoLogo "{0}" "{1}" {2}' -f $HiddenWrapper, $TunnelRunner, $tunnelArgs) -WorkingDirectory $RunnerRoot
    Register-ScheduledTask -TaskName $TunnelTaskName -InputObject (New-ScheduledTask -Action $tunnelAction -Trigger $trigger -Settings $settings -Principal $principal -Description "Connects the local PUDU web app through Cloudflare Named Tunnel.") -Force | Out-Null
    Start-ScheduledTask -TaskName $TunnelTaskName
}

Write-Host "Installed local web task: $WebTaskName" -ForegroundColor Green
if (-not $SkipTunnel) { Write-Host "Installed Named Tunnel task: $TunnelTaskName" -ForegroundColor Green }
Write-Host "Local health URL: http://127.0.0.1:${Port}/_stcore/health"
Write-Host "Logs: $LogDirectory"
