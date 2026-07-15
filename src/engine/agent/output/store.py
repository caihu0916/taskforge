
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""交付物持久化 — DB记录 + 文件管理"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import structlog

from src.infra.database.sql_safe import safe_table_name, validate_where_clause

logger = structlog.get_logger(__name__)

_DELIVERABLES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    task_summary TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT 'md',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    chat_id TEXT,
    created_at TEXT NOT NULL
);
"""

_DELIVERABLES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_deliverables_agent ON deliverables(agent_name);
CREATE INDEX IF NOT EXISTS idx_deliverables_type ON deliverables(file_type);
CREATE INDEX IF NOT EXISTS idx_deliverables_created ON deliverables(created_at);
CREATE INDEX IF NOT EXISTS idx_deliverables_chat ON deliverables(chat_id);
"""


def ensure_deliverables_table(cm: Any) -> None:
    """Safety-net: 检查交付物表是否存在，缺失则 warning

    Alembic 现在是唯一的 schema 管理者 (20260615_consolidation)。
    """
    with cm.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deliverables'").fetchone()
        if row[0] == 0:
            logger.warning("safety_net_missing_deliverables", hint="Run: alembic upgrade head")
        else:
            logger.info("safety_net_deliverables_ok")


def save_deliverable(
    cm: Any,
    deliverable_id: str,
    agent_name: str,
    task_summary: str,
    file_path: str,
    file_name: str,
    file_type: str,
    size_bytes: int,
    title: str,
    chat_id: str | None = None,
) -> None:
    """保存交付物记录到DB"""
    with cm.get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO deliverables 
               (id, agent_name, task_summary, file_path, file_name, file_type, 
                size_bytes, title, chat_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                deliverable_id,
                agent_name,
                task_summary,
                file_path,
                file_name,
                file_type,
                size_bytes,
                title,
                chat_id,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    logger.info("deliverable_saved", id=deliverable_id, type=file_type, file=file_name)


def list_deliverables(
    cm: Any,
    agent_name: str | None = None,
    file_type: str | None = None,
    chat_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """查询交付物列表，返回 (items, total)"""
    with cm.get_conn() as conn:
        where_parts = []
        params: list[Any] = []
        if agent_name:
            where_parts.append("agent_name = ?")
            params.append(agent_name)
        if file_type:
            where_parts.append("file_type = ?")
            params.append(file_type)
        if chat_id:
            where_parts.append("chat_id = ?")
            params.append(chat_id)

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        where = validate_where_clause(where) if where else ""

        # 总数
        total = conn.execute(f"SELECT COUNT(*) FROM {safe_table_name('deliverables')} {where}", params).fetchone()[0]

        rows = conn.execute(
            f"SELECT id, agent_name, task_summary, file_name, file_type, size_bytes, title, chat_id, created_at FROM {safe_table_name('deliverables')} {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "agent_name": row["agent_name"],
                    "task_summary": row["task_summary"],
                    "file_name": row["file_name"],
                    "file_type": row["file_type"],
                    "size_bytes": row["size_bytes"],
                    "title": row["title"],
                    "chat_id": row["chat_id"],
                    "created_at": row["created_at"],
                }
            )
        return results, total


def get_deliverable(cm: Any, deliverable_id: str) -> dict | None:
    """获取单个交付物"""
    with cm.get_conn() as conn:
        row = conn.execute(
            "SELECT id, agent_name, task_summary, file_path, file_name, file_type, size_bytes, title, chat_id, created_at FROM deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "agent_name": row["agent_name"],
            "task_summary": row["task_summary"],
            "file_path": row["file_path"],
            "file_name": row["file_name"],
            "file_type": row["file_type"],
            "size_bytes": row["size_bytes"],
            "title": row["title"],
            "chat_id": row["chat_id"],
            "created_at": row["created_at"],
        }


def delete_deliverable(cm: Any, deliverable_id: str) -> bool:
    """删除交付物记录+文件+空目录"""
    d = get_deliverable(cm, deliverable_id)
    if not d:
        return False
    file_path = d["file_path"]
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            # 清理空目录
            parent = os.path.dirname(file_path)
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            logger.warning("deliverable_file_delete_failed", path=file_path)
    with cm.get_conn() as conn:
        conn.execute("DELETE FROM deliverables WHERE id = ?", (deliverable_id,))
        conn.commit()
    logger.info("deliverable_deleted", id=deliverable_id)
    return True
