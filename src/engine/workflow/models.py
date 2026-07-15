
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 工作流数据模型 — PDCA工作流 + 阶段 + 步骤

设计决策:
  - Workflow: 一个完整的PDCA周期
  - Phase: Plan/Do/Check/Act 四阶段
  - Step: 阶段内的原子任务, 绑定Agent角色
  - 支持嵌套: Step可以是子Workflow (递归)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── 枚举 ──


class PhaseType(StrEnum):
    PLAN = "plan"
    DO = "do"
    CHECK = "check"
    ACT = "act"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    APPROVAL_PENDING = "approval_pending"
    CHECK_FAILED = "check_failed"  # P2-01: 质量门禁未通过


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── 步骤 ──


class Step(BaseModel):
    """工作流步骤 — 绑定Agent角色"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="步骤名称")
    description: str = Field(default="")
    agent_role: str = Field(description="执行Agent角色: boss/hitmaker/deal_hunter/...")
    action: str = Field(description="动作指令")
    status: StepStatus = Field(default=StepStatus.PENDING)
    result: str = Field(default="", description="执行结果")
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="期望输出JSON Schema, 空则不限格式",
        examples=[{"type": "object", "properties": {"summary": {"type": "string"}, "items": {"type": "array"}}}],
    )
    deadline: str = Field(default="", description="截止时间(ISO格式), 空则不限")
    requires_approval: bool = Field(default=False, description="是否需要人工审批")
    params: dict[str, Any] = Field(default_factory=dict, description="执行器参数（step_executors 注入）")
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")
    started_at: str = Field(default="")
    finished_at: str = Field(default="")
    # ── 条件分支字段 (Phase 1.1) ──
    condition: str = Field(default="", description="条件表达式（if_else/loop/switch步骤）")
    branch_id: str = Field(default="", description="步骤所属分支ID（如 'then'/'else'/'case_xxx'）")

    model_config = {"populate_by_name": True}


# ── 阶段 ──


class Phase(BaseModel):
    """PDCA阶段"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phase_type: PhaseType = Field(description="PDCA阶段类型")
    name: str = Field(default="", description="阶段名称, 空则用phase_type")
    description: str = Field(default="")
    steps: list[Step] = Field(default_factory=list)
    status: StepStatus = Field(default=StepStatus.PENDING)
    result: str = Field(default="")
    deadline: str = Field(default="", description="阶段截止时间(ISO格式), 空则不限")
    requires_approval: bool = Field(default=False, description="阶段完成时是否需要审批才能推进")
    on_failure: str = Field(
        default="advance",
        description="阶段失败时动作: advance=继续推进, retry_plan=回退Plan, retry_do=回退Do, retry_self=重试本阶段, halt=暂停工作流",
    )
    max_retries: int = Field(default=3, ge=0, description="retry_self最大重试次数, 0=不限制")
    retry_count: int = Field(default=0, ge=0, description="当前已重试次数")
    started_at: str = Field(default="")
    finished_at: str = Field(default="")

    def effective_name(self) -> str:
        return self.name or self.phase_type.value.upper()


# ── 工作流 ──


