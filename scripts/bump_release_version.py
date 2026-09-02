from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from control_center.release import bump_release_version_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Increment the application version with base-10 carry and update its exact version test.")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    current_version, new_version = bump_release_version_files(args.root.resolve())
    print(json.dumps({"current_version": current_version, "new_version": new_version}, ensure_ascii=False))


if __name__ == "__main__":
    main()
