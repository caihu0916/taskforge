
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Agent输出格式化管道"""

from __future__ import annotations

from .adapter import render_deliverable
from .router import OutputDecision, OutputFormat, route_output

__all__ = ["OutputDecision", "OutputFormat", "render_deliverable", "route_output"]
