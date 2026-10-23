from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import submission_queue  # noqa: E402
from scripts import submission_worker  # noqa: E402


def queue_task_types() -> set[str]:
    return {
        value
        for name, value in vars(submission_queue).items()
        if name.startswith("QUEUE_TASK_TYPE_") and isinstance(value, str)
    }


def validate_release_consistency() -> dict[str, int | str]:
    if (
        submission_queue.SUBMISSION_QUEUE_MODULE_VERSION
        != app.REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION
    ):
        raise ValueError(
            "app.py 与 submission_queue.py 模块版本不匹配："
            f"required={app.REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION}, "
            f"actual={submission_queue.SUBMISSION_QUEUE_MODULE_VERSION}"
        )
    missing_worker_tasks = sorted(
        queue_task_types() - submission_worker.SUPPORTED_QUEUE_TASK_TYPES
    )
    if missing_worker_tasks:
        raise ValueError(
            "Submission Worker 未覆盖队列任务类型：" + ", ".join(missing_worker_tasks)
        )
    unexpected_worker_tasks = sorted(
        submission_worker.SUPPORTED_QUEUE_TASK_TYPES - queue_task_types()
    )
    if unexpected_worker_tasks:
        raise ValueError(
            "Submission Worker 声明了队列中不存在的任务类型："
            + ", ".join(unexpected_worker_tasks)
        )
    if submission_worker.inventory_app.APP_VERSION != app.APP_VERSION:
        raise ValueError("Submission Worker 与应用版本不一致。")
    return {
        "app_version": app.APP_VERSION,
        "queue_module_version": submission_queue.SUBMISSION_QUEUE_MODULE_VERSION,
        "queue_task_types": len(queue_task_types()),
    }


def main() -> int:
    try:
        stats = validate_release_consistency()
    except (ImportError, TypeError, ValueError) as exc:
        print(f"release_consistency_invalid: {exc}", file=sys.stderr)
        return 1
    print(
        "release_consistency_valid",
        f"app_version={stats['app_version']}",
        f"queue_module_version={stats['queue_module_version']}",
        f"queue_task_types={stats['queue_task_types']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
