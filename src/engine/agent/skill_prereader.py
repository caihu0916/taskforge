
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill Prereader — Fable 5 模式 A 落地

Fable 5 的 skills_forced_preread 机制：Agent 在执行任何工具前，必须先读匹配的 SKILL.md，
确保不会凭"印象"执行，而是严格按技能文档操作。

TaskForge 应用：
  - 解析用户消息，匹配可能触发的技能
  - 匹配到的技能自动加载 SKILL.md 内容
  - 注入到 context_builder 的 session 层
  - 不匹配则零开销（不注入任何内容）

匹配策略:
  1. 关键词匹配: 用户消息中出现 trigger_keywords 或技能名
  2. 工具名匹配: 工具调用中的 skill 名称
  3. 路径匹配: 用户操作文件匹配 paths 模式

集成点: context_builder.py Layer1.7（与 reminders 并列）
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# 单次注入上限（字符数），防止 token 膨胀
_MAX_PREREAD_CHARS = 1500

# 单次最多预加载技能数
_MAX_PREREAD_SKILLS = 3


class SkillPrereader:
    """技能强制预读中间件

    用法:
        prereader = SkillPrereader()
        content = prereader.preread("帮我写一篇小红书笔记")
        #如果匹配到 xhs-copywriting 技能, 返回其 SKILL.md 摘要
        #否则返回 ""
    """

    def __init__(self):
        self._skills_cache: dict = {}  # name → SkillDefinition (lazy load)

    def _load_skills(self) -> dict:
        """延迟加载技能列表"""
        if self._skills_cache:
            return self._skills_cache

        try:
            from src.engine.skill.skill_loader import get_skill_loader

            loader = get_skill_loader()
            loader.load_all()
            for skill in loader.list_skills():
                self._skills_cache[skill.name] = skill
        except Exception:
            logger.debug("skill_prereader_load_failed", exc_info=True)

        return self._skills_cache

    def match_skills(self, message: str, context: dict | None = None) -> list[str]:
        """根据用户消息匹配可能触发的技能名

        匹配优先级:
        1. 技能名直接出现在消息中
        2. trigger_keywords 匹配
        3. 工具路径关联（可选）

        Args:
            message: 用户消息
            context: 可选上下文（暂未使用，预留扩展）

        Returns:
            匹配到的技能名列表，最多 _MAX_PREREAD_SKILLS 个
        """
        if not message:
            return []

        skills = self._load_skills()
        if not skills:
            return []

        matched: list[tuple[int, str]] = []  # (priority, name)

        msg_lower = message.lower()

        for name, skill in skills.items():
            priority = 0

            # 1. 技能名出现在消息中（最高优先级）
            # 支持中划线和下划线两种格式
            name_variants = [name, name.replace("-", "_"), name.replace("_", "-")]
            for variant in name_variants:
                if variant.lower() in msg_lower:
                    priority = 100
                    break

            # 2. trigger_keywords 匹配
            if priority == 0 and skill.trigger_keywords:
                for kw in skill.trigger_keywords:
                    if kw.lower() in msg_lower:
                        priority = 50
                        break

            # 3. 描述关键词模糊匹配（最低优先级，仅当描述词出现在消息中）
            if priority == 0 and skill.description:
                desc_words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", skill.description)
                desc_hits = sum(1 for w in desc_words if w.lower() in msg_lower and len(w) >= 2)
                if desc_hits >= 2:
                    priority = 10 + desc_hits

            if priority > 0:
                matched.append((priority, name))

        # 按优先级排序，取前 N 个
        matched.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in matched[:_MAX_PREREAD_SKILLS]]

    def preread(self, message: str, context: dict | None = None) -> str:
        """预读匹配技能的 SKILL.md 内容

        Returns:
            预读内容字符串，可能为空
        """
        matched_names = self.match_skills(message, context)
        if not matched_names:
            return ""

        skills = self._load_skills()
        parts: list[str] = []
        total_chars = 0

        for name in matched_names:
            skill = skills.get(name)
            if not skill or not skill.content:
                continue

            # 截取技能内容（保留关键部分）
            content = skill.content
            if total_chars + len(content) > _MAX_PREREAD_CHARS:
                # 截断到剩余配额
                remaining = _MAX_PREREAD_CHARS - total_chars
                if remaining < 50:
                    break  # 剩余空间太小，跳过
                content = content[:remaining] + "..."

            header = f"##技能: {name}"
            if skill.description:
                header += f" — {skill.description[:80]}"
            parts.append(f"{header}\n{content}")
            total_chars += len(content) + len(header) + 1

            if total_chars >= _MAX_PREREAD_CHARS:
                break

        return "\n\n".join(parts)

    def preread_for_context_builder(self, message: str, context: dict | None = None) -> str:
        """供 context_builder.py 调用的入口

        返回带标记的完整注入文本，或空字符串。
        空字符串时不生成 system message，零开销。
        """
        content = self.preread(message, context)
        if not content:
            return ""
        return f"<skill_preread>\n{content}\n</skill_preread>"

    def get_matched_names(self, message: str) -> list[str]:
        """返回当前消息匹配的技能名（调试/日志用）"""
        return self.match_skills(message)


# ── 单例 ──

_instance: SkillPrereader | None = None


def get_skill_prereader() -> SkillPrereader:
    """获取 SkillPrereader 单例"""
    global _instance
    if _instance is None:
        _instance = SkillPrereader()
    return _instance
