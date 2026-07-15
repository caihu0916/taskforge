
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Template marketplace data models and enums."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────


class IndustryType(StrEnum):
    """一级分类：行业"""

    ECOMMERCE = "ecommerce"
    SAAS = "saas"
    CONSULTING = "consulting"
    EDUCATION = "education"
    FINANCE = "finance"
    CONTENT = "content"
    CROSS_BORDER = "cross_border"
    FREELANCE = "freelance"


class TemplateCategory(StrEnum):
    """二级分类：角色（沿用 agent_template.py）"""

    MARKETING = "marketing"
    SALES = "sales"
    SERVICE = "service"
    CONTENT = "content"
    ANALYSIS = "analysis"
    DEVELOPMENT = "development"
    OPERATIONS = "operations"
    GENERAL = "general"


class TemplateVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    ORG = "org"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    INSTALLED = "installed"


class SourceType(StrEnum):
    BUILTIN = "builtin"
    YAML = "yaml"
    AGENT = "agent"
    WORKFLOW = "workflow"
    COMMUNITY = "community"


# ── Core Models ────────────────────────────────────────────────────────


class MarketplaceTemplate(BaseModel):
    """模板市场主表模型"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    display_name: str
    description: str = ""
    industry: str = IndustryType.FREELANCE
    category: str = TemplateCategory.GENERAL
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    icon: str = ""
    visibility: str = TemplateVisibility.PUBLIC
    status: str = TemplateStatus.PUBLISHED
    min_platform_version: str = "1.0.0"
    source_type: str = SourceType.BUILTIN
    source_id: str = ""
    config: dict = Field(default_factory=dict)
    skills: list[dict] = Field(default_factory=list)
    workflow_dsl: dict = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)
    download_count: int = 0
    rating_sum: float = 0.0
    rating_count: int = 0
    featured: bool = False
    activated_resource_type: str = ""  # "agent" | "workflow" | ""
    activated_resource_id: str = ""    # agent_name or workflow_id
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    @property
    def rating(self) -> float:
        """计算平均评分"""
        if self.rating_count == 0:
            return 0.0
        return round(self.rating_sum / self.rating_count, 1)


class MarketplaceReview(BaseModel):
    """模板评分评论"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    template_id: str
    user_id: str = ""
    rating: int = Field(ge=1, le=5)
    comment: str = ""
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))


# ── Request Models ─────────────────────────────────────────────────────


class CreateTemplateReq(BaseModel):
    """创建模板请求"""

    name: str
    display_name: str
    description: str = ""
    industry: str = IndustryType.FREELANCE
    category: str = TemplateCategory.GENERAL
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    icon: str = ""
    source_type: str = SourceType.BUILTIN
    source_id: str = ""
    config: dict = Field(default_factory=dict)
    skills: list[dict] = Field(default_factory=list)
    workflow_dsl: dict = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)


class RateTemplateReq(BaseModel):
    """评分请求"""

    rating: int = Field(ge=1, le=5)
    comment: str = ""


class TemplateListReq(BaseModel):
    """模板列表查询参数"""

    industry: str | None = None
    category: str | None = None
    tags: str | None = None  # 逗号分隔
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort: str = "downloads"  # downloads/rating/newest
    q: str | None = None


# ── YAML→Industry 映射 ────────────────────────────────────────────────

YAML_TO_INDUSTRY: dict[str, str] = {
    "finance": IndustryType.FINANCE,
    "ecommerce": IndustryType.ECOMMERCE,
    "content": IndustryType.CONTENT,
    "education": IndustryType.EDUCATION,
    "consultant": IndustryType.CONSULTING,
    "coach": IndustryType.FREELANCE,
    "legal": IndustryType.FREELANCE,
    "handmade": IndustryType.ECOMMERCE,
    "freelance": IndustryType.FREELANCE,
    "service_booking": IndustryType.FREELANCE,
    "office": IndustryType.FREELANCE,
    "local": IndustryType.FREELANCE,
    "livestream": IndustryType.CONTENT,
    "craft": IndustryType.ECOMMERCE,
    "caster": IndustryType.CONTENT,
    "xiaohongshu": IndustryType.CONTENT,
}

# Workflow template key → Industry 映射
WORKFLOW_KEY_TO_INDUSTRY: dict[str, str] = {
    "ecommerce_sop": IndustryType.ECOMMERCE,
    "saas_sop": IndustryType.SAAS,
    "consulting_sop": IndustryType.CONSULTING,
    "education_sop": IndustryType.EDUCATION,
    "cross_border_sop": IndustryType.CROSS_BORDER,
    "code_corps_pipeline": IndustryType.FREELANCE,
    "daily_report": IndustryType.FREELANCE,
    "weekly_review": IndustryType.FREELANCE,
    "marketing_campaign": IndustryType.CONTENT,
    "customer_followup": IndustryType.SAAS,
    "content_pipeline": IndustryType.CONTENT,
    "tax_filing": IndustryType.FINANCE,
    "product_launch": IndustryType.ECOMMERCE,
    "month_end_close": IndustryType.FINANCE,
    "xhs_hot_content": IndustryType.CONTENT,
    "wechat_article_publish": IndustryType.CONTENT,
    "multi_platform_distribute": IndustryType.CONTENT,
    "content_repurpose": IndustryType.CONTENT,
    "content_calendar_planning": IndustryType.CONTENT,
}
