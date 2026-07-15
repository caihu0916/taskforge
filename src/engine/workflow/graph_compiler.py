
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Graph DSL → PDCA 编译器 — 将可视化画布 DAG 编译为可执行的 PDCA 工作流

核心逻辑:
  1. 解析 Graph DSL JSON (nodes + edges)
  2. 拓扑排序: 从 trigger 节点出发，BFS 遍历 DAG
  3. 节点映射:
     - trigger   → 不生成 Step (纯入口标记)
     - action    → Step (agent_role + action)
     - approval  → Step (requires_approval=True)
     - condition → 不生成 Step, 但其出边 label 决定下游 step 的 condition/branch_id
  4. 分组策略: 按拓扑层分组为 DO phases (条件分支的 then/else 分到同一 Phase)
  5. 输出: 完整的 Plan/Do/Check/Act phases

编译保证:
  - condition 节点的每条出边 data.label 写入下游 Step.branch_id
  - condition 节点的 data.expression 写入下游 Step.condition
  - approval 节点的 data.approver/timeoutMinutes 写入 Step.params
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import structlog

from src.engine.workflow.models import (
    Phase,
    PhaseType,
    Step,
    Workflow,
)

logger = structlog.get_logger(__name__)


def compile_graph_to_pdca(
    graph_dsl: str | dict,
    workflow_name: str = "",
    workflow_description: str = "",
) -> Workflow:
    """将 Graph DSL 编译为 PDCA Workflow

    Args:
        graph_dsl: JSON 字符串或已解析的 dict，格式:
            {
              "nodes": [{id, type, data: {kind, label, ...}, position}],
              "edges": [{id, source, target, sourceHandle, data: {label}}],
              "variables": {...},
              "metadata": {name, description, version}
            }
        workflow_name: 覆盖名称 (空则取 metadata.name)
        workflow_description: 覆盖描述 (空则取 metadata.description)

    Returns:
        Workflow (PDCA 模型), 含完整 phases
    """
    if isinstance(graph_dsl, str):
        try:
            graph = json.loads(graph_dsl)
        except json.JSONDecodeError as e:
            raise ValueError(f"graph_dsl JSON 解析失败: {e}") from e
    else:
        graph = graph_dsl

    nodes_list = graph.get("nodes", [])
    edges_list = graph.get("edges", [])
    meta = graph.get("metadata", {})

    # ── 索引构建 ──
    node_map: dict[str, dict] = {n["id"]: n for n in nodes_list}
    # source_id → [edge, ...]
    out_edges: dict[str, list[dict]] = {}
    # target_id → [edge, ...]
    in_edges: dict[str, list[dict]] = {}
    for e in edges_list:
        src = e.get("source", "")
        tgt = e.get("target", "")
        out_edges.setdefault(src, []).append(e)
        in_edges.setdefault(tgt, []).append(e)

    # ── 拓扑排序 (BFS from trigger) ──
    sorted_ids = _topo_sort(nodes_list, out_edges, in_edges)

    # ── 生成 Steps ──
    steps: list[Step] = []
    for nid in sorted_ids:
        node = node_map.get(nid)
        if node is None:
            continue
        ndata = node.get("data", {})
        kind = ndata.get("kind", "")

        # trigger 不生成 Step
        if kind == "trigger":
            continue

        # condition 不直接生成 Step，但需要记住其表达式供下游使用
        if kind == "condition":
            continue

        # 从入边推断 condition 和 branch_id
        condition, branch_id = _infer_condition_from_in_edges(nid, in_edges, node_map)

        step = _build_step(nid, ndata, kind, condition, branch_id)
        steps.append(step)

    # ── 分组为 DO Phases ──
    do_phases = _group_steps_to_phases(steps)

    # ── 构建完整 PDCA ──
    phases: list[Phase] = [
        Phase(phase_type=PhaseType.PLAN, name="Plan", description=""),
    ]
    phases.extend(do_phases)
    phases.append(Phase(phase_type=PhaseType.CHECK, name="Check", description=""))
    phases.append(Phase(phase_type=PhaseType.ACT, name="Act", description=""))

    name = workflow_name or meta.get("name", "workflow")
    description = workflow_description or meta.get("description", "")

    return Workflow(name=name, description=description, phases=phases)


# ── 内部工具函数 ──


def _topo_sort(
    nodes: list[dict],
    out_edges: dict[str, list[dict]],
    in_edges: dict[str, list[dict]],
) -> list[str]:
    """从 trigger 节点出发的 BFS 拓扑排序

    确保上游节点排在下游节点前面。
    """
    # 入度计算
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for n in nodes:
        nid = n["id"]
        for e in in_edges.get(nid, []):
            src = e.get("source", "")
            if src in in_degree:
                # 只计算来自 nodes 内部的边
                pass
        # 实际入度 = 来自 nodes 内部的入边数
        count = 0
        for e in in_edges.get(nid, []):
            src = e.get("source", "")
            if src in in_degree:
                count += 1
        in_degree[nid] = count

    # 找 trigger 节点 (或入度为 0 的节点) 作为起点
    queue: deque[str] = deque()
    for n in nodes:
        nid = n["id"]
        ndata = n.get("data", {})
        if ndata.get("kind") == "trigger" or in_degree[nid] == 0:
            queue.append(nid)

    result: list[str] = []
    visited: set[str] = set()

    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        result.append(nid)

        for e in out_edges.get(nid, []):
            tgt = e.get("target", "")
            if tgt in in_degree and tgt not in visited:
                in_degree[tgt] -= 1
                if in_degree[tgt] <= 0:
                    queue.append(tgt)

    # 残余节点 (孤岛/环路) 追加
    for n in nodes:
        if n["id"] not in visited:
            result.append(n["id"])

    return result


