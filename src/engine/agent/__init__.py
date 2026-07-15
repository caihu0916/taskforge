
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge Agent 引擎 — 角色系统 + 编编 + 进化 + 模板 + 部门看板 + 管道流"""

from __future__ import annotations

from .department import DepartmentManager, get_department_manager
from .evolution import EvolutionEngine, EvolutionPhase, EvolutionSession, EvolutionStatus, EvolutionStep
from .flow import AsyncNode, Context, Flow, Node, NodeStatus
from .matcher import RoleMatch, RoleMatcher
from .pipeline import PipelineEngine, get_pipeline_engine
from .prompts import PromptRenderer
from .roles import ROLE_DEFINITIONS, AgentRole, Capability, RoleDefinition, get_role_definition, list_roles
from .template_engine import StepDef, TemplateDef, TemplateEngine

__all__ = [
    "ROLE_DEFINITIONS",
    "AgentRole",
    "AsyncNode",
    "Capability",
    "Context",
    "DepartmentManager",
    "EvolutionEngine",
    "EvolutionPhase",
    "EvolutionSession",
    "EvolutionStatus",
    "EvolutionStep",
    "Flow",
    "Node",
    "NodeStatus",
    "PipelineEngine",
    "PromptRenderer",
    "RoleDefinition",
    "RoleMatch",
    "RoleMatcher",
    "StepDef",
    "TemplateDef",
    "TemplateEngine",
    "get_department_manager",
    "get_pipeline_engine",
    "get_role_definition",
    "list_roles",
]
