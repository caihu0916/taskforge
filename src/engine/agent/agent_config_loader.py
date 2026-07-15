
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill-Gap 2-2: Agent 角色配置动态加载

增强点：
1. 多源加载：内置 + DB + 文件系统（YAML/JSON）
2. 热重载：文件变更时自动刷新
3. 配置校验：加载时验证配置完整性
4. 配置合并：按优先级合并多源配置
5. 文件监听：支持 watch 模式
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from src.engine.agent.agent_config import AgentConfig
from src.exceptions import ErrorCode, TaskForgeError

logger = structlog.get_logger(__name__)


class ConfigValidationError(TaskForgeError):
    default_code = ErrorCode.CFG_VALIDATION_FAILED
    """配置校验错误"""


@dataclass
class ConfigSource:
    """配置源信息"""

    name: str
    type: str  # builtin | db | file
    path: str = ""
    priority: int = 0  # 越大优先级越高
    last_loaded: float = 0.0
    config_count: int = 0


@dataclass
class LoadResult:
    """加载结果"""

    success: bool
    configs: list[AgentConfig] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "source": self.source,
            "config_count": len(self.configs),
            "errors": self.errors,
        }


class ConfigValidator:
    """配置校验器"""

    REQUIRED_FIELDS = {"role", "name_cn"}
    OPTIONAL_FIELDS = {"name_en", "emoji", "priority", "enabled", "capabilities", "system_prompt"}

    @classmethod
    def validate(cls, config_dict: dict[str, Any]) -> list[str]:
        """校验配置字典，返回错误列表（空列表表示通过）"""
        errors: list[str] = []
        errors.extend(cls._check_required_fields(config_dict))
        errors.extend(cls._check_field_types(config_dict))
        errors.extend(cls._check_role_format(config_dict))
        return errors

    @classmethod
    def _check_required_fields(cls, config_dict: dict[str, Any]) -> list[str]:
        """检查必需字段：存在性 + 非空"""
        errors: list[str] = []
        for field_name in cls.REQUIRED_FIELDS:
            if field_name not in config_dict:
                errors.append(f"missing required field: {field_name}")
            elif not config_dict[field_name]:
                errors.append(f"empty value for required field: {field_name}")
        return errors

    @classmethod
    def _check_field_types(cls, config_dict: dict[str, Any]) -> list[str]:
        """检查字段类型：按字段分发到对应校验器"""
        errors: list[str] = []
        for field_name, checker in cls._FIELD_TYPE_CHECKERS.items():
            if field_name in config_dict:
                errors.extend(checker(config_dict))
        return errors

    @staticmethod
    def _check_role_type(config_dict: dict[str, Any]) -> list[str]:
        if not isinstance(config_dict["role"], str):
            return ["field 'role' must be string"]
        return []

    @staticmethod
    def _check_name_cn_type(config_dict: dict[str, Any]) -> list[str]:
        if not isinstance(config_dict["name_cn"], str):
            return ["field 'name_cn' must be string"]
        return []

    @staticmethod
    def _check_priority_type(config_dict: dict[str, Any]) -> list[str]:
        priority = config_dict["priority"]
        if not isinstance(priority, int):
            return ["field 'priority' must be integer"]
        if priority < 0 or priority > 100:
            return ["field 'priority' must be between 0 and 100"]
        return []

    @staticmethod
    def _check_enabled_type(config_dict: dict[str, Any]) -> list[str]:
        if not isinstance(config_dict["enabled"], bool):
            return ["field 'enabled' must be boolean"]
        return []

    @staticmethod
    def _check_capabilities_type(config_dict: dict[str, Any]) -> list[str]:
        capabilities = config_dict["capabilities"]
        if not isinstance(capabilities, list):
            return ["field 'capabilities' must be list"]
        if not all(isinstance(c, str) for c in capabilities):
            return ["all capabilities must be strings"]
        return []

    @staticmethod
    def _check_system_prompt_type(config_dict: dict[str, Any]) -> list[str]:
        if not isinstance(config_dict["system_prompt"], str):
            return ["field 'system_prompt' must be string"]
        return []

    @classmethod
    def _check_role_format(cls, config_dict: dict[str, Any]) -> list[str]:
        """检查 role 格式（只允许小写字母、数字、下划线）"""
        role = config_dict.get("role")
        if not isinstance(role, str):
            return []
        if not all(c.islower() or c.isdigit() or c == "_" for c in role):
            return [f"role '{role}' contains invalid characters (only lowercase/digit/_ allowed)"]
        return []

    # 字段类型校验分发表
    _FIELD_TYPE_CHECKERS = {
        "role": _check_role_type,
        "name_cn": _check_name_cn_type,
        "priority": _check_priority_type,
        "enabled": _check_enabled_type,
        "capabilities": _check_capabilities_type,
        "system_prompt": _check_system_prompt_type,
    }


