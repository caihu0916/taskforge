
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P2-08: Fork 并行机制 — ForkOrchestrator 并行调度多个 fork 子任务

复用 SubAgentPool (B-03) 做并发限流 + 异常隔离。
ForkResult 封装 success/result/error/name, 统一成功与异常的返回格式。

用法:
    orch = ForkOrchestrator(max_concurrent=3)
    results = await orch.fork_all([task_a, task_b, task_c], names=["a", "b", "c"])
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from .sub_agent_pool import SubAgentPool

logger = structlog.get_logger(__name__)

# fork 任务类型: 零参协程函数 (调用返回 coroutine)
ForkTask = Callable[[], Awaitable[Any]]


@dataclass
class ForkResult:
    """P2-08: Fork 任务结果封装 — 统一成功与异常"""

    success: bool
    result: Any = None
    error: str = ""
    name: str = ""


class ForkOrchestrator:
    """P2-08: Fork 并行编排器 — 复用 SubAgentPool 做并发限流

    ponytail: 不重新实现并发逻辑, 委托 SubAgentPool.spawn/wait_all, 仅加 ForkResult 封装。
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._max_concurrent = max_concurrent

    async def fork_all(
        self,
        tasks: list[ForkTask],
        *,
        names: list[str] | None = None,
    ) -> list[ForkResult]:
        """并行执行多个 fork 任务, 返回 ForkResult 列表

        Args:
            tasks: 零参协程函数列表 (调用返回 coroutine)
            names: 可选任务名列表 (便于日志追踪)

        Returns:
            ForkResult 列表, 顺序与 tasks 一致, 异常隔离不传播
        """
        if not tasks:
            return []

        if names is None:
            names = [f"fork_{i}" for i in range(len(tasks))]

        pool = SubAgentPool(max_concurrent=self._max_concurrent)
        for task_fn in tasks:
            pool.spawn(task_fn())

        raw_results = await pool.wait_all()

        # 封装为 ForkResult (异常隔离)
        results: list[ForkResult] = []
        for i, raw in enumerate(raw_results):
            name = names[i] if i < len(names) else f"fork_{i}"
            if isinstance(raw, Exception):
                results.append(ForkResult(success=False, error=str(raw), name=name))
            else:
                results.append(ForkResult(success=True, result=raw, name=name))
        return results


__all__ = ["ForkOrchestrator", "ForkResult"]
