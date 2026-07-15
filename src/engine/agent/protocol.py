
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge Agent 执行协议 — 统一 SpecialistAgent 和 AgentRunner 的执行接口

解决两套并行 Agent 执行路径的认知负担:
  - SpecialistAgent: 同步式业务逻辑执行
  - AgentRunner: ReAct 循环 (LLM + 工具调用 + 记忆)

两者均实现 AgentExecutable 协议，上层调度器无需关心执行模型差异。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentExecutionResult:
    """统一执行结果 — SpecialistAgent 和 AgentRunner 共用"""

    success: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    agent_name: str = ""
    execution_mode: str = ""  # "direct" (SpecialistAgent) | "react" (AgentRunner)
    exec_id: str = ""
    tokens_used: int = 0
    elapsed_ms: float = 0.0


class AgentExecutable(ABC):
    """Agent 统一执行协议

    所有 Agent 执行器（SpecialistAgent / AgentRunner）必须实现此协议。
    上层调度器通过此协议调用，无需关心底层是直接执行还是 ReAct 循环。
    """

    @abstractmethod
    async def execute_task(
        self,
        task: str,
        *,
        context: dict[str, Any] | None = None,
        agent_role: str = "",
    ) -> AgentExecutionResult:
        """执行任务，返回统一结果

        Args:
            task: 任务描述
            context: 上下文信息 (可选)
            agent_role: Agent 角色ID (可选，用于路由)

        Returns:
            AgentExecutionResult 统一结果
        """
        ...
