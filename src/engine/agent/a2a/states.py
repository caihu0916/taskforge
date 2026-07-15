
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""A2A Protocol 状态定义(P1-INF-003)

A2A 标准五态,对应 A2A Protocol 规范。
与现有 AgentState(9 态)的映射见 transitions.py。
"""

from __future__ import annotations

from enum import StrEnum


class A2AState(StrEnum):
    """A2A Protocol 五态状态机

    规范来源: https://github.com/google-a2a/A2A

    状态说明:
      - submitted: 任务已提交,待执行
      - working: 执行中(LLM 思考/工具调用/收尾)
      - input-required: 需要外部输入(如人工审批/用户确认)
      - completed: 正常完成(终态)
      - failed: 执行失败/取消/错误(终态)
    """

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
