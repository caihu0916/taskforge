
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""跨会话记忆增强配置 (P3-C)

会话摘要自动生成 + 跨会话检索 + 去重衰减
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """跨会话记忆增强配置 (P3-C)

    会话摘要自动生成 + 跨会话检索 + 去重衰减
    """

    auto_summary: bool = Field(
        default=True,
        description="聊天结束时自动生成会话摘要并存入EPISODIC层 (TF_MEMORY__AUTO_SUMMARY)",
    )
    cross_session_retrieval: bool = Field(
        default=True,
        description="react_loop启动时检索跨会话记忆注入system prompt (TF_MEMORY__CROSS_SESSION_RETRIEVAL)",
    )
    max_injected_rules: int = Field(
        default=5,
        ge=0,
        le=20,
        description="注入system prompt的最大记忆条数 (TF_MEMORY__MAX_INJECTED_RULES)",
    )
    summary_max_length: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="会话摘要最大字符数 (TF_MEMORY__SUMMARY_MAX_LENGTH)",
    )
    dedup_similarity_threshold: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        description="去重相似度阈值(向量余弦), 超过则视为重复 (TF_MEMORY__DEDUP_SIMILARITY_THRESHOLD)",
    )
