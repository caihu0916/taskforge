
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent进化引擎 - 数据模型

包含:
  - 枚举定义 (ExecutionResult, StrategyType, EvolutionAction, EvolutionPhase, EvolutionStatus)
  - 数据模型 (EvolutionStep, EvolutionSession, ExecutionRecord, Strategy, MemoryEntry, EvolutionReport)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ExecutionResult(Enum):
    """执行结果"""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"


class StrategyType(Enum):
    """策略类型"""

    PROMPT_TEMPLATE = "prompt_template"
    TOOL_SELECTION = "tool_selection"
    WORKFLOW_ORDER = "workflow_order"
    PARAMETER_SETTING = "parameter_setting"


class EvolutionAction(Enum):
    """进化动作"""

    KEEP = "keep"  # 保持当前策略
    ADJUST = "adjust"  # 微调参数
    REPLACE = "replace"  # 替换为新策略
    ARCHIVE = "archive"  # 归档旧策略


class EvolutionPhase(Enum):
    """进化阶段"""

    PLAN = "plan"
    EXECUTE = "execute"
    REFLECT = "reflect"
    LEARN = "learn"


class EvolutionStatus(Enum):
    """进化状态"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class EvolutionStep:
    """进化步骤"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    iteration: int = 0
    session_id: str = ""
    phase: EvolutionPhase = EvolutionPhase.PLAN
    status: EvolutionStatus = EvolutionStatus.RUNNING
    plan: str = ""
    action: str = ""
    action_result: dict[str, Any] = field(default_factory=dict)
    reflection: str = ""
    success: bool = False
    learned: str = ""
    rules_applied: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EvolutionSession:
    """进化会话"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    max_iterations: int = 5
    current_iteration: int = 0
    steps: list[EvolutionStep] = field(default_factory=list)
    status: EvolutionStatus = EvolutionStatus.RUNNING
    is_complete: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = ""

    @property
    def latest_step(self) -> EvolutionStep | None:
        """获取最新步骤"""
        return self.steps[-1] if self.steps else None


@dataclass
class ExecutionRecord:
    """执行记录"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    task_id: str = ""
    task_description: str = ""
    strategy_used: str = ""  # 使用的策略ID
    result: ExecutionResult = ExecutionResult.FAILED
    duration_seconds: float = 0.0
    tokens_used: int = 0
    user_feedback_score: float = 0.0  # 1-5分
    error_message: str = ""
    output_quality_score: float = 0.0  # AI自评质量
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Strategy:
    """策略定义"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    strategy_type: StrategyType = StrategyType.PROMPT_TEMPLATE
    content: dict[str, Any] = field(default_factory=dict)  # 策略内容 (prompt/参数等)
    version: int = 1
    is_active: bool = True
    success_count: int = 0
    failure_count: int = 0
    avg_quality_score: float = 0.0
    avg_duration: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = ""


@dataclass
class MemoryEntry:
    """记忆条目"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    category: str = ""  # lesson_learned, best_practice, pitfall, user_preference
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 置信度 0-1
    usage_count: int = 0
    last_used_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EvolutionReport:
    """进化报告"""

    period_start: str = ""
    period_end: str = ""
    total_executions: int = 0
    success_rate: float = 0.0
    avg_quality_score: float = 0.0
    avg_duration: float = 0.0
    top_strategies: list[dict] = field(default_factory=list)
    worst_strategies: list[dict] = field(default_factory=list)
    new_memories: int = 0
    strategies_adjusted: int = 0
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = ""


__all__ = [
    "EvolutionAction",
    "EvolutionPhase",
    "EvolutionReport",
    "EvolutionSession",
    "EvolutionStatus",
    "EvolutionStep",
    "ExecutionRecord",
    "ExecutionResult",
    "MemoryEntry",
    "Strategy",
    "StrategyType",
]
