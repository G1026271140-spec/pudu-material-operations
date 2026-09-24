from __future__ import annotations

import re
from pathlib import Path


def next_patch_version(version: str) -> str:
    match = re.fullmatch(r"V(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"无法识别版本号：{version}")
    major, minor, patch = (int(part) for part in match.groups())
    if patch >= 9:
        patch = 0
        minor += 1
    else:
        patch += 1
    if minor >= 10:
        minor = 0
        major += 1
    return f"V{major}.{minor}.{patch}"


def bump_release_version_files(root: Path) -> tuple[str, str]:
    app_path = root / "app.py"
    admin_test_path = root / "tests" / "test_admin_access.py"
    app_text = app_path.read_text(encoding="utf-8-sig")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', app_text, re.MULTILINE)
    if not match:
        raise RuntimeError("app.py 中未找到 APP_VERSION。")
    current_version = match.group(1)
    new_version = next_patch_version(current_version)
    app_text = app_text[: match.start()] + f'APP_VERSION = "{new_version}"' + app_text[match.end() :]
    admin_test = admin_test_path.read_text(encoding="utf-8-sig")
    old_assertion = f'self.assertEqual(app.APP_VERSION, "{current_version}")'
    if old_assertion not in admin_test:
        raise RuntimeError("版本测试未包含当前 APP_VERSION，已停止自动递增。")
    app_path.write_text(app_text, encoding="utf-8", newline="")
    admin_test_path.write_text(
        admin_test.replace(old_assertion, f'self.assertEqual(app.APP_VERSION, "{new_version}")', 1),
        encoding="utf-8",
        newline="",
    )
    return current_version, new_version
