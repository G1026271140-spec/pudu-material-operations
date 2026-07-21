import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    result = app.maintain_inventory_status()
    print(
        "inventory_status_maintenance_completed",
        json.dumps(result, ensure_ascii=False, default=str),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
