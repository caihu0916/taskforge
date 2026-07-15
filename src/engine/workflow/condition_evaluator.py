
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""工作流条件评估引擎 — 支持多种条件类型的运行时评估

设计决策:
  - 独立于 PDCAEngine，单一职责
  - 复用 dsl.evaluate_condition 的 AST 白名单安全评估
  - 扩展支持 5+ 条件类型: expression, result_match, step_status, value_range, always/never
  - 评估延迟 < 100ms (纯内存操作，无IO)
  - Feature Flag 守护: workflow_branch 关闭时所有条件评估返回 True（不跳过）

条件类型:
  1. expression — 通用表达式 (a > b and c == d)，变量从 store 替换
  2. result_match — 上一步结果匹配 (正则/关键词/JSON路径)
  3. step_status — 指定步骤状态检查 (step_id == "done"/"failed")
  4. value_range — 数值范围检查 (score >= 0.7)
  5. always / never — 无条件真/假（用于模板占位）
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── 条件类型常量 ──

COND_EXPRESSION = "expression"  # 通用表达式
COND_RESULT_MATCH = "result_match"  # 上一步结果匹配
COND_STEP_STATUS = "step_status"  # 步骤状态检查
COND_VALUE_RANGE = "value_range"  # 数值范围
COND_ALWAYS = "always"  # 无条件真
COND_NEVER = "never"  # 无条件假


class ConditionEvaluator:
    """工作流条件评估引擎

    线程安全 (无状态，所有数据通过参数传入)
    """

    def evaluate(
        self,
        condition: str,
        *,
        store: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        flag_enabled: bool = True,
    ) -> bool:
        """评估条件表达式

        Args:
            condition: 条件字符串，格式为 "type:payload"
                       - "expression:a > b" — 通用表达式
                       - "result_match:关键词" — 上一步结果包含关键词
                       - "result_match:/regex/" — 上一步结果匹配正则
                       - "step_status:step_id=status" — 步骤状态检查
                       - "value_range:key>=val" — 数值范围
                       - "always" — 无条件真
                       - "never" — 无条件假
                       - 纯表达式(无type:前缀) — 默认当 expression 处理
            store: 运行时 KV 缓存（条件变量来源）
            context: 执行上下文（含 prev_result, step_statuses 等）
            flag_enabled: workflow_branch feature flag 是否开启

        Returns:
            bool — 条件是否满足
        """
        if not flag_enabled:
            # Flag 关闭 → 不跳过任何分支（返回 True = 执行）
            return True

        if not condition or not condition.strip():
            # 无条件 → 不跳过
            return True

        store = store or {}
        context = context or {}

        t0 = time.monotonic()

        try:
            result = self._dispatch(condition.strip(), store, context)
        except Exception as e:
            logger.warning("condition_eval_error", condition=condition[:100], error=str(e), exc_info=True)
            # 评估出错 → 安全策略: 不跳过（返回 True），避免意外跳过必要步骤
            result = True

        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > 50:
            logger.warning("condition_eval_slow", condition=condition[:80], elapsed_ms=round(elapsed_ms, 2))

        return result

    def _dispatch(self, condition: str, store: dict[str, Any], context: dict[str, Any]) -> bool:
        """根据条件类型分发评估"""
        # 快速路径: 无前缀的 always/never 关键字
        lower = condition.lower()
        if lower == COND_ALWAYS:
            return True
        if lower == COND_NEVER:
            return False

        # 分离类型前缀
        if ":" in condition:
            cond_type, payload = condition.split(":", 1)
            cond_type = cond_type.strip().lower()
            payload = payload.strip()
        else:
            # 无前缀 → 默认 expression
            cond_type = COND_EXPRESSION
            payload = condition

        if cond_type == COND_ALWAYS:
            return True
        if cond_type == COND_NEVER:
            return False
        if cond_type == COND_EXPRESSION:
            return self._eval_expression(payload, store)
        if cond_type == COND_RESULT_MATCH:
            return self._eval_result_match(payload, context)
        if cond_type == COND_STEP_STATUS:
            return self._eval_step_status(payload, context)
        if cond_type == COND_VALUE_RANGE:
            return self._eval_value_range(payload, store)

        # 未知类型 → 当 expression 兜底
        logger.warning("unknown_condition_type", cond_type=cond_type, fallback="expression")
        return self._eval_expression(condition, store)

    def _eval_expression(self, expr: str, store: dict[str, Any]) -> bool:
        """通用表达式评估 — 委托给 dsl.evaluate_condition"""
        from src.engine.workflow.dsl import evaluate_condition

        return evaluate_condition(expr, store)

    def _eval_result_match(self, payload: str, context: dict[str, Any]) -> bool:
        """上一步结果匹配评估

        payload 格式:
          - "关键词" — 上一步结果包含该关键词（不区分大小写）
          - "/regex/" — 上一步结果匹配正则
        """
        prev_result = str(context.get("prev_result", ""))
        if not prev_result:
            return False

        if payload.startswith("/") and payload.endswith("/"):
            # 正则匹配
            pattern = payload[1:-1]
            try:
                return bool(re.search(pattern, prev_result, re.IGNORECASE))
            except re.error as e:
                logger.warning("result_match_regex_error", pattern=pattern, error=str(e))
                return False
        else:
            # 关键词包含（不区分大小写）
            return payload.lower() in prev_result.lower()

    def _eval_step_status(self, payload: str, context: dict[str, Any]) -> bool:
        """步骤状态检查

        payload 格式: "step_id=status" 或 "step_id!=status"
        status: done/failed/pending/running/skipped/approval_pending
        """
        step_statuses: dict[str, str] = context.get("step_statuses", {})

        # 支持 != 和 == 两种操作符
        if "!=" in payload:
            step_id, expected = payload.split("!=", 1)
            step_id = step_id.strip()
            expected = expected.strip().lower()
            actual = step_statuses.get(step_id, "").lower()
            return actual != expected
        if "=" in payload or "==" in payload:
            sep = "==" if "==" in payload else "="
            step_id, expected = payload.split(sep, 1)
            step_id = step_id.strip()
            expected = expected.strip().lower()
            actual = step_statuses.get(step_id, "").lower()
            return actual == expected
        # 只有 step_id → 检查是否为 done
        step_id = payload.strip()
        return step_statuses.get(step_id, "").lower() == "done"

    def _eval_value_range(self, payload: str, store: dict[str, Any]) -> bool:
        """数值范围检查

        payload 格式: "key>=val" / "key>val" / "key<=val" / "key<val" / "key==val" / "key!=val"
        key: store 中的变量名
        val: 比较数值
        """
        # 支持 >=, <=, !=, >, <, ==, =
        for op in (">=", "<=", "!=", "==", ">", "<", "="):
            if op in payload:
                key, val_str = payload.split(op, 1)
                key = key.strip()
                val_str = val_str.strip()
                break
        else:
            logger.warning("value_range_no_operator", payload=payload)
            return True

        actual = store.get(key)
        if actual is None:
            return False

        try:
            actual_num = float(actual)
            compare_num = float(val_str)
        except (ValueError, TypeError):
            # 非数值 → 字符串比较
            actual_num = str(actual)
            compare_num = val_str

        if op == ">=":
            return actual_num >= compare_num
        if op == "<=":
            return actual_num <= compare_num
        if op == ">":
            return actual_num > compare_num
        if op == "<":
            return actual_num < compare_num
        if op in ("==", "="):
            return actual_num == compare_num
        if op == "!=":
            return actual_num != compare_num

        return True  # 不应到达


