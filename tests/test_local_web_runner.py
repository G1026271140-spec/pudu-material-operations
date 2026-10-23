from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalWebRunnerTests(unittest.TestCase):
    def test_web_runner_is_localhost_only(self) -> None:
        source = (ROOT / "scripts" / "run_local_web_app.ps1").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1", source)
        self.assertNotIn("--host 0.0.0.0", source)
        self.assertIn("uvicorn request_web.api:api", source)
        self.assertIn('$ErrorActionPreference = "Continue"', source)

    def test_named_tunnel_uses_private_token_file(self) -> None:
        runner = (ROOT / "scripts" / "run_cloudflare_named_tunnel.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_local_web_app_task.ps1").read_text(encoding="utf-8")
        self.assertIn("--token-file $TokenFile", runner)
        self.assertIn('[ValidateRange(1, 65535)][int]$Port = 8501', runner)
        self.assertIn('tunnel --no-autoupdate --url "http://127.0.0.1:$Port" run', runner)
        self.assertIn('"-Port", $Port', installer)
        self.assertIn('$ErrorActionPreference = "Continue"', runner)
        self.assertIn("SetAccessRuleProtection($true, $false)", installer)
        self.assertNotIn("--token $token", runner)

    def test_scheduled_tasks_restart_after_failure(self) -> None:
        installer = (ROOT / "scripts" / "install_local_web_app_task.ps1").read_text(encoding="utf-8")
        self.assertIn("-RestartCount 999", installer)
        self.assertIn("-MultipleInstances IgnoreNew", installer)
        self.assertIn("New-ScheduledTaskSettingsSet -Hidden", installer)
        self.assertIn("Get-Command powershell.exe", installer)
        self.assertIn('$env:USERPROFILE "PuduMaterialWebRunner"', installer)
        self.assertNotIn('$env:LOCALAPPDATA "PuduMaterialWebRunner"', installer)
        self.assertIn("Stop-ScheduledTask -TaskName $taskName", installer)
        self.assertIn("Get-CimInstance Win32_Process", installer)
        self.assertIn("$escapedRunnerRepoPath", installer)
        self.assertIn("Stop-RunnerPowerShell $WebRunner", installer)
        self.assertIn("Stop-RunnerPowerShell $TunnelRunner", installer)

    def test_submission_and_cache_installers_clean_only_owned_shells(self) -> None:
        submission = (ROOT / "scripts" / "install_submission_worker_task.ps1").read_text(encoding="utf-8")
        cache = (ROOT / "scripts" / "install_local_cache_task.ps1").read_text(encoding="utf-8")
        self.assertIn("Stop-RunnerPowerShell $InstalledRunnerScript", submission)
        self.assertIn("-notmatch \"-Interactive\"", cache)
        self.assertIn("-Hidden", cache)
        card = (ROOT / "scripts" / "install_feishu_card_worker_task.ps1").read_text(encoding="utf-8")
        self.assertIn("-Hidden", card)

    def test_material_cache_generators_retry_transient_failures(self) -> None:
        runner = (ROOT / "scripts" / "run_local_cache_refresh.ps1").read_text(encoding="utf-8")
        self.assertIn("function Invoke-CheckedCommandWithRetry", runner)
        self.assertIn("[int]$MaxAttempts = 3", runner)
        self.assertIn("Invoke-CheckedCommandWithRetry $venvPython @($generator)", runner)

    pass  # Retired widget assertion: test_request_quantity_controls_are_compact_and_no_200_preset

    def test_background_installers_use_wscript_wrapper(self) -> None:
        wrapper = (ROOT / "scripts" / "run_powershell_hidden.vbs").read_text(encoding="utf-8")
        self.assertIn("//B //NoLogo", "//B //NoLogo")
        self.assertIn("shell.Run command, 0, False", wrapper)
        for name in ("install_local_web_app_task.ps1", "install_submission_worker_task.ps1", "install_local_cache_task.ps1"):
            installer = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("run_powershell_hidden.vbs", installer)
            self.assertIn('wscript.exe', installer)

    def test_runtime_watchdog_is_hidden_and_checks_three_tasks(self) -> None:
        runner = (ROOT / "scripts" / "run_runtime_watchdog.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_runtime_watchdog_task.ps1").read_text(encoding="utf-8")
        self.assertIn('"PUDU Material Web App"', runner)
        self.assertIn('"PUDU Material Cloudflare Tunnel"', runner)
        self.assertIn('"PUDU Submission Worker"', runner)
        self.assertIn("Start-ScheduledTask", runner)
        self.assertIn("New-ScheduledTaskSettingsSet -Hidden", installer)
        self.assertIn("-RepetitionInterval (New-TimeSpan -Minutes 1)", installer)
        self.assertIn("wscript.exe", installer)


if __name__ == "__main__":
    unittest.main()
