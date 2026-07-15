
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""子Agent缓存安全参数与 Prompt Cache

从 sub_agent.py 拆分出的模块，包含:
  - CacheSafeParams: 缓存安全参数(子代理参数快照)
  - Prompt Cache 工具函数: _generate_prompt_cache_key / get/set/clear_cached_prompt
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CacheSafeParams:
    """缓存安全参数 — 子代理的参数快照，避免修改父代理缓存

    参考 claude-code 的 CacheSafeParams + promptCache:
    - 深拷贝父代理的关键参数
    - P1-1: shared_system_prompt / prompt_cache_key (Prompt Cache 共享)
    - P1-2: 子代理修改不影响父代理、权限冒泡
    """

    # 上下文快照 (深拷贝)
    messages_snapshot: list[dict[str, Any]] = field(default_factory=list)
    tool_results_snapshot: dict[str, Any] = field(default_factory=dict)
    # P1-1: Prompt Cache 共享
    shared_system_prompt: str = ""
    prompt_cache_key: str = ""
    # 权限快照
    allowed_tools: set[str] = field(default_factory=set)
    permission_level: str = "read_only"
    # M5-F3: 权限冒泡模式 (silent | bubble | block)
    permission_mode: str = "silent"
    # 元数据
    parent_agent: str = ""
    session_id: str = ""
    project_space_id: str = ""

    @classmethod
    def from_parent(
        cls,
        *,
        parent_agent: str = "",
        messages: list[dict[str, Any]] | None = None,
        tool_results: dict[str, Any] | None = None,
        allowed_tools: set[str] | None = None,
        permission_level: str = "read_only",
        session_id: str = "",
        project_space_id: str = "",
        # P1-1: Prompt Cache
        system_prompt: str = "",
        prompt_cache_key: str = "",
    ) -> CacheSafeParams:
        """从父代理创建缓存安全参数

        深拷贝所有可变数据，确保子代理修改不影响父代理
        """
        # P1-1: 生成 prompt_cache_key (基于 system_prompt 哈希)
        if system_prompt and not prompt_cache_key:
            prompt_cache_key = _generate_prompt_cache_key(system_prompt)

        return cls(
            messages_snapshot=copy.deepcopy(messages or []),
            tool_results_snapshot=copy.deepcopy(tool_results or {}),
            allowed_tools=set(allowed_tools or set()),
            permission_level=permission_level,
            parent_agent=parent_agent,
            session_id=session_id,
            project_space_id=project_space_id,
            shared_system_prompt=system_prompt,
            prompt_cache_key=prompt_cache_key,
        )

    def get_inherited_messages(self, max_messages: int = 20) -> list[dict[str, Any]]:
        """获取继承的消息列表 (截断到 max_messages)"""
        if len(self.messages_snapshot) <= max_messages:
            return copy.deepcopy(self.messages_snapshot)
        # 保留 system 消息 + 最近的消息
        system = [m for m in self.messages_snapshot if m.get("role") == "system"]
        non_system = [m for m in self.messages_snapshot if m.get("role") != "system"]
        keep = max(1, max_messages - len(system))
        result = list(system) + non_system[-keep:]
        return copy.deepcopy(result)

    def get_prompt_cache_metadata(self) -> dict[str, Any]:
        """P1-1: 获取 Prompt Cache 元数据 (传递给 LLM API)

        用于支持支持 prompt caching 的 LLM provider (如 Claude、Gemini)
        子代理可以共享父代理的系统提示词缓存，减少 token 消耗。
        """
        if not self.shared_system_prompt or not self.prompt_cache_key:
            return {}
        return {
            "cache_key": self.prompt_cache_key,
            "system_prompt_hash": self.prompt_cache_key,
            "estimated_tokens": _estimate_tokens(self.shared_system_prompt),
        }

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否在允许列表中

        权限冒泡: 子代理只能使用父代理允许的工具
        """
        if not self.allowed_tools:
            return True
        return tool_name in self.allowed_tools


# ── P1-1: Prompt Cache 工具函数 ──

# 进程内 Prompt Cache (简单 LRU)
_prompt_cache: dict[str, str] = {}
_PROMPT_CACHE_MAX_SIZE = 50


def _generate_prompt_cache_key(system_prompt: str) -> str:
    """P1-1: 生成 Prompt Cache 键

    基于系统提示词内容的 SHA256 哈希，确保相同提示词产生相同 key。
    子代理可共享父代理的缓存 key。
    """
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]


def _estimate_tokens(text: str) -> int:
    """P0-2.2: 快速估算 token 数 — 委托给权威双语感知实现"""
    from src.engine.context.assembler_models import estimate_tokens

    return estimate_tokens(text) if text else 0


def get_cached_prompt(cache_key: str) -> str | None:
    """P1-1: 获取缓存的 Prompt

    子代理或其他并行代理可以共享相同的系统提示词，减少 token 消耗。
    """
    return _prompt_cache.get(cache_key)


def set_cached_prompt(cache_key: str, prompt: str) -> None:
    """P1-1: 缓存 Prompt

    简单的 LRU: 超过最大容量时，移除最早的条目。
    """
    if len(_prompt_cache) >= _PROMPT_CACHE_MAX_SIZE:
        # 移除最早的条目
        oldest_key = next(iter(_prompt_cache))
        del _prompt_cache[oldest_key]
    _prompt_cache[cache_key] = prompt
    logger.debug("prompt_cache_set", key=cache_key, tokens=_estimate_tokens(prompt))


def clear_prompt_cache() -> None:
    """P1-1: 清理 Prompt Cache (用于测试重置)"""
    _prompt_cache.clear()
