
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""节点状态机 A2A 五态对齐(P1-S1-012)

将工作流节点的执行状态统一映射到 A2A Protocol 五态:
  - submitted: 节点已创建,待执行
  - working: 执行中
  - input-required: 需要外部输入(如审批/人工确认)
  - completed: 正常完成
  - failed: 执行失败

本模块提供:
  - NodeStateMachine: 节点状态机,管理状态转换 + 校验合法性
  - node_status_to_a2a: 节点状态 → A2A 状态映射
  - create_node_lifecycle: 创建节点生命周期记录

与 src/engine/agent/a2a/transitions.py 复用同一转换表,确保一致性。
"""

from __future__ import annotations

import time
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.engine.agent.a2a.states import A2AState
from src.engine.agent.a2a.transitions import is_valid_transition
from src.exceptions import ErrorCode, TaskForgeError

logger = structlog.get_logger(__name__)


# ── 节点状态枚举(对齐 A2A 五态) ──

# 节点状态直接复用 A2AState,确保协议一致性
NodeStatus = A2AState


# ── 节点状态机 ──


@dataclass
class NodeStateRecord:
    """节点状态记录"""

    node_id: str
    run_id: str = ""
    status: NodeStatus = NodeStatus.SUBMITTED
    previous_status: NodeStatus | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class NodeStateMachine:
    """节点状态机

    管理单个节点的状态转换,确保所有转换符合 A2A 协议规范。

    用法:
        sm = NodeStateMachine(node_id="n1", run_id="r1")
        sm.transition(NodeStatus.WORKING)   #submitted → working
        sm.transition(NodeStatus.COMPLETED) #working → completed

        #非法转换会抛出 InvalidTransitionError
        sm.transition(NodeStatus.WORKING)   #completed → working (非法)
    """

    def __init__(self, node_id: str, run_id: str = "") -> None:
        self._record = NodeStateRecord(node_id=node_id, run_id=run_id)
        self.logger = structlog.get_logger(__name__).bind(node_id=node_id, run_id=run_id)

    @property
    def record(self) -> NodeStateRecord:
        return self._record

    @property
    def status(self) -> NodeStatus:
        return self._record.status

    @property
    def node_id(self) -> str:
        return self._record.node_id

    def transition(
        self,
        to_status: NodeStatus | str,
        metadata: dict[str, Any] | None = None,
    ) -> NodeStateRecord:
        """执行状态转换

        Args:
            to_status: 目标状态
            metadata: 转换元数据(如错误信息、输入数据等)

        Returns:
            更新后的状态记录

        Raises:
            InvalidTransitionError: 非法转换
        """
        to = NodeStatus(to_status) if isinstance(to_status, str) else to_status
        from_status = self._record.status

        if not is_valid_transition(from_status, to):
            raise InvalidTransitionError(
                node_id=self._record.node_id,
                from_status=from_status,
                to_status=to,
            )

        # 记录转换历史
        transition_entry = {
            "from": from_status.value,
            "to": to.value,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self._record.transitions.append(transition_entry)
        self._record.previous_status = from_status
        self._record.status = to
        self._record.updated_at = time.time()

        if metadata:
            if "error" in metadata:
                self._record.error = str(metadata["error"])
            self._record.metadata.update(metadata)

        self.logger.info(
            "node_state_transition",
            from_status=from_status.value,
            to_status=to.value,
            transition_count=len(self._record.transitions),
        )

        return self._record

    def can_transition(self, to_status: NodeStatus | str) -> bool:
        """检查是否可以转换到目标状态(不实际转换)"""
        to = NodeStatus(to_status) if isinstance(to_status, str) else to_status
        return is_valid_transition(self._record.status, to)

    def is_terminal(self) -> bool:
        """是否处于终态(completed/failed)"""
        return self._record.status in (NodeStatus.COMPLETED, NodeStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典(供 API 返回 / 持久化)"""
        return {
            "node_id": self._record.node_id,
            "run_id": self._record.run_id,
            "status": self._record.status.value,
            "previous_status": self._record.previous_status.value if self._record.previous_status else None,
            "is_terminal": self.is_terminal(),
            "transitions": self._record.transitions,
            "created_at": self._record.created_at,
            "updated_at": self._record.updated_at,
            "error": self._record.error,
            "metadata": self._record.metadata,
        }


# ── 异常 ──


class InvalidTransitionError(TaskForgeError):
    default_code = ErrorCode.WF_INVALID_TRANSITION
    """非法状态转换异常"""

    def __init__(
        self,
        node_id: str,
        from_status: NodeStatus,
        to_status: NodeStatus,
    ) -> None:
        self.node_id = node_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid node state transition: {from_status.value} → {to_status.value} (node_id={node_id})")


# ── 节点状态映射工具 ──


def node_status_to_a2a(status: str | NodeStatus) -> A2AState:
    """节点状态映射到 A2A 状态

    节点状态已直接使用 A2AState,此函数用于兼容字符串输入。
    """
    if isinstance(status, A2AState):
        return status
    return A2AState(status)


def create_node_lifecycle(
    node_id: str,
    run_id: str = "",
) -> NodeStateMachine:
    """创建节点生命周期状态机

    初始状态为 submitted。

    Args:
        node_id: 节点 ID
        run_id: 工作流运行 ID

    Returns:
        NodeStateMachine 实例
    """
    return NodeStateMachine(node_id=node_id, run_id=run_id)


# ── 批量状态管理器 ──


class NodeLifecycleManager:
    """批量管理多个节点的生命周期

    用于工作流执行器管理所有节点的状态。
    """

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id or _uuid.uuid4().hex[:8]
        self._machines: dict[str, NodeStateMachine] = {}

    def register(self, node_id: str) -> NodeStateMachine:
        """注册节点(初始状态 submitted)"""
        if node_id in self._machines:
            return self._machines[node_id]
        sm = NodeStateMachine(node_id=node_id, run_id=self.run_id)
        self._machines[node_id] = sm
        return sm

    def get(self, node_id: str) -> NodeStateMachine | None:
        return self._machines.get(node_id)

    def transition(
        self,
        node_id: str,
        to_status: NodeStatus | str,
        metadata: dict[str, Any] | None = None,
    ) -> NodeStateRecord:
        """转换节点状态(自动注册未注册的节点)"""
        sm = self.register(node_id)
        return sm.transition(to_status, metadata)

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """获取所有节点状态(序列化)"""
        return {nid: sm.to_dict() for nid, sm in self._machines.items()}

    def get_status(self, node_id: str) -> NodeStatus | None:
        sm = self._machines.get(node_id)
        return sm.status if sm else None

    def is_node_terminal(self, node_id: str) -> bool:
        sm = self._machines.get(node_id)
        return sm.is_terminal() if sm else False

    def all_nodes_terminal(self) -> bool:
        """所有节点是否都处于终态"""
        if not self._machines:
            return True
        return all(sm.is_terminal() for sm in self._machines.values())

    def summary(self) -> dict[str, int]:
        """状态汇总统计"""
        counts: dict[str, int] = {}
        for sm in self._machines.values():
            status = sm.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts
