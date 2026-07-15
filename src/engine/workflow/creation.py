
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 工作流创建与阶段构建"""

from __future__ import annotations

from typing import Any

import structlog

from src.engine.workflow.models import (
    Phase,
    PhaseType,
    Step,
    StepStatus,
    Workflow,
)

logger = structlog.get_logger(__name__)

PHASE_STEP_TEMPLATES: dict[PhaseType, list[dict[str, str]]] = {
    PhaseType.PLAN: [
        {"name": "目标定义", "agent_role": "boss", "action": "明确本轮PDCA的核心目标和关键指标"},
        {"name": "情报收集", "agent_role": "researcher", "action": "收集市场数据和竞品动态"},
        {"name": "方案制定", "agent_role": "boss", "action": "制定执行方案和资源配置"},
    ],
    PhaseType.DO: [
        {"name": "内容生产", "agent_role": "hitmaker", "action": "按计划产出内容和素材"},
        {"name": "客户触达", "agent_role": "deal_hunter", "action": "主动触达潜在客户, 推进转化"},
        {"name": "服务交付", "agent_role": "support", "action": "处理客户需求和售后问题"},
    ],
    PhaseType.CHECK: [
        {"name": "数据复盘", "agent_role": "boss", "action": "分析执行数据, 计算ROI和转化率"},
        {"name": "合规检查", "agent_role": "compliance", "action": "审核内容和流程合规性"},
    ],
    PhaseType.ACT: [
        {"name": "决策调整", "agent_role": "boss", "action": "基于复盘结果做出策略调整决策"},
        {"name": "财务确认", "agent_role": "accountant", "action": "核对本轮收支和账单"},
    ],
}


class CreationMixin:
    """工作流创建和阶段构建方法"""

    def create_workflow(
        self,
        name: str,
        description: str = "",
        template_id: str = "",
        scenario_workflow_id: str = "",
        scenario_id: str = "",
        custom_phases: list[Phase] | None = None,
    ) -> Workflow:
        if custom_phases:
            phases = custom_phases
        elif scenario_workflow_id:
            phases = self._build_from_scenario_workflow(scenario_workflow_id, scenario_id=scenario_id or None)
        elif template_id:
            phases = self._build_phases_from_template(template_id)
        else:
            phases = self._build_default_phases(scenario_id=scenario_id or None)

        wf = Workflow(
            name=name,
            description=description,
            phases=phases,
            template_id=template_id or scenario_workflow_id,
        )
        self._wf_mgr.create(wf)
        logger.info(
            "workflow_created", id=wf.id, name=name, template_id=template_id or scenario_workflow_id or "default"
        )
        return wf

    def _build_phases_from_template(self, template_id: str) -> list[Phase]:
        from src.engine.workflow.template_builder import build_phases_from_template

        return build_phases_from_template(self, template_id)

    def _build_default_phases(self, scenario_id: str | None = None) -> list[Phase]:
        """构建默认 PDCA 四阶段: 优先使用场景角色, 无场景时回退到硬编码模板"""
        roles = self._get_scenario_roles(scenario_id)
        if not roles:
            return self._build_template_phases()

        role_groups = self._classify_scenario_roles(roles)
        return [
            self._build_plan_phase(role_groups),
            self._build_do_phase(role_groups),
            self._build_check_phase(role_groups),
            self._build_act_phase(role_groups),
        ]

    def _build_template_phases(self) -> list[Phase]:
        """无场景角色时, 从 PHASE_STEP_TEMPLATES 构建硬编码默认阶段"""
        phases = []
        for pt in PhaseType:
            steps = [
                Step(name=s["name"], agent_role=s["agent_role"], action=s["action"])
                for s in PHASE_STEP_TEMPLATES.get(pt, [])
            ]
            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, steps=steps, on_failure=on_failure))
        return phases

    def _classify_scenario_roles(self, roles: list[Any]) -> dict[str, Any]:
        """将场景角色按职能分类: 调研/执行/合规/账房/boss"""
        research_roles = [r for r in roles if r.id in ("researcher", "research") or "调研" in r.name]
        exec_roles = [r for r in roles if r.id not in ("boss", "compliance", "accountant") and r not in research_roles]
        compliance_roles = [r for r in roles if r.id == "compliance" or "合规" in r.name]
        accountant_roles = [r for r in roles if r.id == "accountant" or "账房" in r.name]
        boss_role = next((r for r in roles if r.id == "boss"), None)
        return {
            "research": research_roles,
            "exec": exec_roles,
            "compliance": compliance_roles,
            "accountant": accountant_roles,
            "boss": boss_role,
        }

    def _build_plan_phase(self, role_groups: dict[str, Any]) -> Phase:
        """构建 PLAN 阶段: boss 目标定义 + 调研角色情报, 空时回退到默认"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="目标定义", agent_role=boss_role.id, action="明确本轮PDCA的核心目标和关键指标"))
        for r in role_groups["research"]:
            steps.append(Step(name=f"{r.name}情报", agent_role=r.id, action=f"{r.description}"))
        if not steps:
            steps.append(Step(name="目标定义", agent_role="boss", action="确立目标和方向"))
        return Phase(phase_type=PhaseType.PLAN, steps=steps)

    def _build_do_phase(self, role_groups: dict[str, Any]) -> Phase:
        """构建 DO 阶段: 取前3个执行角色, 空时回退到 boss"""
        steps = [Step(name=r.name, agent_role=r.id, action=r.description) for r in role_groups["exec"][:3]]
        if not steps:
            steps.append(Step(name="执行", agent_role="boss", action="按计划执行"))
        return Phase(phase_type=PhaseType.DO, steps=steps)

    def _build_check_phase(self, role_groups: dict[str, Any]) -> Phase:
        """构建 CHECK 阶段: boss 复盘 + 合规审核, 空时回退到 boss; on_failure=retry_plan"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="数据复盘", agent_role=boss_role.id, action="分析执行数据, 计算ROI和转化率"))
        for r in role_groups["compliance"]:
            steps.append(Step(name=r.name, agent_role=r.id, action=r.description))
        if not steps:
            steps.append(Step(name="复盘检查", agent_role="boss", action="检查执行结果"))
        return Phase(phase_type=PhaseType.CHECK, steps=steps, on_failure="retry_plan")

    def _build_act_phase(self, role_groups: dict[str, Any]) -> Phase:
        """构建 ACT 阶段: boss 决策调整 + 账房核对, 空时回退到 boss"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="决策调整", agent_role=boss_role.id, action="基于复盘结果做出策略调整决策"))
        for r in role_groups["accountant"]:
            steps.append(Step(name=r.name, agent_role=r.id, action=r.description))
        if not steps:
            steps.append(Step(name="决策", agent_role="boss", action="做出调整决策"))
        return Phase(phase_type=PhaseType.ACT, steps=steps)

    def _build_from_scenario_workflow(self, scenario_workflow_id: str, scenario_id: str | None = None) -> list[Phase]:
        scenario = self._get_scenario(scenario_id)
        if scenario is None:
            return self._build_default_phases(scenario_id)

        wf_tpl = None
        for tpl in scenario.workflows:
            if tpl.id == scenario_workflow_id:
                wf_tpl = tpl
                break

        if wf_tpl is None:
            logger.warning("scenario_workflow_not_found", id=scenario_workflow_id, scenario=scenario.id)
            return self._build_default_phases(scenario_id)

        phase_names = wf_tpl.phases
        while len(phase_names) < 4:
            phase_names.append(f"阶段{len(phase_names) + 1}")
        phase_names = phase_names[:4]

        phase_types = [PhaseType.PLAN, PhaseType.DO, PhaseType.CHECK, PhaseType.ACT]
        phases = []

        for i, (pt, pname) in enumerate(zip(phase_types, phase_names, strict=False)):
            if wf_tpl.step_specs and i < len(wf_tpl.step_specs) and wf_tpl.step_specs[i]:
                steps = [
                    Step(
                        name=spec.name,
                        agent_role=spec.agent_role,
                        action=spec.action or spec.name,
                        requires_approval=spec.requires_approval,
                    )
                    for spec in wf_tpl.step_specs[i]
                ]
            else:
                steps = self._auto_assign_steps_for_phase(pt, scenario)

            on_failure = "retry_plan" if pt == PhaseType.CHECK else "advance"
            phases.append(Phase(phase_type=pt, name=pname, steps=steps, on_failure=on_failure))

        return phases

    def _auto_assign_steps_for_phase(self, phase_type: PhaseType, scenario: Any) -> list[Step]:
        """根据场景角色自动为指定阶段分配步骤（策略分发：按 phase_type 查表）"""
        role_groups = self._classify_scenario_roles(scenario.roles)
        builders = {
            PhaseType.PLAN: self._build_auto_plan_steps,
            PhaseType.DO: self._build_auto_do_steps,
            PhaseType.CHECK: self._build_auto_check_steps,
            PhaseType.ACT: self._build_auto_act_steps,
        }
        builder = builders.get(phase_type)
        if builder is None:
            return []
        return builder(role_groups)

    def _build_auto_plan_steps(self, role_groups: dict[str, Any]) -> list[Step]:
        """PLAN 阶段自动步骤: boss 目标定义 + 调研角色, 空时回退到默认"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="目标定义", agent_role=boss_role.id, action="确立目标和方向"))
        for r in role_groups["research"]:
            steps.append(Step(name=f"{r.name}调研", agent_role=r.id, action=r.description))
        return steps or [Step(name="规划", agent_role="boss", action="制定计划")]

    def _build_auto_do_steps(self, role_groups: dict[str, Any]) -> list[Step]:
        """DO 阶段自动步骤: 取前3个执行角色, 空时回退到 boss"""
        steps = [Step(name=r.name, agent_role=r.id, action=r.description) for r in role_groups["exec"][:3]]
        return steps or [Step(name="执行", agent_role="boss", action="按计划执行")]

    def _build_auto_check_steps(self, role_groups: dict[str, Any]) -> list[Step]:
        """CHECK 阶段自动步骤: boss 复盘 + 合规审核, 空时回退到 boss"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="复盘分析", agent_role=boss_role.id, action="分析执行数据"))
        for r in role_groups["compliance"]:
            steps.append(Step(name=r.name, agent_role=r.id, action=r.description))
        return steps or [Step(name="检查", agent_role="boss", action="检查执行结果")]

    def _build_auto_act_steps(self, role_groups: dict[str, Any]) -> list[Step]:
        """ACT 阶段自动步骤: boss 决策 + 账房核对, 空时回退到 boss"""
        boss_role = role_groups["boss"]
        steps: list[Step] = []
        if boss_role:
            steps.append(Step(name="决策调整", agent_role=boss_role.id, action="做出调整决策"))
        for r in role_groups["accountant"]:
            steps.append(Step(name=r.name, agent_role=r.id, action=r.description))
        return steps or [Step(name="改进", agent_role="boss", action="持续改进")]

    def _get_scenario(self, scenario_id: str | None = None) -> Any | None:
        try:
            from src.scenarios.registry import get_scenario_registry

            registry = get_scenario_registry()
            if scenario_id:
                return registry.get(scenario_id)
            try:
                from config import get_settings

                sid = get_settings().scenario
            except Exception as e:
                logger.warning("scenario_settings_load_failed", error=str(e), exc_info=True)
                sid = "content_ecommerce"
            return registry.get(sid)
        except Exception as e:
            logger.warning("scenario_load_failed", error=str(e), exc_info=True)
            return None

    def _get_scenario_roles(self, scenario_id: str | None = None) -> list[Any]:
        scenario = self._get_scenario(scenario_id)
        if scenario is None:
            return []
        return scenario.roles

    def workflow_stats(self, wf_id: str) -> dict[str, Any]:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            return {"error": "工作流不存在"}

        total_steps = sum(len(p.steps) for p in wf.phases)
        done_steps = sum(1 for p in wf.phases for s in p.steps if s.status == StepStatus.DONE)
        failed_steps = sum(1 for p in wf.phases for s in p.steps if s.status == StepStatus.FAILED)
        progress = done_steps / total_steps if total_steps > 0 else 0

        return {
            "workflow_id": wf.id,
            "status": wf.status.value,
            "current_phase": wf.phases[wf.current_phase].effective_name()
            if wf.current_phase < len(wf.phases)
            else "完成",
            "total_steps": total_steps,
            "done_steps": done_steps,
            "failed_steps": failed_steps,
            "progress": round(progress, 2),
        }
