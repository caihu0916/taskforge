
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge VariablePool + Jinja2 模板引擎 — Dify 对标实现

三层变量存储:
  global   — 系统级常量 (公司名、日期、版本等)，跨工作流共享
  workflow — 当前工作流级变量 (客户ID、合同金额等)，在创建时注入
  steps    — 步骤级变量 (step_id → {output, status, ...})，在步骤完成后写入

语法支持:
  {{ path.to.var }}                        — 简单变量访问 (兼容 Dify)
  {{ var | filter(args) }}                 — Jinja2 Filter 管道
  {% if cond %}...{% elif %}...{% endif %} — 条件块
  {% for x in list %}...{% endfor %}       — 循环块
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------- 轻量级变量访问器 (不依赖 Jinja2) ----------

_DOT_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")


def _dot_lookup(data: dict[str, Any], path: str, default: str = "") -> Any:
    """按点号路径查找嵌套 dict 值。"""
    parts = path.split(".")
    cur: Any = data
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# ---------- 自定义 Jinja2 Filters ----------


def _tf_upper(value: Any) -> str:
    return str(value).upper()


def _tf_lower(value: Any) -> str:
    return str(value).lower()


def _tf_truncate(value: Any, length: int = 50) -> str:
    s = str(value)
    return s if len(s) <= length else s[:length] + "..."


def _tf_json(value: Any, indent: int | None = None) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=indent)
    except Exception:
        return str(value)


def _tf_money(value: Any, symbol: str = "¥") -> str:
    try:
        num = float(value)
        return f"{symbol}{num:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _tf_date(value: Any = None, fmt: str = "%Y-%m-%d") -> str:
    dt = value if isinstance(value, datetime) else datetime.now(UTC)
    return dt.strftime(fmt)


def _tf_default(value: Any, default_val: Any = "") -> Any:
    return value if value not in (None, "", [], {}) else default_val


_CUSTOM_FILTERS: dict[str, Any] = {
    "upper": _tf_upper,
    "lower": _tf_lower,
    "truncate": _tf_truncate,
    "json": _tf_json,
    "money": _tf_money,
    "date": _tf_date,
    "default": _tf_default,
    "int": lambda v: int(v) if v not in (None, "") else 0,
    "float": lambda v: float(v) if v not in (None, "") else 0.0,
    "len": lambda v: len(v) if hasattr(v, "__len__") else 0,
    "round": lambda v, n=2: round(float(v), n) if v not in (None, "") else 0,
}


# ---------- VariablePool ----------


