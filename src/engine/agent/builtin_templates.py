
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""内置 Agent 模板(P1-S1-014~016)

提供 5+ 个开箱即用的 Agent 模板:
  - 小红书爆款文案 Agent(营销)
  - CRM 销售跟进 Agent(销售)
  - 智能客服 Agent(客服)
  - 数据分析报告 Agent(分析)
  - 代码审查 Agent(开发)
  - 运维巡检 Agent(运维)

每个模板包含完整的 manifest + config + skills 定义。
"""

from __future__ import annotations

import hashlib

from src.engine.agent.agent_template import (
    AgentTemplate,
    TemplateCategory,
    TemplateManifest,
    TemplateSkill,
    TemplateStatus,
    TemplateVisibility,
)


def _stable_id(name: str) -> str:
    """基于 name 生成稳定的模板 ID(确保幂等)"""
    return hashlib.md5(name.encode("utf-8")).hexdigest()[:12]


def _create_xhs_marketing_template() -> AgentTemplate:
    """小红书爆款文案 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("xhs-marketing-agent"),
        manifest=TemplateManifest(
            name="xhs-marketing-agent",
            display_name="小红书爆款文案 Agent",
            description="自动生成小红书爆款文案,包含标题、正文、标签和封面图描述。支持热点追踪和内容优化。",
            category=TemplateCategory.MARKETING,
            version="1.0.0",
            author="TaskForge",
            tags=["小红书", "文案", "营销", "AI写作"],
            icon="📝",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "xhs_writer",
            "model": "gpt-4o-mini",
            "temperature": 0.8,
            "max_tokens": 2048,
            "system_prompt": "你是小红书爆款文案写手,擅长创作种草干货、生活方式分享类内容。",
        },
        skills=[
            TemplateSkill(
                name="hot_topic_discovery",
                description="发现小红书热门话题",
                tool_ids=["web_search", "xhs_hot_search"],
                prompt_template="搜索小红书热门话题: {{keyword}},返回 top {{limit}} 个话题",
            ),
            TemplateSkill(
                name="content_generation",
                description="生成小红书文案",
                tool_ids=["llm_router"],
                prompt_template=(
                    "主题: {{topic}}\n风格: {{style}}\n生成小红书笔记,包含标题、正文(3-5段,emoji穿插)、标签、封面图描述"
                ),
            ),
            TemplateSkill(
                name="content_review",
                description="内容审核与优化",
                tool_ids=["llm_router"],
                prompt_template="审核以下内容是否符合小红书规范: {{content}}",
            ),
        ],
        variables={
            "keyword": "美妆",
            "limit": "10",
            "style": "种草干货",
        },
    )


def _create_crm_sales_template() -> AgentTemplate:
    """CRM 销售跟进 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("crm-sales-agent"),
        manifest=TemplateManifest(
            name="crm-sales-agent",
            display_name="CRM 销售跟进 Agent",
            description="自动跟进销售线索,生成跟进话术,预测成交概率,提醒关键节点。",
            category=TemplateCategory.SALES,
            version="1.0.0",
            author="TaskForge",
            tags=["CRM", "销售", "跟进", "话术"],
            icon="💼",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "sales_assistant",
            "model": "gpt-4o",
            "temperature": 0.6,
            "system_prompt": "你是资深销售助理,擅长客户跟进、话术生成和成交预测。",
        },
        skills=[
            TemplateSkill(
                name="lead_scoring",
                description="线索评分与优先级排序",
                tool_ids=["crm_api", "llm_router"],
                prompt_template="根据线索信息评分: {{lead_info}}",
            ),
            TemplateSkill(
                name="followup_script",
                description="生成跟进话术",
                tool_ids=["llm_router"],
                prompt_template="客户: {{customer_name}},阶段: {{stage}},生成跟进话术",
            ),
            TemplateSkill(
                name="deal_prediction",
                description="成交概率预测",
                tool_ids=["crm_api", "llm_router"],
                prompt_template="预测成交概率: {{deal_info}}",
            ),
        ],
        variables={
            "stage": "negotiation",
        },
    )


def _create_customer_service_template() -> AgentTemplate:
    """智能客服 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("smart-service-agent"),
        manifest=TemplateManifest(
            name="smart-service-agent",
            display_name="智能客服 Agent",
            description="7x24 智能客服,自动应答常见问题,工单分类,情绪识别,复杂问题转人工。",
            category=TemplateCategory.SERVICE,
            version="1.0.0",
            author="TaskForge",
            tags=["客服", "智能应答", "工单", "情绪识别"],
            icon="🎧",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "customer_service",
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "system_prompt": "你是专业客服,耐心解答用户问题,识别情绪,必要时转人工。",
        },
        skills=[
            TemplateSkill(
                name="intent_recognition",
                description="用户意图识别",
                tool_ids=["llm_router"],
                prompt_template="识别用户意图: {{user_message}}",
            ),
            TemplateSkill(
                name="faq_answer",
                description="FAQ 自动应答",
                tool_ids=["kb_search", "llm_router"],
                prompt_template="基于知识库回答: {{question}}",
            ),
            TemplateSkill(
                name="sentiment_analysis",
                description="情绪识别",
                tool_ids=["llm_router"],
                prompt_template="分析用户情绪: {{user_message}}",
            ),
            TemplateSkill(
                name="ticket_routing",
                description="工单分类与路由",
                tool_ids=["ticket_api"],
                prompt_template="分类工单: {{ticket_content}}",
            ),
        ],
    )


