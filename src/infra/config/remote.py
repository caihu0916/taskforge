
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-09: 远程 API 桩函数配置 — 开源版连接 SaaS 服务端

环境变量:
  TF_REMOTE__BASE_URL  — SaaS 服务端 base URL (默认 https://api.taskforge.cn)
  TF_REMOTE__TIMEOUT   — HTTP 请求超时秒数 (默认 30)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RemoteConfig(BaseModel):
    """远程 API 配置 — 开源版桩函数调用 SaaS 服务端时复用"""

    base_url: str = Field(
        default="https://api.taskforge.cn",
        description="SaaS 服务端 base URL (TF_REMOTE__BASE_URL)",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="HTTP 请求超时(秒) (TF_REMOTE__TIMEOUT)",
    )
