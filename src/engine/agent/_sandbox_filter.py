
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""G02-T03 SubAgent 沙箱隔离 — AgentSandbox 角色白名单过滤

从 sub_agent.py 拆分出的模块，包含:
  - get_sandbox_allowed_tools: 获取角色沙箱允许工具集
  - _apply_sandbox_filter: 应用沙箱过滤创建受限注册表
  - _inject_mcp_tools: 将 MCP 服务器工具注入子 Agent 注册表
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def get_sandbox_allowed_tools(role: str, parent_allowed: set[str] | None = None) -> set[str]:
    """G02-T03: 获取角色在沙箱中的允许工具集

    双重约束: 角色白名单 ∩ 父代理允许列表
    - 角色白名单: AgentSandbox 中该角色注册的工具集
    - 父代理允许列表: CacheSafeParams.allowed_tools (权限冒泡)
    - 结果 = 角色白名单 ∩ 父允许 (空父允许=不限制, 只限角色白名单)

    Args:
        role: Agent角色名
        parent_allowed: 父代理允许的工具集, None/空=不限制

    Returns:
        该角色在沙箱中允许使用的工具集
    """
    from src.engine.autonomous.security import get_agent_sandbox

    sandbox = get_agent_sandbox()

    # 获取角色白名单中的所有工具
    role_perms = sandbox.list_permissions(role)
    role_allowed = set(role_perms.get("allowed_tools", []))

    # 如果角色没有白名单, 默认只允许安全工具 (非DANGEROUS_TOOLS)
    if not role_allowed:
        from src.engine.tool.sandbox_rules import DANGEROUS_TOOLS

        # 未知角色: 不允许任何危险工具
        if parent_allowed:
            return parent_allowed - DANGEROUS_TOOLS
        return set()  # 未知角色无白名单 → 空集 (最安全)

    # 双重约束: 角色白名单 ∩ 父允许
    if parent_allowed:
        return role_allowed & parent_allowed

    # 无父限制: 仅角色白名单
    return role_allowed


def _apply_sandbox_filter(
    parent_registry: Any,
    role: str,
    parent_allowed: set[str] | None = None,
) -> Any:
    """G02-T03: 应用沙箱过滤 — 按角色白名单限制工具注册表

    这是权限冒泡+角色白名单的联合过滤:
    1. 通过 AgentSandbox 获取角色允许的工具集
    2. 与父代理允许列表求交集
    3. 仅保留交集内的工具到新注册表

    Args:
        parent_registry: 父代理的完整工具注册表
        role: 子Agent角色
        parent_allowed: 父代理允许的工具集 (CacheSafeParams.allowed_tools)

    Returns:
        受限的工具注册表 (仅包含允许的工具)
    """
    from src.engine.tool.registry import ToolRegistry

    allowed = get_sandbox_allowed_tools(role, parent_allowed)

    restricted = ToolRegistry()
    registered_count = 0
    denied_count = 0

    for tool in parent_registry.list_tools(enabled_only=True):
        if tool.name in allowed:
            try:
                restricted.register(tool)
                registered_count += 1
            except ValueError:
                pass  # 已注册，跳过
        else:
            denied_count += 1

    if denied_count > 0:
        logger.info(
            "sandbox_tools_filtered",
            role=role,
            registered=registered_count,
            denied=denied_count,
        )

    return restricted


def _inject_mcp_tools(tool_reg: Any, mcp_servers: list[str]) -> Any:
    """P2-2.1: 将指定 MCP 服务器的工具注入子 Agent 的 tool_registry

    从全局 MCPClientOrchestrator 获取指定服务器的工具,
    创建 OrchestratorToolAdapter 并注册到 tool_reg。
    未知服务器静默跳过（仅日志警告），不阻塞子 Agent 启动。

    Args:
        tool_reg: ToolRegistry 实例（可能是受限副本）
        mcp_servers: 需要注入的服务器名称列表

    Returns:
        注入了 MCP 工具的 tool_reg（同一个实例）
    """
    try:
        from src.engine.mcp.adapter import OrchestratorToolAdapter
        from src.engine.mcp.orchestrator import get_mcp_orchestrator
    except ImportError:
        logger.warning("mcp_inject_import_failed", servers=mcp_servers)
        return tool_reg

    try:
        orchestrator = get_mcp_orchestrator()
    except Exception as e:
        logger.warning("mcp_inject_orchestrator_unavailable", error=str(e), servers=mcp_servers)
        return tool_reg

    injected_count = 0
    skipped_servers: list[str] = []

    for server_name in mcp_servers:
        # 获取该服务器已发现的所有工具
        server_tools = [t for t in orchestrator.list_all_tools() if t.server_name == server_name]
        if not server_tools:
            skipped_servers.append(server_name)
            continue

        for tool_def in server_tools:
            try:
                adapter = OrchestratorToolAdapter(orchestrator, tool_def)
                tool_reg.register(adapter, category="mcp", tags=["external", server_name])
                injected_count += 1
            except (ValueError, Exception) as e:
                # ValueError: 名称冲突（已注册）, 其他: 安全跳过
                logger.debug("mcp_inject_tool_skipped", tool=tool_def.prefixed_name, error=str(e))

    if injected_count > 0:
        logger.info(
            "mcp_tools_injected",
            injected=injected_count,
            servers=mcp_servers,
            skipped_servers=skipped_servers,
        )
    elif skipped_servers:
        logger.warning(
            "mcp_inject_no_tools_found",
            servers=mcp_servers,
            skipped_servers=skipped_servers,
        )

    return tool_reg
