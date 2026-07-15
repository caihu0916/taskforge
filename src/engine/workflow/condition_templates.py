
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""条件模板库 — 常用条件分支预设

提供开箱即用的条件模板，覆盖一人公司常见业务场景:
  - 审批门禁: 金额/数量超阈值需人工审批
  - 质量门禁: 步骤结果包含关键词/正则才放行
  - 分支路由: 根据变量值走不同路径
  - 失败重试: 前序步骤失败时触发备选路径
  - 时效检查: 数值在指定范围内才继续

每个模板返回 condition 字符串，可直接赋值给 Step.condition
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 模板定义 ──

CONDITION_TEMPLATES: dict[str, dict[str, Any]] = {
    # ── 审批门禁类 ──
    "amount_over_threshold": {
        "name": "金额超阈值",
        "description": "当金额超过指定阈值时执行（如审批流程）",
        "category": "approval",
        "condition_template": "value_range:{{amount_key}}>={{threshold}}",
        "params": {
            "amount_key": {"type": "str", "default": "amount", "desc": "store中金额变量名"},
            "threshold": {"type": "float", "default": 1000, "desc": "阈值金额"},
        },
        "example": "value_range:amount>=1000",
    },
    "count_over_threshold": {
        "name": "数量超阈值",
        "description": "当数量超过指定值时执行",
        "category": "approval",
        "condition_template": "value_range:{{count_key}}>={{threshold}}",
        "params": {
            "count_key": {"type": "str", "default": "count", "desc": "store中数量变量名"},
            "threshold": {"type": "int", "default": 10, "desc": "阈值数量"},
        },
        "example": "value_range:count>=10",
    },
    # ── 质量门禁类 ──
    "result_contains": {
        "name": "结果包含关键词",
        "description": "上一步结果包含指定关键词时执行",
        "category": "quality",
        "condition_template": "result_match:{{keyword}}",
        "params": {
            "keyword": {"type": "str", "default": "成功", "desc": "匹配关键词"},
        },
        "example": "result_match:成功",
    },
    "result_matches_regex": {
        "name": "结果匹配正则",
        "description": "上一步结果匹配正则表达式时执行",
        "category": "quality",
        "condition_template": "result_match:/{{pattern}}/",
        "params": {
            "pattern": {"type": "str", "default": "错误|失败|异常", "desc": "正则表达式"},
        },
        "example": "result_match:/错误|失败|异常/",
    },
    "score_above": {
        "name": "评分高于阈值",
        "description": "质量评分高于指定值时执行",
        "category": "quality",
        "condition_template": "value_range:{{score_key}}>={{threshold}}",
        "params": {
            "score_key": {"type": "str", "default": "score", "desc": "store中评分变量名"},
            "threshold": {"type": "float", "default": 0.7, "desc": "阈值评分"},
        },
        "example": "value_range:score>=0.7",
    },
    # ── 分支路由类 ──
    "if_approved": {
        "name": "已审批",
        "description": "当approved变量为True时执行",
        "category": "routing",
        "condition_template": "value_range:{{approved_key}}==1",
        "params": {
            "approved_key": {"type": "str", "default": "approved", "desc": "store中审批状态变量名"},
        },
        "example": "value_range:approved==1",
    },
    "if_type_equals": {
        "name": "类型匹配",
        "description": "当类型变量等于指定值时执行",
        "category": "routing",
        "condition_template": "result_match:{{type_value}}",
        "params": {
            "type_value": {"type": "str", "default": "urgent", "desc": "期望类型值"},
        },
        "example": "result_match:urgent",
    },
    # ── 失败重试类 ──
    "on_step_failed": {
        "name": "前序步骤失败",
        "description": "指定步骤失败时执行（备选路径）",
        "category": "failure",
        "condition_template": "step_status:{{step_id}}=FAILED",
        "params": {
            "step_id": {"type": "str", "default": "s1", "desc": "监控步骤ID"},
        },
        "example": "step_status:s1=FAILED",
    },
    "on_step_done": {
        "name": "前序步骤成功",
        "description": "指定步骤成功完成时执行",
        "category": "failure",
        "condition_template": "step_status:{{step_id}}=DONE",
        "params": {
            "step_id": {"type": "str", "default": "s1", "desc": "监控步骤ID"},
        },
        "example": "step_status:s1=DONE",
    },
    # ── 特殊占位 ──
    "unconditional": {
        "name": "无条件执行",
        "description": "始终执行（占位用）",
        "category": "special",
        "condition_template": "always",
        "params": {},
        "example": "always",
    },
    "never_execute": {
        "name": "永不执行",
        "description": "永不执行（禁用占位）",
        "category": "special",
        "condition_template": "never",
        "params": {},
        "example": "never",
    },
}


def list_condition_templates(category: str | None = None) -> list[dict[str, Any]]:
    """列出条件模板

    Args:
        category: 按类别过滤 (approval/quality/routing/failure/special)，None返回全部
    """
    templates = []
    for key, tpl in CONDITION_TEMPLATES.items():
        if category and tpl.get("category") != category:
            continue
        templates.append(
            {
                "id": key,
                "name": tpl["name"],
                "description": tpl["description"],
                "category": tpl["category"],
                "params": tpl["params"],
                "example": tpl["example"],
            }
        )
    return templates


def build_condition(template_id: str, **kwargs: Any) -> str:
    """从模板构建条件字符串

    Args:
        template_id: 模板ID
        **kwargs: 模板参数（覆盖默认值）

    Returns:
        可直接赋值给 Step.condition 的条件字符串
    """
    tpl = CONDITION_TEMPLATES.get(template_id)
    if tpl is None:
        logger.warning("condition_template_not_found", template_id=template_id)
        return "always"  # 安全回退

    # 无参数模板（always/never）
    if not tpl["params"]:
        return tpl["condition_template"]

    # 合并默认参数与传入参数
    merged = {}
    for param_name, param_def in tpl["params"].items():
        merged[param_name] = kwargs.get(param_name, param_def["default"])

    # 替换模板变量 {{var}}
    condition = tpl["condition_template"]
    for k, v in merged.items():
        condition = condition.replace(f"{{{{{k}}}}}", str(v))

    return condition


def get_condition_template(template_id: str) -> dict[str, Any] | None:
    """获取单个条件模板详情"""
    tpl = CONDITION_TEMPLATES.get(template_id)
    if tpl is None:
        return None
    return {
        "id": template_id,
        "name": tpl["name"],
        "description": tpl["description"],
        "category": tpl["category"],
        "condition_template": tpl["condition_template"],
        "params": tpl["params"],
        "example": tpl["example"],
    }
