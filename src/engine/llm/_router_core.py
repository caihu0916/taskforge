
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-17: LLMRouter 双模式桩版本 — 开源版 LLM 路由器

数据链路: LLMRouter → _detect_mode → OllamaProvider(local) / remote_stubs(remote)

桩版本设计 (无闭源依赖):
  - 双模式: local (Ollama 免费) > remote (SaaS API Key) > unavailable
  - 保持真实签名所有参数 (profile/provider/model/user_id) — 上层调用零感知
  - 不动 provider_bootstrap.py / router.py — 开源版直接 import LLMRouter

回滚: 主项目原 _router_core.py 保留为闭源版 (含 ProviderRegistry/fallback/cache)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)

# unavailable 模式的注册引导文案
_UNAVAILABLE_GUIDE = (
    "无可用 LLM: 请安装 Ollama (本地免费) 或配置 API Key (远程 SaaS)。"
    "Ollama: https://ollama.com/download | API Key: https://taskforge.cn/register"
)

# 与主项目 _router_core.py 一致的默认值
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096


class LLMRouter:
    """LLM 路由器桩版本 — 双模式分发 (local/remote/unavailable)

    模式优先级:
      1. local — Ollama 可用时优先 (免费、隐私)
      2. remote — 有 API Key 时使用 SaaS (付费、强大)
      3. unavailable — 两者均不可用时抛 RuntimeError 含注册引导
    """

    def __init__(self, registry: Any = None) -> None:
        # ponytail: registry 参数保持签名兼容, 桩版本忽略 (无 ProviderRegistry)
        self._registry = registry
        self._ollama_provider: Any = None

    @property
    def registry(self) -> Any:
        return self._registry

    def set_tracker(self, tracker: object) -> None:
        """保持签名兼容 — 桩版本无 UsageTracker"""
        self._tracker = tracker

    def set_token_saver(self, token_saver: object) -> None:
        """保持签名兼容 — 桩版本无 TokenSaver"""
        self._token_saver = token_saver

    async def close_all(self) -> None:
        """关闭所有 Provider 连接 — 桩版本无共享连接, 空操作"""

    # ------------------------------------------------------------------
    # _detect_mode — 双模式检测核心
    # ------------------------------------------------------------------

    async def _detect_mode(self) -> str:
        """检测可用 LLM 模式

        Returns:
            "local" — Ollama 可用 (免费优先)
            "remote" — 有 API Key (SaaS 付费)
            "unavailable" — 两者均不可用
        """
        # 1. 优先检测 local (Ollama 免费)
        try:
            from src.engine.llm._local_provider import OllamaProvider

            if self._ollama_provider is None:
                self._ollama_provider = OllamaProvider()
            if await self._ollama_provider.is_available():
                return "local"
        except Exception as e:
            logger.warning("llm_detect_local_failed", error=str(e), exc_info=True)

        # 2. 其次检测 remote (API Key)
        try:
            from src.infra.secure_storage import get_api_key

            if get_api_key():
                return "remote"
        except Exception as e:
            logger.warning("llm_detect_remote_failed", error=str(e), exc_info=True)

        # 3. 两者均不可用
        return "unavailable"

    # ------------------------------------------------------------------
    # chat — 同步对话 (保持真实签名)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "fast",
        provider: str = "",
        model: str = "",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        user_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """同步对话 — 双模式分发

        Args:
            messages: OpenAI 格式消息列表
            profile: 路由 profile (fast/deep/coding/local) — 桩版本忽略, 保持兼容
            provider: 指定 Provider — 桩版本忽略, 保持兼容
            model: 模型名
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            user_id: 用户 ID — 桩版本忽略, 保持兼容
            **kwargs: 透传额外参数
        """
        mode = await self._detect_mode()

        if mode == "local":
            if self._ollama_provider is None:
                from src.engine.llm._local_provider import OllamaProvider

                self._ollama_provider = OllamaProvider()
            return await self._ollama_provider.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        if mode == "remote":
            from src.infra.remote_stubs import remote_llm_chat

            return await remote_llm_chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        # unavailable
        raise RuntimeError(_UNAVAILABLE_GUIDE)

    # ------------------------------------------------------------------
    # stream_chat — 流式对话 (保持真实签名)
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "fast",
        provider: str = "",
        model: str = "",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        user_id: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式对话 — 双模式分发

        Yields:
            每次产出的文本片段
        """
        mode = await self._detect_mode()

        if mode == "local":
            if self._ollama_provider is None:
                from src.engine.llm._local_provider import OllamaProvider

                self._ollama_provider = OllamaProvider()
            async for chunk in self._ollama_provider.stream_chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk
            return

        if mode == "remote":
            from src.infra.remote_stubs import remote_llm_stream

            async for chunk in remote_llm_stream(
                messages,
                model=model,
                **kwargs,
            ):
                yield chunk
            return

        # unavailable
        raise RuntimeError(_UNAVAILABLE_GUIDE)
