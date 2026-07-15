
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""API密钥凭证池配置 — 多Key轮转/故障转移"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CredentialPoolConfig(BaseModel):
    """API密钥凭证池配置 — 多Key轮转/故障转移"""

    default_strategy: Literal["round_robin", "least_used", "random", "fill_first"] = Field(
        default="round_robin",
        description="默认Key选取策略 (TF_CREDENTIAL_POOL__DEFAULT_STRATEGY)",
    )
    per_provider_strategy: dict[str, str] = Field(
        default_factory=dict,
        description='按Provider指定策略，如 {"openai": "fill_first"} (TF_CREDENTIAL_POOL__PER_PROVIDER_STRATEGY)',
    )
    exhausted_ttl_seconds: int = Field(
        default=300,
        ge=1,
        description="Key耗尽后冷却时间(秒) (TF_CREDENTIAL_POOL__EXHAUSTED_TTL_SECONDS)",
    )
    exhausted_ttl_minutes: int = Field(
        default=30,
        ge=1,
        description="Key耗尽后长冷却时间(分钟) (TF_CREDENTIAL_POOL__EXHAUSTED_TTL_MINUTES)",
    )
    health_check_interval: int = Field(
        default=60,
        ge=1,
        description="Key健康检查间隔(秒) (TF_CREDENTIAL_POOL__HEALTH_CHECK_INTERVAL)",
    )
    custom_providers: str = Field(
        default="",
        description="自定义Provider密钥(JSON字符串，逗号分隔provider_id) (TF_CREDENTIAL_POOL__CUSTOM_PROVIDERS)",
    )
