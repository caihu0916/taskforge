
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 工作流事件溯源 + 检查点持久化

职责:
  - WorkflowEvent: 记录工作流每次状态变更的不可变事件
  - Checkpoint: 定期快照完整工作流状态，加速恢复
  - WorkflowEventManager: 事件持久化 CRUD
  - CheckpointManager: 检查点持久化 CRUD
  - recover_workflow(): 从最新检查点 + 重放后续事件 → 恢复工作流

设计决策:
  - 事件不可变：append-only，不修改/删除
  - 检查点可选：feature flag 守护，按策略自动创建
  - 恢复幂等：重放时跳过已处理事件
  - 参考 TraceManager 的 BaseManager 风格实现
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


# ── 工作流事件类型 ──


class WorkflowEventType(StrEnum):
    """工作流生命周期事件"""

    CREATED = "created"
    STARTED = "started"
    PHASE_ADVANCED = "phase_advanced"
    STEP_EXECUTED = "step_executed"
    STEP_APPROVED = "step_approved"
    STEP_REJECTED = "step_rejected"
    STEP_SKIPPED = "step_skipped"
    STEP_FAILED = "step_failed"
    CHECKPOINT_SAVED = "checkpoint_saved"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    GRAPH_COMPILED = "graph_compiled"
    STORE_UPDATED = "store_updated"


# ── WorkflowEvent 模型 ──


class WorkflowEvent(BaseModel):
    """工作流事件 — 不可变，append-only"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = Field(description="工作流ID")
    event_type: WorkflowEventType = Field(description="事件类型")
    payload: dict[str, Any] = Field(default_factory=dict, description="事件数据")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    trace_id: str = Field(default="", description="追踪ID，串联TracePipeline")


# ── Checkpoint 模型 ──


class Checkpoint(BaseModel):
    """工作流检查点 — 完整快照"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = Field(description="工作流ID")
    phase_index: int = Field(default=0, description="快照时的阶段索引")
    snapshot: str = Field(default="{}", description="完整Workflow JSON快照")
    event_count: int = Field(default=0, description="快照时的事件总数")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ── DDL ──

WORKFLOW_EVENT_DDL = """CREATE TABLE IF NOT EXISTS workflow_events (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    timestamp TEXT NOT NULL,
    trace_id TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_workflow_events_wf_id ON workflow_events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_type ON workflow_events(event_type);
CREATE INDEX IF NOT EXISTS idx_workflow_events_ts ON workflow_events(timestamp)
"""

WORKFLOW_CHECKPOINT_DDL = """CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    phase_index INTEGER DEFAULT 0,
    snapshot TEXT NOT NULL DEFAULT '{}',
    event_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_wf_id ON workflow_checkpoints(workflow_id, created_at DESC)
"""


# ── WorkflowEventManager ──

_EVENT_COLUMNS = [
    "id",
    "workflow_id",
    "event_type",
    "payload",
    "timestamp",
    "trace_id",
]

_EVENT_JSON_COLUMNS = {"payload"}


_INSERT_SQL = (
    f"INSERT INTO workflow_events ({', '.join(_EVENT_COLUMNS)}) VALUES ({', '.join('?' for _ in _EVENT_COLUMNS)})"
)


