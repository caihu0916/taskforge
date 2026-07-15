
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Template activation — materialize marketplace templates into runtime agents/workflows.

When a user "installs" a template, this module activates it:
  - AGENT/role templates → TemplateDrivenAgent registered in AgentRegistry
  - WORKFLOW templates → PDCA Workflow via create_workflow_from_template()
  - YAML templates → PDCA Workflow via template_builder
  - BUILTIN templates → no-op (already registered at startup)
  - COMMUNITY templates → dispatch by which fields are populated
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from src.engine.template_market.models import MarketplaceTemplate, SourceType

logger = structlog.get_logger(__name__)


# ── Activation Result ──────────────────────────────────────────────────


@dataclass
class ActivationResult:
    """Result of activating a template into the runtime."""

    success: bool
    resource_type: str = ""  # "agent" | "workflow" | "none"
    resource_id: str = ""    # agent_name or workflow_id
    error: str = ""


# ── TemplateDrivenAgent ────────────────────────────────────────────────


class TemplateDrivenAgent:
    """Lightweight agent materialized from a MarketplaceTemplate.

    Wraps LLM router with template's system_prompt/skills/config.
    Registered into AgentRegistry so it can be dispatched at runtime.
    """

    # SpecialistAgent protocol fields
    agent_name: str = ""
    agent_vibe: str = ""
    category: str = ""
    engine_module: str = ""

    def __init__(self, template: MarketplaceTemplate, cm: Any = None) -> None:
        config = template.config
        self._cm = cm
        self.agent_name = f"tpl-{template.id}"
        self.agent_vibe = config.get("system_prompt", template.description)[:200]
        self.category = template.category
        self.engine_module = "template_market"
        self._config = config
        self._skills = template.skills
        self._variables = template.variables

    def get_system_prompt(self) -> str:
        """Return the template's system prompt for LLM injection."""
        base = self._config.get("system_prompt", "")
        if not base:
            base = f"你是{self.agent_vibe}。"
        return base

    async def execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """Execute task via LLM router using template's config."""
        try:
            from src.engine.llm.provider_bootstrap import get_llm_router

            router = get_llm_router()
            messages = [
                {"role": "system", "content": self.get_system_prompt()},
                {"role": "user", "content": task},
            ]
            response = await router.chat(
                messages=messages,
                model=self._config.get("model", ""),
                temperature=float(self._config.get("temperature", 0.7)),
            )
            return {"success": True, "data": {"body": response}}
        except Exception as e:
            logger.warning("template_agent_execute_failed", agent=self.agent_name, error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_task(self, task: str, *, context: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """AgentExecutable protocol entry point."""
        return await self.execute(task, **(context or {}), **kwargs)

    def get_workflow(self, task: str = "") -> list[dict[str, str]]:
        """Return workflow steps from template skills."""
        return [
            {"name": s.get("name", ""), "step": s.get("prompt_template", "")}
            for s in self._skills
            if isinstance(s, dict)
        ]

    def get_rules(self) -> dict[str, Any]:
        """Return tools from template skills."""
        tool_ids: list[str] = []
        for s in self._skills:
            if isinstance(s, dict):
                tool_ids.extend(s.get("tool_ids", []))
        return {"tools": tool_ids}

    async def safe_execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """Safe execute wrapper (simplified, no DB recording for template agents)."""
        try:
            return await self.execute(task, **kwargs)
        except Exception as e:
            logger.exception("template_agent_safe_execute_failed", agent=self.agent_name)
            return {"success": False, "error": str(e), "agent": self.agent_name}


# ── TemplateActivator ──────────────────────────────────────────────────


class TemplateActivator:
    """Unified template → runtime activation engine."""

    def activate(self, template: MarketplaceTemplate) -> ActivationResult:
        """Activate an installed template into the runtime.

        Dispatches by source_type to the appropriate handler.
        """
        try:
            source = template.source_type
            if source == SourceType.WORKFLOW:
                return self._activate_workflow(template)
            if source in (SourceType.AGENT, SourceType.BUILTIN):
                return self._activate_agent(template)
            if source == SourceType.YAML:
                return self._activate_yaml(template)
            if source == SourceType.COMMUNITY:
                return self._activate_community(template)
            return ActivationResult(success=False, error=f"unknown source_type: {source}")
        except Exception as e:
            logger.exception("activation_failed", template_id=template.id, source_type=template.source_type)
            return ActivationResult(success=False, error=str(e))

    # ── WORKFLOW activation ─────────────────────────────────────────

    def _activate_workflow(self, template: MarketplaceTemplate) -> ActivationResult:
        """Create a PDCA workflow from template_library key or workflow_dsl."""
        # Path 1: workflow_dsl is populated → compile via DSL
        if template.workflow_dsl and len(template.workflow_dsl) > 0:
            return self._activate_workflow_from_dsl(template)

        # Path 2: source_id maps to template_library → create_workflow_from_template
        try:
            from src.engine.workflow.engine import get_pdca_engine
            from src.engine.workflow.template_library import create_workflow_from_template

            engine = get_pdca_engine()
            wf = create_workflow_from_template(
                engine,
                template.source_id,
                name=template.display_name,
                description=template.description,
            )
            logger.info("workflow_activated", template_id=template.id, workflow_id=wf.id)
            return ActivationResult(success=True, resource_type="workflow", resource_id=wf.id)
        except ImportError:
            logger.debug("workflow_engine_not_available")
            return ActivationResult(success=False, error="workflow engine not available")
        except Exception as e:
            logger.warning("workflow_activation_failed", template_id=template.id, error=str(e))
            return ActivationResult(success=False, error=str(e))

    def _activate_workflow_from_dsl(self, template: MarketplaceTemplate) -> ActivationResult:
        """Activate workflow from embedded workflow_dsl dict."""
        try:
            from src.engine.workflow.engine import get_pdca_engine
            from src.engine.workflow.models import Phase, PhaseType, Step

            engine = get_pdca_engine()

            # Convert workflow_dsl dict → Phase/Step list
            phases: list[Phase] = []
            dsl = template.workflow_dsl
            for phase_data in dsl.get("phases", []):
                steps = [
                    Step(
                        name=s.get("name", ""),
                        agent_role=s.get("agent_role", "general"),
                        action=s.get("action", ""),
                        params=s.get("params", {}),
                    )
                    for s in phase_data.get("steps", [])
                ]
                phases.append(
                    Phase(
                        phase_type=PhaseType(phase_data.get("type", "do")),
                        name=phase_data.get("name", ""),
                        steps=steps,
                    )
                )

            wf = engine.create_workflow(
                name=template.display_name,
                description=template.description,
                custom_phases=phases,
            )
            logger.info("workflow_dsl_activated", template_id=template.id, workflow_id=wf.id)
            return ActivationResult(success=True, resource_type="workflow", resource_id=wf.id)
        except Exception as e:
            logger.warning("workflow_dsl_activation_failed", template_id=template.id, error=str(e))
            return ActivationResult(success=False, error=str(e))

    # ── AGENT activation ────────────────────────────────────────────

    def _activate_agent(self, template: MarketplaceTemplate) -> ActivationResult:
        """Register a TemplateDrivenAgent into AgentRegistry."""
        try:
            from src.engine.agent.specialist_base import get_agent_registry

            registry = get_agent_registry()
            agent = TemplateDrivenAgent(template, cm=registry._cm)

            # Skip if already registered
            if registry.get(agent.agent_name):
                logger.debug("agent_already_registered", agent_name=agent.agent_name)
                return ActivationResult(success=True, resource_type="agent", resource_id=agent.agent_name)

            registry.register(agent)
            logger.info("agent_activated", template_id=template.id, agent_name=agent.agent_name)
            return ActivationResult(success=True, resource_type="agent", resource_id=agent.agent_name)
        except Exception as e:
            logger.warning("agent_activation_failed", template_id=template.id, error=str(e))
            return ActivationResult(success=False, error=str(e))

    # ── YAML activation ─────────────────────────────────────────────

    def _activate_yaml(self, template: MarketplaceTemplate) -> ActivationResult:
        """Activate YAML template as PDCA workflow (most useful path)."""
        try:
            from src.engine.workflow.engine import get_pdca_engine

            engine = get_pdca_engine()
            wf = engine.create_workflow(
                name=template.display_name,
                description=template.description,
                template_id=template.source_id,
            )
            logger.info("yaml_workflow_activated", template_id=template.id, workflow_id=wf.id)
            return ActivationResult(success=True, resource_type="workflow", resource_id=wf.id)
        except Exception as e:
            # Fallback: register as agent if workflow fails
            logger.debug("yaml_workflow_failed_trying_agent", error=str(e))
            return self._activate_agent(template)

    # ── COMMUNITY activation ────────────────────────────────────────

    def _activate_community(self, template: MarketplaceTemplate) -> ActivationResult:
        """Community templates: activate by which fields are populated."""
        if template.workflow_dsl and len(template.workflow_dsl) > 0:
            result = self._activate_workflow(template)
            if result.success:
                return result

        if template.config.get("system_prompt") or template.skills:
            return self._activate_agent(template)

        return ActivationResult(success=False, error="no activatable content in community template")

    # ── Reconciliation (multi-instance hot-plug sync) ──────────────

    def reconcile_from_db(self) -> dict[str, int]:
        """Scan DB for installed templates and sync AgentRegistry.

        Called at startup or periodically to handle multi-instance deploys
        where only one worker processed the install() API call.

        Returns {"activated": N, "skipped": N, "errors": N}
        """
        try:
            from src.engine.template_market.manager import get_template_market_manager

            mgr = get_template_market_manager()
        except Exception as e:
            logger.warning("reconcile_db_unavailable", error=str(e))
            return {"activated": 0, "skipped": 0, "errors": 0}

        # Find all installed templates that have activated_resource_id
        with mgr._cm.get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {mgr._safe_table()} "
                f"WHERE status = 'installed' AND activated_resource_type = 'agent' "
                f"AND activated_resource_id != ''"
            ).fetchall()

        stats = {"activated": 0, "skipped": 0, "errors": 0}

        try:
            from src.engine.agent.specialist_base import get_agent_registry

            registry = get_agent_registry()
        except Exception as e:
            logger.warning("reconcile_registry_unavailable", error=str(e))
            return stats

        for row in rows:
            try:
                tpl = mgr._row_to_model(row)
                agent_name = tpl.activated_resource_id

                # Already registered — skip
                if registry.get(agent_name):
                    stats["skipped"] += 1
                    continue

                # Register TemplateDrivenAgent from stored template
                agent = TemplateDrivenAgent(tpl, cm=registry._cm)
                registry.register(agent)
                stats["activated"] += 1
            except Exception as e:
                logger.warning("reconcile_item_failed", template_id=row[0], error=str(e))
                stats["errors"] += 1

        if stats["activated"] > 0:
            logger.info("reconcile_completed", **stats)

        return stats


# ── Singleton ──────────────────────────────────────────────────────────

_activator: TemplateActivator | None = None


def get_template_activator() -> TemplateActivator:
    global _activator
    if _activator is None:
        _activator = TemplateActivator()
    return _activator
