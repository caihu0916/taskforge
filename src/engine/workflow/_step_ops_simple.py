
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 步骤同步操作Mixin"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from src.engine.workflow.models import (
    StepStatus,
    Workflow,
    WorkflowStatus,
)
from src.exceptions import ValidationError

logger = structlog.get_logger(__name__)


class StepOpsSimpleMixin:
    """步骤同步操作方法"""

    def execute_step(self, wf_id: str, step_id: str, result: str = "") -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    if step.requires_approval:
                        step.status = StepStatus.APPROVAL_PENDING
                        step.result = result
                        step.finished_at = datetime.now(UTC).isoformat()
                        self._log_step(wf_id, step, phase.phase_type)
                        self._save(
                            wf,
                            event_type="step_executed",
                            payload={"step_id": step_id, "step_name": step.name, "status": "approval_pending"},
                        )
                        # 提交审批记录到审批引擎
                        try:
                            self.approval_engine.submit_approval(
                                target_type="step",
                                target_id=step_id,
                                workflow_id=wf_id,
                                title=f"步骤审批: {step.name}",
                                description=step.action[:200] if step.action else "",
                                context={"phase": phase.phase_type.value, "result_preview": (result or "")[:200]},
                            )
                        except Exception:
                            logger.debug("approval_submit_failed", wf_id=wf_id, step_id=step_id, exc_info=True)
                        logger.info("step_awaiting_approval", wf_id=wf_id, step_id=step_id)
                        return wf

                    step.status = StepStatus.DONE
                    step.result = result
                    step.finished_at = datetime.now(UTC).isoformat()
                    self._log_step(wf_id, step, phase.phase_type)
                    self._save(
                        wf,
                        event_type="step_executed",
                        payload={"step_id": step_id, "step_name": step.name, "result_preview": (result or "")[:100]},
                    )
                    self._maybe_learn_from_step(step)

                    if self._is_phase_complete(wf):
                        wf = self._auto_advance_if_allowed(wf)

                    return wf

        raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")

    def fail_step(self, wf_id: str, step_id: str, error: str = "") -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    step.status = StepStatus.FAILED
                    step.result = error
                    step.finished_at = datetime.now(UTC).isoformat()
                    self._log_step(wf_id, step, phase.phase_type)
                    self._save(
                        wf,
                        event_type="step_failed",
                        payload={"step_id": step_id, "step_name": step.name, "error": (error or "")[:200]},
                    )

                    if self._is_phase_complete(wf):
                        wf = self._auto_advance_if_allowed(wf)
                    return wf

        raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")

    def approve_step(self, wf_id: str, step_id: str, approver: str = "", comment: str = "") -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    if step.status != StepStatus.APPROVAL_PENDING:
                        raise ValidationError(f"步骤状态为{step.status.value}, 无需审批", code="STEP_NOT_PENDING")
                    # 审批引擎记录审批通过
                    try:
                        pending = self.approval_engine.find_pending("step", step_id)
                        if pending:
                            self.approval_engine.approve(pending.id, approver=approver, comment=comment)
                    except Exception:
                        logger.debug("approval_record_approve_failed", wf_id=wf_id, step_id=step_id, exc_info=True)
                    step.status = StepStatus.DONE
                    step.finished_at = datetime.now(UTC).isoformat()
                    self._maybe_learn_from_step(step)
                    # 人类审批完成后, 恢复工作流 RUNNING 状态 (agent 路径中设置了 PAUSED)
                    if wf.status == WorkflowStatus.PAUSED:
                        wf.status = WorkflowStatus.RUNNING
                        # P0-2 FIX: 审批后自动恢复工作流执行
                        # 异步继续自动执行（不阻塞审批响应）
                        try:
                            import asyncio

                            loop = asyncio.get_running_loop()
                            loop.create_task(self.run_workflow_auto(wf.id))
                        except RuntimeError:
                            # 没有运行的事件循环，记录调试信息
                            logger.debug("workflow_resume_no_event_loop", wf_id=wf_id)
                    self._save(
                        wf,
                        event_type="step_approved",
                        payload={"step_id": step_id, "step_name": step.name, "approver": approver},
                    )
                    logger.info("step_approved", wf_id=wf_id, step_id=step_id, approver=approver)
                    if self._is_phase_complete(wf):
                        wf = self._auto_advance_if_allowed(wf)
                    self._ws_broadcast(
                        wf_id,
                        "step_approved",
                        {
                            "workflow_id": wf_id,
                            "step_id": step_id,
                            "step_name": step.name,
                            "status": wf.status.value,
                        },
                    )
                    return wf

        raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")

    def reject_step(self, wf_id: str, step_id: str, reason: str = "", rejecter: str = "") -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        for phase in wf.phases:
            for step in phase.steps:
                if step.id == step_id:
                    if step.status != StepStatus.APPROVAL_PENDING:
                        raise ValidationError(f"步骤状态为{step.status.value}, 无需驳回")
                    # 审批引擎记录审批驳回
                    try:
                        pending = self.approval_engine.find_pending("step", step_id)
                        if pending:
                            self.approval_engine.reject(pending.id, rejecter=rejecter, reason=reason)
                    except Exception:
                        logger.debug("approval_record_reject_failed", wf_id=wf_id, step_id=step_id, exc_info=True)
                    step.status = StepStatus.FAILED
                    step.result = f"审批驳回: {reason}" if reason else "审批驳回"
                    self._save(
                        wf,
                        event_type="step_rejected",
                        payload={"step_id": step_id, "step_name": step.name, "reason": (reason or "")[:200]},
                    )
                    logger.info("step_rejected", wf_id=wf_id, step_id=step_id, rejecter=rejecter)
                    return wf

        raise ValidationError("步骤不存在", code="STEP_NOT_FOUND")

    def _is_phase_complete(self, wf: Workflow) -> bool:
        if wf.current_phase >= len(wf.phases):
            return False
        current = wf.phases[wf.current_phase]
        if not current.steps:
            return True
        # Phase is complete when all steps are in a terminal state
        # (DONE/SKIPPED = success, FAILED = triggers on_failure strategy)
        return all(s.status in (StepStatus.DONE, StepStatus.SKIPPED, StepStatus.FAILED) for s in current.steps)

    def _is_phase_successful(self, wf: Workflow) -> bool:
        """Check if all steps in current phase completed successfully (DONE/SKIPPED only)."""
        if wf.current_phase >= len(wf.phases):
            return False
        current = wf.phases[wf.current_phase]
        if not current.steps:
            return True
        return all(s.status in (StepStatus.DONE, StepStatus.SKIPPED) for s in current.steps)
