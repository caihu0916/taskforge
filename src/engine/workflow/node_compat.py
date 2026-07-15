
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""
node_compat.py — 节点类型兼容矩阵

定义工作流 DAG 中各节点类型之间的连接规则：
- 哪些节点类型可以连接
- 连接的条件（如审批通过/驳回）
- 不兼容的节点对

G03-T01: NL→Workflow DAG AI转换 — 第1步
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# ── 可用节点类型 ──


class NodeType:
    """工作流节点类型枚举"""

    AI_GENERATE = "ai_generate"  # AI内容生成
    COMPLIANCE_CHECK = "compliance_check"  # 合规检查
    APPROVAL = "approval"  # 人工审批
    PLATFORM_PUBLISH = "platform_publish"  # 平台发布
    TRANSFORM = "transform"  # 数据转换/处理
    TIMER = "timer"  # 定时触发
    WEBHOOK = "webhook"  # Webhook触发
    PARALLEL = "parallel"  # 并行分支
    AGGREGATE = "aggregate"  # 聚合汇合
    TOOL_CALL = "tool_call"  # 工具调用
    CONDITION = "condition"  # 条件判断


ALL_NODE_TYPES = {
    NodeType.AI_GENERATE,
    NodeType.COMPLIANCE_CHECK,
    NodeType.APPROVAL,
    NodeType.PLATFORM_PUBLISH,
    NodeType.TRANSFORM,
    NodeType.TIMER,
    NodeType.WEBHOOK,
    NodeType.PARALLEL,
    NodeType.AGGREGATE,
    NodeType.TOOL_CALL,
    NodeType.CONDITION,
}

# ── 兼容矩阵 ──
# Key: (source_type, target_type)
# Value: dict with optional 'condition' and 'label'

EDGE_COMPAT: dict[tuple[str, str], dict] = {
    # ── 触发器 → Action ──
    (NodeType.TIMER, NodeType.AI_GENERATE): {"default": True},
    (NodeType.TIMER, NodeType.TRANSFORM): {"default": True},
    (NodeType.TIMER, NodeType.TOOL_CALL): {"default": True},
    (NodeType.TIMER, NodeType.PARALLEL): {"default": True},
    (NodeType.WEBHOOK, NodeType.AI_GENERATE): {"default": True},
    (NodeType.WEBHOOK, NodeType.TRANSFORM): {"default": True},
    (NodeType.WEBHOOK, NodeType.TOOL_CALL): {"default": True},
    (NodeType.WEBHOOK, NodeType.PARALLEL): {"default": True},
    # ── AI生成 → 下游 ──
    (NodeType.AI_GENERATE, NodeType.COMPLIANCE_CHECK): {"default": True},
    (NodeType.AI_GENERATE, NodeType.TRANSFORM): {"default": True},
    (NodeType.AI_GENERATE, NodeType.PLATFORM_PUBLISH): {"default": True, "label": "跳过合规直发"},
    (NodeType.AI_GENERATE, NodeType.TOOL_CALL): {"default": True},
    (NodeType.AI_GENERATE, NodeType.PARALLEL): {"default": True},
    # ── 合规检查 → 下游（条件分支） ──
    (NodeType.COMPLIANCE_CHECK, NodeType.APPROVAL): {"condition": "pass", "label": "合规通过→审批"},
    (NodeType.COMPLIANCE_CHECK, NodeType.PLATFORM_PUBLISH): {"condition": "pass", "label": "合规通过→发布"},
    (NodeType.COMPLIANCE_CHECK, NodeType.AI_GENERATE): {"condition": "fail", "label": "合规失败→回退修改"},
    (NodeType.COMPLIANCE_CHECK, NodeType.TRANSFORM): {"condition": "pass", "label": "合规通过→转换"},
    # ── 审批 → 下游（条件分支） ──
    (NodeType.APPROVAL, NodeType.PLATFORM_PUBLISH): {"condition": "approved", "label": "审批通过→发布"},
    (NodeType.APPROVAL, NodeType.AI_GENERATE): {"condition": "rejected", "label": "驳回→重写"},
    (NodeType.APPROVAL, NodeType.TRANSFORM): {"condition": "approved", "label": "审批通过→转换"},
    # ── 转换/处理 → 下游 ──
    (NodeType.TRANSFORM, NodeType.AI_GENERATE): {"default": True},
    (NodeType.TRANSFORM, NodeType.COMPLIANCE_CHECK): {"default": True},
    (NodeType.TRANSFORM, NodeType.PLATFORM_PUBLISH): {"default": True},
    (NodeType.TRANSFORM, NodeType.TOOL_CALL): {"default": True},
    (NodeType.TRANSFORM, NodeType.APPROVAL): {"default": True},
    # ── 工具调用 → 下游 ──
    (NodeType.TOOL_CALL, NodeType.TRANSFORM): {"default": True},
    (NodeType.TOOL_CALL, NodeType.AI_GENERATE): {"default": True},
    (NodeType.TOOL_CALL, NodeType.COMPLIANCE_CHECK): {"default": True},
    (NodeType.TOOL_CALL, NodeType.PLATFORM_PUBLISH): {"default": True},
    # ── 条件判断 → 下游 ──
    (NodeType.CONDITION, NodeType.AI_GENERATE): {"condition": "true"},
    (NodeType.CONDITION, NodeType.TRANSFORM): {"condition": "true"},
    (NodeType.CONDITION, NodeType.PLATFORM_PUBLISH): {"condition": "true"},
    (NodeType.CONDITION, NodeType.APPROVAL): {"condition": "true"},
    # ── 并行/聚合 ──
    (NodeType.PARALLEL, NodeType.AI_GENERATE): {"default": True},
    (NodeType.PARALLEL, NodeType.TRANSFORM): {"default": True},
    (NodeType.PARALLEL, NodeType.TOOL_CALL): {"default": True},
    (NodeType.AI_GENERATE, NodeType.AGGREGATE): {"default": True},
    (NodeType.TRANSFORM, NodeType.AGGREGATE): {"default": True},
    (NodeType.TOOL_CALL, NodeType.AGGREGATE): {"default": True},
    (NodeType.AGGREGATE, NodeType.PLATFORM_PUBLISH): {"default": True},
    (NodeType.AGGREGATE, NodeType.TRANSFORM): {"default": True},
    (NodeType.AGGREGATE, NodeType.APPROVAL): {"default": True},
}


