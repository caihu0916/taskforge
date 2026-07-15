
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill Router — Fable 5 模式 B: 三层路由

Fable 5 的 MCP Three-Layer Routing 机制：第三方技能调用时，
必须经过 search → user confirmation → fallback 的三级路由，
防止 Agent 未经授权调用外部服务或泄露数据。

三层路由:
  Layer 1 (search): 检查工具是否需要用户授权
  Layer 2 (confirm): 暂停执行，等待用户确认（通过 Chat 返回确认请求）
  Layer 3 (fallback): 用户拒绝或超时后，使用安全替代方案

关键设计:
  - THIRD_PARTY_TOOLS 定义需要授权的第三方工具集合
  - confirm_timeout 控制确认超时（默认 60s）
  - 确认结果可缓存（同一会话内同工具不需重复确认）
  - fallback 机制不阻断工作流，而是降级到安全替代

集成点:
  - ReAct loop: 工具执行前调用 SkillRouter.route()
  - context_builder.py: 注入路由规则提示
  - guardrails.py: 作为安全网补充
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 路由决策 ──


class RouteDecision(StrEnum):
    """路由决策结果"""

    ALLOW = "allow"  # 直接放行（内置工具）
    CONFIRM = "confirm"  # 需要用户确认
    DENY = "deny"  # 直接拒绝（黑名单）


class ConfirmResult(StrEnum):
    """用户确认结果"""

    APPROVED = "approved"  # 用户批准
    DENIED = "denied"  # 用户拒绝
    TIMEOUT = "timeout"  # 确认超时


# ── 需要授权的第三方工具 ──

# 定义哪些工具/技能需要用户确认（Fable 5 的 search 层）
# 格式: tool_name → {confirm_reason, fallback_tool, risk_level}
THIRD_PARTY_TOOLS: dict[str, dict[str, Any]] = {
    # Firecrawl 系列 — 外部网络抓取，可能暴露数据
    "firecrawl_scrape": {
        "confirm_reason": "将向外部服务发送URL请求",
        "fallback_tool": "web_search",
        "risk_level": "medium",
    },
    "firecrawl_search": {
        "confirm_reason": "将向外部服务发送搜索请求",
        "fallback_tool": "baidu_search",
        "risk_level": "low",
    },
    "firecrawl_interact": {
        "confirm_reason": "将在外部浏览器中交互，可能修改外部数据",
        "fallback_tool": None,  # 无安全替代，需要确认
        "risk_level": "high",
    },
    "firecrawl_crawl": {
        "confirm_reason": "将批量抓取外部网站内容",
        "fallback_tool": None,
        "risk_level": "high",
    },
    # muapi 系列 — AI 媒体生成，消耗额度
    "muapi_generate": {
        "confirm_reason": "将调用外部AI模型生成内容，消耗API额度",
        "fallback_tool": None,
        "risk_level": "medium",
    },
    # 发布系列 — 公开内容，不可撤回
    "xhs_post": {
        "confirm_reason": "将公开发布小红书笔记，发布后不可撤回",
        "fallback_tool": None,
        "risk_level": "high",
    },
    "wechat_publish": {
        "confirm_reason": "将发布微信公众号文章，发布后不可撤回",
        "fallback_tool": None,
        "risk_level": "high",
    },
    # 财务操作系列
    "payment_process": {
        "confirm_reason": "将执行支付操作",
        "fallback_tool": None,
        "risk_level": "critical",
    },
}

# 黑名单 — 任何情况下都不允许的工具
BLACKLISTED_TOOLS: set[str] = set()


@dataclass
class RouteResult:
    """路由检查结果"""

    decision: RouteDecision
    tool_name: str
    confirm_reason: str = ""
    fallback_tool: str | None = None
    risk_level: str = "low"
    cached_approval: bool = False  # 是否命中缓存的批准

    @property
    def needs_confirm(self) -> bool:
        return self.decision == RouteDecision.CONFIRM

    @property
    def is_allowed(self) -> bool:
        return self.decision == RouteDecision.ALLOW


@dataclass
class FallbackOption:
    """降级替代方案"""

    original_tool: str
    fallback_tool: str | None
    reason: str
    message: str = ""

    @property
    def has_fallback(self) -> bool:
        return self.fallback_tool is not None


