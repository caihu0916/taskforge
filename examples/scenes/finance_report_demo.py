
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-25: 示例场景 — 财务报表生成演示

数据链路: 场景脚本 → LLMRouter(双模式) → Ollama(本地) / SaaS(远程) → 报表

用法:
  # 本地模式 (需先启动 Ollama + ollama pull qwen2.5:7b)
  python examples/scenes/finance_report_demo.py

  # 远程模式 (需先配置 API Key)
  TF_REMOTE_AUTH_EMAIL=you@example.com TF_REMOTE_AUTH_PASSWORD=xxx \
    python examples/scenes/finance_report_demo.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将项目根目录加入 sys.path, 使 src.* 可导入
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.engine.llm._router_core import LLMRouter  # noqa: E402
from src.infra.config.settings import get_settings  # noqa: E402


async def generate_finance_report() -> dict:
    """生成示例财务报表 — 调用 LLMRouter 双模式分发"""
    router = LLMRouter()
    settings = get_settings()

    # 检测模式
    mode = await router._detect_mode()
    print(f"[模式检测] 当前 LLM 模式: {mode}")

    if mode == "unavailable":
        print("\n[引导] 无可用 LLM, 请选择以下任一方式:")
        print("  1. 安装 Ollama (本地免费): https://ollama.com/download")
        print("     然后: ollama pull qwen2.5:7b")
        print("  2. 配置 API Key (远程 SaaS): https://taskforge.cn/register")
        return {"error": "unavailable"}

    print(f"\n[调用] 使用 {mode} 模式生成财务报表...")

    # 调用 LLM 生成报表
    messages = [
        {
            "role": "system",
            "content": "你是财务分析师,擅长生成清晰的财务报表。",
        },
        {
            "role": "user",
            "content": (
                f"请为'{settings.app_name}'生成{__get_current_month()}财务报表,包含:\n"
                "1. 收入汇总 (假设总收入10万元)\n"
                "2. 成本分析 (假设总成本6万元)\n"
                "3. 毛利率计算\n"
                "4. 下月预测\n\n"
                "请用 Markdown 表格格式输出。"
            ),
        },
    ]

    try:
        result = await router.chat(
            messages,
            model=settings.llm.model or "qwen2.5:7b",
            temperature=0.3,
            max_tokens=2048,
        )
        return result
    except RuntimeError as e:
        print(f"[错误] LLM 调用失败: {e}")
        return {"error": str(e)}


def __get_current_month() -> str:
    """获取当前月份描述"""
    from datetime import datetime

    now = datetime.now()
    return f"{now.year}年{now.month}月"


async def main():
    """主入口"""
    print("=" * 60)
    print("TaskForge 开源版 — 财务报表生成演示")
    print("=" * 60)

    result = await generate_finance_report()

    if "error" not in result:
        print("\n" + "=" * 60)
        print("生成的财务报表:")
        print("=" * 60)
        print(result.get("content", "(空响应)"))
        print("\n" + "=" * 60)
        print(f"Provider: {result.get('provider', 'unknown')}")
        print(f"Model: {result.get('model', 'unknown')}")
        usage = result.get("usage", {})
        print(
            f"Token 使用: prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}"
        )
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
