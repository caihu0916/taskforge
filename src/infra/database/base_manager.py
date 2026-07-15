
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge BaseManager — 通用 CRUD 基类

消除 TaskManager/MemoryStore/InvoiceManager 之间的重复 CRUD 代码。
子类声明 WHAT (表名/模型/列)，基类处理 HOW (SQL/序列化)。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

import structlog
from pydantic import BaseModel

from src.exceptions import DatabaseError

if TYPE_CHECKING:
    from src.infra.database.connection import ConnectionManager

logger = structlog.get_logger(__name__)

M = TypeVar("M", bound=BaseModel)


class BaseManager:
    """SQLite CRUD 基类。

    子类必须定义:
        table_name: str           — e.g. "tasks"
        model_class: type         — e.g. Task
        ddl: str                  — CREATE TABLE IF NOT EXISTS ...
        columns: list[str]        — 有序列名 (对应 INSERT 占位符顺序)

    可选覆盖:
        json_columns: set[str]    — 需要 json.dumps/loads 的列
        enum_columns: dict[str, type]  — 需要 Enum() 包装的列
        datetime_columns: set[str]     — 需要 isoformat/fromisoformat 的列
        filter_column: str        — count() 的过滤列，默认 "status"
        create_return_id: bool    — True 则 create() 返回 str id
        insert_suffix: str        — e.g. "OR REPLACE"
        column_alias: dict[str, str]  — 列名到模型字段名的映射
    """

    table_name: ClassVar[str] = ""
    model_class: ClassVar[type] = object
    ddl: ClassVar[str] = ""
    columns: ClassVar[list[str]] = []
    json_columns: ClassVar[set[str]] = set()
    enum_columns: ClassVar[dict[str, type]] = {}
    datetime_columns: ClassVar[set[str]] = {"created_at", "updated_at"}
    filter_column: ClassVar[str] = "status"
    create_return_id: ClassVar[bool] = False
    insert_suffix: ClassVar[str] = ""
    column_alias: ClassVar[dict[str, str]] = {}
    default_json_values: ClassVar[dict[str, Any]] = {}
    """JSON 列的空值默认值 — {列名: 默认}，如 {"metadata": {}, "tags": []}

    替代旧的 "metadata" in col 启发式判断。
    未在此声明的列默认返回 {}。
    """

    def __init__(self, cm: ConnectionManager, *, scenario_id: str | None = None) -> None:
        self._cm = cm
        self._scenario_id = scenario_id
        self._initialized = False

    def _safe_table(self) -> str:
        """C3: 返回验证后的安全表名"""
        from src.infra.database.sql_safe import validate_identifier

        return validate_identifier(self.table_name, "table")

    def _safe_filter_column(self) -> str:
        """C3: 返回验证后的安全过滤列名"""
        from src.infra.database.sql_safe import validate_identifier

        return validate_identifier(self.filter_column, "column")

    def _where_scenario(self, sql: str, params: list | None = None) -> tuple[str, list]:
        """如果设置了 scenario_id，追加 WHERE scenario_id = ? 条件"""
        if self._scenario_id is not None:
            if "WHERE" in sql.upper():
                sql += " AND scenario_id = ?"
            else:
                sql += " WHERE scenario_id = ?"
            if params is None:
                params = [self._scenario_id]
            else:
                params.append(self._scenario_id)
        return sql, params or []

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._cm.get_conn() as conn:
            conn.executescript(self.ddl)
            self._auto_add_missing_columns(conn)
            conn.commit()
        self._initialized = True
        logger.info("manager_initialized", table=self.table_name)

    def _auto_add_missing_columns(self, conn: Any) -> None:
        """自愈：检测 DDL 声明的列是否存在于实际表中，缺失则 ALTER TABLE ADD COLUMN"""
        if not self.columns:
            return
        try:
            cursor = conn.execute(f"PRAGMA table_info({self._safe_table()})")
            existing = {row[1] for row in cursor.fetchall()}
            ddl_defaults = self._parse_ddl_column_defaults()
            for col in self.columns:
                if col not in existing:
                    default = ddl_defaults.get(col, "''")
                    col_type = ddl_defaults.get(f"__type__{col}", "TEXT")
                    conn.execute(f"ALTER TABLE {self._safe_table()} ADD COLUMN {col} {col_type} DEFAULT {default}")
                    logger.warning("auto_add_missing_column", table=self.table_name, column=col)
        except Exception:
            logger.warning("auto_add_missing_columns_failed", table=self.table_name, exc_info=True)

    def _parse_ddl_column_defaults(self) -> dict[str, str]:
        """从 DDL 文本解析列类型和默认值，用于 ALTER TABLE ADD COLUMN"""
        import re

        result: dict[str, str] = {}
        for raw_line in self.ddl.split("\n"):
            line = raw_line.strip().rstrip(",")
            m = re.match(
                r"(\w+)\s+(TEXT|INTEGER|REAL|BLOB|NUMERIC)\s*(?:NOT NULL\s*)?(?:DEFAULT\s+(.+?))?$", line, re.IGNORECASE
            )
            if m:
                col_name, col_type, default_val = m.group(1), m.group(2), m.group(3)
                result[f"__type__{col_name}"] = col_type.upper()
                if default_val is not None:
                    result[col_name] = default_val.strip()
        return result

    def create(self, item: M) -> M | str:
        # 自动设置 scenario_id
        if self._scenario_id is not None and hasattr(item, "scenario_id"):
            item.scenario_id = self._scenario_id  # type: ignore[assignment]
        values = self._model_to_values(item)
        placeholders = ", ".join("?" for _ in self.columns)
        col_list = ", ".join(self.columns)
        suffix = f" {self.insert_suffix}" if self.insert_suffix else ""
        sql = f"INSERT{suffix} INTO {self._safe_table()} ({col_list}) VALUES ({placeholders})"
        with self._cm.get_conn() as conn:
            conn.execute(sql, values)
            conn.commit()
        item_id = getattr(item, "id", "")
        logger.info("item_created", table=self.table_name, id=item_id)
        return item_id if self.create_return_id else item

    def _safe_columns(self, columns: list[str] | None = None) -> str:
        """校验列名白名单并返回安全的 SELECT 列字符串"""
        if columns is None:
            return "*"
        invalid = [c for c in columns if c not in self.columns]
        if invalid:
            raise DatabaseError(f"非法SELECT列: {invalid}")
        return ", ".join(columns)

    def get(self, item_id: str, *, columns: list[str] | None = None) -> M | None:
        col_str = self._safe_columns(columns)
        sql, params = self._where_scenario("WHERE id = ?", [item_id])
        sql = f"SELECT {col_str} FROM {self._safe_table()} {sql}"
        with self._cm.get_conn() as conn:
            row = conn.execute(sql, params).fetchone()
            return self._row_to_model(row) if row else None

    def delete(self, item_id: str) -> bool:
        sql, params = self._where_scenario("WHERE id = ?", [item_id])
        with self._cm.get_conn() as conn:
            cursor = conn.execute(f"DELETE FROM {self._safe_table()} {sql}", params)
            conn.commit()
            return cursor.rowcount > 0

    def count(self, filter_value: Any = None) -> int:
        with self._cm.get_conn() as conn:
            if filter_value is not None:
                sql = f"SELECT COUNT(*) FROM {self._safe_table()} WHERE {self._safe_filter_column()} = ?"
                sql, params = self._where_scenario(sql, [filter_value])
                row = conn.execute(sql, params).fetchone()
            else:
                sql = f"SELECT COUNT(*) FROM {self._safe_table()} WHERE 1=1"
                sql, params = self._where_scenario(sql)
                row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

    # 合法排序方向白名单
    _ALLOWED_ORDER_DIRECTIONS = {"ASC", "DESC"}

    def update_fields(self, item_id: str, *, return_updated: bool = True, **fields: Any) -> M | None:
        if not fields:
            return self.get(item_id) if return_updated else None
        sets: list[str] = []
        params: list[Any] = []
        for col, val in fields.items():
            # 列名白名单校验 — 防止SQL注入 (提前校验)
            if col not in self.columns:
                raise DatabaseError(f"无效列名: {col}")
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if not sets:
            return self.get(item_id) if return_updated else None
        # 仅当表有 updated_at 列时才追加（部分旧表可能不含此列）
        if "updated_at" in self.columns:
            sets.append("updated_at = ?")
            params.append(datetime.now(UTC).isoformat())
        params.append(item_id)
        sql = f"UPDATE {self._safe_table()} SET {', '.join(sets)} WHERE id = ?"
        sql, params = self._where_scenario(sql, params)
        with self._cm.get_conn() as conn:
            conn.execute(sql, params)
            conn.commit()
        return self.get(item_id) if return_updated else None

    def update_status(
        self,
        item_id: str,
        new_status: Any,
        *,
        return_updated: bool = True,
        expected_old_status: Any = None,
        **extra_fields: Any,
    ) -> M | None:
        # ── TOCTOU-safe 路径: 用 SQL WHERE 条件原子检测旧状态 ──
        if expected_old_status is not None:
            return self._atomic_status_update(
                item_id,
                new_status,
                expected_old_status=expected_old_status,
                return_updated=return_updated,
                **extra_fields,
            )

        # ── 常规路径: 先查再改 (保持向后兼容) ──
        item = self.get(item_id)
        if item is None:
            return None
        if hasattr(item, "can_transition_to") and not item.can_transition_to(new_status):
            raise DatabaseError(f"Cannot transition from {item.status} to {new_status}")
        now = datetime.now(UTC).isoformat()
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [new_status, now]
        for col, val in extra_fields.items():
            # 列名白名单校验 — 防止SQL注入
            if col not in self.columns:
                raise DatabaseError(f"无效列名: {col}")
            sets.append(f"{col} = ?")
            params.append(val)
        params.append(item_id)
        sql = f"UPDATE {self._safe_table()} SET {', '.join(sets)} WHERE id = ?"
        sql, params = self._where_scenario(sql, params)
        with self._cm.get_conn() as conn:
            conn.execute(sql, params)
            conn.commit()
        logger.info("status_updated", table=self.table_name, id=item_id, new=str(new_status))
        return self.get(item_id) if return_updated else None

    def _atomic_status_update(
        self,
        item_id: str,
        new_status: Any,
        *,
        expected_old_status: Any,
        return_updated: bool = True,
        **extra_fields: Any,
    ) -> M | None:
        """TOCTOU-safe 状态更新: WHERE id=? AND status=? 原子检测竞态。"""
        from src.exceptions import TaskConcurrentUpdate

        now = datetime.now(UTC).isoformat()
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [new_status, now]
        for col, val in extra_fields.items():
            if col not in self.columns:
                raise DatabaseError(f"无效列名: {col}")
            sets.append(f"{col} = ?")
            params.append(val)
        # WHERE id = ? AND status = expected_old_status
        # 注意: WHERE 参数必须在 SET 参数之后
        params.extend([item_id, expected_old_status])
        sql = f"UPDATE {self._safe_table()} SET {', '.join(sets)} WHERE id = ? AND status = ?"
        sql, params = self._where_scenario(sql, params)
        with self._cm.get_conn() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            if cursor.rowcount == 0:
                # 竞态: 旧状态已不匹配，被其他调度器/进程抢占
                raise TaskConcurrentUpdate(
                    f"任务 {item_id} 并发冲突: 预期状态 {expected_old_status} 已不匹配",
                    details={"item_id": item_id, "expected_old": str(expected_old_status), "new": str(new_status)},
                )
        logger.info(
            "status_updated_atomic",
            table=self.table_name,
            id=item_id,
            old=str(expected_old_status),
            new=str(new_status),
        )
        return self.get(item_id) if return_updated else None

    def _validate_order_by(self, order_by: str) -> str:
        """校验 ORDER BY 子句 — 只允许白名单列名 + ASC/DESC, 支持多列排序"""
        safe_parts = []
        for part in order_by.strip().split(","):
            tokens = part.strip().split()
            if len(tokens) == 1:
                col_name, direction = tokens[0], "ASC"
            elif len(tokens) == 2:
                col_name, direction = tokens[0], tokens[1].upper()
            else:
                raise DatabaseError(f"非法 ORDER BY 片段: {part.strip()}")
            if col_name not in self.columns:
                raise DatabaseError(f"非法排序列: {col_name}")
            if direction not in self._ALLOWED_ORDER_DIRECTIONS:
                raise DatabaseError(f"非法排序方向: {direction}")
            safe_parts.append(f"{col_name} {direction}")
        return ", ".join(safe_parts)

    def _validate_filter_columns(self, filters: dict[str, Any]) -> dict[str, Any]:
        """校验过滤列名 — 只允许白名单列名"""
        invalid = [k for k in filters if k not in self.columns]
        if invalid:
            raise DatabaseError(f"非法过滤列: {invalid}")
        return filters

    def list_items(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str = "created_at DESC",
        limit: int = 50,
        columns: list[str] | None = None,
    ) -> list[M]:
        filters = filters or {}
        # 安全校验: 过滤列名白名单
        self._validate_filter_columns(filters)
        # 安全校验: ORDER BY 白名单
        safe_order = self._validate_order_by(order_by)
        # 安全校验: SELECT 列白名单
        col_str = self._safe_columns(columns)
        sql = f"SELECT {col_str} FROM {self._safe_table()} WHERE 1=1"
        params: list[Any] = []
        for col, val in filters.items():
            if val is not None:
                sql += f" AND {col} = ?"
                params.append(val)
        sql, params = self._where_scenario(sql, params)
        sql += f" ORDER BY {safe_order} LIMIT ?"
        params.append(limit)
        with self._cm.get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_model(r) for r in rows]

    def _model_to_values(self, item: M) -> tuple:
        values = []
        for col in self.columns:
            attr = self.column_alias.get(col, col)
            val = getattr(item, attr, None)
            if val is None:
                values.append(None)
            elif col in self.datetime_columns and isinstance(val, datetime):
                values.append(val.isoformat())
            elif col in self.json_columns:
                values.append(json.dumps(val, ensure_ascii=False))
            else:
                values.append(val)
        return tuple(values)

    def _row_to_model(self, row: Any) -> M:
        data = {}
        for col in self.columns:
            try:
                val = row[col]
            except (IndexError, KeyError):
                # 列在DB中不存在(迁移未完成) — 跳过，让Pydantic用默认值
                continue
            attr = self.column_alias.get(col, col)
            if col in self.json_columns and isinstance(val, str):
                default = self.default_json_values.get(col, {})
                data[attr] = json.loads(val) if val and val.strip() else default
            elif col in self.enum_columns and isinstance(val, (str, int)):
                enum_cls = self.enum_columns[col]
                if isinstance(val, str) and issubclass(enum_cls, int):
                    val = int(val)
                data[attr] = enum_cls(val)
            elif col in self.datetime_columns and isinstance(val, str):
                if val:
                    dt = datetime.fromisoformat(val)
                    # 优先保留原始类型：model 字段如果是 str 则转回 isoformat
                    field_type = self.model_class.model_fields.get(attr, None)
                    if field_type is not None and field_type.annotation is str:
                        data[attr] = dt.isoformat()
                    else:
                        data[attr] = dt
                else:
                    data[attr] = ""
            else:
                data[attr] = val
        return self.model_class(**data)
