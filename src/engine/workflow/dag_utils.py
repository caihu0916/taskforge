
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Skill-Gap 1-2-1: DAG 循环检测算法增强

提供通用的 DAG 循环检测工具，支持：
1. 拓扑排序检测循环
2. 返回具体循环路径
3. 高性能（100 节点 < 100ms）
4. 支持多种环形模式识别

使用场景：
- 工作流编辑器保存时验证
- NL-to-DAG 解析时验证
- 节点连接时实时验证
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def detect_cycle_dfs(
    nodes: list[Any],
    edges: list[tuple[int, int]],
) -> list[list[int]]:
    """DFS 检测环并返回所有循环路径

    Args:
        nodes: 节点列表（仅用于获取数量）
        edges: 边列表 [(source_idx, target_idx), ...]

    Returns:
        循环路径列表，每个路径是节点索引列表 [n1, n2, ..., n1]
    """
    n = len(nodes)
    adj: dict[int, list[int]] = defaultdict(list)
    for src, tgt in edges:
        if 0 <= src < n and 0 <= tgt < n:
            adj[src].append(tgt)

    visited: set[int] = set()
    on_stack: set[int] = set()
    path: list[int] = []
    cycles: list[list[int]] = []

    def dfs(node: int) -> None:
        visited.add(node)
        on_stack.add(node)
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor in on_stack:
                # 找到环 — 提取环路径
                cycle_start = path.index(neighbor)
                cycle = [*path[cycle_start:], neighbor]
                cycles.append(cycle)
            elif neighbor not in visited:
                dfs(neighbor)
        on_stack.discard(node)
        path.pop()

    for i in range(n):
        if i not in visited:
            dfs(i)

    return cycles


def detect_cycle_bfs(
    nodes: list[Any],
    edges: list[tuple[int, int]],
) -> bool:
    """BFS（Kahn 算法）检测是否存在环

    更快但只返回是否存在环，不返回路径。

    Args:
        nodes: 节点列表
        edges: 边列表

    Returns:
        True 如果存在环，False 否则
    """
    n = len(nodes)
    in_degree = [0] * n
    adj: dict[int, list[int]] = defaultdict(list)
    for src, tgt in edges:
        if 0 <= src < n and 0 <= tgt < n:
            adj[src].append(tgt)
            in_degree[tgt] += 1

    # 入度为 0 的节点入队
    queue = deque([i for i in range(n) if in_degree[i] == 0])
    visited_count = 0

    while queue:
        node = queue.popleft()
        visited_count += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 如果访问的节点数 < 总节点数，说明存在环
    return visited_count < n


def validate_dag(
    nodes: list[Any],
    edges: list[tuple[int, int]],
    node_label_fn: Callable[[int, Any], str] | None = None,
) -> tuple[bool, list[str]]:
    """验证 DAG，返回是否有效和错误信息列表

    Args:
        nodes: 节点列表
        edges: 边列表 [(source_idx, target_idx), ...]
        node_label_fn: 可选的节点标签函数，用于生成可读的循环路径

    Returns:
        (is_valid, errors): 是否有效，错误信息列表
    """
    errors: list[str] = []
    n = len(nodes)

    if n == 0:
        return True, []

    # 1. 索引范围校验
    for src, tgt in edges:
        if not (0 <= src < n and 0 <= tgt < n):
            errors.append(f"边索引越界: ({src}, {tgt})，节点数={n}")

    # 2. 环检测（DFS，返回路径）
    cycles = detect_cycle_dfs(nodes, edges)
    for cycle in cycles:
        if node_label_fn:
            cycle_str = " → ".join(node_label_fn(idx, nodes[idx]) for idx in cycle if idx < n)
        else:
            cycle_str = " → ".join(str(idx) for idx in cycle)
        errors.append(f"DAG包含环: {cycle_str}")

    # 3. 孤立节点检测（无入边也无出边）
    if n > 1:
        has_incoming = set()
        has_outgoing = set()
        for src, tgt in edges:
            has_outgoing.add(src)
            has_incoming.add(tgt)
        for i in range(n):
            if i not in has_incoming and i not in has_outgoing:
                label = node_label_fn(i, nodes[i]) if node_label_fn else str(i)
                errors.append(f"孤立节点: {label}")

    return len(errors) == 0, errors


def find_cycle_path(
    nodes: list[Any],
    edges: list[tuple[int, int]],
) -> list[int] | None:
    """查找并返回第一个循环路径

    Args:
        nodes: 节点列表
        edges: 边列表

    Returns:
        第一个循环路径（节点索引列表），无环时返回 None
    """
    cycles = detect_cycle_dfs(nodes, edges)
    return cycles[0] if cycles else None


def has_cycle(nodes: list[Any], edges: list[tuple[int, int]]) -> bool:
    """快速判断是否存在环（使用 Kahn 算法）

    Args:
        nodes: 节点列表
        edges: 边列表

    Returns:
        True 如果存在环
    """
    return detect_cycle_bfs(nodes, edges)
