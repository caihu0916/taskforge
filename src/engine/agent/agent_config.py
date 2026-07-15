
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""No-Code Agent 配置向导 — 后端配置模型 + CRUD 服务

提供:
  - AgentConfig: 可序列化的 Agent 配置模型
  - AgentConfigService: 角色配置 CRUD + 过滤 + 概览

设计: 配置覆盖层在内存中, 不影响原始 RoleDefinition。
     update() 创建覆盖副本, 原始定义始终不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.engine.agent._base import AgentRole

logger = structlog.get_logger(__name__)


@dataclass
class AgentConfig:
    """Agent 配置 — 前端可编辑的角色参数"""

    role: str
    name_cn: str
    name_en: str = ""
    emoji: str = ""
    priority: int = 1
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)
    system_prompt: str = ""

    @classmethod
    def from_role_definition(cls, rd: Any) -> AgentConfig:
        """从 RoleDefinition 创建 AgentConfig"""
        return cls(
            role=rd.role.value if hasattr(rd.role, "value") else str(rd.role),
            name_cn=rd.name_cn,
            name_en=rd.name_en,
            emoji=rd.emoji,
            priority=rd.priority,
            capabilities=[c.value for c in rd.capabilities],
            system_prompt=rd.system_prompt_template,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "emoji": self.emoji,
            "priority": self.priority,
            "enabled": self.enabled,
            "capabilities": self.capabilities,
            "system_prompt": self.system_prompt,
        }