def _infer_condition_from_in_edges(
    node_id: str,
    in_edges: dict[str, list[dict]],
    node_map: dict[str, dict],
) -> tuple[str, str]:
    """从入边推断 condition 和 branch_id

    规则:
      - 如果上游是 condition 节点，且边有 label (如 'true'/'false'/'case_xxx'):
        branch_id = 边的 label
        condition = 根据分支标签决定:
          - 'true' 分支: 直接使用 condition 节点的 expression
          - 'false' 分支: 取反表达式 → "not (expression)"
          - 其他标签: 使用 "expression AND branch == 'label'" 形式
      - 如果多个 condition 上游 (并列路径)，取第一个非空 condition
      - 否则: condition="", branch_id=""
    """
    edges_in = in_edges.get(node_id, [])
    condition = ""
    branch_id = ""

    for e in edges_in:
        src_id = e.get("source", "")
        src_node = node_map.get(src_id)
        if src_node is None:
            continue
        src_data = src_node.get("data", {})
        src_kind = src_data.get("kind", "")

        if src_kind == "condition":
            # 从边获取分支标签
            edge_data = e.get("data", {})
            edge_label = edge_data.get("label", "") if edge_data else ""
            # sourceHandle 也可能携带分支信息
            if not edge_label:
                edge_label = e.get("sourceHandle", "")

            if not branch_id and edge_label:
                branch_id = edge_label
                # 根据分支标签组合 condition
                raw_expression = src_data.get("expression", "")
                if not condition and raw_expression:
                    if edge_label == "true":
                        # true 分支: 保持原表达式
                        condition = raw_expression
                    elif edge_label == "false":
                        # false 分支: 自动取反
                        condition = f"not ({raw_expression})"
                    else:
                        # 其他标签 (case_xxx): 表达式 + 分支匹配
                        condition = raw_expression

    return condition, branch_id


def _build_step(
    node_id: str,
    ndata: dict[str, Any],
    kind: str,
    condition: str,
    branch_id: str,
) -> Step:
    """从节点 data 构建 PDCA Step"""
    label = ndata.get("label", "")
    description = ndata.get("description", "")

    if kind == "approval":
        approver = ndata.get("approver", "")
        timeout_minutes = ndata.get("timeoutMinutes", 60)
        return Step(
            id=node_id,
            name=label or "审批",
            description=description,
            agent_role=approver or "human",
            action=f"审批: {description}" if description else f"审批: {label}",
            requires_approval=True,
            condition=condition,
            branch_id=branch_id,
            params={
                "approver": approver,
                "timeout_minutes": timeout_minutes,
            },
        )

    # kind == "action"
    agent_role = ndata.get("agentRole", "boss")
    action = ndata.get("action", "")
    output_schema_str = ndata.get("outputSchema", "")

    params: dict[str, Any] = {}
    if output_schema_str:
        params["output_schema_str"] = output_schema_str

    return Step(
        id=node_id,
        name=label or f"{agent_role}: {action[:50]}" if action else label or "步骤",
        description=description,
        agent_role=agent_role,
        action=action or label,
        condition=condition,
        branch_id=branch_id,
        params=params,
    )


def _group_steps_to_phases(steps: list[Step]) -> list[Phase]:
    """将编译后的 Steps 分组为 DO Phases

    分组策略:
      - 同一条件分支 (由同一 condition 节点产生的 true/false) → 同一 Phase
      - 无条件的连续步骤组成一个 Phase
      - 不同条件节点或条件 vs 无条件 → 新 Phase

    判断 "同一条件分组" 的依据:
      branch_id 为 true/false 的步骤, 若其 condition 同源
      (true 分支: "expr", false 分支: "not (expr)"), 归入同一 Phase
    """
    if not steps:
        return [Phase(phase_type=PhaseType.DO, name="Do", steps=[])]

    def _condition_family(cond: str) -> str:
        """提取条件族: 去除 not () 包裹得到同源表达式"""
        if cond.startswith("not (") and cond.endswith(")"):
            return cond[5:-1]  # "not (amount > 10000)" → "amount > 10000"
        return cond

    phases: list[Phase] = []
    current_steps: list[Step] = []
    current_family: str = ""  # 当前条件族 (同源表达式)

    for step in steps:
        step_family = _condition_family(step.condition) if step.condition else ""

        # 是否需要开启新 Phase:
        # 1. 当前有积累的 steps
        # 2. 新 step 有条件族
        # 3. 当前也有条件族
        # 4. 新 step 的条件族与当前族不同 (非同源)
        if current_steps and step_family and current_family and step_family != current_family:
            # 不同源条件切换 → 保存当前 Phase
            phases.append(
                Phase(
                    phase_type=PhaseType.DO,
                    name=f"Do ({current_family[:30]})" if current_family else "Do",
                    steps=current_steps,
                )
            )
            current_steps = []
            current_family = step_family
        elif step.condition:
            if not current_family:
                current_family = step_family

        current_steps.append(step)

    # 最后一组
    if current_steps:
        phases.append(
            Phase(
                phase_type=PhaseType.DO,
                name=f"Do ({current_family[:30]})" if current_family else "Do",
                steps=current_steps,
            )
        )

    return phases
