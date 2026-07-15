
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Template marketplace manager — BaseManager for marketplace_templates + marketplace_reviews."""

from __future__ import annotations

import structlog

from src.engine.template_market.models import MarketplaceReview, MarketplaceTemplate
from src.infra.database.base_manager import BaseManager

logger = structlog.get_logger(__name__)

# ── DDL ────────────────────────────────────────────────────────────────

MARKETPLACE_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS marketplace_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT 'freelance',
    category TEXT NOT NULL DEFAULT 'general',
    version TEXT NOT NULL DEFAULT '1.0.0',
    author TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    icon TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'public',
    status TEXT NOT NULL DEFAULT 'published',
    min_platform_version TEXT NOT NULL DEFAULT '1.0.0',
    source_type TEXT NOT NULL DEFAULT 'builtin',
    source_id TEXT NOT NULL DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    skills TEXT NOT NULL DEFAULT '[]',
    workflow_dsl TEXT NOT NULL DEFAULT '{}',
    variables TEXT NOT NULL DEFAULT '{}',
    download_count INTEGER NOT NULL DEFAULT 0,
    rating_sum REAL NOT NULL DEFAULT 0.0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    featured INTEGER NOT NULL DEFAULT 0,
    activated_resource_type TEXT NOT NULL DEFAULT '',
    activated_resource_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_mkt_industry ON marketplace_templates(industry);
CREATE INDEX IF NOT EXISTS idx_mkt_category ON marketplace_templates(category);
CREATE INDEX IF NOT EXISTS idx_mkt_status ON marketplace_templates(status);
CREATE INDEX IF NOT EXISTS idx_mkt_featured ON marketplace_templates(featured);
"""

