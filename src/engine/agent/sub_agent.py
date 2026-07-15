
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge SubAgent 动态生成和执行

设计:
  - spawn_agent(): 创建临时子Agent，执行后自动清理
  - 子Agent继承父Agent的SharedContextPool和LLM路由
  - 结果回写到agent_executions表，与父执行关联
  - 受Feature Flag "sub_agent_spawn" 控制

P1-1 Prompt Cache共享 (参考 claude-code promptCache):
  - shared_system_prompt: 共享的系统提示词前缀
  - prompt_cache_key: 缓存键，用于 LLM API prompt caching
  - 子代理共享父代理的系统提示词，减少重复 token 消耗

P1-2 Fork子代理增强 (参考 claude-code forkSubagent):
  - CacheSafeParams: 缓存安全参数，避免子代理修改影响父代理
  - 上下文继承: 继承父代理对话历史(只读) + 工具结果
  - 权限冒泡: 子代理权限 <= 父代理权限，不能越权
  - 生命周期: 创建→执行→结果回传→自动清理

G02-T03 SubAgent沙箱隔离:
  - AgentSandbox接入: spawn时按role白名单过滤工具集
  - 权限冒泡+角色白名单双重约束: 子Agent工具集 = 父允许 ∩ 角色白名单
  - 无越权提升: 禁止子Agent获得超出角色白名单的工具

用法:
  from src.engine.agent.sub_agent import spawn_agent

  result = await spawn_agent(
      parent_agent="marketing_writing",
      role="seo_optimizer",
      task="优化标题SEO",
      context={"title": "原始标题", "keywords": ["AI", "效率"]},
  )

拆分出的子模块:
  _cache_safe_params.py — CacheSafeParams + Prompt Cache
  _sandbox_filter.py — 沙箱隔离过滤 + MCP工具注入
  _sub_agent_helpers.py — 消息构建 + 执行记录 + 上下文写回
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from src.engine.agent._cache_safe_params import CacheSafeParams
from src.engine.agent._sandbox_filter import _apply_sandbox_filter, _inject_mcp_tools

if TYPE_CHECKING:
    from src.engine.agent.dynamic_tools import DynamicToolRegistry
    from src.engine.agent.spawn_edges import SpawnEdgeManager
from src.engine.agent._sub_agent_helpers import (
    _build_sub_messages,
    _build_sub_messages_inherited,
    _create_restricted_registry,
    _create_restricted_registry_from_names,
    _record_sub_execution,
    _write_sub_context,
)

__all__ = [
    "CacheSafeParams",
    "spawn_agent",
    "spawn_agent_v3",
]

logger = structlog.get_logger(__name__)


def _check_spawn_flag() -> dict[str, Any] | None:
    """检查 sub_agent_spawn 特性开关，返回错误 dict 或 None（None 表示通过）"""
    try:
        from src.engine.feature.flags import is_enabled

        if not is_enabled("sub_agent_spawn"):
            logger.warning("sub_agent_disabled")
            return {"success": False, "error": "SubAgent spawn is disabled"}
    except Exception as e:
        logger.warning("sub_agent_flag_check_failed", error=str(e), exc_info=True)
        return {"success": False, "error": "Feature flag system unavailable, sub-agent disabled for safety"}
    return None


def _record_spawn_edge(
    edge_manager: SpawnEdgeManager | None,
    parent_agent: str,
    sub_id: str,
    task: str,
) -> str | None:
    """Δ1: 记录 spawn 关系（依赖注入，无 manager 时跳过保持向后兼容）"""
    if edge_manager is None:
        return None
    try:
        return edge_manager.record(
            parent_agent_id=parent_agent,
            child_agent_id=sub_id,
            task_summary=task,
        )
    except Exception as e:
        logger.warning("spawn_edge_record_error", sub_id=sub_id, error=str(e), exc_info=True)
        # edge 记录失败不阻断主流程
        return None


