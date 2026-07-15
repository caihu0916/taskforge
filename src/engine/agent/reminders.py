
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Reminders 动态注入中间件 — Fable 5 模式 D 落地

Fable 5 的 anthropic_reminders 机制：按需注入安全规则，
不静态写死在 system prompt 中。避免规则全塞导致 token 膨胀和规则冲突。

两层提醒机制:
1. 场景触发（原5条）：根据用户消息关键词动态匹配
2. 角色绑定（新增34角色）：根据当前AgentRole注入专属安全提醒

集成点: context_builder.py Layer1.5 ~ Layer2 之间

用法:
    middleware = ReminderMiddleware()
    #场景触发
    content = middleware.inject(user_message, {"message_count": 25})
    #角色绑定
    content = middleware.inject_for_role("accountant", user_message, {})
    #完整注入(场景+角色)
    content = middleware.inject_full("accountant", user_message, {"message_count": 25})
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ._base import AgentRole
from ._role_reminders import get_role_reminder_list

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


# ── 提醒规则定义 ──


@dataclass
class ReminderRule:
    """单条动态提醒规则"""

    name: str
    trigger: Callable[[str, dict], bool]
    content: str
    max_inject_chars: int = 200  # 单条提醒最大字符数，防注入过长


# ── 内置提醒内容 ──

_FINANCE_REMINDER = (
    "【财务安全】1.提供通用信息不构成专业建议 "
    "2.敏感字段掩码(身份证前三后四/银行卡前四后四/手机号前三后四) "
    "3.¥10,000以上操作需人类确认,¥100,000以上需高管审批"
)

_PUBLISH_REMINDER = (
    "【发布合规】1.发布前必须合规检查 2.小红书:标注AI合成内容,禁止AI托管互动 "
    "3.公众号:禁止诱导分享/标题党,需原创声明 4.通用:禁用绝对化用语"
)

_CODE_SAFETY_REMINDER = (
    "【代码红线】1.禁止批量脚本修改业务代码 2.一次只改一个文件的一处 "
    "3.改完必须启动后端验证(不仅是py_compile) 4.修一项验证一项"
)

_CONTEXT_REFRESH_REMINDER = "【上下文管理】对话超过20轮,优先保留最近5轮+当前任务关键信息,压缩后确认不丢关键数据"

_USER_DATA_REMINDER = (
    "【数据保护】1.不输出身份证/银行卡/API密钥等敏感信息 2.查询结果必须掩码 3.跨会话隔离:不向非授权用户透露项目凭证"
)


