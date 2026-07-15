
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 工作流 API — 向后兼容 re-export.

路由已迁移至 src.api.routes.workflow_routes.py。
本文件保留 Pydantic 模型 + 幂等性工具供其他模块引用，并暴露 create_workflow_api() 兼容旧调用。
"""

from __future__ import annotations

import sqlite3
import warnings
from typing import Any

import structlog
from pydantic import BaseModel, Field

from src.engine.workflow import idempotency as _idempotency

logger = structlog.get_logger(__name__)


# ── 幂等性工具 ───────────────────────────────────────────


def require_idempotency_key(
    x_idempotency_key: str | None = None,
) -> str | None:
    """向后兼容 — 路由层已使用 Header() 注入。"""
    if not x_idempotency_key:
        return None
    value = x_idempotency_key.strip()
    if len(value) > 200:
        value = value[:200]
    return value or None


class IdempotencyHelper:
    """幂等性检查/写入助手 — 供引擎层内部使用。"""

    def __init__(self, key: str | None, endpoint: str):
        self.key = key
        self.endpoint = endpoint
        self._cached: dict[str, Any] | None = None
        self._can_execute: bool = True
        if key:
            try:
                cached_raw = _idempotency.lookup(key, endpoint)
                if cached_raw is not None:
                    self._cached = {**cached_raw, "cached": True}
                    self._can_execute = False
                else:
                    self._can_execute = _idempotency.acquire(key, endpoint)
            except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError) as exc:
                logger.warning("idempotency_lookup_failed", error=str(exc), endpoint=endpoint)
                self._cached = None
                self._can_execute = True

    @property
    def cached(self) -> dict[str, Any] | None:
        return self._cached

    @property
    def can_execute(self) -> bool:
        return self._can_execute

    def save(self, response: dict[str, Any], workflow_id: str | None = None) -> None:
        if not self.key:
            return
        try:
            response_to_save = {k: v for k, v in response.items() if k != "cached"}
            _idempotency.store(self.key, self.endpoint, response_to_save, workflow_id=workflow_id)
        except (ValueError, KeyError, RuntimeError, sqlite3.OperationalError) as exc:
            logger.warning("idempotency_store_failed", error=str(exc), endpoint=self.endpoint)


# ── Pydantic Request/Response Models ──


class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="工作流名称")
    description: str = Field(default="", max_length=500, description="描述")
    template_id: str = Field(default="", description="来源模板ID")
    scenario_workflow_id: str = Field(default="", description="场景工作流模板ID")
    scenario_id: str = Field(default="content_ecommerce", description="业务场景ID")
    graph_dsl: str = Field(default="", description="图形化工作流编排DSL(JSON)")


class ExecuteStepRequest(BaseModel):
    result: str = Field(default="", max_length=5000, description="步骤执行结果")
    error: str = Field(default="", max_length=2000, description="失败原因(空=成功)")


class RejectStepRequest(BaseModel):
    reason: str = Field(default="", max_length=2000, description="驳回原因")


class UpdateWorkflowRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100, description="工作流名称")
    description: str | None = Field(default=None, max_length=500, description="描述")
    phases: list[dict[str, Any]] | None = Field(default=None, description="更新阶段配置")
    graph_dsl: str | None = Field(default=None, description="图形化工作流编排DSL(JSON)")


class RunDslRequest(BaseModel):
    script: str = Field(..., min_length=1, description="DSL 脚本文本")
    args: dict[str, Any] | None = Field(default=None, description="运行时参数")


class StoreSetRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, description="变量名")
    value: Any = Field(..., description="变量值")


class SaveGraphRequest(BaseModel):
    graph_dsl: str = Field(..., min_length=1, description="图形化工作流编排DSL(JSON)")


class QuickStartRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict, description="模板变量参数")
    auto_run: bool = Field(default=True, description="是否自动执行")


class ValidateOutputRequest(BaseModel):
    raw_output: str = Field(..., description="LLM 原始输出字符串")
    json_schema: dict[str, Any] | None = Field(None, description="JSON Schema (可选)")


class ValidateOutputResponse(BaseModel):
    valid: bool
    data: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    retry_prompt: str | None = None


def create_workflow_api():
    """向后兼容 — 委托给 routes 层。"""
    warnings.warn(
        "Importing create_workflow_api from src/engine/workflow/api.py is deprecated. Use src.api.routes.workflow_routes instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from src.api.routes.workflow_routes import create_workflow_api as _create

    return _create()
