
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""DynamicToolRegistry — Agent 线程级动态工具注册（Δ2）

职责:
  - register(): 注册动态工具到指定 Agent
  - get_tools(agent_id): 查询 Agent 的动态工具列表
  - unregister(id): 删除工具
  - merge_tools_for_agent(): 全局+动态合并，全局优先，保序去重

端点对齐:
  POST /api/v2/agents/{agent_id}/tools → register()
  GET /api/v2/agents/{agent_id}/tools → get_tools()
  spawn_agent → merge_tools_for_agent(global, dynamic)

设计:
  - 依赖注入 ConnectionManager
  - 合并用 list(dict.fromkeys(merged)) 保序去重
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.infra.database.connection import ConnectionManager

logger = structlog.get_logger(__name__)

__all__ = ["DynamicToolRegistry", "merge_tools_for_agent"]


class DynamicToolRegistry:
    """Agent 动态工具注册表

    用法:
        reg = DynamicToolRegistry(cm)
        tool_id = reg.register(agent_id="boss", tool_name="custom_search", config={"k": "v"})
        tools = reg.get_tools("boss")
        reg.unregister(tool_id)
    """

    def __init__(self, cm: ConnectionManager) -> None:
        self._cm = cm

    def register(self, *, agent_id: str, tool_name: str, config: dict[str, Any]) -> str:
        """注册动态工具

        Args:
            agent_id: 所属 Agent ID
            tool_name: 工具名
            config: 工具配置（JSON 序列化存储）

        Returns:
            tool_id (UUID)
        """
        tool_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        config_json = json.dumps(config, ensure_ascii=False)
        try:
            with self._cm.get_conn() as conn:
                conn.execute(
                    """INSERT INTO agent_dynamic_tools
                    (id, agent_id, tool_name, tool_config_json, registered_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (tool_id, agent_id, tool_name, config_json, now),
                )
            logger.info(
                "dynamic_tool_registered",
                tool_id=tool_id,
                agent_id=agent_id,
                tool_name=tool_name,
            )
        except Exception as e:
            logger.warning(
                "dynamic_tool_register_failed",
                tool_id=tool_id,
                agent_id=agent_id,
                tool_name=tool_name,
                error=str(e),
                exc_info=True,
            )
            raise
        return tool_id

    def get_tools(self, agent_id: str) -> list[dict[str, Any]]:
        """查询 Agent 的动态工具列表

        Returns:
            [{"tool_id": ..., "tool_name": ..., "config": ..., "registered_at": ...}]
        """
        try:
            with self._cm.get_conn() as conn:
                rows = conn.execute(
                    """SELECT id, agent_id, tool_name, tool_config_json, registered_at
                       FROM agent_dynamic_tools
                       WHERE agent_id = ?
                       ORDER BY registered_at ASC""",
                    (agent_id,),
                ).fetchall()
            return [
                {
                    "tool_id": r["id"],
                    "tool_name": r["tool_name"],
                    "config": json.loads(r["tool_config_json"]),
                    "registered_at": r["registered_at"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(
                "dynamic_tool_get_failed",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )
            raise

    def unregister(self, tool_id: str) -> bool:
        """删除工具

        Returns:
            True 表示删除了一行；False 表示 tool_id 不存在（幂等）
        """
        try:
            with self._cm.get_conn() as conn:
                cur = conn.execute(
                    "DELETE FROM agent_dynamic_tools WHERE id = ?",
                    (tool_id,),
                )
                deleted = cur.rowcount > 0
            if deleted:
                logger.info("dynamic_tool_unregistered", tool_id=tool_id)
            else:
                logger.debug("dynamic_tool_unregister_noop", tool_id=tool_id, reason="not_found")
            return deleted
        except Exception as e:
            logger.warning(
                "dynamic_tool_unregister_failed",
                tool_id=tool_id,
                error=str(e),
                exc_info=True,
            )
            raise


def merge_tools_for_agent(
    global_tools: list[str],
    dynamic_tools: list[dict[str, Any]],
) -> list[str]:
    """合并全局工具 + Agent 动态工具

    规则:
      1. 全局工具在前，保持原顺序
      2. 动态工具追加在后，保持注册顺序
      3. 同名工具去重（全局优先，动态同名跳过）

    Args:
        global_tools: 全局工具名列表（如 ["search", "write"]）
        dynamic_tools: 动态工具列表，每项含 "tool_name" 字段

    Returns:
        合并后的工具名列表（保序去重）

    Examples:
        >>> merge_tools_for_agent(["a", "b"], [{"tool_name": "b"}, {"tool_name": "c"}])
        ['a', 'b', 'c']
    """
    merged = list(global_tools)  # 副本，不修改原列表
    for dt in dynamic_tools:
        name = dt.get("tool_name")
        if name and name not in merged:
            merged.append(name)
    # dict.fromkeys 保序去重（双保险）
    return list(dict.fromkeys(merged))
