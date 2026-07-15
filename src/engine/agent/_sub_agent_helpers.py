
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""子Agent辅助函数 — 消息构建 / 执行记录 / 上下文写回

从 sub_agent.py 拆分出的模块，包含:
  - _build_sub_messages: 构建子Agent对话消息(基础版)
  - _build_sub_messages_inherited: 继承父代理上下文版
  - _create_restricted_registry: 权限冒泡受限注册表
  - _record_sub_execution: 记录子Agent执行到DB
  - _write_sub_context: 写入SharedContextPool + 通知父Agent
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.engine.agent._cache_safe_params import CacheSafeParams

logger = structlog.get_logger(__name__)


def _build_sub_messages(
    role: str,
    task: str,
    context: dict | None,
    parent_agent: str,
    scratchpad_dir: str = "",  # W6
) -> list[dict]:
    """构建子Agent的对话消息"""
    scratchpad_hint = f"\n共享Scratchpad目录: {scratchpad_dir} (可读写共享文件)" if scratchpad_dir else ""
    messages = [
        {
            "role": "system",
            "content": (
                f"你是{role}角色的子Agent，由{parent_agent}生成。"
                f"专注完成以下任务，精简高效。完成后直接输出结果。"
                f"{scratchpad_hint}"
            ),
        }
    ]

    # 注入父Agent上下文
    if context:
        ctx_str = json.dumps(context, ensure_ascii=False)[:500]
        messages.append(
            {
                "role": "user",
                "content": f"上下文数据:\n{ctx_str}",
            }
        )

    messages.append({"role": "user", "content": task})
    return messages


def _build_sub_messages_inherited(
    role: str,
    task: str,
    context: dict | None,
    parent_agent: str,
    params: CacheSafeParams,
    scratchpad_dir: str = "",  # W6
) -> list[dict]:
    """P1-2: 构建子Agent的对话消息 — 继承父代理上下文

    与 _build_sub_messages 的区别:
    1. 继承父代理的对话历史(只读，截断到20条)
    2. 注入工具结果摘要
    3. 添加权限边界提示
    """
    # 继承父代理消息
    inherited = params.get_inherited_messages(max_messages=20)

    scratchpad_hint = f"\n共享Scratchpad目录: {scratchpad_dir} (可读写共享文件)" if scratchpad_dir else ""
    # 替换 system 消息
    system_msg = {
        "role": "system",
        "content": (
            f"你是{role}角色的子Agent，由{parent_agent}生成。"
            f"专注完成以下任务，精简高效。完成后直接输出结果。"
            f"{scratchpad_hint}"
        ),
    }

    # 保留非 system 的继承消息
    non_system = [m for m in inherited if m.get("role") != "system"]

    messages = [system_msg]

    # 注入工具结果摘要
    if params.tool_results_snapshot:
        results_summary = json.dumps(params.tool_results_snapshot, ensure_ascii=False)[:500]
        messages.append(
            {
                "role": "system",
                "content": f"[父代理工具结果摘要]\n{results_summary}",
            }
        )

    # 添加继承的对话历史
    messages.extend(non_system)

    # 注入额外上下文
    if context:
        ctx_str = json.dumps(context, ensure_ascii=False)[:500]
        messages.append(
            {
                "role": "user",
                "content": f"上下文数据:\n{ctx_str}",
            }
        )

    # 当前任务
    messages.append({"role": "user", "content": task})

    return messages


def _create_restricted_registry(
    parent_registry: Any,
    params: CacheSafeParams,
) -> Any:
    """P1-2: 创建受限的工具注册表 — 权限冒泡

    子代理只能使用父代理允许的工具子集
    """
    from src.engine.tool.registry import ToolRegistry

    restricted = ToolRegistry()
    for tool in parent_registry.list_tools(enabled_only=True):
        if params.is_tool_allowed(tool.name):
            with contextlib.suppress(ValueError):
                restricted.register(tool)
    return restricted


def _create_restricted_registry_from_names(
    parent_registry: Any,
    tool_names: list[str],
) -> Any:
    """Δ2: 按工具名列表创建受限注册表 — 动态工具合并后重建

    仅保留 tool_names 中存在的工具（保序），用于全局+动态合并后的工具集重建。
    """
    from src.engine.tool.registry import ToolRegistry

    restricted = ToolRegistry()
    name_set = set(tool_names)
    for tool in parent_registry.list_tools(enabled_only=True):
        if tool.name in name_set:
            with contextlib.suppress(ValueError):
                restricted.register(tool)
    return restricted


def _record_sub_execution(
    sub_id: str,
    parent_agent: str,
    role: str,
    task: str,
    result: dict,
) -> None:
    """记录子Agent执行到DB — 使用 record_execution 统一模式"""
    try:
        from src.engine.agent.exec_helpers import record_execution
        from src.infra.database.connection import get_connection_manager

        cm = get_connection_manager()
        status = "completed" if result.get("success") else "failed"
        record_execution(
            cm,
            agent_name=f"{parent_agent}/sub/{role}",
            category="sub_agent",
            exec_id=sub_id,
            status=status,
            result=json.dumps(result, ensure_ascii=False)[:4000],
        )
    except Exception as e:
        logger.error("sub_execution_record_failed", sub_id=sub_id, error=str(e), exc_info=True)


def _write_sub_context(sub_id: str, parent_agent: str, task: str, result: dict) -> None:
    """将子Agent结果写入SharedContextPool + 通知父Agent"""
    try:
        from src.engine.context.shared_pool import get_shared_context_pool
        from src.infra.async_task_tracker import spawn_task

        pool = get_shared_context_pool()
        content = result.get("content", "")[:300]
        spawn_task(
            pool.write(
                agent_name=f"sub_{parent_agent}",
                key=sub_id,
                content=content or json.dumps(result, ensure_ascii=False)[:300],
                priority=3,
                intent_tags=[task[:30], parent_agent],
            ),
            name="sub_agent_write_context",
        )
    except Exception as e:
        logger.warning("sub_context_write_failed", sub_id=sub_id, error=str(e), exc_info=True)

    # T2: 异步通知父Agent子任务完成
    try:
        from src.infra.async_utils import run_async

        async def _notify_parent() -> None:
            try:
                from src.engine.agent.message_router import get_message_router

                router = get_message_router()
                success = result.get("success", False)
                await router.send(
                    sender_id=f"sub_{sub_id}",
                    target_agent=parent_agent,
                    content=f"子Agent[{sub_id}] 任务完成: {task[:100]} — {'成功' if success else '失败'}",
                    metadata={
                        "sub_agent_id": sub_id,
                        "task": task[:200],
                        "success": success,
                        "type": "sub_agent_completion",
                    },
                )
            except Exception as exc:
                logger.debug("sub_notify_parent_failed", sub_id=sub_id, error=str(exc))

        run_async(_notify_parent(), timeout=5)
    except Exception as e:
        logger.debug("sub_notify_parent_skip", sub_id=sub_id, error=str(e))
