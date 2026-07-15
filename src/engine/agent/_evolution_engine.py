
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent进化引擎 - 核心引擎

包含 AgentEvolutionEngine 核心类
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog

from src.exceptions import AgentError

from ._evolution_models import (
    EvolutionPhase,
    EvolutionReport,
    EvolutionSession,
    EvolutionStatus,
    EvolutionStep,
    ExecutionRecord,
    ExecutionResult,
    MemoryEntry,
    Strategy,
    StrategyType,
)

logger = structlog.get_logger(__name__)


class AgentEvolutionEngine:
    """Agent自我进化引擎"""

    def __init__(self, db_conn=None):
        self._db = db_conn
        self._success_threshold = 0.7  # 成功率阈值
        self._quality_threshold = 3.5  # 质量评分阈值 (1-5)
        self._min_samples = 10  # 最小样本数

    # ── 进化会话管理 ──

    def create_session(self, goal: str, max_iterations: int = 5) -> EvolutionSession:
        """创建进化会话"""
        session = EvolutionSession(goal=goal, max_iterations=max_iterations)
        logger.info("evolution_session_created", goal=goal, max_iterations=max_iterations)
        return session

    def start_iteration(self, session: EvolutionSession) -> EvolutionStep:
        """开始新的迭代"""
        if session.current_iteration >= session.max_iterations:
            raise AgentError(f"最大迭代次数已达: {session.max_iterations}")

        session.current_iteration += 1
        step = EvolutionStep(
            iteration=session.current_iteration,
            session_id=session.id,
            phase=EvolutionPhase.PLAN,
            status=EvolutionStatus.RUNNING,
        )
        session.steps.append(step)
        return step

    def plan(self, step: EvolutionStep, plan: str) -> None:
        """制定计划"""
        step.plan = plan
        step.phase = EvolutionPhase.PLAN

    def execute(self, step: EvolutionStep, action: str, result: dict[str, Any] | None = None) -> None:
        """执行动作"""
        step.action = action
        step.action_result = result or {}
        step.phase = EvolutionPhase.EXECUTE

    def reflect(
        self, step: EvolutionStep, reflection: str, success: bool = False, issues: list[str] | None = None
    ) -> None:
        """反思结果"""
        step.reflection = reflection
        step.success = success
        step.issues = issues or []
        step.phase = EvolutionPhase.REFLECT

    def learn(self, step: EvolutionStep, learned: str, rules: list[str] | None = None) -> None:
        """学习总结"""
        step.learned = learned
        step.rules_applied = rules or []
        step.phase = EvolutionPhase.LEARN

    def check_completion(self, session: EvolutionSession) -> str:
        """检查是否完成"""
        latest = session.latest_step
        if latest is None:
            return "continue"

        if latest.success:
            session.status = EvolutionStatus.COMPLETED
            session.is_complete = True
            session.completed_at = datetime.now().isoformat()
            return "completed"

        if session.current_iteration >= session.max_iterations:
            session.status = EvolutionStatus.COMPLETED
            session.is_complete = True
            session.completed_at = datetime.now().isoformat()
            return "max_reached"

        return "continue"

    def get_session_summary(self, session: EvolutionSession) -> dict[str, Any]:
        """获取会话摘要"""
        successes = sum(1 for s in session.steps if s.success)
        learned_items = [s.learned for s in session.steps if s.learned]
        return {
            "goal": session.goal,
            "iterations": session.current_iteration,
            "total_steps": len(session.steps),
            "successes": successes,
            "learned": learned_items,
            "status": session.status.value,
        }

    # ── 执行记录 ──

    def record_execution(
        self,
        agent_id: str,
        task_id: str,
        task_description: str,
        strategy_id: str,
        result: ExecutionResult,
        duration: float = 0.0,
        tokens: int = 0,
        user_score: float = 0.0,
        error: str = "",
        quality_score: float = 0.0,
    ) -> ExecutionRecord:
        """记录执行结果"""
        record = ExecutionRecord(
            agent_id=agent_id,
            task_id=task_id,
            task_description=task_description,
            strategy_used=strategy_id,
            result=result,
            duration_seconds=duration,
            tokens_used=tokens,
            user_feedback_score=user_score,
            error_message=error,
            output_quality_score=quality_score,
        )

        if self._db:
            with self._db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO execution_records
                    (id, agent_id, task_id, task_description, strategy_used, result,
                     duration_seconds, tokens_used, user_feedback_score, error_message, output_quality_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id,
                        record.agent_id,
                        record.task_id,
                        record.task_description,
                        record.strategy_used,
                        record.result.value,
                        record.duration_seconds,
                        record.tokens_used,
                        record.user_feedback_score,
                        record.error_message,
                        record.output_quality_score,
                    ),
                )
                conn.commit()

        # 更新策略统计
        self._update_strategy_stats(strategy_id, result, duration, quality_score)

        # 如果失败，提取教训
        if result == ExecutionResult.FAILED and error:
            self._extract_lesson(agent_id, task_description, error)

        logger.info("execution_recorded", agent=agent_id, task=task_id, result=result.value)
        return record

    def create_strategy(self, name: str, strategy_type: StrategyType, content: dict[str, Any]) -> Strategy:
        """创建新策略"""
        strategy = Strategy(
            name=name,
            strategy_type=strategy_type,
            content=content,
        )

        if self._db:
            with self._db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO strategies
                    (id, name, strategy_type, content, version, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        strategy.id,
                        strategy.name,
                        strategy.strategy_type.value,
                        json.dumps(content, ensure_ascii=False),
                        strategy.version,
                        strategy.is_active,
                    ),
                )
                conn.commit()

        logger.info("strategy_created", name=name, type=strategy_type.value)
        return strategy

    def add_memory(self, category: str, title: str, content: str, tags: list[str] | None = None) -> MemoryEntry:
        """添加记忆"""
        entry = MemoryEntry(
            category=category,
            title=title,
            content=content,
            tags=tags or [],
        )

        if self._db:
            with self._db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO memories
                    (id, category, title, content, tags, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        entry.id,
                        entry.category,
                        entry.title,
                        entry.content,
                        ",".join(entry.tags),
                        entry.confidence,
                    ),
                )
                conn.commit()

        logger.info("memory_added", category=category, title=title)
        return entry

    def get_relevant_memories(self, task_description: str, limit: int = 5) -> list[MemoryEntry]:
        """获取相关记忆 (基于关键词匹配)"""
        if not self._db:
            return []

        # 简化版: 基于标签匹配
        keywords = self._extract_keywords(task_description)
        if not keywords:
            return []

        with self._db.get_conn() as conn:
            rows = conn.execute(
                """SELECT id, content, layer, tags, metadata, created_at, updated_at, accessed_at, access_count, consumed, source_agent, confidence, learning_type, session_id, importance, decay_score FROM memories
                WHERE tags LIKE ? OR title LIKE ? OR content LIKE ?
                ORDER BY confidence DESC, usage_count DESC
                LIMIT ?""",
                (f"%{keywords[0]}%", f"%{keywords[0]}%", f"%{keywords[0]}%", limit),
            ).fetchall()

        return [
            MemoryEntry(
                id=row[0],
                category=row[1],
                title=row[2],
                content=row[3],
                tags=row[4].split(",") if row[4] else [],
                confidence=row[5],
                usage_count=row[6],
                last_used_at=row[7],
            )
            for row in rows
        ]

    def list_memories(self, category: str = "", limit: int = 50) -> list[MemoryEntry]:
        """列出记忆（按分类过滤）"""
        if not self._db:
            return []

        with self._db.get_conn() as conn:
            if category:
                rows = conn.execute(
                    """SELECT id, content, layer, tags, metadata, created_at, updated_at, accessed_at, access_count, consumed, source_agent, confidence, learning_type, session_id, importance, decay_score FROM memories
                    WHERE category = ?
                    ORDER BY created_at DESC
                    LIMIT ?""",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, content, layer, tags, metadata, created_at, updated_at, accessed_at, access_count, consumed, source_agent, confidence, learning_type, session_id, importance, decay_score FROM memories
                    ORDER BY created_at DESC
                    LIMIT ?""",
                    (limit,),
                ).fetchall()

        return [
            MemoryEntry(
                id=row[0],
                category=row[1],
                title=row[2],
                content=row[3],
                tags=row[4].split(",") if row[4] else [],
                confidence=row[5],
                usage_count=row[6],
                last_used_at=row[7],
                created_at=row[8] if len(row) > 8 else "",
            )
            for row in rows
        ]

    def run_evolution_cycle(self) -> EvolutionReport:
        """执行进化周期 (建议每天运行一次)"""
        now = datetime.now()
        period_start = (now - timedelta(days=7)).isoformat()
        period_end = now.isoformat()

        report = EvolutionReport(
            period_start=period_start,
            period_end=period_end,
            generated_at=now.isoformat(),
        )

        if not self._db:
            return report

        with self._db.get_conn() as conn:
            # 统计执行
            row = conn.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN result='success' THEN 1 ELSE 0 END),
                          AVG(output_quality_score),
                          AVG(duration_seconds)
                   FROM execution_records
                   WHERE created_at BETWEEN ? AND ?""",
                (period_start, period_end),
            ).fetchone()

            if row:
                report.total_executions = row[0] or 0
                report.success_rate = (row[1] / row[0] * 100) if row[0] > 0 else 0
                report.avg_quality_score = row[2] or 0
                report.avg_duration = row[3] or 0

            # 最佳策略
            rows = conn.execute(
                """SELECT s.id, s.name, s.success_count, s.failure_count, s.avg_quality_score
                   FROM strategies s
                   WHERE s.is_active=1 AND (s.success_count + s.failure_count) >= ?
                   ORDER BY CAST(s.success_count AS FLOAT) / NULLIF(s.success_count + s.failure_count, 0) DESC
                   LIMIT 5""",
                (self._min_samples,),
            ).fetchall()

            report.top_strategies = [
                {
                    "id": r[0],
                    "name": r[1],
                    "success_rate": f"{r[2] / (r[2] + r[3]) * 100:.1f}%" if (r[2] + r[3]) > 0 else "0%",
                    "avg_quality": r[4],
                }
                for r in rows
            ]

            # 最差策略
            rows = conn.execute(
                """SELECT s.id, s.name, s.success_count, s.failure_count, s.avg_quality_score
                   FROM strategies s
                   WHERE s.is_active=1 AND (s.success_count + s.failure_count) >= ?
                   ORDER BY CAST(s.success_count AS FLOAT) / NULLIF(s.success_count + s.failure_count, 0) ASC
                   LIMIT 5""",
                (self._min_samples,),
            ).fetchall()

            report.worst_strategies = [
                {
                    "id": r[0],
                    "name": r[1],
                    "success_rate": f"{r[2] / (r[2] + r[3]) * 100:.1f}%" if (r[2] + r[3]) > 0 else "0%",
                    "avg_quality": r[4],
                }
                for r in rows
            ]

        # 生成建议
        report.recommendations = self._generate_recommendations(report)

        # 执行策略调整
        report.strategies_adjusted = self._adjust_strategies(report.worst_strategies)

        logger.info("evolution_cycle_completed", executions=report.total_executions, success_rate=report.success_rate)
        return report

    def _update_strategy_stats(
        self, strategy_id: str, result: ExecutionResult, duration: float, quality_score: float
    ) -> None:
        """更新策略统计"""
        if not self._db:
            return

        with self._db.get_conn() as conn:
            if result == ExecutionResult.SUCCESS:
                conn.execute(
                    "UPDATE strategies SET success_count = success_count + 1 WHERE id=?",
                    (strategy_id,),
                )
            else:
                conn.execute(
                    "UPDATE strategies SET failure_count = failure_count + 1 WHERE id=?",
                    (strategy_id,),
                )

            # 更新平均质量
            conn.execute(
                """UPDATE strategies
                SET avg_quality_score = (
                    SELECT AVG(output_quality_score) FROM execution_records
                    WHERE strategy_used=? AND output_quality_score > 0
                ),
                avg_duration = (
                    SELECT AVG(duration_seconds) FROM execution_records
                    WHERE strategy_used=?
                ),
                updated_at = ?
                WHERE id=?""",
                (strategy_id, strategy_id, datetime.now().isoformat(), strategy_id),
            )
            conn.commit()

    def _extract_lesson(self, agent_id: str, task_description: str, error: str) -> None:
        """从失败中提取教训"""
        lesson_title = f"失败教训: {task_description[:50]}..."
        lesson_content = f"错误: {error}\n\n建议避免类似操作。"

        self.add_memory(
            category="pitfall",
            title=lesson_title,
            content=lesson_content,
            tags=[agent_id, "failure"],
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """提取关键词 (简化版)"""
        # 实际应使用NLP库，这里简单分词
        stop_words = {
            "的",
            "了",
            "是",
            "在",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "一个",
            "上",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "自己",
            "这",
        }
        keywords = []
        for word in text.split():
            if word not in stop_words and len(word) > 1:
                keywords.append(word)
        return keywords[:5]

    def _generate_recommendations(self, report: EvolutionReport) -> list[str]:
        """生成进化建议"""
        recommendations = []

        if report.success_rate < 50:
            recommendations.append("成功率低于50%，建议全面审查策略和prompt质量")
        elif report.success_rate < 70:
            recommendations.append("成功率偏低，建议优化失败案例中的策略")

        if report.avg_quality_score < 3.0:
            recommendations.append("平均质量评分较低，建议提升输出质量标准")

        if report.avg_duration > 300:
            recommendations.append("平均执行时间超过5分钟，建议优化流程减少冗余步骤")

        if report.worst_strategies:
            worst = report.worst_strategies[0]
            recommendations.append(f"策略'{worst['name']}'表现最差，建议替换或调整")

        return recommendations

    def _adjust_strategies(self, worst_strategies: list[dict]) -> int:
        """调整表现最差的策略"""
        adjusted = 0
        if not self._db:
            return adjusted

        for strategy in worst_strategies:
            success_rate = float(strategy["success_rate"].replace("%", ""))
            if success_rate < 30:
                # 成功率低于30%，归档策略
                with self._db.get_conn() as conn:
                    conn.execute(
                        "UPDATE strategies SET is_active=0 WHERE id=?",
                        (strategy["id"],),
                    )
                    conn.commit()
                adjusted += 1
                logger.info("strategy_archived", id=strategy["id"], name=strategy["name"])

        return adjusted


# ── 全局实例 ──

_evolution_engine: AgentEvolutionEngine | None = None


class EvolutionEngine(AgentEvolutionEngine):
    """EvolutionEngine 别名，保持向后兼容"""


def get_evolution_engine(db_conn=None) -> AgentEvolutionEngine:
    global _evolution_engine
    if _evolution_engine is None:
        _evolution_engine = AgentEvolutionEngine(db_conn)
    return _evolution_engine
