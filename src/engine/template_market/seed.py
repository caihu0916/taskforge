
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Seed marketplace_templates from existing template subsystems."""

from __future__ import annotations

import structlog

from src.engine.template_market.manager import get_template_market_manager
from src.engine.template_market.models import (
    WORKFLOW_KEY_TO_INDUSTRY,
    YAML_TO_INDUSTRY,
    IndustryType,
    MarketplaceTemplate,
    SourceType,
    TemplateCategory,
)

logger = structlog.get_logger(__name__)


def _skill_to_dict(skill) -> dict:
    """TemplateSkill (dataclass) → dict"""
    try:
        from dataclasses import asdict
        return asdict(skill)
    except Exception:
        return {"name": getattr(skill, "name", ""), "description": getattr(skill, "description", "")}


def seed_marketplace() -> int:
    """启动时注册现有模板到 marketplace。返回新注册数量。"""
    mgr = get_template_market_manager()
    count = 0

    # 1. 从 builtin agent templates 注册
    count += _seed_builtin_agents(mgr)

    # 2. 从 YAML templates/ 目录注册
    count += _seed_yaml_templates(mgr)

    # 3. 从 workflow template_library 注册
    count += _seed_workflow_templates(mgr)

    # 4. 从 role_template_market 注册10个角色模板
    count += _seed_role_templates(mgr)

    logger.info("marketplace_seeded", new_count=count)
    return count


def _seed_builtin_agents(mgr) -> int:
    """注册6个内置Agent模板"""
    try:
        from src.engine.agent.agent_template import TemplateStore
        from src.engine.agent.builtin_templates import register_builtin_templates
    except ImportError:
        logger.debug("builtin_templates_not_available")
        return 0

    # 获取已注册的builtin模板
    store = TemplateStore()
    register_builtin_templates(store)
    count = 0

    for tpl in store.list():
        # 检查是否已存在（通过source_id去重）
        existing = mgr.list_items(filters={"source_id": tpl.id}, limit=1)
        if existing:
            continue

        template = MarketplaceTemplate(
            id=f"agent-{tpl.id}",
            name=tpl.manifest.name if tpl.manifest else tpl.id,
            display_name=tpl.manifest.display_name if tpl.manifest else tpl.id,
            description=tpl.manifest.description if tpl.manifest else "",
            industry=IndustryType.FREELANCE,
            category=tpl.manifest.category if tpl.manifest else TemplateCategory.GENERAL,
            version=tpl.manifest.version if tpl.manifest else "1.0.0",
            author=tpl.manifest.author if tpl.manifest else "",
            tags=tpl.manifest.tags if tpl.manifest else [],
            icon=tpl.manifest.icon if tpl.manifest else "",
            source_type=SourceType.AGENT,
            source_id=tpl.id,
            config=tpl.config,
            skills=[_skill_to_dict(s) for s in tpl.skills],
            variables=tpl.variables,
        )
        mgr.create(template)
        count += 1

    return count


def _seed_yaml_templates(mgr) -> int:
    """注册15个YAML场景模板"""
    try:
        from src.infra.template.registry import get_template_registry
    except ImportError:
        logger.debug("yaml_registry_not_available")
        return 0

    registry = get_template_registry()  # 单例，已自动 load_all()
    count = 0

    for manifest in registry.list_templates():
        # 检查是否已存在
        existing = mgr.list_items(filters={"source_id": manifest.id}, limit=1)
        if existing:
            continue

        industry = YAML_TO_INDUSTRY.get(manifest.category, IndustryType.FREELANCE)

        template = MarketplaceTemplate(
            id=f"yaml-{manifest.id}",
            name=manifest.id,
            display_name=manifest.name,
            description=manifest.description,
            industry=industry,
            category=TemplateCategory.GENERAL,
            version=manifest.version,
            tags=manifest.tags if hasattr(manifest, "tags") else [],
            icon=manifest.icon if hasattr(manifest, "icon") else "",
            source_type=SourceType.YAML,
            source_id=manifest.id,
        )
        mgr.create(template)
        count += 1

    return count


def _seed_workflow_templates(mgr) -> int:
    """注册18个workflow模板"""
    try:
        from src.engine.workflow.template_library import INDUSTRY_SOP_TEMPLATES, SOLO_TEMPLATES
    except ImportError:
        logger.debug("workflow_templates_not_available")
        return 0

    count = 0
    all_templates = {**SOLO_TEMPLATES, **INDUSTRY_SOP_TEMPLATES}

    for key, tpl_data in all_templates.items():
        # 检查是否已存在
        existing = mgr.list_items(filters={"source_id": key}, limit=1)
        if existing:
            continue

        industry = WORKFLOW_KEY_TO_INDUSTRY.get(key, IndustryType.FREELANCE)
        name = tpl_data.get("name", key)
        description = tpl_data.get("description", "")

        template = MarketplaceTemplate(
            id=f"wf-{key}",
            name=key,
            display_name=name,
            description=description,
            industry=industry,
            category=TemplateCategory.OPERATIONS,
            source_type=SourceType.WORKFLOW,
            source_id=key,
            featured=1 if key in INDUSTRY_SOP_TEMPLATES else 0,
        )
        mgr.create(template)
        count += 1

    return count


# ── RoleCategory → IndustryType / TemplateCategory 映射 ────────────────

_ROLE_TO_INDUSTRY = {
    "sales": IndustryType.FREELANCE,
    "service": IndustryType.FREELANCE,
    "finance": IndustryType.FINANCE,
    "hr": IndustryType.FREELANCE,
    "data": IndustryType.SAAS,
    "operations": IndustryType.FREELANCE,
    "product": IndustryType.SAAS,
    "legal": IndustryType.CONSULTING,
    "tech": IndustryType.SAAS,
    "marketing": IndustryType.CONTENT,
}

_ROLE_TO_TEMPLATE_CATEGORY = {
    "sales": TemplateCategory.SALES,
    "service": TemplateCategory.SERVICE,
    "finance": TemplateCategory.ANALYSIS,
    "hr": TemplateCategory.OPERATIONS,
    "data": TemplateCategory.ANALYSIS,
    "operations": TemplateCategory.OPERATIONS,
    "product": TemplateCategory.GENERAL,
    "legal": TemplateCategory.GENERAL,
    "tech": TemplateCategory.DEVELOPMENT,
    "marketing": TemplateCategory.MARKETING,
}


def _seed_role_templates(mgr) -> int:
    """注册10个角色模板（from role_template_market）"""
    try:
        from src.engine.agent.role_template_market import RoleTemplateMarket
    except ImportError:
        logger.debug("role_template_market_not_available")
        return 0

    market = RoleTemplateMarket()
    count = 0

    for role_tpl in market.list_templates():
        # 去重：通过 source_id 检查
        existing = mgr.list_items(filters={"source_id": role_tpl.template_id}, limit=1)
        if existing:
            continue

        industry = _ROLE_TO_INDUSTRY.get(role_tpl.category, IndustryType.FREELANCE)
        category = _ROLE_TO_TEMPLATE_CATEGORY.get(role_tpl.category, TemplateCategory.GENERAL)

        template = MarketplaceTemplate(
            id=f"role-{role_tpl.template_id}",
            name=role_tpl.template_id,
            display_name=role_tpl.name,
            description=role_tpl.description,
            industry=industry,
            category=category,
            version="1.0.0",
            author="TaskForge",
            tags=role_tpl.skills,
            icon="🤖",
            source_type=SourceType.AGENT,
            source_id=role_tpl.template_id,
            config={
                "system_prompt": role_tpl.system_prompt,
                "welcome_message": role_tpl.welcome_message,
                "tone": role_tpl.tone,
                "language": role_tpl.language,
            },
            skills=[{"name": s} for s in role_tpl.skills],
            variables=dict.fromkeys(role_tpl.tools, ""),
        )
        mgr.create(template)
        count += 1

    return count
