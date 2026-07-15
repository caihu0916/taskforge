
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge PersonalityVariant — 人格变体枚举 + 运行时切换机制

P0-4: 人格变体系统
- 定义多种人格风格（正式、随意、技术、创意等）
- 支持运行时动态切换
- 自动注入到Agent系统提示词

人格变体:
- FORMAL: 正式商务风格
- CASUAL: 轻松随意风格
- TECHNICAL: 技术专家风格
- CREATIVE: 创意风格
- ANALYTICAL: 分析型风格
- EMPATHETIC: 共情风格
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from ._base import AgentRole
from ._role_reminders import get_role_reminder_list

logger = structlog.get_logger(__name__)


class PersonalityVariant(StrEnum):
    """人格变体枚举 — 定义不同的沟通风格"""

    FORMAL = "formal"  # 正式商务风格
    CASUAL = "casual"  # 轻松随意风格
    TECHNICAL = "technical"  # 技术专家风格
    CREATIVE = "creative"  # 创意风格
    ANALYTICAL = "analytical"  # 分析型风格
    EMPATHETIC = "empathetic"  # 共情风格
    DEFAULT = "default"  # 默认风格


@dataclass
class PersonalityProfile:
    """人格配置文件"""

    variant: PersonalityVariant
    name: str
    description: str
    system_prompt_injection: str
    tone_indicators: list[str]
    response_style: dict[str, Any] = field(default_factory=dict)


# 人格配置映射
PERSONALITY_PROFILES: dict[PersonalityVariant, PersonalityProfile] = {
    PersonalityVariant.FORMAL: PersonalityProfile(
        variant=PersonalityVariant.FORMAL,
        name="正式商务",
        description="专业、严谨的商务沟通风格",
        system_prompt_injection="""
你的沟通风格：正式、专业、严谨。
- 使用商务术语和正式表达
- 避免口语化和随意表达
- 保持专业形象和可信度
- 回复结构清晰、逻辑严谨
""",
        tone_indicators=["专业", "严谨", "正式", "规范"],
        response_style={
            "max_length": 500,
            "formality": "high",
            "use_bullets": True,
            "use_headings": True,
        },
    ),
    PersonalityVariant.CASUAL: PersonalityProfile(
        variant=PersonalityVariant.CASUAL,
        name="轻松随意",
        description="友好、亲切的日常沟通风格",
        system_prompt_injection="""
你的沟通风格：轻松、友好、亲切。
- 使用日常口语化表达
- 避免过于正式的术语
- 保持轻松愉快的氛围
- 回复简洁明了、易于理解
""",
        tone_indicators=["友好", "亲切", "轻松", "自然"],
        response_style={
            "max_length": 300,
            "formality": "low",
            "use_bullets": False,
            "use_emojis": True,
        },
    ),
    PersonalityVariant.TECHNICAL: PersonalityProfile(
        variant=PersonalityVariant.TECHNICAL,
        name="技术专家",
        description="深入、专业的技术沟通风格",
        system_prompt_injection="""
你的沟通风格：技术导向、深入专业。
- 使用技术术语和精确表达
- 提供详细的技术分析
- 包含代码示例和技术细节
- 保持技术准确性和专业性
""",
        tone_indicators=["技术", "专业", "深入", "精确"],
        response_style={
            "max_length": 800,
            "formality": "medium",
            "use_bullets": True,
            "use_code_blocks": True,
        },
    ),
    PersonalityVariant.CREATIVE: PersonalityProfile(
        variant=PersonalityVariant.CREATIVE,
        name="创意风格",
        description="富有想象力和创造性的沟通风格",
        system_prompt_injection="""
你的沟通风格：富有创意、充满想象力。
- 使用生动形象的语言
- 鼓励创新和发散思维
- 提供多样化的观点和解决方案
- 保持开放和探索的态度
""",
        tone_indicators=["创意", "创新", "想象", "生动"],
        response_style={
            "max_length": 600,
            "formality": "low",
            "use_bullets": True,
            "use_metaphors": True,
        },
    ),
    PersonalityVariant.ANALYTICAL: PersonalityProfile(
        variant=PersonalityVariant.ANALYTICAL,
        name="分析型",
        description="逻辑严密、数据驱动的分析风格",
        system_prompt_injection="""
你的沟通风格：逻辑严密、数据驱动。
- 基于事实和数据进行分析
- 提供结构化的分析框架
- 明确列出假设和结论
- 保持客观中立的态度
""",
        tone_indicators=["逻辑", "分析", "数据", "客观"],
        response_style={
            "max_length": 700,
            "formality": "high",
            "use_bullets": True,
            "use_data_visualization": True,
        },
    ),
    PersonalityVariant.EMPATHETIC: PersonalityProfile(
        variant=PersonalityVariant.EMPATHETIC,
        name="共情风格",
        description="富有同理心和关怀的沟通风格",
        system_prompt_injection="""
你的沟通风格：富有同理心、关怀体贴。
- 理解并表达用户的感受
- 提供支持和鼓励
- 使用温暖关怀的语言
- 关注用户的情感需求
""",
        tone_indicators=["关怀", "理解", "支持", "温暖"],
        response_style={
            "max_length": 400,
            "formality": "low",
            "use_bullets": False,
            "use_empathetic_language": True,
        },
    ),
    PersonalityVariant.DEFAULT: PersonalityProfile(
        variant=PersonalityVariant.DEFAULT,
        name="默认风格",
        description="平衡适中的默认沟通风格",
        system_prompt_injection="""
你的沟通风格：平衡适中、适应性强。
- 根据上下文调整表达方式
- 保持专业但不失亲和力
- 提供清晰实用的信息
- 确保内容易于理解
""",
        tone_indicators=["平衡", "适中", "实用", "清晰"],
        response_style={
            "max_length": 400,
            "formality": "medium",
            "use_bullets": True,
            "use_headings": False,
        },
    ),
}


