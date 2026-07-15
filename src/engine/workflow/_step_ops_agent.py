
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 步骤Agent执行Mixin"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from src.engine.agent.exec_helpers import record_execution
from src.engine.workflow.models import (
    Phase,
    Step,
    StepStatus,
    Workflow,
    WorkflowStatus,
)
from src.exceptions import ValidationError

logger = structlog.get_logger(__name__)

# P1-2 FIX: LLM 调用超时控制，防止服务挂掉时步骤永远 RUNNING
LLM_TIMEOUT = 300  # 5 分钟超时

# P2-01: QualityGate 单例 — Agent 输出质量门禁 (lazy init)
_quality_gate = None


def _get_quality_gate():
    """懒加载 QualityGate 单例"""
    global _quality_gate
    if _quality_gate is None:
        from src.engine.quality.gate import QualityGate

        _quality_gate = QualityGate()
    return _quality_gate


class StepOpsAgentMixin:
    """步骤Agent执行方法"""

    async def execute_step_with_agent(self, wf_id: str, step_id: str) -> Workflow:
        """步骤Agent执行 — 一写二记，支持条件分支跳过

        P0-1 FIX: 添加并发锁保护，防止同一工作流并发执行。
        """
        # P0-1 FIX: 添加并发锁保护
        lock = self._get_wf_lock(wf_id)
        async with lock:
            from src.engine.agent.exec_helpers import record_execution

            wf = self._wf_mgr.get(wf_id)
            if wf is None:
                raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

            target_step, current_phase = self._find_step_in_wf(wf, step_id)
            if target_step is None:
                raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")
            if target_step.status == StepStatus.DONE:
                raise ValidationError("步骤已完成", code="STEP_ALREADY_DONE")

            # ── 条件分支检查: 条件不满足 → 直接 SKIPPED ──
            skipped_wf = self._check_condition_skip(wf, target_step, current_phase, step_id, wf_id)
            if skipped_wf is not None:
                return skipped_wf

            # Phase 0.2: step_executors 优先路由 — 自动化执行器命中则不走 LLM Agent
            handled_wf = await self._try_step_executor(wf, target_step, current_phase, step_id, wf_id)
            if handled_wf is not None:
                return handled_wf

            # Agent 执行
            exec_id = str(uuid.uuid4())
            agent_role = target_step.agent_role or "workflow_step"
            record_execution(
                self._cm, agent_role, "workflow", exec_id, "running", task=f"step:{step_id}:{target_step.action[:100]}"
            )

            await self._setup_running_state(wf, target_step, current_phase, step_id, wf_id)

            try:
                user_message = self._build_step_user_message(wf, target_step, current_phase)

                blocked_wf = await self._run_pre_execute_hook(
                    wf, target_step, step_id, wf_id, user_message, exec_id, agent_role
                )
                if blocked_wf is not None:
                    return blocked_wf

                agent_result = await self._call_llm_and_parse(
                    wf, target_step, current_phase, step_id, wf_id, user_message
                )

                await self._run_post_execute_hook(wf, target_step, step_id, wf_id, agent_result)
            except Exception as e:
                return self._handle_agent_failure(wf, target_step, step_id, wf_id, exec_id, agent_role, e)

            return await self._finalize_step_result(
                wf, target_step, current_phase, step_id, wf_id, exec_id, agent_role, agent_result
            )

    def _find_step_in_wf(self, wf: Workflow, step_id: str) -> tuple[Step | None, Phase | None]:
        """在工作流中查找步骤，返回 (step, phase)"""
        target_step = None
        current_phase = None
        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    target_step = step
                    current_phase = phase
                    break
        return target_step, current_phase

    def _check_condition_skip(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str
    ) -> Workflow | None:
        """条件分支检查: 条件不满足 → 直接 SKIPPED. 返回 wf 若跳过，否则 None"""
        if target_step.status not in (StepStatus.PENDING, StepStatus.FAILED):
            return None
        from src.engine.feature.flags import is_enabled as _isf

        if not (_isf("workflow_branch") and target_step.condition):
            return None
        from src.engine.workflow.condition_evaluator import get_condition_evaluator

        evaluator = get_condition_evaluator()
        store = wf.store or {}
        context = self._build_condition_context(wf, target_step)

        should_execute = evaluator.evaluate(
            target_step.condition,
            store=store,
            context=context,
            flag_enabled=True,
        )

        if should_execute:
            return None

        target_step.status = StepStatus.SKIPPED
        target_step.result = f"条件不满足，跳过: {target_step.condition[:100]}"
        target_step.finished_at = datetime.now(UTC).isoformat()
        self._save(
            wf,
            event_type="step_skipped",
            payload={
                "step_id": step_id,
                "step_name": target_step.name,
                "condition": target_step.condition[:100],
            },
        )
        self._log_step(wf_id, target_step, current_phase.phase_type.value if current_phase else "")
        logger.info(
            "step_skipped_by_condition",
            wf_id=wf_id,
            step_id=step_id,
            condition=target_step.condition[:80],
        )
        # SKIPPED 步骤也算完成，检查阶段是否结束
        if self._is_phase_complete(wf):
            wf = self._auto_advance_if_allowed(wf)
        return wf

    async def _try_step_executor(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str
    ) -> Workflow | None:
        """Phase 0.2: step_executors 优先路由 — 自动化执行器命中则不走 LLM Agent. 返回 wf 若已处理，否则 None"""
        try:
            from src.engine.workflow.step_executors import STEP_EXECUTOR_REGISTRY

            executor = STEP_EXECUTOR_REGISTRY.get(target_step.action)
            if executor is None:
                return None

            target_step.status = StepStatus.RUNNING
            target_step.started_at = datetime.now(UTC).isoformat()
            self._save(wf)  # RUNNING是中间状态，不记录事件
            # 执行器参数从 step.params 注入
            # FIX-005: step_executor 超时保护
            try:
                _coro = executor(**target_step.params) if target_step.params else executor()
                result = await asyncio.wait_for(_coro, timeout=LLM_TIMEOUT)
            except TimeoutError:
                return self._handle_executor_timeout(wf, target_step, current_phase, step_id, wf_id)

            # Phase 0.2: 人类决策点检测 — needs_human_review → 暂停等审批
            if isinstance(result, dict) and result.get("needs_human_review"):
                return self._handle_executor_human_review(wf, target_step, current_phase, step_id, wf_id, result)

            return self._handle_executor_done(wf, target_step, current_phase, step_id, wf_id, result)
        except Exception as exc:
            logger.debug("exception_handled", error=str(exc))
            # FIX-026: executor异常记录为ERROR级别，仅当步骤配置了fallback才回退LLM
            logger.error("step_executor_failed_fallback_agent", action=target_step.action, exc_info=True)
            return None

    def _handle_executor_timeout(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str
    ) -> Workflow:
        """处理步骤执行器超时"""
        target_step.status = StepStatus.FAILED
        target_step.result = f"步骤执行器超时（{LLM_TIMEOUT}秒）"
        target_step.finished_at = datetime.now(UTC).isoformat()
        self._save(
            wf,
            event_type="step_timeout",
            payload={"step_id": step_id, "step_name": target_step.name, "timeout": LLM_TIMEOUT},
        )
        self._log_step(wf_id, target_step, current_phase.phase_type.value if current_phase else "")
        self._notify_event(wf, "step_timeout")
        return wf

    def _handle_executor_human_review(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str, result
    ) -> Workflow:
        """处理步骤执行器人类决策点 — 暂停等审批"""
        target_step.status = StepStatus.APPROVAL_PENDING
        target_step.result = result
        target_step.finished_at = None
        wf.status = WorkflowStatus.PAUSED  # 暂停等人工审批
        self._save(
            wf,
            event_type="step_executed",
            payload={"step_id": step_id, "step_name": target_step.name, "status": "approval_pending"},
        )
        self._log_step(wf_id, target_step, current_phase.phase_type.value if current_phase else "")
        # 提交审批记录到审批引擎
        try:
            self.approval_engine.submit_approval(
                target_type="step",
                target_id=step_id,
                workflow_id=wf_id,
                title=f"人工审核: {target_step.name}",
                description=str(result.get("preview", ""))[:200],
                context={
                    "needs_human_review": True,
                    "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                },
            )
        except (ValueError, KeyError, RuntimeError, TypeError):
            logger.debug("approval_submit_agent_failed", wf_id=wf_id, step_id=step_id, exc_info=True)
        self._ws_broadcast(
            wf_id,
            "approval_required",
            {
                "workflow_id": wf_id,
                "step_id": step_id,
                "step_name": target_step.name,
                "preview": result,
            },
        )
        return wf

    def _handle_executor_done(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str, result
    ) -> Workflow:
        """处理步骤执行器正常完成"""
        target_step.status = StepStatus.DONE
        target_step.result = result
        target_step.finished_at = datetime.now(UTC).isoformat()
        self._save(
            wf,
            event_type="step_executed",
            payload={
                "step_id": step_id,
                "step_name": target_step.name,
                "result_preview": str(result)[:100] if result else "",
            },
        )
        self._log_step(wf_id, target_step, current_phase.phase_type.value if current_phase else "")
        self._auto_advance_if_allowed(wf)
        return wf

    async def _setup_running_state(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str
    ) -> None:
        """设置 RUNNING 状态、ws广播、chat_bridge、STEP_START hook"""
        target_step.status = StepStatus.RUNNING
        target_step.started_at = datetime.now(UTC).isoformat()
        self._save(wf)  # RUNNING是中间状态，不记录事件

        self._ws_broadcast(
            wf_id,
            "step_running",
            {
                "workflow_id": wf_id,
                "step_id": step_id,
                "step_name": target_step.name,
                "agent_role": target_step.agent_role,
                "phase": current_phase.phase_type.value if current_phase else "",
            },
        )

        try:
            from src.engine.chat.chat_bridge import on_step_running

            on_step_running(
                wf_id, target_step.name, target_step.agent_role, current_phase.phase_type.value if current_phase else ""
            )
        except (RuntimeError, ValueError, ImportError, AttributeError) as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)

        try:
            from src.engine.hooks import HookDispatcher, HookEvent

            dispatcher = HookDispatcher.get_dispatcher()
            await dispatcher.emit(
                HookEvent.STEP_START,
                workflow_id=wf_id,
                step_id=step_id,
                agent_role=target_step.agent_role,
                action=target_step.action,
            )
        except (RuntimeError, ValueError, TypeError) as hook_err:
            logger.warning("hook_step_start_error", error=str(hook_err), exc_info=True)

    async def _run_pre_execute_hook(
        self,
        wf: Workflow,
        target_step: Step,
        step_id: str,
        wf_id: str,
        user_message: str,
        exec_id: str,
        agent_role: str,
    ) -> Workflow | None:
        """PRE_EXECUTE hook — 返回 wf 若被 blocked，否则 None"""
        try:
            from src.engine.hooks import HookBlockedError, HookDispatcher, HookEvent

            dispatcher = HookDispatcher.get_dispatcher()
            await dispatcher.emit(
                HookEvent.PRE_EXECUTE,
                agent_role=target_step.agent_role,
                workflow_id=wf_id,
                step_id=step_id,
                content=user_message,
                user_input=user_message,
            )
        except HookBlockedError as blocked:
            target_step.status = StepStatus.FAILED
            target_step.result = f"Hook blocked: {blocked.block_message}"
            target_step.finished_at = datetime.now(UTC).isoformat()
            self._save(
                wf,
                event_type="step_failed",
                payload={
                    "step_id": step_id,
                    "step_name": target_step.name,
                    "error": f"hook_blocked:{blocked.block_message[:200]}",
                },
            )
            record_execution(
                self._cm,
                agent_role,
                "workflow",
                exec_id,
                "failed",
                error=f"hook_blocked:{blocked.block_message[:200]}",
            )
            logger.warning("step_blocked_by_hook", wf_id=wf_id, step_id=step_id, hook=blocked.hook_name, exc_info=True)
            return wf
        except (RuntimeError, ValueError, TypeError) as hook_err:
            logger.warning("hook_pre_execute_error", error=str(hook_err), exc_info=True)
        return None

    async def _call_llm_and_parse(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str, user_message: str
    ) -> str:
        """构建 system prompt、智能路由、LLM 调用 (含超时保护)、解析结果"""
        system_prompt = self._build_step_system_prompt(wf, target_step, current_phase)

        # AGENT-011: 用结构化分隔符包裹 system prompt，防止 prompt injection 冒充系统指令
        from src.engine.agent._prompts import wrap_system_prompt

        system_prompt = wrap_system_prompt(system_prompt)

        # ponytail: 开源版LLM模块不可用时降级；P0-09/P0-17提供remote_stubs桩
        try:
            from src.engine.llm.smart_router import get_smart_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        smart = get_smart_router()
        routing = smart.route(message=target_step.action, agent_role=target_step.agent_role)

        try:
            from src.engine.llm.router import get_llm_router
        except ImportError as e:
            raise RuntimeError("LLM模块不可用（开源版需配置远程API或安装Ollama）") from e

        llm_router = get_llm_router()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        # P1-2 FIX: 添加超时控制，防止 LLM 调用卡死
        try:
            result = await asyncio.wait_for(
                llm_router.chat(messages, provider=routing.provider, model=routing.model),
                timeout=LLM_TIMEOUT,
            )
        except TimeoutError as e:
            logger.error(
                "llm_call_timeout",
                wf_id=wf_id,
                step_id=step_id,
                provider=routing.provider,
                model=routing.model,
            )
            raise RuntimeError(f"LLM call timeout after {LLM_TIMEOUT}s") from e
        agent_result = result.get("content", "")
        return self._parse_step_result(agent_result, target_step)

    async def _run_post_execute_hook(
        self, wf: Workflow, target_step: Step, step_id: str, wf_id: str, agent_result: str
    ) -> None:
        """POST_EXECUTE hook"""
        try:
            from src.engine.hooks import HookDispatcher, HookEvent

            dispatcher = HookDispatcher.get_dispatcher()
            await dispatcher.emit(
                HookEvent.POST_EXECUTE,
                agent_role=target_step.agent_role,
                workflow_id=wf_id,
                step_id=step_id,
                result=agent_result,
                completed=True,
            )
        except (RuntimeError, ValueError, TypeError) as hook_err:
            logger.warning("hook_post_execute_error", error=str(hook_err), exc_info=True)

    def _handle_agent_failure(
        self, wf: Workflow, target_step: Step, step_id: str, wf_id: str, exec_id: str, agent_role: str, e: Exception
    ) -> Workflow:
        """处理 Agent 执行异常"""
        target_step.status = StepStatus.FAILED
        target_step.result = f"Agent执行失败: {e!s}"
        target_step.finished_at = datetime.now(UTC).isoformat()
        self._save(
            wf,
            event_type="step_failed",
            payload={"step_id": step_id, "step_name": target_step.name, "error": str(e)[:200]},
        )
        record_execution(
            self._cm, agent_role, "workflow", exec_id, "failed", error=f"agent_execution_failed:{str(e)[:300]}"
        )
        logger.error("step_agent_execution_failed", wf_id=wf_id, step_id=step_id, error=str(e), exc_info=True)
        return wf

    async def _set_step_post_agent_status(
        self, wf: Workflow, target_step: Step, step_id: str, wf_id: str, agent_result: str, current_phase: Phase | None
    ) -> None:
        """设置 Agent 执行后的步骤状态 (审批/完成)"""
        if target_step.requires_approval:
            target_step.status = StepStatus.APPROVAL_PENDING
            # Agent执行完毕需审批 → 提交审批记录
            try:
                self.approval_engine.submit_approval(
                    target_type="step",
                    target_id=step_id,
                    workflow_id=wf_id,
                    title=f"Agent结果审批: {target_step.name}",
                    description=(agent_result or "")[:200],
                    context={
                        "agent_role": target_step.agent_role,
                        "phase": current_phase.phase_type.value if current_phase else "",
                    },
                )
            except (ValueError, KeyError, RuntimeError, TypeError):
                logger.debug("approval_submit_agent_result_failed", wf_id=wf_id, step_id=step_id, exc_info=True)
        else:
            # P2-01: QualityGate 集成 — Agent 输出必须通过质量检查才能标记 DONE
            quality_passed = True
            quality_result = None
            try:
                gate = _get_quality_gate()
                quality_result = gate.check(agent_result, target_step.agent_role)
                if not quality_result.passed:
                    quality_passed = False
                    logger.info(
                        "quality_check_not_passed",
                        wf_id=wf_id,
                        step_id=step_id,
                        score=quality_result.score,
                        issues=quality_result.issues,
                    )
            except Exception:
                logger.warning("quality_check_exception", step_id=step_id, exc_info=True)

            if quality_passed:
                target_step.status = StepStatus.DONE
                self._maybe_learn_from_step(target_step)
                try:
                    from src.engine.hooks import HookDispatcher, HookEvent

                    await HookDispatcher.get_dispatcher().emit(
                        HookEvent.STEP_DONE,
                        workflow_id=wf_id,
                        step_id=step_id,
                        agent_role=target_step.agent_role,
                        result=agent_result,
                    )
                except (RuntimeError, ValueError, TypeError) as e:
                    logger.warning("hook_post_execute_failed", error=str(e), exc_info=True)
            else:
                # 质量不通过 — 判断是否重试
                should_retry = False
                if quality_result:
                    try:
                        should_retry = _get_quality_gate().should_retry(step_id, quality_result)
                    except Exception:
                        logger.warning("quality_retry_check_failed", step_id=step_id, exc_info=True)

                if should_retry:
                    target_step.status = StepStatus.PENDING
                    target_step.result = agent_result
                    logger.info(
                        "quality_retry_scheduled",
                        wf_id=wf_id,
                        step_id=step_id,
                        retry_count=_get_quality_gate()._retry_counts.get(step_id, 0),
                    )
                else:
                    target_step.status = StepStatus.CHECK_FAILED
                    target_step.result = agent_result
                    logger.warning(
                        "quality_check_failed_final",
                        wf_id=wf_id,
                        step_id=step_id,
                        score=quality_result.score if quality_result else 0.0,
                        issues=quality_result.issues if quality_result else [],
                    )

    def _notify_step_done(
        self, wf: Workflow, target_step: Step, current_phase: Phase | None, step_id: str, wf_id: str, agent_result: str
    ) -> None:
        """chat_bridge 通知步骤完成"""
        try:
            from src.engine.chat.chat_bridge import on_step_done

            duration_ms = 0
            if target_step.started_at and target_step.finished_at:
                from datetime import datetime as _dt

                try:
                    s = _dt.fromisoformat(target_step.started_at)
                    f = _dt.fromisoformat(target_step.finished_at)
                    duration_ms = int((f - s).total_seconds() * 1000)
                except (ValueError, TypeError) as e:
                    logger.warning("operation_failed", error=str(e), exc_info=True)
            on_step_done(
                wf_id,
                target_step.name,
                target_step.agent_role,
                current_phase.phase_type.value if current_phase else "",
                (agent_result or "")[:200],
                duration_ms,
            )
        except (RuntimeError, ValueError, ImportError, AttributeError) as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)

    async def _finalize_step_result(
        self,
        wf: Workflow,
        target_step: Step,
        current_phase: Phase | None,
        step_id: str,
        wf_id: str,
        exec_id: str,
        agent_role: str,
        agent_result: str,
    ) -> Workflow:
        """Agent 执行成功后的收尾: 状态设置、保存、广播、通知"""
        await self._set_step_post_agent_status(wf, target_step, step_id, wf_id, agent_result, current_phase)
        target_step.result = agent_result
        target_step.finished_at = datetime.now(UTC).isoformat()
        for phase in wf.phases:
            for s in phase.steps:
                if s.id == step_id:
                    self._log_step(wf_id, target_step, phase.phase_type)
                    break
        # 最终 _save: 根据步骤最终状态决定事件类型
        _final_event = "step_executed"
        _final_payload = {"step_id": step_id, "step_name": target_step.name}
        if target_step.status == StepStatus.APPROVAL_PENDING:
            _final_payload["status"] = "approval_pending"
        self._save(wf, event_type=_final_event, payload=_final_payload)

        record_execution(self._cm, agent_role, "workflow", exec_id, "completed", result=(agent_result or "")[:4000])

        self._ws_broadcast(
            wf_id,
            "step_done",
            {
                "workflow_id": wf_id,
                "step_id": step_id,
                "step_name": target_step.name,
                "status": target_step.status.value,
                "agent_role": target_step.agent_role,
                "result_preview": (agent_result or "")[:200],
            },
        )

        self._notify_step_done(wf, target_step, current_phase, step_id, wf_id, agent_result)

        if target_step.status == StepStatus.DONE and self._is_phase_complete(wf):
            wf = self._auto_advance_if_allowed(wf)

        return wf

    def _build_step_system_prompt(self, wf: Workflow, step: Step, phase: Phase) -> str:
        from src.engine.workflow.step_prompts import build_step_system_prompt

        return build_step_system_prompt(wf, step, phase)

    def _build_step_user_message(self, wf: Workflow, step: Step, phase: Phase) -> str:
        from src.engine.workflow.step_prompts import build_step_user_message

        return build_step_user_message(wf, step, phase)

    def _get_agent_prompt_template(self, agent_role: str) -> str | None:
        from src.engine.workflow.step_prompts import get_agent_prompt_template

        return get_agent_prompt_template(agent_role)

    def _parse_step_result(self, raw_result: str, step: Step) -> str:
        from src.engine.workflow.step_prompts import parse_step_result

        return parse_step_result(raw_result, step)
