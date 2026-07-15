
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""浏览器工具配置 — Playwright/CDP"""

from __future__ import annotations

from typing import Literal

import structlog
from pydantic import BaseModel, Field, field_validator

_logger = structlog.get_logger(__name__)


class BrowserConfig(BaseModel):
    """浏览器工具配置 — Playwright/CDP"""

    command_timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="浏览器命令超时(秒) (TF_BROWSER__COMMAND_TIMEOUT)",
    )
    cdp_url: str = Field(
        default="",
        description="Chrome DevTools Protocol URL (TF_BROWSER__CDP_URL)",
    )
    headless: bool = Field(
        default=True,
        description="无头模式 (TF_BROWSER__HEADLESS)",
    )
    engine: Literal["auto", "chrome"] = Field(
        default="auto",
        description="浏览器引擎: auto(自动检测)/chrome (TF_BROWSER__ENGINE)",
    )
    allow_private_urls: bool = Field(
        default=False,
        description="允许访问私有URL(内网) (TF_BROWSER__ALLOW_PRIVATE_URLS)",
    )
    auto_local_for_private_urls: bool = Field(
        default=True,
        description="自动将私有URL路由到本地浏览器 (TF_BROWSER__AUTO_LOCAL_FOR_PRIVATE_URLS)",
    )
    inactivity_timeout: int = Field(
        default=300,
        ge=30,
        le=86400,
        description="浏览器无活动超时(秒) (TF_BROWSER__INACTIVITY_TIMEOUT)",
    )
    vision_model: str = Field(
        default="vision-standard",
        description="浏览器视觉截屏模型 (TF_BROWSER__VISION_MODEL)",
    )

    @field_validator("allow_private_urls")
    @classmethod
    def warn_private_urls(cls, v: bool) -> bool:
        if v:
            _logger.warning("browser.allow_private_urls=True: 允许访问内网URL，存在安全风险")
        return v