def _create_worktree(isolation: str, sub_id: str) -> str:
    """P2-2.2: 工作空间隔离 — worktree 创建，返回 path（失败/未启用返回空串）"""
    if isolation != "worktree":
        return ""
    try:
        from src.engine.feature.flags import is_enabled as ff_enabled

        if not ff_enabled("worktree_isolation"):
            logger.debug("worktree_isolation_disabled_ff", sub_id=sub_id)
            return ""
        from src.engine.agent.worktree import WorktreeManager

        worktree_path, _worktree_branch = WorktreeManager.create(name=f"sub-{sub_id}")
        logger.info(
            "worktree_created_for_sub",
            sub_id=sub_id,
            path=worktree_path,
        )
        return worktree_path
    except Exception as e:
        logger.warning("worktree_create_failed_fallback", sub_id=sub_id, error=str(e), exc_info=True)
        return ""


def _build_spawn_messages(
    role: str,
    task: str,
    context: dict[str, Any] | None,
    parent_agent: str,
    cache_safe_params: CacheSafeParams | None,
    scratchpad_dir: str,
) -> list:
    """构建子 Agent 对话上下文（P1-2: 有 CacheSafeParams 时继承父代理上下文）"""
    if cache_safe_params is not None:
        return _build_sub_messages_inherited(
            role,
            task,
            context,
            parent_agent,
            cache_safe_params,
            scratchpad_dir=scratchpad_dir,
        )
    return _build_sub_messages(role, task, context, parent_agent, scratchpad_dir=scratchpad_dir)


def _merge_dynamic_tools(
    tool_reg,
    dynamic_tool_registry: DynamicToolRegistry | None,
    cache_safe_params: CacheSafeParams | None,
    sub_id: str,
):
    """Δ2: 动态工具合并 — 仅当 cache_safe_params 携带 parent_agent 时启用

    避免无 agent 上下文的旧路径回归。合并失败不阻断主流程。
    """
    if dynamic_tool_registry is None or cache_safe_params is None or not cache_safe_params.parent_agent:
        return tool_reg
    try:
        from src.engine.agent.dynamic_tools import merge_tools_for_agent

        agent_id = cache_safe_params.parent_agent
        dynamic_tools = dynamic_tool_registry.get_tools(agent_id)
        if not dynamic_tools:
            return tool_reg
        # 合并全局工具名 + 动态工具名（全局优先，保序去重）
        global_tool_names = [t.name for t in tool_reg.list_tools(enabled_only=True)]
        merged_names = merge_tools_for_agent(global_tool_names, dynamic_tools)
        # 用合并后的工具名列表重建受限 registry
        new_reg = _create_restricted_registry_from_names(tool_reg, merged_names)
        logger.info(
            "dynamic_tools_merged",
            sub_id=sub_id,
            agent_id=agent_id,
            dynamic_count=len(dynamic_tools),
            merged_count=len(merged_names),
        )
        return new_reg
    except Exception as e:
        logger.warning(
            "dynamic_tools_merge_failed",
            sub_id=sub_id,
            error=str(e),
            exc_info=True,
        )
        # 合并失败不阻断主流程，继续用 sandbox 后的 tool_reg
        return tool_reg


def _prepare_tool_registry(
    role: str,
    cache_safe_params: CacheSafeParams | None,
    dynamic_tool_registry: DynamicToolRegistry | None,
    mcp_servers: list[str] | None,
    sub_id: str,
):
    """准备子 Agent 的工具注册表：权限冒泡 + 沙箱隔离 + 动态合并 + MCP 注入

    双重约束: 角色白名单 ∩ 父允许, 确保无越权提升
    """
    from src.engine.tool.registry import get_tool_registry

    tool_reg = get_tool_registry()

    # P1-2: 权限冒泡 — 创建受限的工具注册表
    if cache_safe_params is not None and cache_safe_params.allowed_tools:
        tool_reg = _create_restricted_registry(tool_reg, cache_safe_params)

    # G02-T03: 沙箱隔离 — 按角色白名单进一步过滤工具集
    parent_allowed = cache_safe_params.allowed_tools if cache_safe_params else None
    tool_reg = _apply_sandbox_filter(tool_reg, role, parent_allowed)

    # Δ2: 动态工具合并
    tool_reg = _merge_dynamic_tools(tool_reg, dynamic_tool_registry, cache_safe_params, sub_id)

    # P2-2.1: mcp_servers 工具注入 — 将指定服务器的 MCP 工具注册到子 Agent 的 tool_reg
    if mcp_servers:
        tool_reg = _inject_mcp_tools(tool_reg, mcp_servers)

    return tool_reg


