
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 步骤提示词构建与解析"""

from __future__ import annotations

import json

import structlog

from src.engine.workflow.models import (
    Phase,
    Step,
    StepStatus,
    Workflow,
)

logger = structlog.get_logger(__name__)


def build_step_system_prompt(wf: Workflow, step: Step, phase: Phase) -> str:
    """构造步骤系统提示词 — 注入Agent角色模板 + 工作流上下文"""
    parts = []

    role_template = get_agent_prompt_template(step.agent_role)
    if role_template:
        parts.append(f"你是{step.agent_role}角色。以下是你的角色专业指令:\n\n{role_template}")
    else:
        parts.append(f"你是{step.agent_role}角色。")

    parts.append("\n##当前工作流上下文")
    parts.append(f"- 工作流: {wf.name}")
    if wf.description:
        parts.append(f"- 目标: {wf.description}")
    parts.append(f"- 当前阶段: {phase.effective_name()} ({phase.phase_type.value})")
    if phase.description:
        parts.append(f"- 阶段说明: {phase.description}")

    if step.output_schema:
        parts.append("\n##输出要求")
        parts.append("请严格按照以下JSON Schema输出结果，不要输出其他内容:")
        parts.append(f"```json\n{json.dumps(step.output_schema, ensure_ascii=False, indent=2)}\n```")
    else:
        parts.append("\n##输出要求")
        parts.append("请输出结构化的专业结果，包含: 1) 核心结论 2) 关键发现/数据 3) 具体建议/行动项")

    return "\n".join(parts)


def build_step_user_message(wf: Workflow, step: Step, phase: Phase) -> str:
    """构造步骤用户消息 — 注入前序步骤结果"""
    parts = []

    parts.append(f"##当前任务\n{step.action}")
    if step.description:
        parts.append(f"\n补充说明: {step.description}")

    completed_in_phase = [
        s for s in phase.steps if s.status in (StepStatus.DONE, StepStatus.APPROVAL_PENDING) and s.id != step.id
    ]
    if completed_in_phase:
        parts.append("\n##同阶段已完成步骤")
        for prev in completed_in_phase:
            result_preview = prev.result[:500] + "..." if len(prev.result) > 500 else prev.result
            parts.append(f"###{prev.name}")
            parts.append(result_preview)

    phase_idx = wf.phases.index(phase)
    if phase_idx > 0:
        parts.append("\n##前序阶段摘要")
        for prev_phase in wf.phases[:phase_idx]:
            done_steps = [s for s in prev_phase.steps if s.status == StepStatus.DONE]
            if done_steps:
                parts.append(f"###{prev_phase.effective_name()}")
                for s in done_steps:
                    summary = s.result[:200] + "..." if len(s.result) > 200 else s.result
                    parts.append(f"- **{s.name}**: {summary}")

    return "\n".join(parts)


def get_agent_prompt_template(agent_role: str) -> str | None:
    """获取Agent角色的系统提示词模板 — 从prompt_templates表查询"""
    try:
        from src.engine.prompt.database import get_prompt_db

        db = get_prompt_db()
        role_map = {
            "boss": "boss_planning",
            "hitmaker": "hitmaker_xhs",
            "hit_maker": "hitmaker_xhs",
            "deal_hunter": "dealhunter_followup",
            "researcher": "researcher_market",
            "support": "support_aftersale",
            "accountant": "accountant_cost",
            "butler": "butler_schedule",
            "compliance": "compliance_ad",
            "caster": "caster_livestream",
        }
        prompt_id = role_map.get(agent_role)
        if prompt_id:
            pt = db.get_prompt(prompt_id)
            if pt:
                return pt.system_prompt
        # 降级: 按id前缀搜索
        prompts = db.list_prompts(id_prefix=agent_role.split("_", maxsplit=1)[0], active_only=True)
        if prompts:
            return prompts[0].system_prompt
    except Exception as e:
        logger.warning("prompt_lookup_failed", agent_role=agent_role, error=str(e), exc_info=True)
    return None


def parse_step_result(raw_result: str, step: Step) -> str:
    """尝试解析结构化输出 — 如果LLM返回了JSON包裹的内容, 提取有效部分"""
    if not step.output_schema:
        return raw_result

    import re

    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw_result, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            logger.debug("step_result_json_parse_failed")

    return raw_result
