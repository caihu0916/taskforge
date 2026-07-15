
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge Pipeline Helpers — 拆自 pipeline.py，符合T9铁律.

包含: 行转换 + 种子数据初始化
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def row_to_pipeline(r) -> dict:
    """数据库行 → 管道dict"""
    steps = json.loads(r["steps"] or "[]")
    return {
        "id": r["id"],
        "name": r["name"],
        "department": r["department"],
        "description": r["description"],
        "steps": steps,
        "is_builtin": bool(r["is_builtin"]),
        "enabled": bool(r["enabled"]),
    }


def row_to_run(r) -> dict:
    """数据库行 → 执行记录dict"""
    return {
        "id": r["id"],
        "pipeline_id": r["pipeline_id"],
        "pipeline_name": r["pipeline_name"],
        "department": r["department"],
        "steps_total": r["steps_total"],
        "steps_done": r["steps_done"],
        "status": r["status"],
        "results": json.loads(r["results"] or "[]"),
        "started_at": r["started_at"],
        "completed_at": r["completed_at"],
    }
