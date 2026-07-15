
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""
nl_to_dag.py — 自然语言 → 工作流 DAG 意图解析器

3步 DAG 生成管线:
  Step1: _parse_intent  — LLM解析自然语言 → 结构化步骤列表
  Step2: _infer_edges   — 模板匹配 + LLM few-shot 推断边
  Step3: _validate_dag  — DAG 验证 (环检测 / 孤立节点 / 类型校验)

G03-T01: 意图解析器 + 节点兼容矩阵
G03-T02: 边推断 + DAG验证
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog

from src.engine.workflow.node_compat import (
    ALL_NODE_TYPES,
    EDGE_COMPAT,
    NodeType,
    is_compatible,
)

logger = structlog.get_logger(__name__)

# ── LLM JSON 输出解析 ──


def _parse_json_response(content: str) -> dict | None:
    """3阶段 JSON 提取: 直接解析 → 代码块提取 → 子串提取"""
    # Stage 1: 直接解析
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # Stage 2: 提取 ```json ... ``` 代码块
    import re

    m = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Stage 3: 找第一个 { 和最后一个 }
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ── 数据结构 ──


@dataclass
class ParsedStep:
    """解析出的单步骤"""

    type: str  # 节点类型 (ai_generate / compliance_check / ...)
    description: str  # 步骤描述
    config: dict = field(default_factory=dict)  # 步骤配置


@dataclass
class ParsedIntent:
    """意图解析结果"""

    intent: str  # 意图概述
    platforms: list[str]  # 涉及平台
    frequency: str  # 执行频率
    steps: list[ParsedStep]  # 结构化步骤列表
    variables: dict = field(default_factory=dict)  # 提取的变量
    requires_approval: bool = False  # 是否需要审批


@dataclass
class InferredEdge:
    """推断的边"""

    source: str  # 源步骤索引或类型
    target: str  # 目标步骤索引或类型
    condition: str = ""  # 条件 (pass/fail/approved/rejected)
    label: str = ""  # 边标签


@dataclass
class NL2DAGResult:
    """NL→DAG 最终结果"""

    intent: ParsedIntent
    edges: list[InferredEdge]
    valid: bool  # DAG 是否验证通过
    errors: list[str]  # 验证错误
    confidence: float  # 置信度 0.0~1.0
    needs_editing: bool  # 置信度 < 0.85 时为 True
    suggestions: list[str]  # 建议修改


# ── Step1: 意图解析 ──

INTENT_SYSTEM_PROMPT = """你是一个工作流意图解析器。用户描述一个业务流程，你需要将其解析为结构化的步骤列表。

必须以JSON格式回复，格式如下:
{
  "intent": "意图概述",
  "platforms": ["涉及平台"],
  "frequency": "执行频率",
  "steps": [
    {"type": "节点类型", "description": "步骤描述"}
  ],
  "variables": {"提取的变量名": "值"},
  "requires_approval": true/false
}

可用节点类型:
- timer: 定时触发
- webhook: Webhook触发
- ai_generate: AI内容生成
- compliance_check: 合规检查
- approval: 人工审批
- platform_publish: 平台发布
- transform: 数据转换/处理
- tool_call: 工具调用
- condition: 条件判断
- parallel: 并行分支
- aggregate: 聚合汇合

规则:
1. 每个步骤必须有type和description
2. type必须是上述可用类型之一
3. 涉及发布到平台必须先过合规检查
4. 审批环节仅当业务确实需要人工确认时添加
5. variables提取关键参数(时间、平台名、内容类型等)
"""


