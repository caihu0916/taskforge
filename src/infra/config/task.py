
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""任务执行配置"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskConfig(BaseModel):
    """任务执行配置"""

    tool_timeout: int = Field(
        default=60,
        ge=5,
        le=600,
        description="LongRunner每步工具/LLM调用超时(秒) (TF_TASK__TOOL_TIMEOUT)",
    )
    llm_timeout: int = Field(
        default=120,
        ge=10,
        le=1800,
        description="LongRunner每步LLM推理超时(秒) (TF_TASK__LLM_TIMEOUT)",
    )
    max_concurrent: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Dispatcher最大并发执行任务数 (TF_TASK__MAX_CONCURRENT)",
    )
