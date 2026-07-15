
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent 模板数据层(P1-S1-013~017)

提供 Agent 模板的定义、存储、查询、安装功能:
  - AgentTemplate: 模板数据模型(P1-S1-017)
  - TemplateCategory: 模板分类
  - TemplateStore: 模板存储(内存 + SQLite 持久化)
  - 内置模板注册(P1-S1-014~016): 5+ 个开箱即用的 Agent 模板
  - TemplateInstaller: 模板安装引擎(P1-S1-019)

设计原则:
  - 模板自描述: 包含 manifest + config + skills 完整定义
  - 版本化: 支持 semver,可升级
  - 可组合: 模板可依赖其他模板
  - 沙箱安装: 安装前校验,失败可回滚
"""

from __future__ import annotations

import json
import time
import uuid as _uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 枚举 ──


class TemplateCategory(StrEnum):
    """模板分类"""

    MARKETING = "marketing"  # 营销
    SALES = "sales"  # 销售
    SERVICE = "service"  # 客服
    CONTENT = "content"  # 内容创作
    ANALYSIS = "analysis"  # 数据分析
    DEVELOPMENT = "development"  # 开发辅助
    OPERATIONS = "operations"  # 运维
    GENERAL = "general"  # 通用


class TemplateStatus(StrEnum):
    """模板状态"""

    DRAFT = "draft"  # 草稿
    PUBLISHED = "published"  # 已发布
    DEPRECATED = "deprecated"  # 已废弃
    INSTALLED = "installed"  # 已安装


class TemplateVisibility(StrEnum):
    """模板可见性"""

    PUBLIC = "public"  # 公开(市场)
    PRIVATE = "private"  # 私有(个人)
    ORG = "org"  # 组织内


# ── 数据模型(P1-S1-017) ──


@dataclass
class TemplateSkill:
    """模板技能定义"""

    name: str
    description: str = ""
    tool_ids: list[str] = field(default_factory=list)  # 关联的 MCP 工具 ID
    prompt_template: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateManifest:
    """模板清单(元数据)"""

    name: str
    display_name: str
    description: str
    category: TemplateCategory = TemplateCategory.GENERAL
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    icon: str = ""  # 图标 URL 或 emoji
    visibility: TemplateVisibility = TemplateVisibility.PUBLIC
    status: TemplateStatus = TemplateStatus.PUBLISHED
    min_platform_version: str = "1.0.0"
    dependencies: list[str] = field(default_factory=list)  # 依赖的其他模板 ID
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    download_count: int = 0
    rating: float = 0.0
    rating_count: int = 0


@dataclass
class AgentTemplate:
    """Agent 模板完整定义(P1-S1-017)

    一个 Agent 模板包含:
      - manifest: 元数据(名称/分类/版本等)
      - config: Agent 配置(角色/模型/温度等)
      - skills: 技能列表
      - workflow_dsl: 关联的工作流 DSL(可选)
    """

    id: str = field(default_factory=lambda: _uuid.uuid4().hex[:12])
    manifest: TemplateManifest | None = None
    config: dict[str, Any] = field(default_factory=dict)
    skills: list[TemplateSkill] = field(default_factory=list)
    workflow_dsl: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)  # 变量定义
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "manifest": self.manifest.__dict__ if self.manifest else None,
            "config": self.config,
            "skills": [s.__dict__ for s in self.skills],
            "workflow_dsl": self.workflow_dsl,
            "variables": self.variables,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentTemplate:
        """从字典反序列化"""
        manifest_data = data.get("manifest")
        manifest = None
        if manifest_data:
            manifest = TemplateManifest(
                name=manifest_data.get("name", ""),
                display_name=manifest_data.get("display_name", ""),
                description=manifest_data.get("description", ""),
                category=TemplateCategory(manifest_data.get("category", "general")),
                version=manifest_data.get("version", "1.0.0"),
                author=manifest_data.get("author", ""),
                tags=manifest_data.get("tags", []),
                icon=manifest_data.get("icon", ""),
                visibility=TemplateVisibility(manifest_data.get("visibility", "public")),
                status=TemplateStatus(manifest_data.get("status", "published")),
                min_platform_version=manifest_data.get("min_platform_version", "1.0.0"),
                dependencies=manifest_data.get("dependencies", []),
                created_at=manifest_data.get("created_at", time.time()),
                updated_at=manifest_data.get("updated_at", time.time()),
                download_count=manifest_data.get("download_count", 0),
                rating=manifest_data.get("rating", 0.0),
                rating_count=manifest_data.get("rating_count", 0),
            )

        skills = [
            TemplateSkill(
                name=s.get("name", ""),
                description=s.get("description", ""),
                tool_ids=s.get("tool_ids", []),
                prompt_template=s.get("prompt_template", ""),
                config=s.get("config", {}),
            )
            for s in data.get("skills", [])
        ]

        return cls(
            id=data.get("id", _uuid.uuid4().hex[:12]),
            manifest=manifest,
            config=data.get("config", {}),
            skills=skills,
            workflow_dsl=data.get("workflow_dsl", {}),
            variables=data.get("variables", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


# ── 模板存储 ──


class TemplateStore:
    """模板存储(内存 + 可选 SQLite 持久化)

    用法:
        store = TemplateStore()
        store.save(template)
        template = store.get(template_id)
        all_templates = store.list()
    """

    def __init__(self, persistence_path: str = "") -> None:
        self._templates: dict[str, AgentTemplate] = {}
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self.logger = structlog.get_logger(__name__).bind(component="TemplateStore")

        if self._persistence_path:
            self._load_from_disk()

    def save(self, template: AgentTemplate) -> None:
        """保存模板(新增或更新)"""
        template.updated_at = time.time()
        self._templates[template.id] = template
        self._persist()
        self.logger.info(
            "template_saved",
            template_id=template.id,
            name=template.manifest.name if template.manifest else "",
        )

    def get(self, template_id: str) -> AgentTemplate | None:
        """获取模板"""
        return self._templates.get(template_id)

    def delete(self, template_id: str) -> bool:
        """删除模板"""
        removed = self._templates.pop(template_id, None)
        if removed:
            self._persist()
            self.logger.info("template_deleted", template_id=template_id)
        return removed is not None

    @staticmethod
    def _filter_by_category(templates: list[AgentTemplate], category: TemplateCategory) -> list[AgentTemplate]:
        """按分类过滤"""
        return [t for t in templates if t.manifest and t.manifest.category == category]

    @staticmethod
    def _filter_by_visibility(templates: list[AgentTemplate], visibility: TemplateVisibility) -> list[AgentTemplate]:
        """按可见性过滤"""
        return [t for t in templates if t.manifest and t.manifest.visibility == visibility]

    @staticmethod
    def _filter_by_status(templates: list[AgentTemplate], status: TemplateStatus) -> list[AgentTemplate]:
        """按状态过滤"""
        return [t for t in templates if t.manifest and t.manifest.status == status]

    @staticmethod
    def _filter_by_tag(templates: list[AgentTemplate], tag: str) -> list[AgentTemplate]:
        """按标签过滤"""
        return [t for t in templates if t.manifest and tag in t.manifest.tags]

    @staticmethod
    def _filter_by_query(templates: list[AgentTemplate], query: str) -> list[AgentTemplate]:
        """按搜索词过滤（匹配 name / display_name / description）"""
        q = query.lower()
        return [
            t
            for t in templates
            if t.manifest
            and (
                q in t.manifest.name.lower()
                or q in t.manifest.display_name.lower()
                or q in t.manifest.description.lower()
            )
        ]

    def list(
        self,
        category: TemplateCategory | None = None,
        visibility: TemplateVisibility | None = None,
        status: TemplateStatus | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[AgentTemplate]:
        """列出模板(支持过滤)"""
        result = list(self._templates.values())

        # 过滤分发表: (参数值, 过滤函数)
        filters = [
            (category, self._filter_by_category),
            (visibility, self._filter_by_visibility),
            (status, self._filter_by_status),
            (tag, self._filter_by_tag),
            (query, self._filter_by_query),
        ]
        for param, filter_fn in filters:
            if param:
                result = filter_fn(result, param)

        return result

    def exists(self, template_id: str) -> bool:
        return template_id in self._templates

    @property
    def size(self) -> int:
        return len(self._templates)

    def _persist(self) -> None:
        """持久化到磁盘"""
        if not self._persistence_path:
            return
        try:
            data = {tid: t.to_dict() for tid, t in self._templates.items()}
            self._persistence_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.error("template_persist_failed", error=str(e))

    def _load_from_disk(self) -> None:
        """从磁盘加载"""
        if not self._persistence_path or not self._persistence_path.exists():
            return
        try:
            data = json.loads(self._persistence_path.read_text(encoding="utf-8"))
            for tid, tdata in data.items():
                self._templates[tid] = AgentTemplate.from_dict(tdata)
            self.logger.info("templates_loaded_from_disk", count=len(self._templates))
        except Exception as e:
            self.logger.error("template_load_failed", error=str(e))


# ── 全局单例 ──

_global_store: TemplateStore | None = None


def get_template_store() -> TemplateStore:
    """获取全局模板存储单例"""
    global _global_store
    if _global_store is None:
        _global_store = TemplateStore(persistence_path="data/agent_templates.json")
    return _global_store


def set_template_store(store: TemplateStore) -> None:
    """设置全局模板存储(用于测试)"""
    global _global_store
    _global_store = store