class VariablePool:
    """三层变量池 + 表达式渲染。"""

    def __init__(
        self,
        global_vars: dict[str, Any] | None = None,
        workflow_vars: dict[str, Any] | None = None,
        step_vars: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.global_vars: dict[str, Any] = global_vars or {}
        self.workflow_vars: dict[str, Any] = workflow_vars or {}
        self.step_vars: dict[str, dict[str, Any]] = step_vars or {}
        # 运行时统计
        self._render_count: int = 0
        self._last_errors: list[str] = []

    # ── 设置/读取 ──

    def set_global(self, key: str, value: Any) -> None:
        self.global_vars[key] = value

    def set_workflow(self, key: str, value: Any) -> None:
        self.workflow_vars[key] = value

    def set_step_output(self, step_id: str, output: Any) -> None:
        self.step_vars.setdefault(step_id, {})["output"] = output
        self.step_vars[step_id]["status"] = "completed"

    def get(self, dot_path: str) -> Any:
        """按路径读取。支持 steps.{step_id}.output.{key} 语法。"""
        if dot_path.startswith("steps."):
            rest = dot_path[len("steps.") :]  # e.g. "step_001.output.risk"
            return _dot_lookup(self.step_vars, rest)
        if dot_path in self.workflow_vars:
            return self.workflow_vars[dot_path]
        if dot_path in self.global_vars:
            return self.global_vars[dot_path]
        # 支持 "workflow.xxx" / "global.xxx" 前缀
        if dot_path.startswith("workflow."):
            return _dot_lookup(self.workflow_vars, dot_path[len("workflow.") :])
        if dot_path.startswith("global."):
            return _dot_lookup(self.global_vars, dot_path[len("global.") :])
        return None

    # ── 合并为统一 dict (给 Jinja2 用) ──

    def to_context(self) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        ctx.update(self.global_vars)
        ctx.update(self.workflow_vars)
        ctx["steps"] = self.step_vars
        ctx["workflow"] = self.workflow_vars
        ctx["global"] = self.global_vars
        return ctx

    # ── 渲染: 先走轻量 {{var}} 替换，失败/含复杂语法再走 Jinja2 ──

    def resolve(self, template: str | None) -> str:
        """渲染模板字符串。失败时返回原模板(不阻塞主流程)。"""
        if template is None:
            return ""
        if not isinstance(template, str):
            try:
                return str(template)
            except Exception:
                return ""
        if "{{" not in template and "{%" not in template:
            return template

        self._render_count += 1
        context = self.to_context()

        # 优先: 轻量 {{var}} 替换 (不依赖 Jinja2)
        if "{%" not in template:
            try:
                return self._resolve_lightweight(template, context)
            except Exception as e:
                logger.debug("exception_handled", error=str(e))
                self._last_errors.append(f"lightweight: {e}")
                logger.debug("variable_pool_lightweight_failed", error=str(e))

        # 回退: Jinja2 (若可用)
        try:
            return self._resolve_jinja2(template, context)
        except ImportError:
            # 连 Jinja2 都没有：尽力替换简单 {{var}}，返回原文
            return self._resolve_naive(template, context)
        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            self._last_errors.append(f"jinja2: {e}")
            logger.warning("variable_pool_render_failed", error=str(e), template_preview=template[:100])
            return template

    def resolve_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """递归渲染 dict 中的字符串值。"""
        out: dict[str, Any] = {}
        for k, v in d.items():
            if isinstance(v, str):
                out[k] = self.resolve(v)
            elif isinstance(v, dict):
                out[k] = self.resolve_dict(v)
            elif isinstance(v, list):
                out[k] = [
                    self.resolve_dict(x) if isinstance(x, dict) else self.resolve(x) if isinstance(x, str) else x
                    for x in v
                ]
            else:
                out[k] = v
        return out

    # ── 辅助 ──

    def _resolve_lightweight(self, template: str, context: dict[str, Any]) -> str:
        """纯 Python 实现 {{path.to.var | filter | filter2(args)}} 替换。"""

        def repl(m: re.Match[str]) -> str:
            expr = m.group(1).strip()  # "customer_name | upper | truncate(20)"
            parts = [p.strip() for p in expr.split("|")]
            value: Any = self._lookup_by_path(parts[0], context)
            for raw_filter_part in parts[1:]:
                filter_part = raw_filter_part.strip()
                if not filter_part:
                    continue
                value = self._apply_filter(filter_part, value)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return "" if value is None else str(value)

        # 支持 {{ 变量 | filter | filter2(args) }}
        pattern = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
        return pattern.sub(repl, template)

    def _lookup_by_path(self, path: str, context: dict[str, Any]) -> Any:
        """智能查找变量：先按完整路径，失败则在 context 中做字典点号查找。"""
        # 直接查找 self.get 语义 (支持 steps.xxx / workflow.xxx / global.xxx)
        val = self.get(path)
        if val is not None:
            return val
        # 回退: context dict 点号查找
        return _dot_lookup(context, path, default="")

    def _apply_filter(self, filter_expr: str, value: Any) -> Any:
        """应用 filter: "truncate(20)" → func(value, 20); "upper" → func(value)"""
        m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\((.*)\))?$", filter_expr)
        if not m:
            return value
        fname = m.group(1)
        args_str = m.group(2) or ""
        args: list[Any] = []
        kwargs: dict[str, Any] = {}
        if args_str.strip():
            for raw_token in self._split_csv(args_str):
                token = raw_token.strip()
                if "=" in token and not token.startswith('"') and not token.startswith("'"):
                    k, v = token.split("=", 1)
                    kwargs[k.strip()] = self._parse_literal(v.strip())
                else:
                    args.append(self._parse_literal(token))
        func = _CUSTOM_FILTERS.get(fname)
        if func is None:
            logger.debug("variable_pool_unknown_filter", filter=fname)
            return value
        try:
            return func(value, *args, **kwargs)
        except Exception as e:
            logger.debug("variable_pool_filter_error", filter=fname, error=str(e))
            return value

    @staticmethod
    def _split_csv(s: str) -> list[str]:
        """简单 CSV 拆分 (支持引号)。用于 filter 参数解析。"""
        parts: list[str] = []
        cur = ""
        quote = ""
        for ch in s:
            if quote:
                if ch == quote:
                    quote = ""
                else:
                    cur += ch
            elif ch in ('"', "'"):
                quote = ch
            elif ch == ",":
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur:
            parts.append(cur)
        return parts

    @staticmethod
    def _parse_literal(s: str) -> Any:
        s = s.strip()
        if s in ("true", "True"):
            return True
        if s in ("false", "False"):
            return False
        if s in ("null", "None", ""):
            return None
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s

    # ── Jinja2 实现 (可选依赖) ──

    def _resolve_jinja2(self, template: str, context: dict[str, Any]) -> str:
        from jinja2 import Environment, StrictUndefined, Undefined

        env = Environment(
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )
        env.filters.update(_CUSTOM_FILTERS)
        tpl = env.from_string(template)
        try:
            return tpl.render(**context)
        except Exception as e:
            logger.warning("variable_pool_jinja2_strict_failed", error=str(e))
            # 降级: 用宽松 Undefined (未定义变量渲染为空字符串)
            env.undefined = Undefined
            tpl2 = env.from_string(template)
            return tpl2.render(**context)

    def _resolve_naive(self, template: str, context: dict[str, Any]) -> str:
        """连 Jinja2 都不可用时的最轻量替换 (仅 {{path.to.var}})。"""

        def repl(m: re.Match[str]) -> str:
            path = m.group(1).strip()
            val = self._lookup_by_path(path, context)
            return "" if val is None else str(val)

        return _DOT_PATTERN.sub(repl, template)

    # ── 调试/序列化 ──

    def snapshot(self) -> dict[str, Any]:
        return {
            "global": self.global_vars,
            "workflow": self.workflow_vars,
            "steps": self.step_vars,
            "render_count": self._render_count,
            "last_errors": self._last_errors[-5:],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariablePool:
        return cls(
            global_vars=data.get("global"),
            workflow_vars=data.get("workflow"),
            step_vars=data.get("steps"),
        )

    def __repr__(self) -> str:
        return f"VariablePool(global={len(self.global_vars)}, workflow={len(self.workflow_vars)}, steps={len(self.step_vars)})"


# ---------- 便捷工厂 ----------


def create_default_pool(workflow_id: str = "", **extra: Any) -> VariablePool:
    """创建带默认全局变量的 VariablePool。"""
    now = datetime.now(UTC)
    global_vars = {
        "company_name": "TaskForge Inc.",
        "today": now.strftime("%Y-%m-%d"),
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "year": now.year,
        "workflow_id": workflow_id,
    }
    global_vars.update(extra)
    return VariablePool(global_vars=global_vars)


# ---------- 单例 Registry (多工作流共享全局变量) ----------


class VariablePoolRegistry:
    """工作流级 VariablePool 注册表。"""

    def __init__(self, shared_global: dict[str, Any] | None = None) -> None:
        self._shared: dict[str, Any] = shared_global or {}
        self._pools: dict[str, VariablePool] = {}

    def get_or_create(self, workflow_id: str) -> VariablePool:
        if workflow_id not in self._pools:
            self._pools[workflow_id] = create_default_pool(workflow_id=workflow_id, **self._shared)
        return self._pools[workflow_id]

    def set_shared(self, key: str, value: Any) -> None:
        self._shared[key] = value
        for pool in self._pools.values():
            pool.set_global(key, value)


# 全局共享注册表 (用于跨工作流的全局常量)
_global_registry = VariablePoolRegistry()


def get_global_registry() -> VariablePoolRegistry:
    return _global_registry
