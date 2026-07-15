
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""WorkflowExecutor — 声明式工作流执行引擎 (对标 v2.1.168 WorkflowInput/Output)

支持: agent() / parallel() / pipeline() / phase() 四种步骤类型
特性: V3 spawn_agent 执行 + pipeline上下文传递 + 断点续跑 + 进度回调 + 持久化
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


@dataclass
class WorkflowRun:
    workflow_name: str = ""
    run_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:8])
    status: str = "pending"  # pending / running / completed / failed / paused
    step_results: list[dict] = field(default_factory=list)
    _store: dict[str, Any] = field(default_factory=dict)  # 运行时键值缓存
    error: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    dead_letters: list[dict] = field(default_factory=list)  # on_failure=dead_letter 时的记录


class WorkflowExecutor:
    """声明式工作流执行器 — 解析 DSL 脚本并逐步执行

    P1-INF-012 并发安全加固:
      - self._runs dict 使用 AsyncLockManager 保护,防止多协程并发写入损坏
      - prepare()/run() 中对 _runs 的写入通过命名锁串行化
    """

    def __init__(self, session_dir: str = "", cm=None) -> None:
        self._session_dir = Path(session_dir or "data/workflows")
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, WorkflowRun] = {}
        self._cm = cm
        # P1-INF-012: 并发锁保护 _runs dict
        from src.infra.concurrency import get_async_lock_manager

        self._lock_mgr = get_async_lock_manager()

    # ── 持久化 ──

    def _persist_run(self, run: WorkflowRun) -> None:
        """将 WorkflowRun 写入 workflow_runs 表"""
        if not self._cm:
            return
        from src.engine.workflow.models import WORKFLOW_RUN_DDL

        now = datetime.now(UTC).isoformat()
        try:
            with self._cm.get_conn() as conn:
                conn.execute(WORKFLOW_RUN_DDL.split(";")[0])
                conn.execute(
                    """INSERT OR REPLACE INTO workflow_runs
                       (run_id, workflow_name, status, total_steps, completed_steps, step_results, error, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run.run_id,
                        run.workflow_name,
                        run.status,
                        run.total_steps,
                        run.completed_steps,
                        json.dumps(run.step_results, ensure_ascii=False),
                        run.error,
                        now,
                        now,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.debug("workflow_run_persist_failed", run_id=run.run_id, error=str(e))

    def _load_run(self, run_id: str) -> WorkflowRun | None:
        """从 workflow_runs 表加载一条记录"""
        if not self._cm:
            return None
        from src.engine.workflow.models import WORKFLOW_RUN_DDL

        try:
            with self._cm.get_conn() as conn:
                conn.execute(WORKFLOW_RUN_DDL.split(";")[0])
                row = conn.execute(
                    "SELECT run_id, workflow_name, status, total_steps, completed_steps, step_results, error FROM workflow_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if not row:
                    return None
                return WorkflowRun(
                    run_id=row["run_id"],
                    workflow_name=row["workflow_name"],
                    status=row["status"],
                    total_steps=row["total_steps"],
                    completed_steps=row["completed_steps"],
                    step_results=json.loads(row["step_results"]) if row["step_results"] else [],
                    error=row["error"] or "",
                )
        except Exception as e:
            logger.debug("workflow_run_load_failed", run_id=run_id, error=str(e))
            return None

    def _emit_workflow_event(self, event_type: str, data: dict) -> None:
        """I5: 发射 EventBus 事件 (非阻塞, 失败不影响主流程)"""
        try:
            from src.engine.autonomous.event_bus import EventType, get_event_bus

            bus = get_event_bus()
            # 统一使用 workflow.event 类型，具体动作放在 data.action 里
            enriched_data = {**data, "action": event_type}
            evt = bus.emit(EventType.WORKFLOW_EVENT, data=enriched_data, source="WorkflowExecutor")
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(bus.publish(evt))
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("workflow_event_publish_failed", evt_type=event_type, error=str(e), exc_info=True)

    # ── 执行 ──

    def prepare(self, script, args: dict | None = None) -> WorkflowRun:
        """预解析脚本，返回 WorkflowRun（不执行）

        P1-INF-012: 使用锁保护 _runs dict 写入
        """
        from src.engine.workflow.dsl import parse_workflow_script

        wf = parse_workflow_script(script) if isinstance(script, str) else script
        name = getattr(wf, "name", str(script))
        run = WorkflowRun(
            workflow_name=name,
            status="pending",
            total_steps=len(wf.steps),
        )
        # P1-INF-012: 同步方法直接操作 dict(prepare 不在协程中)
        self._runs[run.run_id] = run
        self._persist_run(run)
        return run

    async def run(
        self,
        script,
        args: dict | None = None,
        *,
        on_progress: Callable[[dict], None] | None = None,
        on_approval: Callable | None = None,  # G02-T03: 审批暂停/恢复回调
        cancel_event: asyncio.Event | None = None,
    ) -> WorkflowRun:
        """执行工作流脚本

        Args:
            script: DSL字符串或已解析的WorkflowScript
            args: 运行时参数
            on_progress: 步骤进度回调 → {"run_id", "step", "total", "status", ...}
            on_approval: G02-T03 审批回调, 返回True(批准)/False(暂停)
            cancel_event: 取消信号
        """
        wf, run = self._prepare_run(script)
        pipeline_context: dict = {}

        for i, step in enumerate(wf.steps):
            # 取消检查
            if self._is_cancelled(run, cancel_event, i):
                break

            # G02-T03: 审批暂停/恢复
            if not await self._check_approval(step, on_approval, run, i):
                break

            on_failure = step.opts.get("on_failure", "halt")
            max_retries = int(step.opts.get("max_retries", 1))
            retry_backoff_ms = int(step.opts.get("retry_backoff_ms", 50))
            step_succeeded = False
            last_error: Exception | None = None
            attempt_count = 0

            while attempt_count <= max_retries and not step_succeeded:
                attempt_count += 1
                if attempt_count > 1 and retry_backoff_ms > 0:
                    await asyncio.sleep(retry_backoff_ms / 1000.0)
                try:
                    pipeline_context = await self._execute_step_by_type(step, args, pipeline_context, run, i)
                    step_succeeded = True
                except Exception as e:
                    logger.debug("exception_handled", error=str(e))
                    last_error = e
                    if run.step_results and run.step_results[-1].get("step_index") == i:
                        run.step_results.pop()
                    if on_failure != "retry":
                        break

            if step_succeeded:
                self._on_step_success(run, step, i, on_progress)
                continue

            err_msg = str(last_error) if last_error else ""
            logger.warning("workflow_step_failed", run_id=run.run_id, step=i, error=err_msg, exc_info=True)
            action = self._handle_step_failure(run, step, i, on_failure, err_msg, attempt_count)
            if action == "continue":
                continue
            break

        self._finalize_run(run, wf)
        return run

    def _prepare_run(self, script) -> tuple[Any, WorkflowRun]:
        """解析脚本并初始化 WorkflowRun"""
        from src.engine.workflow.dsl import parse_workflow_script

        wf = parse_workflow_script(script) if isinstance(script, str) else script
        run = WorkflowRun(
            workflow_name=wf.name,
            status="running",
            total_steps=len(wf.steps),
        )
        self._runs[run.run_id] = run
        self._persist_run(run)
        logger.info("workflow_started", name=wf.name, run_id=run.run_id, steps=len(wf.steps))
        return wf, run

    def _is_cancelled(self, run: WorkflowRun, cancel_event: asyncio.Event | None, i: int) -> bool:
        """检查取消信号"""
        if cancel_event and cancel_event.is_set():
            run.status = "paused"
            run.error = "cancelled"
            logger.info("workflow_cancelled", run_id=run.run_id, step=i)
            return True
        return False

    async def _check_approval(self, step, on_approval, run: WorkflowRun, i: int) -> bool:
        """G02-T03: 审批暂停/恢复 — requires_approval步骤需人工确认. 返回True=继续执行"""
        if not step.opts.get("requires_approval") or on_approval is None:
            return True
        try:
            approved = await on_approval(
                {
                    "step_index": i,
                    "step_type": step.type,
                    "step_prompt": step.prompt[:200],
                    "run_id": run.run_id,
                }
            )
        except Exception:
            logger.exception("workflow_on_approval_error")
            approved = False

        if not approved:
            run.status = "paused"
            run.error = f"approval_required_at_step_{i}"
            logger.info("workflow_paused_for_approval", run_id=run.run_id, step=i)
            self._persist_run(run)
            return False
        return True

    async def _execute_step_by_type(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """按步骤类型分派执行，返回更新后的 pipeline_context"""
        dispatch = {
            "parallel": self._exec_parallel,
            "pipeline": self._exec_pipeline,
            "phase": self._exec_phase,
            "if_else": self._exec_if_else,
            "loop": self._exec_loop,
            "switch": self._exec_switch,
        }
        handler = dispatch.get(step.type, self._exec_agent)
        return await handler(step, args, pipeline_context, run, i)

    async def _exec_parallel(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 parallel 步骤 — 所有子步骤并发"""
        results = await asyncio.gather(
            *[self._execute_step(child, args or {}, pipeline_context=pipeline_context) for child in step.children]
        )
        aggregated = "; ".join(r.get("result", "") for r in results if r.get("result"))
        run.step_results.append(
            {
                "step_index": i,
                "type": "parallel",
                "prompt": f"parallel x{len(step.children)}",
                "status": "completed",
                "result": aggregated,
                "sub_results": results,
            }
        )
        return pipeline_context

    async def _exec_pipeline(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 pipeline 步骤 — 子步骤串行，上下文传递"""
        pipe_result: dict = {}
        for _j, child in enumerate(step.children):
            if pipeline_context:
                child.prompt = f"{child.prompt}\n[上下文]\n{pipeline_context.get('result', '')}"
            pipe_result = await self._execute_step(child, args or {}, pipeline_context=pipeline_context)
            pipeline_context = pipe_result
        run.step_results.append(
            {
                "step_index": i,
                "type": "pipeline",
                "prompt": f"pipeline x{len(step.children)}",
                "status": "completed",
                "result": pipe_result.get("result", ""),
            }
        )
        return pipeline_context

    async def _exec_phase(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 phase 步骤 — 阶段内子步骤串行"""
        phase_results = []
        for child in step.children:
            if pipeline_context and child.type == "agent":
                child.prompt = f"{child.prompt}\n[上一步结果]\n{pipeline_context.get('result', '')}"
            r = await self._execute_step(child, args or {}, pipeline_context=pipeline_context)
            pipeline_context = r
            phase_results.append(r)
        run.step_results.append(
            {
                "step_index": i,
                "type": "phase",
                "prompt": step.opts.get("title", f"phase-{i}"),
                "status": "completed",
                "result": "; ".join(r.get("result", "") for r in phase_results),
            }
        )
        return pipeline_context

    async def _exec_if_else(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 if_else 步骤 — 条件分支"""
        from src.engine.workflow.dsl import evaluate_condition

        cond_result = evaluate_condition(step.condition, run._store)
        branch = step.branch_true if cond_result else step.branch_false
        branch_label = "then" if cond_result else "else"
        branch_results = []
        for child in branch:
            if pipeline_context and child.type == "agent":
                child.prompt = f"{child.prompt}\n[上一步结果]\n{pipeline_context.get('result', '')}"
            r = await self._execute_step(child, args or {}, pipeline_context=pipeline_context)
            pipeline_context = r
            branch_results.append(r)
        run.step_results.append(
            {
                "step_index": i,
                "type": "if_else",
                "prompt": step.prompt,
                "status": "completed",
                "result": f"[{branch_label}] " + "; ".join(r.get("result", "") for r in branch_results),
                "branch": branch_label,
                "condition_result": cond_result,
            }
        )
        return pipeline_context

    async def _exec_loop(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 loop 步骤 — 循环执行 body"""
        from src.engine.workflow.dsl import evaluate_condition

        max_iter = step.opts.get("max_iterations", 10)
        loop_results = []
        exit_early = False
        for iteration in range(max_iter):
            if iteration > 0 and step.condition:
                try:
                    if evaluate_condition(step.condition, run._store):
                        exit_early = True
                        break
                except ValueError:
                    pass
            iter_results = []
            for child in step.branch_true:
                if pipeline_context and child.type == "agent":
                    child.prompt = f"{child.prompt}\n[上一步结果]\n{pipeline_context.get('result', '')}"
                r = await self._execute_step(child, args or {}, pipeline_context=pipeline_context)
                pipeline_context = r
                iter_results.append(r)
            loop_results.extend(iter_results)
        run.step_results.append(
            {
                "step_index": i,
                "type": "loop",
                "prompt": step.prompt,
                "status": "completed",
                "result": f"iterations={len(loop_results)}, exit_early={exit_early}; "
                + "; ".join(r.get("result", "") for r in loop_results),
                "iterations": len(loop_results),
                "exit_early": exit_early,
            }
        )
        return pipeline_context

    async def _exec_switch(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行 switch 步骤 — 多分支选择"""
        on_value = str(run._store.get(step.condition, step.condition))
        matched_branch = step.cases.get(on_value)
        branch_label = f"case_{on_value}" if matched_branch else "default"
        branch = matched_branch if matched_branch else step.default_branch
        branch_results = []
        for child in branch:
            if pipeline_context and child.type == "agent":
                child.prompt = f"{child.prompt}\n[上一步结果]\n{pipeline_context.get('result', '')}"
            r = await self._execute_step(child, args or {}, pipeline_context=pipeline_context)
            pipeline_context = r
            branch_results.append(r)
        run.step_results.append(
            {
                "step_index": i,
                "type": "switch",
                "prompt": step.prompt,
                "status": "completed",
                "result": f"[{branch_label}] " + "; ".join(r.get("result", "") for r in branch_results),
                "branch": branch_label,
                "on_value": on_value,
            }
        )
        return pipeline_context

    async def _exec_agent(self, step, args, pipeline_context: dict, run: WorkflowRun, i: int) -> dict:
        """执行普通 agent 步骤"""
        if pipeline_context and step.type == "agent":
            step.prompt = f"{step.prompt}\n[上一步结果]\n{pipeline_context.get('result', '')}"
        result = await self._execute_step(step, args or {}, pipeline_context=pipeline_context)
        pipeline_context = result
        run.step_results.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": step.prompt,
                "status": "completed",
                "result": result.get("result", str(result)),
            }
        )
        return pipeline_context

    def _on_step_success(self, run: WorkflowRun, step, i: int, on_progress) -> None:
        """步骤成功后的持久化、事件发射和进度回调"""
        run.completed_steps = i + 1
        self._persist_run(run)
        self._emit_workflow_event(
            "workflow.step_completed",
            {
                "run_id": run.run_id,
                "step": i + 1,
                "total": run.total_steps,
                "type": step.type,
            },
        )
        if on_progress:
            on_progress(
                {
                    "run_id": run.run_id,
                    "step": i + 1,
                    "total": run.total_steps,
                    "status": "running",
                    "step_type": step.type,
                }
            )

    def _handle_step_failure(
        self, run: WorkflowRun, step, i: int, on_failure: str, err_msg: str, attempt_count: int
    ) -> str:
        """处理步骤失败，返回 break 或 continue"""
        dispatch = {
            "halt": self._fail_halt,
            "skip": self._fail_skip,
            "dead_letter": self._fail_dead_letter,
            "retry": self._fail_retry,
        }
        handler = dispatch.get(on_failure, self._fail_halt)
        return handler(run, step, i, err_msg, attempt_count)

    def _fail_halt(self, run: WorkflowRun, step, i: int, err_msg: str, attempt_count: int) -> str:
        run.step_results.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": step.prompt,
                "status": "failed",
                "error": err_msg,
            }
        )
        return "break"

    def _fail_skip(self, run: WorkflowRun, step, i: int, err_msg: str, attempt_count: int) -> str:
        run.step_results.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": step.prompt,
                "status": "skipped",
                "error": err_msg,
            }
        )
        return "continue"

    def _fail_dead_letter(self, run: WorkflowRun, step, i: int, err_msg: str, attempt_count: int) -> str:
        # P1-2: 统一状态标记为 "dead_letter"，便于区分
        # P1-3: 脱敏处理 — 截断 prompt，过滤敏感字段
        safe_prompt = self._sanitize_text(step.prompt[:200] if step.prompt else "")
        safe_error = self._sanitize_text(err_msg[:500] if err_msg else "")
        run.dead_letters.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": safe_prompt,
                "error": safe_error,
            }
        )
        run.step_results.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": safe_prompt,
                "status": "dead_letter",
                "error": safe_error,
            }
        )
        return "continue"

    def _fail_retry(self, run: WorkflowRun, step, i: int, err_msg: str, attempt_count: int) -> str:
        run.step_results.append(
            {
                "step_index": i,
                "type": step.type,
                "prompt": step.prompt,
                "status": "failed",
                "error": err_msg,
                "retries": attempt_count,
            }
        )
        return "break"

    def _sanitize_text(self, text: str) -> str:
        """脱敏处理 — 过滤可能的敏感信息（API key、密码等）"""
        return re.sub(
            r"(api[_-]?key|password|secret|token|credential)[\s:=]+[^\s]+",
            "[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )

    def _finalize_run(self, run: WorkflowRun, wf) -> None:
        """计算最终状态并发射完成事件"""
        run.status = (
            "completed"
            if all(s.get("status") in ("completed", "skipped", "dead_letter") for s in run.step_results)
            else "failed"
        )
        if run.step_results:
            errors = [s.get("error", "") for s in run.step_results if s.get("status") == "failed" and s.get("error")]
            if errors:
                run.error = "; ".join(errors)
        self._persist_run(run)
        # I5: EventBus 事件传播
        self._emit_workflow_event(
            f"workflow.{run.status}",
            {
                "run_id": run.run_id,
                "name": run.workflow_name,
                "steps_completed": run.completed_steps,
                "status": run.status,
            },
        )
        logger.info(
            "workflow_finished", name=wf.name, run_id=run.run_id, status=run.status, steps=len(run.step_results)
        )

    async def _execute_step(self, step, args: dict, *, pipeline_context: dict | None = None) -> dict:
        """执行单个 agent step → spawn_agent V3"""
        from src.engine.feature.flags import is_enabled

        role = step.opts.get("role", "butler")

        if is_enabled("sub_agent_spawn"):
            try:
                from src.engine.agent.sub_agent import CacheSafeParams, spawn_agent

                cache_params = CacheSafeParams.from_parent(
                    parent_agent="workflow",
                    permission_level="write",
                )
                result = await spawn_agent(
                    parent_agent="workflow",
                    role=role,
                    task=step.prompt,
                    context=args,
                    max_turns=step.opts.get("max_turns", 3),
                    cache_safe_params=cache_params,
                    scratchpad_dir=args.get("scratchpad_dir", ""),
                    on_progress=args.get("on_progress"),
                    cancel_event=args.get("cancel_event"),
                )
                return {"result": result.get("result", result.get("response", str(result)))}
            except Exception as e:
                logger.warning("workflow_spawn_v3_failed_fallback", error=str(e), exc_info=True)

        # Fallback: router.chat (无工具，纯对话)
        try:
            from src.engine.llm.router import get_llm_router

            router = get_llm_router()
            resp = await router.chat(
                [{"role": "user", "content": step.prompt}],
                profile="fast",
                max_tokens=2000,
            )
            return {"result": resp.get("content", "")}
        except Exception as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)
            return {"result": f"Step failed: {e}"}

    # ── 断点续跑 ──

    async def resume(self, run_id: str, previous_run: WorkflowRun | None = None) -> WorkflowRun | None:
        """恢复未完成的run: 跳过已完成的step，从第一个failed/pending处重跑"""
        run = previous_run or self._runs.get(run_id)
        if not run:
            return None
        completed = [s for s in run.step_results if s.get("status") == "completed"]
        pending = [s for s in run.step_results if s.get("status") != "completed"]
        logger.info("workflow_resumed", run_id=run_id, completed=len(completed), pending=len(pending))
        # 标记pending步骤重跑（实际重跑需重新传入脚本，此处记录意图）
        run.status = "paused" if pending else "completed"
        self._runs[run_id] = run
        return run

    def get_run(self, run_id: str) -> WorkflowRun | None:
        """获取运行记录 — 先查内存再查DB"""
        run = self._runs.get(run_id)
        if run:
            return run
        return self._load_run(run_id)

    def list_runs(self) -> list[dict]:
        """列出所有运行记录 — 内存+DB合并"""
        from src.engine.workflow.models import WORKFLOW_RUN_DDL

        result = {
            r.run_id: {
                "run_id": r.run_id,
                "name": r.workflow_name,
                "status": r.status,
                "steps": r.total_steps,
                "completed": r.completed_steps,
            }
            for r in self._runs.values()
        }
        # 补充 DB 中内存没有的记录
        if self._cm:
            try:
                with self._cm.get_conn() as conn:
                    conn.execute(WORKFLOW_RUN_DDL.split(";")[0])
                    rows = conn.execute(
                        "SELECT run_id, workflow_name, status, total_steps, completed_steps FROM workflow_runs ORDER BY updated_at DESC"
                    ).fetchall()
                    for row in rows:
                        rid = row["run_id"]
                        if rid not in result:
                            result[rid] = {
                                "run_id": rid,
                                "name": row["workflow_name"],
                                "status": row["status"],
                                "steps": row["total_steps"],
                                "completed": row["completed_steps"],
                            }
            except Exception as e:
                logger.debug("workflow_list_runs_db_failed", error=str(e))
        return list(result.values())

    # ── 运行时键值存储 ──

    def store_set(self, run_id: str, key: str, value: Any) -> None:
        run = self._runs.get(run_id)
        if run:
            run._store[key] = value

    def store_get(self, run_id: str, key: str, default: Any = None) -> Any:
        run = self._runs.get(run_id)
        if run:
            return run._store.get(key, default)
        return default

    # ── 脚本持久化 ──

    def persist_script(self, wf, source: str) -> str:
        """持久化脚本到session目录, 返回路径"""
        name = getattr(wf, "name", "workflow")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        path = self._session_dir / f"{safe_name}.js"
        path.write_text(source, encoding="utf-8")
        logger.info("workflow_script_persisted", path=str(path))
        return str(path)

    def load_script(self, path: str) -> Any:
        """从持久化路径加载脚本"""
        from src.engine.workflow.dsl import parse_workflow_script

        source = Path(path).read_text(encoding="utf-8")
        return parse_workflow_script(source)
