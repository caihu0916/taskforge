
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""外部桥接服务凭据 — 百度搜索桥接/视觉API"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BridgeConfig(BaseModel):
    """外部桥接服务凭据 — 百度搜索桥接/视觉API"""

    tools_bridge_url: str = Field(
        default="",
        description="百度搜索桥接URL (TF_BRIDGE__TOOLS_BRIDGE_URL)",
    )
    tools_bridge_token: str = Field(
        default="",
        description="百度搜索桥接Token (TF_BRIDGE__TOOLS_BRIDGE_TOKEN)",
    )
    vision_api_url: str = Field(
        default="",
        description="视觉API URL (TF_BRIDGE__VISION_API_URL)",
    )
    vision_api_key: str = Field(
        default="",
        description="视觉API Key (TF_BRIDGE__VISION_API_KEY)",
    )
    vision_model: str = Field(
        default="vision-standard",
        description="视觉API默认模型 (TF_BRIDGE__VISION_MODEL)",
    )
    memory_root: str = Field(
        default="",
        description="记忆根目录 (TF_BRIDGE__MEMORY_ROOT)，空则自动推导",
    )
    a2a_signing_secret: str = Field(
        default="",
        description="A2A 协议签名密钥 (TF_BRIDGE__A2A_SIGNING_SECRET), 生产必填",
    )
