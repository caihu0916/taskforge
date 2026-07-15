
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 工作流执行控制 (启动/推进/暂停/取消/自动运行)"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.engine.workflow.models import (
    Phase,
    PhaseType,
    Step,
    StepStatus,
    Workflow,
    WorkflowStatus,
    validate_workflow_transition,
)
from src.exceptions import ValidationError

if TYPE_CHECKING:
    from src.engine.workflow.variable_pool import VariablePool

logger = structlog.get_logger(__name__)

# 条件评估失败时 step.result 的前缀，用于识别已失败的步骤避免重复评估
_COND_EVAL_FAIL_PREFIX = "条件评估失败"


class ExecutionMixin:
    """工作流执行控制方法"""

    # FIX-002: 按 wf_id 键控的互斥锁，防止同一工作流并发执行
    _wf_locks: dict[str, asyncio.Lock] = {}

    def _get_wf_lock(self, wf_id: str) -> asyncio.Lock:
        """获取或创建 wf_id 对应的互斥锁"""
        if wf_id not in self._wf_locks:
            self._wf_locks[wf_id] = asyncio.Lock()
        return self._wf_locks[wf_id]

    def _parse_graph_dsl(self, graph_dsl: str) -> tuple[list, list[tuple[int, int]]]:
        """解析 graph_dsl JSON 为 (nodes, edges) 供 DAG 校验使用

        graph_dsl 格式: {"nodes": [...], "edges": [{"source": idx, "target": idx}, ...]}
        """
        import json

        data = json.loads(graph_dsl)
        nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        edges: list[tuple[int, int]] = []
        for e in raw_edges:
            src = e.get("source", -1) if isinstance(e, dict) else -1
            tgt = e.get("target", -1) if isinstance(e, dict) else -1
            if isinstance(src, int) and isinstance(tgt, int):
                edges.append((src, tgt))
        return nodes, edges

    def start_workflow(self, wf_id: str) -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        if wf.status not in (WorkflowStatus.DRAFT, WorkflowStatus.PAUSED):
            raise ValidationError(f"工作流状态{wf.status.value}不可启动", code="WORKFLOW_CANNOT_START")

        # FIX-010: 启动时DAG循环校验（start_workflow是所有工作流启动入口）
        if wf.graph_dsl:
            try:
                nodes, edges = self._parse_graph_dsl(wf.graph_dsl)
                if nodes:
                    from src.engine.workflow.dag_utils import detect_cycle_bfs

                    if detect_cycle_bfs(nodes, edges):
                        raise ValidationError("工作流DAG包含循环，无法启动", code="WORKFLOW_CYCLE_DETECTED")
            except ValidationError:
                raise
            except (ValueError, KeyError, RuntimeError) as e:
                logger.warning("dag_validation_error", wf_id=wf_id, error=str(e))

        validate_workflow_transition(wf.status, WorkflowStatus.RUNNING)
        wf.status = WorkflowStatus.RUNNING
        wf.current_phase = 0
        if wf.phases:
            wf.phases[0].status = StepStatus.RUNNING
        self._save(wf, event_type="started")
        logger.info("workflow_started", id=wf_id)
        return wf

    def advance_phase(self, wf_id: str, *, auto_loop: bool = True) -> Workflow:
        """推进工作流到下一阶段（编排：完成当前阶段 → 完成/推进分支 → 持久化）"""
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        if wf.status != WorkflowStatus.RUNNING:
            raise ValidationError("工作流未在运行中", code="WORKFLOW_NOT_RUNNING")

        current_phase_type = self._finalize_current_phase(wf)
        wf.current_phase += 1

        if wf.current_phase >= len(wf.phases):
            self._handle_workflow_completion(wf, wf_id, auto_loop, current_phase_type)
        else:
            self._handle_phase_advancement(wf, wf_id)

        self._save_phase_advance_event(wf)
        return wf

    def _finalize_current_phase(self, wf: Workflow) -> PhaseType | None:
        """标记当前阶段为 DONE 并返回其类型"""
        if wf.current_phase >= len(wf.phases):
            return None
        phase = wf.phases[wf.current_phase]
        phase_type = phase.phase_type
        phase.status = StepStatus.DONE
        phase.finished_at = datetime.now(UTC).isoformat()
        return phase_type

    def _handle_workflow_completion(
        self, wf: Workflow, wf_id: str, auto_loop: bool, current_phase_type: PhaseType | None
    ) -> None:
        """处理工作流完成: 状态变更、指标、下一轮、通知、自动产出、Chat桥接"""
        validate_workflow_transition(wf.status, WorkflowStatus.COMPLETED)
        wf.status = WorkflowStatus.COMPLETED
        logger.info("workflow_completed", id=wf_id)

        self._record_completion_metrics()
        self._maybe_create_next_cycle(wf, wf_id, auto_loop, current_phase_type)
        self._notify_event(wf, "completed")
        self._trigger_auto_output(wf, wf_id)
        self._notify_workflow_completed_chat(wf, wf_id)

    def _record_completion_metrics(self) -> None:
        """记录工作流完成指标到 Prometheus"""
        try:
            from src.infra.observability.prometheus_metrics import get_custom_metrics

            get_custom_metrics().record_workflow(status="completed")
        except (RuntimeError, ValueError, ImportError):
            logger.warning("exception_swallowed", context="record_workflow_metrics", exc_info=True)

    def _maybe_create_next_cycle(
        self, wf: Workflow, wf_id: str, auto_loop: bool, current_phase_type: PhaseType | None
    ) -> None:
        """auto_loop 且 ACT 阶段完成时创建下一轮 PDCA 循环"""
        if not auto_loop or current_phase_type != PhaseType.ACT:
            return
        next_wf = self._create_next_cycle(wf)
        if next_wf is not None:
            logger.info("pdca_next_cycle_created", prev_id=wf_id, next_id=next_wf.id)
        else:
            logger.info("pdca_cycle_limit_reached", wf_id=wf_id, max_iterations=wf.max_pdca_iterations)

    def _trigger_auto_output(self, wf: Workflow, wf_id: str) -> None:
        """自动产出: 工作流完成 → 自动生成 PDF/Excel/HTML"""
        try:
            from src.engine.feature.flags import is_enabled as _isf

            if not _isf("workflow_auto_output"):
                return
            from src.engine.workflow.auto_output import AutoOutputHook

            hook = AutoOutputHook()
            results = self._collect_workflow_results(wf)
            self._dispatch_auto_output(hook, wf.name, results)
            logger.info("workflow_auto_output_triggered", wf_id=wf_id)
        except (RuntimeError, ValueError, ImportError) as e:
            logger.warning("workflow_auto_output_hook_failed", error=str(e), exc_info=True)

    def _collect_workflow_results(self, wf: Workflow) -> list[dict]:
        """收集工作流中所有有结果的步骤用于自动产出"""
        return [
            {
                "type": s.action[:60] if s.action else "step",
                "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                "result": s.result or "",
            }
            for p in wf.phases
            for s in (p.steps or [])
            if s.result
        ]

    def _dispatch_auto_output(self, hook, name: str, results: list[dict]) -> None:
        """分发自动产出任务（优先复用事件循环，否则新建）"""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(hook.on_workflow_completed(name, results, output_formats=["pdf", "xlsx", "html"]))
        except RuntimeError:
            from src.infra.async_utils import run_async

            run_async(hook.on_workflow_completed(name, results, output_formats=["pdf", "xlsx", "html"]))

    def _notify_workflow_completed_chat(self, wf: Workflow, wf_id: str) -> None:
        """Chat桥接: 工作流完成 → 推入Chat汇总"""
        try:
            from src.engine.chat.chat_bridge import on_workflow_completed

            on_workflow_completed(wf_id, wf.name, [p.model_dump() for p in wf.phases])
        except (RuntimeError, ValueError, ImportError, AttributeError) as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)

    def _handle_phase_advancement(self, wf: Workflow, wf_id: str) -> None:
        """处理阶段推进: 标记新阶段 RUNNING、通知、Chat桥接"""
        phase = wf.phases[wf.current_phase]
        phase.status = StepStatus.RUNNING
        phase.started_at = datetime.now(UTC).isoformat()
        logger.info("workflow_phase_advanced", id=wf_id, phase=phase.effective_name())
        self._notify_event(wf, f"phase_{phase.phase_type.value}")
        self._notify_phase_advanced_chat(wf_id, phase)

    def _notify_phase_advanced_chat(self, wf_id: str, phase: Phase) -> None:
        """Chat桥接: 阶段推进 → 推入Chat"""
        try:
            from src.engine.chat.chat_bridge import on_phase_advanced

            on_phase_advanced(wf_id, phase.phase_type.value)
        except (RuntimeError, ValueError, ImportError, AttributeError) as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)

    def _save_phase_advance_event(self, wf: Workflow) -> None:
        """持久化阶段推进/完成事件"""
        _event_type = "completed" if wf.status == WorkflowStatus.COMPLETED else "phase_advanced"
        _payload = {"current_phase": wf.current_phase}
        if wf.status == WorkflowStatus.COMPLETED:
            _payload["total_phases"] = len(wf.phases)
        self._save(wf, event_type=_event_type, payload=_payload)

    def _handle_phase_failure(self, wf: Workflow, failed_phase: Phase) -> Workflow:
        strategy = failed_phase.on_failure
        logger.info("phase_failure_handled", wf_id=wf.id, phase=failed_phase.effective_name(), strategy=strategy)
        self._notify_event(wf, f"phase_{failed_phase.phase_type.value}_failed_{strategy}")

        if strategy == "halt":
            validate_workflow_transition(wf.status, WorkflowStatus.PAUSED)
            wf.status = WorkflowStatus.PAUSED
            self._save(
                wf,
                event_type="paused",
                payload={"reason": "phase_failure_halt", "phase": failed_phase.phase_type.value},
            )
            return wf

        if strategy == "retry_self":
            return self.retry_phase(wf.id, wf.current_phase)

        if strategy == "retry_plan":
            target_idx = self._find_phase_index(wf, PhaseType.PLAN)
            if target_idx is not None:
                return self.retry_phase(wf.id, target_idx)
            return self.retry_phase(wf.id, 0)

        if strategy == "retry_do":
            target_idx = self._find_phase_index(wf, PhaseType.DO)
            if target_idx is not None:
                return self.retry_phase(wf.id, target_idx)
            return self.retry_phase(wf.id, 1)

        logger.warning("unknown_on_failure_strategy", wf_id=wf.id, strategy=strategy)
        validate_workflow_transition(wf.status, WorkflowStatus.PAUSED)
        wf.status = WorkflowStatus.PAUSED
        self._save(wf, event_type="paused", payload={"reason": "unknown_failure_strategy", "strategy": strategy})
        return wf

    def _find_phase_index(self, wf: Workflow, phase_type: PhaseType) -> int | None:
        for i, p in enumerate(wf.phases):
            if p.phase_type == phase_type:
                return i
        return None

    def _create_next_cycle(self, completed_wf: Workflow) -> Workflow | None:
        """FIX-012: 创建下一轮PDCA循环，受 max_pdca_iterations 上限保护

        Returns:
            新工作流实例，或 None 表示已达上限应停止循环
        """
        next_cycle = completed_wf.pdca_cycle + 1

        # 最大迭代次数保护
        if completed_wf.max_pdca_iterations > 0 and next_cycle > completed_wf.max_pdca_iterations:
            logger.warning(
                "pdca_max_iterations_reached",
                wf_id=completed_wf.id,
                cycle=completed_wf.pdca_cycle,
                max_iterations=completed_wf.max_pdca_iterations,
            )
            self._notify_event(completed_wf, "max_iterations_reached")
            return None

        new_wf = Workflow(
            name=f"{completed_wf.name} (第{next_cycle}轮)",
            description=completed_wf.description,
            template_id=completed_wf.template_id,
            pdca_cycle=next_cycle,
            max_pdca_iterations=completed_wf.max_pdca_iterations,
        )
        if completed_wf.template_id:
            new_wf.phases = self._build_from_scenario_workflow(completed_wf.template_id)
        else:
            new_wf.phases = self._build_default_phases()
        self._wf_mgr.create(new_wf)
        return self.start_workflow(new_wf.id)

    async def run_workflow_auto(self, wf_id: str) -> Workflow:
        """自动执行工作流（编排：校验 → 加锁 → 循环执行步骤）"""
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        if wf.status != WorkflowStatus.RUNNING:
            raise ValidationError(f"工作流状态{wf.status.value}不可自动执行", code="WORKFLOW_CANNOT_AUTO_EXEC")

        self._validate_dag_no_cycle(wf, wf_id)

        # FIX-002: 互斥锁防止同一工作流并发执行
        lock = self._get_wf_lock(wf_id)
        if lock.locked():
            logger.warning("workflow_already_running", wf_id=wf_id)
            return wf
        async with lock:
            return await self._run_auto_loop(wf, wf_id)

    def _validate_dag_no_cycle(self, wf: Workflow, wf_id: str) -> None:
        """FIX-010: 运行时DAG循环校验 — 启动前检查graph_dsl是否含环"""
        if not wf.graph_dsl:
            return
        try:
            nodes, edges = self._parse_graph_dsl(wf.graph_dsl)
            if nodes:
                from src.engine.workflow.dag_utils import detect_cycle_bfs

                if detect_cycle_bfs(nodes, edges):
                    raise ValidationError("工作流DAG包含循环，无法执行", code="WORKFLOW_CYCLE_DETECTED")
        except ValidationError:
            raise
        except (ValueError, KeyError, RuntimeError) as e:
            logger.warning("dag_validation_error", wf_id=wf_id, error=str(e))

    async def _run_auto_loop(self, wf: Workflow, wf_id: str) -> Workflow:
        """自动执行主循环：查找待处理步骤 → 审批/执行 → 推进"""
        while wf.status == WorkflowStatus.RUNNING:
            step, phase = self._find_next_pending_step(wf)
            if step is None:
                next_wf = self._handle_no_pending_step(wf, wf_id)
                if next_wf is None:
                    break  # 已是最后阶段 → 退出循环，返回当前 wf
                wf = next_wf
                continue

            if step.requires_approval and step.status != StepStatus.FAILED:
                self._handle_approval_pending_step(wf, wf_id, step, phase)
                break

            next_wf = await self._execute_step_and_check(wf, wf_id, step)
            if next_wf is None:
                break
            wf = next_wf
            if self._should_stop_after_step(wf, wf_id, step.id):
                break
        return wf

    def _handle_no_pending_step(self, wf: Workflow, wf_id: str) -> Workflow | None:
        """无待处理步骤时推进到下一阶段或退出（返回None表示退出循环）"""
        if wf.current_phase >= len(wf.phases) - 1:
            return None  # 已是最后阶段 → 退出循环
        # 无待处理步骤但还有后续阶段 → 推进到下一阶段继续
        self.advance_phase(wf_id)
        return self._wf_mgr.get(wf_id)

    def _handle_approval_pending_step(self, wf: Workflow, wf_id: str, step: Step, phase: Phase) -> None:
        """处理需要审批的步骤: 挂起、广播、Chat桥接"""
        step.status = StepStatus.APPROVAL_PENDING
        self._save(
            wf,
            event_type="step_executed",
            payload={"step_id": step.id, "step_name": step.name, "status": "approval_pending"},
        )
        self._ws_broadcast(
            wf_id,
            "step_awaiting_approval",
            {
                "workflow_id": wf_id,
                "step_id": step.id,
                "step_name": step.name,
                "agent_role": step.agent_role,
                "phase": phase.phase_type.value,
            },
        )
        self._notify_step_awaiting_approval_chat(wf_id, step, phase)

    def _notify_step_awaiting_approval_chat(self, wf_id: str, step: Step, phase: Phase) -> None:
        """Chat桥接: 审批待定 → 推入Chat审批卡片"""
        try:
            from src.engine.chat.chat_bridge import on_step_awaiting_approval

            on_step_awaiting_approval(wf_id, step.name, step.agent_role, phase.phase_type.value, step.id)
        except (RuntimeError, ValueError, ImportError, AttributeError) as e:
            logger.warning("operation_failed", error=str(e), exc_info=True)

    async def _execute_step_and_check(self, wf: Workflow, wf_id: str, step: Step) -> Workflow | None:
        """执行步骤并重新加载工作流（返回None表示应退出循环）"""
        try:
            await self.execute_step_with_agent(wf_id, step.id)
        except Exception as e:
            logger.error("auto_execute_step_failed", wf_id=wf_id, step_id=step.id, error=str(e), exc_info=True)
            return None
        return self._wf_mgr.get(wf_id)

    def _should_stop_after_step(self, wf: Workflow, wf_id: str, step_id: str) -> bool:
        """步骤执行后判断是否应停止循环"""
        target = self._find_step(wf, step_id)
        if target and target.status in (StepStatus.FAILED, StepStatus.APPROVAL_PENDING):
            return True
        if wf.status == WorkflowStatus.COMPLETED:
            self._ws_broadcast(
                wf_id,
                "workflow_completed",
                {"workflow_id": wf_id, "name": wf.name},
            )
            # Chat桥接已在advance_phase的completed分支处理
            return True
        return False

    def _find_next_pending_step(self, wf: Workflow) -> tuple[Step | None, Phase | None]:
        """查找下一个待执行步骤，支持条件分支评估

        当 workflow_branch feature flag 开启时:
          - 有 condition 的步骤会被评估
          - 条件不满足 → 标记 SKIPPED → 跳过
          - 条件满足或无条件 → 正常返回
          - 条件评估异常 → 标记 FAILED → 跳过（避免静默跳过必要步骤）
        当当前 phase 有审批阻塞中的步骤时:
          - 返回 None, 阻止后续步骤执行
        """
        if not wf.phases or wf.current_phase >= len(wf.phases):
            return None, None

        # 检查 feature flag
        from src.engine.feature.flags import is_enabled as _isf

        branch_enabled = _isf("workflow_branch")

        phase = wf.phases[wf.current_phase]

        # 审批阻塞: 当前 phase 有 APPROVAL_PENDING 步骤 → 阻止后续执行
        for step in phase.steps:
            if step.status == StepStatus.APPROVAL_PENDING:
                return None, None

        for step in phase.steps:
            if step.status not in (StepStatus.PENDING, StepStatus.FAILED):
                continue

            # 已因条件评估失败过的步骤 → 不再重复评估（避免无限循环）
            if step.status == StepStatus.FAILED and step.result.startswith(_COND_EVAL_FAIL_PREFIX):
                continue

            # 无条件 → 直接返回
            if not step.condition or not branch_enabled:
                return step, phase

            # 有条件 → 评估
            try:
                skip = self._should_skip_step(wf, step)
            except Exception as exc:
                logger.debug("exception_handled", error=str(exc))
                # 评估异常：步骤已在 _should_skip_step 中标记为 FAILED 并保存
                continue

            if skip:
                step.status = StepStatus.SKIPPED
                step.finished_at = datetime.now(UTC).isoformat()
                logger.info("step_skipped_by_condition", wf_id=wf.id, step_id=step.id, condition=step.condition[:80])
                self._save(
                    wf,
                    event_type="step_skipped",
                    payload={"step_id": step.id, "step_name": step.name, "condition": step.condition[:100]},
                )
                continue

            return step, phase

        return None, None

    def _should_skip_step(self, wf: Workflow, step: Step) -> bool:
        """评估步骤条件，返回是否应跳过 (True=跳过, False=执行)

        异常处理: 当 evaluate() 抛出异常时，将步骤标记为 FAILED（而非静默跳过），
        记录错误日志，并重新抛出异常以便上层 _find_next_pending_step 感知。
        """
        from src.engine.workflow.condition_evaluator import get_condition_evaluator

        evaluator = get_condition_evaluator()

        # 使用 Workflow.store 运行时KV缓存
        store = wf.store or {}
        context = self._build_condition_context(wf, step)

        # 评估条件 (返回 True=条件满足=执行, False=条件不满足=跳过)
        try:
            should_execute = evaluator.evaluate(
                step.condition,
                store=store,
                context=context,
                flag_enabled=True,  # _find_next_pending_step 已检查 flag
            )
        except Exception as e:
            logger.error(
                "condition_evaluation_failed",
                wf_id=wf.id,
                step_id=step.id,
                step_name=step.name,
                condition=step.condition,
                error=str(e),
                exc_info=True,
            )
            step.status = StepStatus.FAILED
            step.result = f"{_COND_EVAL_FAIL_PREFIX}: {e}"
            step.finished_at = datetime.now(UTC).isoformat()
            if hasattr(self, "_save"):
                self._save(wf)
            raise

        return not should_execute

    def _build_condition_context(self, wf: Workflow, current_step: Step) -> dict:
        """构建条件评估上下文: step_statuses + prev_result"""
        step_statuses: dict[str, str] = {}
        prev_result = ""
        found_prev = False

        for phase in wf.phases:
            for step in phase.steps:
                step_statuses[step.id] = step.status.value if hasattr(step.status, "value") else str(step.status)
                if step.id == current_step.id:
                    found_prev = True
                    break
                if step.result:
                    prev_result = str(step.result) if not isinstance(step.result, str) else step.result
            if found_prev:
                break

        return {
            "step_statuses": step_statuses,
            "prev_result": prev_result,
        }

    def resume_from_step(self, workflow_id: str, step_id: str) -> Workflow:
        wf = self._wf_mgr.get(workflow_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        for phase_idx, phase in enumerate(wf.phases):
            for step in phase.steps:
                if step.id == step_id:
                    validate_workflow_transition(wf.status, WorkflowStatus.RUNNING)
                    wf.status = WorkflowStatus.RUNNING
                    wf.current_phase = phase_idx
                    for prev_step in phase.steps:
                        if prev_step.id != step_id and prev_step.status == StepStatus.PENDING:
                            prev_step.status = StepStatus.DONE
                            prev_step.finished_at = datetime.now(UTC).isoformat()
                            self._log_step(workflow_id, prev_step, phase.phase_type)
                        if prev_step.id == step_id:
                            prev_step.status = StepStatus.PENDING
                            prev_step.result = ""
                    phase.status = StepStatus.RUNNING
                    for p_idx in range(phase_idx):
                        wf.phases[p_idx].status = StepStatus.DONE
                        wf.phases[p_idx].finished_at = datetime.now(UTC).isoformat()
                    self._save(wf, event_type="started", payload={"action": "resume_from_step", "step_id": step_id})
                    logger.info("workflow_resumed", workflow_id=workflow_id, step_id=step_id)
                    return wf

        raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")

    # ── VariablePool 集成 ──────────────────────────────────────────

    def _get_variable_pool(self, wf_id: str) -> VariablePool:
        """获取或创建工作流对应的 VariablePool。"""
        from src.engine.workflow.variable_pool import get_global_registry

        reg = get_global_registry()
        return reg.get_or_create(wf_id)

    def _apply_variables(self, wf_id: str, template: str | None) -> str:
        """解析模板字符串中的变量引用。

        使用 VariablePool 三层变量 (global/workflow/steps) 渲染模板。
        """
        if not template:
            return template or ""
        pool = self._get_variable_pool(wf_id)
        return pool.resolve(template)

    def _inject_step_output(self, wf_id: str, step_id: str, output: Any) -> None:
        """将步骤输出注入 VariablePool。"""
        pool = self._get_variable_pool(wf_id)
        pool.set_step_output(step_id, output if isinstance(output, dict) else {"result": output})

    def _set_workflow_var(self, wf_id: str, key: str, value: Any) -> None:
        """设置工作流级变量。"""
        pool = self._get_variable_pool(wf_id)
        pool.set_workflow(key, value)

    def _set_global_var(self, key: str, value: Any) -> None:
        """设置全局变量（跨工作流共享）。"""
        from src.engine.workflow.variable_pool import get_global_registry

        reg = get_global_registry()
        reg.set_shared(key, value)
