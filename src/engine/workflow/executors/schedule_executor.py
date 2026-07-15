
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Schedule 节点执行器(P1-S1-006)

定时调度节点,支持 cron 表达式和间隔触发。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from . import BaseExecutor, NodeInput, NodeOutput, register_executor

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from src.engine.scheduler.cron import CronManager

# 全局 CronManager 实例
_cron_manager: CronManager | None = None


def _get_cron_manager() -> CronManager:
    """获取或创建全局 CronManager 实例"""
    global _cron_manager
    if _cron_manager is None:
        from src.engine.scheduler.cron import CronManager

        _cron_manager = CronManager()
    return _cron_manager


@register_executor("schedule")
class ScheduleExecutor(BaseExecutor):
    """定时调度执行器

    配置:
        mode: 调度模式(cron | interval | once,默认 once)
        cron: cron 表达式(mode=cron 时必填)
        interval: 间隔秒数(mode=interval 时必填)
        execute_at: 执行时间 ISO 格式(mode=once 时必填)
        timezone: 时区(默认 UTC)
    """

    node_type = "schedule"
    config_schema = {
        "mode": {"required": False, "type": "string", "default": "once"},
        "cron": {"required": False, "type": "string", "default": ""},
        "interval": {"required": False, "type": "number", "default": 0},
        "execute_at": {"required": False, "type": "string", "default": ""},
        "timezone": {"required": False, "type": "string", "default": "UTC"},
        "prompt": {"required": False, "type": "string", "default": ""},
        "recurring": {"required": False, "type": "boolean", "default": True},
        "durable": {"required": False, "type": "boolean", "default": True},
    }

    async def execute(self, inp: NodeInput) -> NodeOutput:
        mode = inp.config.get("mode", "once")
        prompt = inp.config.get("prompt", inp.node_id or "scheduled_task")
        recurring = inp.config.get("recurring", True)
        durable = inp.config.get("durable", True)

        if mode == "cron":
            cron_expr = inp.config.get("cron", "")
            if not cron_expr:
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error="cron expression is required for cron mode",
                )
            # 验证 cron 表达式格式(简化版)
            parts = cron_expr.split()
            if len(parts) != 5:
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error=f"Invalid cron expression: {cron_expr} (expected 5 fields)",
                )

            # 注册到 CronManager
            try:
                cron_mgr = _get_cron_manager()
                job_id = cron_mgr.create(
                    cron=cron_expr,
                    prompt=prompt,
                    recurring=recurring,
                    durable=durable,
                    enabled=True,
                )
                logger.info("schedule_cron_registered", node_id=inp.node_id, job_id=job_id, cron=cron_expr)
            except Exception as e:
                logger.warning("schedule_cron_registration_failed", node_id=inp.node_id, error=str(e))
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error=f"Failed to register cron job: {e}",
                )

            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "mode": "cron",
                    "cron": cron_expr,
                    "job_id": job_id,
                    "next_run": "scheduled",
                    "timezone": inp.config.get("timezone", "UTC"),
                },
            )

        if mode == "interval":
            interval = inp.config.get("interval", 0)
            if interval <= 0:
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error="interval must be positive for interval mode",
                )

            # interval 模式使用 cron 近似实现 (每 interval 秒)
            # 转换为 cron 表达式: */n * * * * 表示每 n 分钟
            if interval >= 60:
                minutes = interval // 60
                cron_expr = f"*/{minutes} * * * *"
            else:
                # 对于小于 60 秒的间隔，转换为每 n 分钟的 cron
                # 注意：标准 cron 最小精度是分钟，小于 60 秒需要特殊处理
                cron_expr = "*/1 * * * *"
                logger.warning("interval_approximated_to_cron", original_seconds=interval, cron=cron_expr)

            try:
                cron_mgr = _get_cron_manager()
                job_id = cron_mgr.create(
                    cron=cron_expr,
                    prompt=f"{prompt} (interval={interval}s)",
                    recurring=recurring,
                    durable=durable,
                    enabled=True,
                )
                logger.info("schedule_interval_registered", node_id=inp.node_id, job_id=job_id, interval=interval)
            except Exception as e:
                logger.warning("schedule_interval_registration_failed", node_id=inp.node_id, error=str(e))
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error=f"Failed to register interval job: {e}",
                )

            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "mode": "interval",
                    "interval_seconds": interval,
                    "job_id": job_id,
                    "next_run": "scheduled",
                },
            )

        if mode == "once":
            execute_at = inp.config.get("execute_at", "")
            # once 模式使用 recurring=False 的 cron
            if not execute_at:
                # 立即执行，返回成功但不注册
                return NodeOutput(
                    node_id=inp.node_id,
                    status="completed",
                    output={
                        "mode": "once",
                        "execute_at": "immediate",
                        "next_run": "immediate",
                    },
                )

            # 尝试将 execute_at 转换为 cron 表达式（仅精确到分钟）
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
                # 转换为 5 字段 cron: 分 时 日 月 星期
                cron_expr = f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"
                cron_mgr = _get_cron_manager()
                job_id = cron_mgr.create(
                    cron=cron_expr,
                    prompt=prompt,
                    recurring=False,  # oneshot
                    durable=durable,
                    enabled=True,
                )
                logger.info("schedule_once_registered", node_id=inp.node_id, job_id=job_id, execute_at=execute_at)
            except Exception as e:
                logger.warning("schedule_once_registration_failed", node_id=inp.node_id, error=str(e))
                return NodeOutput(
                    node_id=inp.node_id,
                    status="failed",
                    error=f"Failed to parse execute_at or register job: {e}",
                )

            return NodeOutput(
                node_id=inp.node_id,
                status="completed",
                output={
                    "mode": "once",
                    "execute_at": execute_at,
                    "job_id": job_id,
                    "next_run": execute_at,
                },
            )

        return NodeOutput(
            node_id=inp.node_id,
            status="failed",
            error=f"Unknown schedule mode: {mode}",
        )
