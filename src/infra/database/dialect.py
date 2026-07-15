
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""数据库方言适配 — 统一 SQLite/PostgreSQL 差异

提供 DDL/SQL 生成时的方言适配，避免在业务代码中硬编码数据库特定语法。
方言选择基于配置中的数据库 URL（sqlite:/// 或 postgresql://）。

DATA-009: 所有接受 table/index 标识符的方法首行调用 safe_table_name / validate_identifier,
防止 SQL 注入向量通过 f-string 拼接到 SQL 中。
"""

from __future__ import annotations

# DATA-009: 标识符安全校验 — 所有动态拼接到 SQL 的 table/index 必须先校验
from src.infra.database.sql_safe import safe_table_name, validate_identifier


class _BaseDialect:
    """方言基类 — 子类实现具体 SQL 生成"""

    backend: str
    is_sqlite: bool
    now_sql: str

    def table_exists_sql(self, table: str) -> str:
        """返回检查表是否存在的 SQL（结果首列非 None 表示存在）"""
        raise NotImplementedError

    def table_check_sql(self, table: str) -> str:
        """返回统计表是否存在的 SQL（结果首列 == 0 表示缺失）"""
        raise NotImplementedError

    def index_check_sql(self, index: str) -> str:
        """返回统计索引是否存在的 SQL（结果首列 == 0 表示缺失）"""
        raise NotImplementedError

    def column_check_sql(self, table: str, column: str) -> str:
        """返回查询列是否存在的 SQL"""
        raise NotImplementedError

    def adapt_ddl(self, ddl: str) -> str:
        """将 DDL 语句适配为当前方言可执行的语法"""
        return ddl


class _SQLiteDialect(_BaseDialect):
    """SQLite 方言"""

    backend = "sqlite"
    is_sqlite = True
    now_sql = "datetime('now')"

    def table_exists_sql(self, table: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        return f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"

    def table_check_sql(self, table: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        return f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'"

    def index_check_sql(self, index: str) -> str:
        validate_identifier(index)  # DATA-009: 防 SQL 注入, 校验 index 标识符
        return f"SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='{index}'"

    def column_check_sql(self, table: str, column: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        # PRAGMA 不接受参数化, column 仅在调用方使用, 这里只校验 table
        return f"PRAGMA table_info({table})"


class _PostgresDialect(_BaseDialect):
    """PostgreSQL 方言"""

    backend = "postgresql"
    is_sqlite = False
    now_sql = "NOW()"

    def table_exists_sql(self, table: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        return f"SELECT to_regclass('public.{table}')"

    def table_check_sql(self, table: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        return f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='{table}'"

    def index_check_sql(self, index: str) -> str:
        validate_identifier(index)  # DATA-009: 防 SQL 注入, 校验 index 标识符
        return f"SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname='{index}'"

    def column_check_sql(self, table: str, column: str) -> str:
        safe_table_name(table)  # DATA-009: 防 SQL 注入, 校验 table 标识符
        return (
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' AND column_name='{column}'"
        )


_dialect: _BaseDialect | None = None


def get_dialect() -> _BaseDialect:
    """获取当前数据库方言单例（基于配置的数据库 URL 自动选择）"""
    global _dialect
    if _dialect is None:
        from config import get_settings

        url = get_settings().db.url
        _dialect = _SQLiteDialect() if url.startswith(("sqlite:///", "sqlite+aiosqlite:///")) else _PostgresDialect()
    return _dialect


def reset_dialect() -> None:
    """重置方言单例（测试用）"""
    global _dialect
    _dialect = None
