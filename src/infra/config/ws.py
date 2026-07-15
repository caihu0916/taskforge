
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""WebSocket 配置"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WSConfig(BaseModel):
    """WebSocket 配置"""

    pubsub_enabled: bool = Field(
        default=True,
        description="是否启用Redis Pub/Sub跨Worker广播 (TF_WS__PUBSUB_ENABLED)",
    )
    pubsub_channel: str = Field(
        default="tf:ws:broadcast",
        description="Redis Pub/Sub channel名 (TF_WS__PUBSUB_CHANNEL)",
    )
