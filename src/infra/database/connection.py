
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge SQLite 连接管理器

设计决策:
  - SQLite 连接不能安全跨线程使用，因此采用 threading.local() 线程本地连接
  - 每个线程首次访问时创建连接并设置 WAL PRAGMA，线程结束时自动关闭
  - 提供 contextmanager get_conn() 确保连接正确获取/归还
  - 健康检查 + 自动重连

铁律: 零裸 sqlite3.connect()，所有数据库访问必须通过本模块。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from config import get_settings

if TYPE_CHECKING:
    from collections.abc import Generator

logger = structlog.get_logger(__name__)

# ── UnitOfWork 上下文（线程本地）───────────────────────
# 当 UnitOfWork 激活时，_uow_local.conn 持有事务连接。
# get_conn() / get() 自动返回该连接，使跨模块写操作共享同一事务。
_uow_local = threading.local()


def _set_uow_conn(conn: sqlite3.Connection | None) -> None:
    """设置当前线程的 UoW 连接（None=清除）"""
    _uow_local.conn = conn


def _get_uow_conn() -> sqlite3.Connection | None:
    """获取当前线程的 UoW 连接（无则返回 None）"""
    return getattr(_uow_local, "conn", None)


# ── WAL PRAGMA 最佳实践组合 ──
_WAL_PRAGMAS = [
    "PRAGMA journal_mode=WAL",  # 读写并发
    "PRAGMA synchronous=NORMAL",  # 安全与性能平衡
    "PRAGMA busy_timeout=5000",  # 写冲突等5秒
    "PRAGMA temp_store=MEMORY",  # 临时表内存化
    "PRAGMA mmap_size=268435456",  # 256MB mmap
    "PRAGMA cache_size=-64000",  # 64MB页缓存 (OPT-018)
    "PRAGMA foreign_keys=ON",  # 外键约束
]


