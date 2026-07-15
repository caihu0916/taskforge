
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill-Gap 1-2-4: Workflow 单步测试运行

支持在工作流编辑器中单独测试某个节点的执行，无需启动整个工作流。

功能：
1. 接收节点配置和模拟上下文，执行单个节点
2. 返回执行结果、耗时、状态和日志
3. 支持输入预览和输出验证
4. 不影响真实工作流状态（dry-run 模式）
5. 支持所有节点类型（通过 EXECUTOR_REGISTRY 分发）

使用场景：
- 工作流编辑器中"测试此节点"按钮
- 节点配置修改后快速验证
- 调试节点行为
"""

from __future__ import annotations

import asyncio
import time
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.engine.workflow.executors import (
    EXECUTOR_REGISTRY,
    NodeInput,
    NodeOutput,
    get_executor,
)

logger = structlog.get_logger(__name__)


@dataclass
class StepTestRequest:
    """单步测试请求"""

    node_type: str
    config: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0  # 单步测试超时（秒）


@dataclass
class StepTestResult:
    """单步测试结果"""

    success: bool
    status: str = "completed"  # completed/failed/timeout
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    node_type: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    context_preview: dict[str, Any] = field(default_factory=dict)
    test_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:16])
    logs: list[dict[str, Any]] = field(default_factory=list)


async def test_single_step(request: StepTestRequest) -> StepTestResult:
    """执行单个节点的测试运行

    Args:
        request: 测试请求

    Returns:
        StepTestResult: 测试结果
    """
    test_id = _uuid.uuid4().hex[:16]
    start_time = time.monotonic()
    logs: list[dict[str, Any]] = []

    logs.append(
        {
            "timestamp": time.time(),
            "level": "INFO",
            "message": f"开始测试节点: {request.node_type}",
            "test_id": test_id,
        }
    )

    # 检查节点类型是否注册
    executor_cls = get_executor(request.node_type)
    if executor_cls is None:
        logs.append(
            {
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"未知节点类型: {request.node_type}",
                "test_id": test_id,
            }
        )
        return StepTestResult(
            success=False,
            status="failed",
            error=f"未知节点类型: {request.node_type}",
            duration_ms=(time.monotonic() - start_time) * 1000,
            node_type=request.node_type,
            config=request.config,
            context_preview=_truncate_context(request.context),
            test_id=test_id,
            logs=logs,
        )

    # 配置校验
    try:
        executor = executor_cls()
        config_error = executor.validate_config(request.config)
        if config_error:
            logs.append(
                {
                    "timestamp": time.time(),
                    "level": "ERROR",
                    "message": f"配置校验失败: {config_error}",
                    "test_id": test_id,
                }
            )
            return StepTestResult(
                success=False,
                status="failed",
                error=f"配置校验失败: {config_error}",
                duration_ms=(time.monotonic() - start_time) * 1000,
                node_type=request.node_type,
                config=request.config,
                context_preview=_truncate_context(request.context),
                test_id=test_id,
                logs=logs,
            )
    except Exception as e:
        logger.debug("exception_handled", error=str(e))
        logs.append(
            {
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"执行器初始化失败: {e}",
                "test_id": test_id,
            }
        )
        return StepTestResult(
            success=False,
            status="failed",
            error=f"执行器初始化失败: {e}",
            duration_ms=(time.monotonic() - start_time) * 1000,
            node_type=request.node_type,
            config=request.config,
            context_preview=_truncate_context(request.context),
            test_id=test_id,
            logs=logs,
        )

    # 构造 NodeInput
    node_input = NodeInput(
        node_id=f"test_{test_id}",
        node_type=request.node_type,
        config=request.config,
        context=request.context,
        run_id=f"test_run_{test_id}",
    )

    logs.append(
        {
            "timestamp": time.time(),
            "level": "INFO",
            "message": f"执行节点: {request.node_type} (超时: {request.timeout}s)",
            "test_id": test_id,
        }
    )

    # 执行节点（带超时）
    try:
        output: NodeOutput = await asyncio.wait_for(
            executor.execute_with_trace(node_input),
            timeout=request.timeout,
        )

        duration_ms = (time.monotonic() - start_time) * 1000

        if output.status == "failed":
            logs.append(
                {
                    "timestamp": time.time(),
                    "level": "ERROR",
                    "message": f"节点执行失败: {output.error}",
                    "test_id": test_id,
                    "duration_ms": output.duration_ms,
                }
            )
            return StepTestResult(
                success=False,
                status="failed",
                output=output.output,
                error=output.error,
                duration_ms=duration_ms,
                node_type=request.node_type,
                config=request.config,
                context_preview=_truncate_context(request.context),
                test_id=test_id,
                logs=logs,
            )

        logs.append(
            {
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"节点执行成功 (状态: {output.status}, 耗时: {output.duration_ms:.2f}ms)",
                "test_id": test_id,
                "duration_ms": output.duration_ms,
            }
        )

        return StepTestResult(
            success=True,
            status=output.status,
            output=output.output,
            duration_ms=duration_ms,
            node_type=request.node_type,
            config=request.config,
            context_preview=_truncate_context(request.context),
            test_id=test_id,
            logs=logs,
        )

    except TimeoutError:
        duration_ms = (time.monotonic() - start_time) * 1000
        logs.append(
            {
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"节点执行超时 (超时: {request.timeout}s)",
                "test_id": test_id,
            }
        )
        return StepTestResult(
            success=False,
            status="timeout",
            error=f"节点执行超时 (超时: {request.timeout}s)",
            duration_ms=duration_ms,
            node_type=request.node_type,
            config=request.config,
            context_preview=_truncate_context(request.context),
            test_id=test_id,
            logs=logs,
        )

    except Exception as e:
        logger.debug("exception_handled", error=str(e))
        duration_ms = (time.monotonic() - start_time) * 1000
        logs.append(
            {
                "timestamp": time.time(),
                "level": "ERROR",
                "message": f"节点执行异常: {type(e).__name__}: {e}",
                "test_id": test_id,
            }
        )
        return StepTestResult(
            success=False,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            duration_ms=duration_ms,
            node_type=request.node_type,
            config=request.config,
            context_preview=_truncate_context(request.context),
            test_id=test_id,
            logs=logs,
        )


def _truncate_context(context: dict[str, Any], max_length: int = 200) -> dict[str, Any]:
    """截断上下文以避免日志过大"""
    truncated = {}
    for k, v in context.items():
        if isinstance(v, str) and len(v) > max_length:
            truncated[k] = v[:max_length] + "...(truncated)"
        elif isinstance(v, (dict, list)) and len(str(v)) > max_length:
            truncated[k] = f"<{type(v).__name__} len={len(v)}>"
        else:
            truncated[k] = v
    return truncated


def list_testable_node_types() -> list[dict[str, Any]]:
    """列出所有可测试的节点类型"""
    from src.engine.workflow.node_compat import get_node_description, get_node_label

    result = []
    for node_type, executor_cls in sorted(EXECUTOR_REGISTRY.items()):
        result.append(
            {
                "type": node_type,
                "label": get_node_label(node_type),
                "description": get_node_description(node_type),
                "executor": executor_cls.__name__,
                "config_schema": getattr(executor_cls, "config_schema", {}),
                "default_config": executor_cls.get_default_config(),
            }
        )
    return result


def get_node_config_schema(node_type: str) -> dict[str, Any] | None:
    """获取节点配置 schema（用于前端动态生成配置表单）"""
    executor_cls = get_executor(node_type)
    if executor_cls is None:
        return None
    return {
        "node_type": node_type,
        "config_schema": getattr(executor_cls, "config_schema", {}),
        "default_config": executor_cls.get_default_config(),
    }


def validate_step_config(node_type: str, config: dict[str, Any]) -> tuple[bool, str | None]:
    """验证节点配置（不执行）

    Args:
        node_type: 节点类型
        config: 配置字典

    Returns:
        (is_valid, error_message)
    """
    executor_cls = get_executor(node_type)
    if executor_cls is None:
        return False, f"未知节点类型: {node_type}"

    try:
        executor = executor_cls()
        error = executor.validate_config(config)
        if error:
            return False, error
        return True, None
    except Exception as e:
        return False, f"执行器初始化失败: {e}"
