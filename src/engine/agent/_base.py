
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Role base types and schema — 枚举 + Pydantic模型."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.engine.agent.a2a.agent_card import AgentCard


class AgentRole(StrEnum):
    """12角色枚举"""

    BOSS = "boss"
    HITMAKER = "hitmaker"
    DEAL_HUNTER = "deal_hunter"
    RESEARCHER = "researcher"
    SUPPORT = "support"
    COMPANION = "companion"
    ACCOUNTANT = "accountant"
    BUTLER = "butler"
    COMPLIANCE = "compliance"
    CASTER = "caster"
    ANALYST = "analyst"
    OPERATOR = "operator"
    # D5-2: 行业 Agency 角色 (Hermes 对标)
    XHS_SPECIALIST = "xhs_specialist"  # 小红书运营
    DOUYIN_SPECIALIST = "douyin_specialist"  # 抖音运营
    CROSS_BORDER = "cross_border"  # 跨境电商
    WECHAT_OA_SPECIALIST = "wechat_oa_specialist"  # 公众号运营
    BILIBILI_SPECIALIST = "bilibili_specialist"  # B站运营
    WEIBO_SPECIALIST = "weibo_specialist"  # 微博运营
    KUAISHOU_SPECIALIST = "kuaishou_specialist"  # 快手运营
    ZHIHU_SPECIALIST = "zhihu_specialist"  # 知乎运营
    PRIVATE_DOMAIN = "private_domain"  # 私域运营
    CHINA_ECOMMERCE = "china_ecommerce"  # 国内电商
    # D5-3: 代码师团 (Code Corps)
    ARCHITECT = "architect"  # 架构师
    CODE_AUDITOR = "code_auditor"  # 审计官
    BACKEND_DEV = "backend_dev"  # 后端研发
    FRONTEND_DEV = "frontend_dev"  # 前端研发
    TECH_WRITER = "tech_writer"  # 技术文案
    DEVELOPER = "developer"  # 代码开发
    QA_ENGINEER = "qa_engineer"  # QA测试
    SEO_SPECIALIST = "seo_specialist"  # SEO专家
    BAIDU_SEO = "baidu_seo"  # 百度SEO
    LIVESTREAM_COACH = "livestream_coach"  # 直播电商
    GROWTH_HACKER = "growth_hacker"  # 增长黑客
    CONTENT_CREATOR = "content_creator"  # 内容创作者
    # G02-T03: 角色编排四角色 (Planner→Coder→Reviewer→Documenter)
    PLANNER = "planner"  # 规划师
    CODER = "coder"  # 编码师
    REVIEWER = "reviewer"  # 审查师
    DOCUMENTER = "documenter"  # 文档师
    # P3-02: 对抗性验证 Agent (独立于 REVIEWER, 专责红队/幻觉检测)
    VERIFICATION = "verification"  # 验证师


class Capability(StrEnum):
    """角色能力标签"""

    DECISION = "decision"
    PLANNING = "planning"
    DELEGATION = "delegation"
    WRITING = "writing"
    DESIGN = "design"
    PLATFORM_OPS = "platform_ops"
    SEO = "seo"
    SELLING = "selling"
    NEGOTIATION = "negotiation"
    CRM = "crm"
    LEAD_CAPTURE = "lead_capture"
    FOLLOW_UP = "follow_up"
    # 代码师团能力
    CODE_WRITE = "code_write"
    CODE_TEST = "code_test"
    CODE_REVIEW = "code_review"
    ARCHITECTURE = "architecture"
    TECH_DOCS = "tech_docs"
    FRONTEND = "frontend"
    BACKEND = "backend"
    FUNNEL = "funnel"
    REPURCHASE = "repurchase"
    BILLING = "billing"
    COLLECTION = "collection"
    ACCOUNTING = "accounting"
    TAX = "tax"
    SCHEDULING = "scheduling"
    CS = "cs"
    DATA_ENTRY = "data_entry"
    REVIEW = "review"
    RISK = "risk"
    # P3-02: 对抗性验证能力
    VERIFICATION = "verification"
    LEGAL = "legal"
    WEB_SCRAPE = "web_scrape"
    DATA_COLLECTION = "data_collection"
    ANALYSIS = "analysis"
    MARKET_RESEARCH = "market_research"
    CS_CHAT = "cs_chat"
    ISSUE_TRIAGE = "issue_triage"
    REFUND = "refund"
    ESCALATION = "escalation"
    LIVE_STREAM = "live_stream"
    PRODUCT_SHOW = "product_show"
    INTERACTION = "interaction"
    LIVE_CRISIS = "live_crisis"
    LIVE_REVIEW = "live_review"
    FORECASTING = "forecasting"
    ANOMALY_DETECTION = "anomaly_detection"
    DASHBOARD = "dashboard"
    DATA_VISUALIZATION = "data_visualization"
    REPORT = "report"
    # 桌面自动化
    SCREEN_CAPTURE = "screen_capture"
    MOUSE_CONTROL = "mouse_control"
    KEYBOARD_CONTROL = "keyboard_control"
    WINDOW_MANAGEMENT = "window_management"
    GUI_AUTOMATION = "gui_automation"


class RoleDefinition(BaseModel):
    """角色定义 — 包含身份、能力、系统提示词模板、通道策略覆盖"""

    role: AgentRole = Field(description="角色枚举")
    name_cn: str = Field(description="中文名")
    name_en: str = Field(description="英文名")
    emoji: str = Field(default="", description="角色图标")
    capabilities: list[Capability] = Field(default_factory=list, description="能力标签")
    priority: int = Field(default=1, ge=0, le=5, description="优先级 (0最低,5最高)")
    system_prompt_template: str = Field(default="", description="系统提示词模板")
    channel_overrides: dict[str, dict] = Field(
        default_factory=dict,
        description="通道策略覆盖, key=通道名(feishu/wechat/dingtalk), value=策略字段",
        examples=[{"feishu": {"dm_policy": "allowlist", "allow_from": ["ou_xxx"]}}],
    )
    # A2A Agent Card (P1-S1-006)
    agent_card: AgentCard | None = Field(
        default=None,
        description="A2A Agent Card 元数据,描述 Agent 的能力和工具列表",
    )

    model_config = {"frozen": True}


def _rebuild_model() -> None:
    from src.engine.agent.a2a.agent_card import AgentCard  # noqa: F401 — required for RoleDefinition.model_rebuild()

    RoleDefinition.model_rebuild()


_rebuild_model()