class ConnectionManager:
    """线程安全的 SQLite 连接管理器

    - 每个线程维护自己的连接 (threading.local)
    - 连接创建时自动设置 WAL PRAGMA
    - 健康检查 + 自动重建损坏连接
    - 优雅关闭时释放所有线程的连接
    """

    def __init__(self, db_path: str | Path | None = None, wal_mode: bool = True):
        # Note: pool_size only applies to PostgreSQL mode. SQLite uses thread-local connections.
        settings = get_settings()
        if db_path:
            self._db_path = Path(db_path)
        else:
            # 从 URL 提取路径 — 兼容 sqlite:/// 和 sqlite+aiosqlite:/// 两种格式
            url = settings.db.url
            for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
                if url.startswith(prefix):
                    self._db_path = Path(url[len(prefix) :])
                    break
            else:
                self._db_path = Path(url)
        self._wal_mode = wal_mode
        self._local = threading.local()
        self._lock = threading.Lock()
        self._closed = False
        self._all_connections: list[sqlite3.Connection] = []
        self._engine_tables_checked: bool = False  # 实例级别标记
        # 统计
        self._stats = {
            "connections_created": 0,
            "connections_reused": 0,
            "connections_rebuilt": 0,
            "health_checks": 0,
        }

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _get_thread_conn(self) -> sqlite3.Connection | None:
        """获取当前线程的连接(可能为None)"""
        return getattr(self._local, "conn", None)

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接并设置 PRAGMA"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,  # 多线程安全: thread-local 隔离 + WAL 串行写
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row

        if self._wal_mode:
            for pragma in _WAL_PRAGMAS:
                conn.execute(pragma)

        self._local.conn = conn
        with self._lock:
            self._all_connections.append(conn)
        self._stats["connections_created"] += 1
        logger.debug("sqlite_conn_created", path=str(self._db_path), thread=threading.current_thread().name)

        # 首次连接时自动创建引擎基础设施表 (safety-net)
        if not self._engine_tables_checked:
            self._engine_tables_checked = True
            try:
                from src.infra.database.engine_tables import ensure_engine_tables

                ensure_engine_tables(conn)
            except (sqlite3.OperationalError, sqlite3.IntegrityError, ConnectionError):
                logger.debug("engine_tables_ensure_failed", exc_info=True)

        return conn

    def get(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接 (惰性创建 + 健康检查)"""
        if self._closed:
            # P0-06: 抛出具体子类，便于 isinstance 判断（替代字符串匹配）
            from src.exceptions import DatabaseConnectionClosedError

            raise DatabaseConnectionClosedError("ConnectionManager is closed")

        # UoW 激活时直接返回事务连接，跳过健康检查
        # （事务中连接重建会丢失事务）
        uow_conn = _get_uow_conn()
        if uow_conn is not None:
            return uow_conn

        conn = self._get_thread_conn()
        if conn is None:
            return self._create_connection()

        # 健康检查
        if not self._is_healthy(conn):
            logger.warning("sqlite_conn_unhealthy_rebuilding", thread=threading.current_thread().name)
            self._close_thread_conn()
            self._stats["connections_rebuilt"] += 1
            return self._create_connection()

        self._stats["connections_reused"] += 1
        return conn

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """上下文管理器方式获取连接

        用法:
            with cm.get_conn() as conn:
                conn.execute("INSERT ...")
                conn.commit()  #调用者显式commit

        退出时自动rollback残留的implicit transaction，释放WAL锁。
        不会影响已commit的数据。

        UoW 感知: 当 UnitOfWork 激活时，返回 UoW 事务连接，
        退出时不 rollback（由 UoW 管理事务生命周期）。
        """
        # UoW 激活时：返回 UoW 连接，退出时不 rollback
        uow_conn = _get_uow_conn()
        if uow_conn is not None:
            try:
                yield uow_conn
            except (sqlite3.OperationalError, sqlite3.IntegrityError, ConnectionError, RuntimeError):
                raise  # UoW __exit__ 会处理 rollback
            # 故意不 rollback —— UoW 管理事务
            return

        conn = self.get()
        try:
            yield conn
        except (sqlite3.OperationalError, sqlite3.IntegrityError, ConnectionError, RuntimeError):
            conn.rollback()
            raise
        else:
            # 正常退出时提交隐式事务 — 确保 INSERT/UPDATE 对后续连接可见
            conn.commit()
        finally:
            # 始终rollback：结束任何残留的implicit transaction，释放WAL锁
            # 对已commit的数据无影响，仅清除commit后自动开始的空事务
            try:
                conn.rollback()
            except (sqlite3.OperationalError, RuntimeError):
                logger.debug("db_conn_rollback_cleanup_failed", thread=threading.current_thread().name)

    def _is_healthy(self, conn: sqlite3.Connection) -> bool:
        """检查连接是否存活"""
        try:
            conn.execute("SELECT 1")
            return True
        except (sqlite3.OperationalError, sqlite3.DatabaseError, sqlite3.ProgrammingError, OSError):
            return False

    def _close_thread_conn(self) -> None:
        """关闭当前线程的连接"""
        conn = self._get_thread_conn()
        if conn is not None:
            try:
                conn.close()
            except (sqlite3.OperationalError, OSError) as e:
                logger.warning("db_conn_close_failed", error=str(e), exc_info=True)
            self._local.conn = None

    def close(self) -> None:
        """关闭所有连接 (优雅关闭时调用)"""
        self._closed = True
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except (sqlite3.OperationalError, OSError):
                    logger.debug("db_conn_close_cleanup_failed", thread=threading.current_thread().name)
            self._all_connections.clear()
        self._local.conn = None
        logger.info("sqlite_conn_manager_closed", path=str(self._db_path))

    # ── 健康检查 (面向 /health/ready) ──

    def health_check(self) -> dict[str, Any]:
        """返回连接健康状态"""
        self._stats["health_checks"] += 1
        start = time.monotonic()
        try:
            conn = self.get()
            conn.execute("SELECT 1")
            latency_ms = (time.monotonic() - start) * 1000
            # 获取 WAL 状态
            wal_mode = ""
            try:
                row = conn.execute("PRAGMA journal_mode").fetchone()
                wal_mode = row[0] if row else "unknown"
            except (sqlite3.OperationalError, ConnectionError) as e:
                logger.warning("wal_query_failed", error=str(e), exc_info=True)
            return {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "wal_mode": wal_mode,
                "db_path": str(self._db_path),
                "stats": dict(self._stats),
            }
        except (sqlite3.OperationalError, sqlite3.DatabaseError, ConnectionError, OSError) as e:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception("db_health_check_failed", db_path=str(self._db_path))
            return {
                "status": "unhealthy",
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
                "db_path": str(self._db_path),
                "stats": dict(self._stats),
            }

    def get_stats(self) -> dict[str, Any]:
        """返回连接统计"""
        return dict(self._stats)

    def backup(self, backup_path: str | Path | None = None) -> Path:
        """在线备份数据库 — 使用 SQLite 内置 backup API

        特点: 不会锁住写操作, 适合生产环境在线备份。
        """
        if backup_path is None:
            from datetime import datetime

            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            backup_path = self._db_path.parent / "backups" / f"taskforge_{ts}.db"

        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        dst_conn = sqlite3.connect(str(backup_path))
        try:
            src_conn = self.get()
            src_conn.backup(dst_conn, pages=128)  # 128页增量, 减少内存占用
            dst_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("sqlite_backup_completed", path=str(backup_path))
        finally:
            dst_conn.close()

        return backup_path


# ── 全局单例 — 根据配置自动选择 SQLite / PostgreSQL ──
from src.infra.singleton import Singleton


def _create_connection_manager():
    """工厂函数 — 根据 db.url 配置选择 SQLite 或 PostgreSQL 连接管理器"""
    settings = get_settings()
    if settings.db.is_postgresql:
        from src.infra.database.pg_connection import PgConnectionManager

        logger.info("database_backend_selected", backend="postgresql")
        return PgConnectionManager(
            db_url=settings.db.url,
            pool_size=settings.db.pool_size,
        )
    logger.info("database_backend_selected", backend="sqlite")
    return ConnectionManager()


_connection_manager = Singleton(_create_connection_manager)


def get_connection_manager():
    """获取全局连接管理器单例 (自动选择 SQLite / PostgreSQL)"""
    return _connection_manager.get()


def reset_connection_manager() -> None:
    """重置连接管理器单例 (仅用于测试)"""
    instance = _connection_manager.instance
    if instance is not None:
        instance.close()
    _connection_manager.reset()
