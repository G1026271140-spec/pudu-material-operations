param(
    [int]$PreferredPort = 8501
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    $PythonCommand = Get-Command python -ErrorAction Stop
    $PythonPath = $PythonCommand.Source
}

function Test-PortInUse {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $connection
}

$Port = $PreferredPort
while (Test-PortInUse -Port $Port) {
    $Port += 1
}

$LocalUrl = "http://localhost:$Port"
$NetworkIps = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.AddressState -eq "Preferred"
    } |
    Select-Object -ExpandProperty IPAddress -First 3

Write-Host ""
Write-Host "React + FastAPI will run on the first available port." -ForegroundColor Green
Write-Host "Local URL:   $LocalUrl" -ForegroundColor Cyan
foreach ($Ip in $NetworkIps) {
    Write-Host "Network URL: http://$Ip`:$Port" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Application page: $LocalUrl/" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop the app." -ForegroundColor DarkGray
Write-Host ""

Set-Location -LiteralPath $ProjectRoot
& $PythonPath -m uvicorn request_web.api:api --host 0.0.0.0 --port $Port
