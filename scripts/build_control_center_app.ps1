[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $VenvPython) {
    $Python = $VenvPython
} else {
    $PythonCommand = Get-Command python.exe -ErrorAction Stop
    $Python = $PythonCommand.Source
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the local packaging dependency (PyInstaller)..."
    & $Python -m pip install "pyinstaller>=6.11,<7"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}

$WorkRoot = Join-Path $ProjectRoot "work\pyinstaller-control-center"
$EntryPoint = Join-Path $ProjectRoot "scripts\control_center_entry.py"
$IconPath = Join-Path $ProjectRoot "assets\app-icon.ico"
$AppSource = Join-Path $ProjectRoot "app.py"
$VersionText = (Select-String -LiteralPath $AppSource -Pattern '^APP_VERSION\s*=\s*["'']([^"'']+)' | Select-Object -First 1).Matches.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($VersionText)) { throw "APP_VERSION was not found in app.py." }
$VersionNumbers = @($VersionText.TrimStart("V").Split(".") | ForEach-Object { [int]$_ })
while ($VersionNumbers.Count -lt 4) { $VersionNumbers += 0 }
$VersionTuple = ($VersionNumbers[0..3] -join ", ")
$VersionFile = Join-Path $WorkRoot "control-center-version.txt"
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($VersionTuple), prodvers=($VersionTuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'PUDU'),
      StringStruct('FileDescription', 'PUDU Configuration and Runtime Control Center'),
      StringStruct('FileVersion', '$VersionText'),
      StringStruct('InternalName', 'PUDU-Control-Center'),
      StringStruct('OriginalFilename', 'PUDU-Control-Center.exe'),
      StringStruct('ProductName', 'PUDU Control Center'),
      StringStruct('ProductVersion', '$VersionText')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -LiteralPath $VersionFile -Encoding UTF8
$Arguments = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "PUDU-Control-Center",
    "--distpath", $ProjectRoot,
    "--workpath", (Join-Path $WorkRoot "build"),
    "--specpath", $WorkRoot,
    "--paths", $ProjectRoot,
    "--version-file", $VersionFile
)
if (Test-Path -LiteralPath $IconPath) {
    $Arguments += @("--icon", $IconPath)
}
$Arguments += $EntryPoint

& $Python -m PyInstaller @Arguments
if ($LASTEXITCODE -ne 0) { throw "Control center packaging failed." }

$Output = Join-Path $ProjectRoot "PUDU-Control-Center.exe"
$VersionMarker = Join-Path $ProjectRoot "PUDU-Control-Center.version"
$VersionText | Set-Content -LiteralPath $VersionMarker -Encoding ASCII
Write-Host "Built portable application: $Output"
