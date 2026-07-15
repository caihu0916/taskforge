
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 工作流超时检查调度器 — 定时检查运行中工作流的超时步骤

在应用启动时自动运行, 每分钟检查一次:
  1. 扫描所有 RUNNING 状态的工作流
  2. 调用 PDCAEngine.check_deadlines() 标记超时步骤
  3. 通过通道通知发送超时提醒
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog

from src.infra.async_task_tracker import spawn_task

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL = 60  # 每分钟检查一次


class WorkflowDeadlineScheduler:
    """工作流步骤超时检查调度器"""

    def __init__(self, interval_seconds: float = DEFAULT_INTERVAL) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            return
        self._running = True
        self._task = spawn_task(self._check_loop(), name="deadline_check_loop")
        logger.info("workflow_deadline_scheduler_started", interval=self._interval)

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("workflow_deadline_scheduler_stopped")

    async def _check_loop(self) -> None:
        """主循环"""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self._run_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("workflow_deadline_check_error", error=str(e), exc_info=True)

    async def _run_check(self) -> None:
        """执行一次超时检查"""
        try:
            from src.engine.workflow.engine import get_pdca_engine

            engine = get_pdca_engine()
            # 列出所有运行中的工作流
            from src.engine.workflow.models import WorkflowStatus

            running_workflows = engine.list_workflows(status=WorkflowStatus.RUNNING)

            total_overdue = 0
            for wf in running_workflows:
                result = engine.check_deadlines(wf.id)
                overdue_count = len(result.get("overdue_steps", []))
                if overdue_count > 0:
                    total_overdue += overdue_count
                    # 通知: 超时提醒
                    try:
                        from src.engine.channel.notifier import notify_workflow_event

                        await notify_workflow_event(
                            wf.name,
                            "deadline_expired",
                            f"{overdue_count}个步骤超时",
                        )
                    except Exception as e:
                        logger.warning("deadline_notify_failed", error=str(e), exc_info=True)

            if total_overdue > 0:
                logger.info(
                    "workflow_deadlines_checked", total_overdue=total_overdue, workflows_checked=len(running_workflows)
                )
        except Exception as e:
            logger.warning("workflow_deadline_check_failed", error=str(e), exc_info=True)


# ── 全局单例 ──
from src.infra.singleton import Singleton

_deadline_scheduler = Singleton(WorkflowDeadlineScheduler)


def get_workflow_deadline_scheduler() -> WorkflowDeadlineScheduler:
    return _deadline_scheduler.get()


def reset_workflow_deadline_scheduler() -> None:
    _deadline_scheduler.reset()