def is_compatible(source: str, target: str) -> bool:
    """检查两个节点类型是否兼容"""
    return (source, target) in EDGE_COMPAT


def get_edge_rule(source: str, target: str) -> dict | None:
    """获取两个节点类型之间的连接规则"""
    return EDGE_COMPAT.get((source, target))


def get_compatible_targets(source: str) -> list[str]:
    """获取某个节点类型的所有兼容下游类型"""
    return [t for (s, t) in EDGE_COMPAT if s == source]


def get_compatible_sources(target: str) -> list[str]:
    """获取某个节点类型的所有兼容上游类型"""
    return [s for (s, t) in EDGE_COMPAT if t == target]


def validate_edge(source: str, target: str) -> tuple[bool, str]:
    """
    验证两个节点类型之间是否可以建边。

    Returns:
        (is_valid, reason)
    """
    if source not in ALL_NODE_TYPES:
        return False, f"未知源节点类型: {source}"
    if target not in ALL_NODE_TYPES:
        return False, f"未知目标节点类型: {target}"

    rule = get_edge_rule(source, target)
    if rule is None:
        return False, f"不兼容: {source} → {target}"

    return True, rule.get("label", f"兼容: {source} → {target}")


# ── Skill-Gap 1-2-2: 节点拖拽上下文提示 ──


# 节点类型中文名称映射
NODE_TYPE_LABELS: dict[str, str] = {
    NodeType.AI_GENERATE: "AI内容生成",
    NodeType.COMPLIANCE_CHECK: "合规检查",
    NodeType.APPROVAL: "人工审批",
    NodeType.PLATFORM_PUBLISH: "平台发布",
    NodeType.TRANSFORM: "数据转换",
    NodeType.TIMER: "定时触发",
    NodeType.WEBHOOK: "Webhook触发",
    NodeType.PARALLEL: "并行分支",
    NodeType.AGGREGATE: "聚合汇合",
    NodeType.TOOL_CALL: "工具调用",
    NodeType.CONDITION: "条件判断",
}

# 节点类型描述
NODE_TYPE_DESCRIPTIONS: dict[str, str] = {
    NodeType.AI_GENERATE: "使用 LLM 生成文本、图片、视频等内容",
    NodeType.COMPLIANCE_CHECK: "检查内容是否符合平台规则和法律法规",
    NodeType.APPROVAL: "等待人工审批，支持通过/驳回",
    NodeType.PLATFORM_PUBLISH: "发布到目标平台（抖音、小红书、微信公众号等）",
    NodeType.TRANSFORM: "数据格式转换、字段映射、文本处理",
    NodeType.TIMER: "按时间触发（cron 表达式或固定间隔）",
    NodeType.WEBHOOK: "由外部系统通过 HTTP 调用触发",
    NodeType.PARALLEL: "将流程拆分为多个并行分支",
    NodeType.AGGREGATE: "等待多个并行分支完成并合并结果",
    NodeType.TOOL_CALL: "调用 MCP 工具或外部 API",
    NodeType.CONDITION: "根据条件表达式分支流程",
}

