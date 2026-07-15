
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill-Gap 2-3: 工作流版本管理

增强点：
1. 版本快照：保存工作流的某个版本
2. 版本历史：查询版本历史
3. 版本回滚：回滚到指定版本
4. 版本比较：比较两个版本的差异
5. 版本标签：支持标签管理（如 v1.0, stable）
6. 草稿/发布分离：支持草稿编辑和正式发布
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from src.infra.database.connection import ConnectionManager, get_connection_manager

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)


class VersionStatus(StrEnum):
    """版本状态"""

    DRAFT = "draft"  # 草稿
    PUBLISHED = "published"  # 已发布
    ARCHIVED = "archived"  # 已归档
    DEPRECATED = "deprecated"  # 已废弃


@dataclass
class WorkflowVersion:
    """工作流版本"""

    version_id: str
    workflow_id: str
    version_number: int
    label: str = ""  # 如 v1.0, stable
    status: VersionStatus = VersionStatus.DRAFT
    snapshot: dict[str, Any] = field(default_factory=dict)  # 工作流快照
    change_log: str = ""  # 变更说明
    created_by: str = ""
    created_at: str = ""
    parent_version_id: str = ""  # 父版本（用于版本树）

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "workflow_id": self.workflow_id,
            "version_number": self.version_number,
            "label": self.label,
            "status": self.status.value,
            "snapshot": self.snapshot,
            "change_log": self.change_log,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "parent_version_id": self.parent_version_id,
        }


@dataclass
class VersionDiff:
    """版本差异"""

    from_version: str
    to_version: str
    added: dict[str, Any] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)
    modified: dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
            "summary": self.summary,
        }

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)


