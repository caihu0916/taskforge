
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskFlow 节点定义 — 从 flow.py 拆出

Node/AsyncNode/LLMCallNode 三阶段执行单元 + retry
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

Context = dict[str, Any]
Transition = str | None


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Node(ABC):
    """节点基类 — prep/exec/post 三阶段 + retry"""

    def __init__(self, name: str = "", max_retries: int = 0, retry_delay: float = 1.0) -> None:
        self.name = name or self.__class__.__name__
        self.status = NodeStatus.PENDING
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def prep(self, ctx: Context) -> Any:
        return None

    @abstractmethod
    def exec(self, prep_result: Any, ctx: Context) -> Any: ...

    @abstractmethod
    def post(self, ctx: Context, exec_result: Any) -> None: ...

    def run(self, ctx: Context) -> Any:
        """同步执行节点。若在异步上下文中，请优先使用 run_async() 以避免阻塞事件循环。"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._run_internal_sync(ctx)
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                last_error = e
                if attempt < self.max_retries:
                    import time

                    time.sleep(self.retry_delay * (2**attempt))
                    logger.info("node_retry", node=self.name, attempt=attempt + 1)
                else:
                    logger.exception("node_retry_exhausted", node=self.name, attempt=attempt + 1)
        raise last_error

    async def run_async(self, ctx: Context) -> Any:
        """异步安全版 run — 用 asyncio.sleep 替代 time.sleep"""
        import asyncio

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._run_internal_sync(ctx)
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    logger.info("node_retry", node=self.name, attempt=attempt + 1)
                else:
                    logger.exception("node_retry_exhausted", node=self.name, attempt=attempt + 1)
        raise last_error

    def _run_internal_sync(self, ctx: Context) -> Any:
        self.status = NodeStatus.RUNNING
        try:
            prep_result = self.prep(ctx)
            exec_result = self.exec(prep_result, ctx)
            self.post(ctx, exec_result)
            self.status = NodeStatus.SUCCESS
            return exec_result
        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            self.status = NodeStatus.FAILED
            logger.warning("node_failed", node=self.name, error=str(e), exc_info=True)
            raise


class AsyncNode(Node, ABC):
    @abstractmethod
    async def exec(self, prep_result: Any, ctx: Context) -> Any: ...

    async def run_async(self, ctx: Context) -> Any:
        """异步执行 + 重试 — 复用 Node.run_async 的 asyncio.sleep 逻辑"""
        import asyncio

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                self.status = NodeStatus.RUNNING
                prep_result = self.prep(ctx)
                exec_result = await self.exec(prep_result, ctx)
                self.post(ctx, exec_result)
                self.status = NodeStatus.SUCCESS
                return exec_result
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                last_error = e
                self.status = NodeStatus.FAILED
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    logger.info("async_node_retry", node=self.name, attempt=attempt + 1)
                else:
                    logger.exception("async_node_retry_exhausted", node=self.name, attempt=attempt + 1)
        raise last_error


class LLMCallNode(AsyncNode):
    """LLM调用节点 — 真实路由调用"""

    def __init__(
        self,
        name: str = "llm_call",
        input_key: str = "prompt",
        output_key: str = "response",
        system_prompt: str = "",
        profile: str = "fast",
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ) -> None:
        super().__init__(name=name, max_retries=max_retries, retry_delay=retry_delay)
        self.input_key = input_key
        self.output_key = output_key
        self.system_prompt = system_prompt
        self.profile = profile

    def _build_messages(self, ctx: Context) -> list[dict[str, Any]]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        user_content = ctx.get(self.input_key, "")
        if user_content:
            messages.append({"role": "user", "content": str(user_content)})
        history = ctx.get("history", [])
        if isinstance(history, list):
            messages = messages[:-1] + history + messages[-1:]
        return messages

    async def exec(self, prep_result: Any, ctx: Context) -> Any:
        # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
        try:
            from src.engine.llm.router import get_llm_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        router = get_llm_router()
        messages = self._build_messages(ctx)
        result = await router.chat(messages, profile=self.profile)
        ctx[self.output_key] = result.get("content", "")
        ctx["__llm_usage__"] = result.get("usage", {})
        ctx["__llm_provider__"] = result.get("provider", "")
        return result
