
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge PDCA引擎 — 工作流执行核心

职责:
  - 创建工作流 (从模板/手工)
  - 推进阶段 (Plan→Do→Check→Act)
  - 执行步骤 (分发到Agent)
  - 阶段完成检查
  - PDCA循环 (Act结束后可自动开始下一轮)
  - 审批门禁 (步骤/阶段需审批才能推进)
  - 截止时间 (步骤超时自动标记失败)

实现拆分到4个Mixin模块:
  - creation.py  — 工作流创建与阶段构建
  - execution.py — 工作流执行控制 (启动/推进/暂停/自动运行)
  - phase_ops.py — 阶段操作 (审批/重试/截止时间)
  - step_ops.py  — 步骤操作 (执行/审批/拒绝/失败/LLM Agent)
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.engine.workflow.creation import CreationMixin
from src.engine.workflow.execution import ExecutionMixin
from src.engine.workflow.models import (
    STEP_LOG_DDL,
    WORKFLOW_DDL,
    Phase,
    PhaseType,
    Step,
    StepStatus,
    Workflow,
    WorkflowStatus,
    validate_workflow_transition,
)
from src.engine.workflow.phase_ops import PhaseOpsMixin
from src.engine.workflow.step_ops import StepOpsMixin
from src.exceptions import ValidationError
from src.infra.database.base_manager import BaseManager

if TYPE_CHECKING:
    from src.engine.workflow.event_store import WorkflowEvent
    from src.infra.database.connection import ConnectionManager

logger = structlog.get_logger(__name__)


class WorkflowManager(BaseManager):
    """工作流持久化"""

    table_name = "workflows"
    model_class = Workflow
    ddl = WORKFLOW_DDL
    columns = [
        "id",
        "name",
        "description",
        "status",
        "phases_json",
        "current_phase",
        "template_id",
        "metadata",
        "graph_dsl",
        "store_json",
        "created_at",
        "updated_at",
    ]
    json_columns = {"phases_json", "metadata", "store_json"}
    enum_columns = {"status": WorkflowStatus}
    datetime_columns = {"created_at", "updated_at"}
    default_json_values = {"phases_json": [], "metadata": {}, "store_json": {}}

    def _model_to_values(self, item: Workflow) -> tuple:
        values = []
        for col in self.columns:
            if col == "phases_json":
                values.append(
                    json.dumps(
                        [p.model_dump() for p in item.phases],
                        ensure_ascii=False,
                        default=str,
                    )
                )
            elif col == "metadata":
                values.append(json.dumps(item.metadata_, ensure_ascii=False))
            elif col == "store_json":
                values.append(json.dumps(item.store, ensure_ascii=False))
            elif col == "created_at" and isinstance(item.created_at, datetime):
                values.append(item.created_at.isoformat())
            elif col == "updated_at" and isinstance(item.updated_at, datetime):
                values.append(item.updated_at.isoformat())
            else:
                val = getattr(item, col, None)
                values.append(val)
        return tuple(values)

    def _row_to_model(self, row: Any) -> Workflow:
        data = {}
        for col in self.columns:
            try:
                val = row[col]
            except (KeyError, IndexError):
                # Column may not exist in DB yet (e.g. after ALTER TABLE migration)
                continue
            if col == "phases_json" and isinstance(val, str):
                phases_data = json.loads(val) if val else []
                data["phases"] = [Phase(**p) for p in phases_data]
            elif col == "metadata" and isinstance(val, str):
                data["metadata_"] = json.loads(val) if val else {}
            elif col == "store_json" and isinstance(val, str):
                data["store"] = json.loads(val) if val else {}
            elif col in ("created_at", "updated_at") and isinstance(val, str):
                data[col] = datetime.fromisoformat(val)
            else:
                data[col] = val
        return Workflow(**data)


