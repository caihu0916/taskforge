
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""Async utility — 安全的 async-from-sync 桥接

解决审计 C-1: asyncio.run() 在运行中的事件循环内调用导致死锁。
对标 Claude Code anyio 统一异步层。

用法:
  from src.infra.async_utils import run_async
  result = run_async(some_async_function(arg1, arg2))
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import structlog

from src.exceptions import ToolError

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = structlog.get_logger(__name__)


def run_async(coro: Coroutine[Any, Any, Any], timeout: float = 30.0) -> Any:
    """安全地从同步上下文执行异步协程.

    如果当前没有事件循环在运行, 直接 asyncio.run()。
    如果有事件循环在运行 (例如在 async 函数中调用同步→异步), 则在新线程中运行。

    Args:
        coro: 要执行的异步协程
        timeout: 超时秒数

    Returns:
        协程的返回值

    Raises:
        TimeoutError: 超时
        Exception: 协程内部异常
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环 → 直接 run
        return asyncio.run(coro)

    # 有运行中的循环 → 在新线程中运行 (避免嵌套)
    result_container: list[Any] = []
    error_container: list[Exception] = []
    done = threading.Event()

    def _run_in_thread() -> None:
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_container.append(new_loop.run_until_complete(coro))
            finally:
                new_loop.close()
        except Exception as e:
            logger.warning("_run_in_thread_failed", error=str(e), exc_info=True)
            error_container.append(e)
        finally:
            done.set()

    thread = threading.Thread(target=_run_in_thread, daemon=True, name="run_async")
    thread.start()
    if not done.wait(timeout=timeout):
        raise TimeoutError(f"Async operation timed out after {timeout}s")

    if error_container:
        raise error_container[0]
    if not result_container:
        raise ToolError("Async operation returned no result")
    return result_container[0]
