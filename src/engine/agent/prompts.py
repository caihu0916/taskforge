
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge Agent Prompt 渲染 — 从模板生成系统提示词

设计决策:
  - 模板变量用 {var} 格式, Python str.format() 渲染
  - 必填变量缺失时抛 KeyError (早发现)
  - 渲染结果缓存, 同一角色+变量只渲染一次
"""

from __future__ import annotations

from .roles import ROLE_DEFINITIONS, AgentRole

# 默认模板变量
DEFAULT_VARS: dict[str, str] = {
    "business_name": "我的小店",
    "owner_name": "老板",
}


class PromptRenderer:
    """系统提示词渲染器

    用法:
        renderer = PromptRenderer(business_name="张三的知识铺")
        prompt = renderer.render(AgentRole.HITMAKER)
    """

    def __init__(self, **overrides: str) -> None:
        self._vars = {**DEFAULT_VARS, **overrides}
        self._cache: dict[str, str] = {}

    def render(self, role: AgentRole, **extra_vars: str) -> str:
        """渲染角色的系统提示词"""
        cache_key = f"{role.value}:{sorted(extra_vars.items())}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        definition = ROLE_DEFINITIONS[role]
        template = definition.system_prompt_template
        if not template:
            return ""

        merged = {**self._vars, **extra_vars}
        try:
            result = template.format(**merged)
        except KeyError:
            # 缺变量的模板直接返回原文(不 crash)
            result = template

        self._cache[cache_key] = result
        return result

    def render_with_context(
        self,
        role: AgentRole,
        *,
        task_description: str = "",
        constraints: list[str] | None = None,
        **extra_vars: str,
    ) -> str:
        """渲染 + 追加任务上下文"""
        base = self.render(role, **extra_vars)
        parts = [base]

        if task_description:
            parts.append(f"\n当前任务: {task_description}")

        if constraints:
            parts.append("\n约束条件:")
            for c in constraints:
                parts.append(f"- {c}")

        return "\n".join(parts)

    def update_vars(self, **kwargs: str) -> None:
        """更新模板变量 (清缓存)"""
        self._vars.update(kwargs)
        self._cache.clear()

    @property
    def vars(self) -> dict[str, str]:
        return dict(self._vars)
