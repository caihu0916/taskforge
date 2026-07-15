
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge 模板引擎 — YAML模板描述 → Flow编排图

设计决策:
  - 模板 YAML 定义 steps, 每步对应一个 Node 子类
  - 内置 Node 工厂: 常见模式(调用LLM/搜索/生成内容/审核)直接映射
  - 变量填充: {var} 占位符在运行时替换
  - 最终输出 Flow 实例, 可直接 run()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
import yaml
from pydantic import BaseModel, Field

from .flow import Context, Flow, Node

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


# ── 模板 Schema ──


class StepDef(BaseModel):
    """模板中的一步定义"""

    name: str = Field(description="步骤名 (唯一)")
    type: str = Field(default="llm_call", description="节点类型: llm_call/search/generate/review/output")
    prompt: str = Field(default="", description="提示词模板")
    role: str = Field(default="", description="执行角色")
    next: str = Field(default="", description="下一步名 (空=结束)")
    branch: dict[str, str] | None = Field(default=None, description="分支: {条件名: 目标步骤名}")
    loop_to: str = Field(default="", description="循环回跳目标")
    loop_condition: str = Field(default="", description="循环条件表达式变量名")
    output_key: str = Field(default="", description="结果写入ctx的key")

    model_config = {"populate_by_name": True}


class TemplateDef(BaseModel):
    """完整的模板定义"""

    id: str = Field(description="模板ID")
    name: str = Field(description="模板名称")
    description: str = Field(default="", description="模板描述")
    category: str = Field(default="general", description="分类")
    variables: dict[str, str] = Field(default_factory=dict, description="模板变量: {var_name: default_value}")
    steps: list[StepDef] = Field(default_factory=list, description="步骤列表")

    model_config = {"populate_by_name": True}


# ── 内置 Node 类型 ──


class LLMCallNode(Node):
    """调用 LLM 的节点"""

    def __init__(self, name: str, prompt_template: str = "", output_key: str = "", role: str = "") -> None:
        super().__init__(name)
        self.prompt_template = prompt_template
        self.output_key = output_key or name
        self.role = role

    def prep(self, ctx: Context):
        # 填充变量
        prompt = self.prompt_template
        for key, val in ctx.get("__variables__", {}).items():
            prompt = prompt.replace(f"{{{key}}}", str(val))
        # 也支持ctx里的值
        for key, val in ctx.items():
            if not key.startswith("__"):
                prompt = prompt.replace(f"{{{key}}}", str(val))
        return prompt

    def exec(self, prep_result, ctx):
        # 实际调用 LLM (这里用 mock, 真实调用在运行时注入)
        return ctx.get("__llm_mock__", f"[LLM响应: {prep_result[:30]}...]")

    def post(self, ctx, exec_result):
        ctx[self.output_key] = exec_result


class SearchNode(Node):
    """搜索节点"""

    def __init__(self, name: str, prompt_template: str = "", output_key: str = "", role: str = "") -> None:
        super().__init__(name)
        self.prompt_template = prompt_template
        self.output_key = output_key or name
        self.role = role

    def prep(self, ctx):
        query = self.prompt_template
        for key, val in ctx.items():
            if not key.startswith("__"):
                query = query.replace(f"{{{key}}}", str(val))
        return query

    def exec(self, prep_result, ctx):
        return ctx.get("__search_mock__", f"[搜索结果: {prep_result[:30]}...]")

    def post(self, ctx, exec_result):
        ctx[self.output_key] = exec_result


class ReviewNode(Node):
    """审核节点"""

    def __init__(self, name: str, prompt_template: str = "", output_key: str = "", role: str = "") -> None:
        super().__init__(name)
        self.prompt_template = prompt_template
        self.output_key = output_key or "review_result"
        self.role = role

    def prep(self, ctx):
        content = self.prompt_template
        for key, val in ctx.items():
            if not key.startswith("__"):
                content = content.replace(f"{{{key}}}", str(val))
        return content

    def exec(self, prep_result, ctx):
        return ctx.get("__review_mock__", {"approved": True, "issues": []})

    def post(self, ctx, exec_result):
        ctx[self.output_key] = exec_result


