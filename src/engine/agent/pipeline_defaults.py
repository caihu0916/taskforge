
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""pipeline_defaults — 内置管道模板和种子数据"""

from __future__ import annotations

BUILTIN_PIPELINES = [
    {
        "id": "pipe_content_prod",
        "name": "内容生产流水线",
        "department": "marketing",
        "description": "选题→创作→审核→发布全流程",
        "steps": [
            {"pos": 0, "agent_id": "researcher", "label": "选题调研"},
            {"pos": 1, "agent_id": "hitmaker", "label": "爆款创作"},
            {"pos": 2, "agent_id": "compliance", "label": "合规审核"},
            {"pos": 3, "agent_id": "caster", "label": "多渠道发布"},
        ],
        "is_builtin": 1,
    },
    {
        "id": "pipe_deal_conv",
        "name": "成交转化流水线",
        "department": "marketing",
        "description": "线索→跟进→报价→成交→复购",
        "steps": [
            {"pos": 0, "agent_id": "deal_hunter", "label": "线索捕获"},
            {"pos": 1, "agent_id": "deal_hunter", "label": "深度跟进"},
            {"pos": 2, "agent_id": "deal_hunter", "label": "智能报价"},
            {"pos": 3, "agent_id": "accountant", "label": "收款确认"},
            {"pos": 4, "agent_id": "support", "label": "售后复购"},
        ],
        "is_builtin": 1,
    },
    {
        "id": "pipe_daily_ops",
        "name": "每日运营流水线",
        "department": "ops",
        "description": "晨会→执行→复盘日报",
        "steps": [
            {"pos": 0, "agent_id": "butler", "label": "晨会调度"},
            {"pos": 1, "agent_id": "butler", "label": "任务分发"},
            {"pos": 2, "agent_id": "analyst", "label": "数据复盘"},
            {"pos": 3, "agent_id": "boss", "label": "决策审批"},
        ],
        "is_builtin": 1,
    },
]