class StepLogManager(BaseManager):
    """步骤执行日志"""

    table_name = "workflow_step_logs"
    model_class = Step
    ddl = STEP_LOG_DDL
    columns = [
        "id",
        "workflow_id",
        "step_id",
        "phase_type",
        "name",
        "agent_role",
        "action",
        "result",
        "status",
        "metadata",
        "started_at",
        "finished_at",
        "created_at",
    ]
    json_columns = {"metadata"}
    enum_columns = {"phase_type": PhaseType, "status": StepStatus}

    def insert_log(
        self,
        wf_id: str,
        step: Step,
        phase_type: PhaseType,
    ) -> str:
        """插入步骤执行日志 — 封装SQL在Manager层

        Args:
            wf_id: 工作流ID
            step: 步骤对象
            phase_type: 阶段类型

        Returns:
            日志记录ID
        """
        import uuid as _uuid
        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        log_id = str(_uuid.uuid4())
        now = _dt.now(_UTC).isoformat()
        metadata_json = json.dumps(
            {"workflow_id": wf_id, "step_id": step.id, "phase_type": phase_type.value},
            ensure_ascii=False,
        )
        with self._cm.get_conn() as conn:
            conn.execute(
                f"INSERT INTO {self._safe_table()} "
                "(id, workflow_id, step_id, phase_type, name, agent_role, "
                "action, result, status, metadata, started_at, finished_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    log_id,
                    wf_id,
                    step.id,
                    phase_type.value,
                    step.name,
                    step.agent_role,
                    step.action,
                    step.result or "",
                    step.status.value,
                    metadata_json,
                    step.started_at or now,
                    step.finished_at or now,
                    now,
                ),
            )
            conn.commit()
        return log_id


