from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import main
from .bundle import import_bundle


def cli() -> int:
    parser = argparse.ArgumentParser(description="PUDU Material Operations deployment launcher")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--inspect-bundle", type=Path)
    parser.add_argument("--password", default="")
    args, _unknown = parser.parse_known_args()
    if args.self_test:
        from .models import normalize_hostname
        assert normalize_hostname("HTTPS://PUDU.EXAMPLE.COM/") == "pudu.example.com"
        print(json.dumps({"status": "ok", "component": "deployment_launcher"}))
        return 0
    if args.inspect_bundle:
        print(json.dumps(import_bundle(args.inspect_bundle, args.password).safe_dict(), ensure_ascii=False, indent=2, default=str))
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
