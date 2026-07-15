
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""
edge_templates.py — 工作流边模板库 + 匹配引擎

预定义5大业务场景的边模板:
1. 内容发布管线: timer→ai_generate→compliance→publish
2. 发票自动入账: webhook→ai_generate→transform→tool_call
3. 内容审批管线: ai_generate→compliance→approval→publish + 驳回回边
4. 数据ETL: webhook→transform→tool_call→aggregate→publish
5. 分支聚合: trigger→parallel→[action1,action2]→aggregate→publish

G03-T02: 边推断增强 — 模板库匹配
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from src.engine.workflow.node_compat import NodeType

logger = structlog.get_logger(__name__)


@dataclass
class EdgeTemplate:
    """边模板: 一组类型签名 + 预定义边"""

    name: str  # 模板名
    signature: tuple[str, ...]  # 步骤类型签名
    edges: list[dict]  # 预定义边 [{source, target, condition, label}]
    description: str = ""  # 模板描述


# ── 预定义模板库 ──

TEMPLATES: list[EdgeTemplate] = [
    EdgeTemplate(
        name="content_publish",
        signature=(NodeType.TIMER, NodeType.AI_GENERATE, NodeType.COMPLIANCE_CHECK, NodeType.PLATFORM_PUBLISH),
        edges=[
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 3, "condition": "pass", "label": "合规通过→发布"},
        ],
        description="定时内容发布管线",
    ),
    EdgeTemplate(
        name="content_with_approval",
        signature=(NodeType.AI_GENERATE, NodeType.COMPLIANCE_CHECK, NodeType.APPROVAL, NodeType.PLATFORM_PUBLISH),
        edges=[
            {"source": 0, "target": 1},
            {"source": 1, "target": 2, "condition": "pass", "label": "合规通过→审批"},
            {"source": 2, "target": 3, "condition": "approved", "label": "审批通过→发布"},
            {"source": 2, "target": 0, "condition": "rejected", "label": "驳回→重写"},
        ],
        description="内容审批发布管线(含驳回回边)",
    ),
    EdgeTemplate(
        name="invoice_auto_post",
        signature=(NodeType.WEBHOOK, NodeType.AI_GENERATE, NodeType.TRANSFORM, NodeType.TOOL_CALL),
        edges=[
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 3},
        ],
        description="发票自动入账管线",
    ),
    EdgeTemplate(
        name="data_etl",
        signature=(
            NodeType.WEBHOOK,
            NodeType.TRANSFORM,
            NodeType.TOOL_CALL,
            NodeType.AGGREGATE,
            NodeType.PLATFORM_PUBLISH,
        ),
        edges=[
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 3},
            {"source": 3, "target": 4},
        ],
        description="数据ETL管线",
    ),
    EdgeTemplate(
        name="parallel_publish",
        signature=(NodeType.TIMER, NodeType.PARALLEL, NodeType.AGGREGATE, NodeType.PLATFORM_PUBLISH),
        edges=[
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 3},
        ],
        description="并行聚合发布管线",
    ),
]


def _match_score(sig: tuple[str, ...], template_sig: tuple[str, ...]) -> float:
    """
    计算签名与模板的匹配得分 (0.0~1.0)

    算法: 最长公共子序列(LCS)比率
    - 完全匹配 = 1.0
    - 子序列匹配 = matched/len(sig)
    - 无匹配 = 0.0
    """
    if not sig or not template_sig:
        return 0.0

    m, n = len(sig), len(template_sig)
    # LCS 动态规划
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if sig[i - 1] == template_sig[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_len = dp[m][n]
    return lcs_len / max(m, n)


def match_template(steps: list[str]) -> EdgeTemplate | None:
    """
    为步骤类型序列匹配最佳模板

    匹配阈值: >= 0.7 (70%以上LCS比率)
    如果多个模板超过阈值，选最高的

    Args:
        steps: 步骤类型名称列表

    Returns:
        最佳匹配的 EdgeTemplate, 或 None
    """
    if not steps:
        return None

    sig = tuple(steps)
    best_template = None
    best_score = 0.0
    threshold = 0.7

    for tmpl in TEMPLATES:
        score = _match_score(sig, tmpl.signature)
        if score >= threshold and score > best_score:
            best_score = score
            best_template = tmpl

    if best_template:
        logger.info("template_matched", template=best_template.name, score=round(best_score, 2))
    return best_template
