
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Hard Limits 执行引擎 — Fable 5 模式 C 落地

Fable 5 的 copyright_style_hard_limits 机制：用精确数值边界替代模糊规则，
让"¥500自批""禁止批量脚本修改"从 prompt 文本变成运行时可执行、可审计的硬限制。

关键设计:
- 所有阈值从 hard_limits.yaml 加载（不硬编码）
- 超限后有 5 种执行动作: alert / warn / block / escalate / hard_stop
- 提供检查接口供 guardrails / risk_checks / context_builder 调用
- 兼容现有代码：risk_checks 仍然返回 dict，但阈值从本模块读取

集成点:
  - guardrails.py: 替代 MAX_REPEATS 等硬编码常量
  - risk_checks_*.py: 替代函数体内硬编码阈值
  - context_builder.py: 通过 _defs.py 注入角色限额
  - reminders.py: 触发规则可引用 hard_limits 的阈值

AGENT-016 安全策略:
  - 生产 hard_limits.yaml 应设只读 (chmod 0440 / Windows ACL)
  - 启动时校验期望 SHA256 — 防篡改
  - 未配置规则默认 deny (passed=False, action=BLOCK) — 安全策略
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import structlog

from src.exceptions import TaskForgeError

logger = structlog.get_logger(__name__)

YAML_PATH = Path(__file__).parent / "hard_limits.yaml"


class EnforcementAction(StrEnum):
    """超限执行动作"""

    ALERT = "alert"  # 仅告警，不阻断
    WARN = "warn"  # 警告，insert提示但允许继续
    BLOCK = "block"  # 阻止执行
    ESCALATE = "escalate"  # 升级给人类
    HARD_STOP = "hard_stop"  # 硬停止，中断整个流程


class HardLimitResult:
    """硬限制检查结果"""

    __slots__ = ("action", "category", "current", "limit", "message", "passed", "rule")

    def __init__(
        self,
        passed: bool,
        action: EnforcementAction,
        category: str,
        rule: str,
        current: Any = None,
        limit: Any = None,
        message: str = "",
    ):
        self.passed = passed
        self.action = action
        self.category = category
        self.rule = rule
        self.current = current
        self.limit = limit
        self.message = message

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:
        status = "PASS" if self.passed else f"FAIL({self.action.value})"
        return f"HardLimitResult({self.category}.{self.rule}: {status}, current={self.current}, limit={self.limit})"


