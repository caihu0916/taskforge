
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent角色模板市场 (P1-S1-010)

提供10个预置Agent角色模板:
  - 销售顾问、客服、财务分析师、HR专员
  - 数据分析师、运营专员、产品经理
  - 法务顾问、技术支持、市场营销

设计原则:
  - 单一职责: 仅负责角色模板管理
  - 铁律9: 模块 < 300行
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RoleCategory(StrEnum):
    """角色类别"""

    SALES = "sales"  # 销售
    SERVICE = "service"  # 客服
    FINANCE = "finance"  # 财务
    HR = "hr"  # 人事
    DATA = "data"  # 数据
    OPERATIONS = "operations"  # 运营
    PRODUCT = "product"  # 产品
    LEGAL = "legal"  # 法务
    TECH = "tech"  # 技术
    MARKETING = "marketing"  # 市场


@dataclass
class RoleTemplate:
    """角色模板"""

    template_id: str
    name: str
    category: RoleCategory
    description: str = ""
    system_prompt: str = ""  # 系统提示词
    welcome_message: str = ""  # 欢迎语
    skills: list[str] = field(default_factory=list)  # 技能列表
    tools: list[str] = field(default_factory=list)  # 工具列表
    tone: str = "professional"  # 语气
    language: str = "zh-CN"
    examples: list[dict[str, str]] = field(default_factory=list)  # 示例对话
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    downloads: int = 0
    rating: float = 0.0


