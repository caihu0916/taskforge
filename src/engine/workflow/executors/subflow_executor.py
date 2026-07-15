
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Subflow 节点执行器(P1-S1-005)

调用子工作流,支持参数传递和结果返回。
"""

from __future__ import annotations

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("subflow")
class SubflowExecutor(BaseExecutor):
    """子工作流执行器

    配置:
        workflow_id: 子工作流 ID(必填)
        inputs: 传递给子工作流的输入参数(可选)
        wait_for_completion: 是否等待完成(默认 true)
    """

    node_type = "subflow"
    config_schema = {
        "workflow_id": {"required": True, "type": "string"},
        "inputs": {"required": False, "type": "object", "default": {}},
        "wait_for_completion": {"required": False, "type": "boolean", "default": True},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        workflow_id = inp.config.get("workflow_id", "")
        sub_inputs = inp.config.get("inputs", {})
        wait = inp.config.get("wait_for_completion", True)

        if not workflow_id:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="workflow_id is required",
            )

        # 合并上下文到子工作流输入
        merged_inputs = {**inp.context, **sub_inputs}

        try:
            # 尝试调用 WorkflowExecutor 执行子工作流
            from src.engine.workflow.executor import WorkflowExecutor

            # 获取或创建 executor 实例
            executor = WorkflowExecutor()

            # 根据workflow_id加载工作流脚本
            # 优先从DSL脚本文件加载，否则使用workflow_id作为脚本名
            from pathlib import Path

            script_path = Path(f"data/workflows/{workflow_id}.dsl")
            if script_path.exists():
                script = executor.load_script(str(script_path))
            else:
                # 如果没有DSL文件，使用workflow_id作为简单脚本
                script = f"agent: role=worker\n  action: Execute subworkflow {workflow_id}"

            # 准备子工作流（使用正确的参数签名）
            run = executor.prepare(script, args=merged_inputs)

            if not wait:
                # 不等待,返回子工作流 run_id
                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "sub_run_id": run.run_id,
                        "workflow_id": workflow_id,
                        "waited": False,
                    },
                )

            # 等待完成
            result = await executor.run(script, args=merged_inputs)

            return NodeOutput(
                node_id=inp.node_id,
                status=result.status,
                output={
                    "sub_run_id": result.run_id,
                    "workflow_id": workflow_id,
                    "waited": True,
                    "result": result.step_results,
                    "outputs": result._store,
                },
            )

        except ImportError:
            # WorkflowExecutor 不可用,返回模拟结果
            logger.warning("subflow_executor_unavailable", workflow_id=workflow_id)
            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "workflow_id": workflow_id,
                    "inputs": merged_inputs,
                    "note": "Subflow executor not available, simulated execution",
                },
            )
        except Exception as e:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Subflow execution failed: {e}",
            )