class HardLimits:
    """硬限制引擎 — 从 YAML 加载阈值，提供检查接口

    用法:
        limits = HardLimits()
        result = limits.check("finance", "self_approve_max", 800)
        if not result:
            #result.action == EnforcementAction.BLOCK
            #result.message 包含告警信息
    """

    def __init__(self, yaml_path: Path | None = None):
        self._yaml_path: Path = yaml_path or YAML_PATH
        self._config: dict = {}
        self._enforcement: dict = {}
        self._load(self._yaml_path)

    def _load(self, path: Path) -> None:
        """加载 YAML 配置"""
        if not path.exists():
            logger.warning("hard_limits_yaml_not_found", path=str(path))
            return

        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("hard_limits_yaml_load_failed", path=str(path), exc_info=True)
            return

        # 分离阈值和执行动作
        for key in ("finance", "risk_thresholds", "agent_safety", "code_change", "publish"):
            if key in data:
                self._config[key] = data[key]

        self._enforcement = data.get("enforcement", {})
        logger.debug("hard_limits_loaded", categories=list(self._config.keys()))

    # ── 通用读取接口 ──

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """获取指定分类下的阈值

        Args:
            category: 分类名 (finance / agent_safety / code_change / publish)
            key: 阈值键名
            default: 找不到时的默认值
        """
        section = self._config.get(category, {})
        if isinstance(section, dict):
            return section.get(key, default)
        return default

    def get_risk(self, sub_category: str, key: str, default: Any = None) -> Any:
        """获取 risk_thresholds 下的子分类阈值

        Args:
            sub_category: invoice / fund / declare / audit
            key: 阈值键名
            default: 默认值
        """
        risks = self._config.get("risk_thresholds", {})
        section = risks.get(sub_category, {})
        if isinstance(section, dict):
            return section.get(key, default)
        return default

    # ── 检查接口 ──

    def check(
        self,
        category: str,
        rule: str,
        current_value: Any,
        operator: Literal["gt", "gte", "lt", "lte", "eq", "ne"] = "gt",
    ) -> HardLimitResult:
        """通用检查接口

        Args:
            category: 分类名
            rule: 规则键名
            current_value: 当前值
            operator: 比较方式
                gt: current > limit → FAIL
                gte: current >= limit → FAIL
                lt: current < limit → FAIL
                lte: current <= limit → FAIL
                eq: current == limit → FAIL
                ne: current != limit → FAIL

        Returns:
            HardLimitResult
        """
        limit = self.get(category, rule)
        if limit is None:
            # AGENT-016: 未配置规则默认 deny — 安全策略
            # 生产环境应显式配置所有规则; 未配置规则视为禁止, 防止遗漏导致越权
            return HardLimitResult(
                passed=False,
                action=EnforcementAction.BLOCK,
                category=category,
                rule=rule,
                current=current_value,
                limit=limit,
                message=f"[{category}.{rule}] 未配置阈值, 默认 deny (安全策略)",
            )

        # 比较
        failed = False
        if operator == "gt":
            failed = current_value > limit
        elif operator == "gte":
            failed = current_value >= limit
        elif operator == "lt":
            failed = current_value < limit
        elif operator == "lte":
            failed = current_value <= limit
        elif operator == "eq":
            failed = current_value == limit
        elif operator == "ne":
            failed = current_value != limit

        # 获取执行动作
        action = self._get_enforcement_action(category, rule)

        if not failed:
            return HardLimitResult(
                passed=True,
                action=action,
                category=category,
                rule=rule,
                current=current_value,
                limit=limit,
            )

        # 超限
        return HardLimitResult(
            passed=False,
            action=action,
            category=category,
            rule=rule,
            current=current_value,
            limit=limit,
            message=f"[{category}.{rule}] 当前值={current_value}, 限额={limit}, 动作={action.value}",
        )

    def check_finance_amount(self, rule: str, amount: float) -> HardLimitResult:
        """财务金额检查的快捷方法 — 更严格的默认检查"""
        return self.check("finance", rule, amount, operator="gt")

    def check_code_change(self, rule: str, value: Any, operator: str = "gt") -> HardLimitResult:
        """代码变更检查的快捷方法"""
        return self.check("code_change", rule, value, operator=operator)

    def check_agent_safety(self, rule: str, value: Any, operator: str = "gt") -> HardLimitResult:
        """Agent 安全检查的快捷方法"""
        return self.check("agent_safety", rule, value, operator=operator)

    # ── 执行动作 ──

    def _get_enforcement_action(self, category: str, rule: str) -> EnforcementAction:
        """从 enforcement 配置获取执行动作

        enforcement key 格式: over_{rule_key} 或直接 rule_key
        例: over_self_approve_max 对应 rule=self_approve_max
        """
        cat_enforcement = self._enforcement.get(category, {})

        # 优先精确匹配
        if rule in cat_enforcement:
            action_str = cat_enforcement[rule]
        # 其次前缀匹配: over_{rule}
        elif f"over_{rule}" in cat_enforcement:
            action_str = cat_enforcement[f"over_{rule}"]
        else:
            action_str = "alert"

        try:
            return EnforcementAction(action_str)
        except ValueError:
            return EnforcementAction.ALERT

    def should_block(self, result: HardLimitResult) -> bool:
        """判断结果是否需要阻断"""
        if result.passed:
            return False
        return result.action in (EnforcementAction.BLOCK, EnforcementAction.HARD_STOP)

    def should_escalate(self, result: HardLimitResult) -> bool:
        """判断结果是否需要升级人类"""
        if result.passed:
            return False
        return result.action == EnforcementAction.ESCALATE

    # ── AGENT-016: 完整性校验 (防篡改) ──

    def compute_sha256(self) -> str:
        """计算 YAML 文件的 SHA256 — 用于完整性校验

        Returns:
            64 字符 hex SHA256 摘要

        Raises:
            FileNotFoundError: YAML 文件不存在
        """
        if not self._yaml_path.exists():
            raise FileNotFoundError(f"hard_limits.yaml 不存在: {self._yaml_path}")
        raw = self._yaml_path.read_bytes()
        return hashlib.sha256(raw).hexdigest()

    def verify_integrity(self, expected_sha256: str) -> None:
        """校验 YAML 文件 SHA256 是否与期望值匹配 — 防篡改

        生产环境应在启动时调用此方法, 期望 SHA256 从可信源 (环境变量/ secrets) 读取。
        不匹配则抛 SecurityError, 拒绝启动。

        Args:
            expected_sha256: 期望的 64 字符 hex SHA256

        Raises:
            TaskForgeError: SHA256 不匹配 (文件被篡改) 或文件不存在
        """
        if not expected_sha256 or not isinstance(expected_sha256, str):
            raise TaskForgeError("hard_limits.yaml 期望 SHA256 为空 — 请配置 TF_HARD_LIMITS__EXPECTED_SHA256")
        try:
            actual = self.compute_sha256()
        except FileNotFoundError as e:
            raise TaskForgeError(f"hard_limits.yaml 不存在: {e}") from e
        # 恒定时间比较 — 防时序攻击
        import hmac as _hmac

        if not _hmac.compare_digest(actual, expected_sha256):
            raise TaskForgeError(
                "hard_limits.yaml SHA256 校验失败 — 文件可能被篡改",
                details={
                    "expected": expected_sha256,
                    "actual": actual,
                    "path": str(self._yaml_path),
                },
            )
        logger.debug("hard_limits_integrity_verified", path=str(self._yaml_path))

    # ── 注入 context_builder 的角色限额文本 ──

    def build_limits_prompt(self, role: str) -> str:
        """根据角色生成限额提示文本，注入 context_builder

        替代 _defs.py 中内嵌在 compact prompt 里的限额描述，
        让限额值从 YAML 读取而非硬编码。
        """
        parts: list[str] = []

        if role in ("boss", "accountant"):
            self_approve = self.get("finance", "self_approve_max", 500)
            parts.append(f"单笔自批上限¥{self_approve},超限提交审批")
            collection = self.get("finance", "collection_escalate", 10000)
            parts.append(f"催款超¥{collection}升掌柜")

        if role == "accountant":
            diff_investigate = self.get("finance", "difference_investigate", 50)
            parts.append(f"差异超¥{diff_investigate}必须调查")
            refund = self.get("finance", "refund_approve", 200)
            parts.append(f"退款超¥{refund}需审批")

        if role in ("developer", "frontend_dev", "butler"):
            max_changes = self.get("code_change", "max_changes_per_file", 1)
            require_verify = self.get("code_change", "require_backend_verify", True)
            parts.append(f"代码一次只改{max_changes}处,改完{'必须启动验证' if require_verify else '建议验证'}")
            batch_ban = self.get("code_change", "batch_script_ban", True)
            if batch_ban:
                parts.append("禁止批量脚本修改业务代码")

        if role == "butler":
            max_repeats = self.get("agent_safety", "max_repeats", 5)
            max_failures = self.get("agent_safety", "max_failures", 5)
            parts.append(f"重复{max_repeats}次或失败{max_failures}次必须上报用户")

        if not parts:
            return ""

        return "[硬限制] " + "; ".join(parts)

    # ── 运行时计数器（跟踪当前会话状态） ──

    def __init_session_state(self) -> None:
        """初始化会话级计数器（首次访问时调用）"""
        if not hasattr(self, "_session_counts"):
            self._session_counts: dict[str, int] = {}

    def increment(self, key: str) -> int:
        """递增会话计数器，返回新值"""
        self.__init_session_state()
        self._session_counts[key] = self._session_counts.get(key, 0) + 1
        return self._session_counts[key]

    def get_count(self, key: str) -> int:
        """获取会话计数器值"""
        self.__init_session_state()
        return self._session_counts.get(key, 0)

    def reset_counts(self) -> None:
        """重置会话计数器"""
        self._session_counts = {}


# ── 单例 ──

_instance: HardLimits | None = None


def get_hard_limits() -> HardLimits:
    """获取 HardLimits 单例"""
    global _instance
    if _instance is None:
        _instance = HardLimits()
    return _instance
