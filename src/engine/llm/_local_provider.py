
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-16: OllamaProvider — 开源版本地 LLM Provider

数据链路: OllamaProvider → httpx.AsyncClient → localhost:11434 → Ollama API

自包含设计 (无闭源依赖):
  - httpx.AsyncClient per-request (不依赖共享 http_client)
  - RuntimeError 替代 LLMError (ponytail: P0-17 桩版本捕获 RuntimeError 即可)
  - is_available() 用于 graceful 降级检测

实现 LLMProvider Protocol (src/engine/llm/protocol.py):
  - name 属性
  - chat() / stream_chat() / list_models() / count_tokens()
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)

# Ollama 默认地址 — 用户未配置时的回退值
_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider:
    """Ollama 本地 LLM Provider (开源版自包含实现)

    基于 httpx 异步调用, 支持:
      - 同步对话 (chat)
      - NDJSON 流式输出 (stream_chat)
      - 模型列表 (list_models)
      - Token 估算 (count_tokens)
      - 可用性检测 (is_available) — P0-16 新增, 用于双模式路由
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        from config import get_settings

        settings = get_settings()
        self._base_url = (base_url or settings.llm.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._default_model = default_model or settings.llm.model
        self._timeout = float(timeout or settings.llm.timeout)

    @property
    def name(self) -> str:
        return "ollama"

    # ------------------------------------------------------------------
    # is_available — P0-16 双模式路由的可用性检测
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        """检测 Ollama 服务是否可用 (async, 不抛异常)

        Returns:
            True 如果 Ollama 响应 /api/tags; False 如果连接失败
        """
        # ponytail: async 与其他方法一致, P0-17 双模式路由统一 await
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                resp = await client.get("/api/tags")
                return resp.status_code == 200
        except httpx.ConnectError:
            return False
        except Exception:
            logger.warning("ollama_is_available_failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # chat — 同步对话
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """同步对话 — POST /api/chat

        Returns:
            {"content": str, "model": str, "provider": "ollama", "usage": {...}}
        """
        model = model or self._default_model
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.post("/api/chat", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama chat 失败: HTTP {resp.status_code}")
            data = resp.json()

        return {
            "content": data.get("message", {}).get("content", ""),
            "response": data.get("message", {}).get("content", ""),
            "model": data.get("model", model),
            "provider": "ollama",
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        }

    # ------------------------------------------------------------------
    # stream_chat — NDJSON 流式对话
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式对话 — POST /api/chat (stream=True)

        Yields:
            每次产出的文本片段 (NDJSON message.content)
        """
        model = model or self._default_model
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with (
            httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client,
            client.stream("POST", "/api/chat", json=payload) as resp,
        ):
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama stream_chat 失败: HTTP {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    # ------------------------------------------------------------------
    # list_models — 模型列表
    # ------------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """列出已安装模型 — GET /api/tags

        连接失败时返回空列表 (不抛异常), 供 UI 优雅降级。
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
            except (httpx.ConnectError, httpx.HTTPStatusError) as e:
                logger.warning("ollama_list_models_failed", error=str(e))
                return []

    # ------------------------------------------------------------------
    # count_tokens — Token 估算 (无 Ollama API, 用字符估算)
    # ------------------------------------------------------------------

    async def count_tokens(self, text: str, *, model: str = "") -> int:
        """粗略估算 token 数 — 中文≈2 token/字, 其他≈0.25 token/字符"""
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 2 + other_chars * 0.25)
