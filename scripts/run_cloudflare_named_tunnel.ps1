[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CloudflaredPath,
    [Parameter(Mandatory = $true)][string]$TokenFile,
    [Parameter(Mandatory = $true)][string]$LogDirectory,
    [ValidateRange(1, 65535)][int]$Port = 8501
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$logPath = Join-Path $LogDirectory "tunnel.log"
if (-not (Test-Path -LiteralPath $CloudflaredPath)) { throw "cloudflared was not found: $CloudflaredPath" }
if (-not (Test-Path -LiteralPath $TokenFile)) { throw "Cloudflare tunnel token file was not found: $TokenFile" }
$token = (Get-Content -LiteralPath $TokenFile -Raw -Encoding UTF8).Trim()
if (-not $token) { throw "Cloudflare tunnel token is empty." }
Add-Content -LiteralPath $logPath -Value ("{0} [INFO] Starting Cloudflare Named Tunnel." -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -Encoding UTF8
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $CloudflaredPath tunnel --no-autoupdate --url "http://127.0.0.1:$Port" run --token-file $TokenFile 2>&1 |
        ForEach-Object { Add-Content -LiteralPath $logPath -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), [string]$_) -Encoding UTF8 }
    $exitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
exit $exitCode
