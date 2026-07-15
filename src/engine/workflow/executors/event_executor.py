
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Event 节点执行器(P1-S1-007)

事件节点,对接 INF-001 事件总线,支持发布/订阅事件。
"""

from __future__ import annotations

from typing import Any

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("event")
class EventExecutor(BaseExecutor):
    """事件节点执行器

    配置:
        action: 事件动作(publish | subscribe,默认 publish)
        event_type: 事件类型(必填,如 "order.created")
        payload: 事件载荷(publish 模式,支持 {{var}})
        filter: 订阅过滤器(subscribe 模式,可选)
        timeout: 订阅等待超时秒数(默认 30)
    """

    node_type = "event"
    config_schema = {
        "action": {"required": False, "type": "string", "default": "publish"},
        "event_type": {"required": True, "type": "string"},
        "payload": {"required": False, "type": "object", "default": {}},
        "filter": {"required": False, "type": "object", "default": {}},
        "timeout": {"required": False, "type": "number", "default": 30},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        action = inp.config.get("action", "publish")
        event_type = inp.config.get("event_type", "")

        if not event_type:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="event_type is required",
            )

        if action == "publish":
            return await self._publish(inp, event_type)
        if action == "subscribe":
            return await self._subscribe(inp, event_type)
        return NodeOutput(
            node_id=inp.node_id,
            status="failed",
            error=f"Unknown event action: {action}",
        )

    async def _publish(self, inp: NodeInput, event_type: str) -> NodeOutput:
        """发布事件到事件总线"""
        payload = inp.config.get("payload", {})
        # 上下文变量替换
        payload = self._interpolate_payload(payload, inp.context)

        try:
            from src.infra.eventbus import get_event_bus

            bus = get_event_bus()
            await bus.publish(event_type, payload)

            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "action": "publish",
                    "event_type": event_type,
                    "payload": payload,
                    "published": True,
                },
            )
        except ImportError:
            logger.warning("eventbus_unavailable", event_type=event_type)
            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "action": "publish",
                    "event_type": event_type,
                    "payload": payload,
                    "published": False,
                    "note": "EventBus not available, event not published",
                },
            )
        except Exception as e:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Event publish failed: {e}",
            )

    async def _subscribe(self, inp: NodeInput, event_type: str) -> NodeOutput:
        """订阅事件(等待匹配事件到达)"""
        timeout = inp.config.get("timeout", 30)
        event_filter = inp.config.get("filter", {})

        try:
            import asyncio

            from src.infra.eventbus import get_event_bus

            bus = get_event_bus()
            future: asyncio.Future = asyncio.get_event_loop().create_future()

            async def handler(event_data: dict[str, Any]) -> None:
                if not future.done() and self._match_filter(event_data, event_filter):
                    future.set_result(event_data)

            bus.subscribe(event_type, handler)

            try:
                event_data = await asyncio.wait_for(future, timeout=timeout)
                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "action": "subscribe",
                        "event_type": event_type,
                        "event": event_data,
                        "received": True,
                    },
                )
            except TimeoutError:
                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "action": "subscribe",
                        "event_type": event_type,
                        "received": False,
                        "timeout": timeout,
                    },
                )
        except ImportError:
            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "action": "subscribe",
                    "event_type": event_type,
                    "received": False,
                    "note": "EventBus not available",
                },
            )

    def _interpolate_payload(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """上下文变量替换"""
        if not context:
            return payload
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                for ctx_key, ctx_val in context.items():
                    value = value.replace(f"{{{{{ctx_key}}}}}", str(ctx_val))  # noqa: PLW2901
            result[key] = value
        return result

    def _match_filter(self, event_data: dict[str, Any], event_filter: dict[str, Any]) -> bool:
        """检查事件是否匹配过滤器"""
        if not event_filter:
            return True
        return all(event_data.get(key) == value for key, value in event_filter.items())