async def _parse_intent(nl_text: str) -> ParsedIntent:
    """
    Step1: LLM 解析自然语言 → 结构化步骤列表

    Args:
        nl_text: 用户自然语言描述

    Returns:
        ParsedIntent: 结构化意图
    """
    # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
    try:
        from src.engine.llm.router import get_llm_router
    except ImportError as e:
        raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

    router = get_llm_router()
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"解析以下业务流程:\n{nl_text}"},
    ]

    try:
        result = await router.chat(messages, profile="fast", max_tokens=2048)
        content = result.get("content", "") or result.get("response", "") or ""
    except Exception as e:
        logger.warning("intent_parse_llm_failed", error=str(e))
        # 降级: 返回基本结构
        return ParsedIntent(
            intent=nl_text[:100],
            platforms=[],
            frequency="",
            steps=[ParsedStep(type=NodeType.TRANSFORM, description=nl_text)],
            variables={},
            requires_approval=False,
        )

    parsed = _parse_json_response(content)
    if not parsed:
        logger.warning("intent_parse_json_failed", content=content[:200])
        return ParsedIntent(
            intent=nl_text[:100],
            platforms=[],
            frequency="",
            steps=[ParsedStep(type=NodeType.TRANSFORM, description=nl_text)],
        )

    # 解析步骤列表
    steps = []
    for s in parsed.get("steps", []):
        node_type = s.get("type", NodeType.TRANSFORM)
        if node_type not in ALL_NODE_TYPES:
            node_type = NodeType.TRANSFORM
        steps.append(
            ParsedStep(
                type=node_type,
                description=s.get("description", ""),
            )
        )

    return ParsedIntent(
        intent=parsed.get("intent", ""),
        platforms=parsed.get("platforms", []),
        frequency=parsed.get("frequency", ""),
        steps=steps,
        variables=parsed.get("variables", {}),
        requires_approval=parsed.get("requires_approval", False),
    )


# ── Step2: 边推断 (G03-T02 增强) ──


def _infer_edges(intent: ParsedIntent) -> list[InferredEdge]:
    """
    Step2: 边推断 — 模板匹配优先 → 顺序推断降级

    优先级:
    1. 模板库匹配: 类型签名LCS>=0.7 → 使用预定义模板边
    2. 顺序推断: 兼容矩阵+条件分支 (原有逻辑)
    """
    from src.engine.workflow.edge_templates import match_template

    steps = intent.steps
    step_types = [s.type for s in steps]

    # ── 1. 尝试模板匹配 ──
    tmpl = match_template(step_types)
    if tmpl and len(step_types) == len(tmpl.signature):
        # 仅当步骤数量与模板签名长度完全一致时，模板边的索引才能正确映射
        edges = _build_template_edges(tmpl, steps, intent.requires_approval)
        logger.info("edges_from_template", template=tmpl.name, count=len(edges))
        return edges

    # ── 2. 回退到顺序推断 ──
    return _build_sequential_edges(steps, intent.requires_approval)


def _build_template_edges(tmpl, steps: list[ParsedStep], requires_approval: bool) -> list[InferredEdge]:
    """从模板构建边列表，并按需补充审批驳回回边（模板可能已含）"""
    edges: list[InferredEdge] = []
    for e in tmpl.edges:
        edges.append(
            InferredEdge(
                source=str(e["source"]),
                target=str(e["target"]),
                condition=e.get("condition", ""),
                label=e.get("label", ""),
            )
        )
    if requires_approval:
        _add_first_approval_rejection_edge(edges, steps)
    return edges


def _build_sequential_edges(steps: list[ParsedStep], requires_approval: bool) -> list[InferredEdge]:
    """顺序推断: 兼容矩阵+条件分支，并按需补充审批驳回回边"""
    edges: list[InferredEdge] = []
    for i in range(len(steps) - 1):
        src_type = steps[i].type
        tgt_type = steps[i + 1].type

        # 检查兼容性
        rule = EDGE_COMPAT.get((src_type, tgt_type))
        if rule:
            edges.append(
                InferredEdge(
                    source=str(i),
                    target=str(i + 1),
                    condition=rule.get("condition", ""),
                    label=rule.get("label", ""),
                )
            )
        else:
            # 不兼容但顺序需要 → 标记为需人工确认
            edges.append(
                InferredEdge(
                    source=str(i),
                    target=str(i + 1),
                    condition="",
                    label=f"⚠ 不兼容: {src_type}→{tgt_type}",
                )
            )

    # 审批节点自动添加驳回回边
    if requires_approval:
        _add_all_approval_rejection_edges(edges, steps)
    return edges


def _find_rejection_target(steps: list[ParsedStep], approval_idx: int) -> int | None:
    """找到 approval 节点之前最近的 AI_GENERATE 节点索引"""
    for j in range(approval_idx - 1, -1, -1):
        if steps[j].type == NodeType.AI_GENERATE:
            return j
    return None


def _make_rejection_edge(approval_idx: int, target_idx: int) -> InferredEdge:
    """构建一条审批驳回回边"""
    return InferredEdge(
        source=str(approval_idx),
        target=str(target_idx),
        condition="rejected",
        label="驳回→重写",
    )


