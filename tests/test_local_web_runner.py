from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalWebRunnerTests(unittest.TestCase):
    def test_web_runner_is_localhost_only(self) -> None:
        source = (ROOT / "scripts" / "run_local_web_app.ps1").read_text(encoding="utf-8")
        self.assertIn("--server.address=127.0.0.1", source)
        self.assertNotIn("--server.address=0.0.0.0", source)

    def test_named_tunnel_uses_private_token_file(self) -> None:
        runner = (ROOT / "scripts" / "run_cloudflare_named_tunnel.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install_local_web_app_task.ps1").read_text(encoding="utf-8")
        self.assertIn("--token-file $TokenFile", runner)
        self.assertIn("SetAccessRuleProtection($true, $false)", installer)
        self.assertNotIn("--token $token", runner)

    def test_scheduled_tasks_restart_after_failure(self) -> None:
        installer = (ROOT / "scripts" / "install_local_web_app_task.ps1").read_text(encoding="utf-8")
        self.assertIn("-RestartCount 999", installer)
        self.assertIn("-MultipleInstances IgnoreNew", installer)


if __name__ == "__main__":
    unittest.main()
