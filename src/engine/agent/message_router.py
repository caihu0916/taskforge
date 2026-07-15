
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge MessageRouter — Agent间精确消息路由

设计原则:
  - 支持Agent A→Agent B精确消息路由
  - 支持广播模式（target_agent=None）
  - 支持消息持久化（可选）
  - 支持消息确认机制

集成点:
  - SwarmOrchestrator._send_results_to_parent()
  - Agent协议扩展 (AgentMessage.target_agent)

端点设计:
| 端点 | 方法 | 说明 |
|------|------|------|
| /api/v2/agents/{agent_id}/message | POST | 向指定Agent发送消息 |
| /api/v2/agents/{agent_id}/messages | GET | 获取Agent消息列表 |

验收标准:
  - Agent A→B消息能正确投递
  - 支持精确路由和广播两种模式
  - 消息持久化（可选）
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.infra.async_task_tracker import spawn_task

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


@dataclass
class AgentMessage:
    """Agent消息结构"""

    message_id: str
    sender_id: str
    target_agent: str | None  # None表示广播
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    delivered: bool = False
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "target_agent": self.target_agent,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "delivered": self.delivered,
            "acknowledged": self.acknowledged,
        }


class MessageRouter:
    """消息路由器 — 支持精确路由和广播"""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = {}  # agent_id -> [callback]
        self._message_store: dict[str, list[AgentMessage]] = {}  # agent_id -> [messages]
        self._lock = asyncio.Lock()
        self._persistence_enabled = False

    async def send(
        self,
        sender_id: str,
        target_agent: str | None,
        content: str,
        metadata: dict[str, Any] | None = None,
        persist: bool = False,
    ) -> str:
        """
        发送消息

        Args:
            sender_id: 发送者ID
            target_agent: 目标Agent ID，None表示广播
            content: 消息内容
            metadata: 元数据
            persist: 是否持久化

        Returns:
            message_id: 消息ID
        """
        message_id = str(uuid.uuid4())
        message = AgentMessage(
            message_id=message_id,
            sender_id=sender_id,
            target_agent=target_agent,
            content=content,
            metadata=metadata or {},
        )

        async with self._lock:
            if target_agent:
                # 精确路由到目标Agent
                if target_agent in self._subscribers:
                    for callback in self._subscribers[target_agent]:
                        try:
                            spawn_task(callback(message), name="route_message_to_agent")
                        except Exception as e:
                            logger.warning("message_delivery_failed", agent=target_agent, error=str(e))
                    message.delivered = True
                else:
                    logger.debug("no_subscribers_for_agent", agent=target_agent)

                # 持久化消息
                if persist or self._persistence_enabled:
                    if target_agent not in self._message_store:
                        self._message_store[target_agent] = []
                    self._message_store[target_agent].append(message)

                logger.info(
                    "message_route_exact",
                    message_id=message_id,
                    sender=sender_id,
                    target=target_agent,
                )
            else:
                # 广播模式
                for agent_id, callbacks in self._subscribers.items():
                    for callback in callbacks:
                        try:
                            spawn_task(callback(message), name="broadcast_message_to_agent")
                        except Exception as e:
                            logger.warning("broadcast_delivery_failed", agent=agent_id, error=str(e))
                message.delivered = True

                logger.info(
                    "message_route_broadcast",
                    message_id=message_id,
                    sender=sender_id,
                    recipients=len(self._subscribers),
                )

        return message_id

    async def subscribe(self, agent_id: str, callback: Callable[[AgentMessage], Any]) -> None:
        """
        订阅消息

        Args:
            agent_id: Agent ID
            callback: 消息回调函数
        """
        async with self._lock:
            if agent_id not in self._subscribers:
                self._subscribers[agent_id] = []
            if callback not in self._subscribers[agent_id]:
                self._subscribers[agent_id].append(callback)

        logger.info("agent_subscribed", agent_id=agent_id)

    async def unsubscribe(self, agent_id: str, callback: Callable[[AgentMessage], Any]) -> None:
        """
        取消订阅

        Args:
            agent_id: Agent ID
            callback: 消息回调函数
        """
        async with self._lock:
            if agent_id in self._subscribers and callback in self._subscribers[agent_id]:
                self._subscribers[agent_id].remove(callback)
                if not self._subscribers[agent_id]:
                    del self._subscribers[agent_id]

        logger.info("agent_unsubscribed", agent_id=agent_id)

    async def get_messages(self, agent_id: str, limit: int = 100) -> list[AgentMessage]:
        """
        获取Agent的消息列表

        Args:
            agent_id: Agent ID
            limit: 返回数量限制

        Returns:
            消息列表
        """
        async with self._lock:
            return self._message_store.get(agent_id, [])[-limit:]

    async def acknowledge_message(self, agent_id: str, message_id: str) -> bool:
        """
        确认消息已接收

        Args:
            agent_id: Agent ID
            message_id: 消息ID

        Returns:
            是否确认成功
        """
        async with self._lock:
            if agent_id in self._message_store:
                for msg in self._message_store[agent_id]:
                    if msg.message_id == message_id:
                        msg.acknowledged = True
                        return True
        return False

    def enable_persistence(self) -> None:
        """启用消息持久化"""
        self._persistence_enabled = True

    def disable_persistence(self) -> None:
        """禁用消息持久化"""
        self._persistence_enabled = False

    def get_subscriber_count(self) -> int:
        """获取订阅者数量"""
        return len(self._subscribers)


# 单例模式
_router: MessageRouter | None = None


def get_message_router() -> MessageRouter:
    """获取MessageRouter单例"""
    global _router
    if _router is None:
        _router = MessageRouter()
    return _router