class PersonalityManager:
    """人格管理器 — 管理Agent的人格变体和运行时切换"""

    def __init__(self) -> None:
        self._current_variant: PersonalityVariant = PersonalityVariant.DEFAULT
        self._agent_personalities: dict[str, PersonalityVariant] = {}  # agent_id -> variant
        self._initialized = False

    def initialize(self) -> None:
        """初始化人格管理器"""
        if self._initialized:
            return
        self._initialized = True
        logger.info("personality_manager_initialized", default_variant=self._current_variant.value)

    def set_global_variant(self, variant: PersonalityVariant | str) -> None:
        """设置全局默认人格变体

        Args:
            variant: 人格变体枚举值或字符串
        """
        if isinstance(variant, str):
            variant = PersonalityVariant(variant)
        self._current_variant = variant
        logger.info("global_personality_variant_changed", variant=variant.value)

    def get_global_variant(self) -> PersonalityVariant:
        """获取全局默认人格变体"""
        return self._current_variant

    def set_agent_variant(self, agent_id: str, variant: PersonalityVariant | str) -> None:
        """为特定Agent设置人格变体

        Args:
            agent_id: Agent标识
            variant: 人格变体枚举值或字符串
        """
        if isinstance(variant, str):
            variant = PersonalityVariant(variant)
        self._agent_personalities[agent_id] = variant
        logger.info("agent_personality_variant_changed", agent_id=agent_id, variant=variant.value)

    def get_agent_variant(self, agent_id: str) -> PersonalityVariant:
        """获取特定Agent的人格变体（若无则返回全局默认）

        Args:
            agent_id: Agent标识

        Returns:
            PersonalityVariant: 人格变体
        """
        return self._agent_personalities.get(agent_id, self._current_variant)

    def clear_agent_variant(self, agent_id: str) -> None:
        """清除特定Agent的人格变体设置（将使用全局默认）

        Args:
            agent_id: Agent标识
        """
        self._agent_personalities.pop(agent_id, None)
        logger.info("agent_personality_variant_cleared", agent_id=agent_id)

    def get_profile(self, variant: PersonalityVariant | None = None) -> PersonalityProfile:
        """获取人格配置文件

        Args:
            variant: 人格变体（默认为全局默认）

        Returns:
            PersonalityProfile: 人格配置文件
        """
        if variant is None:
            variant = self._current_variant
        return PERSONALITY_PROFILES.get(variant, PERSONALITY_PROFILES[PersonalityVariant.DEFAULT])

    def get_agent_profile(self, agent_id: str) -> PersonalityProfile:
        """获取特定Agent的人格配置文件

        Args:
            agent_id: Agent标识

        Returns:
            PersonalityProfile: 人格配置文件
        """
        variant = self.get_agent_variant(agent_id)
        return self.get_profile(variant)

    def get_prompt_injection(self, agent_id: str | None = None) -> str:
        """获取人格提示词注入内容

        Args:
            agent_id: Agent标识（可选，None表示使用全局默认）

        Returns:
            str: 提示词注入内容
        """
        profile = self.get_agent_profile(agent_id) if agent_id else self.get_profile()
        return profile.system_prompt_injection

    def list_variants(self) -> list[dict[str, Any]]:
        """列出所有可用的人格变体

        Returns:
            list[dict]: 变体列表（包含名称和描述）
        """
        return [
            {
                "variant": variant.value,
                "name": profile.name,
                "description": profile.description,
                "tone_indicators": profile.tone_indicators,
            }
            for variant, profile in PERSONALITY_PROFILES.items()
        ]

    def validate_variant(self, variant_str: str) -> bool:
        """验证人格变体字符串是否有效

        Args:
            variant_str: 变体字符串

        Returns:
            bool: 是否有效
        """
        try:
            PersonalityVariant(variant_str)
            return True
        except ValueError:
            return False

    def get_role_reminders(self, role: AgentRole | str) -> list[str]:
        """获取角色专属安全提醒列表

        Fable 5 模式 D：运行时按角色注入专属安全提醒，
        数据来自 _role_reminders.py ROLE_REMINDERS 映射。

        Args:
            role: AgentRole枚举或角色名字符串

        Returns:
            提醒字符串列表
        """
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                logger.warning("unknown_role_for_reminders", role=role)
                return []
        reminders = get_role_reminder_list(role)
        if reminders:
            logger.debug("role_reminders_loaded", role=role.value, count=len(reminders))
        return reminders

    def get_role_prompt_injection(self, role: AgentRole | str) -> str:
        """获取角色的完整提示词注入：人格风格 + 角色专属提醒

        Args:
            role: AgentRole枚举或角色名字符串

        Returns:
            完整的提示词注入内容
        """
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                role = None

        parts = []
        # 1. 人格风格
        personality = self.get_prompt_injection()
        if personality:
            parts.append(personality.strip())

        # 2. 角色专属提醒
        if role is not None:
            reminders = self.get_role_reminders(role)
            if reminders:
                reminder_text = "\n".join(f"- {r}" for r in reminders)
                parts.append(f"【角色安全提醒】\n{reminder_text}")

        return "\n\n".join(parts)


# 全局单例
_manager: PersonalityManager | None = None


def get_personality_manager() -> PersonalityManager:
    """获取PersonalityManager单例"""
    global _manager
    if _manager is None:
        _manager = PersonalityManager()
        _manager.initialize()
    return _manager


def set_personality_variant(variant: str | PersonalityVariant) -> None:
    """便捷函数：设置全局人格变体"""
    manager = get_personality_manager()
    manager.set_global_variant(variant)


def get_personality_variant() -> PersonalityVariant:
    """便捷函数：获取全局人格变体"""
    manager = get_personality_manager()
    return manager.get_global_variant()


def inject_personality_prompt(agent_id: str | None = None) -> str:
    """便捷函数：获取人格提示词注入"""
    manager = get_personality_manager()
    return manager.get_prompt_injection(agent_id)


def inject_role_reminders(role: AgentRole | str) -> list[str]:
    """便捷函数：获取角色专属安全提醒"""
    manager = get_personality_manager()
    return manager.get_role_reminders(role)


def inject_full_role_prompt(role: AgentRole | str) -> str:
    """便捷函数：获取角色完整提示词(人格+安全提醒)"""
    manager = get_personality_manager()
    return manager.get_role_prompt_injection(role)