class Workflow(BaseModel):
    """PDCA工作流"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(description="工作流名称")
    description: str = Field(default="")
    status: WorkflowStatus = Field(default=WorkflowStatus.DRAFT)
    phases: list[Phase] = Field(default_factory=list, description="PDCA四阶段")
    current_phase: int = Field(default=0, description="当前阶段索引(0-3)")
    template_id: str = Field(default="", description="来源模板ID")
    pdca_cycle: int = Field(default=1, description="PDCA循环轮次")
    max_pdca_iterations: int = Field(default=10, description="PDCA最大循环次数, 0=不限制")
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")
    # ── 图形化DSL (工作流编排画布状态, JSON格式: nodes/edges/variables/metadata) ──
    graph_dsl: str = Field(default="", description="图形化工作流编排DSL(JSON), 画布节点/边/变量")
    # ── 运行时KV Store (条件分支变量缓存, 不持久化) ──
    store: dict[str, Any] = Field(default_factory=dict, description="运行时KV缓存(条件变量, 不持久化)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"populate_by_name": True}

    def current_phase_obj(self) -> Phase | None:
        if 0 <= self.current_phase < len(self.phases):
            return self.phases[self.current_phase]
        return None

    def next_step(self) -> Step | None:
        """推算当前工作流的下一个待执行步骤

        查找逻辑：
          1. 工作流非 running 状态 → None
          2. 在当前阶段查找第一个非 done/skipped 的步骤
          3. 当前阶段无待执行步骤 → 遍历后续阶段
          4. 全部阶段无待执行步骤 → None

        Returns:
            下一个待执行步骤，或 None（工作流已完成）
        """
        _IDLE_STATUSES = {
            WorkflowStatus.DRAFT,
            WorkflowStatus.PAUSED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.COMPLETED,
        }
        if self.status in _IDLE_STATUSES:
            return None

        _TERMINAL = {StepStatus.DONE, StepStatus.SKIPPED}

        # 从当前阶段开始查找
        for phase_idx in range(self.current_phase, len(self.phases)):
            phase = self.phases[phase_idx]
            for step in phase.steps:
                if step.status not in _TERMINAL:
                    return step

        return None

    def next_step_with_context(self) -> dict | None:
        """推算下一步并附带阶段上下文

        Returns:
            {"step": Step, "phase_index": int, "phase_type": str} 或 None
        """
        step = self.next_step()
        if step is None:
            return None

        _TERMINAL = {StepStatus.DONE, StepStatus.SKIPPED}

        # 找到该步骤所在阶段
        for phase_idx in range(self.current_phase, len(self.phases)):
            phase = self.phases[phase_idx]
            for s in phase.steps:
                if s.id == step.id:
                    return {
                        "step": step,
                        "phase_index": phase_idx,
                        "phase_type": phase.phase_type.value,
                    }

        return None


# ── DDL ──

WORKFLOW_DDL = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    phases_json TEXT DEFAULT '[]',
    current_phase INTEGER DEFAULT 0,
    template_id TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    graph_dsl TEXT DEFAULT '',
    store_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

STEP_LOG_DDL = """
CREATE TABLE IF NOT EXISTS workflow_step_logs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    phase_type TEXT NOT NULL,
    name TEXT DEFAULT '',
    agent_role TEXT NOT NULL,
    action TEXT DEFAULT '',
    result TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    metadata TEXT DEFAULT '{}',
    started_at TEXT DEFAULT '',
    finished_at TEXT DEFAULT '',
    created_at TEXT NOT NULL
)
;
CREATE INDEX IF NOT EXISTS idx_workflow_step_logs_instance ON workflow_step_logs(workflow_id, step_id)
"""

WORKFLOW_RUN_DDL = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    total_steps INTEGER NOT NULL DEFAULT 0,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    step_results TEXT DEFAULT '[]',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

# ── 状态转换表 ──

_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.DRAFT: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},
    WorkflowStatus.RUNNING: {
        WorkflowStatus.PAUSED,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.PAUSED: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},
    WorkflowStatus.COMPLETED: set(),  # 终态
    WorkflowStatus.FAILED: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},  # 允许重试
    WorkflowStatus.CANCELLED: set(),  # 终态
}


def validate_workflow_transition(current: WorkflowStatus, target: WorkflowStatus) -> None:
    """校验工作流状态转换是否合法，不合法则抛出 ValidationError。

    设计决策:
      - 放在 models.py 避免循环导入（engine.py / execution.py 均依赖此函数）
      - ValidationError 延迟导入，避免 models↔exceptions 循环依赖
    """
    allowed = _WORKFLOW_TRANSITIONS.get(current, set())
    if target not in allowed:
        from src.exceptions import ValidationError

        raise ValidationError(
            f"工作流不允许从 {current.value} 转换到 {target.value}",
            code="WORKFLOW_INVALID_TRANSITION",
        )