MARKETPLACE_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS marketplace_reviews (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mkr_template ON marketplace_reviews(template_id);
"""


# ── TemplateMarketManager ─────────────────────────────────────────────


class TemplateMarketManager(BaseManager):
    """模板市场主表 CRUD + 搜索/安装/评分"""

    table_name = "marketplace_templates"
    model_class = MarketplaceTemplate
    ddl = MARKETPLACE_TEMPLATES_DDL
    columns = [
        "id",
        "name",
        "display_name",
        "description",
        "industry",
        "category",
        "version",
        "author",
        "tags",
        "icon",
        "visibility",
        "status",
        "min_platform_version",
        "source_type",
        "source_id",
        "config",
        "skills",
        "workflow_dsl",
        "variables",
        "download_count",
        "rating_sum",
        "rating_count",
        "featured",
        "activated_resource_type",
        "activated_resource_id",
        "created_at",
        "updated_at",
    ]
    json_columns = {"tags", "config", "skills", "workflow_dsl", "variables"}
    datetime_columns = {"created_at", "updated_at"}
    filter_column = "status"
    default_json_values = {
        "tags": [],
        "config": {},
        "skills": [],
        "workflow_dsl": {},
        "variables": {},
    }

    def initialize(self) -> None:
        """Initialize table + safe migration for new columns."""
        super().initialize()
        self._migrate_add_activated_columns()

    def _migrate_add_activated_columns(self) -> None:
        """Safely add activated_resource_type/id columns if missing."""
        with self._cm.get_conn() as conn:
            try:
                conn.execute(
                    f"SELECT activated_resource_type FROM {self._safe_table()} LIMIT 1"
                )
            except Exception:
                conn.execute(
                    f"ALTER TABLE {self._safe_table()} ADD COLUMN activated_resource_type TEXT NOT NULL DEFAULT ''"
                )
                conn.execute(
                    f"ALTER TABLE {self._safe_table()} ADD COLUMN activated_resource_id TEXT NOT NULL DEFAULT ''"
                )
                conn.commit()
                logger.info("migration_applied", migration="add_activated_columns")

    def count_by_filter(
        self,
        *,
        industry: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> int:
        """按条件统计全量条数（分页total用）"""
        with self._cm.get_conn() as conn:
            sql = f"SELECT COUNT(*) FROM {self._safe_table()} WHERE 1=1"
            params: list = []
            if query:
                sql += " AND (name LIKE ? OR display_name LIKE ? OR description LIKE ? OR tags LIKE ?)"
                q = f"%{query}%"
                params.extend([q, q, q, q])
            if industry:
                sql += " AND industry = ?"
                params.append(industry)
            if category:
                sql += " AND category = ?"
                params.append(category)
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

    def search(
        self,
        query: str,
        *,
        industry: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MarketplaceTemplate], int]:
        """全文搜索：name/display_name/description/tags，返回(results, total)"""
        total = self.count_by_filter(industry=industry, category=category, query=query)
        with self._cm.get_conn() as conn:
            sql = f"SELECT * FROM {self._safe_table()} WHERE 1=1"
            params: list = []
            if query:
                sql += " AND (name LIKE ? OR display_name LIKE ? OR description LIKE ? OR tags LIKE ?)"
                q = f"%{query}%"
                params.extend([q, q, q, q])
            if industry:
                sql += " AND industry = ?"
                params.append(industry)
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += " ORDER BY download_count DESC LIMIT ? OFFSET ?"
            params.extend([page_size, (page - 1) * page_size])
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_model(r) for r in rows], total

    def install(self, template_id: str) -> MarketplaceTemplate | None:
        """安装模板：递增download_count，设置status=installed，激活到运行时"""
        item = self.get(template_id)
        if item is None:
            return None
        new_count = item.download_count + 1

        # Activate into runtime
        activation_error = ""
        activated_resource_type = ""
        activated_resource_id = ""
        try:
            from src.engine.template_market.activator import get_template_activator

            activator = get_template_activator()
            result = activator.activate(item)
            if result.success:
                activated_resource_type = result.resource_type
                activated_resource_id = result.resource_id
            else:
                activation_error = result.error
        except Exception as e:
            activation_error = str(e)

        if activation_error:
            logger.warning("activation_skipped", template_id=template_id, error=activation_error)

        return self.update_fields(
            template_id,
            download_count=new_count,
            status="installed",
            activated_resource_type=activated_resource_type,
            activated_resource_id=activated_resource_id,
        )

    def uninstall(self, template_id: str) -> MarketplaceTemplate | None:
        """卸载模板：恢复status=published，清理运行时资源"""
        item = self.get(template_id)
        if item is None:
            return None
        if item.status != "installed":
            return item  # 未安装，无需操作

        # Deactivate from runtime
        try:
            self._deactivate(item)
        except Exception as e:
            logger.warning("deactivation_failed", template_id=template_id, error=str(e))

        return self.update_fields(
            template_id,
            status="published",
            activated_resource_type="",
            activated_resource_id="",
        )

    def _deactivate(self, item: MarketplaceTemplate) -> None:
        """Remove activated resource from runtime."""
        resource_type = getattr(item, "activated_resource_type", "")
        resource_id = getattr(item, "activated_resource_id", "")

        if not resource_id:
            return

        if resource_type == "agent":
            try:
                from src.engine.agent.specialist_base import get_agent_registry

                registry = get_agent_registry()
                if resource_id in registry._agents:
                    del registry._agents[resource_id]
                    logger.info("agent_deactivated", agent_name=resource_id)
            except Exception as e:
                logger.debug("agent_deactivation_failed", error=str(e))

        # Note: workflow deactivation (delete workflow) is more complex
        # and should be handled explicitly by the user

    def add_rating(self, template_id: str, rating: int) -> MarketplaceTemplate | None:
        """更新模板评分汇总"""
        item = self.get(template_id)
        if item is None:
            return None
        new_sum = item.rating_sum + rating
        new_count = item.rating_count + 1
        return self.update_fields(
            template_id,
            rating_sum=new_sum,
            rating_count=new_count,
        )

    def get_featured(self, limit: int = 10) -> list[MarketplaceTemplate]:
        """获取精选模板"""
        return self.list_items(
            filters={"featured": 1},
            order_by="download_count DESC",
            limit=limit,
        )

    def list_by_industry(self, industry: str, *, page: int = 1, page_size: int = 20) -> tuple[list[MarketplaceTemplate], int]:
        """按行业列表，返回(results, total)"""
        total = self.count_by_filter(industry=industry)
        offset = (page - 1) * page_size
        with self._cm.get_conn() as conn:
            sql = f"SELECT * FROM {self._safe_table()} WHERE industry = ? ORDER BY download_count DESC LIMIT ? OFFSET ?"
            rows = conn.execute(sql, [industry, page_size, offset]).fetchall()
            return [self._row_to_model(r) for r in rows], total


# ── TemplateReviewManager ─────────────────────────────────────────────


class TemplateReviewManager(BaseManager):
    """模板评分评论 CRUD"""

    table_name = "marketplace_reviews"
    model_class = MarketplaceReview
    ddl = MARKETPLACE_REVIEWS_DDL
    columns = ["id", "template_id", "user_id", "rating", "comment", "created_at"]
    datetime_columns = {"created_at"}
    filter_column = "template_id"

    def list_by_template(self, template_id: str) -> list[MarketplaceReview]:
        """获取模板的所有评论"""
        return self.list_items(
            filters={"template_id": template_id},
            order_by="created_at DESC",
            limit=100,
        )

    def has_reviewed(self, template_id: str, user_id: str) -> bool:
        """检查用户是否已评价过该模板"""
        if not user_id:
            return False
        with self._cm.get_conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {self._safe_table()} WHERE template_id = ? AND user_id = ?",
                [template_id, user_id],
            ).fetchone()
            return (row[0] if row else 0) > 0


# ── Singleton getters ─────────────────────────────────────────────────

_tm_manager: TemplateMarketManager | None = None
_tr_manager: TemplateReviewManager | None = None


def get_template_market_manager() -> TemplateMarketManager:
    global _tm_manager
    if _tm_manager is None:
        from src.infra.database.connection import get_connection_manager

        _tm_manager = TemplateMarketManager(get_connection_manager())
        _tm_manager.initialize()
    return _tm_manager


def get_template_review_manager() -> TemplateReviewManager:
    global _tr_manager
    if _tr_manager is None:
        from src.infra.database.connection import get_connection_manager

        _tr_manager = TemplateReviewManager(get_connection_manager())
        _tr_manager.initialize()
    return _tr_manager
