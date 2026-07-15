
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""工作流自动产出 — PDCA 完成→自动生成 PDF/Excel/PPT

解决: 工作流执行结束后, 自动将结果结构化输出, 用户零二次加工.

集成点: PDCAEngine 工作流完成时触发
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AutoOutputHook:
    """工作流自动产出钩子 — 工作流完成时自动生成成品"""

    OUTPUT_DIR = Path("data/output")

    def __init__(self) -> None:
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def on_workflow_completed(
        self, workflow_name: str, results: list[dict], output_formats: list[str] | None = None
    ) -> dict[str, str]:
        """工作流完成时调用 — 自动生成多格式输出

        Args:
            workflow_name: 工作流名称
            results: 步骤结果列表 [{"type": "...", "result": "..."}, ...]
            output_formats: 需要的输出格式 ["pdf", "xlsx", "pptx", "docx"]

        Returns:
            {format: file_path}
        """
        formats = output_formats or ["pdf"]
        outputs: dict[str, str] = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 聚合结果
        sections = self._results_to_sections(results)
        self._extract_summary(results)

        for fmt in formats:
            try:
                if fmt == "pdf":
                    from src.infra.output.pdf_engine import PDFGenerator

                    gen = PDFGenerator()
                    path = gen.generate_report(
                        title=f"{workflow_name} Report",
                        sections=sections,
                        output_path=str(self.OUTPUT_DIR / f"{workflow_name}_{timestamp}.pdf"),
                        subtitle=f"Auto-generated | {timestamp}",
                    )
                    outputs["pdf"] = path

                elif fmt == "xlsx":
                    from src.infra.output.xlsx_engine import XLSXGenerator

                    gen = XLSXGenerator()
                    path = gen.generate_workbook(
                        sheets=[
                            {
                                "name": "Results",
                                "headers": ["Step", "Type", "Result"],
                                "rows": [
                                    [r.get("type", ""), r.get("status", ""), str(r.get("result", ""))[:200]]
                                    for r in results
                                ],
                            }
                        ],
                        output_path=str(self.OUTPUT_DIR / f"{workflow_name}_{timestamp}.xlsx"),
                        title=workflow_name,
                    )
                    outputs["xlsx"] = path

                elif fmt == "pptx":
                    from src.infra.output.pptx_engine import PPTXGenerator

                    gen = PPTXGenerator()
                    slides = [
                        {"type": "content", "title": s.get("type", "Step"), "content": str(s.get("result", ""))[:500]}
                        for s in results[:10]
                    ]
                    path = gen.generate(
                        slides,
                        title=f"{workflow_name}",
                        output_path=str(self.OUTPUT_DIR / f"{workflow_name}_{timestamp}.pptx"),
                    )
                    outputs["pptx"] = path

                elif fmt == "docx":
                    from src.infra.output.docx_engine import DOCXGenerator

                    gen = DOCXGenerator()
                    context = {"title": workflow_name, "results": [str(r.get("result", "")) for r in results]}
                    path = gen.render_template(
                        "report_template.docx",
                        context,
                        output_path=str(self.OUTPUT_DIR / f"{workflow_name}_{timestamp}.docx"),
                    )
                    outputs["docx"] = path

                logger.info("auto_output_generated", workflow=workflow_name, format=fmt, path=outputs.get(fmt, ""))

            except Exception as e:
                logger.warning(
                    "auto_output_format_failed", workflow=workflow_name, format=fmt, error=str(e), exc_info=True
                )

        return outputs

    def _results_to_sections(self, results: list[dict]) -> list[dict[str, Any]]:
        sections = []
        for r in results:
            heading = r.get("type", "Step")
            content = str(r.get("result", ""))[:1000]
            if content:
                sections.append({"heading": heading, "content": content})
        return sections

    def _extract_summary(self, results: list[dict]) -> str:
        total = len(results)
        completed = sum(1 for r in results if r.get("status") == "completed")
        return f"Total steps: {total}, Completed: {completed}"
