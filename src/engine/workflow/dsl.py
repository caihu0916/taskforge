
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Workflow DSL 解析器 + PDCA 编译器 (对标 v2.1.168 WorkflowInput/WorkflowOutput)

两层:
  1. parse_workflow_script(source) → WorkflowScript  (DSL → 中间表示)
  2. compile_to_pdca(script) → Workflow              (中间表示 → PDCA模型)

支持原语: agent() / parallel() / pipeline() / phase()
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.engine.workflow.models import Phase as PDCAPhase
    from src.engine.workflow.models import Step as PDCAStep

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class WorkflowPhase:
    title: str = ""
    detail: str = ""


@dataclass
class WorkflowStep:
    type: str = ""  # agent | parallel | pipeline | phase | if_else | loop | switch
    prompt: str = ""
    opts: dict = field(default_factory=dict)
    children: list[WorkflowStep] = field(default_factory=list)
    # ── 条件分支字段 (Phase 1.1) ──
    condition: str = ""  # 条件表达式
    branch_true: list[WorkflowStep] = field(default_factory=list)  # then分支 / loop body
    branch_false: list[WorkflowStep] = field(default_factory=list)  # else分支
    cases: dict[str, list[WorkflowStep]] = field(default_factory=dict)  # switch cases
    default_branch: list[WorkflowStep] = field(default_factory=list)  # switch default


@dataclass
class WorkflowScript:
    name: str = ""
    description: str = ""
    phases: list[WorkflowPhase] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)


# ── 解析入口 ──


def parse_workflow_script(source: str) -> WorkflowScript:
    """解析 Workflow DSL 脚本 → WorkflowScript 中间表示"""
    meta = _extract_meta(source)
    steps = _extract_steps(source)
    phases = [
        WorkflowPhase(**p) if isinstance(p, dict) else WorkflowPhase(title=str(p)) for p in meta.get("phases", [])
    ]

    return WorkflowScript(
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        phases=phases,
        steps=steps,
    )


# ── meta 解析 ──


