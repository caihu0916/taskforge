
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""DataTransform 节点执行器(P1-S1-010)

数据转换节点,支持 map/filter/reduce/flatten 等操作。
"""

from __future__ import annotations

from typing import Any

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)


@register_executor("data_transform")
class DataTransformExecutor(BaseExecutor):
    """数据转换执行器

    配置:
        operation: 操作类型(map | filter | reduce | flatten | sort | group_by | unique)
        input_key: 输入数据在 context 中的 key(或直接 input 字段)
        input: 直接输入数据(可选,覆盖 input_key)
        expression: 转换表达式(map/filter 用,支持 lambda)
        key_extractor: 键提取表达式(group_by/sort 用)
        initial: reduce 初始值
    """

    node_type = "data_transform"
    config_schema = {
        "operation": {"required": True, "type": "string"},
        "input_key": {"required": False, "type": "string", "default": ""},
        "input": {"required": False, "type": "any", "default": None},
        "expression": {"required": False, "type": "string", "default": ""},
        "key_extractor": {"required": False, "type": "string", "default": ""},
        "initial": {"required": False, "type": "any", "default": None},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        operation = inp.config.get("operation", "")
        input_key = inp.config.get("input_key", "")
        input_data = inp.config.get("input")

        # 获取输入数据
        if input_data is None and input_key:
            input_data = inp.context.get(input_key)

        if input_data is None:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error="No input data (set 'input' or 'input_key')",
            )

        if not isinstance(input_data, list):
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Input must be a list, got {type(input_data).__name__}",
            )

        try:
            result = self._apply_operation(operation, input_data, inp.config, inp.context)
            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "operation": operation,
                    "input_count": len(input_data),
                    "output": result,
                    "output_count": len(result) if isinstance(result, (list, dict)) else 1,
                },
            )
        except Exception as e:
            return NodeOutput(
                node_id=inp.node_id,
                status="failed",
                error=f"Data transform failed: {type(e).__name__}: {e}",
            )

    def _apply_operation(
        self,
        operation: str,
        data: list[Any],
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        dispatch = {
            "map": self._op_map,
            "filter": self._op_filter,
            "reduce": self._op_reduce,
            "flatten": self._op_flatten,
            "sort": self._op_sort,
            "group_by": self._op_group_by,
            "unique": self._op_unique,
        }
        handler = dispatch.get(operation)
        if handler is None:
            raise ValueError(f"Unknown operation: {operation}")
        return handler(data, config, context)

    def _op_map(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        expression = config.get("expression", "")
        if not expression:
            raise ValueError("expression is required for map")
        fn = self._make_lambda(expression)
        return [fn(item) for item in data]

    def _op_filter(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        expression = config.get("expression", "")
        if not expression:
            raise ValueError("expression is required for filter")
        fn = self._make_lambda(expression)
        return [item for item in data if fn(item)]

    def _op_reduce(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        expression = config.get("expression", "")
        if not expression:
            raise ValueError("expression is required for reduce")
        fn = self._make_lambda(expression)
        from functools import reduce

        return reduce(fn, data, config.get("initial"))

    def _op_flatten(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        result: list[Any] = []
        for item in data:
            if isinstance(item, list):
                result.extend(item)
            else:
                result.append(item)
        return result

    def _op_sort(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        key_extractor = config.get("key_extractor", "")
        if key_extractor:
            key_fn = self._make_lambda(key_extractor)
            return sorted(data, key=key_fn)
        return sorted(data)

    def _op_group_by(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        key_extractor = config.get("key_extractor", "")
        if not key_extractor:
            raise ValueError("key_extractor is required for group_by")
        key_fn = self._make_lambda(key_extractor)
        groups: dict[str, list[Any]] = {}
        for item in data:
            key = str(key_fn(item))
            groups.setdefault(key, []).append(item)
        return groups

    def _op_unique(self, data: list[Any], config: dict[str, Any], context: dict[str, Any]) -> Any:
        key_extractor = config.get("key_extractor", "")
        if key_extractor:
            return self._unique_by_key(data, key_extractor)
        # 简单去重(不可哈希的转为 str)
        return self._unique_simple(data)

    def _unique_by_key(self, data: list[Any], key_extractor: str) -> list[Any]:
        key_fn = self._make_lambda(key_extractor)
        seen: set[Any] = set()
        result = []
        for item in data:
            key = key_fn(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _unique_simple(self, data: list[Any]) -> list[Any]:
        seen_str: set[str] = set()
        result = []
        for item in data:
            key = str(item)
            if key not in seen_str:
                seen_str.add(key)
                result.append(item)
        return result

    def _make_lambda(self, expr: str):
        """从表达式创建 lambda 函数

        支持格式:
            "x: x * 2"  →  lambda x: x * 2
            "x, y: x + y"  →  lambda x, y: x + y

        使用AST白名单确保安全性
        """
        import ast as ast_module

        # 白名单允许的AST节点类型
        allowed_nodes = (
            ast_module.Expression,
            ast_module.Lambda,
            ast_module.arguments,
            ast_module.arg,
            ast_module.Name,
            ast_module.Load,
            ast_module.BinOp,
            ast_module.Add,
            ast_module.Sub,
            ast_module.Mult,
            ast_module.Div,
            ast_module.Mod,
            ast_module.Pow,
            ast_module.FloorDiv,
            ast_module.Compare,
            ast_module.Lt,
            ast_module.LtE,
            ast_module.Gt,
            ast_module.GtE,
            ast_module.Eq,
            ast_module.NotEq,
            ast_module.BoolOp,
            ast_module.And,
            ast_module.Or,
            ast_module.UnaryOp,
            ast_module.Not,
            ast_module.USub,
            ast_module.Constant,
            ast_module.IfExp,
            ast_module.List,
            ast_module.Dict,
            ast_module.Tuple,
            ast_module.Set,
            ast_module.ListComp,
            ast_module.SetComp,
            ast_module.DictComp,
            ast_module.comprehension,
        )

        if expr.startswith("lambda "):
            lambda_expr = expr
        elif ":" in expr:
            params, body = expr.split(":", 1)
            params = params.strip()
            body = body.strip()
            lambda_expr = f"lambda {params}: {body}"
        else:
            raise ValueError(f"Invalid lambda expression: {expr}")

        # 解析并验证AST
        try:
            tree = ast_module.parse(lambda_expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Syntax error in lambda expression: {e}") from e

        # 验证所有节点都在白名单中
        for node in ast_module.walk(tree):
            if not isinstance(node, allowed_nodes):
                raise ValueError(f"Forbidden AST node type: {type(node).__name__}")

        # 安全执行
        safe_globals = {"__builtins__": {}}
        return eval(compile(tree, "<lambda>", "eval"), safe_globals)
