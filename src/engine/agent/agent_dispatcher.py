
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent 自动接单调度器 — 启用的Agent自动监听并执行匹配任务

工作流:
  1. 定期扫描 tasks 表中 status='created' 且 agent_role 不为空的任务
  2. 根据 agent_role 匹配 category, 找到该 category 下第一个 enabled 的 SpecialistAgent
  3. 通过 LongRunner 执行任务（支持拆步骤+断点续跑）
  4. 更新任务状态为 running → completed/failed

P0-3.6 重构: 角色/分类/查找逻辑已迁移至 delegate_tool.py 共享函数:
  - auto_assign_role() — 关键词→角色推断
  - role_to_category() — 角色→分类映射
  - find_enabled_agent() — 查找可用Agent
"""

from __future__ import annotations

import asyncio

import structlog

from src.engine.agent.specialist_base import get_agent_registry
from src.engine.tool.builtin.delegate_tool import (
    auto_assign_role,
    find_enabled_agent,
    role_to_category,
)
from src.infra.async_task_tracker import spawn_task

logger = structlog.get_logger(__name__)


class AgentDispatcher:
    """自动接单调度器"""

    def __init__(self, poll_interval: int = 3) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._poll_interval = poll_interval
        self.registry = get_agent_registry()
        # 并发上限信号量 — 防止 dispatch 过多任务同时执行
        from config import get_settings

        max_conc = get_settings().task.max_concurrent
        self._semaphore = asyncio.Semaphore(max_conc)
        logger.info("dispatcher_init", max_concurrent=max_conc)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """启动调度器 — 必须在运行中的事件循环内调用 (uvicorn lifespan 保此条件)"""
        if self._running:
            logger.warning("dispatcher_already_running")
            return
        self._running = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._poll_loop())
        logger.info("agent_dispatcher_started", poll_interval=self._poll_interval)

    def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("agent_dispatcher_stopped")

    async def _poll_loop(self) -> None:
        """轮询任务队列 — CancelledError 优雅退出，单次异常不中断循环"""
        try:
            while self._running:
                try:
                    dispatched = await self._poll_once()
                    if dispatched > 0:
                        logger.info("dispatcher_poll_batch", dispatched=dispatched)
                except Exception as e:
                    logger.error("dispatcher_poll_error", error=str(e), exc_info=True)
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info("agent_dispatcher_cancelled")
        finally:
            self._running = False

    async def _poll_once(self) -> int:
        """执行一次轮询，返回派发数量

        改造: 统一走 LongRunner 执行，支持拆步骤+checkpoint+断点续跑
        自动为无 agent_role 的任务分配角色
        """
        from src.engine.task.long_runner import get_long_runner
        from src.engine.task.manager import TaskStatus, get_task_manager
        from src.infra.database.connection import get_connection_manager

        cm = get_connection_manager()
        mgr = get_task_manager()
        count = 0

        with cm.get_conn() as conn:
            # 取 created + paused 任务（paused 任务优先恢复，created 任务新建）
            rows = conn.execute(
                "SELECT id, title, description, agent_role, metadata, status FROM tasks "
                "WHERE status IN (?, ?) "
                "ORDER BY CASE WHEN status = 'paused' THEN 0 ELSE 1 END, "
                "created_at ASC LIMIT 10",
                (TaskStatus.CREATED.value, TaskStatus.PAUSED.value),
            ).fetchall()

            rows = [dict(r) for r in rows]

        for row in rows:
            task_id = row["id"]
            agent_role = row["agent_role"]
            task_status = row.get("status", "created")

            # paused 任务用 LongRunner.resume() 断点续跑
            if task_status == "paused":
                try:
                    runner = get_long_runner()
                    spawn_task(runner.resume(task_id), name="dispatcher_resume_task")
                    count += 1
                    logger.info("dispatcher_task_resumed", task=task_id, role=agent_role)
                except Exception as e:
                    logger.warning("dispatcher_resume_failed", task=task_id, error=str(e), exc_info=True)
                continue

            # 自动分配: 无 agent_role 的任务根据标题关键词推断
            if not agent_role:
                desc = row.get("description", "")
                agent_role = auto_assign_role(row["title"], desc)
                if agent_role:
                    # 持久化到 DB
                    with cm.get_conn() as conn:
                        conn.execute(
                            "UPDATE tasks SET agent_role = ? WHERE id = ?",
                            (agent_role, task_id),
                        )
                        conn.commit()
                    logger.info("dispatcher_auto_assigned_role", task=task_id, role=agent_role)
                else:
                    logger.debug("dispatcher_cannot_auto_assign", task=task_id)
                    continue

            category = role_to_category(agent_role)

            if not category:
                continue

            agent = find_enabled_agent(category)
            if not agent:
                logger.debug("dispatcher_no_enabled_agent", task=task_id, category=category)
                continue

            # 走 LongRunner 执行 — 拆步骤+checkpoint+断点续跑
            # 信号量控制：最多 max_concurrent 个任务同时执行
            try:
                runner = get_long_runner()
                spawn_task(
                    self._run_with_semaphore(runner.execute, task_id),
                    name="dispatcher_execute_task",
                )
                logger.info("dispatcher_task_dispatched_to_long_runner", task=task_id, agent=agent)
            except Exception as e:
                logger.warning("dispatcher_long_runner_failed", task=task_id, error=str(e), exc_info=True)
                # 降级: 直接走单次 dispatch
                result = await self._direct_dispatch(row, agent, mgr)
                if not result:
                    continue

            count += 1

        return count

    async def _run_with_semaphore(self, coro_fn, *args, **kwargs):
        """在信号量保护下执行协程，控制并发上限"""
        async with self._semaphore:
            return await coro_fn(*args, **kwargs)

    async def _direct_dispatch(self, row, agent: str, mgr) -> bool:
        """降级: 直接单次 dispatch（无拆步骤/断点续跑），受信号量保护"""
        async with self._semaphore:
            return await self._do_direct_dispatch(row, agent, mgr)

    async def _do_direct_dispatch(self, row, agent: str, mgr) -> bool:
        """实际 direct dispatch 逻辑"""
        import json as _json

        from src.engine.quality.gate import get_quality_gate, get_quality_manager
        from src.engine.task.manager import TaskStatus

        task_id = row["id"]
        try:
            updated = mgr.update_status(
                task_id,
                TaskStatus.RUNNING,
                expected_old_status=TaskStatus.CREATED,
            )
            if not updated:
                return False
        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            # TaskConcurrentUpdate: 被其他调度器抢占，静默返回
            from src.exceptions import TaskConcurrentUpdate

            if isinstance(e, TaskConcurrentUpdate):
                logger.info("dispatcher_task_claimed_by_other", task=task_id)
                return False
            logger.warning("dispatcher_task_update_failed", task=task_id, error=str(e), exc_info=True)
            return False

        raw_meta = row["metadata"] or "{}"
        if isinstance(raw_meta, str):
            try:
                parsed_meta = _json.loads(raw_meta)
            except (_json.JSONDecodeError, TypeError):
                parsed_meta = {}
        else:
            parsed_meta = raw_meta if isinstance(raw_meta, dict) else {}

        result = await self.registry.dispatch(
            agent,
            row["title"],
            task_id=task_id,
            description=row["description"],
            metadata=parsed_meta,
        )

        if result.get("success"):
            content = result.get("result", "")[:2000]
            agent_role = (row.get("agent_role", None)) or ""
            gate = get_quality_gate()
            qresult = gate.check(content, agent_role=agent_role or "boss")
            get_quality_manager().record(task_id, qresult, agent_role=agent_role)

            if qresult.passed:
                mgr.update_status(task_id, TaskStatus.COMPLETED, result=content)
            else:
                task = mgr.get(task_id)
                meta = dict(task.metadata_) if task and task.metadata_ else {}
                retries = meta.get("_quality_retries", 0)

                if retries < 2:
                    meta["_quality_retries"] = retries + 1
                    meta["_last_quality_issues"] = qresult.issues
                    meta["_last_quality_score"] = qresult.score
                    mgr.update_fields(task_id, metadata=_json.dumps(meta, ensure_ascii=False))
                    mgr.update_status(task_id, TaskStatus.CREATED, error=qresult.issues[0] if qresult.issues else "")
                    logger.info("quality_retry_direct", task_id=task_id[:8], retry=retries + 1, score=qresult.score)
                else:
                    meta["_quality_retries"] = retries + 1
                    meta["_quality_final_issues"] = qresult.issues
                    meta["_quality_final_score"] = qresult.score
                    mgr.update_fields(task_id, metadata=_json.dumps(meta, ensure_ascii=False))
                    mgr.update_status(
                        task_id, TaskStatus.QUALITY_REVIEW, error=f"质量未达标: {'; '.join(qresult.issues[:3])}"
                    )
                    logger.warning("quality_review_direct", task_id=task_id[:8], score=qresult.score)
        else:
            mgr.update_status(task_id, TaskStatus.FAILED, error=result.get("error", "unknown")[:500])

        return True


# 全局单例
_dispatcher: AgentDispatcher | None = None


def get_agent_dispatcher() -> AgentDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AgentDispatcher()
    return _dispatcher


def reset_agent_dispatcher() -> None:
    global _dispatcher
    _dispatcher = None
