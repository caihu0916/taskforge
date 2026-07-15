
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""PDCA引擎 — 阶段操作 (审批/重试/截止时间)"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from src.engine.workflow.models import (
    StepStatus,
    Workflow,
    WorkflowStatus,
)
from src.exceptions import ValidationError

logger = structlog.get_logger(__name__)


class PhaseOpsMixin:
    """阶段级操作方法"""

    def retry_phase(self, wf_id: str, target_phase_idx: int) -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")
        if target_phase_idx >= len(wf.phases):
            raise ValidationError(f"阶段索引{target_phase_idx}超出范围", code="PHASE_INDEX_OUT_OF_RANGE")

        target_phase = wf.phases[target_phase_idx]

        for step in target_phase.steps:
            if (
                step.status in (StepStatus.FAILED, StepStatus.DONE, StepStatus.SKIPPED)
                and step.result
                and not step.result.startswith("[重试]")
            ):
                step.result = f"[重试] {step.result}"
            step.status = StepStatus.PENDING
            step.started_at = ""
            step.finished_at = ""

        # 重置后续阶段的状态为 PENDING
        for i in range(target_phase_idx + 1, len(wf.phases)):
            later_phase = wf.phases[i]
            later_phase.status = StepStatus.PENDING
            later_phase.started_at = ""
            later_phase.finished_at = ""
            for step in later_phase.steps:
                step.status = StepStatus.PENDING
                step.started_at = ""
                step.finished_at = ""
                step.result = ""

        wf.current_phase = target_phase_idx
        target_phase.status = StepStatus.RUNNING
        target_phase.started_at = datetime.now(UTC).isoformat()
        target_phase.finished_at = ""
        wf.status = WorkflowStatus.RUNNING

        self._save(
            wf,
            event_type="phase_advanced",
            payload={"action": "retry", "target_phase": target_phase_idx, "phase_name": target_phase.effective_name()},
        )
        logger.info("phase_retried", wf_id=wf_id, target_phase=target_phase.effective_name())
        return wf

    def approve_phase(self, wf_id: str, approver: str = "", comment: str = "") -> Workflow:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            raise ValidationError("工作流不存在", code="WORKFLOW_NOT_FOUND")

        if wf.current_phase >= len(wf.phases):
            raise ValidationError("工作流已无当前阶段", code="NO_CURRENT_PHASE")

        current_phase = wf.phases[wf.current_phase]
        if not current_phase.requires_approval:
            raise ValidationError("当前阶段无需审批", code="PHASE_NO_APPROVAL_REQUIRED")
        if current_phase.status != StepStatus.APPROVAL_PENDING:
            raise ValidationError(
                f"阶段状态为{current_phase.status.value}, 未在审批等待", code="PHASE_NOT_PENDING_APPROVAL"
            )

        # 审批引擎记录阶段审批通过
        try:
            pending = self.approval_engine.find_pending("phase", str(wf.current_phase))
            if pending:
                self.approval_engine.approve(pending.id, approver=approver, comment=comment)
            else:
                # 没找到pending记录也创建一个approved记录留痕
                self.approval_engine.submit_approval(
                    target_type="phase",
                    target_id=str(wf.current_phase),
                    workflow_id=wf_id,
                    title=f"阶段审批: {current_phase.effective_name()}",
                )
                just_created = self.approval_engine.find_pending("phase", str(wf.current_phase))
                if just_created:
                    self.approval_engine.approve(just_created.id, approver=approver, comment=comment)
        except Exception:
            logger.debug("phase_approval_record_failed", wf_id=wf_id, exc_info=True)

        current_phase.requires_approval = False
        logger.info("phase_approved", wf_id=wf_id, phase=current_phase.effective_name(), approver=approver)
        return self.advance_phase(wf_id)

    def check_deadlines(self, wf_id: str) -> dict[str, Any]:
        wf = self._wf_mgr.get(wf_id)
        if wf is None:
            return {"overdue_steps": [], "error": "工作流不存在"}

        now = datetime.now(UTC)
        overdue: list[dict[str, str]] = []

        for phase in wf.phases:
            for step in phase.steps:
                if step.deadline and step.status in (
                    StepStatus.PENDING,
                    StepStatus.RUNNING,
                    StepStatus.APPROVAL_PENDING,
                ):
                    try:
                        deadline_dt = datetime.fromisoformat(step.deadline)
                        if deadline_dt.tzinfo is None:
                            deadline_dt = deadline_dt.replace(tzinfo=UTC)
                        if now > deadline_dt:
                            step.status = StepStatus.FAILED
                            step.result = f"超时自动失败 (截止: {step.deadline})"
                            step.finished_at = now.isoformat()
                            overdue.append(
                                {
                                    "step_id": step.id,
                                    "name": step.name,
                                    "deadline": step.deadline,
                                }
                            )
                            self._log_step(wf_id, step, phase.phase_type)
                    except (ValueError, TypeError):
                        logger.warning("invalid_deadline_format", step_id=step.id, deadline=step.deadline)

        for phase in wf.phases:
            if phase.deadline and phase.status in (StepStatus.PENDING, StepStatus.RUNNING, StepStatus.APPROVAL_PENDING):
                try:
                    deadline_dt = datetime.fromisoformat(phase.deadline)
                    if deadline_dt.tzinfo is None:
                        deadline_dt = deadline_dt.replace(tzinfo=UTC)
                    if now > deadline_dt:
                        for step in phase.steps:
                            if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                                step.status = StepStatus.FAILED
                                step.result = f"阶段超时 (截止: {phase.deadline})"
                                step.finished_at = now.isoformat()
                                overdue.append(
                                    {
                                        "step_id": step.id,
                                        "name": step.name,
                                        "deadline": phase.deadline,
                                        "phase_deadline": True,
                                    }
                                )
                        phase.status = StepStatus.FAILED
                except (ValueError, TypeError):
                    logger.debug("phase_deadline_parse_failed")

        if overdue:
            self._save(
                wf,
                event_type="step_failed",
                payload={
                    "action": "deadline_expired",
                    "overdue_count": len(overdue),
                    "step_ids": [o["step_id"] for o in overdue],
                },
            )
            logger.warning("deadlines_expired", wf_id=wf_id, count=len(overdue))
            # 超时后尝试自动推进阶段 (仅RUNNING状态才推进)
            from src.engine.workflow.models import WorkflowStatus

            if wf.status == WorkflowStatus.RUNNING:
                wf = self._auto_advance_if_allowed(wf)

        return {"overdue_steps": overdue}