# ── SkillRouter 核心路由器 ──


class SkillRouter:
    """三层路由器 — search → confirm → fallback

    用法:
        router = get_skill_router()
        result = router.route("firecrawl_scrape", role="butler")
        if result.needs_confirm:
            #暂停执行，向用户请求确认
            confirm = router.request_confirm("firecrawl_scrape", session_id="abc")
            if confirm == ConfirmResult.APPROVED:
                #执行工具
            else:
                #使用 fallback
                fallback = router.get_fallback("firecrawl_scrape")
    """

    def __init__(self, confirm_timeout: int = 60) -> None:
        self._confirm_timeout = confirm_timeout
        # 缓存: (session_id, tool_name) → (approved: bool, timestamp: float)
        self._confirm_cache: dict[tuple[str, str], tuple[bool, float]] = {}
        # 待确认: tool_name → (timestamp, callback_id)
        self._pending_confirms: dict[str, tuple[float, str]] = {}

    # ── Layer 1: search（路由决策） ──

    def route(self, tool_name: str, *, role: str = "", session_id: str = "") -> RouteResult:
        """检查工具调用是否需要路由控制

        Args:
            tool_name: 工具名称
            role: 当前角色（某些角色可能有免确认权限）
            session_id: 会话ID（用于查找缓存确认）

        Returns:
            RouteResult 路由决策
        """
        # 黑名单检查
        if tool_name in BLACKLISTED_TOOLS:
            logger.warning("skill_router_blacklisted", tool=tool_name)
            return RouteResult(
                decision=RouteDecision.DENY,
                tool_name=tool_name,
                confirm_reason="工具在黑名单中，任何情况下不允许使用",
            )

        # 内置工具直接放行
        if tool_name not in THIRD_PARTY_TOOLS:
            return RouteResult(
                decision=RouteDecision.ALLOW,
                tool_name=tool_name,
            )

        # 第三方工具 — 检查缓存确认
        meta = THIRD_PARTY_TOOLS[tool_name]
        if session_id:
            cache_key = (session_id, tool_name)
            if cache_key in self._confirm_cache:
                approved, ts = self._confirm_cache[cache_key]
                if approved and (time.time() - ts) < 300:  # 5分钟缓存
                    logger.debug("skill_router_cached_approval", tool=tool_name, session=session_id)
                    return RouteResult(
                        decision=RouteDecision.ALLOW,
                        tool_name=tool_name,
                        cached_approval=True,
                    )

        # boss 角色对非 critical 风险的工具有免确认权限
        if role == "boss" and meta.get("risk_level") != "critical":
            logger.debug("skill_router_role_bypass", tool=tool_name, role=role)
            return RouteResult(
                decision=RouteDecision.ALLOW,
                tool_name=tool_name,
                cached_approval=True,  # 视同已确认
            )

        # 需要确认
        logger.info(
            "skill_router_needs_confirm",
            tool=tool_name,
            reason=meta.get("confirm_reason", ""),
            risk=meta.get("risk_level", ""),
        )
        return RouteResult(
            decision=RouteDecision.CONFIRM,
            tool_name=tool_name,
            confirm_reason=meta.get("confirm_reason", ""),
            fallback_tool=meta.get("fallback_tool"),
            risk_level=meta.get("risk_level", "low"),
        )

    # ── Layer 2: confirm（用户确认） ──

    def request_confirm(self, tool_name: str, *, session_id: str = "") -> ConfirmResult:
        """模拟用户确认流程

        实际集成时，这个方法应该:
        1. 生成确认请求消息
        2. 返回给 Chat/前端
        3. 等待用户回复
        4. 根据回复返回结果

        当前为同步简化版本，实际异步版本需要通过
        Chatbridge + 前端交互实现。
        """
        if tool_name not in THIRD_PARTY_TOOLS:
            return ConfirmResult.APPROVED

        # 记录待确认
        self._pending_confirms[tool_name] = (time.time(), session_id)
        logger.info("skill_router_confirm_requested", tool=tool_name, session=session_id)

        # 简化实现: 返回 TIMEOUT
        # 实际实现中，这里应该等待前端回调
        return ConfirmResult.TIMEOUT

    def handle_confirm_response(
        self,
        tool_name: str,
        approved: bool,
        *,
        session_id: str = "",
    ) -> None:
        """处理用户确认回复

        Args:
            tool_name: 工具名称
            approved: 用户是否批准
            session_id: 会话ID（用于缓存确认结果）
        """
        if session_id:
            cache_key = (session_id, tool_name)
            self._confirm_cache[cache_key] = (approved, time.time())
            logger.info("skill_router_confirm_response", tool=tool_name, approved=approved, session=session_id)

        # 清理待确认
        self._pending_confirms.pop(tool_name, None)

    # ── Layer 3: fallback（降级替代） ──

    def get_fallback(self, tool_name: str) -> FallbackOption:
        """获取工具的降级替代方案

        Args:
            tool_name: 原始工具名称

        Returns:
            FallbackOption 降级方案
        """
        meta = THIRD_PARTY_TOOLS.get(tool_name, {})
        fallback = meta.get("fallback_tool")

        option = FallbackOption(
            original_tool=tool_name,
            fallback_tool=fallback,
            reason=meta.get("confirm_reason", "需要用户确认但未获得批准"),
        )

        if fallback:
            option.message = f"用户未确认{tool_name}，使用安全替代: {fallback}"
        else:
            option.message = f"用户未确认{tool_name}，且无安全替代方案，跳过此操作"

        logger.info(
            "skill_router_fallback",
            original=tool_name,
            fallback=fallback,
        )
        return option

    # ── 管理 ──

    def register_third_party(
        self,
        tool_name: str,
        *,
        confirm_reason: str,
        fallback_tool: str | None = None,
        risk_level: str = "medium",
    ) -> None:
        """动态注册需要授权的第三方工具"""
        THIRD_PARTY_TOOLS[tool_name] = {
            "confirm_reason": confirm_reason,
            "fallback_tool": fallback_tool,
            "risk_level": risk_level,
        }
        logger.info("skill_router_registered", tool=tool_name, risk=risk_level)

    def add_to_blacklist(self, tool_name: str) -> None:
        """将工具加入黑名单"""
        BLACKLISTED_TOOLS.add(tool_name)
        logger.info("skill_router_blacklisted", tool=tool_name)

    def clear_cache(self, session_id: str = "") -> None:
        """清除确认缓存"""
        if session_id:
            self._confirm_cache = {k: v for k, v in self._confirm_cache.items() if k[0] != session_id}
        else:
            self._confirm_cache.clear()
        logger.debug("skill_router_cache_cleared", session=session_id or "all")

    def get_pending_confirms(self) -> list[str]:
        """获取待确认的工具列表"""
        now = time.time()
        # 清理超时的待确认
        expired = [name for name, (ts, _) in self._pending_confirms.items() if (now - ts) > self._confirm_timeout]
        for name in expired:
            self._pending_confirms.pop(name, None)

        return list(self._pending_confirms.keys())

    # ── 注入 context_builder 的路由规则文本 ──

    def build_router_prompt(self, role: str = "") -> str:
        """生成路由规则提示文本，注入 context_builder

        告诉 Agent 哪些工具需要用户确认，以及替代方案。
        """
        if not THIRD_PARTY_TOOLS:
            return ""

        parts: list[str] = []
        for tool, meta in THIRD_PARTY_TOOLS.items():
            risk = meta.get("risk_level", "medium")
            reason = meta.get("confirm_reason", "")
            fallback = meta.get("fallback_tool")
            entry = f"{tool}({risk})"
            if reason:
                entry += f": {reason}"
            if fallback:
                entry += f" → 替代: {fallback}"
            parts.append(entry)

        prompt = "[路由规则] 以下工具需用户确认才可调用: " + "; ".join(parts)
        if role == "boss":
            prompt += " (BOSS角色免确认非critical工具)"
        return prompt


# ── 单例 ──

_instance: SkillRouter | None = None


def get_skill_router() -> SkillRouter:
    """获取 SkillRouter 单例"""
    global _instance
    if _instance is None:
        _instance = SkillRouter()
    return _instance