class FileConfigLoader:
    """文件系统配置加载器

    支持格式：
    - YAML (.yaml, .yml)
    - JSON (.json)

    目录结构：
    - 单文件：直接包含一个配置
    - 多文件目录：每个文件包含一个或多个配置
    """

    SUPPORTED_EXTENSIONS = {".yaml", ".yml", ".json"}

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self._last_modified: dict[str, float] = {}

    def load_all(self) -> LoadResult:
        """加载目录下所有配置文件"""
        if not self.base_dir.exists():
            return LoadResult(success=True, source=f"file:{self.base_dir}")

        configs: list[AgentConfig] = []
        errors: list[str] = []

        for file_path in self._find_config_files():
            try:
                file_configs = self.load_file(file_path)
                configs.extend(file_configs)
                self._last_modified[str(file_path)] = file_path.stat().st_mtime
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                errors.append(f"{file_path}: {e}")
                logger.warning("config_file_load_failed", file=str(file_path), error=str(e))

        return LoadResult(
            success=len(errors) == 0,
            configs=configs,
            errors=errors,
            source=f"file:{self.base_dir}",
        )

    def load_file(self, file_path: Path) -> list[AgentConfig]:
        """加载单个配置文件"""
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix}")

        content = file_path.read_text(encoding="utf-8")

        data = yaml.safe_load(content) if suffix in {".yaml", ".yml"} else json.loads(content)

        if data is None:
            return []

        # 支持两种格式：
        # 1. 单个配置 dict
        # 2. 配置列表 {"agents": [...]} 或 [...]
        if isinstance(data, dict):
            config_dicts = data["agents"] if "agents" in data and isinstance(data["agents"], list) else [data]
        elif isinstance(data, list):
            config_dicts = data
        else:
            raise ValueError(f"Invalid config format in {file_path}")

        configs: list[AgentConfig] = []
        for i, config_dict in enumerate(config_dicts):
            if not isinstance(config_dict, dict):
                errors_msg = f"config #{i} in {file_path} is not a dict"
                raise ValueError(errors_msg)

            # 校验
            validation_errors = ConfigValidator.validate(config_dict)
            if validation_errors:
                raise ValueError(f"config #{i} validation failed: {', '.join(validation_errors)}")

            configs.append(AgentConfig(**config_dict))

        return configs

    def _find_config_files(self) -> list[Path]:
        """查找所有配置文件"""
        files: list[Path] = []
        if self.base_dir.is_file():
            if self.base_dir.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                files.append(self.base_dir)
        else:
            for ext in self.SUPPORTED_EXTENSIONS:
                files.extend(self.base_dir.rglob(f"*{ext}"))
        return sorted(files)

    def has_changes(self) -> bool:
        """检查文件是否有变更"""
        current_files = {str(p) for p in self._find_config_files()}

        # 新增文件
        if current_files - set(self._last_modified.keys()):
            return True

        # 删除文件
        if set(self._last_modified.keys()) - current_files:
            return True

        # 修改文件
        for file_path in self._find_config_files():
            path_str = str(file_path)
            if path_str in self._last_modified:
                current_mtime = file_path.stat().st_mtime
                if current_mtime != self._last_modified[path_str]:
                    return True

        return False