class RoleTemplateMarket:
    """Agent角色模板市场 (P1-S1-010)"""

    def __init__(self) -> None:
        self._templates: dict[str, RoleTemplate] = {}
        self._counter = 0
        self._init_default_templates()
        # 默认模板已用 ROLE-0001~0010，计数器从10开始
        self._counter = 10

    def gen_template_id(self) -> str:
        self._counter += 1
        return f"ROLE-{self._counter:04d}"

    def _init_default_templates(self) -> None:
        """初始化10个默认角色模板"""
        defaults = [
            RoleTemplate(
                template_id="ROLE-0001",
                name="销售顾问",
                category=RoleCategory.SALES,
                description="专业的销售顾问，擅长客户沟通、需求挖掘、方案推荐",
                system_prompt="你是一名专业的销售顾问，擅长挖掘客户需求、推荐合适方案、促成交易。",
                welcome_message="您好！我是您的专属销售顾问，有什么可以帮您的吗？",
                skills=["需求挖掘", "方案推荐", "异议处理", "成交技巧"],
                tools=["CRM查询", "报价生成", "合同模板"],
                tone="enthusiastic",
            ),
            RoleTemplate(
                template_id="ROLE-0002",
                name="客服专员",
                category=RoleCategory.SERVICE,
                description="贴心的客服专员，耐心解答问题、处理投诉",
                system_prompt="你是一名专业的客服专员，耐心解答客户问题，妥善处理投诉。",
                welcome_message="您好！很高兴为您服务，请问有什么可以帮您？",
                skills=["问题解答", "投诉处理", "情绪安抚", "工单创建"],
                tools=["知识库查询", "工单系统", "SLA查询"],
                tone="friendly",
            ),
            RoleTemplate(
                template_id="ROLE-0003",
                name="财务分析师",
                category=RoleCategory.FINANCE,
                description="专业的财务分析师，擅长财务报表分析、预算管理",
                system_prompt="你是一名专业的财务分析师，擅长财务分析、预算管理、风险评估。",
                welcome_message="您好！我是财务分析师，可以为您提供专业的财务分析服务。",
                skills=["报表分析", "预算编制", "成本控制", "风险评估"],
                tools=["财务系统", "报表生成", "税务计算"],
                tone="professional",
            ),
            RoleTemplate(
                template_id="ROLE-0004",
                name="HR专员",
                category=RoleCategory.HR,
                description="专业的人事专员，处理员工关系、薪酬福利",
                system_prompt="你是一名专业的HR专员，擅长员工关系管理、薪酬福利、招聘培训。",
                welcome_message="您好！我是HR专员，有人事相关问题可以咨询我。",
                skills=["员工关系", "薪酬管理", "招聘培训", "绩效管理"],
                tools=["人事系统", "薪酬计算", "考勤查询"],
                tone="empathetic",
            ),
            RoleTemplate(
                template_id="ROLE-0005",
                name="数据分析师",
                category=RoleCategory.DATA,
                description="资深数据分析师，擅长数据挖掘、可视化、商业洞察",
                system_prompt="你是一名资深数据分析师，擅长数据挖掘、可视化分析、提供商业洞察。",
                welcome_message="您好！我是数据分析师，可以帮您从数据中发现价值。",
                skills=["数据清洗", "统计分析", "可视化", "商业洞察"],
                tools=["SQL查询", "BI工具", "Python分析"],
                tone="analytical",
            ),
            RoleTemplate(
                template_id="ROLE-0006",
                name="运营专员",
                category=RoleCategory.OPERATIONS,
                description="经验丰富的运营专员，擅长用户运营、活动策划",
                system_prompt="你是一名经验丰富的运营专员，擅长用户运营、活动策划、数据分析。",
                welcome_message="您好！我是运营专员，可以协助您策划运营活动。",
                skills=["用户运营", "活动策划", "内容运营", "数据分析"],
                tools=["运营平台", "数据看板", "推送系统"],
                tone="energetic",
            ),
            RoleTemplate(
                template_id="ROLE-0007",
                name="产品经理",
                category=RoleCategory.PRODUCT,
                description="资深产品经理，擅长需求分析、产品设计、项目管理",
                system_prompt="你是一名资深产品经理，擅长需求分析、产品设计、项目推进。",
                welcome_message="您好！我是产品经理，可以协助您进行产品规划。",
                skills=["需求分析", "产品设计", "项目管理", "用户研究"],
                tools=["原型工具", "需求文档", "项目看板"],
                tone="structured",
            ),
            RoleTemplate(
                template_id="ROLE-0008",
                name="法务顾问",
                category=RoleCategory.LEGAL,
                description="专业法务顾问，擅长合同审查、合规咨询",
                system_prompt="你是一名专业法务顾问，擅长合同审查、合规咨询、风险防范。",
                welcome_message="您好！我是法务顾问，可以为您提供法律咨询。",
                skills=["合同审查", "合规咨询", "风险防范", "法律文书"],
                tools=["法规库", "合同模板", "案例库"],
                tone="rigorous",
            ),
            RoleTemplate(
                template_id="ROLE-0009",
                name="技术支持",
                category=RoleCategory.TECH,
                description="专业的技术支持工程师，擅长问题诊断、故障排查",
                system_prompt="你是一名专业的技术支持工程师，擅长问题诊断、故障排查、方案提供。",
                welcome_message="您好！我是技术支持，遇到技术问题可以找我。",
                skills=["问题诊断", "故障排查", "方案提供", "知识库维护"],
                tools=["工单系统", "知识库", "远程协助"],
                tone="patient",
            ),
            RoleTemplate(
                template_id="ROLE-0010",
                name="市场营销",
                category=RoleCategory.MARKETING,
                description="创意的市场营销专家，擅长品牌推广、内容营销",
                system_prompt="你是一名创意的市场营销专家，擅长品牌推广、内容营销、活动策划。",
                welcome_message="您好！我是市场营销专家，可以协助您制定营销策略。",
                skills=["品牌推广", "内容营销", "活动策划", "渠道运营"],
                tools=["营销平台", "数据分析", "设计工具"],
                tone="creative",
            ),
        ]
        for template in defaults:
            template.created_at = datetime.now(UTC).isoformat()
            self._templates[template.template_id] = template

    def add_template(self, template: RoleTemplate) -> bool:
        if not template.template_id:
            template.template_id = self.gen_template_id()
        if template.template_id in self._templates:
            return False
        if not template.created_at:
            template.created_at = datetime.now(UTC).isoformat()
        self._templates[template.template_id] = template
        return True

    def get_template(self, template_id: str) -> RoleTemplate | None:
        return self._templates.get(template_id)

    def list_templates(self, category: RoleCategory | None = None) -> list[RoleTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return sorted(templates, key=lambda t: t.downloads, reverse=True)

    def search_templates(self, keyword: str) -> list[RoleTemplate]:
        """搜索模板"""
        keyword_lower = keyword.lower()
        results: list[RoleTemplate] = []
        for t in self._templates.values():
            if (
                keyword_lower in t.name.lower()
                or keyword_lower in t.description.lower()
                or any(keyword_lower in s.lower() for s in t.skills)
            ):
                results.append(t)
        return results

    def download_template(self, template_id: str) -> RoleTemplate | None:
        """下载模板(增加下载数)"""
        template = self._templates.get(template_id)
        if not template:
            return None
        template.downloads += 1
        return template

    def rate_template(self, template_id: str, rating: float) -> bool:
        """评分"""
        if not 0 <= rating <= 5:
            return False
        template = self._templates.get(template_id)
        if not template:
            return False
        # 简单平均
        if template.rating == 0:
            template.rating = rating
        else:
            template.rating = (template.rating + rating) / 2
        return True

    def get_categories(self) -> list[RoleCategory]:
        """获取所有类别"""
        return list({t.category for t in self._templates.values()})

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_templates": len(self._templates),
            "total_categories": len(self.get_categories()),
            "total_downloads": sum(t.downloads for t in self._templates.values()),
            "avg_rating": sum(t.rating for t in self._templates.values()) / len(self._templates)
            if self._templates
            else 0,
        }
