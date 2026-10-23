$ErrorActionPreference = "Stop"

$repositoryPath = Split-Path -Parent $PSScriptRoot
$manualWakeScript = Join-Path $PSScriptRoot "run_streamlit_wake_manual.cmd"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "PUDU Streamlit Manual Wake.lnk"

if (-not (Test-Path -LiteralPath $manualWakeScript)) {
    throw "Manual wake script was not found: $manualWakeScript"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $manualWakeScript
$shortcut.WorkingDirectory = $repositoryPath
$shortcut.Description = "Manually check and wake the PUDU Streamlit application"
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,208"
$shortcut.Save()

Write-Output $shortcutPath
