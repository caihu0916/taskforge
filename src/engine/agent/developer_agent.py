
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""DeveloperAgent — write→test→iterate 开发循环 (WO-01 [P0])

继承 SpecialistAgent，实现自动化代码开发循环:
  1. Write: LLM 生成代码
  2. Test: 运行测试
  3. Iterate: 失败→根据错误修复→重试，最多3次
  4. 超3次 → 升级人工
"""

from __future__ import annotations

from typing import Any

import structlog

from src.engine.agent.specialist_base import SpecialistAgent

logger = structlog.get_logger(__name__)


class DeveloperAgent(SpecialistAgent):
    """代码开发Agent — write→test→iterate 循环"""

    agent_name = "developer"
    agent_vibe = "写代码→跑测试→修Bug，循环到通过"
    category = "development"

    def get_rules(self) -> dict[str, Any]:
        return {
            "max_iterations": 3,
            "tdd_required": True,
            "type_hints_required": True,
            "escalate_on_max_retries": True,
            "forbidden": ["skip_tests", "ignore_failures", "no_type_hints"],
        }

    def get_workflow(self, task: str) -> list[dict[str, str]]:
        return [
            {"phase": "write", "action": f"Write code for: {task}"},
            {"phase": "test", "action": "Run tests on generated code"},
            {"phase": "iterate", "action": "Fix failures and re-test (max 3x)"},
            {"phase": "deliver", "action": "Return final code or escalate"},
        ]

    async def execute(self, task: str, **kwargs) -> dict[str, Any]:
        """write→test→iterate 循环

        Args:
            task: 开发任务描述
            max_iterations: 最大迭代次数 (默认3)
        """
        max_iterations = kwargs.get("max_iterations", 3)
        iteration = 0
        results: list[dict] = []

        while iteration < max_iterations:
            iteration += 1
            logger.info("developer_iteration", task=task[:60], iteration=iteration)

            # Phase 1: Write code
            write_result = await self._write_code(task, iteration, results)
            if not write_result.get("success"):
                results.append({"iteration": iteration, "write": write_result, "test": None})
                continue

            # Phase 2: Run tests
            test_result = await self._run_tests(write_result)
            results.append({"iteration": iteration, "write": write_result, "test": test_result})

            # Phase 3: Check pass
            if test_result.get("passed", False):
                return {
                    "success": True,
                    "iterations": iteration,
                    "code": write_result.get("code", ""),
                    "test_output": test_result.get("output", ""),
                    "history": results,
                }

        # 超过 max_iterations，升级人工
        return {
            "success": False,
            "reason": "max_iterations_exceeded",
            "iterations": iteration,
            "history": results,
            "message": f"开发循环超过{max_iterations}次迭代，需人工介入",
        }

    async def _write_code(self, task: str, iteration: int, history: list[dict]) -> dict:
        """调用LLM生成代码"""
        try:
            from src.engine.llm.provider_bootstrap import get_llm_router
            from src.engine.llm.router_dispatch import get_smart_router

            # 注入前次失败信息
            history_context = ""
            if history:
                last = history[-1]
                if last.get("test") and not last["test"].get("passed"):
                    history_context = (
                        f"\n上次测试失败:\n{last['test'].get('output', '')[:500]}\n"
                        f"上次代码:\n{last.get('write', {}).get('code', '')[:500]}"
                    )

            prompt = (
                f"你是Python开发者。任务: {task}\n"
                f"第{iteration}次迭代。{history_context}\n"
                f"请输出可直接运行的Python代码。只输出代码，不要解释。"
            )

            smart = get_smart_router()
            routing = smart.route(message=prompt, agent_role="developer")
            router = get_llm_router()
            resp = await router.chat(
                [{"role": "user", "content": prompt}],
                provider=routing.provider,
                model=routing.model,
                max_tokens=2000,
            )
            code = resp.get("content", "") or resp.get("response", "") or str(resp)
            return {"success": bool(code), "code": code, "iteration": iteration}
        except Exception:
            logger.exception("developer_write_failed")
            return {"success": False, "error": "代码生成异常"}

    async def _run_tests(self, write_result: dict) -> dict:
        """运行测试 (通过 code_execute 或 pytest)"""
        code = write_result.get("code", "")
        if not code:
            return {"passed": False, "output": "No code to test"}

        try:
            # 提取代码中的测试或直接执行
            import os
            import subprocess
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(code)
                tmp_path = f.name

            try:
                proc = subprocess.run(
                    ["python", "-m", "pytest", tmp_path, "-v", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=os.path.dirname(tmp_path) or ".",
                    check=False,
                )
                passed = proc.returncode == 0
                output = proc.stdout[-2000:] or proc.stderr[-2000:]
                return {"passed": passed, "output": output, "returncode": proc.returncode}
            finally:
                os.unlink(tmp_path)
        except FileNotFoundError:
            return {"passed": False, "output": "Python not found"}
        except Exception:
            logger.exception("developer_test_failed")
            return {"passed": False, "output": "测试执行异常"}
