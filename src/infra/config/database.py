
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""数据库配置: SQLite(开发) / PostgreSQL(生产) + Read Replica"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.infra.config._constants import PROJECT_ROOT


class DatabaseConfig(BaseModel):
    """数据库配置: SQLite(开发) / PostgreSQL(生产)

    P2-18: 支持 Read Replica 分担查询负载
    """

    url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'taskforge.db'}",
        description="数据库连接URL (sqlite:/// 或 postgresql://)",
    )
    pool_size: int = Field(default=5, ge=1, le=50, description="连接池大小")
    wal_mode: bool = Field(default=True, description="SQLite WAL 模式")
    write_batch_size: int = Field(
        default=50, ge=1, le=500, description="SQLiteWriteQueue批量提交大小(TF_DB__WRITE_BATCH_SIZE)"
    )
    # P2-18: Read Replica 配置
    read_replica_url: str = Field(
        default="", description="只读副本 URL (留空则使用主库，如: postgresql://user:pass@replica:5432/taskforge)"
    )
    replica_poll_interval: float = Field(default=2.0, ge=0.5, le=30.0, description="Replica 故障转移轮询间隔(秒)")
    replica_max_retries: int = Field(default=3, ge=0, le=10, description="Replica 连接失败最大重试次数")

    @field_validator("read_replica_url")
    @classmethod
    def validate_replica_url(cls, v: str, info) -> str:
        """如果配置了 replica_url，必须是有效的 postgresql URL"""
        if v and not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(f"read_replica_url 必须使用 postgresql:// 协议，当前: {v[:50]}...")
        return v

    @property
    def is_postgresql(self) -> bool:
        return self.url.startswith("postgresql") or self.url.startswith("postgres://")

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith(("sqlite:///", "sqlite+aiosqlite:///"))

    @property
    def has_read_replica(self) -> bool:
        """是否配置了读副本"""
        return bool(self.read_replica_url)

    def get_write_url(self) -> str:
        """获取写库 URL"""
        return self.url

    def get_read_url(self) -> str:
        """获取读库 URL（优先使用 replica，否则使用主库）"""
        return self.read_replica_url or self.url
