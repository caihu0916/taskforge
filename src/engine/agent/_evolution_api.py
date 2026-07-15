
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent进化引擎 — 向后兼容重导出

FIX-H1: 路由定义已迁移至 src.api.routes.evolution_routes.py，
此文件仅保留向后兼容重导出 + Pydantic 模型。
"""

from __future__ import annotations

import warnings

from pydantic import BaseModel


class RecordExecutionRequest(BaseModel):
    agent_id: str
    task_id: str
    task_description: str
    strategy_id: str
    result: str
    duration: float = 0.0
    tokens: int = 0
    user_score: float = 0.0
    error: str = ""
    quality_score: float = 0.0


class AddMemoryRequest(BaseModel):
    category: str
    title: str
    content: str
    tags: list[str] = []


def create_evolution_api():
    """向后兼容 — 路由已迁移至 src.api.routes.evolution_routes"""
    warnings.warn(
        "Importing create_evolution_api from src/engine/agent/_evolution_api.py is deprecated. Use src.api.routes.evolution_routes instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from src.api.routes.evolution_routes import create_evolution_api as _create

    return _create()