# 节点类型图标（用于前端显示）
NODE_TYPE_ICONS: dict[str, str] = {
    NodeType.AI_GENERATE: "sparkles",
    NodeType.COMPLIANCE_CHECK: "shield",
    NodeType.APPROVAL: "check-circle",
    NodeType.PLATFORM_PUBLISH: "send",
    NodeType.TRANSFORM: "shuffle",
    NodeType.TIMER: "clock",
    NodeType.WEBHOOK: "webhook",
    NodeType.PARALLEL: "git-branch",
    NodeType.AGGREGATE: "git-merge",
    NodeType.TOOL_CALL: "tool",
    NodeType.CONDITION: "git-pull-request",
}


def get_node_label(node_type: str) -> str:
    """获取节点类型的中文名称"""
    return NODE_TYPE_LABELS.get(node_type, node_type)


def get_node_description(node_type: str) -> str:
    """获取节点类型的描述"""
    return NODE_TYPE_DESCRIPTIONS.get(node_type, "")


def get_node_icon(node_type: str) -> str:
    """获取节点类型的图标名"""
    return NODE_TYPE_ICONS.get(node_type, "circle")


def get_drag_hint(source: str | None, target: str | None) -> dict:
    """获取拖拽时的上下文提示

    Args:
        source: 源节点类型（拖拽起点），可为 None（首次拖拽）
        target: 目标节点类型（拖拽终点），可为 None

    Returns:
        {
            "can_connect": bool,           #是否可以连接
            "label": str,                  #连接标签
            "description": str,            #连接描述
            "source_label": str,           #源节点中文名
            "target_label": str,           #目标节点中文名
            "suggestions": list[str],      #推荐的下游节点类型
            "warning": str | None,         #警告信息（如条件边）
        }
    """
    if source is None or target is None:
        return {
            "can_connect": False,
            "label": "",
            "description": "",
            "source_label": get_node_label(source) if source else "",
            "target_label": get_node_label(target) if target else "",
            "suggestions": [],
            "warning": None,
        }

    is_valid, reason = validate_edge(source, target)
    rule = get_edge_rule(source, target)
    suggestions = get_compatible_targets(source)

    warning = None
    if rule and "condition" in rule:
        condition_labels = {
            "pass": "合规通过",
            "fail": "合规失败",
            "approved": "审批通过",
            "rejected": "驳回",
            "true": "条件为真",
        }
        cond_text = condition_labels.get(rule["condition"], rule["condition"])
        warning = f"此连接为条件边，仅在「{cond_text}」时执行"

    return {
        "can_connect": is_valid,
        "label": rule.get("label", "") if rule else "",
        "description": reason,
        "source_label": get_node_label(source),
        "target_label": get_node_label(target),
        "suggestions": suggestions,
        "warning": warning,
    }


def get_drag_suggestions(node_type: str, max_count: int = 5) -> list[dict]:
    """获取节点拖拽建议（推荐下游节点）

    Args:
        node_type: 当前节点类型
        max_count: 最多返回的建议数量

    Returns:
        [{"type": "ai_generate", "label": "AI内容生成", "description": "...", "icon": "sparkles"}, ...]
    """
    targets = get_compatible_targets(node_type)[:max_count]
    return [
        {
            "type": t,
            "label": get_node_label(t),
            "description": get_node_description(t),
            "icon": get_node_icon(t),
        }
        for t in targets
    ]


def get_node_palette() -> list[dict]:
    """获取节点调色板（用于左侧节点列表）

    Returns:
        所有可用节点的信息列表
    """
    return [
        {
            "type": t,
            "label": get_node_label(t),
            "description": get_node_description(t),
            "icon": get_node_icon(t),
            "category": _get_node_category(t),
        }
        for t in [
            NodeType.TIMER,
            NodeType.WEBHOOK,
            NodeType.AI_GENERATE,
            NodeType.COMPLIANCE_CHECK,
            NodeType.APPROVAL,
            NodeType.TRANSFORM,
            NodeType.TOOL_CALL,
            NodeType.CONDITION,
            NodeType.PARALLEL,
            NodeType.AGGREGATE,
            NodeType.PLATFORM_PUBLISH,
        ]
    ]


def _get_node_category(node_type: str) -> str:
    """获取节点分类"""
    categories = {
        NodeType.TIMER: "触发器",
        NodeType.WEBHOOK: "触发器",
        NodeType.AI_GENERATE: "处理",
        NodeType.COMPLIANCE_CHECK: "处理",
        NodeType.TRANSFORM: "处理",
        NodeType.TOOL_CALL: "处理",
        NodeType.CONDITION: "控制",
        NodeType.PARALLEL: "控制",
        NodeType.AGGREGATE: "控制",
        NodeType.APPROVAL: "人工",
        NodeType.PLATFORM_PUBLISH: "输出",
    }
    return categories.get(node_type, "其他")