class AgentConfigService:
    """Agent 配置 CRUD 服务 — 基于现有 RoleDefinition 体系"""

    def __init__(self) -> None:
        self._overrides: dict[str, dict[str, Any]] = {}
        self._load_overrides_from_db()

    def _get_cm(self):
        """获取 ConnectionManager — 统一走连接池/WAL/外键配置，避免直连 SQLite 路径漂移"""
        from src.infra.database.connection import get_connection_manager

        return get_connection_manager()

    def _load_overrides_from_db(self) -> None:
        import json

        try:
            cm = self._get_cm()
            with cm.get_conn() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS agent_config_overrides "
                    "(role TEXT PRIMARY KEY, overrides TEXT NOT NULL, "
                    "updated_at TEXT DEFAULT (datetime('now')))"
                )
                rows = conn.execute("SELECT role, overrides FROM agent_config_overrides").fetchall()
            for row in rows or []:
                role = row[0] if not isinstance(row, dict) else row["role"]
                overrides_json = row[1] if not isinstance(row, dict) else row["overrides"]
                self._overrides[role] = json.loads(overrides_json)
        except Exception as e:
            logger.warning("agent_config_load_failed", error=str(e))

    def _save_override_to_db(self, role: str, overrides: dict) -> None:
        import json

        cm = self._get_cm()
        with cm.get_conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_config_overrides "
                "(role TEXT PRIMARY KEY, overrides TEXT NOT NULL, "
                "updated_at TEXT DEFAULT (datetime('now')))"
            )
            conn.execute(
                "INSERT OR REPLACE INTO agent_config_overrides (role, overrides) VALUES (?, ?)",
                (role, json.dumps(overrides, ensure_ascii=False)),
            )

    def list_all(
        self,
        min_priority: int = 0,
        capability: str = "",
    ) -> list[AgentConfig]:
        """列出所有 Agent 配置 (内置 + 自定义), 支持过滤"""
        from src.engine.agent._role_definitions import ROLE_DEFINITIONS

        result = []
        built_in_roles = set()
        for rd in ROLE_DEFINITIONS.values():
            config = AgentConfig.from_role_definition(rd)
            built_in_roles.add(config.role)
            # 应用覆盖
            role_str = config.role
            if role_str in self._overrides:
                ov = self._overrides[role_str]
                for k, v in ov.items():
                    if hasattr(config, k):
                        setattr(config, k, v)
            # 过滤
            if config.priority < min_priority:
                continue
            if capability and not any(capability in c for c in config.capabilities):
                continue
            result.append(config)

        # 追加自定义角色 (不在 ROLE_DEFINITIONS 中的 override)
        for role, ov in self._overrides.items():
            if role in built_in_roles:
                continue
            try:
                config = AgentConfig(**ov)
            except Exception as exc:
                logger.debug("exception_handled", error=str(exc))
                continue
            if config.priority < min_priority:
                continue
            if capability and not any(capability in c for c in config.capabilities):
                continue
            result.append(config)

        result.sort(key=lambda c: (-c.priority, c.role))
        return result

    def get(self, role: str) -> AgentConfig | None:
        """获取单个角色配置 (内置 + 自定义)"""
        # 1. 自定义角色: 直接从 override 层取
        if self._is_custom_role(role):
            if role in self._overrides:
                return AgentConfig(**self._overrides[role])
            return None

        # 2. 内置角色: 从 ROLE_DEFINITIONS 取 + 应用覆盖
        try:
            role_enum = AgentRole(role)
        except ValueError:
            return None
        from src.engine.agent._role_definitions import ROLE_DEFINITIONS

        rd = ROLE_DEFINITIONS.get(role_enum)
        if rd is None:
            return None
        config = AgentConfig.from_role_definition(rd)
        if role in self._overrides:
            ov = self._overrides[role]
            for k, v in ov.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        return config

    def update(self, role: str, updates: dict[str, Any]) -> AgentConfig | None:
        """更新角色配置 (覆盖层, 不影响原始定义)"""
        existing = self.get(role)
        if existing is None:
            return None
        # 存到覆盖层
        if role not in self._overrides:
            self._overrides[role] = {}
        for k, v in updates.items():
            if hasattr(existing, k):
                self._overrides[role][k] = v
                setattr(existing, k, v)
        self._save_override_to_db(role, self._overrides[role])
        logger.info("agent_config_updated", role=role, updates=list(updates.keys()))
        return existing

    def create(self, config: AgentConfig) -> AgentConfig:
        """创建自定义 Agent 角色 (覆盖层, 不影响 ROLE_DEFINITIONS)

        自定义角色 role 不在 AgentRole 枚举中, 通过 override 表持久化。
        """
        if config.role in self._overrides and not self._is_custom_role(config.role):
            raise ValueError(f"内置角色 {config.role} 不可创建, 请使用 update() 修改配置")

        overrides = config.to_dict()
        self._overrides[config.role] = overrides
        self._save_override_to_db(config.role, overrides)
        logger.info("agent_config_created", role=config.role, name_cn=config.name_cn)
        return config

    def delete(self, role: str) -> bool:
        """删除角色配置覆盖

        - 内置角色: 仅删除 override 恢复默认
        - 自定义角色: 彻底删除
        返回 True 表示成功删除, False 表示角色不存在
        """
        is_custom = self._is_custom_role(role)

        if not is_custom and role not in self._overrides:
            # 内置角色无覆盖, 不需要删除
            return False
        if is_custom and role not in self._overrides:
            return False

        del self._overrides[role]
        self._delete_override_from_db(role)
        logger.info("agent_config_deleted", role=role, is_custom=is_custom)
        return True

    def _is_custom_role(self, role: str) -> bool:
        """判断是否为自定义角色 (不在 AgentRole 枚举中)"""
        try:
            AgentRole(role)
            return False
        except ValueError:
            return True

    def _delete_override_from_db(self, role: str) -> None:
        with self._get_cm().get_conn() as conn:
            conn.execute("DELETE FROM agent_config_overrides WHERE role = ?", (role,))

    def get_summary(self) -> dict[str, Any]:
        """角色配置概览"""
        all_configs = self.list_all()
        enabled = [c for c in all_configs if c.enabled]
        priorities = [c.priority for c in all_configs]
        avg_priority = round(sum(priorities) / len(priorities), 1) if priorities else 0

        roles_by_capability: dict[str, list[str]] = {}
        for c in all_configs:
            for cap in c.capabilities:
                if cap not in roles_by_capability:
                    roles_by_capability[cap] = []
                roles_by_capability[cap].append(c.role)

        return {
            "total_roles": len(all_configs),
            "enabled_roles": len(enabled),
            "avg_priority": avg_priority,
            "roles_by_capability": roles_by_capability,
            "code_corps_roles": [
                c.role
                for c in all_configs
                if c.role in ("architect", "code_auditor", "backend_dev", "frontend_dev", "tech_writer")
            ],
        }
