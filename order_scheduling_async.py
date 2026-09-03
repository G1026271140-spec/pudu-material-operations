"""Non-blocking scheduling I/O. Worker threads never touch session state or UI."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="order-scheduling-io")


def submit_write(app, kind, payload, key):
    return EXECUTOR.submit(app.enqueue_feishu_background_write, kind, deepcopy(payload), key)


def submit_poll(app, key):
    return EXECUTOR.submit(lambda: app.find_task_by_idempotency_key(app.feishu_client(), key))


def submit_refresh(app):
    from order_scheduling_service import SchedulingService
    return EXECUTOR.submit(lambda: SchedulingService(app).snapshot(live=True))
