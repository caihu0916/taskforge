
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""AI 节点执行器(P1-S1-008)

调用 LLM 执行 AI 任务,支持超时与重试。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("ai")
class AiExecutor(BaseExecutor):
    """AI 节点执行器

    配置:
        prompt: 提示词(必填,支持 {{var}} 上下文变量)
        system_prompt: 系统提示词(可选)
        model: 模型名称(可选,使用默认路由)
        temperature: 温度(默认 0.7)
        max_tokens: 最大 token 数(默认 2048)
        timeout: 超时秒数(默认 60)
        retries: 重试次数(默认 2)
        retry_delay: 重试延迟秒数(默认 1.0)
    """

    node_type = "ai"
    config_schema = {
        "prompt": {"required": True, "type": "string"},
        "system_prompt": {"required": False, "type": "string", "default": ""},
        "model": {"required": False, "type": "string", "default": ""},
        "temperature": {"required": False, "type": "number", "default": 0.7},
        "max_tokens": {"required": False, "type": "number", "default": 2048},
        "timeout": {"required": False, "type": "number", "default": 60},
        "retries": {"required": False, "type": "number", "default": 2},
        "retry_delay": {"required": False, "type": "number", "default": 1.0},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        prompt = inp.config.get("prompt", "")
        system_prompt = inp.config.get("system_prompt", "")
        model = inp.config.get("model", "")
        temperature = inp.config.get("temperature", 0.7)
        max_tokens = inp.config.get("max_tokens", 2048)
        timeout = inp.config.get("timeout", 60)
        retries = inp.config.get("retries", 2)
        retry_delay = inp.config.get("retry_delay", 1.0)

        if not prompt:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="prompt is required",
            )

        # 上下文变量替换
        prompt = self._interpolate(prompt, inp.context)
        if system_prompt:
            system_prompt = self._interpolate(system_prompt, inp.context)

        # 构建消息
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 带重试的 LLM 调用
        last_error = ""
        for attempt in range(retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._call_llm(messages, model, temperature, max_tokens),
                    timeout=timeout,
                )
                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "response": result.get("content", ""),
                        "model": result.get("model", model or "default"),
                        "usage": result.get("usage", {}),
                        "attempts": attempt + 1,
                    },
                )
            except TimeoutError:
                last_error = f"LLM call timeout after {timeout}s"
                logger.warning(
                    "ai_node_timeout",
                    node_id=inp.node_id,
                    attempt=attempt + 1,
                    timeout=timeout,
                )
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "ai_node_error",
                    node_id=inp.node_id,
                    attempt=attempt + 1,
                    error=str(e),
                )

            if attempt < retries:
                await asyncio.sleep(retry_delay)

        return NodeOutput(
            node_id=inp.node_id,
            status="failed",
            error=f"AI node failed after {retries + 1} attempts: {last_error}",
        )

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """调用 LLM(通过 LLM Router)"""
        try:
            from src.engine.llm.router import get_llm_router

            router = get_llm_router()
            kwargs: dict[str, Any] = {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if model:
                kwargs["model"] = model

            response = await router.chat(**kwargs)

            # 统一响应格式
            if isinstance(response, dict):
                return {
                    "content": response.get("content", response.get("text", "")),
                    "model": response.get("model", model or "default"),
                    "usage": response.get("usage", {}),
                }
            # 对象形式
            return {
                "content": getattr(response, "content", str(response)),
                "model": getattr(response, "model", model or "default"),
                "usage": getattr(response, "usage", {}),
            }
        except ImportError:
            # LLM Router 不可用,返回模拟响应
            return {
                "content": f"[Mock LLM Response] Prompt: {messages[-1]['content'][:100]}...",
                "model": model or "mock",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

    def _interpolate(self, text: str, context: dict[str, Any]) -> str:
        """上下文变量替换 {{var}} → context[var]"""
        if not context:
            return text
        result = text
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
