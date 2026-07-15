
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent 状态定义 — 权威状态枚举与转换表 + 状态机

B-02 (2026-06-26): AgentStateMachine 恢复，修复原设计缺陷:
  - COMPLETING → DONE 转换原子化 (asyncio.Lock 保护)
  - IDLE → ERROR 转换已在 _STATE_TRANSITIONS 表中补齐
  - 非法转换抛 IllegalStateTransitionError (或返回 False，由调用方选择)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

import structlog

from src.exceptions import ErrorCode, TaskForgeError

logger = structlog.get_logger(__name__)


class IllegalStateTransitionError(TaskForgeError):
    """非法状态转换异常 — 尝试了 _STATE_TRANSITIONS 表中不允许的转换"""

    default_code = ErrorCode.AGT_INVALID_ROLE  # AGT-0003

    def __init__(self, from_state: AgentState, to_state: AgentState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"非法状态转换: {from_state.value} → {to_state.value}",
            details={"from_state": from_state.value, "to_state": to_state.value},
        )


# ── 状态定义 ──


class AgentState(StrEnum):
    """Agent 任务状态枚举"""

    IDLE = "idle"  # 空闲，等待任务
    PREPARING = "preparing"  # 准备中 (加载知识库、构建上下文)
    RUNNING = "running"  # 运行中 (LLM思考或执行工具)
    WAITING_TOOL = "waiting_tool"  # 等待工具执行返回
    COMPLETING = "completing"  # 完成中 (总结输出)
    DONE = "done"  # 已完成
    FAILED = "failed"  # 执行失败 (可恢复错误)
    CANCELLED = "cancelled"  # 已取消 (用户中断或超时)
    ERROR = "error"  # 错误中止 (不可恢复错误)


# 合法状态转换表
_STATE_TRANSITIONS: dict[AgentState, frozenset] = {
    AgentState.IDLE: frozenset({AgentState.PREPARING, AgentState.CANCELLED, AgentState.ERROR}),
    AgentState.PREPARING: frozenset({AgentState.RUNNING, AgentState.CANCELLED, AgentState.ERROR}),
    AgentState.RUNNING: frozenset(
        {AgentState.WAITING_TOOL, AgentState.COMPLETING, AgentState.CANCELLED, AgentState.FAILED, AgentState.ERROR}
    ),
    AgentState.WAITING_TOOL: frozenset({AgentState.RUNNING, AgentState.CANCELLED, AgentState.FAILED, AgentState.ERROR}),
    AgentState.COMPLETING: frozenset({AgentState.DONE, AgentState.FAILED, AgentState.CANCELLED}),
    AgentState.DONE: frozenset(),  # 终态
    AgentState.FAILED: frozenset(),  # 终态
    AgentState.CANCELLED: frozenset(),  # 终态
    AgentState.ERROR: frozenset(),  # 终态
}

# 状态显示文本
_STATE_LABELS: dict[AgentState, str] = {
    AgentState.IDLE: "空闲",
    AgentState.PREPARING: "准备中...",
    AgentState.RUNNING: "执行中",
    AgentState.WAITING_TOOL: "工具调用中...",
    AgentState.COMPLETING: "总结中...",
    AgentState.DONE: "已完成",
    AgentState.FAILED: "执行失败",
    AgentState.CANCELLED: "已取消",
    AgentState.ERROR: "异常中止",
}

# 状态对应的 emoji (飞书状态卡片用)
_STATE_EMOJI: dict[AgentState, str] = {
    AgentState.IDLE: "",
    AgentState.PREPARING: "",
    AgentState.RUNNING: "",
    AgentState.WAITING_TOOL: "",
    AgentState.COMPLETING: "",
    AgentState.DONE: "",
    AgentState.FAILED: "",
    AgentState.CANCELLED: "",
    AgentState.ERROR: "",
}


# ══════════════════════════════════════════════════════════════════
# B-02: AgentStateMachine 恢复 (2026-06-26)
# 修复原设计缺陷: asyncio.Lock 原子转换 + IDLE→ERROR 已补齐 + 非法转换返回 False
# ══════════════════════════════════════════════════════════════════

# 状态变更回调类型
StateChangeCallback = Callable[
    [AgentState, AgentState, dict[str, Any]],
    Coroutine[Any, Any, None],
]

# 活跃状态集合 (非终态)
_ACTIVE_STATES = frozenset(
    {
        AgentState.IDLE,
        AgentState.PREPARING,
        AgentState.RUNNING,
        AgentState.WAITING_TOOL,
        AgentState.COMPLETING,
    }
)

# 终态集合
_TERMINAL_STATES = frozenset(
    {
        AgentState.DONE,
        AgentState.FAILED,
        AgentState.CANCELLED,
        AgentState.ERROR,
    }
)


