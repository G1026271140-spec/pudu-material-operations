"""Called by both desktop cache tools while their cache mutex is held."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_cache import GROUPS, publish_cache


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=[*GROUPS, "All"], required=True)
    parser.add_argument("--freshly-generated", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "config/project_config.json").read_text(encoding="utf-8-sig"))
    web = config["deployment"]["local_web"]
    target = Path(os.path.expandvars(web["runner_root"])) / "repo"
    groups = tuple(GROUPS) if args.scope == "All" else (args.scope,)
    result = publish_cache(ROOT, target, groups, freshly_generated=args.freshly_generated)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    with urlopen(f"http://127.0.0.1:{int(web['port'])}/api/health", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or payload.get("status") != "ok":
            raise RuntimeError("缓存已同步，但正式应用健康检查未通过。")
    print("live_cache_published_and_web_healthy", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
