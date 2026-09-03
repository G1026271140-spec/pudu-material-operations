from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalWebRunnerTests(unittest.TestCase):
    def test_web_runner_is_localhost_only(self) -> None:
        source = (ROOT / "scripts" / "run_local_web_app.ps1").read_text(encoding="utf-8")
        self.assertIn("--server.address=127.0.0.1", source)
        self.assertNotIn("--server.address=0.0.0.0", source)
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


if __name__ == "__main__":
    unittest.main()