def _extract_meta(source: str) -> dict:
    """提取 export const meta = {...} — 支持多行嵌套"""
    match = re.search(r"export\s+const\s+meta\s*=\s*(\{.*?\})\s*\n\s*\w+\(", source, re.DOTALL)
    if not match:
        # 也匹配 } 后面没有函数调用/有分号的情况
        match = re.search(r"export\s+const\s+meta\s*=\s*(\{.*?\})\s*[;\n]", source, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1)
    # 去注释
    raw = re.sub(r"//[^\n]*", "", raw)
    # 处理无引号key + 单引号转双引号 (先处理值中的单引号, 再处理key)
    raw = re.sub(r"'([^']*)'", r'"\1"', raw)
    raw = re.sub(r"(\w+):", r'"\1":', raw)
    # 移除尾部逗号
    raw = re.sub(r",\s*}", "}", raw)
    raw = re.sub(r",\s*]", "]", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ── 步骤提取 ──


def _extract_steps(source: str) -> list[WorkflowStep]:
    """提取 agent()/parallel()/pipeline()/phase() 调用 — 保持源码顺序"""
    all_calls: list[tuple[int, WorkflowStep]] = []
    # 先找 parallel/pipeline 块 → 记录内部区间, 防止 agent() 重复提取
    container_spans: list[tuple[int, int]] = []

    _extract_parallel_blocks(source, all_calls, container_spans)
    _extract_pipeline_blocks(source, all_calls, container_spans)
    # agent("prompt", {...}) — 排除容器内的
    _extract_agent_calls(source, all_calls, container_spans)
    # phase("title", {detail: "..."}) — 排除容器内的
    _extract_phase_calls(source, all_calls, container_spans)
    # ── Phase 1.1 条件分支原语 ──
    _extract_if_else_blocks(source, all_calls, container_spans)
    _extract_loop_blocks(source, all_calls, container_spans)
    _extract_switch_blocks(source, all_calls, container_spans)

    # 按源码位置排序
    all_calls.sort(key=lambda x: x[0])
    return [call[1] for call in all_calls]


def _is_inside_container(pos: int, container_spans: list[tuple[int, int]]) -> bool:
    """判断位置是否落在已记录的容器区间内"""
    return any(start <= pos < end for start, end in container_spans)


def _extract_parallel_blocks(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 parallel() 块"""
    for m in re.finditer(r"parallel\(\s*\[(.*?)\]\s*\)", source, re.DOTALL):
        children = _extract_children(m.group(1))
        all_calls.append(
            (m.start(), WorkflowStep(type="parallel", prompt=f"parallel x{len(children)}", children=children))
        )
        container_spans.append((m.start(), m.end()))


def _extract_pipeline_blocks(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 pipeline() 块"""
    for m in re.finditer(r"pipeline\(\s*\[(.*?)\]\s*\)", source, re.DOTALL):
        children = _extract_children(m.group(1))
        all_calls.append(
            (m.start(), WorkflowStep(type="pipeline", prompt=f"pipeline x{len(children)}", children=children))
        )
        container_spans.append((m.start(), m.end()))


def _extract_agent_calls(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 agent() 调用 — 排除容器内的"""
    for m in re.finditer(r'agent\(\s*["\']([^"\']*)["\']\s*(?:,\s*(\{[^}]*\}))?\s*\)', source):
        if _is_inside_container(m.start(), container_spans):
            continue
        prompt = m.group(1)
        opts_str = m.group(2) if m.lastindex and m.lastindex >= 2 else "{}"
        all_calls.append((m.start(), WorkflowStep(type="agent", prompt=prompt, opts=_parse_opts(opts_str or "{}"))))


def _extract_phase_calls(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 phase() 调用 — 排除容器内的"""
    for m in re.finditer(r'phase\(\s*["\']([^"\']*)["\']\s*(?:,\s*(\{[^}]*\}))?\s*\)', source):
        if _is_inside_container(m.start(), container_spans):
            continue
        title = m.group(1)
        opts_str = m.group(2) if m.lastindex and m.lastindex >= 2 else "{}"
        opts = _parse_opts(opts_str or "{}")
        all_calls.append((m.start(), WorkflowStep(type="phase", prompt=title, opts=opts)))


def _extract_if_else_blocks(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 if_else() 块

    if_else("描述", {condition: "...", then: agent("A"), else: agent("B")})
    注意: condition可能含 {{var}} 有 }，用 (.*?) 非贪婪+DOTALL 而非 [^}]*
    """
    for m in re.finditer(
        r'if_else\(\s*["\']([^"\']*)["\']\s*,\s*\{(.*?)\}\s*\)',
        source,
        re.DOTALL,
    ):
        if _is_inside_container(m.start(), container_spans):
            continue
        prompt = m.group(1)
        body = m.group(2)
        condition = _extract_key_value(body, "condition")
        then_part, else_part = _split_then_else(body)
        then_children = _extract_children(then_part)
        else_children = _extract_children(else_part)
        all_calls.append(
            (
                m.start(),
                WorkflowStep(
                    type="if_else",
                    prompt=prompt,
                    condition=condition,
                    branch_true=then_children,
                    branch_false=else_children,
                ),
            )
        )
        container_spans.append((m.start(), m.end()))


def _split_then_else(body: str) -> tuple[str, str]:
    """从 if_else body 中切分 then/else 部分

    先按 else 切分，避免 then 分支吞掉 else 内容
    """
    if "else:" in body:
        then_part = body.split("else:", maxsplit=1)[0]
        else_part = body.rsplit("else:", maxsplit=1)[-1]
    else:
        then_part = body
        else_part = ""
    # then_part 里去掉 "then:" 前缀
    if "then:" in then_part:
        then_part = then_part.split("then:")[-1]
    return then_part, else_part


def _extract_loop_blocks(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 loop() 块

    loop("描述", {max_iterations: N, exit_condition: "...", body: agent("...")})
    注意: exit_condition可能含 {{var}} 有 }，用 (.*?) 非贪婪+DOTALL 而非 [^}]*
    """
    for m in re.finditer(
        r'loop\(\s*["\']([^"\']*)["\']\s*,\s*\{(.*?)\}\s*\)',
        source,
        re.DOTALL,
    ):
        if _is_inside_container(m.start(), container_spans):
            continue
        prompt = m.group(1)
        body = m.group(2)
        condition = _extract_key_value(body, "exit_condition")
        max_iter_str = _extract_key_value(body, "max_iterations")
        max_iter = int(max_iter_str) if max_iter_str and max_iter_str.isdigit() else 10
        body_children = _extract_children(body.split("body:")[-1] if "body:" in body else "")
        all_calls.append(
            (
                m.start(),
                WorkflowStep(
                    type="loop",
                    prompt=prompt,
                    condition=condition,
                    opts={"max_iterations": max_iter},
                    branch_true=body_children,  # loop body in branch_true
                ),
            )
        )
        container_spans.append((m.start(), m.end()))


def _extract_switch_blocks(
    source: str,
    all_calls: list[tuple[int, WorkflowStep]],
    container_spans: list[tuple[int, int]],
) -> None:
    """提取 switch() 块

    switch("描述", {on: "...", cases: {...}, default: agent("...")})
    """
    for m in re.finditer(
        r'switch\(\s*["\']([^"\']*)["\']\s*,\s*\{(.*?)\}\s*\)',
        source,
        re.DOTALL,
    ):
        if _is_inside_container(m.start(), container_spans):
            continue
        prompt = m.group(1)
        body = m.group(2)
        on_var = _extract_key_value(body, "on")
        cases = _extract_switch_cases(body)
        default_children = []
        if "default:" in body:
            default_children = _extract_children(body.split("default:")[-1])
        all_calls.append(
            (
                m.start(),
                WorkflowStep(
                    type="switch",
                    prompt=prompt,
                    condition=on_var,  # on 变量存在 condition 字段
                    cases=cases,
                    default_branch=default_children,
                ),
            )
        )
        container_spans.append((m.start(), m.end()))


def _extract_switch_cases(body: str) -> dict[str, list[WorkflowStep]]:
    """提取 switch body 中的 cases (跳过 on/default 键)"""
    cases: dict[str, list[WorkflowStep]] = {}
    for cm in re.finditer(r'["\']([^"\']+)["\']\s*:\s*agent\(\s*["\']([^"\']*)["\']', body):
        case_key = cm.group(1)
        if case_key in ("on", "default"):
            continue
        cases[case_key] = [WorkflowStep(type="agent", prompt=cm.group(2))]
    return cases


def evaluate_condition(condition: str, store: dict[str, Any]) -> bool:
    """安全评估条件表达式

    支持: 变量比较 (> < >= <= == !=)、逻辑运算 (and or not)
    模板变量: {{key}} 从store中替换
    仅允许AST白名单节点，防止代码注入
    """
    # 1. 替换模板变量
    expr = condition
    for k, v in store.items():
        expr = expr.replace(f"{{{{{k}}}}}", json.dumps(v) if isinstance(v, (dict, list)) else str(v))

    # 2. 白名单安全eval（仅允许比较+逻辑运算）
    allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.Compare,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Eq,
        ast.NotEq,
        ast.Load,
        ast.USub,  # 允许负数如 -1
    )
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"不支持的表达式节点: {type(node).__name__} in '{expr}'")

    # 3. 收集裸变量名 → 从 store 构建 locals
    bare_names: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in store:
            bare_names[node.id] = store[node.id]

    # 4. 编译执行（白名单保证安全性）
    return bool(eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, bare_names))


