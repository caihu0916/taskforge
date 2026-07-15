
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 步骤操作 (执行/审批/拒绝/失败)"""

from __future__ import annotations

from src.engine.workflow._step_ops_agent import StepOpsAgentMixin
from src.engine.workflow._step_ops_simple import StepOpsSimpleMixin


class StepOpsMixin(StepOpsSimpleMixin, StepOpsAgentMixin):
    """步骤级操作方法 — 聚合器"""
