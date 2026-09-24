[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python.exe -ErrorAction Stop).Source }

& $Python -c "import PyInstaller, cryptography" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install "pyinstaller>=6.11,<7" "cryptography>=43,<47"
    if ($LASTEXITCODE -ne 0) { throw "Launcher packaging dependencies could not be installed." }
}

$WorkRoot = Join-Path $ProjectRoot "work\pyinstaller-deployment-launcher"
$PayloadStage = Join-Path $WorkRoot "payload-stage"
$PayloadRoot = Join-Path $WorkRoot "payload"
$PayloadZip = Join-Path $PayloadRoot "project.zip"
Remove-Item -LiteralPath $PayloadStage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PayloadRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PayloadStage, $PayloadRoot | Out-Null

$TrackedFiles = @(& git -c core.quotepath=false -C $ProjectRoot ls-files)
$NewLauncherFiles = @(& git -c core.quotepath=false -C $ProjectRoot ls-files --others --exclude-standard -- deployment_launcher scripts/deployment_launcher_entry.py scripts/build_deployment_launcher.ps1 scripts/run_deployment_launcher.ps1 scripts/install_deployment_launcher_shortcut.ps1 docs/deployment_launcher.md)
$Files = @($TrackedFiles + $NewLauncherFiles | Sort-Object -Unique | Where-Object {
    $_ -notmatch '^(Marketing materials Control\.(exe|version)|PUDU Material Operations Setup\.(exe|version)|control_center/|docs/control_center\.md|design-qa\.md)'
})
foreach ($Relative in $Files) {
    $Source = Join-Path $ProjectRoot $Relative
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { continue }
    $Destination = Join-Path $PayloadStage $Relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}
Compress-Archive -Path (Join-Path $PayloadStage "*") -DestinationPath $PayloadZip -CompressionLevel Optimal
Remove-Item -LiteralPath $PayloadStage -Recurse -Force

$VersionText = (Select-String -LiteralPath (Join-Path $ProjectRoot "app.py") -Pattern '^APP_VERSION\s*=\s*["'']([^"'']+)' | Select-Object -First 1).Matches.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($VersionText)) { throw "APP_VERSION was not found in app.py." }
$VersionNumbers = @($VersionText.TrimStart("V").Split(".") | ForEach-Object { [int]$_ })
while ($VersionNumbers.Count -lt 4) { $VersionNumbers += 0 }
$VersionTuple = ($VersionNumbers[0..3] -join ", ")
$VersionFile = Join-Path $WorkRoot "deployment-launcher-version.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($VersionTuple), prodvers=($VersionTuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'PUDU'),
      StringStruct('FileDescription', 'PUDU Material Operations Deployment Launcher'),
      StringStruct('FileVersion', '$VersionText'),
      StringStruct('InternalName', 'PUDU Material Operations Setup'),
      StringStruct('OriginalFilename', 'PUDU Material Operations Setup.exe'),
      StringStruct('ProductName', 'PUDU Material Operations Setup'),
      StringStruct('ProductVersion', '$VersionText')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -LiteralPath $VersionFile -Encoding UTF8

$Arguments = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "PUDU Material Operations Setup",
    "--distpath", $ProjectRoot,
    "--workpath", (Join-Path $WorkRoot "build"),
    "--specpath", $WorkRoot,
    "--paths", $ProjectRoot,
    "--version-file", $VersionFile,
    "--add-data", ("{0};payload" -f $PayloadZip)
)
$IconPath = Join-Path $ProjectRoot "assets\app-icon.ico"
if (Test-Path -LiteralPath $IconPath) { $Arguments += @("--icon", $IconPath) }
$Arguments += (Join-Path $ProjectRoot "scripts\deployment_launcher_entry.py")
& $Python -m PyInstaller @Arguments
if ($LASTEXITCODE -ne 0) { throw "Deployment launcher packaging failed." }

$VersionText | Set-Content -LiteralPath (Join-Path $ProjectRoot "PUDU Material Operations Setup.version") -Encoding ASCII
Write-Host "Built: $(Join-Path $ProjectRoot 'PUDU Material Operations Setup.exe')" -ForegroundColor Green
