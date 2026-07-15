
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Loop 节点执行器(P1-S1-004)

循环执行子节点,支持 for/while 两种模式。
"""

from __future__ import annotations

from typing import Any

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("loop")
class LoopExecutor(BaseExecutor):
    """循环节点执行器

    配置:
        mode: 循环模式(for | while,默认 for)
        items: for 模式下的迭代列表(或上下文变量名)
        condition: while 模式下的条件表达式
        max_iterations: 最大迭代次数(安全阀,默认 1000)
        sub_node: 子节点配置(每轮迭代执行的节点)
    """

    node_type = "loop"
    config_schema = {
        "mode": {"required": False, "type": "string", "default": "for"},
        "items": {"required": False, "type": "any", "default": []},
        "condition": {"required": False, "type": "string", "default": ""},
        "max_iterations": {"required": False, "type": "number", "default": 1000},
        "sub_node": {"required": False, "type": "object", "default": {}},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        mode = inp.config.get("mode", "for")
        max_iter = min(inp.config.get("max_iterations", 1000), 10000)
        sub_node_config = inp.config.get("sub_node", {})

        results: list[dict[str, Any]] = []
        iteration = 0

        if mode == "for":
            items = inp.config.get("items", [])
            # 支持从上下文获取列表
            if isinstance(items, str) and items in inp.context:
                items = inp.context[items]

            if not isinstance(items, (list, tuple)):
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error=f"items must be a list, got {type(items).__name__}",
                )

            for i, item in enumerate(items):
                if i >= max_iter:
                    logger.warning("loop_max_iterations_reached", node_id=inp.node_id, count=i)
                    break

                iteration = i
                result = await self._execute_iteration(inp, sub_node_config, {"item": item, "index": i})
                results.append(result)

        elif mode == "while":
            condition = inp.config.get("condition", "false")
            while iteration < max_iter:
                if not self._eval_condition(condition, inp.context, iteration):
                    break

                result = await self._execute_iteration(inp, sub_node_config, {"iteration": iteration})
                results.append(result)
                iteration += 1

        else:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Unknown loop mode: {mode}",
            )

        return NodeOutput(
            node_id=inp.node_id,
            status="completed",
            output={
                "iterations": len(results),
                "results": results,
                "mode": mode,
            },
        )

    async def _execute_iteration(
        self,
        inp: NodeInput,
        sub_node_config: dict[str, Any],
        loop_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行单次迭代(简化版:直接返回上下文,实际应调用子节点 executor)"""
        # 合并上下文
        merged_context = {**inp.context, **loop_context}

        # 如果有子节点配置,尝试执行
        if sub_node_config and "type" in sub_node_config:
            from . import get_executor

            executor_cls = get_executor(sub_node_config["type"])
            if executor_cls:
                sub_inp = NodeInput(
                    node_id=f"{inp.node_id}_iter_{loop_context.get('index', loop_context.get('iteration', 0))}",
                    node_type=sub_node_config["type"],
                    config=sub_node_config.get("config", {}),
                    context=merged_context,
                    run_id=inp.run_id,
                )
                executor = executor_cls()
                sub_output = await executor.execute_with_trace(sub_inp)
                return {
                    "status": sub_output.status,
                    "output": sub_output.output,
                    "error": sub_output.error,
                }

        return {"status": "completed", "output": loop_context, "error": ""}

    def _eval_condition(self, condition: str, context: dict[str, Any], iteration: int) -> bool:
        """评估 while 条件(安全 eval)"""
        try:
            # 使用AST白名单安全评估条件表达式（防止代码注入）
            from src.engine.workflow.dsl import evaluate_condition

            # 合并上下文和迭代变量
            store = {**context, "iteration": iteration}
            return evaluate_condition(condition, store)
        except Exception:
            return False
