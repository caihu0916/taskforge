
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-18: 开源版应用工厂 — 最小化 FastAPI 实例创建入口

数据链路: create_app → FastAPI → /health → 200 OK

ponytail: 主项目 app_factory.py 含完整路由注册/启动钩子/中间件 (~200行),
开源版仅保留 /health + CORS, 后续按需扩展路由。
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例 — 开源版最小化启动

    Returns:
        配置好 CORS + /health 的 FastAPI 实例
    """
    app = FastAPI(
        title="TaskForge Open Source",
        description="AI Agent OS for Solo Entrepreneurs (Open Source Edition)",
        version="1.0.0",
    )

    # CORS — 前端跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /health — 健康检查端点
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    logger.info("app_factory_created", edition="open_source")
    return app
