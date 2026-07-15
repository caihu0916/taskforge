
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""D6-1: SOUL.md 系统提示覆盖 — 对标 Hermes ~/.hermes/SOUL.md

优先级: data/souls/{role}.md > data/souls/default.md > None
修改后 /reload 即可生效，无需重启。
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_SOUL_DIR = Path("data/souls")


def load_soul(role: str = "") -> str | None:
    """加载 SOUL.md 覆盖

    Args:
        role: Agent 角色名 (如 'butler')，空字符串 = 默认

    Returns:
        SOUL 文本内容，或 None
    """
    paths = []
    if role:
        paths.append(_SOUL_DIR / f"{role}.md")
    paths.append(_SOUL_DIR / "default.md")

    for p in paths:
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    logger.debug("soul_loaded", path=str(p), role=role)
                    return content
            except Exception as e:
                logger.warning("soul_load_failed", path=str(p), error=str(e), exc_info=True)

    return None
