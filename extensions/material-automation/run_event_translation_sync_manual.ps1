$ErrorActionPreference = "Stop"
$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$popup = New-Object -ComObject WScript.Shell

try {
    & $pythonPath (Join-Path $RepoPath "event_translation_sync.py") --once
    if ($LASTEXITCODE -ne 0) { throw "Sync exited with code $LASTEXITCODE." }
    $null = $popup.Popup("Global Events English sync completed successfully.", 0, "PUDU Event Sync", 64)
}
catch {
    $null = $popup.Popup("Sync failed. Please check logs/event_translation_sync.log.`n`n$($_.Exception.Message)", 0, "PUDU Event Sync", 16)
    exit 1
}
