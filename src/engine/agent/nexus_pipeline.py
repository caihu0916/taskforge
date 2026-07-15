
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""NEXUS编排Agent — Dev-QA质量环，任务不过不推进 + 智能消息路由"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from src.engine.agent.specialist_base import SpecialistAgent

logger = structlog.get_logger(__name__)

_NEXUS_SYSTEM = """你是{agent_name}。{agent_vibe}

##NEXUS流水线铁律
1. 不走捷径——每个阶段必须完整完成
2. QA验证——开发输出必须经QA验证才进入下阶段
3. 最多重试3次——失败超3次升级人工
4. 决策基于实际输出——不做假设
5. 交接传完整上下文——不丢信息
6. 结果回流——阶段完成后向父代理汇报进度

##流水线模式
1. full(7阶段): Discovery→Strategy→Foundation→Build(Dev↔QA)→Harden→Launch→Operate
2. sprint(3-5阶段): 精简版，跳过非核心阶段
3. micro(1-2阶段): 快速修复/小任务

##Dev↔QA质量环
Build阶段内：Dev完成→QA验证→不通过→Dev修复→QA再验→通过→下一阶段

##智能路由
- 支持精确路由到指定Agent
- 支持广播模式通知所有Agent
- 阶段完成自动通知父代理"""

NEXUS_PHASES = {
    "full": [
        {"phase": 1, "name": "Discovery", "desc": "需求发现与分析", "agents": ["researcher"]},
        {"phase": 2, "name": "Strategy", "desc": "策略制定与方案设计", "agents": ["strategist"]},
        {"phase": 3, "name": "Foundation", "desc": "基础架构与数据基础", "agents": ["architect"]},
        {"phase": 4, "name": "Build", "desc": "开发与QA循环", "agents": ["developer", "qa"]},
        {"phase": 5, "name": "Harden", "desc": "安全加固与性能优化", "agents": ["security", "perf"]},
        {"phase": 6, "name": "Launch", "desc": "上线部署与验证", "agents": ["devops"]},
        {"phase": 7, "name": "Operate", "desc": "运营监控与迭代", "agents": ["ops"]},
    ],
    "sprint": [
        {"phase": 1, "name": "Discovery", "desc": "需求快速确认", "agents": ["researcher"]},
        {"phase": 2, "name": "Build", "desc": "快速开发与验证", "agents": ["developer", "qa"]},
        {"phase": 3, "name": "Launch", "desc": "快速上线", "agents": ["devops"]},
    ],
    "micro": [
        {"phase": 1, "name": "Build", "desc": "快速修复", "agents": ["developer"]},
    ],
}