class WorkflowVersionManager:
    """工作流版本管理器

    提供版本快照、历史、回滚、比较等功能
    """

    VERSION_DDL = """
    CREATE TABLE IF NOT EXISTS workflow_versions (
        version_id TEXT PRIMARY KEY,
        workflow_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        label TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        snapshot TEXT NOT NULL,
        change_log TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        parent_version_id TEXT DEFAULT '',
        UNIQUE(workflow_id, version_number)
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow ON workflow_versions(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_workflow_versions_status ON workflow_versions(status);
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._cm: ConnectionManager | None = None
        if db_path is not None:
            self._cm = ConnectionManager(db_path)
        self._init_db()

    @property
    def db_path(self) -> Path:
        """返回当前使用的数据库路径"""
        return self._get_cm().db_path

    def _get_cm(self) -> ConnectionManager:
        """获取连接管理器（优先使用实例级，回退到全局单例）"""
        return self._cm if self._cm is not None else get_connection_manager()

    def _init_db(self) -> None:
        with self._get_cm().get_conn() as conn:
            conn.executescript(self.VERSION_DDL)

    def create_version(
        self,
        workflow_id: str,
        workflow_snapshot: dict[str, Any],
        *,
        label: str = "",
        change_log: str = "",
        created_by: str = "",
        parent_version_id: str = "",
        status: VersionStatus = VersionStatus.DRAFT,
    ) -> WorkflowVersion:
        """创建新版本"""
        import uuid

        version_number = self._next_version_number(workflow_id)
        version_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        version = WorkflowVersion(
            version_id=version_id,
            workflow_id=workflow_id,
            version_number=version_number,
            label=label,
            status=status,
            snapshot=workflow_snapshot,
            change_log=change_log,
            created_by=created_by,
            created_at=now,
            parent_version_id=parent_version_id,
        )

        with self._get_cm().get_conn() as conn:
            conn.execute(
                """INSERT INTO workflow_versions
                (version_id, workflow_id, version_number, label, status,
                 snapshot, change_log, created_by, created_at, parent_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version.version_id,
                    version.workflow_id,
                    version.version_number,
                    version.label,
                    version.status.value,
                    json.dumps(version.snapshot, ensure_ascii=False),
                    version.change_log,
                    version.created_by,
                    version.created_at,
                    version.parent_version_id,
                ),
            )
            logger.info(
                "workflow_version_created",
                workflow_id=workflow_id,
                version_number=version_number,
                label=label,
            )

        return version

    def _next_version_number(self, workflow_id: str) -> int:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(version_number) as max_num FROM workflow_versions WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            return (row["max_num"] or 0) + 1

    def get_version(self, version_id: str) -> WorkflowVersion | None:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_version(row)

    def get_version_by_number(self, workflow_id: str, version_number: int) -> WorkflowVersion | None:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? AND version_number = ?",
                (workflow_id, version_number),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_version(row)

    def get_latest_version(self, workflow_id: str) -> WorkflowVersion | None:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? ORDER BY version_number DESC LIMIT 1",
                (workflow_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_version(row)

    def get_published_version(self, workflow_id: str) -> WorkflowVersion | None:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM workflow_versions
                WHERE workflow_id = ? AND status = ?
                ORDER BY version_number DESC LIMIT 1""",
                (workflow_id, VersionStatus.PUBLISHED.value),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_version(row)

    def list_versions(
        self,
        workflow_id: str,
        *,
        status: VersionStatus | None = None,
        limit: int = 100,
    ) -> list[WorkflowVersion]:
        with self._get_cm().get_conn() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM workflow_versions
                    WHERE workflow_id = ? AND status = ?
                    ORDER BY version_number DESC LIMIT ?""",
                    (workflow_id, status.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM workflow_versions
                    WHERE workflow_id = ?
                    ORDER BY version_number DESC LIMIT ?""",
                    (workflow_id, limit),
                ).fetchall()
            return [self._row_to_version(row) for row in rows]

    def update_status(self, version_id: str, status: VersionStatus) -> bool:
        with self._get_cm().get_conn() as conn:
            cursor = conn.execute(
                "UPDATE workflow_versions SET status = ? WHERE version_id = ?",
                (status.value, version_id),
            )
            if cursor.rowcount > 0:
                logger.info(
                    "workflow_version_status_updated",
                    version_id=version_id,
                    status=status.value,
                )
                return True
            return False

    def publish_version(self, version_id: str) -> bool:
        version = self.get_version(version_id)
        if version is None:
            return False

        with self._get_cm().get_conn() as conn:
            conn.execute(
                """UPDATE workflow_versions
                SET status = ?
                WHERE workflow_id = ? AND status = ? AND version_id != ?""",
                (VersionStatus.ARCHIVED.value, version.workflow_id, VersionStatus.PUBLISHED.value, version_id),
            )
            conn.execute(
                "UPDATE workflow_versions SET status = ? WHERE version_id = ?",
                (VersionStatus.PUBLISHED.value, version_id),
            )
            logger.info(
                "workflow_version_published",
                version_id=version_id,
                workflow_id=version.workflow_id,
                version_number=version.version_number,
            )
            return True

    def rollback_to_version(self, version_id: str) -> WorkflowVersion | None:
        """回滚到指定版本

        创建一个新版本，内容为指定版本的快照
        """
        version = self.get_version(version_id)
        if version is None:
            return None

        return self.create_version(
            workflow_id=version.workflow_id,
            workflow_snapshot=version.snapshot,
            label=f"rollback_to_v{version.version_number}",
            change_log=f"回滚到版本 v{version.version_number}",
            parent_version_id=version_id,
        )

    def compare_versions(self, version_id_a: str, version_id_b: str) -> VersionDiff:
        """比较两个版本的差异"""
        version_a = self.get_version(version_id_a)
        version_b = self.get_version(version_id_b)

        if version_a is None or version_b is None:
            return VersionDiff(from_version=version_id_a, to_version=version_id_b, summary="版本不存在")

        return self._diff_snapshots(
            version_a.snapshot,
            version_b.snapshot,
            from_version=f"v{version_a.version_number}",
            to_version=f"v{version_b.version_number}",
        )

    def _diff_snapshots(
        self,
        snapshot_a: dict[str, Any],
        snapshot_b: dict[str, Any],
        *,
        from_version: str,
        to_version: str,
    ) -> VersionDiff:
        """计算两个快照的差异"""
        added: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        modified: dict[str, Any] = {}

        all_keys = set(snapshot_a.keys()) | set(snapshot_b.keys())

        for key in all_keys:
            if key in snapshot_a and key not in snapshot_b:
                removed[key] = snapshot_a[key]
            elif key not in snapshot_a and key in snapshot_b:
                added[key] = snapshot_b[key]
            elif snapshot_a[key] != snapshot_b[key]:
                modified[key] = {
                    "from": snapshot_a[key],
                    "to": snapshot_b[key],
                }

        summary_parts = []
        if added:
            summary_parts.append(f"新增 {len(added)} 项")
        if removed:
            summary_parts.append(f"删除 {len(removed)} 项")
        if modified:
            summary_parts.append(f"修改 {len(modified)} 项")
        summary = "、".join(summary_parts) if summary_parts else "无变更"

        return VersionDiff(
            from_version=from_version,
            to_version=to_version,
            added=added,
            removed=removed,
            modified=modified,
            summary=summary,
        )

    def delete_version(self, version_id: str) -> bool:
        version = self.get_version(version_id)
        if version is None:
            return False
        if version.status != VersionStatus.DRAFT:
            logger.warning(
                "cannot_delete_non_draft_version",
                version_id=version_id,
                status=version.status.value,
            )
            return False

        with self._get_cm().get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM workflow_versions WHERE version_id = ?",
                (version_id,),
            )
            return cursor.rowcount > 0

    def add_label(self, version_id: str, label: str) -> bool:
        with self._get_cm().get_conn() as conn:
            cursor = conn.execute(
                "UPDATE workflow_versions SET label = ? WHERE version_id = ?",
                (label, version_id),
            )
            return cursor.rowcount > 0

    def get_version_by_label(self, workflow_id: str, label: str) -> WorkflowVersion | None:
        with self._get_cm().get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? AND label = ? ORDER BY version_number DESC LIMIT 1",
                (workflow_id, label),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_version(row)

    def _row_to_version(self, row) -> WorkflowVersion:
        """数据库行转 WorkflowVersion"""
        return WorkflowVersion(
            version_id=row["version_id"],
            workflow_id=row["workflow_id"],
            version_number=row["version_number"],
            label=row["label"],
            status=VersionStatus(row["status"]),
            snapshot=json.loads(row["snapshot"]),
            change_log=row["change_log"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            parent_version_id=row["parent_version_id"],
        )

    def get_statistics(self, workflow_id: str) -> dict[str, Any]:
        with self._get_cm().get_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM workflow_versions WHERE workflow_id = ? GROUP BY status",
                (workflow_id,),
            ).fetchall()
            status_counts = {row["status"]: row["count"] for row in rows}
            total = sum(status_counts.values())

            latest = self.get_latest_version(workflow_id)
            published = self.get_published_version(workflow_id)

            return {
                "workflow_id": workflow_id,
                "total_versions": total,
                "status_counts": status_counts,
                "latest_version": latest.version_number if latest else 0,
                "published_version": published.version_number if published else None,
            }
