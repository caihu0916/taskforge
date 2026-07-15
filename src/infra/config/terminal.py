
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""终端/代码执行工具配置"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TerminalConfig(BaseModel):
    """终端/代码执行工具配置"""

    shell_backend: Literal["powershell", "bash", "cmd"] = Field(
        default="powershell",
        description="Shell后端: powershell/bash/cmd (TF_TERMINAL__SHELL_BACKEND)",
    )
    command_timeout: int = Field(
        default=120,
        ge=1,
        le=3600,
        description="命令执行超时(秒) (TF_TERMINAL__COMMAND_TIMEOUT)",
    )
    max_output_bytes: int = Field(
        default=50000,
        ge=1000,
        le=10_000_000,
        description="单条命令最大输出字节数 (TF_TERMINAL__MAX_OUTPUT_BYTES)",
    )
    working_dir: str = Field(
        default="",
        description="默认工作目录 (TF_TERMINAL__WORKING_DIR)",
    )
    allowed_commands: str = Field(
        default="",
        description="命令白名单(逗号分隔)，空则全部允许 (TF_TERMINAL__ALLOWED_COMMANDS)",
    )
    blocked_commands: str = Field(
        default="rm -rf /,format,del /f /s",
        description="命令黑名单(逗号分隔) (TF_TERMINAL__BLOCKED_COMMANDS)",
    )

    @field_validator("working_dir")
    @classmethod
    def reject_dotdot(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("working_dir 不允许包含 '..' 路径遍历")
        return v
