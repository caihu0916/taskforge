
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A Protocol 状态转换表与映射(P1-INF-003)

职责:
  - 定义 A2A 五态合法转换表
  - is_valid_transition: 校验转换合法性(非法 100% 拒绝)
  - agent_state_to_a2a: 现有 AgentState(9 态)→ A2A(5 态)映射(向后兼容)
"""

from __future__ import annotations

from src.engine.agent.a2a.states import A2AState
from src.engine.agent.state_machine import AgentState

# ── A2A 五态合法转换表 ──
# 终态(completed/failed)无出转换,终态转出在 is_valid_transition 中返回 False

_A2A_TRANSITIONS: dict[A2AState, frozenset[A2AState]] = {
    A2AState.SUBMITTED: frozenset(
        {
            A2AState.WORKING,
            A2AState.COMPLETED,  # 幂等命中,立即完成
            A2AState.FAILED,  # 启动即失败
        }
    ),
    A2AState.WORKING: frozenset(
        {
            A2AState.INPUT_REQUIRED,  # 需人工输入(如审批)
            A2AState.COMPLETED,  # 正常完成
            A2AState.FAILED,  # 执行失败
        }
    ),
    A2AState.INPUT_REQUIRED: frozenset(
        {
            A2AState.WORKING,  # 输入完成,恢复执行
            A2AState.COMPLETED,  # 输入即完成
            A2AState.FAILED,  # 用户拒绝/超时
        }
    ),
    A2AState.COMPLETED: frozenset(),  # 终态
    A2AState.FAILED: frozenset(),  # 终态
}


def is_valid_transition(
    from_state: str | A2AState,
    to_state: str | A2AState,
) -> bool:
    """校验 A2A 状态转换合法性

    Args:
        from_state: 起始状态(字符串或 A2AState)
        to_state: 目标状态(字符串或 A2AState)

    Returns:
        True = 合法转换, False = 非法转换(含终态转出/逆向/同态)
    """
    try:
        f = A2AState(from_state) if not isinstance(from_state, A2AState) else from_state
        t = A2AState(to_state) if not isinstance(to_state, A2AState) else to_state
    except ValueError:
        return False  # 未知状态

    if f == t:
        return False  # 同态转移拒绝(必须显式变化)

    return t in _A2A_TRANSITIONS.get(f, frozenset())


# ── AgentState → A2A 映射(向后兼容) ──

_AGENT_STATE_TO_A2A: dict[AgentState, A2AState] = {
    AgentState.IDLE: A2AState.SUBMITTED,  # 空闲等待任务 = 已提交待执行
    AgentState.PREPARING: A2AState.WORKING,  # 准备中 = 执行中
    AgentState.RUNNING: A2AState.WORKING,  # 运行中 = 执行中
    AgentState.WAITING_TOOL: A2AState.INPUT_REQUIRED,  # 等待工具/输入 = 需输入
    AgentState.COMPLETING: A2AState.WORKING,  # 完成中 = 执行中(收尾)
    AgentState.DONE: A2AState.COMPLETED,  # 已完成 = completed
    AgentState.FAILED: A2AState.FAILED,  # 执行失败 = failed
    AgentState.CANCELLED: A2AState.FAILED,  # 已取消 = failed(非正常终止)
    AgentState.ERROR: A2AState.FAILED,  # 错误中止 = failed
}


def agent_state_to_a2a(state: AgentState) -> A2AState:
    """现有 AgentState(9 态)映射到 A2A(5 态)

    用于:
      - 现有工作流执行器向上层暴露 A2A 标准状态
      - Agent Card 协议对齐
      - 跨系统互操作(A2A 协议消费者只关心五态)

    Args:
        state: 现有 AgentState 枚举值

    Returns:
        对应的 A2AState 枚举值

    Raises:
        KeyError: 未知 AgentState(理论上不会发生,映射覆盖全部 9 态)
    """
    if state not in _AGENT_STATE_TO_A2A:
        raise KeyError(f"AgentState {state} 未在 A2A 映射表中,请联系架构组补充")
    return _AGENT_STATE_TO_A2A[state]
