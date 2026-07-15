
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""TaskForge SpecialistAgent 基类 + AgentRegistry 全局调度器

铁律: 每个Agent.execute()必须"一写二记"
  1. 一写: 写入业务表(contents/transactions/suppliers等)
  2. 二记: 记录agent_executions(可回溯)
  3. 计算型任务只记不写
  4. 异常不吞,不返回假数据
"""

from __future__ import annotations

import json
import uuid
from abc import abstractmethod
from datetime import datetime
from typing import Any

import structlog

from src.engine.agent.protocol import AgentExecutable, AgentExecutionResult
from src.infra.observability.tracer import get_tracer

logger = structlog.get_logger(__name__)


class SpecialistAgent(AgentExecutable):
    """专业Agent基类 — 连接agency-agents知识与TaskForge引擎"""

    agent_name: str = ""
    agent_vibe: str = ""
    category: str = ""  # marketing/finance/supply_chain/orchestration/operations
    engine_module: str = ""

    def __init__(self, cm: Any = None) -> None:
        self._cm = cm

    async def execute_task(
        self,
        task: str,
        *,
        context: dict[str, Any] | None = None,
        agent_role: str = "",
    ) -> AgentExecutionResult:
        """AgentExecutable 协议实现 — 委托给 execute()"""
        import time
        import uuid

        tracer = get_tracer()
        span_id = tracer.start_span("agent_execute", agent_role=self.agent_name)
        t0 = time.monotonic()
        try:
            result = await self.execute(task, context or {})
            elapsed = (time.monotonic() - t0) * 1000
            tracer.end_span(span_id, status="ok", latency_ms=int(elapsed))
            return AgentExecutionResult(
                success=result.get("success", False),
                data=result,
                agent_name=self.agent_name,
                execution_mode="direct",
                exec_id=result.get("exec_id", str(uuid.uuid4())[:8]),
                elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.debug("exception_handled", error=str(e))
            elapsed = (time.monotonic() - t0) * 1000
            tracer.end_span(span_id, status="error", error=str(e), latency_ms=int(elapsed), exc_info=True)
            return AgentExecutionResult(
                success=False,
                error=str(e),
                agent_name=self.agent_name,
                execution_mode="direct",
                elapsed_ms=elapsed,
            )

    def get_system_prompt(self) -> str:
        """返回注入LLM的专属系统提示词

        营销类Agent自动追加反AI味品味铁律(零额外LLM成本)
        """
        base = f"你是{self.agent_name}。{self.agent_vibe}"
        if self.category == "marketing":
            from src.engine.prompt.taste_rules import TASTE_INJECTION

            base += f"\n{TASTE_INJECTION}"
        return base

    @abstractmethod
    async def execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """执行专业任务 — 子类必须实现"""
        ...

    @abstractmethod
    def get_workflow(self, task: str) -> list[dict[str, str]]:
        """返回标准化工作流步骤"""
        ...

    @abstractmethod
    def get_rules(self) -> dict[str, Any]:
        """返回专业规范/禁忌/红线"""
        ...

    def _record_execution(
        self,
        exec_id: str,
        status: str,
        result: str = "",
        error: str = "",
        tokens: int = 0,
        task: str = "",
    ) -> None:
        from src.engine.agent.exec_helpers import record_execution

        record_execution(self._cm, self.agent_name, self.category, exec_id, status, result, error, tokens, task=task)

    async def safe_execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """安全执行包装: 自动记录agent_executions + WS广播 + 品味校验"""
        exec_id = str(uuid.uuid4())
        self._record_execution(exec_id, "running", task=task)
        try:
            result = await self.execute(task, **kwargs)

            # 品味校验（仅营销类Agent, 零LLM调用快速扫描）
            if self.category == "marketing" and result.get("success"):
                try:
                    from src.engine.agent.taste_audit import TasteAuditor

                    auditor = TasteAuditor()
                    body = (result.get("data") or {}).get("body", "")
                    if body:
                        taste = auditor.quick_scan(body)
                        if taste is not None:
                            if "data" not in result or not isinstance(result["data"], dict):
                                result["data"] = {}
                            result["data"]["taste_score"] = taste.score
                            result["data"]["taste_violations"] = taste.violations[:5]
                        else:
                            logger.warning("taste_audit_returned_none", agent=self.slug)
                except Exception as e:
                    logger.warning("taste_audit_failed", error=str(e), exc_info=True)

            self._record_execution(
                exec_id,
                "completed",
                result=json.dumps(result, ensure_ascii=False)[:4000],
                task=task,
            )
            self._ws_broadcast_execution(exec_id, "completed")

            # 写入SharedContextPool — 跨Agent共享产出（铁律: 一写二记扩展）
            try:
                from src.engine.context.shared_pool import get_shared_context_pool

                pool = get_shared_context_pool()
                output_text = json.dumps(result, ensure_ascii=False)[:2000]
                if output_text:
                    await pool.write(
                        agent_name=self.agent_name,
                        key=f"exec_{exec_id[:8]}",
                        content=output_text,
                        priority=2 if self.category == "marketing" else 1,
                        intent_tags=[self.category],
                    )
            except Exception as pool_err:
                logger.debug("shared_pool_write_skipped", error=str(pool_err), exc_info=True)

            return result
        except Exception as e:
            logger.exception("specialist_execution_failed", agent=self.agent_name)
            self._record_execution(exec_id, "failed", error=str(e)[:500], task=task)
            self._ws_broadcast_execution(exec_id, "failed", error=str(e)[:100])
            return {"success": False, "error": str(e), "agent": self.agent_name}

    def _ws_broadcast_execution(self, exec_id: str, status: str, error: str = "") -> None:
        from src.engine.agent.exec_helpers import ws_broadcast_execution

        ws_broadcast_execution(self.agent_name, self.category, exec_id, status, error)


class AgentRegistry:
    """全栈Agent注册与调度"""

    def __init__(self) -> None:
        self._agents: dict[str, SpecialistAgent] = {}
        self._cm: Any = None

    def set_cm(self, cm: Any) -> None:
        """启动后设置ConnectionManager，用于状态持久化"""
        self._cm = cm

    def register(self, agent: SpecialistAgent) -> None:
        self._agents[agent.agent_name] = agent
        logger.info("agent_registered", name=agent.agent_name, category=agent.category)

    def get(self, name: str) -> SpecialistAgent | None:
        return self._agents.get(name)

    def get_agent_status(self, agent_name: str) -> str:
        """获取Agent状态: enabled / stopped / disabled"""
        if not self._cm:
            return "enabled"
        try:
            with self._cm.get_conn() as conn:
                row = conn.execute(
                    "SELECT status FROM agent_status WHERE agent_name = ?",
                    (agent_name,),
                ).fetchone()
                return row["status"] if row else "enabled"
        except Exception as e:
            logger.warning("get_agent_status_failed", agent=agent_name, error=str(e), exc_info=True)
            return "enabled"

    def set_agent_status(self, agent_name: str, status: str, reason: str = "") -> None:
        """设置Agent状态，持久化到DB"""
        if not self._cm:
            return
        now = datetime.now().isoformat()
        try:
            with self._cm.get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO agent_status (agent_name, status, disabled_reason, disabled_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (agent_name, status, reason, now if status != "enabled" else "", now),
                )
                conn.commit()
            logger.info("agent_status_changed", agent=agent_name, status=status)
        except Exception as e:
            logger.warning("set_agent_status_failed", agent=agent_name, error=str(e), exc_info=True)

    def list_all(self) -> list[dict[str, str]]:
        return [
            {
                "name": a.agent_name,
                "vibe": a.agent_vibe,
                "category": a.category,
                "status": self.get_agent_status(a.agent_name),
            }
            for a in self._agents.values()
        ]

    def list_by_category(self, category: str) -> list[dict[str, str]]:
        return [
            {"name": a.agent_name, "vibe": a.agent_vibe, "status": self.get_agent_status(a.agent_name)}
            for a in self._agents.values()
            if a.category == category
        ]

    # Pipeline角色→实际Agent名称映射 (FIX-001: Pipeline死代码修复)
    _ROLE_TO_AGENT: dict[str, str] = {
        "researcher": "agency-content-strategy",
        "hitmaker": "agency-douyin",
        "compliance": "agency-orchestrator",
        "caster": "agency-xiaohongshu",
        "deal_hunter": "agency-cross-border",
        "accountant": "agency-bookkeeper",
        "support": "agency-studio-ops",
        "butler": "agency-studio-ops",
        "analyst": "agency-financial-analyst",
        "boss": "agency-orchestrator",
    }

    async def dispatch(self, agent_name: str, task: str, **kwargs: Any) -> dict[str, Any]:
        """调度到指定Agent执行任务 — 精确匹配→角色映射→失败"""
        agent = self._agents.get(agent_name)
        # FIX-001: 精确匹配失败时尝试角色映射
        if not agent:
            mapped = self._ROLE_TO_AGENT.get(agent_name)
            if mapped:
                agent = self._agents.get(mapped)
                if agent:
                    logger.info(
                        "pipeline_role_mapped",
                        role=agent_name,
                        agent=mapped,
                    )
        if not agent:
            return {"success": False, "error": f"Agent '{agent_name}' not found"}
        status = self.get_agent_status(agent_name)
        if status == "disabled":
            return {"success": False, "error": f"Agent '{agent_name}' is disabled"}
        if status == "stopped":
            return {"success": False, "error": f"Agent '{agent_name}' is stopped"}
        return await agent.safe_execute(task, **kwargs)


# ── 全局单例 ──

_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def register_all_agents(cm: Any = None) -> AgentRegistry:
    """注册所有专业Agent到全局Registry

    启动时在startup_hooks中调用此函数,
    传入ConnectionManager实例以启用DB写入.
    """
    registry = get_agent_registry()
    registry.set_cm(cm)

    # 营销师团
    from src.engine.marketing.platforms import (
        BaiduSeoAgent,
        BilibiliAgent,
        ContentStrategyAgent,
        CrossBorderAgent,
        DomesticEcomAgent,
        DouyinAgent,
        GrowthAgent,
        KuaishouAgent,
        LivestreamAgent,
        PrivateDomainAgent,
        SeoAgent,
        WechatOAAgent,
        WeiboAgent,
        XiaohongshuAgent,
        ZhihuAgent,
    )

    registry.register(XiaohongshuAgent(cm))
    registry.register(DouyinAgent(cm))
    registry.register(PrivateDomainAgent(cm))
    registry.register(WechatOAAgent(cm))
    registry.register(LivestreamAgent(cm))
    registry.register(WeiboAgent(cm))
    registry.register(BilibiliAgent(cm))
    registry.register(ZhihuAgent(cm))
    registry.register(KuaishouAgent(cm))
    registry.register(SeoAgent(cm))
    registry.register(BaiduSeoAgent(cm))
    registry.register(CrossBorderAgent(cm))
    registry.register(DomesticEcomAgent(cm))
    registry.register(GrowthAgent(cm))
    registry.register(ContentStrategyAgent(cm))

    from src.engine.agent.nexus_pipeline import NexusPipelineAgent
    from src.engine.butler.operations import OperationsAgent
    from src.engine.finance.financial_modeling import FinancialModelingAgent
    from src.engine.finance.month_end_close import MonthEndCloseAgent
    from src.engine.finance.tax_compliance import TaxComplianceAgent
    from src.engine.supply_chain.agent import SupplyChainAgent

    registry.register(MonthEndCloseAgent(cm))
    registry.register(TaxComplianceAgent(cm))
    registry.register(FinancialModelingAgent(cm))
    registry.register(SupplyChainAgent(cm))
    registry.register(NexusPipelineAgent(cm))
    registry.register(OperationsAgent(cm))

    logger.info(
        "all_agents_registered",
        total=len(registry._agents),
        agents=list(registry._agents.keys()),
    )
    return registry
