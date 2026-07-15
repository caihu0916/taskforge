
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Chat 专家Agent智能分发 — (agent_role + 意图) → SpecialistAgent

在 Chat 对话中, 当用户选了角色且其意图匹配到某个专业 Agent 时,
自动注入该 Agent 的领域知识(system_prompt + workflow + rules),
让通用Chat对话拥有专业Agent的领域深度。

与 AgentDispatcher(后台任务轮询) 互补:
  - AgentDispatcher: 后台任务 → SpecialistAgent → execute()
  - ChatAgentDispatch: 实时Chat → SpecialistAgent → 注入领域上下文

优化增强:
  - 集成智能意图引擎，支持语义理解和实体提取
  - 支持多意图识别和置信度评估
  - 上下文感知的意图匹配
"""

from __future__ import annotations

import structlog

from src.engine.agent.intent_engine import IntentType, get_intent_engine

logger = structlog.get_logger(__name__)


# ── 分发表: (agent_role, 关键词集合) → specialist_agent_name ──
# 匹配规则: agent_role 完全匹配 + user_msg 包含关键词
# 优先级: 列表顺序, 先匹配先命中

_DISPATCH_TABLE: list[dict[str, str | set[str]]] = [
    # ── hitmaker (爆款制造机) → 营销师团 ──
    {"role": "hitmaker", "keywords": {"小红书", "种草", "笔记", "redbook"}, "agent": "agency-xiaohongshu"},
    {"role": "hitmaker", "keywords": {"抖音", "短视频", "DOU+", "douyin"}, "agent": "agency-douyin"},
    {"role": "hitmaker", "keywords": {"直播", "带货", "直播间"}, "agent": "agency-livestream"},
    {"role": "hitmaker", "keywords": {"私域", "企微", "社群", "SCRM"}, "agent": "agency-private-domain"},
    {"role": "hitmaker", "keywords": {"公众号", "微信文章", "订阅号"}, "agent": "agency-wechat-oa"},
    {"role": "hitmaker", "keywords": {"微博", "热搜", "超话"}, "agent": "agency-weibo"},
    {"role": "hitmaker", "keywords": {"B站", "哔哩哔哩", "bilibili"}, "agent": "agency-bilibili"},
    {"role": "hitmaker", "keywords": {"知乎", "问答", "知识营销"}, "agent": "agency-zhihu"},
    {"role": "hitmaker", "keywords": {"快手", "老铁"}, "agent": "agency-kuaishou"},
    {"role": "hitmaker", "keywords": {"SEO", "搜索优化", "排名", "百度SEO"}, "agent": "agency-baidu-seo"},
    {"role": "hitmaker", "keywords": {"跨境", "出海", "amazon", "temu", "shopee"}, "agent": "agency-cross-border"},
    {
        "role": "hitmaker",
        "keywords": {"电商", "淘宝", "天猫", "拼多多", "京东", "大促", "618", "双11"},
        "agent": "agency-domestic-ecom",
    },
    {"role": "hitmaker", "keywords": {"增长", "获客", "裂变", "病毒循环"}, "agent": "agency-growth"},
    {
        "role": "hitmaker",
        "keywords": {"内容策略", "编辑日历", "品牌叙事", "内容矩阵"},
        "agent": "agency-content-strategy",
    },
    {"role": "hitmaker", "keywords": {"SEO优化", "技术SEO", "链接建设"}, "agent": "agency-seo"},
    # ── accountant (账房) → 财务师团 ──
    {"role": "accountant", "keywords": {"月结", "结账", "月末", "月报"}, "agent": "agency-bookkeeper"},
    {"role": "accountant", "keywords": {"税务", "合规", "税率", "发票", "申报"}, "agent": "agency-tax-strategist"},
    {
        "role": "accountant",
        "keywords": {"财务建模", "预测", "场景分析", "决策支持"},
        "agent": "agency-financial-analyst",
    },
    # ── analyst (数据分析师) → 财务师团 ──
    {"role": "analyst", "keywords": {"财务建模", "预测", "场景分析", "模型"}, "agent": "agency-financial-analyst"},
    # ── caster (主播助手) → 营销(直播) ──
    {"role": "caster", "keywords": {"直播", "带货", "直播间", "话术"}, "agent": "agency-livestream"},
    # ── boss (掌柜) → 全局调度 ──
    {"role": "boss", "keywords": {"供应链", "供应商", "采购"}, "agent": "agency-supply-chain"},
    {"role": "boss", "keywords": {"运营", "流程优化", "效率"}, "agent": "agency-studio-ops"},
    # ── deal_hunter (成交猎手) → 营销(增长) ──
    {"role": "deal_hunter", "keywords": {"获客", "增长", "裂变"}, "agent": "agency-growth"},
    {"role": "deal_hunter", "keywords": {"私域", "社群"}, "agent": "agency-private-domain"},
]


def resolve_chat_specialist(agent_role: str, user_msg: str) -> str | None:
    """解析Chat场景下的专家Agent（增强版）

    Args:
        agent_role: 当前Chat选中的角色 (如 "hitmaker")
        user_msg: 用户最新消息

    Returns:
        匹配的SpecialistAgent名称, 或 None

    增强特性:
      1. 先使用智能意图引擎进行语义分析
      2. 根据意图类型和实体进行更精准的匹配
      3. 保留原有关键词匹配作为fallback
    """
    if not agent_role or not user_msg:
        return None

    # Phase 1: 使用智能意图引擎进行语义分析
    try:
        intent_engine = get_intent_engine()
        intent_result = intent_engine.parse(user_msg)

        # 根据意图类型进行优先匹配
        matched_agent = _match_by_intent(agent_role, intent_result)
        if matched_agent:
            logger.debug(
                "chat_specialist_resolved_by_intent",
                role=agent_role,
                agent=matched_agent,
                intent=intent_result.intents[0].intent_type if intent_result.intents else "unknown",
            )
            return matched_agent
    except Exception:
        logger.debug("intent_engine_fallback_to_keyword", exc_info=True)

    # Phase 2: 原有关键词匹配作为fallback
    return _resolve_by_keyword(agent_role, user_msg)


def _match_by_intent(agent_role: str, intent_result) -> str | None:
    """根据意图类型匹配专家Agent"""
    if not intent_result.intents:
        return None

    main_intent = intent_result.intents[0].intent_type

    # 意图到专家Agent的映射
    intent_agent_map = {
        # 天气查询
        IntentType.WEATHER: "agency-weather",
        # 商业意图
        IntentType.INQUIRY: "agency-sales",
        IntentType.PURCHASE: "agency-sales",
        IntentType.COLLABORATION: "agency-partner",
        IntentType.CONSULTATION: "agency-consultant",
        # 计算/数据分析
        IntentType.CALCULATE: "agency-financial-analyst",
        IntentType.KNOWLEDGE: "agency-research",
    }

    # 角色+意图的组合匹配
    role_intent_map = {
        ("hitmaker", IntentType.KNOWLEDGE): "agency-content-strategy",
        ("accountant", IntentType.CALCULATE): "agency-financial-analyst",
        ("analyst", IntentType.KNOWLEDGE): "agency-financial-analyst",
        ("boss", IntentType.SEARCH): "agency-studio-ops",
    }

    # 先检查角色+意图组合
    key = (agent_role, main_intent)
    if key in role_intent_map:
        return role_intent_map[key]

    # 再检查通用意图映射
    if main_intent in intent_agent_map:
        return intent_agent_map[main_intent]

    return None


def _resolve_by_keyword(agent_role: str, user_msg: str) -> str | None:
    """原有关键词匹配（保留向后兼容）"""
    lower_msg = user_msg.lower()

    for entry in _DISPATCH_TABLE:
        if entry["role"] != agent_role:
            continue
        keywords = entry["keywords"]
        if isinstance(keywords, str):
            keywords = {keywords}
        for kw in keywords:
            if kw.lower() in lower_msg:
                logger.debug(
                    "chat_specialist_resolved",
                    role=agent_role,
                    agent=entry["agent"],
                    keyword=kw,
                )
                return entry["agent"]

    return None


def get_specialist_context(agent_name: str) -> str:
    """获取SpecialistAgent的领域上下文 — 注入Chat system prompt

    包含三部分:
      1. agent.get_system_prompt() — 领域专属系统提示词
      2. agent.get_workflow(task) — 标准化工作流步骤
      3. agent.get_rules() — 专业规范/禁忌/红线

    Returns:
        格式化的上下文字符串, 或空串(Agent不存在)
    """
    from src.engine.agent.specialist_base import get_agent_registry

    registry = get_agent_registry()
    agent = registry.get(agent_name)
    if not agent:
        logger.debug("specialist_not_registered", agent=agent_name)
        return ""

    parts: list[str] = []

    # 1. 领域专属提示词
    try:
        prompt = agent.get_system_prompt()
        if prompt:
            parts.append(f"[专家领域知识 — {agent_name}]\n{prompt}")
    except Exception:
        logger.debug("specialist_prompt_failed", agent=agent_name, exc_info=True)

    # 2. 工作流步骤 (概要)
    try:
        workflow = agent.get_workflow("")
        if workflow and isinstance(workflow, list):
            steps = []
            for i, step in enumerate(workflow[:6], 1):
                if isinstance(step, dict):
                    steps.append(f"  {i}. {step.get('name', step.get('step', str(step)))}")
                else:
                    steps.append(f"  {i}. {step}")
            if steps:
                parts.append("[专业工作流]\n" + "\n".join(steps))
    except Exception:
        logger.debug("specialist_workflow_failed", agent=agent_name, exc_info=True)

    # 3. 专业规范/红线
    try:
        rules = agent.get_rules()
        if rules and isinstance(rules, dict):
            lines = []
            for key, val in rules.items():
                if isinstance(val, list):
                    lines.append(f"  {key}: {', '.join(str(v) for v in val[:5])}")
                else:
                    lines.append(f"  {key}: {val}")
            if lines:
                parts.append("[专业规范/红线]\n" + "\n".join(lines))
    except Exception:
        logger.debug("specialist_rules_failed", agent=agent_name, exc_info=True)

    return "\n\n".join(parts)


# ── 业务引擎角色 → 引擎上下文注入 (P2-02) ──

_BUSINESS_ENGINE_ROLES: set[str] = {"butler", "receptionist", "dispatcher", "service_staff", "secretary"}

_BUSINESS_ENGINE_PROMPTS: dict[str, str] = {
    "butler": (
        "[管家引擎 — 日程/提醒/邮件]\n"
        "你具备日程管理、智能提醒、邮件轮询能力。"
        "可以帮用户安排日程、设置提醒、查收邮件、管理待办事项。"
    ),
    "receptionist": (
        "[前台引擎 — 预约/接待/登记]\n"
        "你具备预约管理、来访者登记、服务调度能力。"
        "可以帮用户创建/查看/修改预约、管理来访者记录。"
    ),
    "dispatcher": (
        "[调度引擎 — 任务分配/路由]\n你具备任务分配、智能路由、负载均衡能力。可以帮用户将任务分派给合适的角色或团队。"
    ),
    "service_staff": (
        "[客服引擎 — 工单/支持/售后]\n"
        "你具备工单管理、客户支持、售后服务能力。"
        "可以帮用户创建工单、跟踪处理进度、管理客户咨询。"
    ),
    "secretary": (
        "[秘书引擎 — 会议/文档/纪要]\n"
        "你具备会议管理、文档整理、纪要生成能力。"
        "可以帮用户安排会议、生成会议纪要、管理文档。"
    ),
}


def resolve_business_engine(agent_role: str, user_msg: str) -> str | None:
    """解析业务引擎角色 → 注入业务引擎上下文 (P2-02)

    对于 butler/receptionist/dispatcher/service_staff/secretary 等业务角色,
    返回引擎领域提示词, 让 Chat 拥有业务引擎的专业能力。

    与 resolve_chat_specialist() 互补:
      - resolve_chat_specialist: 内容/营销角色 → SpecialistAgent 上下文
      - resolve_business_engine: 业务角色 → 引擎领域提示词

    Args:
        agent_role: 当前 Chat 选中的角色 (如 "butler")
        user_msg: 用户最新消息 (预留, 未来可根据意图细分引擎)

    Returns:
        业务引擎上下文字符串, 或 None (角色不属于业务引擎)
    """
    if not agent_role or agent_role not in _BUSINESS_ENGINE_ROLES:
        return None

    prompt = _BUSINESS_ENGINE_PROMPTS.get(agent_role)
    if prompt:
        logger.debug("business_engine_resolved", role=agent_role)
        return prompt

    return None
