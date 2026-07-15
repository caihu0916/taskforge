
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""LLM 路由配置 — 用户自行配置后启用，不硬编码具体Provider"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# 已知的试用/演示 API Key 模式（生产环境禁止使用）
_TRIAL_KEY_PATTERNS = re.compile(r"(?i)(trial|demo|sample|test|example|sk-agnes-trial|sk-ag-)")


class AgnesConfig(BaseModel):
    """Agnes AI 全模态免费 Provider 配置

    覆盖文本(256K上下文)、图像(4K生成)、视频(异步生成)三类能力
    OpenAI 兼容协议，无需信用卡绑定

    环境变量映射:
      TF_LLM__AGNES__ENABLED=true
      TF_LLM__AGNES__API_KEY=sk-agnes-xxx
    """

    enabled: bool = Field(default=False, description="启用 Agnes AI Provider")
    api_key: str = Field(default="", description="Agnes API Key")
    base_url: str = Field(default="https://apihub.agnes-ai.com/v1", description="Agnes API 基础URL")
    text_model: str = Field(default="agnes-2.0-flash", description="文本推理模型: agnes-2.0-flash")
    image_model: str = Field(default="agnes-image-2.0", description="图像生成模型: agnes-image-2.0")
    video_model: str = Field(default="agnes-video", description="视频生成模型: agnes-video")
    timeout: int = Field(default=120, ge=10, le=600, description="请求超时(秒)")

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return v.rstrip("/")

    def is_trial_key(self) -> bool:
        """检测是否使用试用/演示 Key"""
        if not self.api_key:
            return False
        return bool(_TRIAL_KEY_PATTERNS.search(self.api_key))


class LLMConfig(BaseModel):
    """LLM 路由配置 — 用户自行配置后启用，不硬编码具体Provider"""

    provider: str = Field(default="", description="LLM 提供商 (由用户配置，空则未激活)")
    model: str = Field(default="", description="默认模型 (由用户配置)")
    base_url: str = Field(default="", description="API 基础URL (由用户配置)")
    api_key: str = Field(default="", description="API 密钥")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    max_context_tokens: int = Field(default=3500, ge=500, le=32768, description="上下文压缩token预算")
    timeout: int = Field(default=60, ge=5, le=300, description="请求超时(秒)")
    cache_enabled: bool = Field(default=True, description="LLM 缓存开关")
    cache_ttl: int = Field(default=3600, description="缓存TTL(秒)")
    builtin_enabled: bool = Field(default=True, description="启用内置免费Provider(开箱即用)")
    # FreeLLMAPI 降级层
    freellmapi_enabled: bool = Field(default=False, description="启用FreeLLMAPI免费聚合降级层")
    freellmapi_base_url: str = Field(default="", description="FreeLLMAPI代理地址")
    freellmapi_api_key: str = Field(default="", description="FreeLLMAPI统一API Key")
    freellmapi_model: str = Field(default="", description="FreeLLMAPI默认模型")
    # LLMScheduler 并发控制
    max_concurrent: int = Field(default=5, ge=1, le=50, description="LLM最大并发调用数")
    queue_size: int = Field(default=100, ge=10, le=1000, description="LLM调度队列大小")
    token_budget_per_minute: int = Field(default=100_000, ge=1000, le=10_000_000, description="每分钟token预算上限")
    scheduler_enabled: bool = Field(default=False, description="启用LLMScheduler流控(灰度开关)")
    # TokenSaver 省token引擎
    ts_enabled: bool = Field(default=True, description="启用TokenSaver省token引擎")
    ts_prompt_caching: bool = Field(default=True, description="提示前缀缓存(复用系统提示)")
    ts_response_length_optimization: bool = Field(default=True, description="响应长度优化(简单查询降低max_tokens)")
    ts_conversation_trimming: bool = Field(default=True, description="对话历史修剪(保留关键决策点)")
    ts_min_prefix_length: int = Field(default=100, ge=20, le=5000, description="缓存前缀最小字符数")
    ts_max_output_tokens: int = Field(default=4096, ge=256, le=32768, description="复杂查询最大输出token")
    ts_min_output_tokens: int = Field(default=256, ge=64, le=2048, description="简单查询最小输出token")
    ts_preserve_recent_rounds: int = Field(default=10, ge=2, le=50, description="对话修剪保留最近N轮")
    agnes: AgnesConfig = Field(default_factory=AgnesConfig, description="Agnes AI 全模态免费 Provider (文本/图像/视频)")

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def is_trial_key(self) -> bool:
        """检测主 Provider API Key 是否为试用/演示 Key"""
        if not self.api_key:
            return False
        return bool(_TRIAL_KEY_PATTERNS.search(self.api_key))
