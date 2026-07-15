
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""代码执行沙箱配置 — 本地/远程模式"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CodeExecutionConfig(BaseModel):
    """代码执行沙箱配置 — 本地/远程模式"""

    timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="代码执行超时(秒) (TF_CODE_EXECUTION__TIMEOUT)",
    )
    max_tool_calls: int = Field(
        default=50,
        ge=1,
        description="单次执行最大工具调用次数 (TF_CODE_EXECUTION__MAX_TOOL_CALLS)",
    )
    mode: Literal["local", "remote"] = Field(
        default="local",
        description="执行模式: local(本地子进程)/remote(远程沙箱) (TF_CODE_EXECUTION__MODE)",
    )
    sandbox_url: str = Field(
        default="ws://127.0.0.1:18765",
        description="远程沙箱WebSocket地址 (TF_CODE_EXECUTION__SANDBOX_URL)",
    )
