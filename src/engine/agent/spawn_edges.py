
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""SpawnEdgeManager — Agent 父子 spawn 关系管理（Δ1 线程关系图）

职责:
  - record(): 记录一次 spawn 关系（parent→child）
  - mark_joined(): 子 Agent 完成时标记 joined
  - get_children(): 查询直接子节点
  - get_descendants(): BFS 遍历全部后代（visited 防环）

端点对齐:
  POST /api/agents/{id}/spawn → spawn_agent() → record()
  GET /api/agents/{id}/descendants → get_descendants()

设计:
  - 依赖注入 ConnectionManager，不全局 import，保证可测试
  - 所有 DB 操作走 cm.get_conn() 上下文（自动 commit/rollback）
  - BFS 防环: visited set 避免环状 spawn 导致无限递归
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.infra.database.connection import ConnectionManager

logger = structlog.get_logger(__name__)

__all__ = ["SpawnEdgeManager"]


class SpawnEdgeManager:
    """Agent spawn 关系管理器

    用法:
        mgr = SpawnEdgeManager(cm)
        edge_id = mgr.record(parent_agent_id="boss", child_agent_id="sub_001", task_summary="优化SEO")
        #... 子 Agent 执行 ...
        mgr.mark_joined(edge_id)
        descendants = mgr.get_descendants("boss")
    """

    def __init__(self, cm: ConnectionManager) -> None:
        self._cm = cm

    def record(self, *, parent_agent_id: str, child_agent_id: str, task_summary: str = "") -> str:
        """记录一次 spawn 关系

        Returns:
            edge_id (UUID)
        """
        edge_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        try:
            with self._cm.get_conn() as conn:
                conn.execute(
                    """INSERT INTO agent_spawn_edges
                    (id, parent_agent_id, child_agent_id, status, spawned_at, joined_at, task_summary)
                    VALUES (?, ?, ?, 'running', ?, NULL, ?)""",
                    (edge_id, parent_agent_id, child_agent_id, now, task_summary),
                )
            logger.info(
                "spawn_edge_recorded",
                edge_id=edge_id,
                parent=parent_agent_id,
                child=child_agent_id,
            )
        except Exception as e:
            logger.warning(
                "spawn_edge_record_failed",
                edge_id=edge_id,
                parent=parent_agent_id,
                child=child_agent_id,
                error=str(e),
                exc_info=True,
            )
            raise
        return edge_id

    def mark_joined(self, edge_id: str) -> bool:
        """标记子 Agent 已完成（status=joined, joined_at=now）

        Returns:
            True 表示更新了一行；False 表示 edge_id 不存在（幂等不抛异常）
        """
        now = datetime.now(UTC).isoformat()
        try:
            with self._cm.get_conn() as conn:
                cur = conn.execute(
                    """UPDATE agent_spawn_edges
                       SET status = 'joined', joined_at = ?
                       WHERE id = ?""",
                    (now, edge_id),
                )
                updated = cur.rowcount > 0
            if updated:
                logger.info("spawn_edge_joined", edge_id=edge_id)
            else:
                logger.debug("spawn_edge_join_noop", edge_id=edge_id, reason="not_found")
            return updated
        except Exception as e:
            logger.warning(
                "spawn_edge_join_failed",
                edge_id=edge_id,
                error=str(e),
                exc_info=True,
            )
            raise

    def get_children(self, agent_id: str) -> list[dict[str, Any]]:
        """查询直接子节点列表"""
        try:
            with self._cm.get_conn() as conn:
                rows = conn.execute(
                    """SELECT id, parent_agent_id, child_agent_id, status, spawned_at, joined_at, task_summary
                       FROM agent_spawn_edges
                       WHERE parent_agent_id = ?
                       ORDER BY spawned_at ASC""",
                    (agent_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(
                "spawn_edge_get_children_failed",
                agent_id=agent_id,
                error=str(e),
                exc_info=True,
            )
            raise

    def get_descendants(self, agent_id: str) -> list[dict[str, Any]]:
        """BFS 遍历全部后代（visited 防环）

        起始 agent_id 自身不计入结果（仅其后代）。
        环状关系（A→B→C→A）不会无限递归：visited 集合阻止重复访问。
        """
        result: list[dict[str, Any]] = []
        visited: set[str] = {agent_id}  # 起点标记已访问，防止回环到自身
        queue: list[str] = [agent_id]

        while queue:
            current = queue.pop(0)
            try:
                children = self.get_children(current)
            except Exception as e:
                logger.warning(
                    "spawn_edge_descendants_step_failed",
                    current=current,
                    error=str(e),
                    exc_info=True,
                )
                # 单步失败不中断整体遍历，跳过该分支
                continue

            for child in children:
                child_id = child["child_agent_id"]
                if child_id in visited:
                    # 防环：已访问过的节点跳过
                    continue
                visited.add(child_id)
                result.append(child)
                queue.append(child_id)

        return result
