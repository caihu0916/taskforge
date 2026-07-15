
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Phase 0: AgentInput/AgentOutput 统一数据模型 (对标 Claude Code v2.1.168 sdk-tools.d.ts)"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentInput:
    """Agent 统一入口 — 对标 Claude Code AgentInput"""

    task: str
    role: str = "leaf"  # leaf | orchestrator
    name: str = ""  # 命名Agent (TeamChannel寻址)
    team_name: str = ""  # Team上下文
    mode: str = "auto"  # auto | plan | dontAsk
    model: str = ""  # sonnet | opus | haiku
    max_turns: int = 5
    isolation: str = "none"  # worktree | none
    run_in_background: bool = False
    blocked_tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)  # W1: MCP服务器列表
    context: dict[str, Any] = field(default_factory=dict)
    on_progress: Any = None  # W2: 进度回调 Callable[[dict], Awaitable]
    cancel_event: Any = None  # W3: asyncio.Event | None


@dataclass
class AgentOutput:
    """Agent 统一出口 — 对标 Claude Code AgentOutput"""

    success: bool
    result: str
    sub_agent_id: str = ""
    sub_agent_role: str = ""
    turns: int = 0
    duration_ms: int = 0
    status: str = "completed"  # completed | async_launched
    usage: dict[str, int] = field(default_factory=dict)
    output_file: str = ""