def _add_first_approval_rejection_edge(edges: list[InferredEdge], steps: list[ParsedStep]) -> None:
    """模板路径: 仅处理第一个 approval 节点的驳回回边 (若模板未含 rejected 边)"""
    # 检查模板是否已包含rejected边
    has_rejected = any(e.condition == "rejected" for e in edges)
    if has_rejected:
        return
    for i, step in enumerate(steps):
        if step.type == NodeType.APPROVAL and i > 0:
            target = _find_rejection_target(steps, i)
            if target is not None:
                edges.append(_make_rejection_edge(i, target))
            break


def _add_all_approval_rejection_edges(edges: list[InferredEdge], steps: list[ParsedStep]) -> None:
    """顺序路径: 处理所有 approval 节点的驳回回边"""
    for i, step in enumerate(steps):
        if step.type == NodeType.APPROVAL and i > 0:
            target = _find_rejection_target(steps, i)
            if target is not None:
                edges.append(_make_rejection_edge(i, target))


# ── Step3: DAG 验证 (G03-T02 会扩展) ──


def _validate_dag(
    steps: list[ParsedStep],
    edges: list[InferredEdge],
) -> tuple[bool, list[str]]:
    """
    Step3: DAG 验证 — 环检测 + 孤立节点 + 类型校验

    Returns:
        (is_valid, errors)
    """
    n = len(steps)
    errors: list[str] = []

    # 1. 类型校验: 检查不兼容的边
    errors.extend(_check_edge_compatibility(steps, edges, n))
    # 2. 环检测 (DFS)
    errors.extend(_check_cycles(steps, edges, n))
    # 3. 孤立节点检测 (无入边也无出边的非首节点)
    errors.extend(_check_isolated_nodes(steps, edges, n))
    # 4. 触发器入边校验: timer/webhook 不应有入边
    errors.extend(_check_trigger_incoming_edges(steps, edges, n))
    # 5. 发布节点入边校验: platform_publish 不应是首节点
    errors.extend(_check_publish_node_edges(steps, edges, n))
    # 6. 分支-汇聚配对: parallel 有出边但全图无 aggregate → 告警
    errors.extend(_check_parallel_aggregate_pairing(steps))

    return len(errors) == 0, errors


def _check_edge_compatibility(steps: list[ParsedStep], edges: list[InferredEdge], n: int) -> list[str]:
    """1. 类型校验: 检查不兼容的边"""
    errors = []
    for edge in edges:
        src_idx = int(edge.source)
        tgt_idx = int(edge.target)
        if 0 <= src_idx < n and 0 <= tgt_idx < n:
            src_type = steps[src_idx].type
            tgt_type = steps[tgt_idx].type
            if not is_compatible(src_type, tgt_type) and edge.condition != "rejected":
                # 驳回回边允许不兼容（特殊的回退边）
                errors.append(f"不兼容边: {src_type}({src_idx})→{tgt_type}({tgt_idx})")
    return errors


def _check_cycles(steps: list[ParsedStep], edges: list[InferredEdge], n: int) -> list[str]:
    """2. 环检测 (DFS) — 只对非 rejected 条件的边做环检测"""
    # 构建完整邻接表 (含 rejected 边, 保留以兼容原始逻辑)
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for edge in edges:
        try:
            src_idx = int(edge.source)
            tgt_idx = int(edge.target)
            if 0 <= src_idx < n and 0 <= tgt_idx < n:
                adj[src_idx].append(tgt_idx)
        except ValueError:
            continue

    # 只对非 rejected 条件的边做环检测
    adj_acyclic: dict[int, list[int]] = {i: [] for i in range(n)}
    for edge in edges:
        if edge.condition == "rejected":
            continue  # 驳回回边是合法的"软环"，不算DAG环
        try:
            src_idx = int(edge.source)
            tgt_idx = int(edge.target)
            if 0 <= src_idx < n and 0 <= tgt_idx < n:
                adj_acyclic[src_idx].append(tgt_idx)
        except ValueError:
            continue

    visited: set[int] = set()
    on_stack: set[int] = set()
    # Skill-Gap 1-2-1: 记录路径以返回具体循环路径
    path: list[int] = []
    cycle_paths: list[list[int]] = []

    def has_cycle(node: int) -> bool:
        visited.add(node)
        on_stack.add(node)
        path.append(node)
        for neighbor in adj_acyclic.get(node, []):
            if neighbor in on_stack:
                # 找到环 — 提取环路径
                cycle_start = path.index(neighbor)
                cycle = [*path[cycle_start:], neighbor]
                cycle_paths.append(cycle)
                return True
            if neighbor not in visited and has_cycle(neighbor):
                return True
        on_stack.discard(node)
        path.pop()
        return False

    errors = []
    for i in range(n):
        if i not in visited and has_cycle(i):
            # Skill-Gap 1-2-1: 返回具体循环路径
            for cycle in cycle_paths:
                cycle_str = " → ".join(f"{steps[idx].type}({idx})" if idx < len(steps) else str(idx) for idx in cycle)
                errors.append(f"DAG包含环: {cycle_str}")
            break
    return errors


