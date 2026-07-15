
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A Task 生命周期执行器(P1-INF-003)

职责:
  - 管理 A2A 任务的五态状态机
  - 强制合法转换(非法抛 ValueError)
  - 记录状态变更历史(审计追溯)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.engine.agent.a2a.states import A2AState
from src.engine.agent.a2a.transitions import is_valid_transition


@dataclass
class StateRecord:
    """状态变更记录(审计)"""

    state: A2AState
    timestamp: str
    note: str = ""


@dataclass
class TaskLifecycle:
    """A2A Task 生命周期执行器

    用法:
        lifecycle = TaskLifecycle(task_id="task-001")
        lifecycle.transition_to("working")
        lifecycle.transition_to("input-required")  #等待审批
        lifecycle.transition_to("working")  #审批通过,恢复
        lifecycle.transition_to("completed")

    非法转换抛 ValueError(如终态转出/逆向/同态)
    """

    task_id: str
    _current: A2AState = field(default=A2AState.SUBMITTED, init=False)
    _history: list[StateRecord] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        # 初始状态记录
        self._history.append(
            StateRecord(
                state=A2AState.SUBMITTED,
                timestamp=datetime.now(UTC).isoformat(),
                note="任务已提交",
            )
        )

    @property
    def current_state(self) -> A2AState:
        """当前状态"""
        return self._current

    @property
    def history(self) -> list[StateRecord]:
        """状态变更历史(只读视图)"""
        return list(self._history)

    def transition_to(
        self,
        to_state: str | A2AState,
        note: str = "",
    ) -> None:
        """状态转换

        Args:
            to_state: 目标状态(字符串或 A2AState)
            note: 转换说明(可选,如"审批通过")

        Raises:
            ValueError: 非法状态转移(含终态转出/逆向/同态)
        """
        if not is_valid_transition(self._current, to_state):
            raise ValueError(f"非法状态转移: {self._current.value} → {to_state} (task_id={self.task_id})")

        target = A2AState(to_state) if not isinstance(to_state, A2AState) else to_state
        self._current = target
        self._history.append(
            StateRecord(
                state=target,
                timestamp=datetime.now(UTC).isoformat(),
                note=note,
            )
        )

    def is_terminal(self) -> bool:
        """当前是否为终态(completed/failed)"""
        return self._current in (A2AState.COMPLETED, A2AState.FAILED)

    def can_transition_to(self, to_state: str | A2AState) -> bool:
        """检查是否可转换到目标状态(不实际转换)"""
        return is_valid_transition(self._current, to_state)