class WorkflowEventManager:
    """WorkflowEvent CRUD — BaseManager 风格，轻量独立，带缓冲。

    缓冲行为:
      - flush_interval_ms > 0: emit 事件会先 append 到 buffer，不立即写入 DB。
        需要显式调用 flush() 来批量写入。
      - flush_interval_ms == 0: 保持旧行为，直接 INSERT（向后兼容）。
      - 事件写入顺序与 emit 顺序一致。
      - max_buffer_size: buffer 上限保护，超出时自动 flush（防止内存溢出）。
    """

    def __init__(self, cm: Any = None, flush_interval_ms: int = 0, max_buffer_size: int = 1000) -> None:
        """创建 WorkflowEventManager。

        Args:
            cm: ConnectionManager 实例
            flush_interval_ms: 缓冲间隔（0=直接写，>0=缓冲模式）
            max_buffer_size: buffer 最大容量（超出时自动 flush，默认 1000）
        """
        from src.infra.database.connection import get_connection_manager

        self._cm = cm or get_connection_manager()
        self._initialized = False
        self._flush_interval_ms = int(flush_interval_ms)
        self._max_buffer_size = max(max_buffer_size, 1)  # 至少 1
        self._buffer: list[WorkflowEvent] = []

    def __len__(self) -> int:
        return len(self._buffer)

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._cm.get_conn() as conn:
            conn.executescript(WORKFLOW_EVENT_DDL)
            conn.commit()
        self._initialized = True
        logger.info("workflow_event_manager_initialized")

    def append(self, event: WorkflowEvent) -> WorkflowEvent:
        """追加一个事件 (append-only，不可修改)

        flush_interval_ms > 0 时会进入 buffer（非阻塞），否则直接写入 DB。
        buffer 超出 max_buffer_size 时自动 flush（防止内存溢出）。
        """
        self.initialize()
        # 缓冲模式：先入 buffer，不写 DB（稍后由 flush() 批量写入）
        if self._flush_interval_ms > 0:
            self._buffer.append(event)
            logger.debug(
                "workflow_event_buffered",
                wf_id=event.workflow_id,
                event_type=event.event_type.value,
                buffer_size=len(self._buffer),
            )
            # P0-1: buffer 上限保护 — 超出时自动 flush
            if len(self._buffer) >= self._max_buffer_size:
                logger.info(
                    "workflow_event_buffer_auto_flush",
                    buffer_size=len(self._buffer),
                    max_size=self._max_buffer_size,
                )
                self.flush()
            return event

        # 无缓冲模式：保持旧行为，直接 INSERT（向后兼容）
        with self._cm.get_conn() as conn:
            conn.execute(_INSERT_SQL, self._event_to_values(event))
            conn.commit()
        logger.debug("workflow_event_appended", wf_id=event.workflow_id, event_type=event.event_type.value)
        return event

    def flush(self) -> int:
        """批量写入 buffer 中的所有事件。

        返回本次写入的事件数（空 buffer 返回 0）。
        """
        if not self._buffer:
            return 0
        # 保持 emit 顺序（Python list 顺序天然一致）
        rows = [self._event_to_values(e) for e in self._buffer]
        with self._cm.get_conn() as conn:
            conn.executemany(_INSERT_SQL, rows)
            conn.commit()
        flushed = len(self._buffer)
        self._buffer = []
        logger.debug("workflow_event_buffer_flushed", flushed=flushed)
        return flushed

    def list_events(
        self,
        workflow_id: str,
        event_type: WorkflowEventType | None = None,
        limit: int = 100,
    ) -> list[WorkflowEvent]:
        """查询工作流事件列表，按时间升序"""
        self.initialize()
        sql = f"SELECT {', '.join(_EVENT_COLUMNS)} FROM workflow_events WHERE workflow_id = ?"
        params: list[Any] = [workflow_id]
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type.value)
        sql += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        with self._cm.get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_event(r) for r in rows]

    def count_events(self, workflow_id: str) -> int:
        """统计工作流事件数量"""
        self.initialize()
        with self._cm.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM workflow_events WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_events_since(self, workflow_id: str, since_timestamp: str) -> list[WorkflowEvent]:
        """查询指定时间点及之后的事件（恢复时重放用，含 since_timestamp 本身）"""
        self.initialize()
        with self._cm.get_conn() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_EVENT_COLUMNS)} FROM workflow_events WHERE workflow_id = ? AND timestamp >= ? ORDER BY timestamp ASC",
                (workflow_id, since_timestamp),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    # ── 内部方法 ──

    @staticmethod
    def _event_to_values(event: WorkflowEvent) -> tuple:
        values = []
        for col in _EVENT_COLUMNS:
            val = getattr(event, col, None)
            if col in _EVENT_JSON_COLUMNS and isinstance(val, dict):
                values.append(json.dumps(val, ensure_ascii=False))
            elif val is None:
                values.append("")
            else:
                values.append(val)
        return tuple(values)

    @staticmethod
    def _row_to_event(row: Any) -> WorkflowEvent:
        data = {}
        for i, col in enumerate(_EVENT_COLUMNS):
            try:
                val = row[i]
            except (IndexError, KeyError):
                continue
            if col in _EVENT_JSON_COLUMNS and isinstance(val, str):
                data[col] = json.loads(val) if val else {}
            elif col == "event_type":
                data[col] = WorkflowEventType(val)
            else:
                data[col] = val
        return WorkflowEvent(**data)