def _create_data_analysis_template() -> AgentTemplate:
    """数据分析报告 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("data-analysis-agent"),
        manifest=TemplateManifest(
            name="data-analysis-agent",
            display_name="数据分析报告 Agent",
            description="自动生成数据分析报告,包含趋势分析、异常检测、可视化建议和行动洞察。",
            category=TemplateCategory.ANALYSIS,
            version="1.0.0",
            author="TaskForge",
            tags=["数据分析", "报告", "可视化", "洞察"],
            icon="📊",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "data_analyst",
            "model": "gpt-4o",
            "temperature": 0.4,
            "system_prompt": "你是资深数据分析师,擅长从数据中提炼洞察并生成结构化报告。",
        },
        skills=[
            TemplateSkill(
                name="trend_analysis",
                description="趋势分析",
                tool_ids=["sql_query", "llm_router"],
                prompt_template="分析数据趋势: {{dataset}}",
            ),
            TemplateSkill(
                name="anomaly_detection",
                description="异常检测",
                tool_ids=["sql_query", "llm_router"],
                prompt_template="检测数据异常: {{dataset}}",
            ),
            TemplateSkill(
                name="report_generation",
                description="生成分析报告",
                tool_ids=["llm_router"],
                prompt_template="基于分析结果生成报告: {{analysis_results}}",
            ),
        ],
    )


def _create_code_review_template() -> AgentTemplate:
    """代码审查 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("code-review-agent"),
        manifest=TemplateManifest(
            name="code-review-agent",
            display_name="代码审查 Agent",
            description="自动审查代码,检查质量、安全、性能问题,提供改进建议和最佳实践。",
            category=TemplateCategory.DEVELOPMENT,
            version="1.0.0",
            author="TaskForge",
            tags=["代码审查", "质量", "安全", "最佳实践"],
            icon="🔍",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "code_reviewer",
            "model": "gpt-4o",
            "temperature": 0.2,
            "system_prompt": "你是资深代码审查员,关注代码质量、安全漏洞、性能问题和最佳实践。",
        },
        skills=[
            TemplateSkill(
                name="quality_check",
                description="代码质量检查",
                tool_ids=["git_api", "llm_router"],
                prompt_template="审查代码质量: {{code_diff}}",
            ),
            TemplateSkill(
                name="security_scan",
                description="安全漏洞扫描",
                tool_ids=["git_api", "llm_router"],
                prompt_template="扫描安全漏洞: {{code_diff}}",
            ),
            TemplateSkill(
                name="best_practices",
                description="最佳实践建议",
                tool_ids=["llm_router"],
                prompt_template="提供最佳实践建议: {{code_diff}}",
            ),
        ],
    )


def _create_ops_inspection_template() -> AgentTemplate:
    """运维巡检 Agent 模板"""
    return AgentTemplate(
        id=_stable_id("ops-inspection-agent"),
        manifest=TemplateManifest(
            name="ops-inspection-agent",
            display_name="运维巡检 Agent",
            description="自动巡检系统健康状态,监控指标异常,生成巡检报告和告警。",
            category=TemplateCategory.OPERATIONS,
            version="1.0.0",
            author="TaskForge",
            tags=["运维", "巡检", "监控", "告警"],
            icon="🛠️",
            visibility=TemplateVisibility.PUBLIC,
            status=TemplateStatus.PUBLISHED,
        ),
        config={
            "role": "ops_inspector",
            "model": "gpt-4o-mini",
            "temperature": 0.3,
            "system_prompt": "你是运维专家,负责系统巡检、异常检测和故障诊断。",
        },
        skills=[
            TemplateSkill(
                name="health_check",
                description="系统健康检查",
                tool_ids=["monitor_api"],
                prompt_template="检查系统健康状态: {{service_name}}",
            ),
            TemplateSkill(
                name="metric_anomaly",
                description="指标异常检测",
                tool_ids=["monitor_api", "llm_router"],
                prompt_template="检测指标异常: {{metrics}}",
            ),
            TemplateSkill(
                name="incident_diagnosis",
                description="故障诊断",
                tool_ids=["log_api", "llm_router"],
                prompt_template="诊断故障原因: {{incident_info}}",
            ),
        ],
    )


# ── 注册内置模板 ──


def get_builtin_templates() -> list[AgentTemplate]:
    """获取所有内置模板"""
    return [
        _create_xhs_marketing_template(),
        _create_crm_sales_template(),
        _create_customer_service_template(),
        _create_data_analysis_template(),
        _create_code_review_template(),
        _create_ops_inspection_template(),
    ]


def register_builtin_templates(store=None) -> int:
    """注册内置模板到存储

    Args:
        store: 模板存储实例(None 则使用全局单例)

    Returns:
        注册的模板数量
    """
    if store is None:
        from src.engine.agent.agent_template import get_template_store

        store = get_template_store()

    count = 0
    for template in get_builtin_templates():
        if not store.exists(template.id):
            store.save(template)
            count += 1

    return count
