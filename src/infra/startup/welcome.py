
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-26: 首次启动引导 — 检测 LLM 模式并打印引导信息

数据链路: startup → welcome.show() → LLMRouter._detect_mode → 控制台输出

调用时机:
  - python app.py 启动时 (在 app_factory.create_app 之后)
  - 显示模式检测结果 + 注册链接
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 引导文案
_GUIDE_LOCAL = """
============================================================
 TaskForge 开源版 — 本地模式 (Ollama)
============================================================
 已检测到 Ollama 本地 LLM, 将使用免费本地模型。
 模型管理: https://ollama.com/library
============================================================
"""

_GUIDE_REMOTE = """
============================================================
 TaskForge 开源版 — 远程模式 (SaaS API)
============================================================
 已配置 API Key, 将使用 TaskForge SaaS 服务。
 控制台: https://taskforge.cn/dashboard
============================================================
"""

_GUIDE_UNAVAILABLE = """
============================================================
 TaskForge 开源版 — 无可用 LLM
============================================================
 请选择以下任一方式启用 LLM:

  1. 安装 Ollama (推荐, 本地免费):
     下载: https://ollama.com/download
     拉模型: ollama pull qwen2.5:7b

  2. 配置 API Key (远程 SaaS, 功能更强):
     注册: https://taskforge.cn/register
     登录: python -c "import asyncio; \\
              from src.infra.remote_stubs import remote_auth_login; \\
              asyncio.run(remote_auth_login('you@example.com', 'pwd'))"
============================================================
"""


async def show_welcome(router: Any = None) -> str:
    """检测 LLM 模式并打印引导信息

    Args:
        router: 可选的 LLMRouter 实例 (避免重复创建)

    Returns:
        检测到的模式: "local" / "remote" / "unavailable"
    """
    if router is None:
        from src.engine.llm._router_core import LLMRouter

        router = LLMRouter()

    mode = await router._detect_mode()

    if mode == "local":
        print(_GUIDE_LOCAL)
    elif mode == "remote":
        print(_GUIDE_REMOTE)
    else:
        print(_GUIDE_UNAVAILABLE)

    logger.info("welcome_shown", mode=mode)
    return mode


def show_welcome_sync() -> str:
    """同步版本的 show_welcome — 供 app.py 启动时调用"""
    return asyncio.run(show_welcome())


if __name__ == "__main__":
    # 直接运行: python -m src.infra.startup.welcome
    show_welcome_sync()
