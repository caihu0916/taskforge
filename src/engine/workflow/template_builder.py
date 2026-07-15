
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 模板阶段构建"""

from __future__ import annotations

import structlog

from src.engine.workflow.models import (
    Phase,
    PhaseType,
    Step,
)

logger = structlog.get_logger(__name__)


def build_phases_from_template(engine, template_id: str) -> list[Phase]:
    """从模板加载步骤并映射到PDCA四阶段

    模板 steps 按 action 语义自动归入 Plan/Do/Check/Act:
      - search/review → Plan 或 Check
      - llm_call (含 hitmaker/boss/researcher) → Plan
      - llm_call (含 deal_hunter/hitmaker/butler/accountant) → Do 或 Act
      - output → Act
    """
    try:
        from pathlib import Path

        import yaml

        from src.infra.template.registry import get_template_registry

        reg = get_template_registry()
        manifest = reg.get(template_id)
        if manifest is None or not manifest.template_dir:
            return _resolve_template_from_library(template_id, engine)

        yaml_path = Path(manifest.template_dir) / "template.yaml"
        if not yaml_path.exists():
            return engine._build_default_phases()

        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_phases = data.get("phases")
        if raw_phases and isinstance(raw_phases, dict):
            return _build_phases_from_yaml_phases(raw_phases, engine)

        raw_steps = data.get("steps", [])
        if not raw_steps:
            return engine._build_default_phases()

        return _build_phases_from_raw_steps(raw_steps)
    except Exception as e:
        logger.warning("template_phases_build_failed", template_id=template_id, error=str(e), exc_info=True)
        return engine._build_default_phases()


def _resolve_template_from_library(template_id: str, engine) -> list[Phase]:
    """Fallback: 查询内存中的 template_library，找不到时回退到默认阶段"""
    phases = _build_phases_from_library(template_id, engine)
    if phases is not None:
        return phases
    logger.warning("template_not_found_for_workflow", id=template_id)
    return engine._build_default_phases()


def _build_phases_from_raw_steps(raw_steps: list) -> list[Phase]:
    """将原始 steps 列表按 type/位置比例分类后构建 PDCA phases"""
    plan_steps, do_steps, check_steps, act_steps = _classify_raw_steps(raw_steps)

    if not check_steps:
        check_steps.append(Step(name="合规检查", agent_role="compliance", action="审核内容合规性"))

    phases = _build_phases_from_step_lists(
        [
            (PhaseType.PLAN, plan_steps),
            (PhaseType.DO, do_steps),
            (PhaseType.CHECK, check_steps),
            (PhaseType.ACT, act_steps),
        ]
    )

    _fill_missing_phases(phases)
    _sort_phases_by_pdca_order(phases)
    return phases


def _classify_raw_steps(raw_steps: list) -> tuple[list[Step], list[Step], list[Step], list[Step]]:
    """按 type 和位置比例将 raw_steps 分类到 plan/do/check/act"""
    plan_steps: list[Step] = []
    do_steps: list[Step] = []
    check_steps: list[Step] = []
    act_steps: list[Step] = []

    n = len(raw_steps)
    for i, s in enumerate(raw_steps):
        step = Step(
            name=s.get("name", f"步骤{i + 1}"),
            agent_role=s.get("role", s.get("agent_role", "boss")),
            action=s.get("action", s.get("prompt", "")[:80]),
            description=s.get("prompt", "")[:200],
        )
        stype = s.get("type", "")
        if stype == "search":
            plan_steps.append(step)
        elif stype == "review":
            check_steps.append(step)
        elif stype == "output":
            act_steps.append(step)
        else:
            _classify_by_ratio(i, n, step, plan_steps, do_steps, act_steps)

    return plan_steps, do_steps, check_steps, act_steps


def _classify_by_ratio(i: int, n: int, step: Step, plan_steps: list, do_steps: list, act_steps: list) -> None:
    """按位置比例分类步骤到 plan/do/act（无明确 type 时）"""
    ratio = i / max(n - 1, 1)
    if ratio < 0.3:
        plan_steps.append(step)
    elif ratio < 0.7:
        do_steps.append(step)
    else:
        act_steps.append(step)


def _build_phases_from_step_lists(step_lists) -> list[Phase]:
    """从 (phase_type, steps) 列表构建 phases，跳过空 steps"""
    phases = []
    for pt, steps in step_lists:
        if steps:
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=steps, on_failure=on_failure))
    return phases


def _fill_missing_phases(phases: list[Phase]) -> None:
    """补齐缺失的 PDCA 阶段（使用默认模板步骤）"""
    from src.engine.workflow.creation import PHASE_STEP_TEMPLATES

    existing_types = {p.phase_type for p in phases}
    for pt in PhaseType:
        if pt not in existing_types:
            default_steps = [
                Step(name=s["name"], agent_role=s["agent_role"], action=s["action"])
                for s in PHASE_STEP_TEMPLATES.get(pt, [])
            ]
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=default_steps, on_failure=on_failure))


def _sort_phases_by_pdca_order(phases: list[Phase]) -> None:
    """按 PDCA 顺序排序 phases"""
    order = {PhaseType.PLAN: 0, PhaseType.DO: 1, PhaseType.CHECK: 2, PhaseType.ACT: 3}
    phases.sort(key=lambda p: order[p.phase_type])


def _build_phases_from_yaml_phases(raw_phases: dict, engine) -> list[Phase]:
    """从 YAML 中的 phases 定义直接构建 PDCA Phase 列表

    YAML phases 结构:
      phases:
        plan:
          steps: [{name, type, prompt, role, ...}]
        do:
          steps: [...]
        check:
          loop_to: plan
          steps: [...]
        act:
          loop_back: plan
          steps: [...]
    """
    from src.engine.workflow.creation import PHASE_STEP_TEMPLATES

    phase_map = {"plan": PhaseType.PLAN, "do": PhaseType.DO, "check": PhaseType.CHECK, "act": PhaseType.ACT}
    phases: list[Phase] = []

    for phase_key, phase_type in phase_map.items():
        phase_data = raw_phases.get(phase_key)
        if not phase_data or not isinstance(phase_data, dict):
            continue

        steps_data = phase_data.get("steps") or []
        steps: list[Step] = []
        for i, s in enumerate(steps_data):
            step = Step(
                name=s.get("name", f"步骤{i + 1}"),
                agent_role=s.get("role", s.get("agent_role", "boss")),
                action=s.get("action", s.get("prompt", "")[:80]),
                description=s.get("prompt", "")[:200],
            )
            steps.append(step)

        if steps:
            on_failure = "retry_plan" if phase_type == PhaseType.CHECK else "advance"
            loop_back = phase_data.get("loop_back", "")
            phase_data.get("loop_to", "")
            phase_name = phase_key.upper()
            if loop_back:
                phase_name = f"{phase_key.upper()}→{loop_back.upper()}"
            phase = Phase(phase_type=phase_type, name=phase_name, steps=steps, on_failure=on_failure)
            phases.append(phase)

    existing_types = {p.phase_type for p in phases}
    for pt in PhaseType:
        if pt not in existing_types:
            default_steps = [
                Step(name=s["name"], agent_role=s["agent_role"], action=s["action"])
                for s in PHASE_STEP_TEMPLATES.get(pt, [])
            ]
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=default_steps, on_failure=on_failure))

    order = {PhaseType.PLAN: 0, PhaseType.DO: 1, PhaseType.CHECK: 2, PhaseType.ACT: 3}
    phases.sort(key=lambda p: order[p.phase_type])

    logger.info("yaml_phases_built", phase_count=len(phases))
    return phases


def _build_phases_from_library(template_id: str, engine) -> list[Phase] | None:
    """从 template_library 内存字典构建 phases（文件系统注册表查不到时的 fallback）

    template_library.py 中的模板定义格式：
      {"phases": [{"phase": "plan", "name": "xxx", "steps": [...]}]}
    """
    from src.engine.workflow.template_library import get_template

    tpl = get_template(template_id)
    if tpl is None or "phases" not in tpl:
        return None

    phase_map = {"plan": PhaseType.PLAN, "do": PhaseType.DO, "check": PhaseType.CHECK, "act": PhaseType.ACT}
    phases: list[Phase] = []

    for phase_def in tpl["phases"]:
        pt_str = phase_def.get("phase", "").lower()
        pt = phase_map.get(pt_str)
        if pt is None:
            continue

        steps: list[Step] = []
        for s in phase_def.get("steps", []):
            steps.append(
                Step(
                    name=s.get("action", s.get("name", "")),
                    agent_role=s.get("role", "boss"),
                    action=s.get("action", ""),
                    description=s.get("action", "")[:200],
                )
            )

        if steps:
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=steps, on_failure=on_failure))

    if not phases:
        return None

    # 补齐缺失的阶段
    existing_types = {p.phase_type for p in phases}
    from src.engine.workflow.creation import PHASE_STEP_TEMPLATES

    for pt in PhaseType:
        if pt not in existing_types:
            default_steps = [
                Step(name=s["name"], agent_role=s["agent_role"], action=s["action"])
                for s in PHASE_STEP_TEMPLATES.get(pt, [])
            ]
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=default_steps, on_failure=on_failure))

    order = {PhaseType.PLAN: 0, PhaseType.DO: 1, PhaseType.CHECK: 2, PhaseType.ACT: 3}
    phases.sort(key=lambda p: order[p.phase_type])

    logger.info("template_library_phases_built", template_id=template_id, phase_count=len(phases))
    return phases
