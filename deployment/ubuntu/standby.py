"""Fail-closed commissioning endpoint, NOT the business application.

No credential loading, business cache reads, Feishu calls, queue writes or
background reconciliation is performed here. Replace the service entry point
only after live-read mode, enterprise SSO and the single-writer cutover pass.
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
STARTED = time.monotonic()


@api.middleware("http")
async def commissioning_gate(request: Request, call_next):
    if request.method in {"GET", "HEAD"} and request.url.path == "/api/health":
        response = await call_next(request)
    else:
        response = JSONResponse(
            {
                "status": "not_ready",
                "detail": "服务环境已部署，业务功能尚未启用；等待飞书网络、企业登录和实时读取模式验收。",
                "business_enabled": False,
                "worker_enabled": False,
                "business_cache_enabled": False,
                "live_read_verified": False,
            },
            status_code=503,
            headers={"Retry-After": "300"},
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@api.get("/api/health")
@api.head("/api/health")
def health():
    # Liveness only: 200 must never imply that the business system is ready.
    return {
        "status": "ok",
        "mode": "commissioning",
        "business_ready": False,
        "uptime_seconds": round(time.monotonic() - STARTED, 2),
    }