class PDCAEngine(CreationMixin, ExecutionMixin, PhaseOpsMixin, StepOpsMixin):
    """PDCA工作流引擎"""

    def __init__(self, cm: ConnectionManager) -> None:
        self._cm = cm
        self._wf_mgr = WorkflowManager(cm)
        self._log_mgr = StepLogManager(cm)
        self._approval_engine = None  # 懒加载: 通过approval_engine属性访问
        self._event_mgr = None  # 懒加载: 通过event_mgr属性访问
        self._checkpoint_mgr = None  # 懒加载: 通过checkpoint_mgr属性访问
        self._lazy_lock = threading.Lock()  # 保护懒加载属性的双重检查锁

    @property
    def approval_engine(self):
        """懒加载审批引擎 (线程安全双重检查锁)"""
        if self._approval_engine is None:
            with self._lazy_lock:
                if self._approval_engine is None:
                    from src.engine.approval.engine import ApprovalFlowEngine
                    from src.engine.approval.models import ApprovalManager

                    mgr = ApprovalManager(self._cm)
                    mgr.initialize()
                    self._approval_engine = ApprovalFlowEngine(mgr)
        return self._approval_engine

    @property
    def event_mgr(self):
        """懒加载工作流事件管理器 (线程安全双重检查锁)"""
        if self._event_mgr is None:
            with self._lazy_lock:
                if self._event_mgr is None:
                    from src.engine.workflow.event_store import WorkflowEventManager

                    self._event_mgr = WorkflowEventManager(self._cm)
                    self._event_mgr.initialize()
        return self._event_mgr

    @property
    def checkpoint_mgr(self):
        """懒加载检查点管理器 (线程安全双重检查锁)"""
        if self._checkpoint_mgr is None:
            with self._lazy_lock:
                if self._checkpoint_mgr is None:
                    from src.engine.workflow.event_store import CheckpointManager

                    self._checkpoint_mgr = CheckpointManager(self._cm)
                    self._checkpoint_mgr.initialize()
        return self._checkpoint_mgr

    def initialize(self) -> None:
        self._wf_mgr.initialize()
        self._log_mgr.initialize()

    def get_workflow(self, wf_id: str) -> Workflow | None:
        return self._wf_mgr.get(wf_id)

    def pause_workflow(self, wf_id: str) -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        validate_workflow_transition(wf.status, WorkflowStatus.PAUSED)
        wf.status = WorkflowStatus.PAUSED
        self._save(wf, event_type="paused")
        logger.info("workflow_paused", id=wf_id)
        return wf

    def cancel_workflow(self, wf_id: str) -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        validate_workflow_transition(wf.status, WorkflowStatus.CANCELLED)
        wf.status = WorkflowStatus.CANCELLED
        self._save(wf, event_type="cancelled")
        logger.info("workflow_cancelled", id=wf_id)
        return wf

    def list_workflows(
        self,
        status: WorkflowStatus | None = None,
        limit: int = 50,
        summary: bool = False,
    ) -> list[Workflow]:
        filters = {}
        if status:
            filters["status"] = status
        # 摘要模式：排除 phases_json/graph_dsl/metadata 大字段
        columns = None
        if summary:
            columns = [
                "id",
                "name",
                "description",
                "status",
                "current_phase",
                "template_id",
                "created_at",
                "updated_at",
            ]
        return self._wf_mgr.list_items(filters=filters, order_by="created_at DESC", limit=limit, columns=columns)

    def compile_graph(self, wf_id: str) -> Workflow:
        """将已保存的 Graph DSL 编译为 PDCA phases 并更新工作流

        流程:
          1. 读取工作流的 graph_dsl 字段
          2. 调用 graph_compiler.compile_graph_to_pdca() 编译
          3. 用编译结果替换工作流的 phases
          4. 持久化保存
        """
        from src.engine.workflow.graph_compiler import compile_graph_to_pdca

        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        if not wf.graph_dsl:
            raise ValidationError("Graph DSL 为空，无法编译", code="GRAPH_DSL_EMPTY")

        compiled = compile_graph_to_pdca(
            graph_dsl=wf.graph_dsl,
            workflow_name=wf.name,
            workflow_description=wf.description,
        )

        # 用编译后的 phases 替换原始 phases
        wf.phases = compiled.phases
        wf.updated_at = datetime.now(UTC)
        self._save(
            wf,
            event_type="graph_compiled",
            payload={"phase_count": len(wf.phases), "step_count": sum(len(p.steps) for p in wf.phases)},
        )

        logger.info(
            "graph_compiled_to_pdca",
            wf_id=wf_id,
            phase_count=len(wf.phases),
            step_count=sum(len(p.steps) for p in wf.phases),
        )
        return wf

    def store_set(self, wf_id: str, key: str, value: Any) -> Workflow:
        """设置工作流运行时KV变量（条件分支使用，不持久化）"""
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        wf.store[key] = value
        self._save(wf, event_type="store_updated", payload={"key": key})
        logger.debug("workflow_store_set", wf_id=wf_id, key=key)
        return wf

    def recover_workflow(self, wf_id: str) -> Workflow:
        """从最新检查点 + 重放事件恢复工作流状态

        流程:
          1. 读取最新 Checkpoint (快照)
          2. 从 Checkpoint 恢复 Workflow 对象
          3. 读取 Checkpoint 之后的事件，重放到 Workflow
          4. 返回恢复后的 Workflow
        """
        if not self._is_event_sourcing_enabled():
            raise ValidationError("事件溯源功能未启用", code="EVENT_SOURCING_DISABLED")

        cp = self.checkpoint_mgr.get_latest(wf_id)
        if cp is None:
            # 无检查点，从事件从头重建
            events = self.event_mgr.list_events(wf_id)
            if not events:
                # 无事件，回退到 DB 当前状态
                wf = self._wf_mgr.get(wf_id)
                if wf is None:
                    raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
                return wf
            # 最早事件应该是 created，从 DB 读初始状态
            wf = self._wf_mgr.get(wf_id)
            if wf is None:
                raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
            logger.info("workflow_recover_from_events", wf_id=wf_id, event_count=len(events))
            return wf

        # 从检查点快照恢复
        from src.engine.workflow.event_store import WorkflowEventType

        wf = Workflow.model_validate_json(cp.snapshot)
        # 重放检查点时间点及之后的事件（用 >= 确保不遗漏同毫秒事件）
        events = self.event_mgr.get_events_since(wf_id, cp.created_at)
        # 过滤元事件（checkpoint_saved 不影响状态）和已纳入快照的 created/started 事件
        replayable = [
            e for e in events if e.event_type not in (WorkflowEventType.CHECKPOINT_SAVED, WorkflowEventType.CREATED)
        ]
        for evt in replayable:
            self._apply_event(wf, evt)
        logger.info("workflow_recovered", wf_id=wf_id, checkpoint_id=cp.id, replayed_events=len(replayable))
        return wf

    def _apply_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """重放单个事件到 Workflow 对象（仅内存，不持久化）

        采用策略分发：按事件类型查表调用对应的 _apply_xxx_event 子方法，
        主函数仅负责分发，不承载具体业务逻辑。
        """
        from src.engine.workflow.event_store import WorkflowEventType

        # 事件类型 → 处理函数的分发表（策略模式）
        handlers = {
            WorkflowEventType.STARTED: self._apply_started_event,
            WorkflowEventType.PAUSED: self._apply_paused_event,
            WorkflowEventType.CANCELLED: self._apply_cancelled_event,
            WorkflowEventType.COMPLETED: self._apply_completed_event,
            WorkflowEventType.PHASE_ADVANCED: self._apply_phase_advanced_event,
            WorkflowEventType.STEP_EXECUTED: self._apply_step_executed_event,
            WorkflowEventType.STEP_APPROVED: self._apply_step_approved_event,
            WorkflowEventType.STEP_REJECTED: self._apply_step_rejected_event,
            WorkflowEventType.STEP_SKIPPED: self._apply_step_skipped_event,
            WorkflowEventType.STEP_FAILED: self._apply_step_failed_event,
            WorkflowEventType.STORE_UPDATED: self._apply_store_updated_event,
            WorkflowEventType.GRAPH_COMPILED: self._apply_graph_compiled_event,
        }
        handler = handlers.get(evt.event_type)
        if handler is not None:
            handler(wf, evt)

    # ── 事件处理子方法（每个仅处理单一事件类型，复杂度均 ≤10）──

    def _apply_started_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STARTED: 工作流进入运行态"""
        wf.status = WorkflowStatus.RUNNING

    def _apply_paused_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """PAUSED: 工作流暂停"""
        wf.status = WorkflowStatus.PAUSED

    def _apply_cancelled_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """CANCELLED: 工作流取消"""
        wf.status = WorkflowStatus.CANCELLED

    def _apply_completed_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """COMPLETED: 工作流完成"""
        wf.status = WorkflowStatus.COMPLETED

    def _apply_phase_advanced_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """PHASE_ADVANCED: 推进当前阶段索引"""
        wf.current_phase = evt.payload.get("current_phase", wf.current_phase)

    def _apply_step_executed_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STEP_EXECUTED: 步骤执行完成或审批挂起"""
        step = self._find_step(wf, evt.payload.get("step_id", ""))
        if step is None:
            return
        # payload status="approval_pending" 表示审批挂起，否则视为完成
        if evt.payload.get("status") == StepStatus.APPROVAL_PENDING.value:
            step.status = StepStatus.APPROVAL_PENDING
        else:
            step.status = StepStatus.DONE
        step.result = evt.payload.get("result", step.result or "")
        step.finished_at = evt.payload.get("finished_at", step.finished_at or "")

    def _apply_step_approved_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STEP_APPROVED: 步骤审批通过"""
        step = self._find_step(wf, evt.payload.get("step_id", ""))
        if step is None:
            return
        step.status = StepStatus.DONE
        step.result = evt.payload.get("result", step.result or "")
        step.finished_at = evt.payload.get("finished_at", step.finished_at or "")

    def _apply_step_rejected_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STEP_REJECTED: 步骤审批拒绝"""
        step = self._find_step(wf, evt.payload.get("step_id", ""))
        if step is None:
            return
        step.status = StepStatus.FAILED
        step.result = evt.payload.get("result", step.result or "")
        step.finished_at = evt.payload.get("finished_at", step.finished_at or "")

    def _apply_step_skipped_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STEP_SKIPPED: 步骤跳过"""
        step = self._find_step(wf, evt.payload.get("step_id", ""))
        if step is None:
            return
        step.status = StepStatus.SKIPPED
        step.result = evt.payload.get("result", step.result or "")
        step.finished_at = evt.payload.get("finished_at", step.finished_at or "")

    def _apply_step_failed_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STEP_FAILED: 步骤失败"""
        step = self._find_step(wf, evt.payload.get("step_id", ""))
        if step is None:
            return
        step.status = StepStatus.FAILED
        step.result = evt.payload.get("result", step.result or "")
        step.finished_at = evt.payload.get("finished_at", step.finished_at or "")

    def _apply_store_updated_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """STORE_UPDATED: 更新运行时KV变量"""
        key = evt.payload.get("key", "")
        if key:
            wf.store[key] = evt.payload.get("value")

    def _apply_graph_compiled_event(self, wf: Workflow, evt: WorkflowEvent) -> None:
        """GRAPH_COMPILED: 图编译后 phases 变化较复杂，从快照恢复更可靠，此处不处理"""

    def _find_step(self, wf: Workflow, step_id: str) -> Step | None:
        """根据 step_id 在所有阶段中查找步骤，未找到返回 None"""
        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    return step
        return None

    def store_get(self, wf_id: str, key: str, default: Any = None) -> Any:
        """获取工作流运行时KV变量"""
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        return wf.store.get(key, default)

    def store_get_all(self, wf_id: str) -> dict[str, Any]:
        """获取工作流全部运行时KV变量"""
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        return dict(wf.store)

    def _auto_advance_if_allowed(self, wf: Workflow) -> Workflow:
        """自动推进工作流（编排：记录失败 → 失败策略 → 审批 → 推进）"""
        if wf.status != WorkflowStatus.RUNNING:
            return wf
        current_phase = wf.phases[wf.current_phase] if wf.current_phase < len(wf.phases) else None
        if current_phase is None:
            return wf

        self._record_failed_steps_if_advancing(wf, current_phase)

        has_failed = any(s.status == StepStatus.FAILED for s in current_phase.steps)
        if has_failed:
            result = self._dispatch_phase_failure_strategy(wf, current_phase)
            if result is not None:
                return result

        if current_phase.requires_approval and current_phase.status != StepStatus.APPROVAL_PENDING:
            return self._submit_phase_approval(wf, current_phase)
        if current_phase.requires_approval:
            return wf
        with contextlib.suppress(ValueError):
            wf = self.advance_phase(wf.id, auto_loop=True)
        return wf

    def _record_failed_steps_if_advancing(self, wf: Workflow, current_phase: Phase) -> None:
        """P1-1 FIX: 阶段内有失败步骤且 on_failure='advance' 时，记录警告和失败结果"""
        failed_steps = [s for s in current_phase.steps if s.status == StepStatus.FAILED]
        if not failed_steps or current_phase.on_failure != "advance":
            return
        logger.warning(
            "phase_has_failures_but_advancing",
            workflow_id=wf.id,
            phase_id=current_phase.id,
            failed_steps=[s.id for s in failed_steps],
            message="Phase has failures but on_failure='advance', failures will be recorded",
        )
        if not hasattr(wf, "failed_steps"):
            object.__setattr__(wf, "failed_steps", [])
        for s in failed_steps:
            wf.failed_steps.append(
                {
                    "step_id": s.id,
                    "step_name": s.name,
                    "result": s.result or "Unknown failure",
                }
            )

    def _dispatch_phase_failure_strategy(self, wf: Workflow, current_phase: Phase) -> Workflow | None:
        """按 on_failure 策略分发处理（retry_self/halt/retry_plan），返回非None表示已处理"""
        handlers = {
            "retry_self": self._handle_retry_self_failure,
            "halt": self._handle_halt_failure,
            "retry_plan": self._handle_retry_plan_failure,
        }
        handler = handlers.get(current_phase.on_failure)
        if handler is None:
            return None
        return handler(wf, current_phase)

    def _handle_retry_self_failure(self, wf: Workflow, current_phase: Phase) -> Workflow:
        """retry_self 策略: 重置步骤状态以重新执行，受 max_retries 上限保护"""
        # FIX-002: 重试计数器防护无限重试
        if current_phase.max_retries > 0 and current_phase.retry_count >= current_phase.max_retries:
            current_phase.status = StepStatus.FAILED
            wf.status = WorkflowStatus.PAUSED
            self._save(
                wf,
                event_type="phase_retry_exhausted",
                payload={"phase": current_phase.phase_type.value, "retry_count": current_phase.retry_count},
            )
            logger.warning(
                "phase_retry_exhausted",
                wf_id=wf.id,
                phase=current_phase.phase_type.value,
                retry_count=current_phase.retry_count,
            )
            return wf
        current_phase.retry_count += 1
        for s in current_phase.steps:
            s.status = StepStatus.PENDING
            s.result = ""
            s.finished_at = ""
            s.started_at = ""
        self._save(
            wf,
            event_type="phase_advanced",
            payload={
                "action": "retry_self",
                "phase": current_phase.phase_type.value,
                "retry_count": current_phase.retry_count,
            },
        )
        return wf  # retry_self: 重置步骤后返回，等待重新执行

    def _handle_halt_failure(self, wf: Workflow, current_phase: Phase) -> Workflow:
        """halt 策略: 暂停工作流"""
        wf.status = WorkflowStatus.PAUSED
        self._save(
            wf,
            event_type="paused",
            payload={"reason": "phase_failure_halt", "phase": current_phase.phase_type.value},
        )
        logger.info("phase_halted", wf_id=wf.id, phase=current_phase.phase_type.value)
        return wf

    def _handle_retry_plan_failure(self, wf: Workflow, current_phase: Phase) -> Workflow:
        """retry_plan 策略: 回退到 PLAN 阶段重试"""
        target_idx = self._find_phase_index(wf, PhaseType.PLAN)
        if target_idx is not None:
            return self.retry_phase(wf.id, target_idx)
        self._save(
            wf,
            event_type="step_failed",
            payload={"reason": "phase_failure_retry_plan_fallback", "phase": current_phase.phase_type.value},
        )
        return wf

    def _submit_phase_approval(self, wf: Workflow, current_phase: Phase) -> Workflow:
        """提交阶段级审批并挂起"""
        current_phase.status = StepStatus.APPROVAL_PENDING
        self._save(
            wf,
            event_type="step_executed",
            payload={"action": "phase_approval_pending", "phase": current_phase.phase_type.value},
        )
        logger.info("phase_awaiting_approval", wf_id=wf.id, phase=current_phase.phase_type.value)
        # 阶段级审批提交审批记录
        try:
            self.approval_engine.submit_approval(
                target_type="phase",
                target_id=str(wf.current_phase),
                workflow_id=wf.id,
                title=f"阶段审批: {current_phase.effective_name()}",
                description=f"阶段 {current_phase.phase_type.value} 完成等待审批",
            )
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError):
            logger.warning("phase_approval_submit_failed", wf_id=wf.id, exc_info=True)
        return wf

    def _notify_event(self, wf: Workflow, event: str) -> None:
        try:
            import asyncio

            from src.engine.channel.notifier import notify_workflow_event

            phase_name = (
                wf.phases[wf.current_phase - 1].effective_name()
                if wf.current_phase > 0 and wf.current_phase <= len(wf.phases)
                else ""
            )
            detail = f"阶段: {phase_name}" if phase_name else ""
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(notify_workflow_event(wf.name, event, detail))
            except RuntimeError:
                logger.debug("workflow_notify_no_event_loop")
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError) as e:
            logger.debug("workflow_notify_failed", error=str(e), exc_info=True)

    def _maybe_learn_from_step(self, step: Step) -> None:
        if not step.result or step.status != StepStatus.DONE:
            return
        try:
            from src.engine.prompt import get_prompt_learner

            learner = get_prompt_learner()
            learner.learn_and_save(
                user_message=step.action,
                assistant_reply=step.result,
                agent_role=step.agent_role,
                signals={"task_completed": True, "task_success": True},
            )
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError) as e:
            logger.debug("step_learn_failed", step_id=step.id, error=str(e), exc_info=True)

    def _ws_broadcast(self, wf_id: str, event_type: str, payload: dict[str, Any]) -> None:
        try:
            import asyncio

            from src.infra.websocket.manager import get_ws_manager

            ws = get_ws_manager()
            room = f"workflow:{wf_id}"

            async def _do_broadcast() -> None:
                await ws.broadcast(event_type, payload, room=room)

            try:
                loop = asyncio.get_running_loop()
                # Already inside async context — schedule without blocking
                loop.create_task(_do_broadcast())
            except RuntimeError:
                # No running event loop — create a temporary one for this fire-and-forget call
                from src.infra.async_utils import run_async

                run_async(_do_broadcast())
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError) as e:
            logger.debug("ws_broadcast_failed", event=event_type, error=str(e), exc_info=True)

    def _save(self, wf: Workflow, event_type: str | None = None, payload: dict[str, Any] | None = None) -> None:
        wf.updated_at = datetime.now(UTC)
        self._wf_mgr.update_fields(
            wf.id,
            status=wf.status.value,
            phases_json=json.dumps([p.model_dump() for p in wf.phases], ensure_ascii=False, default=str),
            current_phase=wf.current_phase,
            updated_at=wf.updated_at.isoformat(),
        )
        # ── 事件溯源 (feature flag 守护) ──
        if event_type and self._is_event_sourcing_enabled():
            from src.engine.workflow.event_store import WorkflowEvent, WorkflowEventType

            try:
                et = WorkflowEventType(event_type)
            except ValueError:
                et = None
            if et:
                evt = WorkflowEvent(
                    workflow_id=wf.id,
                    event_type=et,
                    payload=payload or {},
                )
                try:
                    self.event_mgr.append(evt)
                except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError):
                    logger.debug("workflow_event_append_failed", wf_id=wf.id, event_type=event_type, exc_info=True)

                # 自动检查点策略：阶段推进 或 完成时 创建检查点
                if et in (
                    WorkflowEventType.PHASE_ADVANCED,
                    WorkflowEventType.COMPLETED,
                    WorkflowEventType.CHECKPOINT_SAVED,
                ):
                    self._maybe_create_checkpoint(wf)

    def _is_event_sourcing_enabled(self) -> bool:
        """检查事件溯源 feature flag"""
        try:
            from src.engine.feature.flags import is_enabled

            return is_enabled("workflow_event_sourcing")
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError):
            return False

    def _maybe_create_checkpoint(self, wf: Workflow) -> None:
        """创建自动检查点"""
        from src.engine.workflow.event_store import Checkpoint

        try:
            event_count = self.event_mgr.count_events(wf.id)
            cp = Checkpoint(
                workflow_id=wf.id,
                phase_index=wf.current_phase,
                snapshot=wf.model_dump_json(),
                event_count=event_count,
            )
            self.checkpoint_mgr.create(cp)
            logger.info("workflow_checkpoint_auto_created", wf_id=wf.id, phase=wf.current_phase, events=event_count)
            # 同时发射检查点事件
            self._save_event_only(wf.id, "checkpoint_saved", {"checkpoint_id": cp.id, "phase_index": wf.current_phase})
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError):
            logger.debug("checkpoint_create_failed", wf_id=wf.id, exc_info=True)

    def _save_event_only(self, wf_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """仅追加事件，不触发保存/检查点（避免递归）"""
        if not self._is_event_sourcing_enabled():
            return
        from src.engine.workflow.event_store import WorkflowEvent, WorkflowEventType

        try:
            et = WorkflowEventType(event_type)
        except ValueError:
            return
        try:
            evt = WorkflowEvent(workflow_id=wf_id, event_type=et, payload=payload or {})
            self.event_mgr.append(evt)
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError):
            logger.debug("workflow_event_only_failed", wf_id=wf_id, event_type=event_type, exc_info=True)

    def _log_step(self, wf_id: str, step: Step, phase_type: PhaseType) -> None:
        """记录步骤执行日志 — 委托给 StepLogManager"""
        self._log_mgr.insert_log(wf_id, step, phase_type)


from src.infra.singleton import Singleton


def _init_pdca_engine() -> PDCAEngine:
    from src.infra.database.connection import get_connection_manager

    cm = get_connection_manager()
    engine = PDCAEngine(cm)
    engine.initialize()
    return engine


_pdca_engine = Singleton(_init_pdca_engine)


def get_pdca_engine(cm: ConnectionManager | None = None) -> PDCAEngine:
    return _pdca_engine.get()


def reset_pdca_engine() -> None:
    _pdca_engine.reset()
