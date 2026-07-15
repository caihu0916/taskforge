
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""BossDecisionAgent — 结构化决策流程 (WO-03 [P1])

流程: 信息汇总→风险分析→方案对比→成本收益→推荐排序→输出决策

铁律: 异常不吞,不返回假数据,LLM输出必须解析
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.engine.agent.specialist_base import SpecialistAgent

logger = structlog.get_logger(__name__)

# LLM输出的JSON提取正则
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Any:
    """从LLM输出中提取JSON，兼容markdown代码块包裹"""
    # 1) 尝试提取 ```json ... ``` 块
    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group(1).strip()
    # 2) 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # 3) 找第一个 [ ... ] 或 { ... }
    for regex in (_JSON_ARRAY_RE, _JSON_OBJ_RE):
        m = regex.search(text)
        if m:
            try:
                return json.loads(m.group())
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _safe_risk_level(val: str) -> str:
    """归一化风险等级为 h/m/l"""
    v = str(val).strip().lower()
    if v in ("high", "h", "高"):
        return "h"
    if v in ("low", "l", "低"):
        return "l"
    return "m"


_RISK_WEIGHT = {"h": 3, "m": 2, "l": 1}


class BossDecisionAgent(SpecialistAgent):
    agent_name = "boss-decision"
    agent_vibe = "风险分析→方案对比→成本收益→推荐排序"
    category = "decision"

    def get_rules(self) -> dict[str, Any]:
        return {
            "require_options": 2,
            "human_confirmation": True,
            "forbidden": ["single_option", "skip_risk_analysis", "no_cost_estimate"],
        }

    def get_workflow(self, task: str) -> list[dict[str, str]]:
        return [
            {"phase": "gather", "action": "Collect relevant data"},
            {"phase": "analyze_risks", "action": "Identify risks + probability + impact"},
            {"phase": "compare", "action": "Generate >=2 options + pros/cons"},
            {"phase": "cost_benefit", "action": "Estimate cost/benefit/ROI per option"},
            {"phase": "rank", "action": "Rank by risk-weighted ROI"},
            {"phase": "decide", "action": "Output recommendation + human confirmation point"},
        ]

    async def execute(self, task: str, **kwargs) -> dict[str, Any]:
        summary = await self._gather_information(task)
        risks = await self._analyze_risks(task, summary)
        options = await self._compare_options(task, summary, risks)
        cost_benefit = await self._calculate_cost_benefit(options, summary)
        ranking = self._rank_options(options, cost_benefit, risks)
        return {
            "success": True,
            "decision": {
                "recommendation": ranking[0] if ranking else {},
                "alternatives": ranking[1:] if len(ranking) > 1 else [],
                "risks": risks,
                "cost_benefit": cost_benefit,
                "human_confirmation_required": True,
            },
        }

    # ── LLM调用 ──────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
        try:
            from src.engine.llm.provider_bootstrap import get_llm_router
            from src.engine.llm.router_dispatch import get_smart_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        smart = get_smart_router()
        routing = smart.route(message=prompt, agent_role="boss")
        router = get_llm_router()
        resp = await router.chat(
            [{"role": "user", "content": prompt}],
            provider=routing.provider,
            model=routing.model,
            max_tokens=2000,
        )
        return resp.get("content", "") or resp.get("response", "") or str(resp)

    # ── Phase 1: 信息汇总 ────────────────────────────────

    async def _gather_information(self, task: str) -> str:
        return await self._call_llm(f"汇总与以下决策相关的关键信息，列出数据、约束、利益相关方:\n{task}")

    # ── Phase 2: 风险分析 ────────────────────────────────

    async def _analyze_risks(self, task: str, summary: str) -> list[dict]:
        prompt = (
            f"分析此决策的主要风险（至少3条，至多5条）:\n"
            f"决策: {task}\n背景: {summary}\n\n"
            f"严格按JSON数组输出，不要多余文字:\n"
            f'[{{"risk":"风险描述","probability":"h/m/l","impact":"h/m/l","mitigation":"缓解措施"}}]'
        )
        raw = await self._call_llm(prompt)
        parsed = _extract_json(raw)

        if isinstance(parsed, list) and len(parsed) > 0:
            risks = []
            for item in parsed[:5]:
                if isinstance(item, dict) and "risk" in item:
                    risks.append(
                        {
                            "risk": str(item.get("risk", ""))[:200],
                            "probability": _safe_risk_level(item.get("probability", "m")),
                            "impact": _safe_risk_level(item.get("impact", "m")),
                            "mitigation": str(item.get("mitigation", ""))[:300],
                        }
                    )
            if risks:
                logger.info("risk_analysis_parsed", count=len(risks))
                return risks

        # fallback: 无法解析时返回LLM原文摘要作为观察风险
        logger.warning("risk_analysis_parse_failed", raw_len=len(raw))
        return [{"risk": "LLM风险分析解析失败，需人工审查", "probability": "m", "impact": "m", "mitigation": raw[:300]}]

    # ── Phase 3: 方案对比 ────────────────────────────────

    async def _compare_options(self, task: str, summary: str, risks: list) -> list[dict]:
        risk_summary = "; ".join(r.get("risk", "")[:50] for r in risks[:3])
        prompt = (
            f"为以下决策生成至少2个可行方案，含优缺点:\n"
            f"决策: {task}\n背景: {summary}\n主要风险: {risk_summary}\n\n"
            f"严格按JSON数组输出，不要多余文字:\n"
            f'[{{"name":"方案名","description":"简述","pros":["优点1","优点2"],"cons":["缺点1"]}}]'
        )
        raw = await self._call_llm(prompt)
        parsed = _extract_json(raw)

        if isinstance(parsed, list) and len(parsed) >= 2:
            options = []
            for item in parsed[:5]:
                if isinstance(item, dict) and "name" in item:
                    pros = item.get("pros", [])
                    cons = item.get("cons", [])
                    if isinstance(pros, str):
                        pros = [pros]
                    if isinstance(cons, str):
                        cons = [cons]
                    options.append(
                        {
                            "name": str(item["name"])[:100],
                            "description": str(item.get("description", ""))[:300],
                            "pros": [str(p)[:100] for p in (pros or [])][:5],
                            "cons": [str(c)[:100] for c in (cons or [])][:5],
                        }
                    )
            if len(options) >= 2:
                logger.info("options_parsed", count=len(options))
                return options

        # fallback: 至少2个占位方案
        logger.warning("options_parse_failed", raw_len=len(raw))
        return [
            {
                "name": "方案A(保守)",
                "description": "低风险路径，优先稳妥",
                "pros": ["风险可控"],
                "cons": ["收益可能有限"],
            },
            {
                "name": "方案B(进取)",
                "description": "高风险路径，追求高收益",
                "pros": ["收益潜力大"],
                "cons": ["风险较高"],
            },
        ]

    # ── Phase 4: 成本收益估算 ────────────────────────────

    async def _calculate_cost_benefit(self, options: list, summary: str) -> list[dict]:
        """基于LLM估算每个方案的成本/收益/ROI"""
        names = [o["name"] for o in options]
        prompt = (
            f"估算以下方案的成本与收益（单位:万元）:\n"
            f"背景: {summary}\n方案: {', '.join(names)}\n\n"
            f"严格按JSON数组输出，不要多余文字:\n"
            f'[{{"name":"方案名","cost_estimate":0,"benefit_estimate":0,'
            f'"confidence":"h/m/l","reasoning":"简要理由"}}]'
        )
        raw = await self._call_llm(prompt)
        parsed = _extract_json(raw)

        results = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and "name" in item:
                    try:
                        cost = float(item.get("cost_estimate", 0))
                    except (TypeError, ValueError):
                        cost = 0
                    try:
                        benefit = float(item.get("benefit_estimate", 0))
                    except (TypeError, ValueError):
                        benefit = 0
                    roi = ((benefit - cost) / cost * 100) if cost > 0 else 0
                    results.append(
                        {
                            "name": str(item["name"])[:100],
                            "cost_estimate": cost,
                            "benefit_estimate": benefit,
                            "roi": round(roi, 1),
                            "confidence": _safe_risk_level(item.get("confidence", "m")),
                            "reasoning": str(item.get("reasoning", ""))[:200],
                        }
                    )

        # 匹配回原始options顺序，缺失的补零
        for opt in options:
            matched = next((r for r in results if r["name"] == opt["name"]), None)
            if not matched:
                matched = {
                    "name": opt["name"],
                    "cost_estimate": 0,
                    "benefit_estimate": 0,
                    "roi": 0,
                    "confidence": "l",
                    "reasoning": "LLM未返回估算",
                }
            if matched not in results:
                results.append(matched)

        logger.info("cost_benefit_calculated", count=len(results))
        return results

    # ── Phase 5: 推荐排序 ────────────────────────────────

    def _rank_options(self, options: list, cost_benefit: list, risks: list) -> list[dict]:
        """按 risk-weighted ROI 排序"""
        # 计算整体风险系数（所有risk的impact加权平均）
        avg_risk = sum(_RISK_WEIGHT.get(r.get("impact", "m"), 2) for r in risks) / len(risks) if risks else 2

        risk_discount = 1 - (avg_risk - 1) * 0.15  # 1→0.85, 2→0.70, 3→0.55

        # 构建排序项
        ranked = []
        for opt in options:
            cb = next((c for c in cost_benefit if c["name"] == opt["name"]), None)
            if not cb:
                cb = {"roi": 0, "confidence": "l"}

            confidence_mult = {"h": 1.0, "m": 0.8, "l": 0.5}.get(cb.get("confidence", "m"), 0.8)
            weighted_roi = cb["roi"] * risk_discount * confidence_mult

            ranked.append(
                {
                    "rank": 0,  # 排序后填入
                    "name": opt["name"],
                    "description": opt.get("description", ""),
                    "pros": opt.get("pros", []),
                    "cons": opt.get("cons", []),
                    "cost_estimate": cb.get("cost_estimate", 0),
                    "benefit_estimate": cb.get("benefit_estimate", 0),
                    "roi": cb.get("roi", 0),
                    "risk_weighted_roi": round(weighted_roi, 1),
                }
            )

        # 按risk-weighted ROI降序排
        ranked.sort(key=lambda x: x["risk_weighted_roi"], reverse=True)
        for i, item in enumerate(ranked):
            item["rank"] = i + 1

        logger.info("options_ranked", top=ranked[0]["name"] if ranked else "none")
        return ranked
