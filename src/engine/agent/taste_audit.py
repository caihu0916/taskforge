
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 品味审计器 — 对营销Agent输出做反AI味校验

架构:
  quick_scan()  — 零LLM调用, 纯正则匹配 (来自taste_rules)
  deep_score()  — 可选LLM调用, 5维深度评分
  audit()       — 组合入口: 先快速扫描, 可选深度评分
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from src.engine.prompt.taste_rules import SCORING_RUBRIC, TasteResult, quick_scan

logger = structlog.get_logger(__name__)


class TasteAuditor:
    """品味校验器 — 快速扫描 + 可选深度评分"""

    def __init__(self, llm_fn: Any = None) -> None:
        # llm_fn: async (prompt: str) -> str | None
        # 传入则启用深度评分, 不传则只做快速扫描
        self._llm_fn = llm_fn

    def quick_scan(self, text: str) -> TasteResult:
        """零LLM调用, 正则匹配AI黑话+公式结构"""
        return quick_scan(text)

    async def deep_score(self, text: str) -> dict[str, Any]:
        """可选LLM调用, 5维深度评分

        返回: {
            "dimensions": {directness: N, rhythm: N, trust: N, humanity: N, density: N},
            "total": N,
            "suggestion": str  #改写建议
        }
        """
        if not self._llm_fn or not text:
            return {"dimensions": {}, "total": 0, "suggestion": ""}

        rubric_lines = "\n".join(f"  - {k}: {v['desc']} (0-{v['max']}分)" for k, v in SCORING_RUBRIC.items())

        prompt = f"""你是一个文案品味评审专家。请对以下文本按5个维度打分。

评分维度:
{rubric_lines}

待评文本:
---
{text[:2000]}
---

请严格按以下JSON格式输出, 不要输出其他内容:
{{"directness": N, "rhythm": N, "trust": N, "humanity": N, "density": N, "suggestion": "一句话改写建议"}}"""

        try:
            raw = await self._llm_fn(prompt)
            if not raw:
                return {"dimensions": {}, "total": 0, "suggestion": ""}

            # 提取JSON部分
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start < 0 or end <= start:
                return {"dimensions": {}, "total": 0, "suggestion": ""}

            data = json.loads(raw[start:end])
            dims = {k: min(max(int(data.get(k, 0)), 0), SCORING_RUBRIC[k]["max"]) for k in SCORING_RUBRIC}
            total = sum(dims.values())
            suggestion = str(data.get("suggestion", ""))[:200]

            return {"dimensions": dims, "total": total, "suggestion": suggestion}

        except Exception as e:
            logger.warning("deep_score_failed", error=str(e), exc_info=True)
            return {"dimensions": {}, "total": 0, "suggestion": ""}

    async def audit(self, text: str, deep: bool = False) -> dict[str, Any]:
        """组合入口: 先快速扫描, 可选深度评分

        返回: {
            "quick": TasteResult,
            "deep": {...} | None,
            "final_score": int,
            "is_pass": bool,
        }
        """
        quick = self.quick_scan(text)
        result: dict[str, Any] = {
            "quick": {
                "score": quick.score,
                "violations": quick.violations[:10],  # 最多返回10条
                "is_pass": quick.is_pass,
            },
            "deep": None,
            "final_score": quick.score,
            "is_pass": quick.is_pass,
        }

        # 快速扫描分数<80时才做深度评分 (省LLM调用)
        if deep and quick.score < 80 and self._llm_fn:
            deep_result = await self.deep_score(text)
            result["deep"] = deep_result
            # 综合分: 快速占60%, 深度占40%
            if deep_result["total"] > 0:
                quick_norm = quick.score / 100 * 60
                deep_norm = deep_result["total"] / 100 * 40
                result["final_score"] = int(quick_norm + deep_norm)
                result["is_pass"] = result["final_score"] >= 60

        return result
