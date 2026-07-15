
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskFlow 编排引擎 — 从 flow.py 拆出

Flow: 编排多个Node为有向图, 支持 顺序/分支/循环/并行
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from src.exceptions import AgentError

from ._flow_nodes import AsyncNode, Context, Node, Transition

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class Flow:
    END = "__end__"

    def __init__(self, name: str = "flow") -> None:
        self.name = name
        self._nodes: dict[str, Node] = {}
        self._transitions: dict[str, dict[Transition, str]] = {}
        self._default_next: dict[str, str] = {}
        self._start_key: str = ""
        self._parallel_groups: dict[str, list[str]] = {}

    def start(self, node: Node) -> Flow:
        key = node.name
        self._nodes[key] = node
        self._start_key = key
        return self

    def then(
        self,
        node: Node,
        *,
        after: str,
        transition: Callable[[Context], Transition] | None = None,
        default: str = "",
    ) -> Flow:
        key = node.name
        self._nodes[key] = node
        if transition:
            if after not in self._transitions:
                self._transitions[after] = {}
            self._transitions[after]["__func__"] = transition  # type: ignore
            self._transitions[after][key] = key
        elif default:
            self._default_next[after] = default
        else:
            self._default_next[after] = key
        return self

    def branch(
        self,
        after: str,
        *,
        condition: Callable[[Context], str],
        routes: dict[str, str],
    ) -> Flow:
        self._transitions[after] = {"__func__": condition, **routes}  # type: ignore
        return self

    def loop_back(
        self,
        from_node: str,
        to_node: str,
        *,
        condition: Callable[[Context], bool],
    ) -> Flow:
        if from_node not in self._transitions:
            self._transitions[from_node] = {}
        self._transitions[from_node]["__loop__"] = to_node  # type: ignore
        self._transitions[from_node]["__loop_cond__"] = condition  # type: ignore
        return self

    def parallel(self, group_name: str, nodes: list[Node], *, after: str = "") -> Flow:
        keys = []
        for n in nodes:
            self._nodes[n.name] = n
            keys.append(n.name)
        self._parallel_groups[group_name] = keys
        if after:
            self._default_next[after] = f"__parallel_{group_name}__"
        elif not self._start_key and keys:
            self._start_key = f"__parallel_{group_name}__"
        return self

    def run(self, ctx: Context, *, max_steps: int = 100) -> Context:
        if not self._start_key:
            raise AgentError("Flow 没有起始节点")
        current_key = self._start_key
        steps = 0
        while current_key and current_key != self.END and steps < max_steps:
            steps += 1
            parallel_target = self._find_parallel_group(current_key)
            if parallel_target:
                for nk in self._parallel_groups[parallel_target]:
                    self._nodes[nk].run(ctx)
                current_key = self._default_next.get(f"__parallel_{parallel_target}__", self.END)
                continue
            node = self._nodes.get(current_key)
            if node is None:
                break
            node.run(ctx)
            current_key = self._next(current_key, ctx)
        logger.info("flow_complete", flow=self.name, steps=steps)
        return ctx

    async def run_async(self, ctx: Context, *, max_steps: int = 100) -> Context:
        if not self._start_key:
            raise AgentError("Flow 没有起始节点")
        current_key = self._start_key
        steps = 0
        while current_key and current_key != self.END and steps < max_steps:
            steps += 1
            parallel_target = self._find_parallel_group(current_key)
            if parallel_target:
                node_keys = self._parallel_groups[parallel_target]
                tasks = []
                for nk in node_keys:
                    node = self._nodes[nk]
                    if isinstance(node, AsyncNode):
                        tasks.append(node.run_async(ctx))
                    else:
                        tasks.append(asyncio.to_thread(node.run, ctx))
                await asyncio.gather(*tasks)
                current_key = self._default_next.get(f"__parallel_{parallel_target}__", self.END)
                continue
            node = self._nodes.get(current_key)
            if node is None:
                break
            if isinstance(node, AsyncNode):
                await node.run_async(ctx)
            else:
                await asyncio.to_thread(node.run, ctx)
            current_key = self._next(current_key, ctx)
        logger.info("flow_async_complete", flow=self.name, steps=steps)
        return ctx

    def _next(self, current_key: str, ctx: Context) -> str:
        trans = self._transitions.get(current_key)
        if trans:
            loop_cond = trans.get("__loop_cond__")
            loop_target = trans.get("__loop__")
            if loop_cond and loop_target and loop_cond(ctx):
                return loop_target
            cond_func = trans.get("__func__")
            if cond_func:
                route_key = cond_func(ctx)
                return trans.get(route_key, self.END)
        return self._default_next.get(current_key, self.END)

    def _find_parallel_group(self, key: str) -> str | None:
        for g in self._parallel_groups:
            if key == f"__parallel_{g}__":
                return g
        return None

    @property
    def node_count(self) -> int:
        return len(self._nodes)
