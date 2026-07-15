
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA 工作流模板库 — 一人公司常用场景

一站解决: 日报/周报/月报/营销活动/客户跟进/内容生产 等标准工作流
"""

from __future__ import annotations

from typing import Any

import structlog

from src.exceptions import ValidationError

logger = structlog.get_logger(__name__)

# 一人公司 TOP-8 工作流模板
SOLO_TEMPLATES: dict[str, dict[str, Any]] = {
    "daily_report": {
        "name": "每日运营报告",
        "description": "自动汇总昨日收入/支出/客户互动/待办事项",
        "phases": [
            {
                "phase": "plan",
                "name": "数据准备",
                "steps": [
                    {"role": "accountant", "action": "查询昨日交易记录"},
                    {"role": "butler", "action": "统计待办完成情况"},
                ],
            },
            {
                "phase": "do",
                "name": "报表生成",
                "steps": [
                    {"role": "boss", "action": "生成日报摘要 (收入/支出/利润)"},
                    {"role": "analyst", "action": "分析昨日趋势变化"},
                ],
            },
            {
                "phase": "check",
                "name": "质量检查",
                "steps": [
                    {"role": "boss", "action": "核对数据准确性"},
                ],
            },
            {
                "phase": "act",
                "name": "发布",
                "steps": [
                    {"role": "butler", "action": "发送日报到指定邮箱/群"},
                    {"role": "boss", "action": "更新今日待办优先级"},
                ],
            },
        ],
    },
    "weekly_review": {
        "name": "周度复盘",
        "description": "每周自动复盘: KPI/财务/内容/客户",
        "phases": [
            {
                "phase": "plan",
                "name": "数据收集",
                "steps": [
                    {"role": "researcher", "action": "收集本周所有运营数据"},
                    {"role": "accountant", "action": "导出财务周报"},
                ],
            },
            {
                "phase": "do",
                "name": "分析",
                "steps": [
                    {"role": "analyst", "action": "本周KPI vs 目标对比分析"},
                    {"role": "boss", "action": "本周亮点/问题/机会总结"},
                ],
            },
            {
                "phase": "check",
                "name": "验证",
                "steps": [
                    {"role": "boss", "action": "核对数据口径, 确认结论"},
                ],
            },
            {
                "phase": "act",
                "name": "计划",
                "steps": [
                    {"role": "boss", "action": "制定下周目标和工作重点"},
                ],
            },
        ],
    },
    "marketing_campaign": {
        "name": "营销活动",
        "description": "从选题→内容→发布→追踪 全流程",
        "phases": [
            {
                "phase": "plan",
                "name": "选题策划",
                "steps": [
                    {"role": "researcher", "action": "研究热点话题和竞品内容"},
                    {"role": "hitmaker", "action": "选题提案 (3个选题+角度)"},
                ],
            },
            {
                "phase": "do",
                "name": "内容生产",
                "steps": [
                    {"role": "hitmaker", "action": "撰写内容 (文章/视频脚本/图文)"},
                    {"role": "boss", "action": "审核内容质量"},
                ],
            },
            {
                "phase": "check",
                "name": "发布追踪",
                "steps": [
                    {"role": "analyst", "action": "追踪发布24h数据 (阅读/互动/转化)"},
                ],
            },
            {
                "phase": "act",
                "name": "优化",
                "steps": [
                    {"role": "boss", "action": "基于数据优化下期内容策略"},
                ],
            },
        ],
    },
    "customer_followup": {
        "name": "客户跟进",
        "description": "自动客户分阶段跟进流程",
        "phases": [
            {
                "phase": "plan",
                "name": "客户筛选",
                "steps": [
                    {"role": "deal_hunter", "action": "筛选本周需跟进的客户"},
                    {"role": "analyst", "action": "分析客户画像和痛点"},
                ],
            },
            {
                "phase": "do",
                "name": "跟进执行",
                "steps": [
                    {"role": "deal_hunter", "action": "生成个性化跟进消息"},
                    {"role": "butler", "action": "排期提醒和跟进日程"},
                ],
            },
            {
                "phase": "check",
                "name": "效果评估",
                "steps": [
                    {"role": "analyst", "action": "跟进转化率统计"},
                ],
            },
            {
                "phase": "act",
                "name": "策略调整",
                "steps": [
                    {"role": "boss", "action": "调整客户分层和跟进频率"},
                ],
            },
        ],
    },
    "content_pipeline": {
        "name": "内容生产线",
        "description": "选题→AI写作→SEO优化→多平台发布",
        "phases": [
            {
                "phase": "plan",
                "name": "选题",
                "steps": [
                    {"role": "researcher", "action": "分析热搜和长尾关键词"},
                ],
            },
            {
                "phase": "do",
                "name": "生产",
                "steps": [
                    {"role": "hitmaker", "action": "AI撰写初稿"},
                    {"role": "boss", "action": "SEO优化和标题优化"},
                ],
            },
            {
                "phase": "check",
                "name": "审核",
                "steps": [
                    {"role": "compliance", "action": "内容合规检查"},
                    {"role": "boss", "action": "终审发布"},
                ],
            },
            {
                "phase": "act",
                "name": "发布",
                "steps": [
                    {"role": "butler", "action": "多平台发布和排期"},
                ],
            },
        ],
    },
    "tax_filing": {
        "name": "税务申报",
        "description": "月度/季度税务申报工作流",
        "phases": [
            {
                "phase": "plan",
                "name": "数据准备",
                "steps": [
                    {"role": "accountant", "action": "导出本月所有交易和发票"},
                    {"role": "accountant", "action": "核对银行流水"},
                ],
            },
            {
                "phase": "do",
                "name": "税务计算",
                "steps": [
                    {"role": "accountant", "action": "计算增值税/个税/企业所得税"},
                ],
            },
            {
                "phase": "check",
                "name": "审核",
                "steps": [
                    {"role": "boss", "action": "复核税表数据"},
                ],
            },
            {
                "phase": "act",
                "name": "申报",
                "steps": [
                    {"role": "accountant", "action": "生成申报表 → 电子税务局提交"},
                ],
            },
        ],
    },
    "product_launch": {
        "name": "新品上线",
        "description": "从0到1上线新产品/服务",
        "phases": [
            {
                "phase": "plan",
                "name": "规划",
                "steps": [
                    {"role": "boss", "action": "产品定位和定价策略"},
                    {"role": "researcher", "action": "竞品分析和市场验证"},
                ],
            },
            {
                "phase": "do",
                "name": "开发",
                "steps": [
                    {"role": "hitmaker", "action": "产品页面/宣传材料制作"},
                    {"role": "deal_hunter", "action": "渠道准备和预热"},
                ],
            },
            {
                "phase": "check",
                "name": "测试",
                "steps": [
                    {"role": "boss", "action": "内部测试和定价验证"},
                ],
            },
            {
                "phase": "act",
                "name": "发布",
                "steps": [
                    {"role": "butler", "action": "全渠道发布和首日数据监控"},
                ],
            },
        ],
    },
    "month_end_close": {
        "name": "月末结账",
        "description": "每月财务结账全流程",
        "phases": [
            {
                "phase": "plan",
                "name": "准备",
                "steps": [
                    {"role": "accountant", "action": "收集本月所有凭证和账单"},
                ],
            },
            {
                "phase": "do",
                "name": "结账",
                "steps": [
                    {"role": "accountant", "action": "损益结转/成本分摊/折旧计提"},
                    {"role": "accountant", "action": "生成财务报表 (利润表/资产负债表/现金流)"},
                ],
            },
            {
                "phase": "check",
                "name": "对账",
                "steps": [
                    {"role": "boss", "action": "银行对账和应收应付核对"},
                ],
            },
            {
                "phase": "act",
                "name": "归档",
                "steps": [
                    {"role": "accountant", "action": "生成归档文件 + 备份"},
                ],
            },
        ],
    },
    "xhs_hot_content": {
        "name": "小红书热点内容生产线",
        "description": "热点发现→AI撰写→XHS风格优化→审核→真实发布→数据复盘（内容全闭环）",
        "phases": [
            {
                "phase": "plan",
                "name": "热点发现",
                "steps": [
                    {"role": "researcher", "action": "xhs_hot_search", "params": {"keyword": "{keyword}", "limit": 10}},
                ],
            },
            {
                "phase": "do",
                "name": "内容创作",
                "steps": [
                    {
                        "role": "hitmaker",
                        "action": "xhs_content_write",
                        "params": {"topic": "{hot_topic}", "style": "种草干货"},
                    },
                ],
            },
            {
                "phase": "check",
                "name": "审核把关",
                "steps": [
                    {"role": "compliance", "action": "xhs_compliance_check"},
                    {"role": "boss", "action": "content_review"},
                ],
            },
            {
                "phase": "act",
                "name": "发布+复盘",
                "steps": [
                    {"role": "butler", "action": "xhs_real_publish", "params": {"ai_creation": True}},
                    {"role": "analyst", "action": "xhs_performance_review", "params": {"delay_hours": 24}},
                ],
            },
        ],
    },
    "wechat_article_publish": {
        "name": "微信公众号推文生产线",
        "description": "选题→AI撰写→公众号风格适配→合规审查→草稿箱发布（微信全闭环）",
        "phases": [
            {
                "phase": "plan",
                "name": "选题策划",
                "steps": [
                    {"role": "researcher", "action": "搜索行业热点和竞品动态"},
                    {"role": "hitmaker", "action": "基于热点生成3个选题方向"},
                ],
            },
            {
                "phase": "do",
                "name": "内容创作",
                "steps": [
                    {"role": "writer", "action": "撰写公众号长文（标题+摘要+正文+引导互动）"},
                ],
            },
            {
                "phase": "check",
                "name": "审核把关",
                "steps": [
                    {"role": "compliance", "action": "检查广告法违规词和诱导分享"},
                    {"role": "boss", "action": "content_review"},
                ],
            },
            {
                "phase": "act",
                "name": "发布",
                "steps": [
                    {"role": "butler", "action": "提交到公众号草稿箱"},
                ],
            },
        ],
    },
    "multi_platform_distribute": {
        "name": "多平台内容一键分发",
        "description": "一篇内容自动适配小红书/公众号/抖音/B站/微博/知乎6大平台，合规检查后批量发布",
        "phases": [
            {
                "phase": "plan",
                "name": "内容准备",
                "steps": [
                    {"role": "hitmaker", "action": "生成核心内容素材（标题+正文+标签）"},
                ],
            },
            {
                "phase": "do",
                "name": "多平台适配",
                "steps": [
                    {"role": "adapter", "action": "适配小红书风格（emoji+种草标签）"},
                    {"role": "adapter", "action": "适配公众号风格（深度长文）"},
                    {"role": "adapter", "action": "适配抖音风格（短视频脚本）"},
                    {"role": "adapter", "action": "适配B站风格（UP主+弹幕互动）"},
                    {"role": "adapter", "action": "适配微博风格（140字精炼）"},
                    {"role": "adapter", "action": "适配知乎风格（专业回答）"},
                ],
            },
            {
                "phase": "check",
                "name": "合规审查",
                "steps": [
                    {"role": "compliance", "action": "全平台合规检查（广告法+AI标注+平台规则）"},
                    {"role": "boss", "action": "content_review"},
                ],
            },
            {
                "phase": "act",
                "name": "批量发布",
                "steps": [
                    {"role": "butler", "action": "按优先级依次发布到各平台"},
                    {"role": "analyst", "action": "24h后汇总各平台数据表现"},
                ],
            },
        ],
    },
    "content_repurpose": {
        "name": "内容一鱼多吃复用",
        "description": "一篇长文→拆解为多条短视频脚本/图文笔记/朋友圈金句，最大化内容ROI",
        "phases": [
            {
                "phase": "plan",
                "name": "源内容分析",
                "steps": [
                    {"role": "researcher", "action": "识别源内容核心观点和结构"},
                ],
            },
            {
                "phase": "do",
                "name": "内容拆解",
                "steps": [
                    {"role": "hitmaker", "action": "拆出3条短视频脚本（前3秒钩子+核心论点+CTA）"},
                    {"role": "writer", "action": "拆出2条小红书图文笔记（标题+正文+标签）"},
                    {"role": "writer", "action": "拆出5条朋友圈金句（≤200字走心文案）"},
                ],
            },
            {
                "phase": "check",
                "name": "审核",
                "steps": [
                    {"role": "compliance", "action": "检查拆解后内容的合规性"},
                ],
            },
            {
                "phase": "act",
                "name": "分发",
                "steps": [
                    {"role": "butler", "action": "将各条内容排入发布队列"},
                ],
            },
        ],
    },
    "content_calendar_planning": {
        "name": "内容日历规划",
        "description": "根据品牌定位和目标受众，AI生成一周选题+排期+日历同步",
        "phases": [
            {
                "phase": "plan",
                "name": "品牌分析",
                "steps": [
                    {"role": "researcher", "action": "分析品牌调性和目标受众画像"},
                    {"role": "researcher", "action": "调研本周行业热点和竞品动态"},
                ],
            },
            {
                "phase": "do",
                "name": "选题生成",
                "steps": [
                    {"role": "hitmaker", "action": "AI生成10个选题方向（含CTR预估）"},
                    {"role": "boss", "action": "筛选最终选题并确认优先级"},
                ],
            },
            {
                "phase": "check",
                "name": "排期优化",
                "steps": [
                    {"role": "analyst", "action": "根据历史数据推荐最佳发布时间"},
                    {"role": "compliance", "action": "检查选题的合规风险"},
                ],
            },
            {
                "phase": "act",
                "name": "日历同步",
                "steps": [
                    {"role": "butler", "action": "创建内容规划日历并同步到发布排期"},
                    {"role": "butler", "action": "发送本周内容计划到指定群"},
                ],
            },
        ],
    },
}

# ── 行业 SOP 模板 (一人公司常见行业) ──

INDUSTRY_SOP_TEMPLATES: dict[str, dict[str, Any]] = {
    "ecommerce_sop": {
        "name": "电商运营 SOP",
        "description": "选品→上架→推广→订单处理→售后 全流程",
        "phases": [
            {
                "phase": "plan",
                "name": "选品策划",
                "steps": [
                    {"role": "researcher", "action": "分析竞品价格和销量趋势"},
                    {"role": "deal_hunter", "action": "筛选高毛利潜力商品"},
                    {"role": "boss", "action": "确定本周主推品和定价策略"},
                ],
            },
            {
                "phase": "do",
                "name": "运营执行",
                "steps": [
                    {"role": "hitmaker", "action": "制作商品详情页和推广素材"},
                    {"role": "butler", "action": "上架商品并设置促销活动"},
                    {"role": "hitmaker", "action": "投放站内广告和社媒引流"},
                ],
            },
            {
                "phase": "check",
                "name": "数据复盘",
                "steps": [
                    {"role": "analyst", "action": "统计点击率/转化率/ROAS"},
                    {"role": "accountant", "action": "核算单品毛利和库存周转"},
                ],
            },
            {
                "phase": "act",
                "name": "优化迭代",
                "steps": [
                    {"role": "boss", "action": "下架低效品，追加爆品库存"},
                    {"role": "deal_hunter", "action": "联系供应商优化成本和物流"},
                ],
            },
        ],
    },
    "saas_sop": {
        "name": "SaaS 增长 SOP",
        "description": "获客→引导→激活→留存→续费 增长飞轮",
        "phases": [
            {
                "phase": "plan",
                "name": "增长规划",
                "steps": [
                    {"role": "researcher", "action": "分析用户画像和竞品功能"},
                    {"role": "boss", "action": "制定本月增长目标和渠道策略"},
                ],
            },
            {
                "phase": "do",
                "name": "获客转化",
                "steps": [
                    {"role": "hitmaker", "action": "制作产品教程和落地页"},
                    {"role": "deal_hunter", "action": "执行冷启动外展和 demo 预约"},
                    {"role": "butler", "action": "设置 onboarding 邮件序列和产品内引导"},
                ],
            },
            {
                "phase": "check",
                "name": "数据监控",
                "steps": [
                    {"role": "analyst", "action": "追踪注册→激活→付费转化漏斗"},
                    {"role": "analyst", "action": "分析 churn 原因和 NPS 评分"},
                ],
            },
            {
                "phase": "act",
                "name": "留存优化",
                "steps": [
                    {"role": "boss", "action": "决定 feature优先级和定价调整"},
                    {"role": "support", "action": "主动联系高风险流失用户"},
                ],
            },
        ],
    },
    "consulting_sop": {
        "name": "咨询服务 SOP",
        "description": "获客→诊断→提案→交付→收款→转介绍",
        "phases": [
            {
                "phase": "plan",
                "name": "客户筛选",
                "steps": [
                    {"role": "researcher", "action": "研究目标客户行业和痛点"},
                    {"role": "deal_hunter", "action": "筛选高意向线索并准备案例"},
                ],
            },
            {
                "phase": "do",
                "name": "提案交付",
                "steps": [
                    {"role": "boss", "action": "进行客户诊断访谈"},
                    {"role": "hitmaker", "action": "撰写定制化提案和报价"},
                    {"role": "butler", "action": "排期项目里程碑和交付节点"},
                ],
            },
            {
                "phase": "check",
                "name": "质量把控",
                "steps": [
                    {"role": "boss", "action": "审核交付物质量并获取客户反馈"},
                    {"role": "accountant", "action": "追踪项目工时和利润率"},
                ],
            },
            {
                "phase": "act",
                "name": "关系维护",
                "steps": [
                    {"role": "deal_hunter", "action": "跟进转介绍和续约机会"},
                    {"role": "boss", "action": "沉淀方法论，更新服务产品化"},
                ],
            },
        ],
    },
    "education_sop": {
        "name": "在线教育 SOP",
        "description": "课程设计→录制→上架→招生→教学→续报",
        "phases": [
            {
                "phase": "plan",
                "name": "课程规划",
                "steps": [
                    {"role": "researcher", "action": "调研热门课程主题和学员需求"},
                    {"role": "boss", "action": "确定课程大纲和定价策略"},
                ],
            },
            {
                "phase": "do",
                "name": "内容生产",
                "steps": [
                    {"role": "hitmaker", "action": "录制课程视频和配套资料"},
                    {"role": "butler", "action": "上架课程平台并设置营销页"},
                    {"role": "deal_hunter", "action": "启动招生推广和社群预热"},
                ],
            },
            {
                "phase": "check",
                "name": "教学评估",
                "steps": [
                    {"role": "analyst", "action": "统计完课率/作业提交率/学员评分"},
                    {"role": "boss", "action": "收集学员反馈并评估教学效果"},
                ],
            },
            {
                "phase": "act",
                "name": "迭代优化",
                "steps": [
                    {"role": "hitmaker", "action": "更新课程内容和案例"},
                    {"role": "deal_hunter", "action": "设计老学员续报和老带新方案"},
                ],
            },
        ],
    },
    "cross_border_sop": {
        "name": "跨境电商 SOP",
        "description": "选品→采购→上架→推广→物流→VAT 全链路",
        "phases": [
            {
                "phase": "plan",
                "name": "选品调研",
                "steps": [
                    {"role": "researcher", "action": "分析 Amazon/Shopee/Temu 热销品类"},
                    {"role": "deal_hunter", "action": "比价 1688/义乌/越南 供应商"},
                ],
            },
            {
                "phase": "do",
                "name": "上架推广",
                "steps": [
                    {"role": "hitmaker", "action": "制作多语言 listing 和 A+ 页面"},
                    {"role": "butler", "action": "创建 FBA 发货计划和海外仓备货"},
                    {"role": "hitmaker", "action": "设置站内 PPC 广告和站外引流"},
                ],
            },
            {
                "phase": "check",
                "name": "合规风控",
                "steps": [
                    {"role": "compliance", "action": "检查 VAT/EPR/CE 合规状态"},
                    {"role": "accountant", "action": "核算汇率损益和平台费用占比"},
                ],
            },
            {
                "phase": "act",
                "name": "供应链优化",
                "steps": [
                    {"role": "boss", "action": "调整 SKU 结构和目标市场优先级"},
                    {"role": "deal_hunter", "action": "优化物流方案和关税成本"},
                ],
            },
        ],
    },
    # ── 代码师团协作管道 ──
    "code_corps_pipeline": {
        "name": "代码师团协作管道",
        "description": "架构师出方案→审计官审查→前后端并行开发→交叉审计→文档+验收 全流程",
        "phases": [
            {
                "phase": "plan",
                "name": "架构设计",
                "steps": [
                    {"role": "architect", "action": "分析需求，设计系统架构和接口契约"},
                    {"role": "tech_writer", "action": "将架构设计撰写为PRD/技术方案"},
                ],
            },
            {
                "phase": "check",
                "name": "方案审计",
                "steps": [
                    {"role": "code_auditor", "action": "五层门禁预检架构方案: L1存在→L2连通→L3逻辑→L4安全"},
                    {"role": "architect", "action": "根据审计意见修订方案"},
                ],
            },
            {
                "phase": "do",
                "name": "并行开发",
                "steps": [
                    {"role": "backend_dev", "action": "按接口契约开发后端API+数据模型+测试"},
                    {"role": "frontend_dev", "action": "按接口契约开发前端组件+状态管理+API对接"},
                ],
            },
            {
                "phase": "check",
                "name": "交叉审计",
                "steps": [
                    {"role": "code_auditor", "action": "审查后端代码: L1→L5全层门禁"},
                    {"role": "code_auditor", "action": "审查前端代码: L1→L5全层门禁"},
                    {"role": "architect", "action": "确认前后端接口对齐，无契约偏离"},
                ],
            },
            {
                "phase": "act",
                "name": "文档+验收",
                "steps": [
                    {"role": "tech_writer", "action": "撰写API文档+README+Changelog"},
                    {"role": "architect", "action": "最终验收: 功能完整性+代码质量+文档覆盖"},
                ],
            },
        ],
    },
}

# ── 合并查询 ──

_ALL_TEMPLATES = {**SOLO_TEMPLATES, **INDUSTRY_SOP_TEMPLATES}


def get_template(name: str) -> dict[str, Any] | None:
    return _ALL_TEMPLATES.get(name)


def list_templates() -> list[dict[str, str]]:
    return [{"id": k, "name": v["name"], "description": v["description"]} for k, v in _ALL_TEMPLATES.items()]


def create_workflow_from_template(engine, template_id: str, **overrides) -> Any:
    """从模板创建 PDCA Workflow"""
    from src.engine.workflow.models import Phase, PhaseType, Step

    tmpl = get_template(template_id)
    if not tmpl:
        raise ValidationError(f"Template not found: {template_id}")

    phases = []
    for pdef in tmpl["phases"]:
        phase_type_map = {"plan": PhaseType.PLAN, "do": PhaseType.DO, "check": PhaseType.CHECK, "act": PhaseType.ACT}
        steps = [
            Step(name=s["action"][:50], agent_role=s["role"], action=s["action"], params=s.get("params", {}))
            for s in pdef["steps"]
        ]
        phases.append(Phase(phase_type=phase_type_map[pdef["phase"]], name=pdef["name"], steps=steps))

    name = overrides.get("name", tmpl["name"])
    return engine.create_workflow(name=name, description=tmpl["description"], custom_phases=phases)
