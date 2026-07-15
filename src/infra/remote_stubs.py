
# Copyright (c) 2024-2026 TaskForge Team
# SPDX-License-Identifier: BSL-1.1

"""P0-09: remote_stubs.py 框架 — 开源版连接 SaaS 服务端的桩函数基础

数据链路: secure_storage.retrieve → get_api_key → _sign_request → HTTP header

后续 P0-10..P0-15 在此框架上追加具体桩函数 (llm_chat/llm_stream/template_download/...)。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


def _sign_request(
    method: str,
    path: str,
    *,
    body: bytes | str = b"",
    secret: str,
) -> str:
    """P0-09: 对 HTTP 请求生成 HMAC-SHA256 签名

    Args:
        method: HTTP 方法 (GET/POST/...)
        path: 请求路径 (含 query string)
        body: 请求体 (bytes 或 str; str 按 utf-8 编码)
        secret: HMAC 密钥 (通常为 API Key)

    Returns:
        hex 签名字符串 (64 字符) — 与服务端验签对齐

    签名材料: METHOD\nPATH\nBODY (无尾随换行)
    """
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    material = f"{method.upper()}\n{path}\n".encode() + body_bytes
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def get_remote_client_config() -> dict[str, Any]:
    """P0-09: 获取远程 API httpx 客户端基础配置

    Returns:
        dict 含 base_url, timeout — 供桩函数复用, 避免重复读取配置
    """
    from config import get_settings

    settings = get_settings()
    return {
        "base_url": settings.remote.base_url,
        "timeout": settings.remote.timeout,
    }


# -----------------------------------------------------------------------------
# P0-10: remote_llm_chat — 远程 LLM 对话桩
# -----------------------------------------------------------------------------


async def remote_llm_chat(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> dict[str, Any]:
    """P0-10: 远程 LLM 对话桩 — 调用 SaaS 服务端 /api/v1/llm/chat

    数据链路: get_api_key → _sign_request → httpx.POST → 服务端 → 返回 data 字段

    Args:
        messages: OpenAI 格式消息列表
        model: 模型名 (空串则由服务端默认)
        temperature: 采样温度
        max_tokens: 最大生成 token 数
        **kwargs: 透传到请求 body 的额外参数

    Returns:
        服务端响应的 data 字段 (dict)

    Raises:
        RuntimeError: API Key 未配置 或 服务端返回非 200
    """
    from src.infra.secure_storage import get_api_key

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API Key 未配置 — 请先调用 remote_auth_login 登录")

    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        **kwargs,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign_request("POST", "/api/v1/llm/chat", body=body, secret=api_key)

    config = get_remote_client_config()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Signature": signature,
    }

    async with httpx.AsyncClient(
        base_url=config["base_url"],
        timeout=config["timeout"],
    ) as client:
        response = await client.post(
            "/api/v1/llm/chat",
            content=body,
            headers=headers,
        )
        if response.status_code != 200:
            raise RuntimeError(f"远程 LLM 调用失败: HTTP {response.status_code}")
        return response.json()["data"]


# -----------------------------------------------------------------------------
# P0-11: remote_llm_stream — 远程 LLM 流式桩 (SSE 代理)
# -----------------------------------------------------------------------------


async def remote_llm_stream(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    **kwargs: Any,
) -> AsyncIterator[str]:
    """P0-11: 远程 LLM 流式桩 — SSE 代理

    数据链路: get_api_key → _sign_request → httpx.stream → aiter_lines → 去前缀 → yield

    SSE 格式处理:
      - `data: <payload>` → yield <payload> (去掉 "data: " 前缀)
      - `: <comment>`     → 跳过 (keepalive 注释)
      - 空行             → 跳过

    Args:
        messages: OpenAI 格式消息列表
        model: 模型名
        **kwargs: 透传到请求 body 的额外参数

    Yields:
        str: SSE 数据块 (已去前缀)

    Raises:
        RuntimeError: API Key 未配置 或 服务端返回非 200
    """
    from src.infra.secure_storage import get_api_key

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API Key 未配置 — 请先调用 remote_auth_login 登录")

    payload = {"messages": messages, "model": model, **kwargs}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign_request("POST", "/api/v1/llm/stream", body=body, secret=api_key)

    config = get_remote_client_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-API-Key": api_key,
        "X-Signature": signature,
    }

    async with httpx.AsyncClient(
        base_url=config["base_url"],
        timeout=config["timeout"],
    ) as client, client.stream(
        "POST",
        "/api/v1/llm/stream",
        content=body,
        headers=headers,
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(
                f"远程 LLM 流式调用失败: HTTP {response.status_code}"
            )
        async for line in response.aiter_lines():
            if not line:
                continue
            if line.startswith(":"):
                continue  # SSE keepalive 注释
            if line.startswith("data: "):
                yield line[6:]
            elif line.startswith("data:"):
                yield line[5:]



# -----------------------------------------------------------------------------
# P0-12: remote_template_download — 模板下载桩
# -----------------------------------------------------------------------------


async def remote_template_download(template_id: str) -> dict[str, Any]:
    """P0-12: 远程模板下载桩 — GET /api/v1/templates/{template_id}/download

    数据链路: get_api_key → _sign_request → httpx.GET → 服务端 → 返回 data 字段
    """
    from src.infra.secure_storage import get_api_key

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API Key 未配置 — 请先调用 remote_auth_login 登录")

    path = f"/api/v1/templates/{template_id}/download"
    signature = _sign_request("GET", path, secret=api_key)

    config = get_remote_client_config()
    headers = {"X-API-Key": api_key, "X-Signature": signature}

    async with httpx.AsyncClient(
        base_url=config["base_url"], timeout=config["timeout"]
    ) as client:
        response = await client.get(path, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"远程模板下载失败: HTTP {response.status_code}")
        return response.json()["data"]


# -----------------------------------------------------------------------------
# P0-13: remote_auth_login — 登录桩 (返回 API Key 并持久化)
# -----------------------------------------------------------------------------


async def remote_auth_login(email: str, password: str) -> str:
    """P0-13: 远程登录桩 — POST /api/v1/auth/login, 返回 API Key 并持久化

    数据链路: POST email/password → 服务端签发 API Key → set_api_key 持久化 → 返回

    Args:
        email: 用户邮箱
        password: 用户密码

    Returns:
        服务端签发的 API Key 字符串

    Raises:
        RuntimeError: 服务端返回非 200
    """
    from src.infra.secure_storage import set_api_key

    payload = {"email": email, "password": password}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    config = get_remote_client_config()
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(
        base_url=config["base_url"], timeout=config["timeout"]
    ) as client:
        response = await client.post(
            "/api/v1/auth/login", content=body, headers=headers
        )
        if response.status_code != 200:
            raise RuntimeError(f"远程登录失败: HTTP {response.status_code}")
        api_key = response.json()["data"]["api_key"]

    set_api_key(api_key)  # 持久化到 secure_storage
    return api_key


# -----------------------------------------------------------------------------
# P0-14: remote_scene_execute — 场景执行桩
# -----------------------------------------------------------------------------


async def remote_scene_execute(
    scene_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """P0-14: 远程场景执行桩 — POST /api/v1/scenes/{scene_type}/execute

    数据链路: get_api_key → _sign_request → httpx.POST → 服务端 → 返回 data 字段
    """
    from src.infra.secure_storage import get_api_key

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API Key 未配置 — 请先调用 remote_auth_login 登录")

    path = f"/api/v1/scenes/{scene_type}/execute"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign_request("POST", path, body=body, secret=api_key)

    config = get_remote_client_config()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Signature": signature,
    }

    async with httpx.AsyncClient(
        base_url=config["base_url"], timeout=config["timeout"]
    ) as client:
        response = await client.post(path, content=body, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"远程场景执行失败: HTTP {response.status_code}")
        return response.json()["data"]


# -----------------------------------------------------------------------------
# P0-15: remote_usage_query — 用量查询桩
# -----------------------------------------------------------------------------


async def remote_usage_query() -> dict[str, Any]:
    """P0-15: 远程用量查询桩 — GET /api/v1/usage

    数据链路: get_api_key → _sign_request → httpx.GET → 服务端 → 返回 data 字段
    """
    from src.infra.secure_storage import get_api_key

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API Key 未配置 — 请先调用 remote_auth_login 登录")

    path = "/api/v1/usage"
    signature = _sign_request("GET", path, secret=api_key)

    config = get_remote_client_config()
    headers = {"X-API-Key": api_key, "X-Signature": signature}

    async with httpx.AsyncClient(
        base_url=config["base_url"], timeout=config["timeout"]
    ) as client:
        response = await client.get(path, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"远程用量查询失败: HTTP {response.status_code}")
        return response.json()["data"]
