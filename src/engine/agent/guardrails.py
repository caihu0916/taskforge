
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""C1: GuardrailsEngine — 循环检测

检测模式:
  - 同参数重复 5 次 → hard_stop
  - 同工具失败 5 次 → hard_stop
  - 无进展 5 轮 → warn
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 阈值从 hard_limits.yaml 读取，这里只保留兜底默认值
_FALLBACK_MAX_REPEATS = 5
_FALLBACK_MAX_FAILURES = 5
_FALLBACK_MAX_NO_PROGRESS = 5


def _get_limit(key: str, fallback: int) -> int:
    """从 HardLimits 读取阈值，读取失败则用兜底值"""
    try:
        from src.engine.agent.hard_limits import get_hard_limits

        val = get_hard_limits().get("agent_safety", key, fallback)
        return int(val) if val is not None else fallback
    except Exception as e:
        logger.debug("guardrails_config_fallback", error=str(e))
        return fallback


class GuardrailsEngine:
    """循环检测引擎 + M5-B Denial Tracking"""

    def __init__(self) -> None:
        self._param_history: dict[str, list[str]] = {}  # tool → [param_hash]
        self._tool_failures: dict[str, int] = {}  # tool → count
        self._no_progress_count: int = 0
        # M5-B: Denial Tracking 状态
        from src.engine.agent.denial_tracker import create_denial_state

        self._denial_state = create_denial_state()

    # ── M5-B: Denial Tracking 方法 ──

    def record_permission_denial(self, tool_name: str, reason: str = "") -> dict[str, Any]:
        """记录一次权限拒绝"""
        from src.engine.agent.denial_tracker import record_denial, should_fallback

        self._denial_state = record_denial(self._denial_state)
        if should_fallback(self._denial_state):
            logger.warning(
                "guardrails_denial_fallback",
                tool=tool_name,
                reason=reason,
                consecutive=self._denial_state.consecutive_denials,
                total=self._denial_state.total_denials,
            )
            return {
                "action": "fallback_to_prompt",
                "reason": f"Tool {tool_name} denied {self._denial_state.consecutive_denials}x consecutively. Consider adjusting permissions.",
            }
        return {"action": "allow", "reason": ""}

    def record_permission_success(self) -> None:
        """记录一次权限成功"""
        from src.engine.agent.denial_tracker import record_success

        self._denial_state = record_success(self._denial_state)

    def check_same_params(self, tool_name: str, args: dict[str, Any]) -> bool:
        """检查同参数重复调用。返回 True 表示应 hard_stop"""
        max_repeats = _get_limit("max_repeats", _FALLBACK_MAX_REPEATS)
        h = self._hash_args(args)
        if tool_name not in self._param_history:
            self._param_history[tool_name] = []
        history = self._param_history[tool_name]
        history.append(h)
        if len(history) > max_repeats:
            history.pop(0)
        recent = history[-max_repeats:]
        if len(recent) == max_repeats and all(x == h for x in recent):
            logger.warning("guardrails_same_params_hard_stop", tool=tool_name, repeats=max_repeats)
            return True
        return False

    def record_tool_failure(self, tool_name: str) -> None:
        """记录工具执行失败"""
        self._tool_failures[tool_name] = self._tool_failures.get(tool_name, 0) + 1

    def is_hard_stop(self, tool_name: str) -> bool:
        """同工具失败达到上限"""
        max_failures = _get_limit("max_failures", _FALLBACK_MAX_FAILURES)
        if self._tool_failures.get(tool_name, 0) >= max_failures:
            logger.warning("guardrails_tool_failure_hard_stop", tool=tool_name, failures=max_failures)
            return True
        return False

    def record_no_progress(self) -> None:
        """记录一轮无进展"""
        self._no_progress_count += 1

    def should_warn(self) -> bool:
        """无进展达到上限，应发出警告"""
        max_no_progress = _get_limit("max_no_progress", _FALLBACK_MAX_NO_PROGRESS)
        if self._no_progress_count >= max_no_progress:
            logger.warning("guardrails_no_progress_warn", rounds=self._no_progress_count)
            return True
        return False

    def reset(self) -> None:
        """重置所有计数器"""
        self._param_history.clear()
        self._tool_failures.clear()
        self._no_progress_count = 0

    # ── M1.6: 无进展检测 (比对最近N轮内容) ──

    def check_no_progress(self, turns_last_n: list[str], similarity_threshold: float = 0.8) -> bool:
        """检查最近N轮是否无实质进展

        Args:
            turns_last_n: 最近N轮的LLM输出内容 (每轮前100字符)
            similarity_threshold: 相似度阈值，超过此值视为重复

        Returns:
            True 表示检测到循环/无进展
        """
        if len(turns_last_n) < _get_limit("max_no_progress", _FALLBACK_MAX_NO_PROGRESS):
            return False
        # 简化的重复检测: 如果最近N轮中有>=80%内容相同，视为无进展
        max_no_progress = _get_limit("max_no_progress", _FALLBACK_MAX_NO_PROGRESS)
        last = turns_last_n[-1]
        similar_count = sum(
            1 for t in turns_last_n[-max_no_progress:] if _content_similarity(t, last) >= similarity_threshold
        )
        if similar_count >= max_no_progress:
            logger.warning("guardrails_no_progress_detected", similar_count=similar_count, rounds=len(turns_last_n))
            return True
        return False

    # ── M1.6: 统一入口 ──

    def check_before_call(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """工具调用前统一检查入口

        Returns:
            {"allow": bool, "reason": str, "action": "allow"|"hard_stop"|"warn"|"fallback_to_prompt"}
        """
        # M5-B: 0. Denial fallback 检查 → 拒绝过多则强制提示
        from src.engine.agent.denial_tracker import should_fallback

        if should_fallback(self._denial_state):
            return {
                "allow": False,
                "reason": f"Permission denied {self._denial_state.consecutive_denials}x consecutively ({self._denial_state.total_denials} total). Consider adjusting permissions.",
                "action": "fallback_to_prompt",
            }

        # 1. 同参数重复检测 → hard_stop
        max_repeats = _get_limit("max_repeats", _FALLBACK_MAX_REPEATS)
        if self.check_same_params(tool_name, kwargs):
            return {
                "allow": False,
                "reason": f"Same params repeated {max_repeats}x on {tool_name}",
                "action": "hard_stop",
            }

        # 2. 同工具失败检测 → hard_stop
        max_failures = _get_limit("max_failures", _FALLBACK_MAX_FAILURES)
        if self.is_hard_stop(tool_name):
            return {"allow": False, "reason": f"Tool {tool_name} failed {max_failures}x", "action": "hard_stop"}

        return {"allow": True, "reason": "", "action": "allow"}

    def check_after_turn(self, has_tool_calls: bool, llm_output_preview: str = "") -> dict[str, Any]:
        """每轮结束后检查

        Returns:
            {"continue": bool, "action": "allow"|"hard_stop"|"warn", "warn_message": str}
        """
        # 3. 无进展检测 → warn (不中断)
        if not has_tool_calls:
            self.record_no_progress()
            if self.should_warn():
                return {
                    "continue": True,
                    "action": "warn",
                    "warn_message": (
                        "⚠️ 检测到连续无工具调用循环。请调整策略，使用工具完成任务，"
                        "或直接输出最终结果。避免重复相似内容。"
                    ),
                }

        return {"continue": True, "action": "allow", "warn_message": ""}

    def check_after_call(
        self,
        tool_name: str,
        raw_output: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """工具/LLM 调用后校验输出格式。

        与 OutputGuardrail 配合，校验 JSON 输出是否符合 Schema。
        失败时触发重试（max 3 次）。

        Returns:
            {
                "valid": bool,
                "data": dict | None,
                "errors": list[str],
                "retry": bool,
                "retry_prompt": str | None,
            }
        """
        from src.engine.agent.output_guardrail import OutputGuardrail

        if not raw_output:
            return {"valid": False, "data": None, "errors": ["空输出"], "retry": False, "retry_prompt": None}

        guardrail = OutputGuardrail(max_retry=0)  # 本方法不自己重试，返回 retry_prompt 供调用方处理
        result = guardrail.validate(
            task_prompt="",
            raw_output=raw_output,
            schema=schema,
        )

        if result.valid:
            return {"valid": True, "data": result.data, "errors": [], "retry": False, "retry_prompt": None}

        # 校验失败，返回重试提示
        from src.engine.agent.output_guardrail import build_retry_prompt

        retry_prompt = build_retry_prompt(
            original_prompt="",
            previous_output=raw_output,
            errors=result.errors,
            schema=schema,
        )
        return {
            "valid": False,
            "data": None,
            "errors": result.errors,
            "retry": True,
            "retry_prompt": retry_prompt,
        }

    def record_call(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        success: bool,
        result_preview: str = "",
    ) -> None:
        """记录工具调用结果 (调用后)"""
        if not success:
            self.record_tool_failure(tool_name)

    @staticmethod
    def _hash_args(args: dict[str, Any]) -> str:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)


def _content_similarity(a: str, b: str) -> float:
    """简单的字符串相似度 (Jaccard-like)"""
    if not a or not b:
        return 0.0
    # 使用字符级 bigram 比较
    a_grams = {a[i : i + 2] for i in range(max(0, len(a) - 1))}
    b_grams = {b[i : i + 2] for i in range(max(0, len(b) - 1))}
    if not a_grams or not b_grams:
        return 0.0
    intersection = a_grams & b_grams
    union = a_grams | b_grams
    return len(intersection) / len(union) if union else 0.0
