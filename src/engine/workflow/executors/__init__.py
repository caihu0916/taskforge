
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""节点执行器基类(P1-S1-003~010)

所有节点 executor 继承 BaseExecutor,统一:
  - 输入/输出契约(NodeInput/NodeOutput)
  - 执行结果写入 Trace(P1-S1-021 对接)
  - A2A 五态对齐(P1-S1-012)
  - 错误分类与容错(P1-S1-025)

执行器注册到 EXECUTOR_REGISTRY,供 WorkflowExecutor 按 node.type 分发。
"""

from __future__ import annotations

import time
import uuid as _uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── 执行器注册表 ──

EXECUTOR_REGISTRY: dict[str, type[BaseExecutor]] = {}


def register_executor(node_type: str):
    """装饰器注册执行器类到 EXECUTOR_REGISTRY

    用法:
        @register_executor("http_request")
        class HttpRequestExecutor(BaseExecutor):
            ...
    """

    def deco(cls: type[BaseExecutor]) -> type[BaseExecutor]:
        EXECUTOR_REGISTRY[node_type] = cls
        logger.debug("executor_registered", node_type=node_type, cls=cls.__name__)
        return cls

    return deco


def get_executor(node_type: str) -> type[BaseExecutor] | None:
    """查询执行器类"""
    return EXECUTOR_REGISTRY.get(node_type)


# ── 数据契约 ──


@dataclass
class NodeInput:
    """节点输入"""

    node_id: str
    node_type: str
    config: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)  # 上游节点输出
    run_id: str = ""


@dataclass
class NodeOutput:
    """节点输出"""

    node_id: str = ""
    status: str = "completed"  # submitted/working/input-required/completed/failed
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    trace_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:16])


# ── BaseExecutor 基类 ──


class BaseExecutor(ABC):
    """节点执行器基类

    子类必须实现 execute() 方法。
    基类提供:
      - execute_with_trace(): 执行 + 记录 Trace + 异常捕获
      - validate_config(): 配置校验(子类可覆盖)
      - get_default_config(): 默认配置(子类可覆盖)
    """

    # 节点类型(子类覆盖)
    node_type: str = "base"

    # 配置 schema(子类覆盖,用于校验)
    config_schema: dict[str, Any] = {}

    def __init__(self) -> None:
        self.logger = structlog.get_logger(__name__).bind(executor=self.__class__.__name__)

    @abstractmethod
    async def execute(self, inp: NodeInput) -> NodeOutput:
        """执行节点逻辑(子类必须实现)

        Args:
            inp: 节点输入(含 config 和 context)

        Returns:
            NodeOutput: 节点输出(含 status 和 output)
        """
        ...

    async def execute_with_trace(self, inp: NodeInput) -> NodeOutput:
        """执行节点并记录 Trace

        包装 execute(),添加:
          - 耗时测量
          - 异常捕获(转为 failed 状态)
          - Trace 记录(供 P1-S1-021 ExecutionTracer 对接)

        Args:
            inp: 节点输入

        Returns:
            NodeOutput: 节点输出(含 trace_id 和 duration_ms)
        """
        start = time.monotonic()
        self.logger.info(
            "node_execute_start",
            node_id=inp.node_id,
            node_type=inp.node_type,
            run_id=inp.run_id,
        )

        try:
            output = await self.execute(inp)
            output.duration_ms = (time.monotonic() - start) * 1000
            output.node_id = inp.node_id

            self.logger.info(
                "node_execute_success",
                node_id=inp.node_id,
                node_type=inp.node_type,
                status=output.status,
                duration_ms=round(output.duration_ms, 2),
            )
            return output

        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            duration_ms = (time.monotonic() - start) * 1000
            self.logger.error(
                "node_execute_failed",
                node_id=inp.node_id,
                node_type=inp.node_type,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=round(duration_ms, 2),
            )
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration_ms,
            )

    def validate_config(self, config: dict[str, Any]) -> str | None:
        """校验配置(返回 None=合法, string=错误信息)

        默认基于 config_schema 做必填字段检查。
        子类可覆盖实现更复杂的校验。
        """
        for key, rule in self.config_schema.items():
            if rule.get("required", False) and key not in config:
                return f"Missing required config: {key}"
        return None

    @classmethod
    def get_default_config(cls) -> dict[str, Any]:
        """获取默认配置(基于 config_schema 的 default 值)"""
        defaults: dict[str, Any] = {}
        for key, rule in cls.config_schema.items():
            if "default" in rule:
                defaults[key] = rule["default"]
        return defaults
