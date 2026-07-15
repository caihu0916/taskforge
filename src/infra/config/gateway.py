
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""后台网关进程配置 — 进程管理/健康检查"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class GatewayConfig(BaseModel):
    """后台网关进程配置 — 进程管理/健康检查"""

    daemon_mode: bool = Field(
        default=False,
        description="以守护进程模式运行 (TF_GATEWAY__DAEMON_MODE)",
    )
    pid_file: str = Field(
        default="data/gateway.pid",
        description="PID文件路径 (TF_GATEWAY__PID_FILE)",
    )
    auto_start: bool = Field(
        default=False,
        description="开机自动启动 (TF_GATEWAY__AUTO_START)",
    )
    health_check_interval: int = Field(
        default=30,
        ge=1,
        description="健康检查间隔(秒) (TF_GATEWAY__HEALTH_CHECK_INTERVAL)",
    )

    @field_validator("pid_file")
    @classmethod
    def pid_file_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("gateway.pid_file 不能为空")
        return v