def _extract_key_value(body: str, key: str) -> str:
    """从 if_else/loop/switch 的 body 字符串中提取指定 key 的值

    支持:
      - key: "string_value"   → 返回 string_value
      - key: bare_word        → 返回 bare_word (如 max_iterations: 5)
    """
    # 优先匹配带引号的值: key: "value" 或 key: 'value'
    m = re.search(rf'{key}\s*:\s*["\']([^"\']*)["\']', body)
    if m:
        return m.group(1)
    # 其次匹配无引号的值: key: value (到逗号/右花括号为止)
    m = re.search(rf"{key}\s*:\s*([^\s,}}]+)", body)
    if m:
        return m.group(1)
    return ""


def _extract_children(block: str) -> list[WorkflowStep]:
    """提取 parallel/pipeline 块中的子调用 (agent/phase)"""
    children = []
    for m in re.finditer(r'agent\(\s*["\']([^"\']*)["\']\s*(?:,\s*(\{[^}]*\}))?\s*\)', block):
        prompt = m.group(1)
        opts = _parse_opts(m.group(2) if m.lastindex and m.lastindex >= 2 else "{}")
        children.append(WorkflowStep(type="agent", prompt=prompt, opts=opts))
    for m in re.finditer(r'phase\(\s*["\']([^"\']*)["\']\s*(?:,\s*(\{[^}]*\}))?\s*\)', block):
        title = m.group(1)
        opts = _parse_opts(m.group(2) if m.lastindex and m.lastindex >= 2 else "{}")
        children.append(WorkflowStep(type="phase", prompt=title, opts=opts))
    return children


