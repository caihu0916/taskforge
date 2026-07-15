
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 登录日志模块 — 记录登录活动

功能:
  - 记录登录成功/失败
  - 记录IP地址和User-Agent
  - 支持查询登录历史
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import sqlite3

logger = structlog.get_logger(__name__)

# ── DDL ────────────────────────────────────────────────────────

LOGIN_LOG_DDL = """
CREATE TABLE IF NOT EXISTS login_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT,
    email       TEXT,
    action      TEXT NOT NULL CHECK(action IN ('login_success', 'login_failure', 'logout', 'password_change')),
    ip_address  TEXT DEFAULT '',
    user_agent  TEXT DEFAULT '',
    details     TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_login_logs_user_id ON login_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_login_logs_email ON login_logs(email);
CREATE INDEX IF NOT EXISTS idx_login_logs_action ON login_logs(action);
CREATE INDEX IF NOT EXISTS idx_login_logs_created_at ON login_logs(created_at);
"""


class LoginLogger:
    """登录日志管理器"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保表存在"""
        try:
            self._conn.executescript(LOGIN_LOG_DDL)
        except Exception as e:
            logger.warning("login_log_table_error", error=str(e))

    def log_login_success(
        self,
        user_id: str,
        email: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        """记录登录成功"""
        self._log("login_success", user_id, email, ip_address, user_agent)

    def log_login_failure(
        self,
        email: str,
        ip_address: str = "",
        user_agent: str = "",
        reason: str = "",
    ) -> None:
        """记录登录失败"""
        self._log("login_failure", None, email, ip_address, user_agent, reason)

    def log_logout(
        self,
        user_id: str,
        email: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        """记录登出"""
        self._log("logout", user_id, email, ip_address, user_agent)

    def log_password_change(
        self,
        user_id: str,
        email: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        """记录密码修改"""
        self._log("password_change", user_id, email, ip_address, user_agent)

    def _log(
        self,
        action: str,
        user_id: str | None,
        email: str,
        ip_address: str,
        user_agent: str,
        details: str = "",
    ) -> None:
        """记录日志"""
        try:
            self._conn.execute(
                """INSERT INTO login_logs (user_id, email, action, ip_address, user_agent, details)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, email, action, ip_address, user_agent, details),
            )
            self._conn.commit()

            logger.info(
                "login_activity_logged",
                action=action,
                user_id=user_id,
                email=email,
                ip_address=ip_address,
            )
        except Exception as e:
            logger.error("login_log_error", error=str(e))

    def get_user_login_history(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取用户登录历史"""
        cursor = self._conn.execute(
            """SELECT id, action, ip_address, user_agent, created_at
               FROM login_logs
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        )
        return [
            {
                "id": row[0],
                "action": row[1],
                "ip_address": row[2],
                "user_agent": row[3],
                "created_at": row[4],
            }
            for row in cursor.fetchall()
        ]

    def get_recent_failures(
        self,
        email: str,
        minutes: int = 60,
    ) -> list[dict[str, Any]]:
        """获取最近的登录失败记录"""
        cursor = self._conn.execute(
            """SELECT id, ip_address, user_agent, created_at
               FROM login_logs
               WHERE email = ? AND action = 'login_failure'
               AND created_at > datetime('now', ? || ' minutes')
               ORDER BY created_at DESC""",
            (email, f"-{minutes}"),
        )
        return [
            {
                "id": row[0],
                "ip_address": row[1],
                "user_agent": row[2],
                "created_at": row[3],
            }
            for row in cursor.fetchall()
        ]

    def get_login_stats(self) -> dict[str, Any]:
        """获取登录统计"""
        cursor = self._conn.execute(
            """SELECT action, COUNT(*) as count
               FROM login_logs
               WHERE created_at > datetime('now', '-24 hours')
               GROUP BY action"""
        )
        stats = {row[0]: row[1] for row in cursor.fetchall()}

        cursor = self._conn.execute(
            """SELECT COUNT(DISTINCT user_id) as unique_users
               FROM login_logs
               WHERE action = 'login_success'
               AND created_at > datetime('now', '-24 hours')"""
        )
        stats["unique_users_24h"] = cursor.fetchone()[0]

        return stats


# ── 全局实例 ──

_login_logger: LoginLogger | None = None


def get_login_logger(conn: sqlite3.Connection | None = None) -> LoginLogger:
    """获取登录日志管理器"""
    global _login_logger
    if _login_logger is None:
        if conn is None:
            from src.infra.database.connection import get_connection_manager

            cm = get_connection_manager()
            conn = cm.get_conn().__enter__()
        _login_logger = LoginLogger(conn)
    return _login_logger
