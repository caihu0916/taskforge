
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Role definitions — 34角色RoleDefinition聚合入口

数据按三组拆分到独立模块, 此文件仅做import+merge, 保持外部导入路径不变.
- _roles_core.py: Core 12 (掌柜/爆款制造机/成交猎手/调研员/客服/陪伴师/账房/管家/合规官/主播/分析师/操作员)
- _roles_agency.py: Agency 15 (行业运营专家)
- _roles_codecorps.py: Code Corps 7 (代码师团)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._roles_agency import AGENCY_ROLE_DEFINITIONS
from ._roles_codecorps import CODECORPS_ROLE_DEFINITIONS
from ._roles_core import CORE_ROLE_DEFINITIONS

if TYPE_CHECKING:
    from ._base import AgentRole, RoleDefinition

ROLE_DEFINITIONS: dict[AgentRole, RoleDefinition] = {
    **CORE_ROLE_DEFINITIONS,
    **AGENCY_ROLE_DEFINITIONS,
    **CODECORPS_ROLE_DEFINITIONS,
}