class DynamicConfigLoader:
    """动态配置加载器

    多源加载 + 热重载 + 配置合并

    优先级（从低到高）：
    1. 内置 ROLE_DEFINITIONS
    2. 文件系统配置
    3. DB 覆盖
    """

    def __init__(
        self,
        file_config_dir: str | Path | None = None,
        enable_watch: bool = False,
        watch_interval: float = 30.0,
    ) -> None:
        self._file_loader: FileConfigLoader | None = None
        if file_config_dir:
            self._file_loader = FileConfigLoader(file_config_dir)

        self._enable_watch = enable_watch
        self._watch_interval = watch_interval
        self._watch_thread: threading.Thread | None = None
        self._watch_running = False
        self._callbacks: list = []

        self._sources: dict[str, ConfigSource] = {}
        self._cached_configs: dict[str, AgentConfig] = {}
        self._last_refresh: float = 0.0
        self._lock = threading.RLock()

        # 注册内置源
        self._sources["builtin"] = ConfigSource(
            name="builtin",
            type="builtin",
            priority=10,
        )

        if self._file_loader:
            self._sources["file"] = ConfigSource(
                name="file",
                type="file",
                path=str(self._file_loader.base_dir),
                priority=20,
            )

        self._sources["db"] = ConfigSource(
            name="db",
            type="db",
            priority=30,
        )

    def load_all(self) -> LoadResult:
        """从所有源加载配置并合并"""
        with self._lock:
            all_configs: dict[str, AgentConfig] = {}
            all_errors: list[str] = []

            # 1. 内置配置（优先级最低）
            try:
                builtin_configs = self._load_builtin()
                for config in builtin_configs:
                    all_configs[config.role] = config
                self._sources["builtin"].last_loaded = time.time()
                self._sources["builtin"].config_count = len(builtin_configs)
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                all_errors.append(f"builtin: {e}")
                logger.warning("builtin_load_failed", error=str(e))

            # 2. 文件配置（覆盖内置）
            if self._file_loader:
                try:
                    file_result = self._file_loader.load_all()
                    for config in file_result.configs:
                        all_configs[config.role] = config
                    all_errors.extend(file_result.errors)
                    self._sources["file"].last_loaded = time.time()
                    self._sources["file"].config_count = len(file_result.configs)
                except Exception as e:
                    logger.debug("exception_handled", error=str(e))
                    all_errors.append(f"file: {e}")
                    logger.warning("file_load_failed", error=str(e))

            # 3. DB 覆盖（优先级最高）
            try:
                db_configs = self._load_db_overrides()
                for config in db_configs:
                    all_configs[config.role] = config
                self._sources["db"].last_loaded = time.time()
                self._sources["db"].config_count = len(db_configs)
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                all_errors.append(f"db: {e}")
                logger.warning("db_load_failed", error=str(e))

            self._cached_configs = all_configs
            self._last_refresh = time.time()

            return LoadResult(
                success=len(all_errors) == 0,
                configs=list(all_configs.values()),
                errors=all_errors,
                source="dynamic_loader",
            )

    def _load_builtin(self) -> list[AgentConfig]:
        """加载内置角色定义"""
        from src.engine.agent._role_definitions import ROLE_DEFINITIONS

        return [AgentConfig.from_role_definition(rd) for rd in ROLE_DEFINITIONS.values()]

    def _load_db_overrides(self) -> list[AgentConfig]:
        """加载 DB 覆盖"""
        from src.engine.agent.agent_config import AgentConfigService

        service = AgentConfigService()
        return service.list_all()

    def get(self, role: str) -> AgentConfig | None:
        """获取单个角色配置（使用缓存）"""
        with self._lock:
            if not self._cached_configs:
                self.load_all()
            return self._cached_configs.get(role)

    def list_all(self) -> list[AgentConfig]:
        """列出所有配置（使用缓存）"""
        with self._lock:
            if not self._cached_configs:
                self.load_all()
            return list(self._cached_configs.values())

    def refresh(self) -> LoadResult:
        """强制刷新配置"""
        return self.load_all()

    def has_changes(self) -> bool:
        """检查是否有配置变更"""
        return bool(self._file_loader and self._file_loader.has_changes())

    def start_watch(self) -> None:
        """启动文件监听"""
        if self._watch_running:
            return
        if not self._file_loader:
            logger.warning("watch_requires_file_loader")
            return

        self._watch_running = True
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("config_watch_started", interval=self._watch_interval)

    def stop_watch(self) -> None:
        """停止文件监听"""
        self._watch_running = False
        if self._watch_thread:
            self._watch_thread.join(timeout=5.0)
            self._watch_thread = None
        logger.info("config_watch_stopped")

    def _watch_loop(self) -> None:
        """监听循环"""
        while self._watch_running:
            try:
                if self.has_changes():
                    logger.info("config_changes_detected")
                    result = self.load_all()
                    if result.success:
                        logger.info("config_reloaded", config_count=len(result.configs))
                        self._notify_callbacks(result)
                    else:
                        logger.warning("config_reload_failed", errors=result.errors)
            except Exception as e:
                logger.error("watch_loop_error", error=str(e), exc_info=True)

            time.sleep(self._watch_interval)

    def add_callback(self, callback) -> None:
        """添加配置变更回调"""
        self._callbacks.append(callback)

    def remove_callback(self, callback) -> None:
        """移除配置变更回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self, result: LoadResult) -> None:
        """通知所有回调"""
        for callback in self._callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.warning("callback_failed", error=str(e), exc_info=True)

    def get_sources_info(self) -> list[dict[str, Any]]:
        """获取所有配置源信息"""
        result = []
        for source in self._sources.values():
            result.append(
                {
                    "name": source.name,
                    "type": source.type,
                    "path": source.path,
                    "priority": source.priority,
                    "last_loaded": source.last_loaded,
                    "config_count": source.config_count,
                }
            )
        return result

    def export_to_file(self, file_path: str | Path, format: str = "yaml") -> bool:
        """导出当前配置到文件"""
        try:
            configs = self.list_all()
            data = {"agents": [c.to_dict() for c in configs]}

            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if format.lower() in {"yaml", "yml"}:
                content = yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
            else:  # json
                content = json.dumps(data, ensure_ascii=False, indent=2)

            file_path.write_text(content, encoding="utf-8")
            logger.info("config_exported", file=str(file_path), format=format)
            return True
        except Exception as e:
            logger.error("config_export_failed", error=str(e), exc_info=True)
            return False


# 全局单例
_dynamic_loader: DynamicConfigLoader | None = None


def get_dynamic_loader() -> DynamicConfigLoader:
    """获取全局动态加载器"""
    global _dynamic_loader
    if _dynamic_loader is None:
        # 默认配置目录
        import os

        config_dir = os.environ.get(
            "TASKFORGE_AGENT_CONFIG_DIR",
            os.path.join(os.getcwd(), "data", "agent_configs"),
        )
        _dynamic_loader = DynamicConfigLoader(file_config_dir=config_dir)
    return _dynamic_loader


def reset_dynamic_loader() -> None:
    """重置全局动态加载器"""
    global _dynamic_loader
    if _dynamic_loader:
        _dynamic_loader.stop_watch()
    _dynamic_loader = None
