
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""M5-C: Fork Subagent — 隐式 Fork 机制 (对标 Claude Code forkSubagent.ts)"""

from __future__ import annotations

from typing import Any

FORK_BOILERPLATE_TAG = "fork-subagent-boilerplate"
FORK_PLACEHOLDER_RESULT = "Fork started — processing in background"


def build_forked_messages(directive: str, tool_calls: list[dict] | None = None) -> list[dict[str, Any]]:
    """构建 fork 子Agent 的消息前缀"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"<{FORK_BOILERPLATE_TAG}>"},
    ]
    for tc in tool_calls or []:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": FORK_PLACEHOLDER_RESULT,
            }
        )
    messages.append({"role": "user", "content": directive})
    return messages


def is_in_fork_child(messages: list[dict[str, Any]]) -> bool:
    """检测消息历史中是否包含 fork boilerplate tag"""
    for m in messages:
        content = str(m.get("content", ""))
        if FORK_BOILERPLATE_TAG in content:
            return True
    return False