def _parse_opts(opts_str: str) -> dict:
    """解析 opts 对象字符串为 dict"""
    opts = {}
    for m in re.finditer(r'(\w+):\s*["\']([^"\']*)["\']', opts_str):
        opts[m.group(1)] = m.group(2)
    # 也支持无引号值
    for m in re.finditer(r"(\w+):\s*(true|false|\d+)", opts_str):
        val = m.group(2)
        if val == "true":
            opts[m.group(1)] = True
        elif val == "false":
            opts[m.group(1)] = False
        else:
            opts[m.group(1)] = int(val)
    return opts


# ── DS元 → PDCA 编译器 ──


def compile_to_pdca(
    source: str | WorkflowScript,
    args: dict[str, Any] | None = None,
) -> object:
    """将 WorkflowScript 编译为 PDCA Workflow 模型

    Args:
        source: DSL 字符串或已解析的 WorkflowScript
        args: 运行时参数 (注入到 Step action 模板)

    Returns:
        Workflow (PDCA 模型), 含 Plan/Do/Check/Act 阶段
    """
    from src.engine.workflow.models import Workflow

    wf_script = parse_workflow_script(source) if isinstance(source, str) else source
    args = args or {}

    # 1. 对齐 meta.phases 到 PDCA Phase 元数据
    plan_info, check_info, act_info = _find_pdca_meta_phases(wf_script.phases)

    # 2. 按 phase() 边界分组 steps → DO phases
    do_phases = _compile_do_phases(wf_script, args)

    # 3. 构建完整 PDCA Workflow
    phases = _build_pdca_phases(do_phases, plan_info, check_info, act_info)

    return Workflow(
        name=wf_script.name or "workflow",
        description=wf_script.description,
        phases=phases,
    )


def _find_pdca_meta_phases(
    meta_phases: list[WorkflowPhase],
) -> tuple[WorkflowPhase | None, WorkflowPhase | None, WorkflowPhase | None]:
    """对齐 meta.phases 到 PDCA Phase 元数据"""
    plan_info = next((p for p in meta_phases if p.title.lower() in ("plan", "review")), None)
    check_info = next((p for p in meta_phases if p.title.lower() in ("check", "verify")), None)
    act_info = next((p for p in meta_phases if p.title.lower() in ("act", "synthesize")), None)
    return plan_info, check_info, act_info


def _compile_do_phases(wf_script: WorkflowScript, args: dict[str, Any]) -> list[PDCAPhase]:
    """按 phase() 边界分组 steps → DO phases"""
    do_phases: list[PDCAPhase] = []
    current_phase_steps: list[PDCAStep] = []
    current_phase_name = ""

    for ws in wf_script.steps:
        if ws.type == "phase":
            # 遇到 phase() → 保存当前组, 开始新组
            if current_phase_steps:
                do_phases.append(_build_do_phase(current_phase_name, current_phase_steps))
            current_phase_name = ws.prompt
            current_phase_steps = []
            continue

        phase = _compile_step_to_phase(ws, args)
        if phase is not None:
            do_phases.append(phase)
        else:
            # agent step
            current_phase_steps.append(_step_from_dsl(ws, args))

    # 保存最后一组
    if current_phase_steps:
        do_phases.append(_build_do_phase(current_phase_name, current_phase_steps))

    return do_phases


def _compile_step_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase | None:
    """将单个步骤编译为 DO Phase (parallel/pipeline/if_else/loop/switch). 返回 None 表示 agent step"""
    dispatch = {
        "parallel": _compile_parallel_to_phase,
        "pipeline": _compile_pipeline_to_phase,
        "if_else": _compile_if_else_to_phase,
        "loop": _compile_loop_to_phase,
        "switch": _compile_switch_to_phase,
    }
    compiler = dispatch.get(ws.type)
    if compiler is None:
        return None
    return compiler(ws, args)


def _compile_parallel_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase:
    """parallel → 所有子step在同一Phase内并发"""
    from src.engine.workflow.models import Phase, PhaseType

    child_steps = _convert_children(ws.children, args)
    return Phase(
        phase_type=PhaseType.DO,
        name=ws.prompt,
        steps=child_steps,
    )


def _compile_pipeline_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase:
    """pipeline → 子步骤串行"""
    from src.engine.workflow.models import Phase, PhaseType

    child_steps = _convert_children(ws.children, args)
    return Phase(
        phase_type=PhaseType.DO,
        name=ws.prompt,
        steps=child_steps,
    )