def _cleanup_spawn_resources(
    edge_manager: SpawnEdgeManager | None,
    edge_id: str | None,
    worktree_path: str,
    sub_id: str,
) -> None:
    """清理 spawn 资源：edge 标记 + worktree 清理（成功/失败/异常均调用，保证状态收敛）"""
    # Δ1: 标记 spawn 关系已结束
    if edge_manager is not None and edge_id is not None:
        try:
            edge_manager.mark_joined(edge_id)
        except Exception as e:
            logger.warning("spawn_edge_join_error", edge_id=edge_id, error=str(e), exc_info=True)

    # P2-2.2: worktree 清理
    if worktree_path:
        try:
            from src.engine.agent.worktree import WorktreeManager

            WorktreeManager.cleanup(worktree_path, action="remove", discard_changes=True)
            logger.info("worktree_cleaned_up", sub_id=sub_id, path=worktree_path)
        except Exception as e:
            logger.warning("worktree_cleanup_failed", sub_id=sub_id, path=worktree_path, error=str(e), exc_info=True)


async def spawn_agent_legacy(
    parent_agent: str,
    role: str,
    task: str,
    context: dict[str, Any] | None = None,
    max_turns: int = 3,
    *,
    cache_safe_params: CacheSafeParams | None = None,
    mcp_servers: list[str] | None = None,
    on_progress: Any = None,  # W2
    cancel_event: Any = None,  # W3: asyncio.Event | None
    scratchpad_dir: str = "",  # W6
    isolation: str = "none",  # P2-2.2: none | worktree
    edge_manager: SpawnEdgeManager | None = None,  # Δ1: spawn 关系追踪
    dynamic_tool_registry: DynamicToolRegistry | None = None,  # Δ2: 动态工具合并
) -> dict[str, Any]:
    """[兼容] 旧版 spawn_agent 接口 — 散参数形式

    新代码请使用 spawn_agent(agent_input) 统一接口。
    """
    flag_error = _check_spawn_flag()
    if flag_error:
        return flag_error

    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    logger.info("sub_agent_spawning", sub_id=sub_id, parent=parent_agent, role=role, isolation=isolation)

    edge_id = _record_spawn_edge(edge_manager, parent_agent, sub_id, task)
    worktree_path = _create_worktree(isolation, sub_id)

    try:
        # 1. 构建子Agent的对话上下文
        messages = _build_spawn_messages(
            role,
            task,
            context,
            parent_agent,
            cache_safe_params,
            scratchpad_dir,
        )

        # 2. 通过ReAct循环执行
        # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
        try:
            from src.engine.llm.react_loop import react_loop
            from src.engine.llm.smart_router import get_smart_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        smart = get_smart_router()
        routing = smart.route(message=task, agent_role=role)

        tool_reg = _prepare_tool_registry(
            role,
            cache_safe_params,
            dynamic_tool_registry,
            mcp_servers,
            sub_id,
        )

        result = await react_loop(
            messages,
            tool_registry=tool_reg,
            max_turns=max_turns,
            agent_role=role,
            provider=routing.provider,
            model=routing.model,
            project_space_id=cache_safe_params.project_space_id if cache_safe_params else "",
            on_progress=on_progress,
            cancel_event=cancel_event,
            sandbox_root_path=worktree_path,  # P2-2.2: worktree隔离路径
        )

        # 3. 记录执行到DB
        _record_sub_execution(
            sub_id=sub_id,
            parent_agent=parent_agent,
            role=role,
            task=task,
            result=result,
        )

        # 4. 写入SharedContextPool(供后续Agent读取)
        _write_sub_context(sub_id, parent_agent, task, result)

        result["sub_agent_id"] = sub_id
        result["sub_agent_role"] = role
        logger.info("sub_agent_completed", sub_id=sub_id, success=result.get("success", True))
        return result

    except Exception as e:
        logger.warning("sub_agent_failed", sub_id=sub_id, error=str(e), exc_info=True)
        return {"success": False, "error": str(e), "sub_agent_id": sub_id}
    finally:
        _cleanup_spawn_resources(edge_manager, edge_id, worktree_path, sub_id)


# ── Phase 0.2: spawn_agent 主接口 — AgentInput/Output 统一接口 ──


