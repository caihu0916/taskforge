
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge Agent 角色 — 10角色Schema定义

角色体系 (v1, 10角色):
  掌柜/爆款制造机/成交猎手/调研员/客服/账房/管家/合规官/主播助手/数据分析师

设计决策:
  - v1免费层6个: 爆款制造机/客服/调研员/管家/合规官/成交猎手(基础版)
  - v1付费层5个: 掌柜/账房/成交猎手(完整版)/主播助手/数据分析师
  - 角色能力标签用于匹配引擎自动分配
"""

from __future__ import annotations

from ._base import AgentRole, Capability, RoleDefinition
from ._defs import ROLE_DEFINITIONS, get_role_definition, list_roles

__all__ = [
    "ROLE_DEFINITIONS",
    "AgentRole",
    "Capability",
    "RoleDefinition",
    "get_role_definition",
    "list_roles",
]
