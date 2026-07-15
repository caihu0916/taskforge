
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""B-03: SubAgentPool — 子 Agent 并发池

解决 sub_agent.py spawn_agent_legacy 阻塞式 await 问题。
支持并发 spawn 多个子 Agent，wait_all 等待全部完成。

对标 Claude Code SubAgentPool。

接入点: Coordinator.dispatch → pool.spawn() + pool.wait_all()
依赖: 无 (纯 asyncio 实现)
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class SubAgentPool:
    """子 Agent 并发池 — Semaphore 限流 + asyncio.create_task 并发

    用法:
        pool = SubAgentPool(max_concurrent=3)
        pool.spawn(agent_a())
        pool.spawn(agent_b())
        pool.spawn(agent_c())
        results = await pool.wait_all()
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def pending_count(self) -> int:
        """已 spawn 未完成的任务数"""
        return sum(1 for t in self._tasks if not t.done())

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        """spawn 一个子 Agent 协程，返回 asyncio.Task

        通过 Semaphore 限流，max_concurrent 个任务可同时运行。
        """

        async def _runner() -> Any:
            async with self._semaphore:
                try:
                    return await coro
                except Exception as e:
                    logger.debug("exception_handled", error=str(e))
                    # 异常隔离 — 不传播，以 Exception 对象形式返回
                    logger.warning("sub_agent_pool_task_error", error=str(e), exc_info=True)
                    return e

        task = asyncio.create_task(_runner())
        self._tasks.append(task)
        return task

    async def wait_all(self) -> list[Any]:
        """等待所有已 spawn 的任务完成，返回结果列表

        异常以 Exception 对象形式存在于结果中 (不传播)。
        调用方应检查结果类型。
        """
        if not self._tasks:
            return []
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        # 清理已完成任务，允许 Pool 复用
        self._tasks = []
        return list(results)


__all__ = ["SubAgentPool"]
