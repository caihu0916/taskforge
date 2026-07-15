
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P3-02: 对抗性验证 Agent — VERDICT 结构化输出契约

解析 VERIFICATION Agent 的输出文本为 VerdictResult,
提供 PASS/FAIL/PARTIAL 判定 + 证据 + 置信度的程序化访问。

契约格式:
    VERDICT: PASS|FAIL|PARTIAL
    证据: <证据描述>
    置信度: <0.0-1.0>
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VALID_VERDICTS = ("PASS", "FAIL", "PARTIAL")

_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL|PARTIAL)", re.IGNORECASE)
_EVIDENCE_RE = re.compile(r"证据:\s*(.+)", re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"置信度:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)


@dataclass
class VerdictResult:
    """对抗性验证判定结果"""

    verdict: str
    evidence: str
    confidence: float


def parse_verdict(text: str) -> VerdictResult:
    """解析 VERIFICATION Agent 输出文本为 VerdictResult

    ponytail: 正则提取, 无 VERDICT 行返回 UNKNOWN。
    升级路径: 支持 JSON 格式输出 + 流式解析。
    """
    verdict_match = _VERDICT_RE.search(text)
    verdict = verdict_match.group(1).upper() if verdict_match else "UNKNOWN"

    evidence_match = _EVIDENCE_RE.search(text)
    evidence = evidence_match.group(1).strip() if evidence_match else ""

    confidence_match = _CONFIDENCE_RE.search(text)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0

    return VerdictResult(verdict=verdict, evidence=evidence, confidence=confidence)


__all__ = ["VerdictResult", "parse_verdict"]
