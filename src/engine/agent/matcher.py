
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 角色任务匹配引擎 — 根据任务关键词自动匹配最佳角色

设计决策:
  - 基于能力标签匹配 + 关键词加权
  - 支持多角色推荐 (按匹配度排序)
  - 规则可扩展 (后续可从YAML加载)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .roles import ROLE_DEFINITIONS, AgentRole, Capability, RoleDefinition

# 任务关键词 -> 能力映射规则
KEYWORD_CAPABILITY_MAP: dict[str, list[Capability]] = {
    # 内容创作
    "写": [Capability.WRITING],
    "文案": [Capability.WRITING, Capability.SEO],
    "笔记": [Capability.WRITING, Capability.PLATFORM_OPS],
    "文章": [Capability.WRITING],
    "脚本": [Capability.WRITING, Capability.DESIGN],
    "标题": [Capability.WRITING, Capability.SEO],
    "封面": [Capability.DESIGN],
    "发布": [Capability.PLATFORM_OPS],
    # D5-2: 行业 Agency 关键词
    "小红书": [Capability.PLATFORM_OPS, Capability.WRITING],
    "种草": [Capability.WRITING, Capability.PLATFORM_OPS],
    "抖音": [Capability.PLATFORM_OPS, Capability.DESIGN],
    "短视频": [Capability.DESIGN, Capability.PLATFORM_OPS],
    "跨境电商": [Capability.SELLING, Capability.PLATFORM_OPS],
    "跨境": [Capability.SELLING],
    "选品": [Capability.SELLING],
    "公众号": [Capability.PLATFORM_OPS, Capability.WRITING],
    "视频": [Capability.DESIGN, Capability.PLATFORM_OPS],
    # 销售
    "卖": [Capability.SELLING],
    "成交": [Capability.SELLING, Capability.CRM],
    "客户": [Capability.CRM, Capability.SELLING],
    "跟进": [Capability.CRM, Capability.SELLING],
    "转化": [Capability.SELLING],
    "漏斗": [Capability.SELLING],
    "促销": [Capability.SELLING, Capability.PLATFORM_OPS],
    # 财务
    "账单": [Capability.BILLING],
    "收款": [Capability.BILLING, Capability.COLLECTION],
    "催款": [Capability.COLLECTION],
    "记账": [Capability.ACCOUNTING],
    "成本": [Capability.ACCOUNTING],
    "税务": [Capability.TAX, Capability.ACCOUNTING],
    "发票": [Capability.BILLING, Capability.TAX],
    "对账": [Capability.ACCOUNTING],
    "核销": [Capability.ACCOUNTING],
    # 运维
    "排程": [Capability.SCHEDULING],
    "安排": [Capability.SCHEDULING],
    "客服": [Capability.CS],
    "回复": [Capability.CS],
    "录入": [Capability.DATA_ENTRY],
    "整理": [Capability.DATA_ENTRY],
    "提醒": [Capability.SCHEDULING],
    # 合规
    "审核": [Capability.REVIEW],
    "合规": [Capability.REVIEW, Capability.RISK],
    "风险": [Capability.RISK],
    "法务": [Capability.LEGAL],
    "合同": [Capability.LEGAL, Capability.REVIEW],
    "广告法": [Capability.REVIEW, Capability.LEGAL],
    # 决策
    "决策": [Capability.DECISION],
    "战略": [Capability.DECISION, Capability.PLANNING],
    "规划": [Capability.PLANNING],
    "分配": [Capability.DELEGATION],
}


@dataclass
class RoleMatch:
    """角色匹配结果"""

    role: AgentRole
    score: float = 0.0
    matched_capabilities: list[Capability] = field(default_factory=list)

    @property
    def definition(self) -> RoleDefinition:
        return ROLE_DEFINITIONS[self.role]


class RoleMatcher:
    """角色-任务匹配引擎

    用法:
        matcher = RoleMatcher()
        matches = matcher.match("帮我写一篇小红书笔记")
        best = matches[0]  #爆款制造机
    """

    def __init__(
        self,
        keyword_map: dict[str, list[Capability]] | None = None,
        role_override: dict[AgentRole, list[Capability]] | None = None,
    ) -> None:
        self._keyword_map = keyword_map or KEYWORD_CAPABILITY_MAP
        # 允许运行时覆盖角色的能力标签
        self._role_caps: dict[AgentRole, list[Capability]] = {}
        for role, defn in ROLE_DEFINITIONS.items():
            self._role_caps[role] = list(defn.capabilities)
        if role_override:
            self._role_caps.update(role_override)

    def match(self, task_text: str, *, top_k: int = 3, min_score: float = 0.1) -> list[RoleMatch]:
        """匹配任务文本到角色

        Args:
            task_text: 任务描述文本
            top_k: 返回前K个匹配
            min_score: 最低匹配分数阈值

        Returns:
            按 score 降序排列的 RoleMatch 列表
        """
        # 1. 从任务文本提取所需能力
        required_caps = self._extract_capabilities(task_text)
        if not required_caps:
            # 无关键词命中 → 默认推荐掌柜(总调度)
            return [RoleMatch(role=AgentRole.BOSS, score=0.5)]

        # 2. 对每个角色计算匹配分数
        matches: list[RoleMatch] = []
        for role, caps in self._role_caps.items():
            matched = [c for c in required_caps if c in caps]
            if not matched:
                continue
            score = len(matched) / len(required_caps)
            # 优先级加权: 高优先级角色微调加分
            priority_bonus = ROLE_DEFINITIONS[role].priority * 0.02
            score = min(1.0, score + priority_bonus)
            if score >= min_score:
                matches.append(
                    RoleMatch(
                        role=role,
                        score=round(score, 3),
                        matched_capabilities=matched,
                    )
                )

        # 3. 排序并截断
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_k]

    def _extract_capabilities(self, text: str) -> list[Capability]:
        """从文本提取所需能力"""
        caps: list[Capability] = []
        for keyword, keyword_caps in self._keyword_map.items():
            if keyword in text:
                caps.extend(keyword_caps)
        # 去重
        seen = set()
        unique = []
        for c in caps:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def add_keyword(self, keyword: str, capabilities: list[Capability]) -> None:
        """扩展关键词映射"""
        self._keyword_map[keyword] = capabilities
