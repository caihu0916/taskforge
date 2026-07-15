
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""M5-B: DenialTrackingState — 拒绝追踪 (对标 Claude Code denialTracking.ts)

追踪权限拒绝模式:
  - consecutive_denials: 连续拒绝次数 (max 3)
  - total_denials: 累计拒绝次数 (max 20)
  - should_fallback(): 任一超限 → 强制提示用户
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# 阈值从 hard_limits.yaml 读取，这里只保留兜底默认值
_FALLBACK_MAX_CONSECUTIVE_DENIALS = 3
_FALLBACK_MAX_TOTAL_DENIALS = 20


def _get_limit(key: str, fallback: int) -> int:
    """从 HardLimits 读取阈值，读取失败则用兜底值"""
    try:
        from src.engine.agent.hard_limits import get_hard_limits

        val = get_hard_limits().get("agent_safety", key, fallback)
        return int(val) if val is not None else fallback
    except Exception as e:
        logger.debug("denial_tracker_config_fallback", error=str(e))
        return fallback


@dataclass
class DenialTrackingState:
    """拒绝追踪状态 (immutable 更新模式)"""

    consecutive_denials: int = 0
    total_denials: int = 0


def create_denial_state() -> DenialTrackingState:
    """创建初始状态"""
    return DenialTrackingState()


def record_denial(state: DenialTrackingState) -> DenialTrackingState:
    """记录一次拒绝"""
    return DenialTrackingState(
        consecutive_denials=state.consecutive_denials + 1,
        total_denials=state.total_denials + 1,
    )


def record_success(state: DenialTrackingState) -> DenialTrackingState:
    """记录一次成功 (重置连续计数)"""
    if state.consecutive_denials == 0:
        return state
    return DenialTrackingState(
        consecutive_denials=0,
        total_denials=state.total_denials,
    )


def should_fallback(state: DenialTrackingState) -> bool:
    """任一维度超限 → 需要fallback"""
    max_consecutive = _get_limit("max_consecutive_denials", _FALLBACK_MAX_CONSECUTIVE_DENIALS)
    max_total = _get_limit("max_total_denials", _FALLBACK_MAX_TOTAL_DENIALS)
    return state.consecutive_denials >= max_consecutive or state.total_denials >= max_total