def _compile_if_else_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase:
    """if_else → true分支→Phase A, false分支→Phase B; condition记入每个Step"""
    from src.engine.workflow.models import Phase, PhaseType

    true_steps = _convert_children(ws.branch_true, args)
    for s in true_steps:
        s.condition = ws.condition
        s.branch_id = "then"
    false_steps = _convert_children(ws.branch_false, args)
    for s in false_steps:
        s.condition = ws.condition
        s.branch_id = "else"
    return Phase(
        phase_type=PhaseType.DO,
        name=f"[if_else] {ws.prompt}",
        steps=true_steps + false_steps,
    )


def _compile_loop_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase:
    """loop → body编译为Phase，condition/max_iterations记入Step"""
    from src.engine.workflow.models import Phase, PhaseType

    body_steps = _convert_children(ws.branch_true, args)
    for s in body_steps:
        s.condition = ws.condition
        s.branch_id = "loop_body"
        s.params["max_iterations"] = ws.opts.get("max_iterations", 10)
    return Phase(
        phase_type=PhaseType.DO,
        name=f"[loop] {ws.prompt}",
        steps=body_steps,
    )


def _compile_switch_to_phase(ws: WorkflowStep, args: dict[str, Any]) -> PDCAPhase:
    """switch → 每个case编译为Phase内的Step，condition记入"""
    from src.engine.workflow.models import Phase, PhaseType

    switch_steps: list = []
    for case_key, case_children in ws.cases.items():
        case_steps = _convert_children(case_children, args)
        for s in case_steps:
            s.condition = ws.condition
            s.branch_id = f"case_{case_key}"
        switch_steps.extend(case_steps)
    default_steps = _convert_children(ws.default_branch, args)
    for s in default_steps:
        s.condition = ws.condition
        s.branch_id = "default"
    switch_steps.extend(default_steps)
    return Phase(
        phase_type=PhaseType.DO,
        name=f"[switch] {ws.prompt}",
        steps=switch_steps,
    )


def _build_pdca_phases(
    do_phases: list[PDCAPhase],
    plan_info: WorkflowPhase | None,
    check_info: WorkflowPhase | None,
    act_info: WorkflowPhase | None,
) -> list[PDCAPhase]:
    """构建完整 PDCA Workflow phases 列表"""
    from src.engine.workflow.models import Phase, PhaseType

    phases: list[Phase] = []

    # FIX-015: 仅创建有内容的PDCA阶段，避免空阶段瞬间通过
    # Plan Phase — 仅当DSL提供了plan信息或步骤时创建
    if plan_info and (plan_info.title or plan_info.detail):
        phases.append(
            Phase(
                phase_type=PhaseType.PLAN,
                name=plan_info.title or "Plan",
                description=plan_info.detail or "",
            )
        )

    # Do Phase(s) — 从 DSL steps
    phases.extend(do_phases)

    # Check Phase — 仅当DSL提供了check信息或步骤时创建
    if check_info and (check_info.title or check_info.detail):
        phases.append(
            Phase(
                phase_type=PhaseType.CHECK,
                name=check_info.title or "Check",
                description=check_info.detail or "",
            )
        )

    # Act Phase — 仅当DSL提供了act信息或步骤时创建
    if act_info and (act_info.title or act_info.detail):
        phases.append(
            Phase(
                phase_type=PhaseType.ACT,
                name=act_info.title or "Act",
                description=act_info.detail or "",
            )
        )

    return phases


def _build_do_phase(name: str, steps: list[PDCAStep]) -> PDCAPhase:
    """构建 DO Phase"""
    from src.engine.workflow.models import Phase, PhaseType

    return Phase(
        phase_type=PhaseType.DO,
        name=name or "Do",
        steps=steps,
    )


def _step_from_dsl(ws: WorkflowStep, args: dict[str, Any]) -> PDCAStep:
    """将单个 WorkflowStep (agent type) 转为 PDCA Step"""
    from src.engine.workflow.models import Step

    prompt = ws.prompt
    # 模板替换: {{key}} → args[key]
    for k, v in args.items():
        prompt = prompt.replace(f"{{{{{k}}}}}", str(v))
    role = ws.opts.get("role", "butler")
    return Step(
        name=f"{role}: {prompt[:50]}",
        description=prompt,
        agent_role=role,
        action=prompt,
    )


def _convert_children(children: list[WorkflowStep], args: dict[str, Any]) -> list[PDCAStep]:
    """将 children (list[WorkflowStep]) 转为 list[PDCA Step]"""
    result = []
    for child in children:
        if child.type == "agent":
            result.append(_step_from_dsl(child, args))
        elif child.type == "phase":
            # phase inside parallel/pipeline — skipped (acts as label only)
            continue
    return result
