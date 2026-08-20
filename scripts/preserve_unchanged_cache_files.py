from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOLATILE_KEYS = {"generated_at", "source", "built_from", "tmp_url", "url"}


def stable_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): stable_value(item)
            for key, item in value.items()
            if str(key) not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [stable_value(item) for item in value]
    return value


def committed_bytes(relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def preserve_if_unchanged(relative_path: str) -> bool:
    target = ROOT / relative_path
    previous = committed_bytes(relative_path)
    if previous is None or not target.is_file():
        return False
    try:
        old_value = json.loads(previous.decode("utf-8-sig"))
        new_value = json.loads(target.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if stable_value(old_value) != stable_value(new_value):
        return False
    target.write_bytes(previous)
    return True


def main(paths: list[str]) -> int:
    for path in paths:
        normalized = Path(path).as_posix()
        if preserve_if_unchanged(normalized):
            print(f"cache_content_unchanged {normalized}")
        else:
            print(f"cache_content_changed {normalized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