# ── 单例 ──

_evaluator: ConditionEvaluator | None = None


def get_condition_evaluator() -> ConditionEvaluator:
    """获取 ConditionEvaluator 单例"""
    global _evaluator
    if _evaluator is None:
        _evaluator = ConditionEvaluator()
    return _evaluator


# ── Skill-Gap 1-2-3: 条件节点属性面板增强 ──


def preview_condition(
    condition: str,
    store: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """预览条件评估结果（不抛异常，用于属性面板实时预览）

    Args:
        condition: 条件字符串
        store: 运行时 KV 缓存
        context: 执行上下文

    Returns:
        {
            "valid": bool,            #条件语法是否有效
            "result": bool | None,    #评估结果（语法无效时为 None）
            "error": str | None,      #错误信息
            "type": str,              #条件类型
            "payload": str,           #条件负载
            "description": str,       #可读描述
        }
    """
    if not condition or not condition.strip():
        return {
            "valid": True,
            "result": True,  # 无条件 → 不跳过
            "error": None,
            "type": "empty",
            "payload": "",
            "description": "无条件（始终执行）",
        }

    store = store or {}
    context = context or {}
    cond_str = condition.strip()

    # 识别条件类型
    cond_type, payload = _parse_condition_type(cond_str)

    try:
        evaluator = get_condition_evaluator()
        result = evaluator._dispatch(cond_str, store, context)
        return {
            "valid": True,
            "result": result,
            "error": None,
            "type": cond_type,
            "payload": payload,
            "description": _describe_condition(cond_type, payload),
        }
    except Exception as e:
        return {
            "valid": False,
            "result": None,
            "error": str(e),
            "type": cond_type,
            "payload": payload,
            "description": f"评估失败: {e}",
        }


def _parse_condition_type(condition: str) -> tuple[str, str]:
    """解析条件类型和负载"""
    lower = condition.lower()
    if lower == COND_ALWAYS:
        return COND_ALWAYS, ""
    if lower == COND_NEVER:
        return COND_NEVER, ""

    if ":" in condition:
        cond_type, payload = condition.split(":", 1)
        return cond_type.strip().lower(), payload.strip()

    return COND_EXPRESSION, condition


def _describe_condition(cond_type: str, payload: str) -> str:
    """生成条件的可读描述"""
    descriptions = {
        COND_ALWAYS: "无条件执行",
        COND_NEVER: "永不执行",
        COND_EXPRESSION: f"表达式: {payload}",
        COND_RESULT_MATCH: f"结果匹配: {payload}",
        COND_STEP_STATUS: f"步骤状态: {payload}",
        COND_VALUE_RANGE: f"数值范围: {payload}",
    }
    return descriptions.get(cond_type, f"未知条件: {cond_type}")


def validate_condition(condition: str) -> tuple[bool, str | None]:
    """验证条件语法（不执行评估）

    Args:
        condition: 条件字符串

    Returns:
        (is_valid, error_message)
    """
    if not condition or not condition.strip():
        return True, None

    cond_str = condition.strip()
    cond_type, payload = _parse_condition_type(cond_str)

    if cond_type in (COND_ALWAYS, COND_NEVER):
        return True, None

    if cond_type == COND_EXPRESSION:
        # 表达式：尝试解析（不执行）
        try:
            from src.engine.workflow.dsl import evaluate_condition

            # 用空 store 测试语法
            evaluate_condition(payload, {})
            return True, None
        except Exception as e:
            return False, f"表达式语法错误: {e}"

    if cond_type == COND_RESULT_MATCH:
        # 结果匹配：检查正则是否有效
        if payload.startswith("/") and payload.endswith("/"):
            pattern = payload[1:-1]
            try:
                re.compile(pattern)
                return True, None
            except re.error as e:
                return False, f"正则表达式错误: {e}"
        return True, None

    if cond_type == COND_STEP_STATUS:
        # 步骤状态：检查格式
        if "!=" not in payload and "=" not in payload:
            return False, "格式应为: step_id=status 或 step_id!=status"
        return True, None

    if cond_type == COND_VALUE_RANGE:
        # 数值范围：检查操作符
        operators = [">=", "<=", "!=", "==", ">", "<", "="]
        if not any(op in payload for op in operators):
            return False, "缺少比较操作符 (>=, <=, !=, ==, >, <)"
        return True, None

    # 未知类型
    return False, f"未知条件类型: {cond_type}"


def get_condition_variables(condition: str) -> list[str]:
    """提取条件中引用的变量名（用于属性面板提示）

    Args:
        condition: 条件字符串

    Returns:
        变量名列表
    """
    if not condition or not condition.strip():
        return []

    cond_str = condition.strip()
    cond_type, payload = _parse_condition_type(cond_str)

    if cond_type in (COND_ALWAYS, COND_NEVER):
        return []

    if cond_type == COND_VALUE_RANGE:
        # 提取 key（操作符前的部分）
        for op in (">=", "<=", "!=", "==", ">", "<", "="):
            if op in payload:
                key = payload.split(op, 1)[0].strip()
                return [key] if key else []
        return []

    if cond_type == COND_STEP_STATUS:
        # 提取 step_id
        for sep in ("!=", "==", "="):
            if sep in payload:
                step_id = payload.split(sep, 1)[0].strip()
                return [step_id] if step_id else []
        return [payload.strip()]

    if cond_type == COND_EXPRESSION:
        # 表达式：提取标识符（简单实现）
        # 匹配变量名模式：字母/下划线开头，后跟字母/数字/下划线
        identifiers = re.findall(r"\b[a-zA-Z_]\w*\b", payload)
        # 排除关键字
        keywords = {"and", "or", "not", "true", "false", "True", "False", "None", "in", "is"}
        return [id for id in identifiers if id not in keywords]

    return []


def get_condition_help() -> dict[str, Any]:
    """获取条件类型帮助文档（用于属性面板提示）

    Returns:
        {
            "types": [...],        #所有条件类型
            "examples": [...],     #示例
            "operators": [...],    #支持的操作符
        }
    """
    return {
        "types": [
            {
                "id": COND_EXPRESSION,
                "name": "通用表达式",
                "description": "使用 Python 表达式语法，变量从 store 替换",
                "example": "amount > 1000 and status == 'approved'",
            },
            {
                "id": COND_RESULT_MATCH,
                "name": "结果匹配",
                "description": "上一步结果包含关键词或匹配正则",
                "example": "result_match:成功 或 result_match:/错误|失败/",
            },
            {
                "id": COND_STEP_STATUS,
                "name": "步骤状态",
                "description": "检查指定步骤的状态",
                "example": "step_status:s1=DONE 或 step_status:s1!=FAILED",
            },
            {
                "id": COND_VALUE_RANGE,
                "name": "数值范围",
                "description": "检查 store 中变量的数值范围",
                "example": "value_range:amount>=1000 或 value_range:score<0.7",
            },
            {
                "id": COND_ALWAYS,
                "name": "始终执行",
                "description": "无条件执行（占位用）",
                "example": "always",
            },
            {
                "id": COND_NEVER,
                "name": "永不执行",
                "description": "永不执行（禁用占位）",
                "example": "never",
            },
        ],
        "examples": [
            {"condition": "amount > 1000", "description": "金额大于 1000"},
            {"condition": "result_match:成功", "description": "上一步结果包含'成功'"},
            {"condition": "step_status:s1=DONE", "description": "步骤 s1 已完成"},
            {"condition": "value_range:score>=0.7", "description": "评分 ≥ 0.7"},
            {"condition": "always", "description": "无条件执行"},
        ],
        "operators": [">=", "<=", "!=", "==", ">", "<", "and", "or", "not"],
    }