class ReminderMiddleware:
    """运行时按场景动态注入安全提醒

    用法:
        middleware = ReminderMiddleware()
        content = middleware.inject(user_message, {"message_count": 25})
        #content = "" 或 "【财务安全】...\\n【上下文管理】..."
        #注入到 context_builder 的 system message 中
    """

    def __init__(self):
        self.rules: list[ReminderRule] = []
        self._register_defaults()

    def _register_defaults(self):
        """注册默认的 5 条提醒规则"""

        # 1. 财务操作
        self.rules.append(
            ReminderRule(
                name="finance",
                trigger=lambda msg, ctx: bool(
                    re.search(
                        r"财务|报表|导出|金额|交易|利润|收入|支出|发票|对账|报销|付款|收款|账单",
                        msg,
                    )
                ),
                content=_FINANCE_REMINDER,
            )
        )

        # 2. 发布操作
        self.rules.append(
            ReminderRule(
                name="publish",
                trigger=lambda msg, ctx: bool(
                    re.search(
                        r"发布|推送|公众号|小红书|抖音|B站|知乎|微博|发文章|发笔记|推文|种草",
                        msg,
                    )
                ),
                content=_PUBLISH_REMINDER,
            )
        )

        # 3. 代码变更 — 仅在有代码库上下文时触发
        self.rules.append(
            ReminderRule(
                name="code_safety",
                trigger=lambda msg, ctx: (
                    bool(re.search(r"修改|改代码|修复|重构|优化代码|删代码|新增功能|写代码", msg))
                    and ctx.get("has_codebase", False)
                ),
                content=_CODE_SAFETY_REMINDER,
            )
        )

        # 4. 长对话
        self.rules.append(
            ReminderRule(
                name="context_refresh",
                trigger=lambda msg, ctx: ctx.get("message_count", 0) > 20,
                content=_CONTEXT_REFRESH_REMINDER,
            )
        )

        # 5. 用户数据
        self.rules.append(
            ReminderRule(
                name="user_data",
                trigger=lambda msg, ctx: bool(
                    re.search(
                        r"用户数据|个人信息|身份证|手机号|银行|密码|密钥|API.?key|secret|cookie",
                        msg,
                    )
                ),
                content=_USER_DATA_REMINDER,
            )
        )

    def inject(self, message: str, context: dict | None = None) -> str:
        """根据消息和上下文动态注入匹配的提醒

        Args:
            message: 用户消息文本
            context: 上下文信息，支持:
                - message_count (int): 当前对话轮数
                - has_codebase (bool): 是否涉及代码库

        Returns:
            注入内容字符串，可能为空。每条提醒已截断到 max_inject_chars。
        """
        if not message:
            return ""

        ctx = context or {}
        triggered: list[str] = []

        for rule in self.rules:
            try:
                if rule.trigger(message, ctx):
                    # 截断防过长
                    content = rule.content[: rule.max_inject_chars]
                    triggered.append(content)
            except Exception:
                logger.debug("reminder_trigger_error", rule=rule.name, exc_info=True)
                continue  # 触发器异常不阻断

        if not triggered:
            return ""

        # 拼接，控制总量
        result = "\n".join(triggered)
        # 总注入上限 600 字符（约 200 token），避免 token 膨胀
        max_total = 600
        if len(result) > max_total:
            result = result[:max_total]
            logger.debug("reminders_truncated", original_len=len("\n".join(triggered)))

        return result

    def inject_for_context_builder(self, message: str, context: dict | None = None) -> str:
        """供 context_builder.py 调用的入口

        返回带标记的完整注入文本，或空字符串。
        空字符串时不生成 system message，零开销。
        """
        content = self.inject(message, context)
        if not content:
            return ""
        return f"<reminders>\n{content}\n</reminders>"

    def get_rule_names(self) -> list[str]:
        """返回所有已注册规则名（调试用）"""
        return [r.name for r in self.rules]

    def get_triggered_names(self, message: str, context: dict | None = None) -> list[str]:
        """返回当前消息会触发的规则名（调试/日志用）"""
        ctx = context or {}
        triggered = []
        for rule in self.rules:
            try:
                if rule.trigger(message, ctx):
                    triggered.append(rule.name)
            except Exception as e:
                logger.debug("reminder_trigger_check_failed", rule=rule.name, error=str(e))
                continue
        return triggered

    # ── 角色绑定提醒（Fable 5 模式 D 增强）──

    def inject_for_role(self, role: AgentRole | str, message: str, context: dict | None = None) -> str:
        """根据AgentRole注入专属安全提醒

        角色专属提醒来自 _role_reminders.py ROLE_REMINDERS 映射，
        与场景触发互不冲突，可叠加使用。

        Args:
            role: AgentRole枚举或角色名字符串
            message: 用户消息（保留参数，未来可按消息过滤角色提醒）
            context: 上下文信息

        Returns:
            角色专属提醒字符串，可能为空
        """
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                logger.warning("unknown_role_for_reminder_injection", role=role)
                return ""

        reminders = get_role_reminder_list(role)
        if not reminders:
            return ""

        lines = [f"- {r}" for r in reminders]
        result = "\n".join(lines)

        # 角色提醒上限 400 字符（约 130 token）
        max_role_chars = 400
        if len(result) > max_role_chars:
            result = result[:max_role_chars]
            logger.debug("role_reminders_truncated", role=role.value)

        return result

    def inject_full(self, role: AgentRole | str | None, message: str, context: dict | None = None) -> str:
        """完整注入：场景触发 + 角色绑定

        这是 context_builder 应该调用的主入口。

        Args:
            role: 当前Agent角色（None则只做场景触发）
            message: 用户消息
            context: 上下文信息

        Returns:
            带标记的完整注入文本
        """
        parts = []

        # 1. 场景触发
        scene_content = self.inject(message, context)
        if scene_content:
            parts.append(scene_content)

        # 2. 角色绑定
        if role is not None:
            role_content = self.inject_for_role(role, message, context)
            if role_content:
                parts.append(role_content)

        if not parts:
            return ""

        full = "\n".join(parts)
        # 总注入上限 800 字符（约 250 token）
        max_total = 800
        if len(full) > max_total:
            full = full[:max_total]
            logger.debug(
                "full_reminders_truncated",
                original_len=len("\n".join(parts)),
            )

        return f"<reminders>\n{full}\n</reminders>"


# ── 单例 ──

_instance: ReminderMiddleware | None = None


def get_reminder_middleware() -> ReminderMiddleware:
    """获取 ReminderMiddleware 单例"""
    global _instance
    if _instance is None:
        _instance = ReminderMiddleware()
    return _instance