async def spawn_agent(
    agent_input=None,
    *,
    mcp_servers: list[str] | None = None,
    edge_manager: SpawnEdgeManager | None = None,
    dynamic_tool_registry: DynamicToolRegistry | None = None,
    **kwargs,
) -> dict:
    """spawn_agent V3 统一接口 — 接受 AgentInput, 返回 AgentOutput 兼容 dict

    这是新的主接口。旧散参数形式见 spawn_agent_legacy()。
    """
    from src.engine.agent.models import AgentInput as AI

    # 向后兼容: 无agent_input 或 字符串 → legacy 路径
    if agent_input is None or isinstance(agent_input, str):
        return await spawn_agent_legacy(
            agent_input or kwargs.pop("parent_agent", "coordinator"),
            role=kwargs.pop("role", "leaf"),
            task=kwargs.pop("task", ""),
            context=kwargs.pop("context", None),
            max_turns=kwargs.pop("max_turns", 3),
            cache_safe_params=kwargs.pop("cache_safe_params", None),
            mcp_servers=mcp_servers,
            on_progress=kwargs.pop("on_progress", None),
            cancel_event=kwargs.pop("cancel_event", None),
            scratchpad_dir=kwargs.pop("scratchpad_dir", ""),
            isolation=kwargs.pop("isolation", "none"),  # P2-2.2
            edge_manager=edge_manager,  # Δ1
            dynamic_tool_registry=dynamic_tool_registry,  # Δ2
        )

    if isinstance(agent_input, dict):
        ai = AI(**agent_input)
    elif isinstance(agent_input, AI):
        ai = agent_input
    else:
        return await spawn_agent_legacy(
            str(agent_input),
            edge_manager=edge_manager,
            dynamic_tool_registry=dynamic_tool_registry,
            **kwargs,
        )

    # FW1: 如果直接传入 mcp_servers，覆盖 AgentInput 中的值
    if mcp_servers is not None:
        ai.mcp_servers = list(mcp_servers)

    # W1: 构建 CacheSafeParams + 传递 mcp_servers
    cache_params = CacheSafeParams.from_parent(
        parent_agent=ai.name or "coordinator",
        permission_level="write",
        project_space_id=ai.context.get("project_space_id", "") if ai.context else "",
    )
    if ai.blocked_tools:
        cache_params.allowed_tools = set(ai.blocked_tools)

    return await spawn_agent_legacy(
        parent_agent=ai.name or "coordinator",
        role=ai.role,
        task=ai.task,
        context=ai.context,
        max_turns=ai.max_turns,
        cache_safe_params=cache_params,
        mcp_servers=ai.mcp_servers or None,
        on_progress=ai.on_progress,  # P2-2.3: AgentInput携带优先
        cancel_event=ai.cancel_event,  # P2-2.3
        scratchpad_dir=kwargs.pop("scratchpad_dir", ""),
        isolation=ai.isolation,  # P2-2.2
        edge_manager=edge_manager,  # Δ1
        dynamic_tool_registry=dynamic_tool_registry,  # Δ2
    )


async def spawn_agent_v3(agent_input, *, edge_manager: SpawnEdgeManager | None = None) -> dict:
    """spawn_agent V3 统一接口 — 接受 AgentInput, 返回 AgentOutput 兼容 dict

    Args:
        agent_input: src.engine.agent.models.AgentInput 实例
        edge_manager: Δ1 spawn 关系追踪管理器（可选，依赖注入）

    Returns:
        AgentOutput 兼容 dict
    """
    from src.engine.agent.models import AgentInput as AI

    ai = (
        agent_input
        if isinstance(agent_input, AI)
        else AI(**agent_input)
        if isinstance(agent_input, dict)
        else agent_input
    )

    result = await spawn_agent(
        parent_agent=ai.name or "coordinator",
        role=ai.role,
        task=ai.task,
        context=ai.context,
        max_turns=ai.max_turns,
        mcp_servers=ai.mcp_servers or None,
        on_progress=ai.on_progress,  # P2-2.3: 进度回调
        cancel_event=ai.cancel_event,  # P2-2.3: 中断信号
        isolation=ai.isolation,  # P2-2.2
        edge_manager=edge_manager,  # Δ1
    )
    # 转换为 AgentOutput 兼容格式
    result.setdefault("status", "completed" if not ai.run_in_background else "async_launched")
    result.setdefault("output_file", "")
    result.setdefault("usage", {})
    return result