class NexusPipelineAgent(SpecialistAgent):
    agent_name = "agency-orchestrator"
    agent_vibe = "Dev-QA质量环，任务不过不推进"
    category = "orchestration"

    def get_system_prompt(self) -> str:
        return _NEXUS_SYSTEM.format(
            agent_name=self.agent_name,
            agent_vibe=self.agent_vibe,
        )

    async def execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
        mode = kwargs.get("mode", "full")
        parent_agent = kwargs.get("parent_agent")  # 新增：父代理ID
        if mode not in NEXUS_PHASES:
            mode = "full"
        phases = NEXUS_PHASES[mode]

        # Phase 1: 生成计划
        pipeline_plan = await self._generate_plan(task, mode, phases)
        pipeline_id = str(uuid.uuid4())
        agents_list = list({a for p in phases for a in p.get("agents", [])})

        # Phase 2: 逐阶段执行
        phase_outputs: dict[str, Any] = {}
        quality_gates: dict[str, dict] = {}
        pipeline_status = "completed"

        for phase_def in phases:
            phase_num = str(phase_def["phase"])
            phase_name = phase_def["name"]
            agents = phase_def["agents"]

            try:
                if phase_name == "Build" and "qa" in agents:
                    result = await self._execute_dev_qa_loop(task, phase_outputs)
                else:
                    result = await self._execute_phase(task, phase_def, phase_outputs)

                phase_outputs[phase_num] = result
                gate_passed = result.get("success", False)
                quality_gates[phase_num] = {"passed": gate_passed, "phase": phase_name}

                # 阶段完成后通知父代理
                if parent_agent:
                    await self._notify_parent_agent(
                        parent_agent,
                        pipeline_id,
                        phase_num,
                        phase_name,
                        gate_passed,
                        result,
                    )

                if not gate_passed:
                    pipeline_status = "failed"
                    break
            except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
                logger.exception("pipeline_phase_execution_failed", phase=phase_name)
                phase_outputs[phase_num] = {"success": False, "error": str(e)}
                quality_gates[phase_num] = {"passed": False, "phase": phase_name}

                # 阶段失败也通知父代理
                if parent_agent:
                    await self._notify_parent_agent(
                        parent_agent,
                        pipeline_id,
                        phase_num,
                        phase_name,
                        False,
                        {"error": str(e)},
                    )

                pipeline_status = "failed"
                break

        # Phase 3: 持久化
        if self._cm:
            try:
                with self._cm.get_conn() as conn:
                    conn.execute(
                        "UPDATE nexus_pipelines SET status=?, phase_outputs=?, "
                        "quality_gates=?, current_phase=? WHERE id=?",
                        (
                            pipeline_status,
                            json.dumps(phase_outputs, ensure_ascii=False),
                            json.dumps(quality_gates, ensure_ascii=False),
                            len(phase_outputs),
                            pipeline_id,
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.exception("pipeline_persist_failed", pipeline_id=pipeline_id, error=str(e))

        # 最终结果通知父代理
        if parent_agent:
            await self._notify_parent_agent(
                parent_agent,
                pipeline_id,
                "final",
                pipeline_status,
                pipeline_status == "completed",
                {
                    "phase_outputs": phase_outputs,
                    "quality_gates": quality_gates,
                    "plan": pipeline_plan,
                },
            )

        return {
            "success": pipeline_status == "completed",
            "data": {
                "id": pipeline_id,
                "mode": mode,
                "total_phases": len(phases),
                "phases": phases,
                "agents": agents_list,
                "plan": pipeline_plan,
                "phase_outputs": phase_outputs,
                "quality_gates": quality_gates,
                "status": pipeline_status,
            },
        }

    async def _generate_plan(self, task: str, mode: str, phases: list) -> str:
        # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
        try:
            from src.engine.llm.router import get_llm_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        router = get_llm_router()
        prompt = (
            f"{self.get_system_prompt()}\n\n任务: {task}\n模式: {mode}\n"
            f"阶段: {json.dumps(phases, ensure_ascii=False)}\n"
            f"输出: 每阶段子任务+Agent组合+质量门+风险预判"
        )
        resp = await router.chat(prompt)
        return resp.strip() if resp else ""

    def _resolve_agent(self, task: str, phase_def: dict) -> str:
        """智能匹配最佳Agent角色，失败时回退到静态映射

        优先使用 RoleMatcher 基于任务关键词动态匹配；
        匹配结果与阶段默认角色取交集（兼顾阶段语义）；
        无交集则 fallback 到阶段硬编码的 agents[0]。
        """
        fallback = phase_def.get("agents", ["butler"])[0]
        try:
            from src.engine.agent.matcher import RoleMatcher

            matcher = RoleMatcher()
            matches = matcher.match(task, top_k=3)
            if not matches:
                logger.debug("nexus_role_match_empty", fallback=fallback)
                return fallback
            # 阶段候选角色（来自NEXUS_PHASES硬编码）
            phase_agents = set(phase_def.get("agents", []))
            # 优先选匹配且在阶段候选中的角色
            for m in matches:
                role_name = m.role.value if hasattr(m.role, "value") else str(m.role)
                if role_name in phase_agents:
                    logger.info("nexus_smart_routed", role=role_name, score=m.score, phase=phase_def["name"])
                    return role_name
            # 无交集则用最佳匹配（信任RoleMatcher）
            best_role = matches[0].role.value if hasattr(matches[0].role, "value") else str(matches[0].role)
            logger.info(
                "nexus_smart_routed_no_intersect", role=best_role, score=matches[0].score, phase=phase_def["name"]
            )
            return best_role
        except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
            logger.warning("nexus_role_match_failed", error=str(e), fallback=fallback)
            return fallback

    async def _execute_phase(self, task: str, phase_def: dict, prev_outputs: dict) -> dict:
        """调度 Agent 执行单个阶段 — 使用智能路由选择最佳Agent"""
        from src.engine.agent.sub_agent import spawn_agent

        phase_name = phase_def["name"]
        primary_agent = self._resolve_agent(task, phase_def)

        # AgentMemory: 执行前读取历史记忆
        memory_entries: list[dict] = []
        try:
            from src.engine.feature.flags import is_enabled

            if is_enabled("agent_memory_enabled"):
                from src.engine.memory.agent_memory import AgentMemoryStore

                _mem = AgentMemoryStore()
                memory_entries = _mem.read(agent_id=primary_agent, max_results=5)
                if memory_entries:
                    logger.debug("nexus_memory_injected", agent=primary_agent, entries=len(memory_entries))
        except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
            logger.warning("nexus_memory_read_failed", agent=primary_agent, error=str(e))

        context = {
            "task": task,
            "phase": phase_name,
            "previous_outputs": json.dumps(prev_outputs, ensure_ascii=False)[:500],
        }
        # 将记忆注入上下文
        if memory_entries:
            memory_summary = "\n".join(f"[{m['key']}]: {m['content'][:200]}" for m in memory_entries)
            context["agent_memory"] = memory_summary

        try:
            result = await spawn_agent(
                parent_agent="nexus",
                role=primary_agent,
                task=f"[{phase_name}] {task}",
                context=context,
                max_turns=2,
            )

            # AgentMemory: 执行后写入结果摘要
            try:
                from src.engine.feature.flags import is_enabled

                if is_enabled("agent_memory_enabled"):
                    from src.engine.memory.agent_memory import AgentMemoryStore

                    _mem = AgentMemoryStore()
                    result_summary = json.dumps(result, ensure_ascii=False)[:500]
                    _mem.write(agent_id=primary_agent, key=f"phase_{phase_name}", content=result_summary)
            except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
                logger.warning("nexus_memory_write_failed", agent=primary_agent, error=str(e))

            return result
        except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
            logger.exception("pipeline_dispatch_failed", phase=phase_name)
            return {"success": False, "error": str(e), "phase": phase_name}

    async def _execute_dev_qa_loop(self, task: str, prev_outputs: dict) -> dict:
        """Build 阶段 Dev↔QA 循环 (最多3次)"""
        from src.engine.agent.sub_agent import spawn_agent

        for attempt in range(3):
            dev_result = await spawn_agent(
                parent_agent="nexus",
                role="developer",
                task=f"[Build-{attempt + 1}] {task}",
                max_turns=2,
            )
            if not dev_result.get("success"):
                continue
            qa_result = await spawn_agent(
                parent_agent="nexus",
                role="qa_engineer",
                task=f"Verify: {task}",
                max_turns=2,
                context={"build_output": json.dumps(dev_result, ensure_ascii=False)[:500]},
            )
            if qa_result.get("success"):
                return {"success": True, "attempts": attempt + 1, "dev": dev_result, "qa": qa_result}
        return {"success": False, "error": "Dev-QA loop exhausted after 3 attempts"}

    def get_workflow(self, task: str) -> list[dict[str, str]]:
        return [
            {"step": 1, "name": "Discovery", "desc": "需求发现与分析"},
            {"step": 2, "name": "Strategy", "desc": "策略制定与方案设计"},
            {"step": 3, "name": "Foundation", "desc": "基础架构与数据基础"},
            {"step": 4, "name": "Build(Dev↔QA)", "desc": "开发与QA循环验证"},
            {"step": 5, "name": "Harden", "desc": "安全加固与性能优化"},
            {"step": 6, "name": "Launch", "desc": "上线部署与验证"},
            {"step": 7, "name": "Operate", "desc": "运营监控与迭代"},
        ]

    def get_rules(self) -> dict[str, Any]:
        return {
            "no_shortcuts": "不走捷径，每个阶段必须完整完成",
            "qa_verification": "开发输出必须经QA验证才进入下阶段",
            "max_retries": 3,
            "data_driven_decisions": "决策基于实际输出，不做假设",
            "full_context_handoff": "交接传完整上下文，不丢信息",
            "result_reflow": "阶段完成后向父代理汇报进度",
            "supported_modes": {
                "full": "7阶段完整流水线",
                "sprint": "3-5阶段精简版",
                "micro": "1-2阶段快速修复",
            },
            "dev_qa_loop": "Build阶段Dev→QA循环，不通过不推进",
            "taboos": [
                "禁止跳过QA验证",
                "禁止超3次重试不升级",
                "禁止阶段间丢失上下文",
                "禁止假设输出通过质量门",
            ],
        }

    async def _notify_parent_agent(
        self,
        parent_agent: str,
        pipeline_id: str,
        phase_num: str,
        phase_name: str,
        success: bool,
        result: dict[str, Any],
    ) -> None:
        """通过MessageRouter通知父代理阶段执行状态"""
        try:
            from src.engine.agent.message_router import get_message_router

            router = get_message_router()
            content = f"""NEXUS Pipeline [{pipeline_id}]

阶段 {phase_num}: {phase_name}
状态: {"成功" if success else "失败"}

{json.dumps(result, ensure_ascii=False, indent=2)[:500]}
"""
            await router.send(
                sender_id="nexus_pipeline",
                target_agent=parent_agent,
                content=content,
                metadata={
                    "pipeline_id": pipeline_id,
                    "phase_num": phase_num,
                    "phase_name": phase_name,
                    "success": success,
                    "result": result,
                },
            )
            logger.debug(
                "nexus_notify_parent",
                pipeline_id=pipeline_id,
                phase=phase_name,
                parent_agent=parent_agent,
            )
        except (RuntimeError, ValueError, ConnectionError, ImportError) as e:
            logger.warning("nexus_notify_parent_failed", error=str(e), exc_info=True)