# ── CheckpointManager ──

_CHECKPOINT_COLUMNS = [
    "id",
    "workflow_id",
    "phase_index",
    "snapshot",
    "event_count",
    "created_at",
]


class CheckpointManager:
    """Checkpoint CRUD — BaseManager 风格，轻量独立"""

    def __init__(self, cm: Any = None) -> None:
        from src.infra.database.connection import get_connection_manager

        self._cm = cm or get_connection_manager()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._cm.get_conn() as conn:
            conn.executescript(WORKFLOW_CHECKPOINT_DDL)
            conn.commit()
        self._initialized = True
        logger.info("checkpoint_manager_initialized")

    def create(self, cp: Checkpoint) -> Checkpoint:
        """创建一个检查点"""
        self.initialize()
        with self._cm.get_conn() as conn:
            conn.execute(
                f"INSERT INTO workflow_checkpoints ({', '.join(_CHECKPOINT_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _CHECKPOINT_COLUMNS)})",
                self._checkpoint_to_values(cp),
            )
            conn.commit()
        logger.info("checkpoint_created", wf_id=cp.workflow_id, phase_index=cp.phase_index)
        return cp

    def get_latest(self, workflow_id: str) -> Checkpoint | None:
        """获取工作流最新的检查点"""
        self.initialize()
        with self._cm.get_conn() as conn:
            row = conn.execute(
                f"SELECT {', '.join(_CHECKPOINT_COLUMNS)} FROM workflow_checkpoints WHERE workflow_id = ? ORDER BY created_at DESC LIMIT 1",
                (workflow_id,),
            ).fetchone()
            return self._row_to_checkpoint(row) if row else None

    def list_checkpoints(self, workflow_id: str, limit: int = 20) -> list[Checkpoint]:
        """列出工作流的检查点，按创建时间降序"""
        self.initialize()
        with self._cm.get_conn() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_CHECKPOINT_COLUMNS)} FROM workflow_checkpoints WHERE workflow_id = ? ORDER BY created_at DESC LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
            return [self._row_to_checkpoint(r) for r in rows]

    def delete(self, checkpoint_id: str) -> bool:
        """删除检查点"""
        self.initialize()
        with self._cm.get_conn() as conn:
            conn.execute("DELETE FROM workflow_checkpoints WHERE id = ?", (checkpoint_id,))
            conn.commit()
        return True

    # ── 内部方法 ──

    @staticmethod
    def _checkpoint_to_values(cp: Checkpoint) -> tuple:
        values = []
        for col in _CHECKPOINT_COLUMNS:
            val = getattr(cp, col, None)
            if val is None:
                values.append("")
            else:
                values.append(val)
        return tuple(values)

    @staticmethod
    def _row_to_checkpoint(row: Any) -> Checkpoint:
        data = {}
        for i, col in enumerate(_CHECKPOINT_COLUMNS):
            try:
                val = row[i]
            except (IndexError, KeyError):
                continue
            data[col] = val
        return Checkpoint(**data)
