
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A Protocol 模块 — Agent-to-Agent 通信协议(P1-INF-003)

A2A Protocol 规范: https://github.com/google-a2a/A2A

五态状态机:
  submitted → working → input-required → completed
                                  ↓
                              input-required → working (恢复)
                              input-required → completed (输入即完成)
                              input-required → failed (用户拒绝/超时)

与现有 AgentState 的映射见 transitions.py

AGENT-015: A2A 消息签名/验签模块 — sign_message / verify_message
  当前项目尚未引入完整 A2A 消息传递通道, signing 模块作为未来引入时的签名基础设施
  未来引入 A2A 消息传递时, 必须对每条消息做 HMAC-SHA256 签名/验签 (防篡改/防伪造)
"""

from __future__ import annotations

from src.engine.agent.a2a.agent_card import AgentCard
from src.engine.agent.a2a.signing import sign_message, verify_message
from src.engine.agent.a2a.states import A2AState
from src.engine.agent.a2a.task_lifecycle import TaskLifecycle
from src.engine.agent.a2a.transitions import (
    agent_state_to_a2a,
    is_valid_transition,
)

__all__ = [
    "A2AState",
    "AgentCard",
    "TaskLifecycle",
    "agent_state_to_a2a",
    "is_valid_transition",
    "sign_message",
    "verify_message",
]
