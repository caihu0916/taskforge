
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""模板安装引擎(P1-S1-019)

负责 Agent 模板的安装、升级、卸载:
  - 安装前校验(依赖、版本、配置)
  - 安装执行(复制配置、注册技能、初始化工作流)
  - 安装后验证(完整性检查)
  - 失败回滚(原子操作)
  - 升级迁移(版本兼容性处理)

设计原则:
  - 原子性: 安装要么全部成功,要么全部回滚
  - 可追溯: 记录安装日志和变更
  - 幂等: 重复安装同一模板不会产生副作用
"""

from __future__ import annotations

import time
import uuid as _uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from src.engine.agent.agent_template import (
    AgentTemplate,
    TemplateStatus,
    TemplateStore,
    get_template_store,
)

logger = structlog.get_logger(__name__)


# ── 枚举 ──


class InstallStatus(StrEnum):
    """安装状态"""

    PENDING = "pending"  # 待安装
    VALIDATING = "validating"  # 校验中
    INSTALLING = "installing"  # 安装中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    ROLLED_BACK = "rolled_back"  # 已回滚


class InstallError(StrEnum):
    """安装错误类型"""

    DEPENDENCY_MISSING = "dependency_missing"  # 依赖缺失
    VERSION_INCOMPATIBLE = "version_incompatible"  # 版本不兼容
    CONFIG_INVALID = "config_invalid"  # 配置无效
    SKILL_CONFLICT = "skill_conflict"  # 技能冲突
    UNKNOWN = "unknown"  # 未知错误


# ── 数据模型 ──


@dataclass
class InstallRecord:
    """安装记录"""

    install_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:12])
    template_id: str = ""
    template_version: str = ""
    status: InstallStatus = InstallStatus.PENDING
    error_type: str = ""
    error_message: str = ""
    installed_at: float = 0.0
    rolled_back_at: float = 0.0
    changes: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_id": self.install_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "status": self.status.value,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "installed_at": self.installed_at,
            "rolled_back_at": self.rolled_back_at,
            "changes": self.changes,
            "metadata": self.metadata,
        }


# ── 安装引擎 ──


class TemplateInstaller:
    """模板安装引擎

    用法:
        installer = TemplateInstaller()
        record = installer.install(template)
        if record.status == InstallStatus.COMPLETED:
            logger.info("template_installed", template_id=template.id)
        else:
            logger.error("template_install_failed", error=record.error_message)
    """

    def __init__(self, store: TemplateStore | None = None) -> None:
        self._store = store or get_template_store()
        self._install_records: dict[str, InstallRecord] = {}
        self.logger = structlog.get_logger(__name__).bind(component="TemplateInstaller")

    def install(self, template: AgentTemplate) -> InstallRecord:
        """安装模板(原子操作)

        步骤:
          1. 校验(依赖、版本、配置)
          2. 安装(保存到存储)
          3. 验证(完整性检查)
          4. 失败则回滚

        Returns:
            InstallRecord: 安装记录
        """
        record = InstallRecord(
            template_id=template.id,
            template_version=template.manifest.version if template.manifest else "1.0.0",
        )
        self._install_records[record.install_id] = record

        try:
            # 1. 校验
            record.status = InstallStatus.VALIDATING
            validation_error = self._validate(template)
            if validation_error:
                record.status = InstallStatus.FAILED
                record.error_type, record.error_message = validation_error
                self.logger.warning(
                    "install_validation_failed",
                    template_id=template.id,
                    error=record.error_message,
                )
                return record

            # 2. 安装
            record.status = InstallStatus.INSTALLING
            self._do_install(template, record)

            # 3. 验证
            verify_error = self._verify(template)
            if verify_error:
                # 验证失败,回滚
                self._rollback(record)
                record.status = InstallStatus.FAILED
                record.error_type, record.error_message = verify_error
                return record

            # 4. 完成
            record.status = InstallStatus.COMPLETED
            record.installed_at = time.time()
            self.logger.info(
                "install_completed",
                template_id=template.id,
                install_id=record.install_id,
            )
            return record

        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            # 异常,回滚
            self._rollback(record)
            record.status = InstallStatus.FAILED
            record.error_type = InstallError.UNKNOWN
            record.error_message = f"{type(e).__name__}: {e}"
            self.logger.error(
                "install_exception",
                template_id=template.id,
                error=str(e),
                exc_info=True,
            )
            return record

    def uninstall(self, template_id: str) -> bool:
        """卸载模板"""
        template = self._store.get(template_id)
        if not template:
            return False

        success = self._store.delete(template_id)
        if success:
            self.logger.info("uninstall_completed", template_id=template_id)
        return success

    def upgrade(self, template_id: str, new_template: AgentTemplate) -> InstallRecord:
        """升级模板

        1. 卸载旧版本
        2. 安装新版本
        """
        old = self._store.get(template_id)
        if not old:
            return self.install(new_template)

        # 卸载旧版本
        self._store.delete(template_id)

        # 安装新版本
        record = self.install(new_template)
        if record.status == InstallStatus.FAILED:
            # 升级失败,恢复旧版本
            self._store.save(old)
            self.logger.warning(
                "upgrade_failed_rolled_back",
                template_id=template_id,
            )
        return record

    def get_install_record(self, install_id: str) -> InstallRecord | None:
        """获取安装记录"""
        return self._install_records.get(install_id)

    def list_install_records(self, template_id: str | None = None) -> list[InstallRecord]:
        """列出安装记录"""
        records = list(self._install_records.values())
        if template_id:
            records = [r for r in records if r.template_id == template_id]
        return records

    # ── 内部方法 ──

    def _validate(self, template: AgentTemplate) -> tuple[str, str] | None:
        """校验模板

        Returns:
            None=通过, (error_type, message)=失败
        """
        if not template.manifest:
            return InstallError.CONFIG_INVALID, "Missing manifest"

        if not template.manifest.name:
            return InstallError.CONFIG_INVALID, "Missing manifest.name"

        # 检查依赖
        for dep_id in template.manifest.dependencies:
            if not self._store.exists(dep_id):
                return (
                    InstallError.DEPENDENCY_MISSING,
                    f"Missing dependency: {dep_id}",
                )

        # 检查技能冲突
        existing = self._store.get(template.id)
        if existing:
            existing_skills = {s.name for s in existing.skills}
            new_skills = {s.name for s in template.skills}
            # 允许覆盖同名技能(升级场景),但记录变更
            if existing_skills & new_skills:
                self.logger.info(
                    "skill_overlap_detected",
                    template_id=template.id,
                    overlap=list(existing_skills & new_skills),
                )

        return None

    def _do_install(self, template: AgentTemplate, record: InstallRecord) -> None:
        """执行安装"""
        # 标记为已安装状态
        if template.manifest:
            template.manifest.status = TemplateStatus.INSTALLED
            template.manifest.download_count += 1

        # 保存到存储
        self._store.save(template)

        # 记录变更
        record.changes.append(
            {
                "action": "save_template",
                "template_id": template.id,
                "timestamp": time.time(),
            }
        )

        # 记录技能注册
        for skill in template.skills:
            record.changes.append(
                {
                    "action": "register_skill",
                    "skill_name": skill.name,
                    "tool_ids": skill.tool_ids,
                    "timestamp": time.time(),
                }
            )

    def _verify(self, template: AgentTemplate) -> tuple[str, str] | None:
        """验证安装完整性"""
        installed = self._store.get(template.id)
        if not installed:
            return InstallError.UNKNOWN, "Template not found after install"

        if not installed.manifest:
            return InstallError.CONFIG_INVALID, "Manifest missing after install"

        if installed.manifest.status != TemplateStatus.INSTALLED:
            return InstallError.CONFIG_INVALID, "Status not marked as installed"

        return None

    def _rollback(self, record: InstallRecord) -> None:
        """回滚安装"""
        self.logger.info(
            "install_rolling_back",
            install_id=record.install_id,
            template_id=record.template_id,
        )

        # 逆序撤销变更
        for change in reversed(record.changes):
            try:
                if change["action"] == "save_template":
                    self._store.delete(change["template_id"])
            except Exception as e:
                self.logger.error(
                    "rollback_step_failed",
                    change=change,
                    error=str(e),
                )

        record.rolled_back_at = time.time()
        record.status = InstallStatus.ROLLED_BACK
