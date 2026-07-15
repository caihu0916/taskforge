
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P1-1: BackgroundReviewer — Post-turn 自省循环 (对标 Hermes conversation_loop.py)"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ReviewReport:
    has_issue: bool = False
    issues: list[str] = field(default_factory=list)
    recommended_skills: list[str] = field(default_factory=list)
    auto_correction: str = ""


class BackgroundReviewer:
    """Post-turn 后台自省引擎 — 每轮结束后分析Agent表现"""

    def __init__(self) -> None:
        self._failure_counts: dict[str, int] = {}
        self._turn_count = 0

    def review_turn(self, context: dict[str, Any]) -> ReviewReport:
        self._turn_count += 1
        issues = []
        skills = []

        tool_calls = context.get("tool_calls", [])
        output = context.get("output", "")

        # 检测1: 同工具重复失败
        failures = [tc for tc in tool_calls if not tc.get("success", True)]
        for tc in failures:
            name = tc.get("name", "unknown")
            self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        for name, count in list(self._failure_counts.items())[-3:]:
            if count >= 3:
                issues.append(f"Tool '{name}' failed {count}x consecutive — consider fallback or alternative approach")

        # 检测2: 无进展循环
        if not tool_calls and len(output) > 100:
            think_markers = ["let me think", "I'm thinking", "reconsider", "let me try again"]
            if any(m in output.lower() for m in think_markers):
                issues.append("No-progress loop detected — agent is thinking without acting")

        # 检测3: 技能推荐
        keyword_skill_map = {
            "tax": "tax_calculator",
            "财务": "finance_analyzer",
            "security": "security_auditor",
            "合规": "compliance_checker",
            "分析": "data_analyst",
            "合同": "contract_reviewer",
        }
        for keyword, skill in keyword_skill_map.items():
            if keyword in output.lower() and skill not in skills:
                skills.append(skill)

        report = ReviewReport(
            has_issue=len(issues) > 0,
            issues=issues,
            recommended_skills=skills[:3],
            auto_correction="; ".join(issues[:2]) if issues else "",
        )
        if report.has_issue:
            logger.info("background_review_found_issues", issues=issues, turn=self._turn_count)
        return report
