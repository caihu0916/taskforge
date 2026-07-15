
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent 委托/子Agent调度配置"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field, field_validator

_logger = structlog.get_logger(__name__)


class DelegateConfig(BaseModel):
    """Agent 委托/子Agent调度配置"""

    max_concurrent_children: int = Field(
        default=3,
        ge=1,
        le=20,
        description="最大并发子Agent数 (TF_DELEGATE__MAX_CONCURRENT_CHILDREN)",
    )
    child_timeout_seconds: int = Field(
        default=600,
        ge=60,
        le=86400,
        description="子Agent超时(秒) (TF_DELEGATE__CHILD_TIMEOUT_SECONDS)",
    )
    max_spawn_depth: int = Field(
        default=1,
        ge=1,
        le=5,
        description="最大嵌套深度(1=仅1层子Agent) (TF_DELEGATE__MAX_SPAWN_DEPTH)",
    )
    orchestrator_enabled: bool = Field(
        default=True,
        description="启用Orchestrator编排模式 (TF_DELEGATE__ORCHESTRATOR_ENABLED)",
    )
    inherit_mcp_toolsets: bool = Field(
        default=True,
        description="子Agent继承父Agent的MCP工具集 (TF_DELEGATE__INHERIT_MCP_TOOLSETS)",
    )
    subagent_auto_approve: bool = Field(
        default=False,
        description="自动批准子Agent工具调用(跳过确认) (TF_DELEGATE__SUBAGENT_AUTO_APPROVE)",
    )
    max_iterations: int = Field(
        default=50,
        ge=5,
        le=500,
        description="子Agent最大迭代次数 (TF_DELEGATE__MAX_ITERATIONS)",
    )

    @field_validator("subagent_auto_approve")
    @classmethod
    def warn_auto_approve(cls, v: bool) -> bool:
        if v:
            _logger.warning("delegate.subagent_auto_approve=True: 子Agent工具调用将跳过人工确认")
        return v
