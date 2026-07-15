
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""安全模块配置 — Bash安全扫描 + 通用安全"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BashSecurityConfig(BaseModel):
    """Bash 安全扫描配置 — P0: TeleAgent check_bash.py 移植"""

    enabled: bool = Field(default=True, description="启用 Bash 安全扫描 (TF_SECURITY__BASH__ENABLED)")
    # AGENT-004: 默认 strict（最严格），secure-by-default；需要开发便利时显式配置 developer
    trust_profile: Literal["strict", "developer", "enterprise"] = Field(
        default="strict",
        description="信任等级: strict=最严(默认), developer=允许常见开发, enterprise=受控管理 (TF_SECURITY__BASH__TRUST_PROFILE)",
    )
    sandbox_mode: Literal["persistent_host", "ephemeral_sandbox"] = Field(
        default="persistent_host",
        description="环境模式: persistent_host=宿主机(拦截高危), ephemeral_sandbox=沙箱(降级部分为审查) (TF_SECURITY__BASH__SANDBOX_MODE)",
    )
    max_command_bytes: int = Field(
        default=512 * 1024,
        ge=1024,
        le=10 * 1024 * 1024,
        description="单命令最大字节数 (TF_SECURITY__BASH__MAX_COMMAND_BYTES)",
    )
    tree_sitter_enabled: bool = Field(
        default=True, description="启用 tree-sitter AST 解析 (TF_SECURITY__BASH__TREE_SITTER_ENABLED)"
    )
    session_event_limit: int = Field(
        default=64, ge=16, le=256, description="会话事件环上限 (TF_SECURITY__BASH__SESSION_EVENT_LIMIT)"
    )


class SecurityConfig(BaseModel):
    """安全模块配置"""

    bash: BashSecurityConfig = Field(default_factory=BashSecurityConfig)