class OutputNode(Node):
    """输出节点 — 将结果整合输出"""

    def __init__(self, name: str, prompt_template: str = "", output_key: str = "", role: str = "") -> None:
        super().__init__(name)
        self.prompt_template = prompt_template
        self.output_key = output_key or "final_output"
        self.role = role

    def prep(self, ctx):
        return {k: v for k, v in ctx.items() if not k.startswith("__")}

    def exec(self, prep_result, ctx):
        if self.prompt_template:
            output = self.prompt_template
            for key, val in prep_result.items():
                output = output.replace(f"{{{key}}}", str(val))
            return output
        return str(prep_result)

    def post(self, ctx, exec_result):
        ctx[self.output_key] = exec_result


# ── Node 工厂 ──

NODE_FACTORIES: dict[str, type[Node]] = {
    "llm_call": LLMCallNode,
    "search": SearchNode,
    "generate": LLMCallNode,  # generate 和 llm_call 一样
    "review": ReviewNode,
    "output": OutputNode,
}


def _create_node(step: StepDef) -> Node:
    """从步骤定义创建节点"""
    factory = NODE_FACTORIES.get(step.type, LLMCallNode)
    return factory(
        name=step.name,
        prompt_template=step.prompt,
        output_key=step.output_key,
        role=step.role,
    )


# ── 模板引擎 ──


class TemplateEngine:
    """模板引擎 — YAML → Flow

    用法:
        engine = TemplateEngine()
        template = engine.parse_yaml(yaml_string)
        flow = engine.build_flow(template)
        ctx = engine.prepare_context(template, topic="AI Agent")
        result = flow.run(ctx)
    """

    def parse_yaml(self, yaml_str: str) -> TemplateDef:
        """解析 YAML 模板"""
        data = yaml.safe_load(yaml_str)
        if isinstance(data, dict):
            # 兼容 steps 内联
            steps = data.get("steps", [])
            if isinstance(steps, list):
                data["steps"] = [StepDef(**s) if isinstance(s, dict) else s for s in steps]
        return TemplateDef(**data)

    def parse_dict(self, data: dict[str, Any]) -> TemplateDef:
        """从 dict 创建模板"""
        steps = data.get("steps", [])
        if isinstance(steps, list):
            data["steps"] = [StepDef(**s) if isinstance(s, dict) else s for s in steps]
        return TemplateDef(**data)

    def build_flow(self, template: TemplateDef) -> Flow:
        """将模板构建为 Flow"""
        flow = Flow(name=template.id)

        if not template.steps:
            return flow

        # 创建所有节点
        nodes: dict[str, Node] = {}
        for step_def in template.steps:
            node = _create_node(step_def)
            nodes[step_def.name] = node
            flow._nodes[step_def.name] = node

        # 第一步为 start
        first_step = template.steps[0]
        flow._start_key = first_step.name

        # 建立连接
        for step_def in template.steps:
            if step_def.branch:
                # 分支
                condition_var = step_def.branch.get("__condition_var__", "branch_key")
                flow.branch(
                    step_def.name,
                    condition=self._make_branch_condition(condition_var, step_def.branch),
                    routes={k: v for k, v in step_def.branch.items() if k != "__condition_var__"},
                )
            elif step_def.loop_to:
                # 循环
                loop_cond_var = step_def.loop_condition or "should_loop"
                flow.loop_back(
                    step_def.name,
                    step_def.loop_to,
                    condition=lambda ctx, _var=loop_cond_var: ctx.get(_var, False),
                )
                # 如果还有 next, 也设置默认
                if step_def.next:
                    flow._default_next[step_def.name] = step_def.next
            elif step_def.next:
                flow._default_next[step_def.name] = step_def.next
            else:
                flow._default_next[step_def.name] = Flow.END

        logger.info("template_flow_built", template=template.id, nodes=len(nodes))
        return flow

    def prepare_context(
        self,
        template: TemplateDef,
        **variables: Any,
    ) -> Context:
        """准备上下文 — 填充模板变量"""
        ctx: Context = {"__variables__": {}}
        # 先填默认值
        for var_name, default_val in template.variables.items():
            ctx[var_name] = variables.get(var_name, default_val)
            ctx["__variables__"][var_name] = ctx[var_name]
        # 再覆盖用户变量
        for key, val in variables.items():
            ctx[key] = val
            ctx["__variables__"][key] = val
        return ctx

    @staticmethod
    def _make_branch_condition(var_name: str, branch_map: dict[str, str]) -> Callable[[Context], str]:
        """生成分支条件函数"""

        def condition(ctx: Context) -> str:
            return ctx.get(var_name, "")

        return condition
