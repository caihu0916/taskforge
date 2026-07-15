
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent自我进化引擎 — 记忆学习 + 策略进化 + 性能优化

功能:
  - 执行结果反馈收集 (成功/失败/用户评分)
  - 策略效果评估 (哪些prompt/策略更有效)
  - 自动策略优化 (基于历史数据调整)
  - 长期记忆库 (经验沉淀)
  - 进化报告 (周期性总结)

适用场景:
  - Agent持续优化自身表现
  - 从失败中学习避免重复错误
  - 根据用户反馈调整策略

模块结构:
  - _evolution_models: 枚举 + 数据模型
  - _evolution_engine: 核心引擎类
  - _evolution_api: API路由定义
"""

# 重新导出模型和枚举（保持向后兼容）
# 重新导出API创建函数
from __future__ import annotations

from src.engine.agent._evolution_api import create_evolution_api

# 重新导出引擎类和工厂函数（保持向后兼容）
from src.engine.agent._evolution_engine import (
    AgentEvolutionEngine,
    EvolutionEngine,
    get_evolution_engine,
)
from src.engine.agent._evolution_models import (
    EvolutionAction,
    EvolutionPhase,
    EvolutionReport,
    EvolutionSession,
    EvolutionStatus,
    EvolutionStep,
    ExecutionRecord,
    ExecutionResult,
    MemoryEntry,
    Strategy,
    StrategyType,
)

__all__ = [
    # 引擎
    "AgentEvolutionEngine",
    "EvolutionAction",
    "EvolutionEngine",
    "EvolutionPhase",
    "EvolutionReport",
    "EvolutionSession",
    "EvolutionStatus",
    # 模型
    "EvolutionStep",
    "ExecutionRecord",
    # 枚举
    "ExecutionResult",
    "MemoryEntry",
    "Strategy",
    "StrategyType",
    # API
    "create_evolution_api",
    "get_evolution_engine",
]
