
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge SQL 安全校验 — 防 SQL 注入的表名/列名校验工具

SEC-05: 所有 f-string SQL 拼接必须经过该校验，确保动态部分不含注入向量。
"""

from __future__ import annotations

import re

from src.exceptions import ValidationError

# 表名/列名合法模式: 仅允许 字母/数字/下划线，必须以字母开头
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

# 危险 SQL 关键词黑名单（防信息泄露/破坏）
_SQL_KEYWORDS_BLACKLIST = frozenset(
    {
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "INSERT",
        "UPDATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "UNION",
        "SELECT",
        "INFORMATION_SCHEMA",
    }
)


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """校验 SQL 标识符（表名/列名），返回原值或抛出 ValidationError

    Args:
        name: 待校验的标识符
        kind: 标识符类型描述（用于错误消息）

    Raises:
        ValidationError: 标识符不合法
    """
    if not name:
        raise ValidationError(f"Empty {kind}", code="SQL_EMPTY_IDENTIFIER")
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValidationError(
            f"Invalid {kind}: '{name}' — only [a-zA-Z0-9_] allowed, must start with a letter",
            code="SQL_INVALID_IDENTIFIER",
        )
    upper = name.upper()
    if upper in _SQL_KEYWORDS_BLACKLIST:
        raise ValidationError(f"Dangerous {kind}: '{name}' matches SQL keyword blacklist", code="SQL_DANGEROUS_KEYWORD")
    return name


def validate_where_clause(where: str) -> str:
    """校验动态 WHERE 子句，阻止危险关键词注入

    DATA-010: **本函数仅用于校验参数化片段（列名/操作符/占位符结构），禁止传入含用户值的字符串。**

    正确用法:
        # 用占位符 (?) 传递用户值, where 仅含列名/操作符/占位符
        where = "id = ? AND status = ?"
        validate_where_clause(where)
        cursor.execute(f"SELECT * FROM t WHERE {where}", (user_id, user_status))

    错误用法 (禁止):
        # 把用户值拼接到 where 字符串中 — 即使通过本校验也会导致 SQL 注入
        where = f"id = {user_input}"               # ❌ 禁止: 含用户值
        where = f"name = '{user_name}'"            # ❌ 禁止: 含用户值
        validate_where_clause(where)

    设计说明:
        - 本函数采用黑名单策略（阻止 ; -- /* */ UNION DROP DELETE 等），是纵深防御的一环
        - 黑名单无法穷尽所有注入向量，因此**调用方必须用占位符 (?) 传递用户值**
        - 用户值应通过 params 元组传给 cursor.execute(sql, params)，绝不拼接到 where 字符串

    仅允许: 列名 = 值 / AND / OR / IN / NOT / IS / NULL / LIKE / BETWEEN / ORDER BY / LIMIT / OFFSET
    阻止: ; -- /* */ UNION DROP DELETE 等
    """
    upper = where.upper()
    for danger in (
        ";",
        "--",
        "/*",
        "*/",
        "UNION",
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "INSERT",
        "UPDATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "INFORMATION_SCHEMA",
        "PG_",
    ):
        if danger in upper:
            raise ValidationError(f"Dangerous pattern in WHERE clause: '{danger}'", code="SQL_DANGEROUS_WHERE")
    return where


def safe_table_name(table: str) -> str:
    """校验并返回安全的表名（用于 f-string 拼接）"""
    return validate_identifier(table, kind="table name")


def safe_column_name(col: str) -> str:
    """校验并返回安全的列名（用于 f-string 拼接）"""
    return validate_identifier(col, kind="column name")
