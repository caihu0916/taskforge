
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent输出路由器 — 根据任务特征智能选择输出格式"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OutputFormat(StrEnum):
    MD = "md"
    DOCX = "docx"
    XLSX = "xlsx"
    PDF = "pdf"


@dataclass
class OutputDecision:
    format: OutputFormat
    reason: str
    template_name: str | None = None


_FORMAT_RULES: list[tuple[list[str], OutputFormat, str]] = [
    # XLSX: 数据/表格场景
    (
        ["销售数据", "客户列表", "导出数据", "账单", "交易记录", "财务明细", "export data", "spreadsheet"],
        OutputFormat.XLSX,
        "DATA_EXPORT",
    ),
    (["分析报表", "数据报表", "统计表", "业绩报表", "data report", "analytics"], OutputFormat.XLSX, "DATA_REPORT"),
    # DOCX: 更具体的规则放前面，避免被通用"报告"抢先
    (["财务报告", "年报", "financial report"], OutputFormat.DOCX, "FINANCIAL_REPORT"),
    (["营销方案", "推广方案", "marketing plan", "campaign"], OutputFormat.DOCX, "MARKETING_PLAN"),
    (["方案", "计划书", "合同", "协议", "proposal", "plan", "contract"], OutputFormat.DOCX, "DOCUMENT"),
    (["技术方案", "架构设计", "technical spec", "design doc"], OutputFormat.DOCX, "TECHNICAL_SPEC"),
    # PDF: 通用"报告"放最后
    (["审计报告", "audit report"], OutputFormat.PDF, "AUDIT_REPORT"),
    (["报告", "分析报告", "report"], OutputFormat.PDF, "FORMAL_REPORT"),
]

_AGENT_FORMAT_PREF: dict[str, OutputFormat] = {
    "finance": OutputFormat.DOCX,
    "accountant": OutputFormat.XLSX,
    "analyst": OutputFormat.XLSX,
    "marketing": OutputFormat.DOCX,
    "seo": OutputFormat.DOCX,
    "content": OutputFormat.DOCX,
    "sales": OutputFormat.XLSX,
}

_TEMPLATE_MAP: dict[str, str] = {
    "FINANCIAL_REPORT": "financial_report.docx",
    "MARKETING_PLAN": "marketing_plan.docx",
    "DATA_REPORT": None,
    "DATA_EXPORT": None,
}


def route_output(
    task_description: str,
    agent_role: str | None = None,
    user_format_hint: str | None = None,
    result_data: Any = None,
) -> OutputDecision:
    """根据任务描述、Agent角色、用户偏好决定输出格式

    优先级: user_format_hint > _FORMAT_RULES > _AGENT_FORMAT_PREF > 默认MD
    """
    if user_format_hint:
        fmt = _parse_format_hint(user_format_hint)
        if fmt:
            logger.info("output_routed_by_user_hint", format=fmt.value, hint=user_format_hint)
            return OutputDecision(format=fmt, reason=f"用户指定: {user_format_hint}")

    task_lower = task_description.lower()
    for keywords, fmt, rule_name in _FORMAT_RULES:
        if any(kw in task_lower for kw in keywords):
            template = _TEMPLATE_MAP.get(rule_name)
            logger.info("output_routed_by_rule", format=fmt.value, rule=rule_name)
            return OutputDecision(format=fmt, reason=f"规则匹配: {rule_name}", template_name=template)

    if agent_role:
        role_lower = agent_role.lower()
        for key, fmt in _AGENT_FORMAT_PREF.items():
            if key in role_lower:
                logger.info("output_routed_by_agent_role", format=fmt.value, role=agent_role)
                return OutputDecision(format=fmt, reason=f"Agent角色偏好: {agent_role}")

    if result_data and isinstance(result_data, dict):
        data_keys = set(result_data.keys())
        table_hints = {"rows", "columns", "data", "table_data", "records", "items"}
        if data_keys & table_hints:
            logger.info("output_routed_by_data_structure", format="xlsx")
            return OutputDecision(format=OutputFormat.XLSX, reason="结果含表格数据")

    return OutputDecision(format=OutputFormat.MD, reason="默认格式")


def _parse_format_hint(hint: str) -> OutputFormat | None:
    hint_lower = hint.lower().strip().lstrip(".")
    mapping = {
        "md": OutputFormat.MD,
        "markdown": OutputFormat.MD,
        "docx": OutputFormat.DOCX,
        "doc": OutputFormat.DOCX,
        "word": OutputFormat.DOCX,
        "xlsx": OutputFormat.XLSX,
        "xls": OutputFormat.XLSX,
        "excel": OutputFormat.XLSX,
        "pdf": OutputFormat.PDF,
    }
    return mapping.get(hint_lower)