class AgentStateMachine:
    """Agent 任务状态机 — 原子状态转换 + 回调通知

    B-02: 恢复的 AgentStateMachine，修复原缺陷:
      - asyncio.Lock 保证 COMPLETING → DONE 转换原子性
      - 非法转换返回 False (不抛异常，由调用方判断)
      - 回调异常隔离，不影响状态转换

    用法:
        sm = AgentStateMachine("developer")
        await sm.start()              # IDLE → PREPARING → RUNNING
        await sm.waiting_for_tool()   # RUNNING → WAITING_TOOL
        await sm.tool_complete()      # WAITING_TOOL → RUNNING
        await sm.complete()           # RUNNING → COMPLETING → DONE
    """

    def __init__(
        self,
        agent_role: str,
        on_change: StateChangeCallback | None = None,
    ) -> None:
        self._agent_role = agent_role
        self._on_change = on_change
        self._lock = asyncio.Lock()
        self._current: AgentState = AgentState.IDLE
        self._prev: AgentState = AgentState.IDLE
        self._tool_count: int = 0
        self._error: str = ""
        self._start_time: float = time.monotonic()

    # ── 属性 ──

    @property
    def current(self) -> AgentState:
        return self._current

    @property
    def prev(self) -> AgentState:
        return self._prev

    @property
    def is_active(self) -> bool:
        """是否处于活跃状态 (非终态)"""
        return self._current in _ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        """是否处于终态"""
        return self._current in _TERMINAL_STATES

    @property
    def tool_count(self) -> int:
        return self._tool_count

    @property
    def error(self) -> str:
        return self._error

    @property
    def label(self) -> str:
        return _STATE_LABELS.get(self._current, str(self._current))

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    # ── 内部转换 ──

    async def _transition(self, to_state: AgentState, ctx: dict[str, Any] | None = None) -> bool:
        """原子状态转换，返回 True 成功 / False 非法"""
        async with self._lock:
            allowed = _STATE_TRANSITIONS.get(self._current, frozenset())
            if to_state not in allowed:
                logger.warning(
                    "agent_state_illegal_transition",
                    agent_role=self._agent_role,
                    from_state=self._current.value,
                    to_state=to_state.value,
                )
                return False
            old = self._current
            self._prev = old
            self._current = to_state
            # 回调异常隔离
            if self._on_change is not None:
                try:
                    await self._on_change(old, to_state, ctx or {})
                except Exception as _cb_err:
                    logger.debug("agent_state_callback_error", error=str(_cb_err), exc_info=True)
            logger.debug(
                "agent_state_transition",
                agent_role=self._agent_role,
                from_state=old.value,
                to_state=to_state.value,
            )
            return True

    # ── 公共转换方法 ──

    async def start(self) -> bool:
        """IDLE → PREPARING → RUNNING (两步转换)"""
        ok1 = await self._transition(AgentState.PREPARING, {"reason": "start"})
        if not ok1:
            return False
        return await self._transition(AgentState.RUNNING, {"reason": "start"})

    async def waiting_for_tool(self, tool_name: str = "") -> bool:
        """RUNNING → WAITING_TOOL"""
        ok = await self._transition(AgentState.WAITING_TOOL, {"tool": tool_name})
        if ok:
            self._tool_count += 1
        return ok

    async def tool_complete(self, tool_name: str = "", duration_ms: int = 0) -> bool:
        """WAITING_TOOL → RUNNING"""
        return await self._transition(AgentState.RUNNING, {"tool": tool_name, "duration_ms": duration_ms})

    async def complete(self) -> bool:
        """RUNNING → COMPLETING → DONE (两步转换，原子化)"""
        ok1 = await self._transition(AgentState.COMPLETING, {"reason": "complete"})
        if not ok1:
            return False
        return await self._transition(AgentState.DONE, {"reason": "complete"})

    async def fail(self, reason: str = "") -> bool:
        """RUNNING/WAITING_TOOL → FAILED"""
        self._error = reason
        return await self._transition(AgentState.FAILED, {"reason": reason})

    async def cancel(self, reason: str = "") -> bool:
        """任意活跃状态 → CANCELLED"""
        self._error = reason
        return await self._transition(AgentState.CANCELLED, {"reason": reason})

    async def error_abort(self, reason: str = "") -> bool:
        """任意活跃状态 → ERROR"""
        self._error = reason
        return await self._transition(AgentState.ERROR, {"reason": reason})

    # ── 工具方法 ──

    def reset(self) -> None:
        """重置到 IDLE (不经过状态转换表)"""
        self._current = AgentState.IDLE
        self._prev = AgentState.IDLE
        self._tool_count = 0
        self._error = ""
        self._start_time = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        """生成状态快照"""
        return {
            "agent_role": self._agent_role,
            "current": self._current.value,
            "prev": self._prev.value,
            "is_active": self.is_active,
            "is_terminal": self.is_terminal,
            "tool_count": self._tool_count,
            "error": self._error,
            "duration_ms": self.duration_ms,
        }


__all__ = [
    "AgentState",
    "AgentStateMachine",
    "IllegalStateTransitionError",
    "StateChangeCallback",
]
