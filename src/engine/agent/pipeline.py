
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PipelineEngine — Agent 管道流引擎

职责: 管道的创建/更新/删除/执行
管道=步骤序列, 每步=agent_id+描述, 按序执行
"""

from __future__ import annotations

import json
import uuid

import structlog

from src.engine.agent._pipeline_helpers import _now, row_to_pipeline, row_to_run
from src.infra.database.connection import get_connection_manager
from src.infra.database.sql_safe import safe_column_name, safe_table_name

logger = structlog.get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


from src.engine.agent.pipeline_defaults import BUILTIN_PIPELINES
from src.exceptions import AgentError


class PipelineEngine:
    """管道流管理器 — 无状态，每次调用通过 conn 操作"""

    def list_pipelines(self, department: str = "") -> list[dict]:
        """列出管道，可按部门过滤"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            if department:
                rows = conn.execute(
                    "SELECT id, name, department, description, steps, is_builtin, enabled "
                    "FROM agent_pipelines WHERE department = ? ORDER BY created_at",
                    (department,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, department, description, steps, is_builtin, enabled "
                    "FROM agent_pipelines ORDER BY department, created_at"
                ).fetchall()
            result = []
            for r in rows:
                result.append(row_to_pipeline(r))
            conn.rollback()  # 结束只读隐式事务，释放锁
            return result

    def get_pipeline(self, pipeline_id: str) -> dict | None:
        """获取单条管道"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, department, description, steps, is_builtin, enabled "
                "FROM agent_pipelines WHERE id = ?",
                (pipeline_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.rollback()  # 结束只读隐式事务，释放锁
            return row_to_pipeline(row)

    def create_pipeline(
        self,
        name: str,
        department: str,
        steps: list[dict],
        description: str = "",
    ) -> dict:
        """创建自定义管道"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rid = _gen_id()
            now = _now()
            steps_json = json.dumps(steps, ensure_ascii=False)
            conn.execute(
                "INSERT INTO agent_pipelines (id, name, department, description, steps, is_builtin, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)",
                (rid, name, department, description, steps_json, now, now),
            )
            conn.commit()
            return {"id": rid, "name": name, "department": department}

    def update_pipeline(
        self,
        pipeline_id: str,
        *,
        name: str = "",
        description: str = "",
        steps: list[dict] | None = None,
        enabled: bool | None = None,
    ) -> dict | None:
        """更新管道"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, name, department, description, steps, is_builtin, enabled "
                "FROM agent_pipelines WHERE id = ?",
                (pipeline_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            sets, vals = [], []
            if name:
                sets.append(f"{safe_column_name('name')} = ?")
                vals.append(name)
            if description:
                sets.append(f"{safe_column_name('description')} = ?")
                vals.append(description)
            if steps is not None:
                sets.append(f"{safe_column_name('steps')} = ?")
                vals.append(json.dumps(steps, ensure_ascii=False))
            if enabled is not None:
                sets.append(f"{safe_column_name('enabled')} = ?")
                vals.append(int(enabled))
            if not sets:
                return self.get_pipeline(pipeline_id)
            sets.append(f"{safe_column_name('updated_at')} = ?")
            vals.append(_now())
            vals.append(pipeline_id)
            conn.execute(f"UPDATE {safe_table_name('agent_pipelines')} SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()
            return self.get_pipeline(pipeline_id)

    def delete_pipeline(self, pipeline_id: str) -> bool:
        """删除管道 (内置管道不可删)"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT is_builtin FROM agent_pipelines WHERE id = ?", (pipeline_id,)).fetchone()
            if not row:
                conn.rollback()
                return False
            if row["is_builtin"]:
                conn.rollback()
                raise AgentError("内置管道不可删除")
            conn.execute("DELETE FROM agent_pipelines WHERE id = ?", (pipeline_id,))
            conn.commit()
            return True

    def _get_enabled_pipeline(self, pipeline_id: str) -> dict:
        """获取管道并校验存在性 + 启用状态"""
        pipeline = self.get_pipeline(pipeline_id)
        if not pipeline:
            raise AgentError(f"管道 {pipeline_id} 不存在")
        if not pipeline["enabled"]:
            raise AgentError(f"管道 {pipeline_id} 已停用")
        return pipeline

    def _try_resume_run(self, cm, run_id: str | None, context: dict | None):
        """断点续跑: 检查是否有 partial 状态的 run_id

        返回 (results, resume_from, ctx) 或 None（无 run_id 或无 partial 记录）
        """
        if not run_id:
            return None
        with cm.get_conn() as conn:
            row = conn.execute(
                "SELECT id, pipeline_id, pipeline_name, department, steps_total, "
                "steps_done, status, context, results, started_at, completed_at "
                "FROM pipeline_runs WHERE id = ? AND status = 'partial'",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            results = json.loads(row["results"] or "[]")
            resume_from = len(results)
            ctx = json.loads(row["context"] or "{}")
            if context:
                ctx.update(context)
            conn.rollback()
        return results, resume_from, ctx

    def _create_new_run(self, cm, run_id: str, pipeline_id: str, pipeline: dict, ctx: dict, now: str) -> None:
        """创建新的 pipeline_runs 记录"""
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO pipeline_runs (id, pipeline_id, pipeline_name, department, steps_total, steps_done, status, context, started_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 'running', ?, ?)",
                (
                    run_id,
                    pipeline_id,
                    pipeline["name"],
                    pipeline["department"],
                    len(pipeline["steps"]),
                    json.dumps(ctx, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()

    @staticmethod
    def _build_pass_ctx(ctx: dict, results: list[dict]) -> dict:
        """从 ctx 和已有 results 构建 pass_ctx（恢复已完成步骤的输出）"""
        pass_ctx = ctx.copy()
        for r in results:
            if r.get("status") == "completed" and "step_" in str(r.get("note", "")):
                idx_in = results.index(r)
                pass_ctx[f"step_{idx_in}_output"] = r.get("note", "")
        return pass_ctx

    @staticmethod
    def _process_step_result(agent_id: str, label: str, agent_result, idx: int, pass_ctx: dict) -> dict:
        """处理 agent 执行结果，返回 step result dict"""
        if not isinstance(agent_result, dict):
            agent_result = {"success": False, "error": f"Agent returned non-dict: {type(agent_result)}"}
        status = "completed" if agent_result.get("success") else "failed"
        note = agent_result.get("error") or "执行成功"
        if agent_result.get("data"):
            pass_ctx[f"step_{idx}_output"] = agent_result["data"]
        return {"agent_id": agent_id, "label": label, "status": status, "note": note}

    @staticmethod
    def _step_exception_result(agent_id: str, label: str, error: Exception, step_timeout: int) -> dict:
        """处理步骤执行异常，返回 failed result dict"""
        if isinstance(error, TimeoutError):
            logger.warning("pipeline_step_timeout", agent=agent_id, timeout=step_timeout)
            note = f"执行超时(>{step_timeout}s)"
        else:
            logger.warning("pipeline_step_dispatch_failed", agent=agent_id, error=str(error), exc_info=True)
            note = str(error)[:200]
        return {"agent_id": agent_id, "label": label, "status": "failed", "note": note}

    def _execute_step_sync(self, idx, step, pass_ctx, registry, step_timeout, run_async, asyncio) -> dict:
        """执行单个步骤(同步), 返回 result dict"""
        agent_id = step["agent_id"]
        label = step["label"]
        try:
            agent_result = run_async(
                asyncio.wait_for(registry.dispatch(agent_id, label, **pass_ctx), timeout=step_timeout),
                timeout=step_timeout + 10,
            )
            return self._process_step_result(agent_id, label, agent_result, idx, pass_ctx)
        except Exception as e:
            return self._step_exception_result(agent_id, label, e, step_timeout)

    async def _execute_step_async(self, idx, step, pass_ctx, registry, step_timeout, asyncio) -> dict:
        """异步执行单个步骤 (用于并行组)"""
        agent_id = step["agent_id"]
        label = step["label"]
        try:
            agent_result = await asyncio.wait_for(
                registry.dispatch(agent_id, label, **pass_ctx),
                timeout=step_timeout,
            )
            return self._process_step_result(agent_id, label, agent_result, idx, pass_ctx)
        except Exception as e:
            return self._step_exception_result(agent_id, label, e, step_timeout)

    @staticmethod
    def _collect_parallel_group(steps: list[dict], start_idx: int, group: str) -> tuple[list[int], int]:
        """收集同一 parallel_group 的连续步骤索引，返回 (indices, next_idx)"""
        indices: list[int] = []
        idx = start_idx
        while idx < len(steps) and steps[idx].get("parallel_group", "") == group:
            indices.append(idx)
            idx += 1
        return indices, idx

    @staticmethod
    def _checkpoint_run(cm, run_id: str, results: list[dict]) -> None:
        """每步/每组执行后立即 checkpoint，支持断点续跑"""
        done = sum(1 for r in results if r["status"] == "completed")
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE pipeline_runs SET steps_done = ?, results = ?, status = 'partial' WHERE id = ?",
                (done, json.dumps(results, ensure_ascii=False), run_id),
            )
            conn.commit()

    def _run_steps(self, steps, resume_from, pass_ctx, cm, run_id, results):
        """按 parallel_group 分组执行: 同组并行, 异组/无组串行"""
        import asyncio

        from src.engine.agent.specialist_base import get_agent_registry
        from src.infra.async_utils import run_async

        registry = get_agent_registry()
        step_timeout = 120

        idx = resume_from
        while idx < len(steps):
            group = steps[idx].get("parallel_group", "")
            if group:
                # 收集同一 parallel_group 的连续步骤
                group_indices, idx = self._collect_parallel_group(steps, idx, group)
                logger.info(
                    "pipeline_parallel_group",
                    group=group,
                    step_count=len(group_indices),
                )
                # 并行执行整组
                group_coros = [
                    self._execute_step_async(i, steps[i], pass_ctx, registry, step_timeout, asyncio)
                    for i in group_indices
                ]
                group_results = run_async(asyncio.gather(*group_coros), timeout=step_timeout + 30)
                results.extend(group_results)
            else:
                # 串行执行
                result = self._execute_step_sync(
                    idx,
                    steps[idx],
                    pass_ctx,
                    registry,
                    step_timeout,
                    run_async,
                    asyncio,
                )
                results.append(result)
                idx += 1

            # 每步/每组执行后立即checkpoint，支持断点续跑
            self._checkpoint_run(cm, run_id, results)
        return results

    @staticmethod
    def _finalize_run(cm, run_id: str, results: list[dict]) -> tuple[int, str]:
        """最终更新 run 状态，返回 (done, run_status)"""
        done = sum(1 for r in results if r["status"] == "completed")
        run_status = "completed" if done == len(results) else "partial" if done > 0 else "failed"
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE pipeline_runs SET steps_done = ?, status = ?, results = ?, completed_at = ? WHERE id = ?",
                (done, run_status, json.dumps(results, ensure_ascii=False), _now(), run_id),
            )
            conn.commit()
        return done, run_status

    def run_pipeline(self, pipeline_id: str, context: dict | None = None, run_id: str | None = None) -> dict:
        """执行管道 — 支持断点续跑(partial状态自动恢复)"""
        pipeline = self._get_enabled_pipeline(pipeline_id)

        cm = get_connection_manager()
        now = _now()
        ctx = context or {}
        results: list[dict] = []
        resume_from = 0

        # 断点续跑: 检查是否有partial状态的run_id
        resumed = self._try_resume_run(cm, run_id, context)
        if resumed is not None:
            results, resume_from, ctx = resumed
        elif not run_id:
            run_id = _gen_id()
            self._create_new_run(cm, run_id, pipeline_id, pipeline, ctx, now)

        pass_ctx = self._build_pass_ctx(ctx, results)
        results = self._run_steps(pipeline["steps"], resume_from, pass_ctx, cm, run_id, results)
        done, run_status = self._finalize_run(cm, run_id, results)

        return {
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline["name"],
            "steps_executed": len(results),
            "steps_done": done,
            "status": run_status,
            "results": results,
            "context": ctx,
        }

    def list_runs(self, pipeline_id: str = "", limit: int = 20) -> list[dict]:
        """查询管道执行历史"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            if pipeline_id:
                rows = conn.execute(
                    "SELECT id, pipeline_id, pipeline_name, department, steps_total, "
                    "steps_done, status, results, started_at, completed_at "
                    "FROM pipeline_runs WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT ?",
                    (pipeline_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, pipeline_id, pipeline_name, department, steps_total, "
                    "steps_done, status, results, started_at, completed_at "
                    "FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = []
            for r in rows:
                result.append(row_to_run(r))
            conn.rollback()
            return result

    def init_seed(self) -> dict:
        """初始化内置管道种子数据"""
        cm = get_connection_manager()
        with cm.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) as c FROM agent_pipelines").fetchone()["c"]
            if count > 0:
                return {"seeded": False, "reason": f"已有 {count} 条管道记录"}
            now = _now()
            for p in BUILTIN_PIPELINES:
                steps_json = json.dumps(p["steps"], ensure_ascii=False)
                conn.execute(
                    "INSERT OR IGNORE INTO agent_pipelines (id, name, department, description, steps, is_builtin, enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (p["id"], p["name"], p["department"], p["description"], steps_json, p["is_builtin"], now, now),
                )
            conn.commit()
            return {"seeded": True, "count": len(BUILTIN_PIPELINES)}


# ── 单例 ──
_instance: PipelineEngine | None = None


def get_pipeline_engine() -> PipelineEngine:
    global _instance
    if _instance is None:
        _instance = PipelineEngine()
    return _instance
