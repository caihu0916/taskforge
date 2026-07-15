
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Workflow API 幂等性存储 — workflow_idempotency_keys 表

存储结构:
  key            TEXT PRIMARY KEY    — x-idempotency-key Header 值（复合键 endpoint::key）
  workflow_id    TEXT                — 关联的工作流 ID（可为空）
  endpoint       TEXT                — 端点标识，如 "POST /api/v1/workflows"
  response_json  TEXT                — JSON 序列化的响应内容
  status         TEXT                — pending / completed（Minor-2: 并发保护）
  created_at     TEXT                — 创建时间 ISO 格式
  expires_at     TEXT                — 过期时间 ISO 格式（默认 24 小时）

使用约定:
  1. key + endpoint 组合唯一，因此存储时采用 composite 主键策略
     实际实现: endpoint::key 作为复合主键字符串
  2. 调用方需先调用 ensure_table() 再使用查询方法（tests 中手动 DDL）
  3. Minor-2: 并发保护 — 先写入 pending 状态，执行完再更新为 completed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.infra.database.connection import get_connection_manager

DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 24 小时

CREATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS workflow_idempotency_keys (
    key TEXT PRIMARY KEY,
    workflow_id TEXT,
    endpoint TEXT,
    response_json TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    expires_at TEXT
)
"""


def _compose_key(key: str, endpoint: str) -> str:
    """将 endpoint 与用户提供的 key 组合，避免跨端点共享"""
    return f"{endpoint}::{key}"


def ensure_table() -> None:
    """确保 workflow_idempotency_keys 表存在

    幂等 — 多次调用安全。使用 SQLite 的 `CREATE TABLE IF NOT EXISTS`。"""
    cm = get_connection_manager()
    with cm.get_conn() as conn:
        conn.execute(CREATE_TABLE_DDL)
        conn.commit()


def lookup(key: str, endpoint: str) -> dict[str, Any] | None:
    """查询缓存的响应。若 key 不存在、已过期或状态为 pending 返回 None

    Minor-2: 并发保护 — pending 状态的记录不返回（表示有其他请求正在执行）

    Returns:
        成功时返回解析后的 JSON 响应字典
        不存在、已过期或 pending 返回 None
    """
    composed = _compose_key(key, endpoint)
    cm = get_connection_manager()
    with cm.get_conn() as conn:
        row = conn.execute(
            "SELECT response_json, expires_at, status FROM workflow_idempotency_keys WHERE key = ?",
            (composed,),
        ).fetchone()
    if row is None:
        return None
    response_json, expires_at, status = row[0], row[1], row[2] if len(row) > 2 else "completed"
    # Minor-2: pending 状态不返回（有其他请求正在执行）
    if status == "pending":
        return None
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp < datetime.now(UTC):
                return None
        except (ValueError, TypeError):
            pass
    if response_json:
        try:
            return json.loads(response_json)
        except json.JSONDecodeError:
            return None
    return None


def acquire(key: str, endpoint: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """Minor-2: 尝试获取幂等键的执行权（写入 pending 状态）

    Returns:
        True: 成功获取执行权（可继续执行业务）
        False: 键已存在（completed 或 pending），不应执行
    """
    composed = _compose_key(key, endpoint)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    cm = get_connection_manager()
    with cm.get_conn() as conn:
        # 先检查是否已存在任何记录（completed 或 pending）
        existing = conn.execute(
            "SELECT status FROM workflow_idempotency_keys WHERE key = ?",
            (composed,),
        ).fetchone()
        if existing is not None:
            return False  # 已有记录（completed 或 pending），不应执行
        # 写入 pending 状态（仅当不存在时）
        conn.execute(
            """
            INSERT INTO workflow_idempotency_keys
                (key, endpoint, status, created_at, expires_at)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            (composed, endpoint, now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    return True


def store(
    key: str,
    endpoint: str,
    response: dict[str, Any],
    workflow_id: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """将响应写入幂等缓存（更新为 completed 状态）

    若 key 已存在，则覆盖（INSERT OR REPLACE）。
    """
    composed = _compose_key(key, endpoint)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    cm = get_connection_manager()
    with cm.get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO workflow_idempotency_keys
                (key, workflow_id, endpoint, response_json, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, 'completed', ?, ?)
            """,
            (
                composed,
                workflow_id,
                endpoint,
                json.dumps(response, ensure_ascii=False),
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()


def purge_expired() -> int:
    """清理所有已过期的记录，返回清理数量"""
    cm = get_connection_manager()
    now = datetime.now(UTC).isoformat()
    with cm.get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM workflow_idempotency_keys WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        conn.commit()
        return cursor.rowcount or 0


def delete(key: str, endpoint: str) -> None:
    """删除指定 key（用于测试/调试）"""
    composed = _compose_key(key, endpoint)
    cm = get_connection_manager()
    with cm.get_conn() as conn:
        conn.execute("DELETE FROM workflow_idempotency_keys WHERE key = ?", (composed,))
        conn.commit()
