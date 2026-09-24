[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PackagedApp = Join-Path $ProjectRoot "PUDU Material Operations Setup.exe"
$Marker = Join-Path $ProjectRoot "PUDU Material Operations Setup.version"
$SourceVersion = (Select-String -LiteralPath (Join-Path $ProjectRoot "app.py") -Pattern '^APP_VERSION\s*=\s*["'']([^"'']+)' | Select-Object -First 1).Matches.Groups[1].Value

if ((Test-Path -LiteralPath $PackagedApp) -and (Test-Path -LiteralPath $Marker)) {
    $MarkerVersion = (Get-Content -LiteralPath $Marker -Raw).Trim()
    $ExeVersion = (Get-Item -LiteralPath $PackagedApp).VersionInfo.ProductVersion
    if ($MarkerVersion -eq $SourceVersion -and $ExeVersion -eq $SourceVersion) {
        Start-Process -FilePath $PackagedApp -WorkingDirectory $ProjectRoot -Verb RunAs
        return
    }
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command pythonw.exe -ErrorAction Stop).Source }
Start-Process -FilePath $Python -ArgumentList @("-m", "deployment_launcher") -WorkingDirectory $ProjectRoot -Verb RunAs