def _compute_edge_sets(edges: list[InferredEdge]) -> tuple[set[int], set[int]]:
    """计算有入边/出边的节点集合"""
    has_incoming: set[int] = set()
    has_outgoing: set[int] = set()
    for edge in edges:
        try:
            has_outgoing.add(int(edge.source))
            has_incoming.add(int(edge.target))
        except ValueError:
            continue
    return has_incoming, has_outgoing


def _check_isolated_nodes(steps: list[ParsedStep], edges: list[InferredEdge], n: int) -> list[str]:
    """3. 孤立节点检测 (无入边也无出边的非首节点)"""
    has_incoming, has_outgoing = _compute_edge_sets(edges)
    errors = []
    for i in range(n):
        if i not in has_incoming and i not in has_outgoing and n > 1:
            errors.append(f"孤立节点: 步骤{i}({steps[i].type})无入边也无出边")
    return errors


def _check_trigger_incoming_edges(steps: list[ParsedStep], edges: list[InferredEdge], n: int) -> list[str]:
    """4. 触发器入边校验: timer/webhook 不应有入边"""
    TRIGGER_TYPES = {NodeType.TIMER, NodeType.WEBHOOK}
    errors = []
    for edge in edges:
        try:
            tgt_idx = int(edge.target)
            if 0 <= tgt_idx < n and steps[tgt_idx].type in TRIGGER_TYPES:
                src_type = steps[int(edge.source)].type if 0 <= int(edge.source) < n else "?"
                errors.append(f"结构问题: 触发器{steps[tgt_idx].type}({tgt_idx})不应有入边 (来自{src_type})")
        except ValueError:
            continue
    return errors


def _check_publish_node_edges(steps: list[ParsedStep], edges: list[InferredEdge], n: int) -> list[str]:
    """5. 发布节点入边校验: platform_publish 不应是首节点"""
    has_incoming, _ = _compute_edge_sets(edges)
    errors = []
    for i in range(n):
        if steps[i].type == NodeType.PLATFORM_PUBLISH and i not in has_incoming and n > 1:
            errors.append(f"结构问题: 发布节点({i})缺少入边，不能作为流程起点")
    return errors


def _check_parallel_aggregate_pairing(steps: list[ParsedStep]) -> list[str]:
    """6. 分支-汇聚配对: parallel 有出边但全图无 aggregate → 告警"""
    has_parallel = any(s.type == NodeType.PARALLEL for s in steps)
    has_aggregate = any(s.type == NodeType.AGGREGATE for s in steps)
    if has_parallel and not has_aggregate:
        return ["结构问题: 存在parallel分支但缺少aggregate聚合节点"]
    return []


# ── 主入口 ──


async def nl_to_dag(nl_text: str) -> NL2DAGResult:
    """
    自然语言 → 工作流 DAG

    Args:
        nl_text: 用户自然语言描述

    Returns:
        NL2DAGResult: 完整的 DAG 生成结果
    """
    # Step1: 意图解析
    intent = await _parse_intent(nl_text)
    logger.info("intent_parsed", intent=intent.intent, steps=len(intent.steps))

    # Step2: 边推断
    edges = _infer_edges(intent)
    logger.info("edges_inferred", count=len(edges))

    # Step3: DAG 验证
    valid, errors = _validate_dag(intent.steps, edges)

    # 置信度评估
    incompat_count = sum(1 for e in edges if e.label.startswith("⚠"))
    total_edges = len(edges) if edges else 1
    confidence = max(0.0, 1.0 - (incompat_count / total_edges) * 0.5)
    if not valid:
        confidence *= 0.7

    return NL2DAGResult(
        intent=intent,
        edges=edges,
        valid=valid,
        errors=errors,
        confidence=round(confidence, 2),
        needs_editing=confidence < 0.85,
        suggestions=[] if valid else [f"修复: {e}" for e in errors],
    )
